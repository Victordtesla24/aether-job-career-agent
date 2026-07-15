"""GAP-SRC-001 + GAP-SRC-002 — multi-board sourcing, pagination, honest errors.

RED first: the Ashby/Workable/Wellfound adapters, Seek pagination, the
per-source ScoutResult, and the JobSourceStatus table do not exist yet.

All adapter tests run in fixture mode — NO live HTTP is performed here. The
Seek pagination test monkeypatches the Firecrawl scrape helpers so it never
touches the network either.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "http"

NEW_PER_COMPANY_SOURCES = ("ashby", "workable")
NEW_SOURCES = ("ashby", "workable", "wellfound")


def _load_fixture(source: str) -> dict:
    return json.loads((FIXTURE_DIR / source / "jobs.json").read_text())


def _adapter(source: str):
    from app.services.discovery.adapter_registry import get_adapter_class

    return get_adapter_class(source)


# ---------------------------------------------------------------------------
# GAP-SRC-001 — new real adapters parse fixtures into the common Job shape
# ---------------------------------------------------------------------------


class TestNewAdapters:
    @pytest.mark.parametrize("source", NEW_SOURCES)
    def test_registered_in_registry(self, source):
        from app.services.discovery.base_adapter import BaseAdapter

        assert issubclass(_adapter(source), BaseAdapter)

    @pytest.mark.parametrize("source", NEW_SOURCES)
    def test_parses_fixture_into_job_shape(self, source):
        jobs = _adapter(source)(fixture=_load_fixture(source)).fetch(
            query="delivery lead, product owner, business analyst",
            location="Melbourne, Australia",
        )
        assert len(jobs) >= 1
        for job in jobs:
            assert job["source"] == source
            assert job["sourceUrl"].startswith("http")
            assert job["title"].strip()
            assert job["company"].strip()
            assert isinstance(job["remote"], bool)
            assert isinstance(job["description"], str)

    @pytest.mark.parametrize("source", NEW_SOURCES)
    def test_filters_out_irrelevant_engineering_roles(self, source):
        jobs = _adapter(source)(fixture=_load_fixture(source)).fetch(
            query="delivery lead", location="Melbourne, Australia"
        )
        for job in jobs:
            assert "software engineer" not in job["title"].lower()
            assert "backend engineer" not in job["title"].lower()

    def test_ashby_keeps_au_and_unblocked_remote_only(self):
        jobs = _adapter("ashby")(fixture=_load_fixture("ashby")).fetch(
            query="delivery lead", location="Melbourne, Australia"
        )
        titles = {j["title"] for j in jobs}
        assert "Technical Delivery Manager" in titles  # AU
        assert "Senior Product Manager" in titles  # unblocked remote
        assert "Program Manager" not in titles  # remote US-only → blocked

    def test_portals_config_has_real_tokens(self):
        from app.services.discovery import portals

        # A handful of REAL, verified tokens for each per-company provider.
        for boards in (
            portals.greenhouse_boards(),
            portals.lever_companies(),
            portals.ashby_boards(),
            portals.workable_accounts(),
        ):
            assert len(boards) >= 2
            assert all(isinstance(t, str) and t.strip() for t in boards)
        # Env override replaces the default list.
        import os

        os.environ["AETHER_ASHBY_BOARDS"] = "foo, bar"
        try:
            assert portals.ashby_boards() == ["foo", "bar"]
        finally:
            del os.environ["AETHER_ASHBY_BOARDS"]


# ---------------------------------------------------------------------------
# GAP-SRC-001 — Seek pagination (remove the hard 20-cap)
# ---------------------------------------------------------------------------


class TestSeekPagination:
    @staticmethod
    def _redux_html(records: list[dict]) -> str:
        """A minimal Seek search page carrying a SEEK_REDUX_DATA island."""
        blob = {"results": {"results": records}}
        return "<html><script>window.SEEK_REDUX_DATA = " + json.dumps(blob) + ";</script></html>"

    @staticmethod
    def _record(job_id: str, title: str = "Delivery Manager") -> dict:
        return {
            "id": job_id,
            "title": title,
            "advertiser": {"description": "Real Employer"},
            "locations": [{"label": "Melbourne VIC"}],
            "teaser": "Lead delivery across squads.",
            "bulletPoints": ["Delivery leadership"],
            "listingDate": "2026-07-02T00:00:00Z",
            "workArrangements": {"displayText": "Hybrid"},
        }

    def test_pagination_fetches_more_than_twenty_across_pages(self, monkeypatch):
        from app.services.discovery import seek_adapter as mod

        monkeypatch.setattr(mod, "_get_abacus_credentials", lambda: ("key", "url"))
        monkeypatch.setenv("AETHER_SEEK_MAX_PAGES", "5")
        monkeypatch.setenv("AETHER_SEEK_MAX_JOBS", "100")

        requested_pages: list[str] = []

        def fake_search(api_key, firecrawl_url, page_url):
            requested_pages.append(page_url)
            page = int(page_url.split("page=")[1]) if "page=" in page_url else 1
            # Pages 1..3 each carry 10 distinct jobs; page 4+ exhausted.
            records = (
                [self._record(f"{page}{i:02d}") for i in range(10)] if page <= 3 else []
            )
            return {"success": True, "data": {"rawHtml": self._redux_html(records)}}

        monkeypatch.setattr(mod, "_scrape_seek_page", fake_search)

        payload = mod.SeekAdapter()._fetch_live("delivery lead", "Melbourne")
        jobs = mod.SeekAdapter()._parse(payload)

        assert len(jobs) > 20, f"expected >20 jobs across pages, got {len(jobs)}"
        for job in jobs:
            assert job["source"] == "seek"
            assert job["sourceUrl"].startswith("https://www.seek.com.au/job/")
            assert job["company"] == "Real Employer"
        # Pagination actually walked past page 1.
        assert any("page=2" in p for p in requested_pages)

    def test_page_one_scrape_failure_raises_adapter_error_not_notimplemented(
        self, monkeypatch
    ):
        from app.services.discovery import seek_adapter as mod
        from app.services.discovery.base_adapter import AdapterFetchError

        monkeypatch.setattr(mod, "_get_abacus_credentials", lambda: ("key", "url"))

        def boom(*a, **k):
            raise RuntimeError("HTTP 408 timeout")

        monkeypatch.setattr(mod, "_scrape_seek_page", boom)

        with pytest.raises(AdapterFetchError):
            mod.SeekAdapter()._fetch_live("delivery lead", "Melbourne")

    def test_interstitial_error_page_is_not_persisted_as_a_job(self, monkeypatch):
        """A Seek block page (no data island) raises rather than yielding a
        bogus 'This site can't be reached' job — no garbage persisted."""
        from app.services.discovery import seek_adapter as mod
        from app.services.discovery.base_adapter import AdapterFetchError

        monkeypatch.setattr(mod, "_get_abacus_credentials", lambda: ("key", "url"))

        def error_page(api_key, firecrawl_url, page_url):
            return {
                "success": True,
                "data": {"rawHtml": "<html><body>This site can't be reached</body></html>"},
            }

        monkeypatch.setattr(mod, "_scrape_seek_page", error_page)

        with pytest.raises(AdapterFetchError):
            mod.SeekAdapter()._fetch_live("delivery lead", "Melbourne")


