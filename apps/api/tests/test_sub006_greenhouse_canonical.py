"""SUB-006-GH-CANONICAL — a ``gh_jid`` URL must be resolved to the REAL
Greenhouse form before anything navigates to it.

THE DEFECT (live probe 2026-08-17, ``uat/reports/evidence/models-live/
sub-006-gh-canonical/live-probe-2026-08-17.json``, read-only GETs only):

* ``https://www.databricks.com/company/careers/open-positions/job?gh_jid=8569564002``
  — the shape 99/512 production ``Application`` rows carry — answers 200 with
  **700,675 bytes and ZERO ``<form>`` elements**. The application UI is a
  ``div#grnhse_app`` that Greenhouse's JS mounts, and the board slug is not
  even present in the served HTML. Driving a browser at this page can only
  ever end in ``submit_control_not_found``: there is no form to submit.
* ``https://boards.greenhouse.io/embed/job_app?for=databricks&token=8569564002``
  answers (via a 301 to ``job-boards.greenhouse.io``) with **1 ``<form>`` and
  35 visible controls** — the real, server-rendered application form.
* ``…?for=notarealboardxyz&token=…`` answers **404 with 0 forms** — proof that
  a GUESSED board slug fails loudly, and therefore that the slug must be
  VERIFIED against a real fetch rather than trusted.

WHAT THIS FILE PINS (all of it fixture/synthetic — no live employer page is
fetched by any test here, and nothing is ever submitted anywhere):

1. an employer-domain ``gh_jid`` URL resolves to the canonical embed
   ``job_app`` URL, and only after a fetch of that candidate showed a real
   form (the VERIFICATION GATE);
2. a candidate that answers with no form (the employer microsite shape, or a
   404 board) is REFUSED with the honest reason ``greenhouse_form_unresolvable``
   — never "resolved anyway" and never navigated on faith;
3. the sweep records that refusal as the application's manual step and never
   opens a browser;
4. on success the sweep navigates the RESOLVED url and DISCLOSES the
   resolution (original → resolved) on the application row.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db import new_id
from app.repositories.approval import ApprovalRepository

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "apply_pages"

#: The real 2026-08-13 capture of the canonical embed URL (provenance in
#: ``fixtures/apply_pages/README.md``): 1 form, 36 visible controls.
_EMBED_HTML = (_FIXTURES / "greenhouse_embed_application_real.html").read_text(
    encoding="utf-8", errors="replace"
)
#: The employer-microsite shape: a Greenhouse mount point and NO form at all.
_EMPLOYER_MICROSITE_HTML = (_FIXTURES / "greenhouse_employer_microsite_synthetic.html").read_text(
    encoding="utf-8", errors="replace"
)

_EMPLOYER_URL = (
    "https://www.databricks.com/company/careers/open-positions/job?gh_jid=8569564002"
)
_CANONICAL_URL = (
    "https://boards.greenhouse.io/embed/job_app?for=databricks&token=8569564002"
)


@pytest.fixture(autouse=True)
def _clean_resolver_cache():
    from app.services.apply_channel_resolver import reset_resolution_cache

    reset_resolution_cache()
    yield
    reset_resolution_cache()


def _fetcher(pages: dict[str, str], *, seen: list[str] | None = None):
    """A fetcher over a fixed page table. Anything not in the table 404s —
    exactly how Greenhouse answers a board slug that does not exist."""

    def fetch(url: str) -> dict[str, object]:
        if seen is not None:
            seen.append(url)
        html = pages.get(url)
        if html is None:
            return {"status": 404, "html": ""}
        return {"status": 200, "html": html}

    return fetch


class TestCanonicalResolution:
    def test_employer_gh_jid_page_resolves_to_the_verified_embed_form(self):
        from app.services.apply_channel_resolver import resolve_greenhouse_apply_url

        seen: list[str] = []
        result = resolve_greenhouse_apply_url(
            _EMPLOYER_URL,
            fetch_html=_fetcher({_CANONICAL_URL: _EMBED_HTML}, seen=seen),
        )

        assert result["reason"] is None
        assert result["resolvedUrl"] == _CANONICAL_URL
        assert result["board"] == "databricks"
        assert result["token"] == "8569564002"
        assert result["verified"] is True
        assert result["originalUrl"] == _EMPLOYER_URL
        # The gate FETCHED the candidate before accepting it — the whole point.
        assert _CANONICAL_URL in seen

    def test_the_gate_refuses_a_candidate_whose_page_has_no_form(self):
        """The exact production shape: every candidate answers the formless
        employer microsite. Refuse honestly; do not navigate on faith."""
        from app.services.apply_channel_resolver import (
            GREENHOUSE_UNRESOLVABLE_REASON,
            resolve_greenhouse_apply_url,
        )

        seen: list[str] = []
        result = resolve_greenhouse_apply_url(
            _EMPLOYER_URL,
            fetch_html=_fetcher(
                {_CANONICAL_URL: _EMPLOYER_MICROSITE_HTML}, seen=seen
            ),
        )

        assert result["reason"] == GREENHOUSE_UNRESOLVABLE_REASON
        assert result["resolvedUrl"] is None
        assert result["verified"] is False
        assert seen, "the gate must actually fetch before it refuses"
        # Honest and actionable: names the posting the user has to open.
        assert _EMPLOYER_URL in str(result["detail"])
        assert "did not" in str(result["detail"]) or "could not" in str(result["detail"])

    def test_a_404_board_slug_is_refused_not_returned(self):
        from app.services.apply_channel_resolver import (
            GREENHOUSE_UNRESOLVABLE_REASON,
            resolve_greenhouse_apply_url,
        )

        result = resolve_greenhouse_apply_url(
            _EMPLOYER_URL, fetch_html=_fetcher({})
        )
        assert result["reason"] == GREENHOUSE_UNRESOLVABLE_REASON
        assert result["resolvedUrl"] is None

    def test_a_url_with_no_greenhouse_token_is_refused(self):
        from app.services.apply_channel_resolver import (
            GREENHOUSE_UNRESOLVABLE_REASON,
            resolve_greenhouse_apply_url,
        )

        calls: list[str] = []
        result = resolve_greenhouse_apply_url(
            "https://www.databricks.com/careers/open-positions",
            fetch_html=_fetcher({}, seen=calls),
        )
        assert result["reason"] == GREENHOUSE_UNRESOLVABLE_REASON
        assert result["token"] is None
        assert calls == [], "nothing to verify, so nothing may be fetched"

    def test_the_board_slug_can_come_from_the_employer_pages_embed_config(self):
        """``for=`` is authoritative when the employer page carries the embed
        script — the host-label guess is only ever a fallback candidate."""
        from app.services.apply_channel_resolver import resolve_greenhouse_apply_url

        page = (
            '<html><body><div id="grnhse_app"></div>'
            '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acmecorp">'
            "</script></body></html>"
        )
        expected = (
            "https://boards.greenhouse.io/embed/job_app?for=acmecorp&token=99887766"
        )
        result = resolve_greenhouse_apply_url(
            "https://careers.brandname.example/roles/eng?gh_jid=99887766",
            page_html=page,
            fetch_html=_fetcher({expected: _EMBED_HTML}),
        )
        assert result["board"] == "acmecorp"
        assert result["resolvedUrl"] == expected
        assert result["reason"] is None

    def test_an_explicit_for_param_on_the_posting_url_wins(self):
        from app.services.apply_channel_resolver import resolve_greenhouse_apply_url

        expected = (
            "https://boards.greenhouse.io/embed/job_app?for=xero&token=4242"
        )
        result = resolve_greenhouse_apply_url(
            "https://www.brandname.example/jobs?gh_jid=4242&for=xero",
            fetch_html=_fetcher({expected: _EMBED_HTML}),
        )
        assert result["board"] == "xero"
        assert result["resolvedUrl"] == expected

    def test_a_url_already_on_greenhouse_is_left_alone_and_never_fetched(self):
        from app.services.apply_channel_resolver import resolve_greenhouse_apply_url

        calls: list[str] = []
        already = "https://boards.greenhouse.io/databricks/jobs/8569564002"
        result = resolve_greenhouse_apply_url(
            already, fetch_html=_fetcher({}, seen=calls)
        )
        assert result["reason"] is None
        assert result["resolvedUrl"] == already
        assert calls == []

    def test_the_verification_result_is_cached_so_a_backlog_is_not_hammered(self):
        from app.services.apply_channel_resolver import resolve_greenhouse_apply_url

        seen: list[str] = []
        fetch = _fetcher({_CANONICAL_URL: _EMBED_HTML}, seen=seen)
        first = resolve_greenhouse_apply_url(_EMPLOYER_URL, fetch_html=fetch)
        second = resolve_greenhouse_apply_url(_EMPLOYER_URL, fetch_html=fetch)
        assert first["resolvedUrl"] == second["resolvedUrl"] == _CANONICAL_URL
        assert len(seen) == 1


class TestFormVerificationGate:
    def test_a_real_greenhouse_embed_capture_passes(self):
        from app.services.apply_channel_resolver import greenhouse_form_present

        assert greenhouse_form_present(_EMBED_HTML) is True

    def test_a_formless_employer_microsite_fails(self):
        from app.services.apply_channel_resolver import greenhouse_form_present

        assert greenhouse_form_present(_EMPLOYER_MICROSITE_HTML) is False

    def test_a_lone_newsletter_style_form_is_not_an_application_form(self):
        """One input in one form is a search/subscribe box, not an application.
        The real capture carries 36 controls; the floor is deliberately above
        the marketing-widget shape."""
        from app.services.apply_channel_resolver import greenhouse_form_present

        assert (
            greenhouse_form_present(
                '<html><body><form action="/subscribe">'
                '<input name="email"><button>Go</button></form></body></html>'
            )
            is False
        )

    def test_empty_html_is_not_a_form(self):
        from app.services.apply_channel_resolver import greenhouse_form_present

        assert greenhouse_form_present("") is False


# ---------------------------------------------------------------------------
# The sweep: the ONE seam both the background sweep and the per-card control
# execute through (``routers/approvals._execute_site_submission``).
# ---------------------------------------------------------------------------


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_approved(conn, user_id: str, *, source_url: str) -> tuple[str, str]:
    job_id = new_id()
    resume_id = new_id()
    app_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            '''INSERT INTO "Job"
               ("id","userId","title","company","location","remote","description",
                "requirements","source","sourceUrl","fitScore","updatedAt")
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
            (
                job_id, user_id, "Senior Engineer", "Databricks", "Sydney NSW",
                False, "Build things.", json.dumps([]), "greenhouse",
                source_url, 78.0,
            ),
        )
        cur.execute(
            '''INSERT INTO "Resume"
               ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
               VALUES (%s,%s,1,%s,%s,%s,NOW())''',
            (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake."}), "hash", job_id),
        )
        cur.execute(
            '''INSERT INTO "Application"
               ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
               VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
            (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,\n\nJordan"),
        )
    conn.commit()
    approval = ApprovalRepository().create(
        user_id,
        "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    ApprovalRepository().approve(approval["id"], user_id)
    return app_id, approval["id"]


class TestSweepUsesTheCanonicalForm:
    def test_an_unresolvable_gh_jid_posting_never_reaches_the_browser(
        self, db_session, user_id, monkeypatch
    ):
        from app.services import apply_channel_resolver, apply_executor
        from app.workers import apply_sweep

        app_id, approval_id = _seed_approved(
            db_session, user_id, source_url=_EMPLOYER_URL
        )

        def _exploding(*args, **kwargs):
            raise AssertionError("a formless employer page reached the apply browser")

        monkeypatch.setattr(apply_executor, "fetch_apply_page", _exploding)
        monkeypatch.setattr(apply_executor, "execute_site_application", _exploding)
        monkeypatch.setattr(
            apply_channel_resolver,
            "_default_greenhouse_fetch_html",
            _fetcher({_CANONICAL_URL: _EMPLOYER_MICROSITE_HTML}),
        )

        with pytest.raises(apply_executor.ManualStepRequired) as excinfo:
            apply_sweep._attempt_transmission(user_id, app_id, approval_id)
        assert excinfo.value.reason == "greenhouse_form_unresolvable"

        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "manualStepReason", "manualStepDetail", "transmittedAt" '
                'FROM "Application" WHERE "id" = %s',
                (app_id,),
            )
            reason, detail, transmitted_at = cur.fetchone()
        assert reason == "greenhouse_form_unresolvable"
        assert transmitted_at is None
        assert _EMPLOYER_URL in detail

    def test_a_resolvable_posting_is_navigated_at_the_canonical_url_and_disclosed(
        self, db_session, user_id, monkeypatch
    ):
        """The sweep must resolve `gh_jid` to the canonical embed form and
        hand that URL straight to the ONE Playwright session the live
        submitter opens — it must NOT pre-fetch the page itself (that would
        be a second browser session racing the submitter's own navigation).
        ``page_html`` therefore reaches the executor empty; the submitter
        navigates the canonical URL directly."""
        from app.db import ensure_application_apply_resolution_columns
        from app.services import apply_channel_resolver, apply_executor
        from app.workers import apply_sweep

        app_id, approval_id = _seed_approved(
            db_session, user_id, source_url=_EMPLOYER_URL
        )
        executed: list[dict] = []

        monkeypatch.setattr(
            apply_channel_resolver,
            "_default_greenhouse_fetch_html",
            _fetcher({_CANONICAL_URL: _EMBED_HTML}),
        )

        def _exploding_fetch(*args, **kwargs):
            raise AssertionError(
                "apply_sweep must not pre-fetch the page itself — that is a "
                "second Playwright session competing with the submitter's own"
            )

        monkeypatch.setattr(apply_executor, "fetch_apply_page", _exploding_fetch)
        monkeypatch.setattr(
            apply_executor,
            "execute_site_application",
            lambda *args, **kwargs: executed.append(kwargs) or {"transmitted": True},
        )

        apply_sweep._attempt_transmission(user_id, app_id, approval_id)

        assert executed, "execute_site_application must have been called"
        call = executed[0]
        assert call["apply_url"] == _CANONICAL_URL, (
            "the live submitter's ONE browser session must be pointed at the "
            "REAL (canonical) form, not the employer's formless gh_jid page"
        )
        assert not call.get("page_html"), (
            "the sweep must not hand a pre-fetched page to the executor — the "
            "live submitter opens the canonical URL itself in its own session"
        )

        ensure_application_apply_resolution_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "applyResolvedFrom", "applyResolvedUrl", "applyResolvedAt" '
                'FROM "Application" WHERE "id" = %s',
                (app_id,),
            )
            resolved_from, resolved_url, resolved_at = cur.fetchone()
        assert resolved_from == _EMPLOYER_URL
        assert resolved_url == _CANONICAL_URL
        assert resolved_at is not None
