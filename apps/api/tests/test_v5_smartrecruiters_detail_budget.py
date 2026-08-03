"""SmartRecruiters detail-fetch starvation + sweep cost (BLOCKER-SR-DETAIL).

THE DEFECT THIS SUITE PINS
--------------------------
The SmartRecruiters postings LIST carries no advert text at all, so the real
description only exists at ``/postings/{id}``. The adapter capped those detail
fetches at 40 **per company** and walked the postings in the API's own stable
order, which produced two separate production failures measured on 2026-08-03:

1. **Permanent starvation.** Canva returns 133 location-applicable postings and
   Ampol 123; every sweep enriched the SAME first 40 of each, so the remaining
   postings kept a 0-char description FOREVER. Live board: 289 SmartRecruiters
   rows, 136 with no description, 135 unscored — the fit scorer's evidence gate
   (correctly) refuses to score on no evidence, so those rows can never rank.
2. **Cost.** Up to 160 sequential blocking GETs at ~0.72s each — ~116s of
   wall-clock added to every sweep, with no global budget and no concurrency.

The fix must converge: successive sweeps enrich postings the earlier sweeps
could not, until every persisted row carries its REAL advert text. What is
NEVER acceptable is inventing text for a posting whose advert is genuinely
absent — that row must persist honestly empty and stay unranked.
"""
from __future__ import annotations

import time

import pytest

from app.services.discovery import smartrecruiters_adapter as mod

_LIST_PREFIX = "https://api.smartrecruiters.com/v1/companies/"


def _posting(company: str, index: int) -> dict:
    return {
        "id": f"{company}-{index:04d}",
        "name": "Senior Delivery Lead",
        "company": {"name": company.title()},
        "location": {
            "city": "Melbourne",
            "region": "VIC",
            "country": "au",
            "remote": False,
        },
        "releasedDate": "2026-08-01T04:00:00.000Z",
    }


def _public_url(company: str, posting_id: str) -> str:
    return f"https://jobs.smartrecruiters.com/{company}/{posting_id}"


class _FakeSmartRecruiters:
    """Stands in for ``fetch_json`` — serves list pages and detail payloads.

    Records every DETAIL posting id it is asked for, which is what the
    starvation and budget assertions below are made against.
    """

    def __init__(
        self,
        companies: list[str],
        per_company: int,
        *,
        with_ad: bool = True,
        delay: float = 0.0,
        list_delay: float = 0.0,
    ) -> None:
        self.companies = companies
        self.per_company = per_company
        self.with_ad = with_ad
        self.delay = delay
        self.list_delay = list_delay
        self.detail_calls: list[str] = []
        self.list_calls: list[str] = []

    def __call__(self, url: str, timeout: int | None = None):  # noqa: ARG002
        assert url.startswith(_LIST_PREFIX), url
        rest = url[len(_LIST_PREFIX) :]
        company, _, tail = rest.partition("/postings")
        if tail.startswith("/"):
            posting_id = tail[1:]
            if self.delay:
                time.sleep(self.delay)
            self.detail_calls.append(posting_id)
            if not self.with_ad:
                return {"id": posting_id}
            return {
                "id": posting_id,
                "jobAd": {
                    "sections": {
                        "jobDescription": {
                            "text": f"<p>Real advert text for {posting_id}.</p>"
                        }
                    }
                },
            }
        if self.list_delay:
            time.sleep(self.list_delay)
        self.list_calls.append(url)
        offset = 0
        if "offset=" in url:
            offset = int(url.split("offset=")[1].split("&")[0])
        items = [
            _posting(company, i)
            for i in range(offset, min(offset + 100, self.per_company))
        ]
        return {"content": items}


@pytest.fixture(autouse=True)
def _forget_empty_advert_memo():
    """The read-but-empty memo is process-local state; keep tests hermetic."""
    mod._NO_AD_POSTINGS.clear()
    yield
    mod._NO_AD_POSTINGS.clear()


@pytest.fixture()
def _no_cache(monkeypatch):
    """Default: nothing already persisted, so every posting needs a fetch."""
    monkeypatch.setattr(
        mod.description_cache, "known_descriptions", lambda source, urls: {}
    )


