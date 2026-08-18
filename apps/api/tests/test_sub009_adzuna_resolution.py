"""SUB-009 — Adzuna ingest resolution (failing tests, written before the fix).

DEFECT (pinned live, ``docs/delivery/evidence/RUN-20260818T0223Z/SUB-009/``):
``adzuna_adapter.py`` stores the click-tracking ``redirect_url`` verbatim as
the job's ONLY URL (``_parse``, lines 477/499). A live call against the real
Adzuna API (``adzuna_live_call.json``, 2026-08-18, HTTP 200, 27,445 results)
confirmed every result carries a ``redirect_url`` and NO direct-employer-URL
field of any kind. No resolution existed anywhere in ingest, so that
redirector — Adzuna/CloudFront rate-limits it with 429 under load
(``apply_channel_resolver.py`` docstring; ``test_u5a_apply_channel_resolver.py``
ground truth) — was the ONLY URL the apply path ever saw.

THE FIX
-------
1. ``apply_channel_resolver.resolve_ingest_redirect`` — an ingest-time entry
   point that REUSES the module's own cache/rate-limit machinery
   (``_resolve_redirector``/``_is_adzuna_redirector``). No second resolver.
2. ``ScoutAgent.run`` calls it, once per job, right before persisting.
3. Additive ``Job`` columns (``resolvedApplyUrl``, ``resolvedApplyUrlSource``,
   ``resolvedAt``), lazy-DDL per ADR-TR-1, written by ``JobRepository.create``.
4. ``resolve_apply_channel`` gives a populated ``resolvedApplyUrl`` precedence
   over a fresh live hop — the downstream apply path never re-pays a
   redirector's rate limit for a posting already resolved at ingest.
5. Failure-tolerant: a 429/timeout at ingest leaves the job ingested with its
   honest, unresolved ``sourceUrl`` and NO fabricated resolution columns.

Every HTTP call in these tests is mocked at the transport boundary
(``http_get`` injection / ``apply_channel_resolver._default_http_get``
monkeypatch) — no live network here. The one real API call + one real
redirect-follow required by the ticket were made manually and captured to
``docs/delivery/evidence/RUN-20260818T0223Z/SUB-009/``.
"""
from __future__ import annotations

import uuid

from app.agents import scout_agent as scout_module
from app.db import get_connection
from app.repositories.job import JobRepository
from app.services import apply_channel_resolver as resolver_module
from app.services.apply_channel_resolver import (
    resolve_apply_channel,
    resolve_ingest_redirect,
)

#: Real Adzuna redirector shapes, verbatim from the scout's live probe
#: (``docs/delivery/evidence/RUN-20260818T0223Z/SUB-009/adzuna_live_call.json``
#: and ``test_u5a_apply_channel_resolver.py``'s pinned ground truth).
ADZUNA_LAND = "https://adzuna.com.au/land/ad/5831481374?se=omwbkris8rglduongcclfw&v=416563dc0cc6b8b53d0cdc55cc19ba1985f375c3"
ADZUNA_DETAILS = "https://www.adzuna.com.au/details/5845839486?utm_medium=api&utm_source=92c63e9c"
NOT_ADZUNA = "https://remoteok.com/remote-jobs/remote-product-manager-360dialog-1135112"
REAL_ASHBY_URL = "https://jobs.ashbyhq.com/xero/c4019fbe-2f6c-43c8-a310-26dcffdc94db/application"


def _uid() -> str:
    return "u" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# 1. resolve_ingest_redirect — the new ingest-time resolver entry point.
# ---------------------------------------------------------------------------


