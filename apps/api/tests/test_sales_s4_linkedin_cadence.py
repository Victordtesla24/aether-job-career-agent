"""S4 — LinkedIn DRAFT cadence: real, bounded and disclosed.

Live defect: ``linkedinDrafts`` was 0 on every manual run and nothing said why.
The cause was an undisclosed 24-hour gate — once any draft existed (e.g. the
three written by the admin "generate content" action) every later run returned
early with no counter, no reason and no trace.

The contract pinned here:

* the cadence is explicit — at most ``AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK``
  (default 2) drafts per rolling 7 days, spaced evenly;
* whenever the run produces no draft it says WHY, in the run result;
* drafts are personalized from the owner's own ``CareerProfile`` rows, which
  are supplied to the model as DATA, never as instructions;
* drafts stay DRAFTS — channel ``linkedin_draft``, outcome ``draft_queued``.
  There is no LinkedIn posting path and this suite must never create one;
* the anti-fabrication grounding guard applies to the draft: a post inventing
  user counts or prices is rejected, not queued.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.agents.sales_agent import (
    SalesAgent,
    _now,
    linkedin_drafts_per_week,
)
from app.repositories.career_profile import CareerProfileRepository
from tests._sales_fakes import RecordingLLM
from tests.test_sales_agent import (  # type: ignore[import-untyped]
    admin_headers,  # noqa: F401 — fixture
    repo,  # noqa: F401 — fixture
    sales_env,  # noqa: F401 — fixture
)

DRAFT_TEXT = (
    "I built Aether because my own job search was a mess of copy-paste. "
    "Every claim in a tailored resume has to be provable from your real "
    "history, and every application waits for your explicit yes. "
    "Free plan, no card: https://5cb5f0620.abacusai.cloud"
)


def _db_now():
    """The DATABASE's clock, not this process's.

    ``createdAt`` defaults to the server's ``NOW()`` and the hosted Postgres
    runs a fraction of a second ahead of the VM, so a window pinned to the
    local clock lets rows written moments EARLIER fall inside it. Pinning the
    window to the server clock makes these cadence tests exact instead of
    skew-dependent.
    """
    from app.db import get_connection  # noqa: PLC0415

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT NOW()")
            return cur.fetchone()[0]


def _isolate_cadence_window(repo, monkeypatch, start, *, force_spacing=0):  # noqa: F811
    """Scope BOTH cadence paths to rows created by THIS test.

    The outreach log is shared for the whole session, so a real rolling 7-day
    window would count other tests' drafts. Everything under test stays real —
    the advisory lock, the COUNT, the reservation row, the DB state the cap is
    computed from. Only the window's start moves (and, where a test is about
    the CAP rather than the spacing, the even-spacing rule is switched off so
    the two rules are asserted separately).
    """
    real_cadence = repo.linkedin_draft_cadence
    monkeypatch.setattr(
        repo, "linkedin_draft_cadence", lambda since: real_cadence(start)
    )
    real_reserve = getattr(repo, "reserve_linkedin_draft_slot", None)
    if real_reserve is None:  # pre-fix tree: nothing to isolate
        return

    def _reserve(**kwargs):
        kwargs["since"] = start
        if force_spacing is not None:
            kwargs["min_spacing_seconds"] = force_spacing
        return real_reserve(**kwargs)

    monkeypatch.setattr(repo, "reserve_linkedin_draft_slot", _reserve)


def _agent(repo, llm, monkeypatch, *, start=None, force_spacing=0) -> SalesAgent:  # noqa: F811
    agent = SalesAgent(repo=repo, llm=llm)
    if start is not None:
        _isolate_cadence_window(repo, monkeypatch, start, force_spacing=force_spacing)
    return agent


def _seed_drafts(repo, n: int) -> None:  # noqa: F811
    """Real queued drafts — the state the cap is actually computed from."""
    for i in range(n):
        repo.record_outreach(
            channel="linkedin_draft", outcome="draft_queued",
            subject="LinkedIn draft (manual posting only)",
            body=f"{DRAFT_TEXT} [{i}]", detail="seeded by the cadence suite",
        )


# --------------------------------------------------------------- config
def test_cadence_default_is_two_per_week(monkeypatch):
    monkeypatch.delenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", raising=False)
    assert linkedin_drafts_per_week() == 2


# ------------------------------------------------------------- disclosure
def test_weekly_cap_is_enforced_and_disclosed(repo, sales_env, monkeypatch):  # noqa: F811
    monkeypatch.delenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", raising=False)
    start = _db_now()
    _seed_drafts(repo, 2)  # the week's budget, really in the log
    llm = RecordingLLM(text=DRAFT_TEXT)
    agent = _agent(repo, llm, monkeypatch, start=start)
    result = {"linkedinDrafts": 0, "errors": []}

    agent._run_linkedin_draft(model="test-model", result=result, admin_id=None)

    assert result["linkedinDrafts"] == 0
    cadence = result["linkedinCadence"]
    assert cadence["perWeek"] == 2
    assert cadence["queuedLast7d"] == 2
    assert cadence["reason"], "a zero draft count must state its reason"
    assert "week" in cadence["reason"].lower()
    assert llm.text_calls == [], "no LLM spend once the cadence cap is reached"


def test_spacing_between_drafts_is_enforced_and_disclosed(repo, sales_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", "2")
    start = _db_now()
    _seed_drafts(repo, 1)  # one draft just now — the next is not due yet
    llm = RecordingLLM(text=DRAFT_TEXT)
    # force_spacing=None keeps the agent's OWN even-spacing value: this test is
    # about that rule, not about the cap (budget 2, only 1 spent).
    agent = _agent(repo, llm, monkeypatch, start=start, force_spacing=None)
    result = {"linkedinDrafts": 0, "errors": []}

    agent._run_linkedin_draft(model="test-model", result=result, admin_id=None)

    assert result["linkedinDrafts"] == 0
    cadence = result["linkedinCadence"]
    assert cadence["queuedLast7d"] == 1
    assert cadence["nextEligibleAt"], "the next eligible time must be disclosed"
    assert cadence["reason"]
    assert llm.text_calls == []


def test_zero_drafts_always_carry_a_reason(repo, sales_env, monkeypatch):  # noqa: F811
    """Disabling the cadence is legitimate — going silent about it is not."""
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", "0")
    llm = RecordingLLM(text=DRAFT_TEXT)
    agent = _agent(repo, llm, monkeypatch, start=_db_now())
    result = {"linkedinDrafts": 0, "errors": []}

    agent._run_linkedin_draft(model="test-model", result=result, admin_id=None)

    assert result["linkedinDrafts"] == 0
    assert result["linkedinCadence"]["reason"]
    assert llm.text_calls == []


# ------------------------------------------------------------ generation
def test_draft_is_generated_and_grounded_in_the_owners_career_profile(
    repo, sales_env, monkeypatch, client  # noqa: F811
):
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", "2")
    owner_id = client._test_user_id
    marker = f"Built the Adzuna sourcing pipeline {uuid.uuid4().hex[:8]}"
    CareerProfileRepository().upsert(
        owner_id, "linkedin", status="ok", summary=marker,
        url="https://www.linkedin.com/in/example",
    )
    llm = RecordingLLM(text=DRAFT_TEXT)
    start = _db_now()
    agent = _agent(repo, llm, monkeypatch, start=start)
    result = {"linkedinDrafts": 0, "errors": []}

    agent._run_linkedin_draft(model="test-model", result=result, admin_id=owner_id)

    assert result["linkedinDrafts"] == 1, result
    assert len(llm.text_calls) == 1
    call = llm.text_calls[0]
    assert marker in call["user"], "the owner's career data never reached the prompt"
    # Prompt-injection posture: the profile is DATA, never instructions.
    blob = (call["system"] + call["user"]).lower()
    assert "data" in blob and "instruction" in blob
    rows, _ = repo.list_outreach(
        channel="linkedin_draft", outcome="draft_queued", since=start, limit=5
    )
    assert rows and rows[0]["body"] == DRAFT_TEXT
    assert rows[0]["channel"] == "linkedin_draft"
    assert result["linkedinCadence"]["queuedLast7d"] == 0


def test_fabricated_draft_is_rejected_by_the_grounding_guard(
    repo, sales_env, monkeypatch  # noqa: F811
):
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", "2")
    llm = RecordingLLM(
        text="12,000 users already found jobs with Aether — only $499 this week!"
    )
    start = _db_now()
    agent = _agent(repo, llm, monkeypatch, start=start)
    result = {"linkedinDrafts": 0, "errors": []}

    agent._run_linkedin_draft(model="test-model", result=result, admin_id=None)

    assert result["linkedinDrafts"] == 0
    assert any("grounding guard" in e for e in result["errors"])
    rows, _ = repo.list_outreach(channel="linkedin_draft", outcome="draft_queued", limit=5)
    assert all(
        "12,000 users" not in (r["body"] or "") for r in rows
    ), "a fabricated draft was queued"
    # ... and the slot the rejected draft reserved went back to the budget.
    assert repo.linkedin_draft_cadence(start)["count"] == 0, (
        "a rejected draft kept its reserved weekly slot"
    )


def test_llm_failure_is_recorded_not_swallowed(repo, sales_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", "2")
    llm = RecordingLLM(text_exc=RuntimeError("provider down"))
    agent = _agent(repo, llm, monkeypatch, start=_db_now())
    result = {"linkedinDrafts": 0, "errors": []}

    agent._run_linkedin_draft(model="test-model", result=result, admin_id=None)

    assert result["linkedinDrafts"] == 0
    assert any("linkedin" in e.lower() for e in result["errors"])


# ------------------------------------------------------------------ repo
def test_cadence_query_counts_real_rows(repo):  # noqa: F811
    before = repo.linkedin_draft_cadence(_now() - timedelta(days=7))
    repo.record_outreach(
        channel="linkedin_draft", outcome="draft_queued",
        subject="cadence probe", body="probe body",
        detail="cadence unit probe",
    )
    after = repo.linkedin_draft_cadence(_now() - timedelta(days=7))

    assert after["count"] == before["count"] + 1
    assert after["lastAt"] is not None


# ----------------------------------------------------------- no posting
def test_there_is_still_no_linkedin_posting_path():
    """Hard invariant: drafts only. If this import ever succeeds, the agent
    grew a posting capability nobody approved."""
    import app.agents.sales_agent as mod

    source = open(mod.__file__, encoding="utf-8").read().lower()
    for forbidden in ("api.linkedin.com", "linkedin_post(", "publish_linkedin"):
        assert forbidden not in source, f"LinkedIn posting path appeared: {forbidden}"


@pytest.mark.parametrize("value,expected", [("3", 3), ("0", 0), ("nonsense", 2), ("-4", 0)])
def test_cadence_config_parsing_is_safe(monkeypatch, value, expected):
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", value)
    assert linkedin_drafts_per_week() == expected


# ------------------------------------------------- concurrency (the real cap)
# The cadence was a check-then-act: COUNT the week's drafts, call the model for
# ~10s, THEN insert. Two overlapping runs (a double-clicked /run-now, two admin
# tabs, cron overlapping a manual trigger) both read the same pre-insert count
# and both draft — so the "at most N per week" claim was not actually
# enforceable. The slot must be claimed BEFORE the model call, atomically, and
# given back when the draft honestly fails.
def _drafts_since(repo, start) -> int:  # noqa: F811
    rows, _ = repo.list_outreach(
        channel="linkedin_draft", outcome="draft_queued", since=start, limit=50
    )
    return len(rows)


def test_overlapping_runs_cannot_exceed_the_weekly_cap(repo, sales_env, monkeypatch):  # noqa: F811
    """Two runs overlapping across the model call may produce ONE draft."""
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", "1")
    start = _db_now()
    _isolate_cadence_window(repo, monkeypatch, start)
    second_result: dict = {"linkedinDrafts": 0, "errors": []}

    def _second_run() -> None:
        """The overlapping run — it starts while the first is inside the LLM."""
        SalesAgent(repo=repo, llm=RecordingLLM(text=DRAFT_TEXT))._run_linkedin_draft(
            model="test-model", result=second_result, admin_id=None
        )

    class _OverlappingLLM:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
            self.calls += 1
            if self.calls == 1:
                _second_run()
            return DRAFT_TEXT

    first_result: dict = {"linkedinDrafts": 0, "errors": []}
    SalesAgent(repo=repo, llm=_OverlappingLLM())._run_linkedin_draft(
        model="test-model", result=first_result, admin_id=None
    )

    drafted = first_result["linkedinDrafts"] + second_result["linkedinDrafts"]
    assert drafted == 1, (
        f"{drafted} drafts queued by two overlapping runs against a cap of 1 — "
        "the weekly cadence is not enforceable"
    )
    assert _drafts_since(repo, start) == 1, "more rows landed than the cap allows"
    blocked = second_result.get("linkedinCadence", {}).get("reason", "")
    assert blocked, "the run that lost the race must say why it drafted nothing"


def test_a_failed_draft_gives_its_reserved_slot_back(repo, sales_env, monkeypatch):  # noqa: F811
    """An honest failure must refund the slot, never burn the week's budget."""
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", "1")
    start = _db_now()
    _isolate_cadence_window(repo, monkeypatch, start)

    failed: dict = {"linkedinDrafts": 0, "errors": []}
    SalesAgent(
        repo=repo, llm=RecordingLLM(text_exc=RuntimeError("provider down"))
    )._run_linkedin_draft(model="test-model", result=failed, admin_id=None)
    assert failed["linkedinDrafts"] == 0

    retried: dict = {"linkedinDrafts": 0, "errors": []}
    SalesAgent(repo=repo, llm=RecordingLLM(text=DRAFT_TEXT))._run_linkedin_draft(
        model="test-model", result=retried, admin_id=None
    )

    assert retried["linkedinDrafts"] == 1, (
        "a failed model call consumed the week's only slot — the reservation "
        f"was never released: {retried.get('linkedinCadence')}"
    )
    assert _drafts_since(repo, start) == 1