def test_a_second_sweep_enriches_the_postings_the_first_sweep_could_not(monkeypatch):
    """Convergence: no posting may be starved permanently.

    One board with 100 applicable postings and a budget of 30. Whatever sweep 1
    enriched is then genuinely persisted WITH a description (simulated by the
    cache lookup, which in production reads the ``Job`` table), so sweep 2 must
    spend its whole budget on postings that still have none.
    """
    fake = _FakeSmartRecruiters(["canva"], 100)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva"])
    monkeypatch.setattr(mod, "fetch_json", fake)
    monkeypatch.setattr(mod, "_DETAIL_BUDGET_PER_SWEEP", 30)

    persisted: dict[str, str] = {}
    monkeypatch.setattr(
        mod.description_cache,
        "known_descriptions",
        lambda source, urls: {u: persisted[u] for u in urls if u in persisted},
    )

    def _sweep() -> set[str]:
        fake.detail_calls.clear()
        adapter = mod.SmartRecruitersAdapter()
        jobs = adapter._parse(adapter._fetch_live("Delivery Lead", "Melbourne"))
        for job in jobs:
            if job["description"].strip():
                persisted[job["sourceUrl"]] = job["description"]
        return set(fake.detail_calls)

    first = _sweep()
    assert len(first) == 30, f"budget not spent: {len(first)}"
    assert len(persisted) == 30

    second = _sweep()
    assert len(second) == 30
    assert not (first & second), (
        "the second sweep re-enriched postings that were ALREADY persisted with "
        f"a description — {len(first & second)} overlap(s); the rest stay starved"
    )
    assert len(persisted) == 60, "coverage did not converge across sweeps"

    third = _sweep()
    assert not (third & (first | second))
    assert len(persisted) == 90


def test_detail_fetches_are_globally_budgeted_and_concurrent(monkeypatch):
    """The budget is per SWEEP, not per company, and the fetches overlap.

    Three boards x 60 applicable postings. The old per-company cap of 40 spent
    120 sequential requests here; the sweep budget is a single global number and
    the requests run with bounded concurrency.
    """
    fake = _FakeSmartRecruiters(["canva", "ampol", "seek"], 60, delay=0.05)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva", "ampol", "seek"])
    monkeypatch.setattr(mod, "fetch_json", fake)
    monkeypatch.setattr(mod, "_DETAIL_BUDGET_PER_SWEEP", 30)
    monkeypatch.setattr(
        mod.description_cache, "known_descriptions", lambda source, urls: {}
    )

    started = time.monotonic()
    mod.SmartRecruitersAdapter()._fetch_live("Delivery Lead", "Melbourne")
    elapsed = time.monotonic() - started

    assert len(fake.detail_calls) == 30, (
        "detail fetches must obey ONE global per-sweep budget, not a per-company "
        f"cap (got {len(fake.detail_calls)})"
    )
    # 30 x 50ms sequentially is 1.5s; with bounded concurrency it is a fraction.
    assert elapsed < 0.9, f"detail fetches ran sequentially ({elapsed:.2f}s)"


def test_company_boards_are_listed_concurrently(monkeypatch, _no_cache):
    """13 configured boards fetched one after another cost ~11s of every sweep
    (measured live 2026-08-03). Boards are independent, so they are read with
    bounded concurrency — while still reporting per-company failures."""
    companies = [f"co{i}" for i in range(8)]
    fake = _FakeSmartRecruiters(companies, 0, list_delay=0.1)
    monkeypatch.setattr(mod, "configured_companies", lambda: companies)
    monkeypatch.setattr(mod, "fetch_json", fake)

    started = time.monotonic()
    payload = mod.SmartRecruitersAdapter()._fetch_live("Delivery Lead", "Melbourne")
    elapsed = time.monotonic() - started

    assert [b["company"] for b in payload["boards"]] == companies
    assert len(fake.list_calls) == 8
    # 8 x 100ms sequentially is 0.8s.
    assert elapsed < 0.5, f"company boards were listed sequentially ({elapsed:.2f}s)"


