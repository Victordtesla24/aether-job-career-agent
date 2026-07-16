"""GAP-P6-SRC-002 / SRC-001 / DATA-001 — Cluster C job-sourcing remediation.

RED first (this commit): the compliance registry split, the Adzuna AU adapter,
the expanded verified portal tokens, and the active-feed liveness/freshness
filter do not exist yet.

Binding ADR-P6-SEEK: Seek scraping is ToS-prohibited (seek-tos-check.md verdict
SCRAPING-PROHIBITED; robots.txt names anthropic-ai; probe-13 10/10 cards HTTP
403). The SeekAdapter must NOT run in the live sync path. Volume is reached via
compliant sources only (Greenhouse/Lever/Ashby/Workable ATS APIs + Remotive/
RemoteOK + licensed Adzuna AU). All adapter tests run offline (fixture mode or
monkeypatched HTTP) — no live network here.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "http"


def _load_fixture(source: str) -> dict:
    return json.loads((FIXTURE_DIR / source / "jobs.json").read_text())


# ---------------------------------------------------------------------------
# GAP-P6-SRC-002 — Seek excluded from the LIVE registry (ADR-P6-SEEK)
# ---------------------------------------------------------------------------


class TestSeekComplianceRegistry:
    def test_seek_absent_from_live_registry(self):
        from app.services.discovery.adapter_registry import ADAPTERS

        assert "seek" not in ADAPTERS, (
            "SeekAdapter must NOT be in the live registry the scout iterates "
            "(ADR-P6-SEEK: Seek scraping is ToS-prohibited)"
        )

    def test_seek_class_still_resolvable(self):
        """The adapter stays in the codebase (fixture tests + the opt-in
        escape hatch resolve it) — it is only excluded from the live sync
        path, not deleted."""
        from app.services.discovery.adapter_registry import get_adapter_class
        from app.services.discovery.base_adapter import BaseAdapter

        assert issubclass(get_adapter_class("seek"), BaseAdapter)

    def test_seek_enabled_flag_re_adds_seek(self, monkeypatch):
        """AETHER_ENABLE_SEEK is an explicit, default-OFF opt-in (e.g. a future
        licensed Seek partnership). Default OFF; only a truthy value re-adds it."""
        from app.services.discovery import adapter_registry as reg

        monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
        assert "seek" not in reg.build_live_registry()

        monkeypatch.setenv("AETHER_ENABLE_SEEK", "1")
        assert "seek" in reg.build_live_registry()

    def test_scout_sync_path_never_runs_seek(self):
        """Exercise the real registry through the scout: no 'seek' source is
        touched in a default run (fixture mode via conftest — no network)."""
        from app.agents import scout_agent as module

        class _FakeRepo:
            def create(self, user_id, payload):
                return {**payload, "wasInserted": True}

        class _FakeStatus:
            def upsert(self, *a, **k):
                return None

        result = module.ScoutAgent(
            repository=_FakeRepo(), status_repository=_FakeStatus()
        ).run("seek-guard-user", query="delivery lead", location="Melbourne, AU")
        sources = {s["source"] for s in result.per_source}
        assert "seek" not in sources


# ---------------------------------------------------------------------------
# GAP-P6-SRC-002 / SRC-001 — Adzuna AU licensed adapter
# ---------------------------------------------------------------------------


class TestAdzunaAdapter:
    def test_registered_in_live_registry(self):
        from app.services.discovery.adapter_registry import ADAPTERS, get_adapter_class
        from app.services.discovery.base_adapter import BaseAdapter

        assert "adzuna" in ADAPTERS
        assert issubclass(get_adapter_class("adzuna"), BaseAdapter)

    def test_missing_creds_degrades_honestly(self, monkeypatch):
        """Absent ADZUNA_APP_ID/ADZUNA_APP_KEY ⇒ honest degrade (a benign skip
        the scout records), NEVER fabricated jobs."""
        from app.services.discovery.adzuna_adapter import AdzunaAdapter

        monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
        monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
        with pytest.raises(NotImplementedError):
            AdzunaAdapter()._fetch_live("delivery lead", "Melbourne, AU")

    def test_parses_au_jobs_from_fixture(self):
        from app.services.discovery.adzuna_adapter import AdzunaAdapter

        jobs = AdzunaAdapter(fixture=_load_fixture("adzuna")).fetch(
            query="delivery lead, product owner, business analyst",
            location="Melbourne, Australia",
        )
        assert len(jobs) >= 1
        for job in jobs:
            assert job["source"] == "adzuna"
            # Real Adzuna redirect URL — never fabricated.
            assert job["sourceUrl"].startswith("http")
            assert job["title"].strip()
            assert job["company"].strip()
            assert isinstance(job["remote"], bool)
            # Engineering noise in the fixture is filtered by relevance.
            assert "software engineer" not in job["title"].lower()

    def test_api_failure_raises_adapter_error(self, monkeypatch):
        from app.services.discovery import adzuna_adapter as mod
        from app.services.discovery.base_adapter import AdapterFetchError

        monkeypatch.setenv("ADZUNA_APP_ID", "id")
        monkeypatch.setenv("ADZUNA_APP_KEY", "key")

        def boom(url, *a, **k):
            raise RuntimeError("HTTP 500 from Adzuna")

        monkeypatch.setattr(mod, "fetch_json", boom)
        with pytest.raises(AdapterFetchError):
            mod.AdzunaAdapter()._fetch_live("delivery lead", "Melbourne, AU")

    def test_genuine_zero_does_not_raise(self, monkeypatch):
        from app.services.discovery import adzuna_adapter as mod

        monkeypatch.setenv("ADZUNA_APP_ID", "id")
        monkeypatch.setenv("ADZUNA_APP_KEY", "key")
        monkeypatch.setattr(mod, "fetch_json", lambda url, *a, **k: {"results": []})
        payload = mod.AdzunaAdapter()._fetch_live("delivery lead", "Melbourne, AU")
        assert payload["results"] == []


# ---------------------------------------------------------------------------
# GAP-P6-SRC-001 — expanded, live-verified compliant portal tokens
# ---------------------------------------------------------------------------


class TestExpandedPortalTokens:
    """Every token asserted here was curled live (HTTP 200, real board) against
    the provider's public API before being committed — see portals.py
    docstrings and the token_verification.json evidence artifact."""

    def test_new_greenhouse_tokens_present(self):
        from app.services.discovery import portals

        boards = portals.greenhouse_boards()
        for token in ("databricks", "samsara", "twilio", "grafanalabs"):
            assert token in boards, token

    def test_new_lever_tokens_present(self):
        from app.services.discovery import portals

        companies = portals.lever_companies()
        for token in ("brighte", "mable", "plenti"):
            assert token in companies, token

    def test_new_ashby_tokens_present(self):
        from app.services.discovery import portals

        boards = portals.ashby_boards()
        for token in ("airwallex", "supabase", "harvey"):
            assert token in boards, token

    def test_all_lists_unique_and_nonempty(self):
        from app.services.discovery import portals

        for boards in (
            portals.greenhouse_boards(),
            portals.lever_companies(),
            portals.ashby_boards(),
            portals.workable_accounts(),
        ):
            assert len(boards) >= 3
            assert all(isinstance(t, str) and t.strip() for t in boards)
            assert len(boards) == len(set(boards)), f"duplicate token in {boards!r}"


# ---------------------------------------------------------------------------
# JD ingestion truncation (Cluster G quality DEFECT 3, handed off to Phase 6):
# every compliant adapter fed the description straight through
# ``relevance.snippet(text, limit=500)`` before storage, truncating the
# stored JD to 500 chars. Resume-tailoring and cover-letter agents only ever
# read the already-persisted ``job['description']``, so they were starved of
# keywords beyond the first 500 chars of any real posting. Adapters must
# persist the (near-)full JD, not a short preview.
# ---------------------------------------------------------------------------

_DESCRIPTION_COMPLIANT_SOURCES = (
    "greenhouse", "lever", "ashby", "workable", "adzuna",
    "remotive", "remoteok", "wellfound",
)

#: The field each source's raw item stores its free-text JD under — the
#: FIRST field name here is the one every adapter's ``.get(...) or .get(...)``
#: chain consults first.
_DESCRIPTION_FIELDS = {
    "greenhouse": ("content",),
    "lever": ("descriptionPlain", "description"),
    "ashby": ("descriptionPlain", "descriptionHtml"),
    "workable": ("description",),
    "adzuna": ("description",),
    "remotive": ("description",),
    "remoteok": ("description",),
    "wellfound": ("description",),
}


def _all_source_items(source: str, payload: dict) -> list[dict]:
    """Flatten each source's nested fixture payload to raw item dicts."""
    if source == "greenhouse":
        return [item for board in payload.get("boards", []) for item in board.get("jobs", [])]
    if source == "lever":
        return [item for company in payload.get("companies", []) for item in company.get("postings", [])]
    if source == "ashby":
        return [item for board in payload.get("boards", []) for item in board.get("jobs", [])]
    if source == "workable":
        return [item for account in payload.get("accounts", []) for item in account.get("jobs", [])]
    return payload.get("jobs", []) or payload.get("results", [])


