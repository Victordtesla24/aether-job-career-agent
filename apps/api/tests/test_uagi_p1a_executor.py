"""U-AGI P1-A — plan EXECUTION semantics + the R-1 database admission guard.

The executor is injected with its dispatch/claim/record seams, so these tests
exercise the real ordering, refusal-propagation and halt semantics with no
database and no agents. The second half pins the DB half of the silo class:
F-R8-1 found that ``AETHER_ASYNC_GENERATION`` does NOT make ``silo`` real — the
partial unique index does, and it covered ``scout`` alone.
"""
from __future__ import annotations

import pytest

from app.repositories.background_jobs import (
    _SINGLETON_AGENTS,
    BackgroundJobRepository,
    _ensure_table,
    _reset_bg_ready_for_tests,
)
from app.services.run_scheduler import build_plan, normalize_charter
from app.services.run_scheduler.executor import execute_plan

CHARTER = normalize_charter(
    {
        "head": {"execClass": "silo", "siloBasis": "race-proven",
                 "onRefusal": "halt-chain", "dependsOn": [], "coversCards": ["c1"]},
        "mid": {"execClass": "sequential", "onRefusal": "halt-chain",
                "dependsOn": ["head"], "coversCards": ["c2"]},
        "tail": {"execClass": "sequential", "onRefusal": "halt-chain",
                 "dependsOn": ["mid"], "coversCards": ["c3"]},
        "side": {"execClass": "independent", "onRefusal": "isolate",
                 "dependsOn": [], "coversCards": ["c4"]},
        "side2": {"execClass": "independent", "onRefusal": "isolate",
                  "dependsOn": [], "coversCards": ["c5"]},
    }
)


def _steps():
    return [s.as_dict() for s in build_plan(CHARTER).steps]


def _run(dispatch, *, claim=None, halting=None, states=None):
    recorded: list[tuple[str, str, dict]] = []

    def _on_state(key, state, detail):
        recorded.append((key, state, detail))
        if states is not None:
            states.append((key, state))

    return execute_plan(
        steps=_steps(),
        dispatch=dispatch,
        claim=claim or (lambda key: ("token-" + key, True)),
        release=lambda token, key, ok: None,
        on_state=_on_state,
        halting_reason=halting or (lambda exc: None),
        spacing_seconds=0.0,
        sleep=lambda s: None,
    ), recorded


# ---------------------------------------------------------------------------
# Ordering + normal completion
# ---------------------------------------------------------------------------


def test_steps_execute_in_plan_order_and_all_complete() -> None:
    seen: list[str] = []
    summary, recorded = _run(lambda key, params: seen.append(key) or {"ok": True})

    assert seen == [s["key"] for s in _steps()]
    assert seen.index("head") < seen.index("mid") < seen.index("tail")
    assert summary["status"] == "completed"
    assert summary["haltedAtStep"] is None
    assert all(s["state"] == "completed" for s in summary["steps"])


def test_every_transition_is_recorded_before_and_after_the_dispatch() -> None:
    states: list[tuple[str, str]] = []
    _run(lambda key, params: {"ok": True}, states=states)
    head = [st for k, st in states if k == "head"]
    assert head == ["running", "completed"]


# ---------------------------------------------------------------------------
# Refusal propagation — onRefusal is DATA, the executor obeys it.
# ---------------------------------------------------------------------------


def test_a_halt_chain_failure_ends_its_CHAIN_and_names_what_was_not_attempted() -> None:
    """The chain dies; the independents do not. Reporting "nothing ran" because
    one spine step failed would be true of the code and useless to the user."""
    def dispatch(key, params):
        if key == "mid":
            raise RuntimeError("boom")
        return {"ok": True}

    summary, _ = _run(dispatch)
    by_key = {s["key"]: s for s in summary["steps"]}
    assert by_key["head"]["state"] == "completed"
    assert by_key["mid"]["state"] == "failed"
    assert by_key["tail"]["state"] == "not_attempted"
    assert "boom" in by_key["tail"]["detail"]["reason"]
    assert by_key["tail"]["detail"]["blockedBy"] == ["mid"]
    assert set(summary["notAttempted"]) == {"tail"}
    # The independents still ran, and the plan is honestly PARTIAL — neither a
    # success nor a stop.
    assert by_key["side"]["state"] == "completed"
    assert by_key["side2"]["state"] == "completed"
    assert summary["status"] == "partial"
    assert summary["haltedAtStep"] is None