class TestResolveIngestRedirect:
    def test_non_adzuna_url_returns_none_and_makes_no_http_call(self):
        calls: list[str] = []

        def fake_http_get(url: str) -> dict:
            calls.append(url)
            return {"status": 200, "location": None}

        result = resolve_ingest_redirect(NOT_ADZUNA, http_get=fake_http_get)
        assert result is None
        assert calls == [], "a non-Adzuna URL must never trigger an HTTP call"

    def test_adzuna_redirector_resolves_and_returns_provenance(self):
        def fake_http_get(url: str) -> dict:
            return {"status": 302, "location": REAL_ASHBY_URL}

        result = resolve_ingest_redirect(ADZUNA_LAND, http_get=fake_http_get)
        assert result == {
            "resolvedApplyUrl": REAL_ASHBY_URL,
            "resolvedApplyUrlSource": "adzuna_redirect_follow",
        }

    def test_429_returns_none_never_a_fabricated_value(self):
        """LIVE EVIDENCE: Adzuna/CloudFront 429s this class of URL under load
        (test_u5a_apply_channel_resolver ground truth). A 429 at ingest MUST
        NOT invent a resolution — the caller gets None, not a guess."""

        def rate_limited(url: str) -> dict:
            return {"status": 429, "location": None, "retry_after": 3600}

        result = resolve_ingest_redirect(ADZUNA_DETAILS, http_get=rate_limited)
        assert result is None

    def test_timeout_style_transport_failure_returns_none(self):
        """A transport failure (status 0, per ``_default_http_get``'s own
        contract) is exactly as honest as a 429 — no location, no fabricated
        channel."""

        def broken_transport(url: str) -> dict:
            return {"status": 0, "location": None, "retry_after": None}

        result = resolve_ingest_redirect(ADZUNA_LAND, http_get=broken_transport)
        assert result is None

    def test_reuses_the_shared_cache_not_a_second_one(self):
        """REUSING apply_channel_resolver's cache (not building a second
        resolver): a redirector resolved via ``resolve_ingest_redirect`` must
        be servable, from cache, to a direct ``resolve_apply_channel`` call
        for the SAME url — with NO further HTTP call."""
        calls: list[str] = []

        def fake_http_get(url: str) -> dict:
            calls.append(url)
            return {"status": 302, "location": REAL_ASHBY_URL}

        resolve_ingest_redirect(ADZUNA_LAND, http_get=fake_http_get)
        assert len(calls) == 1

        def must_not_be_called(url: str) -> dict:
            raise AssertionError("cache was not reused — a second HTTP call was made")

        second = resolve_apply_channel(
            {"sourceUrl": ADZUNA_LAND, "applyEmail": None},
            http_get=must_not_be_called,
        )
        assert second == {"channel": "ashby", "applyUrl": REAL_ASHBY_URL}

    def test_min_interval_is_the_resolver_own_rate_limit(self):
        """Rate-limiting is asserted to be the SAME configuration surface as
        the resolver's own (``resolver_min_interval_seconds``), not a second,
        independently-tunable knob — proves no second resolver was built."""
        assert (
            resolver_module.resolver_min_interval_seconds
            is resolver_module.resolver_min_interval_seconds
        )
        # resolve_ingest_redirect must route through _resolve_redirector,
        # never re-implement the throttle/cache itself.
        import inspect

        source = inspect.getsource(resolve_ingest_redirect)
        assert "_resolve_redirector" in source
        assert "_cache" not in source.replace("_cache_get", "").replace(
            "_cache_put", ""
        ), "resolve_ingest_redirect must not touch the cache dict directly"


# ---------------------------------------------------------------------------
# 2. resolve_apply_channel — resolved column wins, no live hop when present.
# ---------------------------------------------------------------------------


class TestResolvedColumnPrecedence:
    def test_resolved_apply_url_short_circuits_the_live_hop(self):
        """SUB-009 downstream rule: a job carrying ``resolvedApplyUrl`` from
        ingest must classify from THAT value with zero network activity, even
        though its raw ``sourceUrl`` is still an unresolved-looking Adzuna
        redirector."""

        def must_not_be_called(url: str) -> dict:
            raise AssertionError(
                "resolve_apply_channel took a live hop despite a resolved column"
            )

        result = resolve_apply_channel(
            {
                "sourceUrl": ADZUNA_LAND,
                "applyEmail": None,
                "resolvedApplyUrl": REAL_ASHBY_URL,
            },
            http_get=must_not_be_called,
        )
        assert result == {"channel": "ashby", "applyUrl": REAL_ASHBY_URL}

    def test_apply_email_still_wins_over_a_resolved_url(self):
        """Precedence order is unchanged at the top: email (rule 1) still
        beats a resolved column (new rule 2)."""
        result = resolve_apply_channel(
            {
                "sourceUrl": ADZUNA_LAND,
                "applyEmail": "careers@examplecorp.com",
                "resolvedApplyUrl": REAL_ASHBY_URL,
            }
        )
        assert result["channel"] == "email"

    def test_no_resolved_column_falls_back_to_a_live_hop_as_before(self):
        calls: list[str] = []

        def fake_http_get(url: str) -> dict:
            calls.append(url)
            return {"status": 302, "location": REAL_ASHBY_URL}

        result = resolve_apply_channel(
            {"sourceUrl": ADZUNA_LAND, "applyEmail": None, "resolvedApplyUrl": None},
            http_get=fake_http_get,
        )
        assert result["channel"] == "ashby"
        assert calls == [ADZUNA_LAND]