class TestDescriptionStorageNotTruncated:
    """A prior fixer confirmed relevance.py:129 ``snippet(text, limit=500)``
    truncates every adapter's stored description to 500 chars BEFORE it ever
    reaches the DB. This must be fixed so the full (or near-full) JD reaches
    storage, bounded to a sane cap rather than an unbounded/None limit."""

    @pytest.mark.parametrize("source", _DESCRIPTION_COMPLIANT_SOURCES)
    def test_long_source_description_is_not_truncated_to_500(self, source):
        payload = _load_fixture(source)
        long_text = "Own the roadmap and delivery cadence end to end. " * 30  # ~1530 chars
        assert len(long_text) > 500

        items = _all_source_items(source, payload)
        assert items, f"{source}: fixture has no items to mutate"
        primary_field = _DESCRIPTION_FIELDS[source][0]
        for item in items:
            if isinstance(item, dict):
                item[primary_field] = long_text

        from app.services.discovery.adapter_registry import get_adapter_class

        jobs = get_adapter_class(source)(fixture=payload).fetch(
            query="delivery lead, product owner, business analyst",
            location="Melbourne, Australia",
        )
        assert jobs, f"{source}: fixture produced no relevant jobs to check"
        for job in jobs:
            assert len(job["description"]) > 500, (
                f"{source}: description truncated to <=500 chars despite a "
                f"{len(long_text)}-char source JD (JD ingestion truncation defect)"
            )