def test_an_isolated_failure_never_stops_the_rest_of_the_plan() -> None:
    def dispatch(key, params):
        if key == "side":
            raise RuntimeError("nope")
        return {"ok": True}

    summary, _ = _run(dispatch)
    assert summary["status"] == "partial"
    by_key = {s["key"]: s for s in summary["steps"]}
    assert by_key["side"]["state"] == "failed"
    assert by_key["side2"]["state"] == "completed"
    assert by_key["tail"]["state"] == "completed"
    assert summary["haltedAtStep"] is None


def test_a_step_whose_dependency_did_not_complete_is_skipped_with_the_reason() -> None:
    """The head is a silo; a lost admission race must not let the chain run on
    stale inputs and claim success."""
    summary, _ = _run(
        lambda key, params: {"ok": True},
        claim=lambda key: (None, False) if key == "head" else ("t", True),
    )
    by_key = {s["key"]: s for s in summary["steps"]}
    assert by_key["head"]["state"] == "refused"
    assert "already" in by_key["head"]["detail"]["reason"]
    # head is halt-chain, so its dependents — transitively — are not attempted.
    assert by_key["mid"]["state"] == "not_attempted"
    assert by_key["tail"]["state"] == "not_attempted"
    # ...but the independents are untouched.
    assert by_key["side"]["state"] == "completed"
    assert by_key["side2"]["state"] == "completed"
    assert summary["status"] == "partial"


# ---------------------------------------------------------------------------
# Parameter threading is DATA (``paramsFrom``), never per-agent code.
# ---------------------------------------------------------------------------

PARAM_CHARTER = normalize_charter(
    {
        "picker": {"execClass": "sequential", "onRefusal": "halt-chain",
                   "dependsOn": [], "coversCards": ["c1"]},
        "worker": {"execClass": "sequential", "onRefusal": "halt-chain",
                   "dependsOn": ["picker"],
                   "paramsFrom": {"job_id": ("picker", "top_job_id")},
                   "coversCards": ["c2"]},
    }
)


def _run_param_plan(dispatch):
    return execute_plan(
        steps=[s.as_dict() for s in build_plan(PARAM_CHARTER).steps],
        dispatch=dispatch,
        claim=lambda key: ("t", True),
        release=lambda token, key, ok: None,
        on_state=lambda key, state, detail: None,
        halting_reason=lambda exc: None,
        spacing_seconds=0.0,
        sleep=lambda s: None,
    )


def test_a_declared_param_is_threaded_from_the_upstream_output() -> None:
    seen: dict[str, dict] = {}

    def dispatch(key, params):
        seen[key] = dict(params)
        return {"top_job_id": "job-42"} if key == "picker" else {"ok": True}

    summary = _run_param_plan(dispatch)
    assert seen["worker"] == {"job_id": "job-42"}
    assert summary["status"] == "completed"


def test_an_upstream_that_selected_nothing_yields_an_honest_skip_not_a_422() -> None:
    dispatched: list[str] = []

    def dispatch(key, params):
        dispatched.append(key)
        return {"top_job_id": None} if key == "picker" else {"ok": True}

    summary = _run_param_plan(dispatch)
    assert dispatched == ["picker"], "the downstream step must not be dispatched"
    worker = next(s for s in summary["steps"] if s["key"] == "worker")
    assert worker["state"] == "not_attempted"
    assert worker["detail"]["missingInputs"] == ["picker.top_job_id"]
    assert "nothing for it to work on" in worker["detail"]["reason"]
    # A step with nothing to do is not a plan HALT — the plan finished, and
    # says so honestly: partial, with the un-run step named.
    assert summary["status"] == "partial"
    assert summary["haltedAtStep"] is None


# ---------------------------------------------------------------------------
# R-4 — quota exhaustion mid-plan answers once, not nineteen times.
# ---------------------------------------------------------------------------


def test_quota_exhaustion_halts_the_plan_instead_of_collecting_19_identical_429s() -> None:
    calls: list[str] = []

    class _Quota(Exception):
        status_code = 429

    def dispatch(key, params):
        calls.append(key)
        raise _Quota("quota_exceeded")

    summary, _ = _run(
        dispatch,
        halting=lambda exc: (
            "plan quota exhausted" if getattr(exc, "status_code", None) == 429 else None
        ),
    )
    assert summary["status"] == "halted"
    assert len(calls) == 1, "a plan must not re-ask a question already answered"
    assert "quota" in summary["haltReason"]


