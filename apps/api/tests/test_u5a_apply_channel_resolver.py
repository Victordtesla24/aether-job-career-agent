"""U5a — apply-channel resolver (failing tests, written before implementation).

GROUND TRUTH pinned here (submission-flow-automation-feasibility scout,
2026-08-13, evidence: uat/reports/evidence/agents-uplift/discovery/
submission-flow-domain-histogram-2026-08-13.json + recent-submitted-
application-urls-60d.txt — live DB query + live HTTP resolution against
production ``Application.sourceUrl`` on 2026-08-13):

  Application-source histogram (512 rows): adzuna 199 (156 'land/ad/*'
  click-tracking redirector, 43 'details/*'), ashby 102, greenhouse 99
  (embedded on the employer's own domain via ``?gh_jid=``), lever 42,
  smartrecruiters 39, seek-alert 24, remoteok 4, remotive 3.

  Live first-hop resolution (2026-08-13T09:06Z) confirmed these EXACT URL
  shapes resolve cleanly with NO redirector in front of them:
    - https://jobs.ashbyhq.com/xero/<uuid>/application                -> 200
    - https://jobs.ashbyhq.com/harvey/<uuid>/application               -> 200
    - https://databricks.com/company/careers/open-positions/job?gh_jid=<id>
      -> 301 -> 301 -> 200 (Greenhouse embedded on the employer domain)
    - https://jobs.smartrecruiters.com/canva/<id>                      -> 200
    - https://jobs.lever.co/brighte/<uuid>                             -> 404
      (listing expired -- still a Lever URL shape, not a redirector)
  and these two returned 429 with Retry-After: 3600 (Adzuna/CloudFront
  rate-limiting THIS VM's egress IP at probe time -- not resolved):
    - https://adzuna.com.au/land/ad/5831481374?se=...&v=...
    - https://adzuna.com.au/details/5823574689

  ADR-SEEK-V3 (docs/delivery/ADR-SEEK-V3.md, RULING: REFUSED, un-superseded,
  re-verified live 2026-08-13T09:06Z via GET /agents/scout/sources/
  availability -> seek:{available:false, reason:'compliance-gated
  (ADR-P6-SEEK)'}) means Seek URLs (au.seek.com/job/*) must NEVER be treated
  as an automatable channel -- only a manual/no-automation classification.

WHAT DOES NOT EXIST YET (confirmed by grep across apps/api/app, 2026-08-13):
  no ``applyChannel`` column, no ``resolve_apply_channel``, no
  ``apps/api/app/services/apply_channel_resolver.py`` module at all. Every
  test below is written against the SPEC in the U-PLAN's "U5 MANDATE
  SHARPENED" section and is expected to fail with ImportError/
  ModuleNotFoundError or a missing-column error until U5a is implemented.

CONTRACT under test (this file IS the spec the implementation must satisfy):

  ``resolve_apply_channel(job: dict, *, http_get=None) -> dict``
    Returns ``{"channel": <member of CHANNELS>, "applyUrl": str | None}``.
    ``job`` is a Job-row-shaped dict; at minimum ``sourceUrl`` and
    ``applyEmail`` (may be ``None``) are read.
    Channel precedence (U5 MANDATE SHARPENED, rule 2):
      1. ``job["applyEmail"]`` truthy -> channel "email" (defers to the
         EXISTING W-SUB email path -- this resolver does not re-derive it).
      2. classify ``sourceUrl`` by host:
         - jobs.ashbyhq.com                          -> "ashby"
         - boards.greenhouse.io / job-boards.greenhouse.io, OR any host
           whose query string carries ``gh_jid`` (the employer-embedded
           shape)                                     -> "greenhouse"
         - jobs.lever.co                              -> "lever"
         - jobs.smartrecruiters.com                   -> "smartrecruiters"
         - au.seek.com / seek.com.au (any subdomain)  -> "seek-manual"
           (ADR-SEEK-V3: NEVER automated)
         - adzuna.com.au land/ad or details link      -> resolve the first
           hop (cached, rate-conscious -- see below), then classify the
           RESOLVED url by the same rules; a 429/failure resolves honestly
           to "unknown" (cached so a rate-limited window does not hammer
           Adzuna/CloudFront again for TTL seconds)
         - anything else with a sourceUrl             -> "generic"
           (best-effort form-fill candidate, incl. Google-Forms-style URLs)
         - no sourceUrl and no applyEmail             -> "unknown"

  ``ensure_application_apply_channel_column()`` (in ``app.db``, additive,
  lazy DDL per ADR-TR-1, mirrors ``ensure_application_transmission_columns``)
    adds ``Application.applyChannel`` (text, nullable).

  ``resolve_and_persist_apply_channel(user_id, application_id, job, *,
  http_get=None) -> dict``
    Same return shape as ``resolve_apply_channel``; additionally writes the
    resolved channel onto ``Application.applyChannel``.
"""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id