# ---------------------------------------------------------------------------
# GAP-P6-DATA-001 — active-feed liveness + freshness + fingerprint dedupe
# ---------------------------------------------------------------------------


class TestActiveFeedPure:
    def test_fingerprint_normalises_company_title_location(self):
        from app.services.discovery.active_feed import job_fingerprint

        a = job_fingerprint("Real Co Pty Ltd", "Delivery Manager", "Melbourne, VIC")
        b = job_fingerprint("real co pty ltd", "  delivery   manager ", "melbourne vic")
        assert a == b
        c = job_fingerprint("Real Co Pty Ltd", "Product Owner", "Melbourne, VIC")
        assert a != c

    def test_is_stale_uses_posted_date(self):
        from app.services.discovery.active_feed import is_stale

        now = datetime(2026, 7, 16)
        fresh = {"postedAt": now - timedelta(days=5)}
        stale = {"postedAt": now - timedelta(days=60)}
        unknown = {"postedAt": None, "updatedAt": None, "createdAt": None}
        assert is_stale(stale, now=now) is True
        assert is_stale(fresh, now=now) is False
        # Unknown date can't be PROVEN stale — kept (never fabricate staleness).
        assert is_stale(unknown, now=now) is False

    def test_active_feed_excludes_prohibited_source(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 7, 16)
        rows = [
            {"source": "seek", "company": "A", "title": "Delivery Manager",
             "location": "Melbourne", "sourceUrl": "https://seek/1",
             "postedAt": now - timedelta(days=1)},
            {"source": "greenhouse", "company": "B", "title": "Program Manager",
             "location": "Sydney", "sourceUrl": "https://gh/2",
             "postedAt": now - timedelta(days=1)},
        ]
        feed = active_feed(rows, now=now)
        assert [j["source"] for j in feed] == ["greenhouse"]

    def test_active_feed_excludes_stale(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 7, 16)
        rows = [
            {"source": "greenhouse", "company": "A", "title": "Delivery Manager",
             "location": "Melbourne", "sourceUrl": "https://gh/1",
             "postedAt": now - timedelta(days=60)},
            {"source": "greenhouse", "company": "B", "title": "Program Manager",
             "location": "Sydney", "sourceUrl": "https://gh/2",
             "postedAt": now - timedelta(days=2)},
        ]
        feed = active_feed(rows, now=now)
        assert [j["sourceUrl"] for j in feed] == ["https://gh/2"]

    def test_active_feed_fingerprint_dedupes_and_zero_dup_urls(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 7, 16)
        rows = [
            {"source": "greenhouse", "company": "Acme", "title": "Delivery Manager",
             "location": "Melbourne", "sourceUrl": "https://gh/a",
             "postedAt": now - timedelta(days=1)},
            {"source": "lever", "company": "Acme", "title": "Delivery Manager",
             "location": "Melbourne", "sourceUrl": "https://lever/a",
             "postedAt": now - timedelta(days=1)},
        ]
        feed = active_feed(rows, now=now)
        assert len(feed) == 1  # same fingerprint collapsed
        urls = [j["sourceUrl"] for j in feed]
        assert len(urls) == len(set(urls))