# ------------------------------------------------------------ repo contract
def test_reserving_a_slot_is_atomic_and_refundable(repo):  # noqa: F811
    start = _db_now()

    first = repo.reserve_linkedin_draft_slot(
        since=start, per_week=1, min_spacing_seconds=0
    )
    assert first["reserved"] is True and first["reservationId"]

    second = repo.reserve_linkedin_draft_slot(
        since=start, per_week=1, min_spacing_seconds=0
    )
    assert second["reserved"] is False, "the cap was not enforced by the reserve"
    assert second["blockedBy"] == "cap"

    assert repo.release_linkedin_draft_slot(first["reservationId"]) is True
    third = repo.reserve_linkedin_draft_slot(
        since=start, per_week=1, min_spacing_seconds=0
    )
    assert third["reserved"] is True, "a released slot must become available again"

    row = repo.finalize_linkedin_draft(
        third["reservationId"], subject="LinkedIn draft", body=DRAFT_TEXT,
        detail="unit test finalize",
    )
    assert row and row["outcome"] == "draft_queued" and row["body"] == DRAFT_TEXT
    # A finalized draft is a real logged draft — it can never be released.
    assert repo.release_linkedin_draft_slot(third["reservationId"]) is False


def test_concurrent_reservations_never_exceed_the_cap(repo):  # noqa: F811
    """Three threads, one slot: the advisory lock makes exactly one win."""
    import threading  # noqa: PLC0415

    start = _db_now()
    outcomes: list[dict] = []
    lock = threading.Lock()
    ready = threading.Barrier(3)

    def _claim() -> None:
        ready.wait(timeout=30)
        got = repo.reserve_linkedin_draft_slot(
            since=start, per_week=1, min_spacing_seconds=0
        )
        with lock:
            outcomes.append(got)

    threads = [threading.Thread(target=_claim) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    won = [o for o in outcomes if o.get("reserved")]
    assert len(outcomes) == 3, "a reserving thread never finished"
    assert len(won) == 1, f"{len(won)} threads claimed the same single slot"


def test_a_stale_reservation_cannot_burn_a_slot_forever(repo):  # noqa: F811
    """A run killed between reserving and drafting must not hold the slot."""
    from datetime import timedelta as _td  # noqa: PLC0415

    from app.db import get_connection  # noqa: PLC0415
    from app.repositories.sales import LINKEDIN_RESERVATION_TTL_MINUTES  # noqa: PLC0415

    start = _db_now()
    stale = repo.reserve_linkedin_draft_slot(
        since=start, per_week=1, min_spacing_seconds=0
    )
    assert stale["reserved"] is True
    # Age the reservation the way a killed process would leave it behind.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "SalesOutreachLog" SET "createdAt" = %s WHERE "id" = %s',
                (_now() - _td(minutes=LINKEDIN_RESERVATION_TTL_MINUTES + 5),
                 stale["reservationId"]),
            )
        conn.commit()

    again = repo.reserve_linkedin_draft_slot(
        since=start, per_week=1, min_spacing_seconds=0
    )

    assert again["reserved"] is True
    assert again["staleReclaimed"] >= 1, (
        "the abandoned reservation was never reclaimed — it would hold the "
        "slot until the rolling window moved past it"
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT 1 FROM "SalesOutreachLog" WHERE "id" = %s',
                (stale["reservationId"],),
            )
            assert cur.fetchone() is None, "the stale reservation row survived"