# ---------------------------------------------------------------------------
# Real URL shapes, verbatim from the scout's live-verified histogram/probe.
# ---------------------------------------------------------------------------

REAL_URLS = {
    "ashby": "https://jobs.ashbyhq.com/xero/c4019fbe-2f6c-43c8-a310-26dcffdc94db/application",
    "ashby_2": "https://jobs.ashbyhq.com/harvey/18f52a89-60df-4a91-9b6e-b078e9393d09/application",
    "greenhouse_embedded": "https://databricks.com/company/careers/open-positions/job?gh_jid=8569564002",
    "greenhouse_samsara": "https://samsara.com/company/careers/roles/7848459?gh_jid=7848459",
    "lever": "https://jobs.lever.co/brighte/3bd048bf-74a9-4a32-9692-34c94bf24bc2",
    "smartrecruiters": "https://jobs.smartrecruiters.com/canva/6000000001305405",
    "smartrecruiters_2": "https://jobs.smartrecruiters.com/nearmap/744000137557569",
    "seek": "https://au.seek.com/job/93669680",
    "adzuna_land": "https://adzuna.com.au/land/ad/5831481374?se=omwbkris8rglduongcclfw&v=416563dc0cc6b8b53d0cdc55cc19ba1985f375c3",
    "adzuna_details": "https://adzuna.com.au/details/5836185488",
    "remoteok": "https://remoteok.com/remote-jobs/remote-product-manager-360dialog-1135112",
}


def _job(source_url: str | None, *, apply_email: str | None = None, source: str = "adzuna") -> dict:
    return {"sourceUrl": source_url, "applyEmail": apply_email, "source": source}


# ---------------------------------------------------------------------------
# 1. Direct-domain classification (no HTTP needed -- these already ARE the
#    final ATS/employer domain per the scout's live resolution).
# ---------------------------------------------------------------------------