def test_one_failing_board_is_still_reported_and_the_others_survive(monkeypatch, _no_cache):
    """Concurrency must not blur per-company failure accounting (GAP-SRC-002)."""
    companies = ["canva", "ampol"]
    fake = _FakeSmartRecruiters(companies, 2)

    def _half_broken(url: str, timeout: int | None = None):
        if "/companies/ampol/" in url:
            raise RuntimeError("connection reset")
        return fake(url, timeout)

    monkeypatch.setattr(mod, "configured_companies", lambda: companies)
    monkeypatch.setattr(mod, "fetch_json", _half_broken)

    payload = mod.SmartRecruitersAdapter()._fetch_live("Delivery Lead", "Melbourne")
    assert [b["company"] for b in payload["boards"]] == ["canva"]
    assert len(payload["boards"][0]["jobs"]) == 2


def test_a_posting_already_persisted_with_a_description_is_not_refetched(monkeypatch):
    """Budget goes to postings that lack a description; the ones that have one
    keep their REAL persisted text instead of being wiped back to 0 chars."""
    fake = _FakeSmartRecruiters(["canva"], 3)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva"])
    monkeypatch.setattr(mod, "fetch_json", fake)

    known_url = _public_url("canva", "canva-0000")
    monkeypatch.setattr(
        mod.description_cache,
        "known_descriptions",
        lambda source, urls: {known_url: "Own delivery of the payments platform."},
    )

    adapter = mod.SmartRecruitersAdapter()
    jobs = adapter._parse(adapter._fetch_live("Delivery Lead", "Melbourne"))

    assert "canva-0000" not in fake.detail_calls, (
        "a posting whose real description is already persisted must not burn a "
        "detail fetch"
    )
    assert sorted(fake.detail_calls) == ["canva-0001", "canva-0002"]

    by_url = {job["sourceUrl"]: job for job in jobs}
    assert "payments platform" in by_url[known_url]["description"], (
        "the already-persisted real description was dropped — re-persisting this "
        "row would overwrite it with an empty string"
    )


def test_a_posting_with_no_advert_persists_honestly_empty(monkeypatch, _no_cache):
    """Anti-fabrication: a posting whose detail payload carries no jobAd gets an
    EMPTY description, never a synthesised one. It stays unranked."""
    fake = _FakeSmartRecruiters(["canva"], 2, with_ad=False)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva"])
    monkeypatch.setattr(mod, "fetch_json", fake)

    adapter = mod.SmartRecruitersAdapter()
    jobs = adapter._parse(adapter._fetch_live("Delivery Lead", "Melbourne"))

    assert jobs, "postings must still persist even with no advert"
    assert all(job["description"] == "" for job in jobs)


def test_postings_beyond_the_budget_still_persist_without_a_description(
    monkeypatch, _no_cache
):
    """Nothing is dropped for want of budget: an un-enriched posting is still
    offered to the board (unranked), it just carries no description yet."""
    fake = _FakeSmartRecruiters(["canva"], 10)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva"])
    monkeypatch.setattr(mod, "fetch_json", fake)
    monkeypatch.setattr(mod, "_DETAIL_BUDGET_PER_SWEEP", 4)

    adapter = mod.SmartRecruitersAdapter()
    jobs = adapter._parse(adapter._fetch_live("Delivery Lead", "Melbourne"))

    assert len(jobs) == 10
    assert len([j for j in jobs if j["description"]]) == 4


def test_persisted_text_is_only_ever_applied_to_its_own_posting(monkeypatch):
    """Anti-fabrication: reuse is keyed on the posting's own apply URL. Text
    persisted for a DIFFERENT posting must never become this posting's ad."""
    fake = _FakeSmartRecruiters(["canva"], 2, with_ad=False)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva"])
    monkeypatch.setattr(mod, "fetch_json", fake)
    monkeypatch.setattr(
        mod.description_cache,
        "known_descriptions",
        lambda source, urls: {
            _public_url("canva", "canva-9999"): "Text belonging to another posting."
        },
    )

    adapter = mod.SmartRecruitersAdapter()
    jobs = adapter._parse(adapter._fetch_live("Delivery Lead", "Melbourne"))
    assert [job["description"] for job in jobs] == ["", ""]