# ---------------------------------------------------------------------------
# Admission — the claim is taken for silo steps only, and always released.
# ---------------------------------------------------------------------------


def test_the_admission_claim_is_taken_for_silo_steps_only() -> None:
    claimed: list[str] = []

    def claim(key):
        claimed.append(key)
        return ("t", True)

    _run(lambda key, params: {"ok": True}, claim=claim)
    assert claimed == ["head"]


def test_the_admission_claim_is_released_even_when_the_step_fails() -> None:
    released: list[tuple[str, bool]] = []

    execute_plan(
        steps=_steps(),
        dispatch=lambda key, params: (_ for _ in ()).throw(RuntimeError("x")),
        claim=lambda key: ("token", True),
        release=lambda token, key, ok: released.append((key, ok)),
        on_state=lambda key, state, detail: None,
        halting_reason=lambda exc: None,
        spacing_seconds=0.0,
        sleep=lambda s: None,
    )
    assert released == [("head", False)]


def test_inter_step_spacing_is_applied_between_steps_not_before_the_first() -> None:
    slept: list[float] = []
    execute_plan(
        steps=_steps(),
        dispatch=lambda key, params: {"ok": True},
        claim=lambda key: ("t", True),
        release=lambda token, key, ok: None,
        on_state=lambda key, state, detail: None,
        halting_reason=lambda exc: None,
        spacing_seconds=5.0,
        sleep=slept.append,
    )
    assert slept == [5.0] * (len(_steps()) - 1)


# ---------------------------------------------------------------------------
# R-1 / F-R8-1 — the DATABASE half of the silo class.
# ---------------------------------------------------------------------------


def test_the_singleton_set_now_covers_the_whole_silo_class(client) -> None:
    assert set(_SINGLETON_AGENTS) == {
        "scout", "submission", "emailAgent", "notification",
        "recruiterOutreach", "reference",
    }


def test_the_partial_unique_index_enforces_the_exclusive_claim(client) -> None:
    """F-R8-1(b): ``IF NOT EXISTS`` will not re-write an existing index, so the
    rule change needs a NEW name. The live index must be UNIQUE over the CLAIM
    and partial on the non-terminal statuses."""
    from app.db import get_connection
    from app.repositories.background_jobs import _SINGLETON_INDEX_NAME

    _reset_bg_ready_for_tests()
    _ensure_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'BackgroundJob' AND schemaname = current_schema()"
            )
            defs = dict(cur.fetchall())
    assert _SINGLETON_INDEX_NAME in defs, (
        "the versioned singleton index was not created — the silo class has no "
        "database backstop and is therefore decorative (F-R8-1)"
    )
    definition = defs[_SINGLETON_INDEX_NAME]
    assert "UNIQUE" in definition
    assert "singletonKey" in definition
    assert "enqueued" in definition and "processing" in definition


def test_an_unclaimed_enqueue_is_never_blocked_by_the_claim_index(client, test_user_id):
    """The regression this index shape exists to avoid: ``emailAgent`` is a silo
    agent AND has an async route that enqueues WITHOUT claiming (it has modes, so
    handing back a job doing something else would be silent substitution). Two
    such rows must coexist — an (userId, agentKey) index would 500 the second."""
    repo = BackgroundJobRepository()
    first = repo.create(test_user_id, "emailAgent", params={"mode": "triage"})
    second = repo.create(test_user_id, "emailAgent", params={"mode": "draft_reply"})
    assert first != second

    # ...and a CLAIM still excludes a second claim for the same agent.
    claim_a, created_a = repo.create_singleton(test_user_id, "emailAgent", params={})
    claim_b, created_b = repo.create_singleton(test_user_id, "emailAgent", params={})
    assert created_a is True and created_b is False and claim_a == claim_b