class TestJobsFeedEndpoint:
    def _insert_job(self, client, headers, *, source, title, posted_days_ago,
                    url=None, company="Acme Co", location="Melbourne, VIC"):
        from app.repositories.job import JobRepository

        me = client.get("/auth/me", headers=headers).json()
        posted = (datetime.utcnow() - timedelta(days=posted_days_ago)).isoformat()
        JobRepository().create(me["id"], {
            "title": title, "company": company, "location": location,
            "remote": False, "description": "Lead delivery across teams.",
            "requirements": [], "source": source,
            "sourceUrl": url or f"https://{source}.example/{uuid.uuid4().hex[:8]}",
            "postedAt": posted,
        })

    def test_default_feed_hides_seek_and_stale_include_stale_shows_them(
        self, client, auth_headers
    ):
        # A live compliant job, a dead Seek job, and a stale compliant job.
        self._insert_job(client, auth_headers, source="greenhouse",
                         title="Delivery Manager", posted_days_ago=3)
        self._insert_job(client, auth_headers, source="seek",
                         title="Program Manager", posted_days_ago=1)
        self._insert_job(client, auth_headers, source="lever",
                         title="Product Owner", posted_days_ago=60)

        default = client.get("/jobs", headers=auth_headers).json()
        sources = {j["source"] for j in default}
        assert "seek" not in sources, "dead Seek rows must not be in the active feed"
        titles = {j["title"] for j in default}
        assert "Delivery Manager" in titles
        assert "Product Owner" not in titles, "stale (>30d) rows must be excluded"

        full = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        # History is preserved (not deleted) and reachable with include_stale.
        assert {"Delivery Manager", "Program Manager", "Product Owner"} <= {
            j["title"] for j in full
        }

    def test_default_feed_has_zero_duplicate_external_urls(self, client, auth_headers):
        self._insert_job(client, auth_headers, source="greenhouse",
                         title="Delivery Manager", posted_days_ago=2)
        self._insert_job(client, auth_headers, source="ashby",
                         title="Business Analyst", posted_days_ago=2)
        feed = client.get("/jobs", headers=auth_headers).json()
        urls = [j["sourceUrl"] for j in feed]
        assert len(urls) == len(set(urls))