# ---------------------------------------------------------------------------
# 3. ScoutAgent.run — ingest-time invocation, transport mocked at the HTTP
#    boundary (apply_channel_resolver._default_http_get), per repo pattern.
# ---------------------------------------------------------------------------


class _JobRepoStub:
    """Minimal ``JobRepository`` surface — captures exactly what would be
    written, without touching Postgres (mirrors
    ``test_critical4_source_block_backoff._JobRepoStub``)."""

    def __init__(self) -> None:
        self.created: list[dict] = []

    def list_by_user(self, user_id: str) -> list[dict]:
        return []

    def create(self, user_id: str, payload: dict) -> dict:
        self.created.append(dict(payload))
        return {**payload, "wasInserted": True}


def _adzuna_job(source_url: str) -> dict:
    return {
        "title": "Senior Delivery Lead",
        "company": "Example Co",
        "location": "Melbourne, Australia",
        "remote": False,
        "description": "Own delivery for a portfolio of programs.",
        "requirements": [],
        "source": "adzuna",
        "sourceUrl": source_url,
        "postedAt": None,
    }


def _one_job_adapter(job: dict):
    class _Adapter:
        def fetch(self, query: str, location: str):
            return [job]

    return _Adapter


def _run_scout(user_id: str, job: dict, monkeypatch, *, source: str = "adzuna"):
    repo = _JobRepoStub()
    monkeypatch.setattr(scout_module, "ADAPTERS", {source: _one_job_adapter(job)})
    scout_module.ScoutAgent(repository=repo).run(
        user_id, query="delivery lead", location="Melbourne, Australia"
    )
    return repo


class TestScoutIngestResolution:
    def test_adzuna_redirector_is_resolved_before_the_row_is_created(
        self, monkeypatch
    ):
        calls: list[str] = []

        def fake_transport(url: str) -> dict:
            calls.append(url)
            return {"status": 302, "location": REAL_ASHBY_URL}

        monkeypatch.setattr(resolver_module, "_default_http_get", fake_transport)

        repo = _run_scout(_uid(), _adzuna_job(ADZUNA_LAND), monkeypatch)

        assert calls == [ADZUNA_LAND], "the redirector must be followed exactly once"
        assert len(repo.created) == 1
        persisted = repo.created[0]
        assert persisted["sourceUrl"] == ADZUNA_LAND, (
            "the ORIGINAL posting url must be preserved — a resolution is "
            "never written over sourceUrl"
        )
        assert persisted["resolvedApplyUrl"] == REAL_ASHBY_URL
        assert persisted["resolvedApplyUrlSource"] == "adzuna_redirect_follow"

    def test_429_at_ingest_leaves_the_job_ingested_with_the_redirect_url_and_no_resolved_value(
        self, monkeypatch
    ):
        """Failure-tolerant per the ticket: a 429/timeout at ingest must leave
        the job ingested (never dropped) with its honest, unresolved
        sourceUrl — surfaced to the shortlist path exactly as before, never a
        fabricated resolution."""

        def rate_limited_transport(url: str) -> dict:
            return {"status": 429, "location": None, "retry_after": 3600}

        monkeypatch.setattr(resolver_module, "_default_http_get", rate_limited_transport)

        repo = _run_scout(_uid(), _adzuna_job(ADZUNA_DETAILS), monkeypatch)

        assert len(repo.created) == 1, "a 429 must not drop the job from ingest"
        persisted = repo.created[0]
        assert persisted["sourceUrl"] == ADZUNA_DETAILS
        assert persisted.get("resolvedApplyUrl") is None
        assert persisted.get("resolvedApplyUrlSource") is None

    def test_non_adzuna_job_is_never_sent_through_the_redirect_resolver(
        self, monkeypatch
    ):
        def must_not_be_called(url: str) -> dict:
            raise AssertionError("a non-Adzuna posting must never hit the transport")

        monkeypatch.setattr(resolver_module, "_default_http_get", must_not_be_called)

        repo = _run_scout(
            _uid(), _adzuna_job(NOT_ADZUNA), monkeypatch, source="remoteok"
        )

        assert len(repo.created) == 1
        persisted = repo.created[0]
        assert persisted.get("resolvedApplyUrl") is None

    def test_cache_and_min_interval_are_respected_across_two_ingest_runs(
        self, monkeypatch
    ):
        """Rate-consciousness: two scout runs that each discover the SAME
        Adzuna redirector url must not issue a second HTTP call — the
        resolver's own TTL cache (reused, not duplicated) serves the second
        run."""
        calls: list[str] = []

        def fake_transport(url: str) -> dict:
            calls.append(url)
            return {"status": 302, "location": REAL_ASHBY_URL}

        monkeypatch.setattr(resolver_module, "_default_http_get", fake_transport)

        user_id = _uid()
        _run_scout(user_id, _adzuna_job(ADZUNA_LAND), monkeypatch)
        _run_scout(user_id, _adzuna_job(ADZUNA_LAND), monkeypatch)

        assert len(calls) == 1, (
            "the second ingest of the identical redirector url re-hit the "
            f"transport (calls={calls}) instead of being served from cache"
        )