# ---------------------------------------------------------------------------
# GAP-SRC-002 — honest per-source error surfacing + JobSourceStatus
# ---------------------------------------------------------------------------


class _FakeJobRepo:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, user_id: str, payload: dict) -> dict:
        self.created.append(payload)
        return {**payload, "wasInserted": True}


class _FakeStatusRepo:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}

    def upsert(self, user_id, source, *, fetched, persisted, error, status):
        self.rows[(user_id, source)] = {
            "fetched": fetched,
            "persisted": persisted,
            "error": error,
            "status": status,
        }


class TestHonestErrorSurfacing:
    def _good_adapter(self):
        job = {
            "title": "Delivery Lead",
            "company": "Acme",
            "location": "Melbourne",
            "remote": False,
            "description": "Lead delivery.",
            "requirements": [],
            "source": "good",
            "sourceUrl": "https://acme.example/jobs/1",
            "postedAt": None,
        }

        class Good:
            def fetch(self, query, location):
                return [dict(job)]

        return Good

    def test_failing_source_is_recorded_not_swallowed(self, monkeypatch):
        from app.agents import scout_agent as module
        from app.services.discovery.base_adapter import AdapterFetchError

        class Bad:
            def fetch(self, query, location):
                raise AdapterFetchError("HTTP 500 from board")

        monkeypatch.setattr(
            module, "ADAPTERS", {"bad": Bad, "good": self._good_adapter()}
        )
        jobs_repo = _FakeJobRepo()
        status_repo = _FakeStatusRepo()
        result = module.ScoutAgent(
            repository=jobs_repo, status_repository=status_repo
        ).run("user-x", query="delivery lead", location="Melbourne")

        # The failing source is surfaced, NOT reported as an empty errors:[].
        assert result.errors, "a real fetch failure must not be silently swallowed"
        assert any("bad" in e for e in result.errors)

        by_source = {s["source"]: s for s in result.per_source}
        assert by_source["bad"]["status"] == "error"
        assert by_source["bad"]["error"]
        assert by_source["bad"]["fetched"] == 0

        # The good source still ran and persisted — one bad source didn't abort it.
        assert by_source["good"]["status"] == "ok"
        assert by_source["good"]["persisted"] == 1
        assert result.persisted == 1
        assert len(jobs_repo.created) == 1

        # Per-source status persisted for BOTH sources.
        assert status_repo.rows[("user-x", "bad")]["status"] == "error"
        assert status_repo.rows[("user-x", "good")]["status"] == "ok"

    def test_distinct_jobs_not_over_collapsed(self, monkeypatch):
        from app.agents import scout_agent as module

        base = {
            "title": "Delivery Lead",
            "company": "Acme",
            "location": "Melbourne",
            "remote": False,
            "description": "Lead delivery.",
            "requirements": [],
            "source": "s",
            "postedAt": None,
        }

        class Adapter:
            def fetch(self, query, location):
                # Same company+title, DIFFERENT sourceUrl → two distinct roles.
                return [
                    {**base, "sourceUrl": "https://acme.example/jobs/1"},
                    {**base, "sourceUrl": "https://acme.example/jobs/2"},
                ]

        monkeypatch.setattr(module, "ADAPTERS", {"s": Adapter})
        jobs_repo = _FakeJobRepo()
        result = module.ScoutAgent(
            repository=jobs_repo, status_repository=_FakeStatusRepo()
        ).run("user-y", query="delivery lead", location="Melbourne")
        assert result.persisted == 2
        assert len(jobs_repo.created) == 2