def test_the_scout_only_index_is_KEPT_because_the_claim_index_does_not_contain_it(
    client,
) -> None:
    """The claim index ADDS to the scout rule; it does not replace it.

    Retiring the scout index was this build's own regression, caught by
    ``test_mon020_async_scout.py::test_active_scout_singleton_is_enforced_by_a_partial_unique_index``.
    Neither index contains the other: the scout one constrains every ACTIVE
    ``scout`` row HOWEVER IT WAS WRITTEN (that is the defence-in-depth MON-020
    shipped — it holds for a caller that never went through
    ``create_singleton``), while the claim one constrains only rows that opted in
    by claiming, which is what lets a silo agent with modes still be enqueued.
    Drop the first and a future unclaimed discovery enqueue gets two concurrent
    passes with no database left to stop it.
    """
    from app.db import get_connection
    from app.repositories.background_jobs import (
        _ALWAYS_SINGLETON_AGENTS,
        _SCOUT_INDEX_NAME,
        _SINGLETON_INDEX_NAME,
    )

    assert _ALWAYS_SINGLETON_AGENTS == ("scout",), (
        "the always-on rule may not be widened without proving that a second "
        "ACTIVE row of that agent is never legitimate — it is for submission "
        "(per job) and emailAgent (per mode)"
    )

    _reset_bg_ready_for_tests()
    _ensure_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'BackgroundJob' AND schemaname = current_schema()"
            )
            defs = dict(cur.fetchall())

    assert _SCOUT_INDEX_NAME in defs, "the shipped MON-020 scout guarantee was dropped"
    assert '"agentKey"' in defs[_SCOUT_INDEX_NAME]
    assert "scout" in defs[_SCOUT_INDEX_NAME]
    # …and it constrains rows that never claimed, which is the whole point.
    assert "singletonKey" not in defs[_SCOUT_INDEX_NAME]
    assert _SINGLETON_INDEX_NAME in defs, "the claim rule is missing"
    assert '"singletonKey"' in defs[_SINGLETON_INDEX_NAME]


@pytest.mark.parametrize(
    "agent", ["submission", "emailAgent", "notification", "recruiterOutreach", "reference"]
)
def test_create_singleton_now_accepts_every_silo_agent(client, test_user_id, agent):
    repo = BackgroundJobRepository()
    first, created_first = repo.create_singleton(test_user_id, agent, params={})
    assert created_first is True
    second, created_second = repo.create_singleton(test_user_id, agent, params={})
    assert created_second is False
    assert second == first, "the second claim must return the run already in flight"


def test_create_singleton_still_refuses_a_non_silo_agent(client, test_user_id):
    repo = BackgroundJobRepository()
    with pytest.raises(ValueError):
        repo.create_singleton(test_user_id, "tailor", params={})


def test_a_singleton_index_from_an_earlier_build_is_replaced_not_kept(client) -> None:
    """A versioned NAME does not prove the RULE, and this is not hypothetical.

    An intermediate build of this branch created ``_SINGLETON_INDEX_NAME`` keyed
    ``("userId","agentKey")``; ``CREATE UNIQUE INDEX IF NOT EXISTS`` then kept it
    forever, and the deployment enforced the superseded rule while the code said
    otherwise. The visible symptom is worse than a stale index: an ordinary
    UNCLAIMED enqueue (a second ``emailAgent`` draft while triage is in flight)
    dies on a raw unique violation. So the DDL verifies the definition and
    replaces a mismatch — the state below is the exact one that failed.
    """
    from app.db import get_connection
    from app.repositories.background_jobs import _SINGLETON_INDEX_NAME

    # The superseded KEY COLUMNS are what the heal detects, so those are exact.
    # The PREDICATE is deliberately inert: this schema is shared with every other
    # branch's suite, and a genuine ``("userId","agentKey") WHERE status IN
    # (...)`` index cannot be built over whatever active rows they happen to
    # hold — a test that can only run when the neighbours are quiet is not a
    # gate. What the real predicate costs is proven separately and for real by
    # ``test_an_unclaimed_enqueue_is_never_blocked_by_the_claim_index``.
    superseded = (
        f'CREATE UNIQUE INDEX "{_SINGLETON_INDEX_NAME}" ON "BackgroundJob" '
        '("userId","agentKey") WHERE "agentKey" = \'__superseded_probe__\''
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP INDEX IF EXISTS "{_SINGLETON_INDEX_NAME}"')
            cur.execute(superseded)
        conn.commit()

    _reset_bg_ready_for_tests()
    _ensure_table()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_get_indexdef(c.oid) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = %s AND n.nspname = current_schema()",
                (_SINGLETON_INDEX_NAME,),
            )
            row = cur.fetchone()
    assert row is not None, (
        "the singleton index is gone — the replacement must leave the table "
        "protected, never merely un-broken"
    )
    assert '"singletonKey"' in row[0], (
        "the superseded (userId, agentKey) definition survived under the current "
        "name, so this deployment enforces a rule the code does not describe"
    )