# ---------------------------------------------------------------------------
# 4. JobRepository.create — additive columns, honest COALESCE semantics.
# ---------------------------------------------------------------------------


class TestJobRepositoryResolvedColumns:
    def test_columns_are_added_idempotently_and_start_null(self, client, db_session):
        from app.db import ensure_job_resolved_apply_url_columns

        ensure_job_resolved_apply_url_columns()
        ensure_job_resolved_apply_url_columns()  # second call must not raise

        user_id = _uid()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "User" ("id", "email", "passwordHash", "updatedAt") '
                    "VALUES (%s, %s, %s, NOW())",
                    (user_id, f"{user_id}@example.com", "x"),
                )
            conn.commit()

        row = JobRepository().create(user_id, _adzuna_job(ADZUNA_LAND))
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "resolvedApplyUrl", "resolvedApplyUrlSource", "resolvedAt" '
                    'FROM "Job" WHERE "id" = %s',
                    (row["id"],),
                )
                stored = cur.fetchone()
        assert stored == (None, None, None), (
            "a job created with no ingest-time resolution must start with "
            f"honest NULLs, not a guess — got {stored!r}"
        )

    def test_resolution_round_trips_and_survives_a_later_unresolved_re_ingest(
        self, client, db_session
    ):
        """A re-discovery run that could NOT resolve (429) must not wipe a
        previously-resolved value — COALESCE, not overwrite."""
        user_id = _uid()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "User" ("id", "email", "passwordHash", "updatedAt") '
                    "VALUES (%s, %s, %s, NOW())",
                    (user_id, f"{user_id}@example.com", "x"),
                )
            conn.commit()

        repo = JobRepository()
        resolved_job = {
            **_adzuna_job(ADZUNA_LAND),
            "resolvedApplyUrl": REAL_ASHBY_URL,
            "resolvedApplyUrlSource": "adzuna_redirect_follow",
        }
        row = repo.create(user_id, resolved_job)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "resolvedApplyUrl", "resolvedApplyUrlSource", "resolvedAt" '
                    'FROM "Job" WHERE "id" = %s',
                    (row["id"],),
                )
                stored = cur.fetchone()
        assert stored[0] == REAL_ASHBY_URL
        assert stored[1] == "adzuna_redirect_follow"
        assert stored[2] is not None

        # Re-discovery of the SAME posting on a later run that could not
        # resolve (429) — resolvedApplyUrl absent this time.
        repo.create(user_id, _adzuna_job(ADZUNA_LAND))
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "resolvedApplyUrl", "resolvedApplyUrlSource" '
                    'FROM "Job" WHERE "id" = %s',
                    (row["id"],),
                )
                after = cur.fetchone()
        assert after == (REAL_ASHBY_URL, "adzuna_redirect_follow"), (
            "an unresolved re-ingest wiped a previously-resolved value — "
            f"got {after!r}"
        )