class TestDirectDomainClassification:
    @pytest.mark.parametrize(
        "url_key,expected_channel",
        [
            ("ashby", "ashby"),
            ("ashby_2", "ashby"),
            ("greenhouse_embedded", "greenhouse"),
            ("greenhouse_samsara", "greenhouse"),
            ("lever", "lever"),
            ("smartrecruiters", "smartrecruiters"),
            ("smartrecruiters_2", "smartrecruiters"),
            ("seek", "seek-manual"),
        ],
    )
    def test_real_url_shape_classifies_correctly(self, url_key, expected_channel):
        from app.services.apply_channel_resolver import resolve_apply_channel

        result = resolve_apply_channel(_job(REAL_URLS[url_key], source=url_key))
        assert result["channel"] == expected_channel
        assert result["applyUrl"] == REAL_URLS[url_key]

    def test_seek_is_never_automated_even_though_url_is_known(self):
        """ADR-SEEK-V3 (RULING: REFUSED, re-verified live 2026-08-13) --
        seek-manual must be a TERMINAL classification, distinct from every
        automatable channel, no matter how confidently the URL parses."""
        from app.services.apply_channel_resolver import (
            AUTOMATABLE_CHANNELS,
            resolve_apply_channel,
        )

        result = resolve_apply_channel(_job(REAL_URLS["seek"], source="seek-alert"))
        assert result["channel"] == "seek-manual"
        assert "seek-manual" not in AUTOMATABLE_CHANNELS

    def test_unrecognized_employer_domain_is_generic_not_unknown(self):
        """A direct employer-site posting with no recognized ATS fingerprint
        (e.g. a bespoke careers page, or a Google-Forms-style application)
        classifies as ``generic`` — a RESOLVED destination, not a dead end.

        What ``generic`` means changed by ORCHESTRATOR RULING U5-F3
        (2026-08-14): it is an ASSISTED channel, never auto-submitted, because
        no dedicated parser exists for a form nobody has ever seen. The
        classification asserted here is unchanged; only the disposition is,
        and that is pinned in ``test_u5_invariant_sweep.py``."""
        from app.services.apply_channel_resolver import resolve_apply_channel

        result = resolve_apply_channel(
            _job("https://docs.google.com/forms/d/e/1FAI.../viewform", source="remotive")
        )
        assert result["channel"] == "generic"

    def test_no_url_and_no_email_is_honestly_unknown(self):
        from app.services.apply_channel_resolver import resolve_apply_channel

        result = resolve_apply_channel(_job(None, source="remotive"))
        assert result["channel"] == "unknown"
        assert result["applyUrl"] is None


# ---------------------------------------------------------------------------
# 2. Channel precedence: applyEmail wins over any URL classification.
# ---------------------------------------------------------------------------


class TestEmailPrecedence:
    def test_apply_email_present_wins_over_ashby_url(self):
        """U5 MANDATE SHARPENED rule 2: 'applyEmail on the JD => existing
        W-SUB email path; ELSE resolve the posting URL'. An email takes
        priority even when the stored sourceUrl also happens to be a
        recognizable ATS link."""
        from app.services.apply_channel_resolver import resolve_apply_channel

        job = _job(REAL_URLS["ashby"], apply_email="careers@examplecorp.com")
        result = resolve_apply_channel(job)
        assert result["channel"] == "email"


# ---------------------------------------------------------------------------
# 3. Adzuna redirector: rate-conscious, cached, honest-unknown on 429.
# ---------------------------------------------------------------------------


class TestAdzunaRedirectorResolution:
    def test_redirector_resolves_to_the_final_ats_domain(self):
        """The scout's live probe found Adzuna 'land/ad' and 'details' links
        are Adzuna's OWN click-tracking redirector, not the final employer
        domain -- resolving one must follow the real first hop."""
        from app.services.apply_channel_resolver import resolve_apply_channel

        calls: list[str] = []

        def fake_http_get(url: str) -> dict:
            calls.append(url)
            return {"status": 302, "location": REAL_URLS["ashby"]}

        result = resolve_apply_channel(
            _job(REAL_URLS["adzuna_land"], source="adzuna"), http_get=fake_http_get
        )
        assert result["channel"] == "ashby"
        assert result["applyUrl"] == REAL_URLS["ashby"]
        assert calls == [REAL_URLS["adzuna_land"]]

    def test_429_resolves_honestly_to_unknown_not_a_guess(self):
        """LIVE EVIDENCE (2026-08-13T09:06Z): both attempted Adzuna first-hop
        probes this session returned HTTP 429, Retry-After: 3600. A resolver
        that guessed a channel on a rate-limited response would be exactly
        the fabrication class this project refuses -- 429 must degrade to an
        honest 'unknown', never a silent default channel."""
        from app.services.apply_channel_resolver import resolve_apply_channel

        def rate_limited_http_get(url: str) -> dict:
            return {"status": 429, "location": None, "retry_after": 3600}

        result = resolve_apply_channel(
            _job(REAL_URLS["adzuna_details"], source="adzuna"),
            http_get=rate_limited_http_get,
        )
        assert result["channel"] == "unknown"

    def test_429_result_is_cached_so_a_second_call_does_not_re_hit_adzuna(self):
        """Rate-consciousness: a second resolve for the SAME redirector URL
        within the cache TTL must NOT issue a second HTTP call -- hammering
        an already-429'd host makes the rate limit worse, not better."""
        from app.services.apply_channel_resolver import resolve_apply_channel

        calls: list[str] = []

        def counting_http_get(url: str) -> dict:
            calls.append(url)
            return {"status": 429, "location": None, "retry_after": 3600}

        job = _job(REAL_URLS["adzuna_land"], source="adzuna")
        first = resolve_apply_channel(job, http_get=counting_http_get)
        second = resolve_apply_channel(job, http_get=counting_http_get)
        assert first["channel"] == second["channel"] == "unknown"
        assert len(calls) == 1, (
            "second resolve for the same URL must be served from cache, not "
            f"re-fetched -- got {len(calls)} http_get calls"
        )

    def test_successful_resolution_is_also_cached(self):
        """Caching applies to the happy path too -- a resolved redirector
        should not be re-resolved on every subsequent read of the same job."""
        from app.services.apply_channel_resolver import resolve_apply_channel

        calls: list[str] = []

        def fake_http_get(url: str) -> dict:
            calls.append(url)
            return {"status": 302, "location": REAL_URLS["smartrecruiters"]}

        job = _job(REAL_URLS["adzuna_details"] + "?cachekey=1", source="adzuna")
        resolve_apply_channel(job, http_get=fake_http_get)
        resolve_apply_channel(job, http_get=fake_http_get)
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# 4. Persistence: Application.applyChannel is an additive column that
#    round-trips through resolve_and_persist_apply_channel.
# ---------------------------------------------------------------------------