class TestFanOutTotalOutageSurfaced:
    """GAP-SRC-002 must-fix: a fan-out adapter (Ashby/Workable) whose EVERY
    configured board/account fetch RAISES is a total outage — it must surface a
    per-source ERROR (status=error, lastError set), never a silent
    status=ok fetched=0. A board that fetches OK but returns zero open roles is
    a *genuine* zero and stays a legitimate status=ok fetched=0.
    """

    # -- adapter-level: _fetch_live raises when every board fails -------------

    def test_ashby_all_boards_fail_raises_adapter_error(self, monkeypatch):
        from app.services.discovery import ashby_adapter as mod
        from app.services.discovery.base_adapter import AdapterFetchError

        def boom(url, *args, **kwargs):  # every board 403s (keyless-provider block)
            raise RuntimeError("HTTP 403 Forbidden")

        monkeypatch.setattr(mod, "fetch_json", boom)
        with pytest.raises(AdapterFetchError):
            mod.AshbyAdapter()._fetch_live("delivery lead", "Melbourne")

    def test_workable_all_accounts_fail_raises_adapter_error(self, monkeypatch):
        from app.services.discovery import workable_adapter as mod
        from app.services.discovery.base_adapter import AdapterFetchError

        def boom(url, body, *args, **kwargs):
            raise RuntimeError("HTTP 429 rate limited")

        monkeypatch.setattr(mod, "fetch_json_post", boom)
        with pytest.raises(AdapterFetchError):
            mod.WorkableAdapter()._fetch_live("delivery lead", "Melbourne")

    def test_ashby_boards_ok_zero_jobs_does_not_raise(self, monkeypatch):
        """Every board fetches OK but has no open roles → normal empty result,
        NOT an error (the scout will record status=ok fetched=0)."""
        from app.services.discovery import ashby_adapter as mod

        monkeypatch.setattr(mod, "fetch_json", lambda url, *a, **k: {"jobs": []})
        payload = mod.AshbyAdapter()._fetch_live("delivery lead", "Melbourne")
        assert payload["boards"], "boards that fetched OK must be retained"
        assert all(b["jobs"] == [] for b in payload["boards"])

    # -- scout-level: total outage → status=error, genuine zero → status=ok ---

    def test_ashby_total_outage_scout_records_status_error(self, monkeypatch):
        from app.agents import scout_agent as scout_mod
        from app.services.discovery import ashby_adapter as mod

        # Reach _fetch_live (conftest points adapters at fixtures by default).
        monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)

        def boom(url, *args, **kwargs):
            raise RuntimeError("HTTP 403 Forbidden")

        monkeypatch.setattr(mod, "fetch_json", boom)
        monkeypatch.setattr(scout_mod, "ADAPTERS", {"ashby": mod.AshbyAdapter})

        status_repo = _FakeStatusRepo()
        result = scout_mod.ScoutAgent(
            repository=_FakeJobRepo(), status_repository=status_repo
        ).run("outage-user", query="delivery lead", location="Melbourne")

        by_source = {s["source"]: s for s in result.per_source}
        # NOT status=ok fetched=0 — a wholly-failed source is an ERROR.
        assert by_source["ashby"]["status"] == "error"
        assert by_source["ashby"]["error"]  # lastError populated
        assert by_source["ashby"]["fetched"] == 0
        assert result.errors and any("ashby" in e for e in result.errors)
        # Persisted JobSourceStatus reflects the outage (never a healthy row).
        assert status_repo.rows[("outage-user", "ashby")]["status"] == "error"
        assert status_repo.rows[("outage-user", "ashby")]["error"]

    def test_ashby_genuine_zero_scout_records_status_ok(self, monkeypatch):
        from app.agents import scout_agent as scout_mod
        from app.services.discovery import ashby_adapter as mod

        monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)
        monkeypatch.setattr(mod, "fetch_json", lambda url, *a, **k: {"jobs": []})
        monkeypatch.setattr(scout_mod, "ADAPTERS", {"ashby": mod.AshbyAdapter})

        status_repo = _FakeStatusRepo()
        result = scout_mod.ScoutAgent(
            repository=_FakeJobRepo(), status_repository=status_repo
        ).run("empty-user", query="delivery lead", location="Melbourne")

        by_source = {s["source"]: s for s in result.per_source}
        # Boards fetched OK, zero jobs → legitimate status=ok fetched=0.
        assert by_source["ashby"]["status"] == "ok"
        assert by_source["ashby"]["error"] is None
        assert by_source["ashby"]["fetched"] == 0
        assert not result.errors
        assert status_repo.rows[("empty-user", "ashby")]["status"] == "ok"
        assert status_repo.rows[("empty-user", "ashby")]["error"] is None

    def test_workable_total_outage_scout_records_status_error(self, monkeypatch):
        from app.agents import scout_agent as scout_mod
        from app.services.discovery import workable_adapter as mod

        monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)

        def boom(url, body, *args, **kwargs):
            raise RuntimeError("HTTP 429 rate limited")

        monkeypatch.setattr(mod, "fetch_json_post", boom)
        monkeypatch.setattr(scout_mod, "ADAPTERS", {"workable": mod.WorkableAdapter})

        status_repo = _FakeStatusRepo()
        result = scout_mod.ScoutAgent(
            repository=_FakeJobRepo(), status_repository=status_repo
        ).run("outage-user2", query="delivery lead", location="Melbourne")

        by_source = {s["source"]: s for s in result.per_source}
        assert by_source["workable"]["status"] == "error"
        assert by_source["workable"]["error"]
        assert by_source["workable"]["fetched"] == 0
        assert result.errors and any("workable" in e for e in result.errors)
        assert status_repo.rows[("outage-user2", "workable")]["status"] == "error"

    def test_workable_genuine_zero_scout_records_status_ok(self, monkeypatch):
        from app.agents import scout_agent as scout_mod
        from app.services.discovery import workable_adapter as mod

        monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)
        monkeypatch.setattr(
            mod, "fetch_json_post", lambda url, body, *a, **k: {"results": []}
        )
        monkeypatch.setattr(scout_mod, "ADAPTERS", {"workable": mod.WorkableAdapter})

        status_repo = _FakeStatusRepo()
        result = scout_mod.ScoutAgent(
            repository=_FakeJobRepo(), status_repository=status_repo
        ).run("empty-user2", query="delivery lead", location="Melbourne")

        by_source = {s["source"]: s for s in result.per_source}
        assert by_source["workable"]["status"] == "ok"
        assert by_source["workable"]["error"] is None
        assert by_source["workable"]["fetched"] == 0
        assert not result.errors
        assert status_repo.rows[("empty-user2", "workable")]["status"] == "ok"


class TestJobSourceStatusRepository:
    def test_upsert_then_list_roundtrip(self):
        from app.repositories.job_source_status import JobSourceStatusRepository

        repo = JobSourceStatusRepository()
        user_id = f"status-user-{uuid.uuid4().hex[:12]}"

        repo.upsert(user_id, "greenhouse", fetched=40, persisted=12, error=None, status="ok")
        repo.upsert(
            user_id, "seek", fetched=0, persisted=0, error="HTTP 408", status="error"
        )
        # Re-upsert overwrites the same (userId, source) row.
        repo.upsert(user_id, "seek", fetched=5, persisted=3, error=None, status="ok")

        rows = repo.list_by_user(user_id)
        by_source = {r["source"]: r for r in rows}
        assert by_source["greenhouse"]["lastFetched"] == 40
        assert by_source["greenhouse"]["lastPersisted"] == 12
        assert by_source["greenhouse"]["status"] == "ok"
        assert by_source["seek"]["status"] == "ok"
        assert by_source["seek"]["lastFetched"] == 5
        assert by_source["seek"]["lastError"] is None
        assert by_source["seek"]["lastSyncAt"] is not None
