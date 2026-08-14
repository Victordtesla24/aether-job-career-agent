"""S-FIX slice A — multi-user scheduled discovery + Adzuna scale guards.

Covers the two day-one blockers found by the S-AUDIT readiness sweep:

* **S-1** — the only scheduled discovery path served ONE hardcoded account, so
  every other paying subscriber got zero automatic job discovery. The fix is a
  server-side sweep (``POST /agents/discovery/sweep``, system-secret gated)
  that iterates every ENTITLED subscriber with a usable search target.
* **S-2** — ``AdzunaAdapter`` issued up to ``max_pages`` uncached live calls on
  every scout run against a 250-call/day key, with no daily budget accounting
  and no backoff when the key was exhausted. The fix is a shared response cache
  (mirroring the proven ``_BENCH_CACHE`` pattern), a daily budget ledger, and
  honest ``SourceBlockedError`` states on quota exhaustion / HTTP 429.
* **S-7 (partial)** — a per-user sliding-window cooldown on the manual scout
  Sync so one user cannot burn the shared Adzuna budget by click-spamming.

No live HTTP anywhere: ``fetch_json`` is monkeypatched per test.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _adzuna_env(monkeypatch):
    """Credentialed Adzuna + clean module state for every case."""
    from app.services.discovery import adzuna_adapter

    # These cases exercise the LIVE fetch path with ``fetch_json`` stubbed, so
    # the suite-wide fixture mode (which short-circuits ``_fetch_live``) is off
    # here. No real HTTP happens: every case patches ``fetch_json`` first.
    monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)
    monkeypatch.setenv("ADZUNA_APP_ID", "test-app-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-app-key")
    monkeypatch.setenv("AETHER_ADZUNA_MAX_PAGES", "2")
    monkeypatch.setenv("AETHER_ADZUNA_RESULTS_PER_PAGE", "2")
    adzuna_adapter.reset_scale_state()
    yield
    adzuna_adapter.reset_scale_state()


def _page(n: int) -> dict[str, Any]:
    return {
        "results": [
            {
                "title": f"Delivery Lead {n}{i}",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Melbourne"},
                "description": "Delivery lead role, agile programs.",
                "redirect_url": f"https://www.adzuna.com.au/details/{n}{i}",
                "created": "2026-08-10T00:00:00Z",
            }
            for i in range(2)
        ]
    }


def _counting_fetch(monkeypatch, *, error=None):
    """Patch ``fetch_json`` with a call-counting stub; returns the counter list."""
    from app.services.discovery import adzuna_adapter

    calls: list[str] = []

    def _fake(url: str, timeout: int = 10):
        calls.append(url)
        if error is not None:
            raise error
        return _page(len(calls))

    monkeypatch.setattr(adzuna_adapter, "fetch_json", _fake)
    return calls


class TestAdzunaSharedCache:
    def test_overlapping_user_searches_share_one_set_of_api_calls(
        self, monkeypatch
    ):
        """S-2: two users searching the same thing must not double the calls."""
        from app.services.discovery.adzuna_adapter import AdzunaAdapter

        calls = _counting_fetch(monkeypatch)
        first = AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        after_first = len(calls)
        assert after_first >= 1
        # A DIFFERENT adapter instance (a different user's scout run) with the
        # same normalized target must be served entirely from the shared cache.
        second = AdzunaAdapter().fetch(query="Delivery Lead ", location=" melbourne")
        assert len(calls) == after_first, "second identical search re-hit the API"
        assert [j["sourceUrl"] for j in second] == [j["sourceUrl"] for j in first]

    def test_expired_cache_entry_refetches(self, monkeypatch):
        from app.services.discovery.adzuna_adapter import AdzunaAdapter

        monkeypatch.setenv("AETHER_ADZUNA_CACHE_TTL_SECONDS", "0")
        calls = _counting_fetch(monkeypatch)
        AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        after_first = len(calls)
        AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        assert len(calls) > after_first, "TTL=0 must not serve a cached page"


class TestAdzunaDailyBudget:
    def test_budget_is_counted_and_exhausts(self, monkeypatch):
        from app.services.discovery import adzuna_adapter
        from app.services.discovery.adzuna_adapter import AdzunaAdapter

        monkeypatch.setenv("AETHER_ADZUNA_DAILY_BUDGET", "2")
        monkeypatch.setenv("AETHER_ADZUNA_BUDGET_SAFETY_MARGIN", "0")
        calls = _counting_fetch(monkeypatch)
        AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        snapshot = adzuna_adapter.budget_snapshot()
        assert snapshot["used"] == len(calls)
        assert snapshot["budget"] == 2
        assert snapshot["remaining"] == 2 - len(calls)

    def test_exhausted_budget_serves_stale_cache_never_empty(self, monkeypatch):
        """At budget the adapter serves the cached listings, honestly stamped."""
        from app.services.discovery import adzuna_adapter
        from app.services.discovery.adzuna_adapter import AdzunaAdapter

        monkeypatch.setenv("AETHER_ADZUNA_DAILY_BUDGET", "2")
        monkeypatch.setenv("AETHER_ADZUNA_BUDGET_SAFETY_MARGIN", "0")
        calls = _counting_fetch(monkeypatch)
        first = AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        spent = len(calls)
        assert spent >= 1 and first
        # Age the cache past its TTL AND exhaust the day's budget.
        monkeypatch.setenv("AETHER_ADZUNA_CACHE_TTL_SECONDS", "0")
        adzuna_adapter._CALL_LEDGER[adzuna_adapter._today_key()] = 999

        served = AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        assert len(calls) == spent, "budget-exhausted path issued a live call"
        assert served, "budget-exhausted path returned EMPTY instead of cache"
        assert adzuna_adapter.budget_snapshot()["exhausted"] is True

    def test_exhausted_budget_without_cache_is_blocked_not_empty(self, monkeypatch):
        from app.services.discovery import adzuna_adapter
        from app.services.discovery.adzuna_adapter import AdzunaAdapter
        from app.services.discovery.base_adapter import SourceBlockedError

        calls = _counting_fetch(monkeypatch)
        adzuna_adapter._CALL_LEDGER[adzuna_adapter._today_key()] = 999
        with pytest.raises(SourceBlockedError) as excinfo:
            AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        assert not calls, "blocked path still called the API"
        message = str(excinfo.value).lower()
        assert "quota" in message or "budget" in message
        assert "utc" in message, "block message must say when the quota resets"


class TestAdzunaRateLimitBackoff:
    def test_http_429_becomes_source_blocked_with_retry_after(self, monkeypatch):
        import urllib.error

        from app.services.discovery.adzuna_adapter import AdzunaAdapter
        from app.services.discovery.base_adapter import SourceBlockedError

        err = urllib.error.HTTPError(
            "https://api.adzuna.com", 429, "Too Many Requests",
            {"Retry-After": "42"}, None,  # type: ignore[arg-type]
        )
        calls = _counting_fetch(monkeypatch, error=err)
        with pytest.raises(SourceBlockedError) as excinfo:
            AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        assert "42" in str(excinfo.value)
        spent = len(calls)

        # The cooldown must hold: the next run does NOT re-hit the API.
        with pytest.raises(SourceBlockedError):
            AdzunaAdapter().fetch(query="delivery lead", location="Melbourne")
        assert len(calls) == spent, "429 cooldown did not suppress the retry"


class TestScoutSyncCooldown:
    def test_rapid_manual_syncs_get_an_honest_429(self, client, auth_headers):
        """S-7: per-user sliding-window cooldown on the manual Sync button."""
        client.app.state.scout_rate_limiter.max_calls = 2
        body = {"query": "delivery lead", "location": "Melbourne"}
        seen: list[int] = []
        for _ in range(3):
            seen.append(client.post("/agents/scout/run", json=body, headers=auth_headers).status_code)
        assert 429 in seen, f"no cooldown fired: {seen}"
        blocked = client.post("/agents/scout/run", json=body, headers=auth_headers)
        assert blocked.status_code == 429
        detail = blocked.json()["detail"]
        assert detail["error"] == "scout_cooldown"
        assert detail["retryAfterSeconds"] > 0
        assert "sync" in detail["message"].lower()
        assert blocked.headers.get("Retry-After")


class TestDiscoverySweep:
    def _seed_entitled_user(self, email: str) -> str:
        from app.db import get_connection
        from app.repositories.billing import _ensure_billing_tables

        _ensure_billing_tables()
        user_id = str(uuid.uuid4())
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "User" ("id","email","name","passwordHash",'
                    '"targetRole","location","updatedAt") '
                    'VALUES (%s,%s,%s,%s,%s,%s,now())',
                    (user_id, email, "Sweep User", "x", "Delivery Lead", "Melbourne, AU"),
                )
                cur.execute(
                    'INSERT INTO "Subscription" ("id","userId","planId","status")'
                    ' VALUES (%s,%s,%s,%s)',
                    (str(uuid.uuid4()), user_id, "pro", "active"),
                )
            conn.commit()
        return user_id

    def test_sweep_requires_the_system_secret(self, client, monkeypatch):
        monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", "s3cret")
        assert client.post("/agents/discovery/sweep").status_code == 401
        assert client.post(
            "/agents/discovery/sweep", headers={"X-Aether-System-Run": "wrong"}
        ).status_code == 401

    def test_sweep_runs_discovery_for_every_entitled_subscriber(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", "s3cret")
        monkeypatch.setenv("AETHER_DISCOVERY_SWEEP_SPACING_SECONDS", "0")
        a = self._seed_entitled_user(f"sweep-a-{uuid.uuid4().hex[:6]}@example.com")
        b = self._seed_entitled_user(f"sweep-b-{uuid.uuid4().hex[:6]}@example.com")

        ran: list[tuple[str, str]] = []

        from app.routers import agents as agents_router

        def _fake_dispatch(user_id, agent_name, params, **kwargs):
            ran.append((user_id, agent_name))
            assert kwargs.get("system_run") is True
            return {"persisted": 1, "updated": 0, "errors": [], "scored": 1,
                    "per_source": []}

        monkeypatch.setattr(agents_router, "_dispatch", _fake_dispatch)
        resp = client.post(
            "/agents/discovery/sweep", headers={"X-Aether-System-Run": "s3cret"}
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        swept = {row["userId"] for row in payload["users"]}
        assert {a, b} <= swept, payload
        assert ("scout" in {n for _, n in ran}) and ("fitScorer" in {n for _, n in ran})
        assert payload["sweptUsers"] == len(payload["users"])

    def test_sweep_reports_a_failing_user_without_aborting_the_rest(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", "s3cret")
        monkeypatch.setenv("AETHER_DISCOVERY_SWEEP_SPACING_SECONDS", "0")
        a = self._seed_entitled_user(f"sweep-c-{uuid.uuid4().hex[:6]}@example.com")
        b = self._seed_entitled_user(f"sweep-d-{uuid.uuid4().hex[:6]}@example.com")

        from app.routers import agents as agents_router

        def _fake_dispatch(user_id, agent_name, params, **kwargs):
            if user_id == a and agent_name == "scout":
                raise RuntimeError("adzuna down")
            return {"persisted": 0, "updated": 0, "errors": [], "scored": 0,
                    "per_source": []}

        monkeypatch.setattr(agents_router, "_dispatch", _fake_dispatch)
        resp = client.post(
            "/agents/discovery/sweep", headers={"X-Aether-System-Run": "s3cret"}
        )
        assert resp.status_code == 200, resp.text
        rows = {row["userId"]: row for row in resp.json()["users"]}
        assert rows[a]["status"] == "error"
        assert "adzuna down" in rows[a]["error"]
        assert rows[b]["status"] == "ok"