@pytest.fixture()
def user_id(client, auth_headers) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" LIMIT 1')
            return cur.fetchone()[0]


def _make_job(user_id: str, *, source_url: str, source: str = "ashby") -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Senior Engineer", "Xero", "Sydney NSW", False,
                    "Build things.", json.dumps([]), source, source_url, 78.0,
                ),
            )
        conn.commit()
    return job_id


def _make_resume(user_id: str, *, source_job_id: str) -> str:
    resume_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,1,%s,%s,%s,NOW())''',
                (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake."}), "hash", source_job_id),
            )
        conn.commit()
    return resume_id


def _make_application(user_id: str, job_id: str, resume_id: str) -> str:
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,\n\nExcited to apply.\n\nJordan"),
            )
        conn.commit()
    return app_id


class TestApplyChannelColumnAdditive:
    def test_column_is_added_idempotently_and_starts_null(self, client, auth_headers, user_id):
        from app.db import ensure_application_apply_channel_column

        ensure_application_apply_channel_column()
        ensure_application_apply_channel_column()  # second call must not raise
        job_id = _make_job(user_id, source_url=REAL_URLS["ashby"])
        resume_id = _make_resume(user_id, source_job_id=job_id)
        app_id = _make_application(user_id, job_id, resume_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT "applyChannel" FROM "Application" WHERE "id" = %s', (app_id,))
                assert cur.fetchone()[0] is None

    def test_resolve_and_persist_round_trips_through_the_database(self, client, auth_headers, user_id):
        from app.services.apply_channel_resolver import resolve_and_persist_apply_channel

        job_id = _make_job(user_id, source_url=REAL_URLS["greenhouse_embedded"], source="greenhouse")
        resume_id = _make_resume(user_id, source_job_id=job_id)
        app_id = _make_application(user_id, job_id, resume_id)
        job_row = _job(REAL_URLS["greenhouse_embedded"], source="greenhouse")

        result = resolve_and_persist_apply_channel(user_id, app_id, job_row)
        assert result["channel"] == "greenhouse"

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT "applyChannel" FROM "Application" WHERE "id" = %s', (app_id,))
                stored = cur.fetchone()[0]
        assert stored == "greenhouse", (
            "the resolved channel must be readable back from the DB exactly "
            f"as computed -- got {stored!r}"
        )