def test_a_fresh_advert_wins_over_the_persisted_copy(monkeypatch):
    """When a posting IS re-read this sweep, the freshly fetched advert is what
    persists — the carried-forward copy is only a fallback."""
    fake = _FakeSmartRecruiters(["canva"], 1)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva"])
    monkeypatch.setattr(mod, "fetch_json", fake)
    monkeypatch.setattr(
        mod.description_cache, "known_descriptions", lambda source, urls: {}
    )
    # Force the posting into the "read before, advert was empty" bucket so it is
    # still fetched, then hand it a stale persisted copy as well.
    adapter = mod.SmartRecruitersAdapter()
    payload = adapter._fetch_live("Delivery Lead", "Melbourne")
    posting = payload["boards"][0]["jobs"][0]
    posting[mod._PERSISTED_AD_KEY] = "Stale copy from an earlier sweep."

    job = adapter._parse(payload)[0]
    assert "Real advert text for canva-0000" in job["description"]
    assert "Stale copy" not in job["description"]


def test_a_cache_lookup_failure_degrades_to_fetching_not_to_a_dead_sweep(monkeypatch):
    """The persisted-description lookup is an optimisation, never a gate: if it
    raises, the sweep still enriches over the network."""
    fake = _FakeSmartRecruiters(["canva"], 3)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva"])
    monkeypatch.setattr(mod, "fetch_json", fake)

    def _boom(source, urls):
        raise RuntimeError("connection pool exhausted")

    monkeypatch.setattr(mod.description_cache, "known_descriptions", _boom)

    adapter = mod.SmartRecruitersAdapter()
    jobs = adapter._parse(adapter._fetch_live("Delivery Lead", "Melbourne"))
    assert len(fake.detail_calls) == 3
    assert all(job["description"] for job in jobs)


def test_a_failing_detail_fetch_does_not_sink_the_sweep(monkeypatch, _no_cache):
    """One posting's detail 500ing must not lose the other postings."""
    fake = _FakeSmartRecruiters(["canva"], 3)
    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva"])
    monkeypatch.setattr(mod, "_DETAIL_BUDGET_PER_SWEEP", 3)

    def _flaky(url: str, timeout: int | None = None):
        if url.endswith("/canva-0001"):
            raise RuntimeError("HTTP 500")
        return fake(url, timeout)

    monkeypatch.setattr(mod, "fetch_json", _flaky)

    adapter = mod.SmartRecruitersAdapter()
    jobs = adapter._parse(adapter._fetch_live("Delivery Lead", "Melbourne"))
    assert len(jobs) == 3
    assert len([j for j in jobs if j["description"]]) == 2


def test_known_descriptions_reads_the_real_persisted_rows(client, test_user_id):
    """Integration: the cache is the ``Job`` table, read with real SQL.

    A row persisted with a real description is a hit; a row persisted with an
    EMPTY description (exactly the starved rows this work exists to fix) is NOT
    a hit, or the starvation would be permanent.
    """
    from app.repositories.job import JobRepository
    from app.services.discovery import description_cache

    repo = JobRepository()
    filled = "https://jobs.smartrecruiters.com/canva/6000000001253917"
    starved = "https://jobs.smartrecruiters.com/canva/6000000001205116"
    for url, description in ((filled, "Own delivery of the payments platform."), (starved, "")):
        repo.create(
            test_user_id,
            {
                "title": "Senior Delivery Lead",
                "company": "Canva",
                "location": "Melbourne, VIC, au",
                "remote": False,
                "description": description,
                "requirements": [],
                "source": "smartrecruiters",
                "sourceUrl": url,
                "postedAt": "2026-08-01T04:00:00.000Z",
            },
        )

    found = description_cache.known_descriptions("smartrecruiters", [filled, starved])
    assert found == {filled: "Own delivery of the payments platform."}

    # A different source never satisfies a SmartRecruiters posting's lookup.
    assert description_cache.known_descriptions("greenhouse", [filled]) == {}
