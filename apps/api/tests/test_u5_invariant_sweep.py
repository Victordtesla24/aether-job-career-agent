"""U5 INVARIANT — the sweep job: no application remains "prepared only"
(failing tests, written before implementation).

U-PLAN "U5 MANDATE SHARPENED" binding rule 1 (verbatim): "NO-PREPARED-ONLY
invariant -- every application the user approves must reach a TERMINAL
state: TRANSMITTED (email or web-form, with evidence screenshot +
transmittedAt/channel) or an HONEST ACTIONABLE state (e.g. 'manual step
required...') -- never silently stuck in prepared; a sweep job re-drives
non-terminal applications."

LIVE EVIDENCE this invariant is currently violated in production (scout,
2026-08-13): "all 339 approved application_submit approvals have
executedAt=NULL" -- 339 real approved gates, in production RIGHT NOW, that
nothing has ever driven to a terminal state. This is the exact class of row
the sweep must eliminate.

WHAT DOES NOT EXIST YET (confirmed by grep, 2026-08-13): no
``apps/api/app/workers/apply_sweep.py``. Depends on U5b's
``app.services.apply_executor`` (``ManualStepRequired`` /
``ApplyExecutorGuardError``), which also does not exist yet -- so every test
below is expected to fail with ImportError/ModuleNotFoundError until BOTH
U5b and this sweep are implemented.

CONTRACT under test (mirrors ``app.workers.board_sweep``'s orchestration-seam
pattern: the real per-application transmission attempt is monkeypatched at
``apply_sweep._attempt_transmission`` so this file pins ORCHESTRATION, not
the executor internals already covered by ``test_u5b_apply_executor.py``):

  ``_attempt_transmission(user_id: str, application_id: str, approval_id:
  str) -> None``
    The real seam: loads the tailored resume/cover letter/profile and calls
    ``app.services.apply_executor.execute_site_application``. May raise
    ``ManualStepRequired`` (executor already persisted the manual-step
    columns) or ``ApplyExecutorGuardError`` (already executed / not
    approved -- a race with a concurrent sweep or a manual execute).

  ``sweep_pending_transmissions(user_id: str, *, deadline: float | None =
  None) -> dict``
    Selects every ``Application`` with an ``ApprovalRequest(type=
    'application_submit', status='approved')`` and NO terminal state yet
    (``transmittedAt IS NULL AND manualStepReason IS NULL``), calls
    ``_attempt_transmission`` for each, and returns
    ``{"processed": N, "transmitted": N, "manual_step": N, "skipped": N}``.
    A ``ManualStepRequired`` counts as ``manual_step`` (DRIVEN, not
    skipped -- the row now carries an honest actionable state, which
    satisfies the invariant even though nothing was sent). An
    ``ApplyExecutorGuardError`` (already executed elsewhere / no longer
    approved) counts as ``skipped`` with no further action -- the row is
    already someone else's terminal outcome.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.db import new_id
from app.repositories.approval import ApprovalRepository

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[2]
_APPLY_PAGE_FIXTURES = _TESTS_DIR / "fixtures" / "apply_pages"
_EXECUTOR_TESTS = _TESTS_DIR / "test_u5b_apply_executor.py"
_TRACKER_LIB = _REPO_ROOT / "apps" / "web" / "src" / "components" / "applications" / "tracker-lib.ts"


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _make_job(conn, user_id: str, *, source_url: str | None = None) -> str:
    job_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            '''INSERT INTO "Job"
               ("id","userId","title","company","location","remote","description",
                "requirements","source","sourceUrl","fitScore","updatedAt")
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
            (
                job_id, user_id, "Senior Engineer", "Xero", "Sydney NSW", False,
                "Build things.", json.dumps([]), "ashby",
                source_url
                if source_url is not None
                else f"https://jobs.ashbyhq.com/xero/{job_id}/application",
                78.0,
            ),
        )
    conn.commit()
    return job_id


def _make_resume(conn, user_id: str, *, source_job_id: str) -> str:
    resume_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            '''INSERT INTO "Resume"
               ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
               VALUES (%s,%s,1,%s,%s,%s,NOW())''',
            (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake."}), "hash", source_job_id),
        )
    conn.commit()
    return resume_id


def _make_application(conn, user_id: str, job_id: str, resume_id: str) -> str:
    app_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            '''INSERT INTO "Application"
               ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
               VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
            (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,\n\nExcited to apply.\n\nJordan"),
        )
    conn.commit()
    return app_id


def _seed_approved(conn, user_id: str, *, source_url: str | None = None) -> tuple[str, str]:
    """``(application_id, approval_id)`` for an approved, non-terminal app."""
    job_id = _make_job(conn, user_id, source_url=source_url)
    resume_id = _make_resume(conn, user_id, source_job_id=job_id)
    app_id = _make_application(conn, user_id, job_id, resume_id)
    approval = ApprovalRepository().create(
        user_id, "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    ApprovalRepository().approve(approval["id"], user_id)
    return app_id, approval["id"]


def _seed_pending(conn, user_id: str) -> tuple[str, str]:
    """An application whose approval is still PENDING -- must never be
    touched by the sweep (approval-gate, not just non-terminal-state)."""
    job_id = _make_job(conn, user_id)
    resume_id = _make_resume(conn, user_id, source_job_id=job_id)
    app_id = _make_application(conn, user_id, job_id, resume_id)
    approval = ApprovalRepository().create(
        user_id, "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    return app_id, approval["id"]


def _mark_transmitted(conn, application_id: str) -> None:
    from app.db import ensure_application_transmission_columns

    ensure_application_transmission_columns()
    with conn.cursor() as cur:
        cur.execute(
            '''UPDATE "Application" SET "transmittedAt" = NOW(),
               "transmissionChannel" = 'ashby', "transmissionRef" = 'evidence/x.png'
               WHERE "id" = %s''',
            (application_id,),
        )
    conn.commit()


class TestSweepDrivesOnlyApprovedNonTerminalApplications:
    def test_approved_non_terminal_applications_are_attempted(self, db_session, user_id, monkeypatch):
        from app.workers import apply_sweep

        driven, _approval_id = _seed_approved(db_session, user_id)
        pending_app_id, _ = _seed_pending(db_session, user_id)

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == [driven]
        assert pending_app_id not in calls
        assert summary["processed"] == 1

    def test_already_transmitted_applications_are_never_re_attempted(self, db_session, user_id, monkeypatch):
        """No-double-submission at the SWEEP level: an application that
        already carries transmittedAt must never reach the executor seam
        again, even though its ApprovalRequest is still 'approved'."""
        from app.workers import apply_sweep

        app_id, _approval_id = _seed_approved(db_session, user_id)
        _mark_transmitted(db_session, app_id)

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == []
        assert summary["processed"] == 0

    def test_re_running_the_sweep_after_a_real_transmission_is_idempotent(self, db_session, user_id, monkeypatch):
        """End-to-end idempotency: the FIRST sweep pass transmits (the fake
        attempt writes transmittedAt, exactly as the real executor would);
        the SECOND pass over the same board must not touch that row again."""
        from app.workers import apply_sweep

        app_id, _approval_id = _seed_approved(db_session, user_id)

        def fake_attempt(uid, application_id, approval_id):
            _mark_transmitted(db_session, application_id)

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", fake_attempt)

        first = apply_sweep.sweep_pending_transmissions(user_id)
        assert first["processed"] == 1

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        second = apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == [], "a second sweep pass re-drove an already-transmitted application"
        assert second["processed"] == 0


class TestManualStepCountsAsDrivenNotSkipped:
    def test_manual_step_required_is_counted_and_leaves_no_prepared_row(self, db_session, user_id, monkeypatch):
        from app.db import ensure_application_manual_step_columns
        from app.services.apply_executor import ManualStepRequired
        from app.workers import apply_sweep

        ensure_application_manual_step_columns()
        app_id, _approval_id = _seed_approved(db_session, user_id)

        def fake_attempt(uid, application_id, approval_id):
            # Mirrors what the REAL executor does before re-raising: persist
            # the manual-step columns, THEN raise.
            with db_session.cursor() as cur:
                cur.execute(
                    '''UPDATE "Application" SET "manualStepReason" = %s,
                       "manualStepDetail" = %s, "manualStepAt" = NOW()
                       WHERE "id" = %s''',
                    ("unknown_required_question", "Flexible Working", application_id),
                )
            db_session.commit()
            raise ManualStepRequired(
                "unknown_required_question", "unanswerable required question",
                question="Flexible Working",
            )

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", fake_attempt)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["manual_step"] == 1
        assert summary["processed"] == 1

        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "manualStepReason", "transmittedAt" FROM "Application" WHERE "id" = %s',
                (app_id,),
            )
            reason, transmitted_at = cur.fetchone()
        assert reason == "unknown_required_question"
        assert transmitted_at is None


class TestNoPrepatedOnlyInvariant:
    def test_no_approved_application_remains_silently_prepared_after_one_sweep_pass(
        self, db_session, user_id, monkeypatch
    ):
        """THE core invariant (U5 MANDATE SHARPENED rule 1): after one sweep
        pass, scanning the whole board for "approved application_submit gate
        + neither transmitted nor manual-stepped" must find ZERO rows --
        this is the exact 339-row production defect the scout measured live
        (all 339 approved gates sit with executedAt=NULL, never driven)."""
        from app.db import (
            ensure_application_manual_step_columns,
            ensure_application_transmission_columns,
        )
        from app.services.apply_executor import ManualStepRequired
        from app.workers import apply_sweep

        ensure_application_manual_step_columns()
        ensure_application_transmission_columns()

        transmit_id, _ = _seed_approved(db_session, user_id)
        manual_id, _ = _seed_approved(db_session, user_id)

        def fake_attempt(uid, application_id, approval_id):
            if application_id == transmit_id:
                _mark_transmitted(db_session, application_id)
            else:
                with db_session.cursor() as cur:
                    cur.execute(
                        '''UPDATE "Application" SET "manualStepReason" = %s,
                           "manualStepDetail" = %s, "manualStepAt" = NOW()
                           WHERE "id" = %s''',
                        ("captcha", "reCAPTCHA challenge detected", application_id),
                    )
                db_session.commit()
                raise ManualStepRequired("captcha", "reCAPTCHA challenge detected")

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", fake_attempt)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["processed"] == 2

        with db_session.cursor() as cur:
            cur.execute(
                '''
                SELECT a."id" FROM "Application" a
                JOIN "ApprovalRequest" ar ON ar."applicationId" = a."id"
                WHERE a."userId" = %s AND ar."type" = 'application_submit'::"ApprovalType"
                  AND ar."status" = 'approved'::"ApprovalStatus"
                  AND a."transmittedAt" IS NULL
                  AND a."manualStepReason" IS NULL
                ''',
                (user_id,),
            )
            silently_prepared = cur.fetchall()
        assert silently_prepared == [], (
            f"{len(silently_prepared)} application(s) remain approved but "
            "neither transmitted nor manual-stepped after a full sweep pass "
            "-- this is the exact prepared-only defect the sweep exists to "
            "eliminate"
        )

    def test_guard_error_from_a_racing_concurrent_execute_is_skipped_not_double_driven(
        self, db_session, user_id, monkeypatch
    ):
        """If a human manually executes the approval WHILE the sweep is
        mid-pass (a real race the sweep must tolerate), the executor seam
        raises the SAME guard the manual path would hit -- the sweep must
        record it as skipped, not crash the whole stretch."""
        from app.services.apply_executor import ApplyExecutorGuardError
        from app.workers import apply_sweep

        _app_id, _approval_id = _seed_approved(db_session, user_id)

        def fake_attempt(uid, application_id, approval_id):
            raise ApplyExecutorGuardError("already_executed", "raced by a concurrent execute")

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", fake_attempt)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["skipped"] == 1
        assert summary["manual_step"] == 0
        assert summary["transmitted"] == 0


# ---------------------------------------------------------------------------
# ORCHESTRATOR RULING U5-F3 (2026-08-14, binding) — the automation allowlist
# may only contain platforms with a DEDICATED, TESTED parser.
#
# `ORCHESTRATOR-RULING-U5-F3.md`: "an untested generic parser auto-submitting a
# subscriber's REAL job application is the worst failure mode this product can
# have". `lever` and `smartrecruiters` were in `AUTOMATABLE_CHANNELS` with no
# dialect parser behind them — `parse_form_schema` fell through to
# `_parse_generic`, i.e. a best-effort schema drove a real submit click on a
# real employer's form. `generic` is the same defect by construction.
#
# These tests pin the ruling as an INVARIANT rather than as a list: adding a
# platform to `AUTOMATABLE_CHANNELS` without a dedicated parser + fixture-backed
# executor tests fails here, whoever adds it and whenever.
# ---------------------------------------------------------------------------

#: Sentinel field name the stubbed generic fallback emits, so "this channel was
#: parsed by the best-effort fallback" is observable instead of inferred.
_GENERIC_FALLBACK_MARKER = "__aether_generic_fallback_probe__"

#: A form every parser can chew on — the probe is about WHICH parser runs, not
#: about what it extracts.
_PROBE_HTML = (
    '<form><label for="email">Email *</label>'
    '<input id="email" name="email" type="email" required></form>'
)


def _channels_riding_the_generic_fallback(channels, monkeypatch) -> list[str]:
    """Which of ``channels`` are parsed by ``_parse_generic``, behaviourally.

    Stubs the fallback and asks ``parse_form_schema`` for each channel: if the
    sentinel comes back, that channel has NO dedicated dialect parser and is
    being auto-submitted on a best-effort schema.
    """
    from app.services import apply_executor

    monkeypatch.setattr(
        apply_executor,
        "_parse_generic",
        lambda soup: [
            {
                "name": _GENERIC_FALLBACK_MARKER,
                "label": "",
                "kind": "text",
                "required": False,
                "options": [],
                "scope": None,
            }
        ],
    )
    riding: list[str] = []
    for channel in sorted(channels):
        fields = apply_executor.parse_form_schema(_PROBE_HTML, channel=channel)
        if any(str(field.get("name")) == _GENERIC_FALLBACK_MARKER for field in fields):
            riding.append(channel)
    return riding


def _channels_without_test_coverage(channels) -> list[str]:
    """Which of ``channels`` lack a REAL captured page fixture + executor tests.

    "Dedicated parser" is only half the bar the ruling sets; the other half is
    that the parser is pinned against a page the platform actually serves.
    """
    executor_tests = _EXECUTOR_TESTS.read_text() if _EXECUTOR_TESTS.exists() else ""
    uncovered: list[str] = []
    for channel in sorted(channels):
        fixtures = list(_APPLY_PAGE_FIXTURES.glob(f"*{channel}*real*.html"))
        referenced = f'channel="{channel}"' in executor_tests
        if not fixtures or not referenced:
            uncovered.append(channel)
    return uncovered


class TestAutomatableChannelsAreParserBacked:
    def test_every_automatable_channel_has_a_dedicated_parser(self, monkeypatch):
        from app.services.apply_channel_resolver import AUTOMATABLE_CHANNELS

        riding = _channels_riding_the_generic_fallback(AUTOMATABLE_CHANNELS, monkeypatch)
        assert riding == [], (
            f"{riding} are in AUTOMATABLE_CHANNELS but parse_form_schema falls "
            "through to _parse_generic for them — a best-effort schema would "
            "drive a REAL submit click on a REAL employer's form "
            "(ORCHESTRATOR-RULING-U5-F3.md)"
        )

    def test_every_automatable_channel_has_a_real_page_fixture_and_executor_tests(self):
        from app.services.apply_channel_resolver import AUTOMATABLE_CHANNELS

        uncovered = _channels_without_test_coverage(AUTOMATABLE_CHANNELS)
        assert uncovered == [], (
            f"{uncovered} are automatable but have no captured real-page fixture "
            "in tests/fixtures/apply_pages and/or no executor test exercising "
            'channel="<name>" — the ruling requires dedicated parser AND tests'
        )

    def test_an_uncovered_platform_added_to_the_set_fails_the_invariant(self, monkeypatch):
        """Negative control: the sweep above must actually be able to fail.

        Without this, a green invariant proves nothing — it could be green
        because it checks nothing.
        """
        from app.services.apply_channel_resolver import AUTOMATABLE_CHANNELS

        candidate = AUTOMATABLE_CHANNELS | {"workday"}
        assert _channels_riding_the_generic_fallback(candidate, monkeypatch) == ["workday"]
        assert _channels_without_test_coverage(candidate) == ["workday"]

    def test_smartrecruiters_and_generic_are_still_assisted_not_automated(self):
        """The ruling's own disposition, pinned literally, for the two
        channels that have NOT re-entered.

        SUB-011 (Track-2 U5c) built the dedicated ``lever`` parser
        (``apply_executor._parse_lever``) with full TDD — see the deliberate
        rationale for editing this exact assertion at
        ``docs/delivery/evidence/RUN-20260818T0223Z/SUB-011/
        04-invariant-pin-rationale.md`` — and Lever re-admitted itself
        legitimately per the ruling's own re-entry clause. No dedicated
        SmartRecruiters (or bespoke-form "generic") parser exists yet, so
        those two remain ASSISTED and this assertion is what has to be
        deliberately changed to re-admit THEM, in turn.
        """
        from app.services.apply_channel_resolver import (
            ASSISTED_CHANNELS,
            AUTOMATABLE_CHANNELS,
        )

        for channel in ("smartrecruiters", "generic"):
            assert channel not in AUTOMATABLE_CHANNELS
            assert channel in ASSISTED_CHANNELS
        assert "lever" in AUTOMATABLE_CHANNELS
        assert "lever" not in ASSISTED_CHANNELS
        assert AUTOMATABLE_CHANNELS == frozenset({"ashby", "greenhouse", "lever"})

    def test_every_channel_is_classified_exactly_once(self):
        """No channel may sit outside the three dispositions.

        A new channel added to ``CHANNELS`` without a decision about how it is
        submitted would otherwise land in the ``_no_channel_reason`` catch-all
        and be described to the user as "could not determine where this posting
        goes" — false, when we resolved it perfectly well.
        """
        from app.services.apply_channel_resolver import (
            ASSISTED_CHANNELS,
            AUTOMATABLE_CHANNELS,
            CHANNELS,
            TERMINAL_NON_SUBMITTING_CHANNELS,
        )

        assert not AUTOMATABLE_CHANNELS & ASSISTED_CHANNELS
        assert not AUTOMATABLE_CHANNELS & TERMINAL_NON_SUBMITTING_CHANNELS
        assert not ASSISTED_CHANNELS & TERMINAL_NON_SUBMITTING_CHANNELS
        assert (
            AUTOMATABLE_CHANNELS | ASSISTED_CHANNELS | TERMINAL_NON_SUBMITTING_CHANNELS
        ) == CHANNELS

    def test_the_frontend_mirror_of_the_allowlist_matches_the_backend(self):
        """The REAL cross-stack pin (round-3 MUST-FIX 4).

        ``tracker-lib.ts`` keeps a literal copy of these sets to decide what the
        UI promises about a channel. A copy that drifts is a promise the backend
        does not keep, so the copy is pinned HERE — where both sides are
        readable — instead of being justified by a comment.
        """
        from app.services.apply_channel_resolver import (
            ASSISTED_CHANNELS,
            AUTOMATABLE_CHANNELS,
        )

        source = _TRACKER_LIB.read_text()

        def literal_set(name: str) -> frozenset[str]:
            match = re.search(rf"{name}[^=]*=\s*new Set\(\[(.*?)\]\)", source, re.S)
            assert match is not None, f"{name} not found in {_TRACKER_LIB}"
            return frozenset(re.findall(r'"([a-z0-9-]+)"', match.group(1)))

        assert literal_set("FE_AUTOMATABLE_CHANNELS") == AUTOMATABLE_CHANNELS
        assert literal_set("FE_ASSISTED_CHANNELS") == ASSISTED_CHANNELS


class TestAssistedChannelsAreNeverAutoSubmitted:
    def test_a_smartrecruiters_posting_reaches_an_honest_assisted_state_without_a_browser(
        self, db_session, user_id, monkeypatch
    ):
        """THE F3 defect, end to end: a SmartRecruiters application must not
        be driven — SmartRecruiters has no dedicated parser (unlike Lever,
        re-admitted at SUB-011; see the Lever browser-reaching test below),
        so it stays ASSISTED and this is the live pin for that.

        Runs the REAL ``_attempt_transmission`` (not the orchestration seam) so
        the assertion covers the actual routing decision, and makes both browser
        entry points explode if anything reaches them — "never auto-submit
        through the generic best-effort path on a real employer site".
        """
        from app.services import apply_executor
        from app.workers import apply_sweep

        app_id, _approval_id = _seed_approved(
            db_session, user_id, source_url="https://jobs.smartrecruiters.com/xero/abc-123"
        )

        def _exploding(*args, **kwargs):
            raise AssertionError("an ASSISTED channel reached the apply browser")

        monkeypatch.setattr(apply_executor, "fetch_apply_page", _exploding)
        monkeypatch.setattr(apply_executor, "execute_site_application", _exploding)

        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["processed"] == 1
        assert summary["manual_step"] == 1
        assert summary["transmitted"] == 0

        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "manualStepReason", "manualStepDetail", "transmittedAt", '
                '"applyChannel" FROM "Application" WHERE "id" = %s',
                (app_id,),
            )
            reason, detail, transmitted_at, channel = cur.fetchone()
        assert channel == "smartrecruiters"
        assert transmitted_at is None
        assert reason == "assisted_manual_submit"
        # Honest, actionable, and specific: names the platform, says a click is
        # needed, and carries the DIRECT url — never "we could not determine
        # where this goes", which would be false for a resolved SmartRecruiters
        # posting.
        assert "needs your click" in detail
        assert "https://jobs.smartrecruiters.com/xero/abc-123" in detail
        assert "could not determine" not in detail

    def test_a_lever_posting_now_reaches_the_browser_path_honestly(
        self, db_session, user_id, monkeypatch
    ):
        """SUB-011: the F3 defect's INVERSE, now that Lever has a dedicated
        parser + fixture-backed tests — the sweep must route it into the
        REAL browser entry points (never the ASSISTED "needs your click"
        copy, which would now be a false demotion), and the bare posting
        URL (no ``/apply`` suffix — the common ``sourceUrl`` shape) must
        reach the executor already carrying Lever's own ``/apply`` suffix,
        never the bare marketing page that has no ``<form>`` on it at all."""
        from app.services import apply_executor
        from app.workers import apply_sweep

        app_id, _approval_id = _seed_approved(
            db_session, user_id, source_url="https://jobs.lever.co/xero/abc-123"
        )

        seen = {}

        def _fake_fetch(apply_url: str) -> str:
            seen["apply_url"] = apply_url
            return "<form></form>"

        def _fake_execute(*args, **kwargs):
            seen["channel"] = kwargs.get("channel")
            seen["apply_url"] = kwargs.get("apply_url")
            return {"transmitted": True}

        monkeypatch.setattr(apply_executor, "fetch_apply_page", _fake_fetch)
        monkeypatch.setattr(apply_executor, "execute_site_application", _fake_execute)
        # This test pins the CHANNEL-ROUTING decision (does Lever now reach
        # the browser entry points at all), not the résumé-rendering pipeline
        # — stub the two real, heavier calls between them the same way the
        # channel decision does not depend on what they return.
        monkeypatch.setattr(apply_sweep, "build_apply_profile", lambda *a, **k: {})
        monkeypatch.setattr(apply_sweep, "_render_resume_pdf", lambda *a, **k: b"")

        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["processed"] == 1
        assert summary["manual_step"] == 0

        with db_session.cursor() as cur:
            cur.execute('SELECT "applyChannel" FROM "Application" WHERE "id" = %s', (app_id,))
            (channel,) = cur.fetchone()
        assert channel == "lever"
        assert seen["channel"] == "lever"
        assert seen["apply_url"] == "https://jobs.lever.co/xero/abc-123/apply"

    def test_an_unresolved_posting_still_says_it_is_unresolved(
        self, db_session, user_id, monkeypatch
    ):
        """The demotion must not blur the two honest states into one.

        ``unknown`` means we do not know where the application goes; ASSISTED
        means we know exactly and deliberately do not click for you.
        """
        from app.services import apply_executor
        from app.workers import apply_sweep

        app_id, _ = _seed_approved(db_session, user_id, source_url="")

        def _exploding(*args, **kwargs):
            raise AssertionError("an unresolved posting reached the apply browser")

        monkeypatch.setattr(apply_executor, "fetch_apply_page", _exploding)
        monkeypatch.setattr(apply_executor, "execute_site_application", _exploding)

        apply_sweep.sweep_pending_transmissions(user_id)
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "manualStepReason" FROM "Application" WHERE "id" = %s', (app_id,)
            )
            (reason,) = cur.fetchone()
        assert reason == "no_automatable_channel"
