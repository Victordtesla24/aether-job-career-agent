"""B1c — story extractor corrective loop + rigor policy + learning signal.

ORCH-B1-BLUEPRINT-2026-08-14.md §3.3/§4.3/§6.1/§7.3. Pins, against the
pre-B1c tree (expected RED):

1. Validation criteria as DATA (``STORY_VALIDATION_CRITERIA``) — a
   fabricated-metric story fails the ``no_fabricated_metrics`` criterion.
2. A closed, ONE-bounded corrective retry: fires exactly once, carries the
   validator's own reason verbatim into the re-prompt, and a still-failing
   second pass is dropped honestly with BOTH reasons recorded — never a
   third attempt.
3. ``storyEvidenceStrictness`` ("standard"/"strict", B1b's whitelisted,
   consumer-less knob until now): standard persists-with-verdict, strict
   excludes with an honest note, at the SAME candidate.
4. Kill-switch / flag OFF ⇒ byte-identical baseline behaviour, additive
   output shape only (``policy_knobs`` stays optional, exactly like
   tailor/coverLetter's shipped ``{}`` == "use today's defaults" contract).
5. The learning signal: the loop outcome recorded onto an active
   ``storyEvidenceStrictness`` AgentDirective via the B1b repository's
   ``record_outcome`` hook.
6. The missed surface (resumes.py:352-363, the ONLY agent dispatched
   outside routers/agents.py): verdicts surface through the upload
   response, never swallowed into a bare ``{"error": ...}``.

Mocking idiom: the ``_StubLLM``/``_QueueLLM`` pattern already established by
``tests/test_story_narrative_grounding.py`` / ``tests/test_story_bank_rebuild.py``
(a fake object exposing ``complete_json(prompt_name, system, user, **kwargs)``,
injected via ``StoryExtractorAgent(llm=...)``) — extended here to a QUEUE of
payloads (one per call) so multi-call (first pass + corrective) behaviour is
observable, which the single-payload stub cannot express.

Run under the shared test-DB lock::

    flock -w 540 /tmp/aether-pytest.lock ./scripts/run-tests.sh \
        tests/test_b1c_story_corrective_loop.py -q -p no:randomly
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.db import get_connection


def _n_chars(base: str, n: int) -> str:
    """A string of EXACTLY ``n`` characters, starting with ``base`` — used to
    straddle the standard (40) / strict (raised) STAR-body minimum precisely,
    without the content itself mattering."""
    text = base
    while len(text) < n:
        text += " with additional detail supplied for length"
    return text[:n]


#: A résumé with ONE achievement bullet carrying a real, evidenced number
#: (30%) under one employer (ANZ) — small enough that
#: ``_BULLETS_PER_CALL=4`` always yields exactly ONE first-pass LLM call.
RESUME_TEXT = """VIKRAM DESHPANDE
WORK EXPERIENCE
Delivery Lead
ANZ
March 2022 - Present
Melbourne, VIC
•
Cut onboarding costs for the retail lending team by 30% through a
self-service documentation portal used across all five squads.
"""

#: A second bullet, no digits at all (non-quantified) — used by the
#: standard-vs-strict test so only the STAR body-length criterion differs
#: between tiers (the metric-evidence and organisation checks stay inert).
RESUME_TEXT_NONQUANT = """VIKRAM DESHPANDE
WORK EXPERIENCE
Delivery Lead
ANZ
March 2022 - Present
Melbourne, VIC
•
Led a full compliance review that satisfied every regulator across the
retail lending division without a single follow-up finding.
"""


def _story(**over: Any) -> dict[str, Any]:
    story = {
        "sourceBulletId": "B1",
        "organisation": "ANZ",
        "title": "Cutting onboarding costs 30% with a self-service portal",
        "situation": (
            "Retail lending onboarding required a specialist to walk every "
            "new starter through the same paperwork by hand, every single "
            "time, across all five squads."
        ),
        "task": (
            "I had to remove the recurring manual cost without adding "
            "headcount or slowing onboarding down for new starters."
        ),
        "action": (
            "I built a self-service documentation portal covering the "
            "whole onboarding flow and rolled it out to all five squads "
            "with a short walkthrough video."
        ),
        "result": (
            "Onboarding costs for the retail lending team fell by 30% and "
            "new starters no longer needed a specialist to get set up."
        ),
        "metrics": {"Onboarding cost reduction": "30%"},
        "tags": ["delivery"],
    }
    story.update(over)
    return story


def _fabricated_story(**over: Any) -> dict[str, Any]:
    """Same story, but claims a 50% reduction — a number the bullet (30%)
    does not evidence. This is the anti-fabrication guard's OWN failure
    mode, mirrored (not re-invented) for the corrective loop to catch."""
    defaults = {
        "metrics": {"Onboarding cost reduction": "50%"},
        "result": (
            "Onboarding costs for the retail lending team fell by 50% and "
            "new starters no longer needed a specialist to get set up."
        ),
    }
    defaults.update(over)
    return _story(**defaults)


class _QueueLLM:
    """A queue of canned ``complete_json`` payloads, one consumed per call.

    Extends (not replaces) the single-payload ``_StubLLM`` idiom already
    used by ``test_story_narrative_grounding.py`` / ``test_story_bank_rebuild.py``
    — same method signature, same injection point — generalised to a list so
    a test can observe DIFFERENT responses across the first pass and the ONE
    corrective retry, and assert on call count / per-call prompt content.
    """

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = list(payloads)
        self.calls: list[dict[str, str]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete_json(self, prompt_name: str, system: str, user: str, **kwargs: Any) -> Any:
        self.calls.append({"prompt_name": prompt_name, "system": system, "user": user})
        if self._payloads:
            return self._payloads.pop(0)
        return {"stories": []}


@pytest.fixture()
def extractor(monkeypatch: pytest.MonkeyPatch):
    """Factory: build a StoryExtractorAgent whose LLM returns ``payloads`` in
    order, one payload per ``complete_json`` call, against ``resume_text``."""
    from app.agents import story_extractor as module

    def build(payloads: list[list[dict[str, Any]]], resume_text: str = RESUME_TEXT):
        monkeypatch.setattr(
            module.StoryExtractorAgent,
            "_resolve_resume_text",
            staticmethod(lambda _user_id: resume_text),
        )
        stub = _QueueLLM([{"stories": p} for p in payloads])
        return module.StoryExtractorAgent(llm=stub), stub

    return build


@pytest.fixture()
def user_id():
    uid = f"t{uuid.uuid4().hex[:24]}"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "User" ("id","email","passwordHash","name","updatedAt")'
                " VALUES (%s,%s,%s,%s,NOW())",
                (uid, f"{uid}@b1c-story-loop.test", "x", "B1c Story Loop"),
            )
        conn.commit()
    yield uid
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "User" WHERE "id" = %s', (uid,))
        conn.commit()


# ---------------------------------------------------------------------------
# (a) Validation criteria as DATA
# ---------------------------------------------------------------------------


class TestValidationCriteriaAreData:
    def test_the_criteria_set_is_a_data_table(self) -> None:
        from app.agents.story_extractor import STORY_VALIDATION_CRITERIA

        assert isinstance(STORY_VALIDATION_CRITERIA, tuple)
        assert len(STORY_VALIDATION_CRITERIA) >= 4
        keys = [c.key for c in STORY_VALIDATION_CRITERIA]
        assert len(keys) == len(set(keys)), "criterion keys must be unique"
        for criterion in STORY_VALIDATION_CRITERIA:
            assert criterion.description  # human-readable, non-empty
            assert criterion.scope in ("story", "run")
            assert callable(criterion.check)

    def test_star_completeness_criterion_is_present(self) -> None:
        from app.agents.story_extractor import STORY_VALIDATION_CRITERIA

        assert any(c.key == "star_completeness" for c in STORY_VALIDATION_CRITERIA)

    def test_minimum_story_count_and_dedup_safety_criteria_are_present(self) -> None:
        from app.agents.story_extractor import STORY_VALIDATION_CRITERIA

        keys = {c.key for c in STORY_VALIDATION_CRITERIA}
        assert "minimum_story_count" in keys
        assert "dedup_safety" in keys

    def test_validator_catches_a_fabricated_metric_story(self) -> None:
        """(a) — a fixture story claiming a number (50%) absent from the
        source bullet (30%) must fail the no_fabricated_metrics criterion."""
        from app.agents.story_extractor import STORY_VALIDATION_CRITERIA, StoryCriteria

        criterion = next(
            c for c in STORY_VALIDATION_CRITERIA if c.key == "no_fabricated_metrics"
        )
        bullet = {
            "id": "B1",
            "text": (
                "Cut onboarding costs for the retail lending team by 30% "
                "through a self-service documentation portal."
            ),
            "employers": ["ANZ"],
        }
        story = _fabricated_story()
        reason = criterion.check(story, bullet, StoryCriteria())
        assert reason is not None
        assert "50" in reason

    def test_validator_passes_a_genuinely_evidenced_story(self) -> None:
        from app.agents.story_extractor import STORY_VALIDATION_CRITERIA, StoryCriteria

        criterion = next(
            c for c in STORY_VALIDATION_CRITERIA if c.key == "no_fabricated_metrics"
        )
        bullet = {
            "id": "B1",
            "text": (
                "Cut onboarding costs for the retail lending team by 30% "
                "through a self-service documentation portal."
            ),
            "employers": ["ANZ"],
        }
        assert criterion.check(_story(), bullet, StoryCriteria()) is None


# ---------------------------------------------------------------------------
# (b)/(c) The closed corrective loop
# ---------------------------------------------------------------------------


class TestCorrectiveLoop:
    def test_a_rejected_story_gets_exactly_one_corrective_attempt(
        self, extractor, user_id, monkeypatch
    ) -> None:
        monkeypatch.setenv("AETHER_AGI_STORY_CORRECTION", "true")
        agent, stub = extractor([[_fabricated_story()], [_story()]])
        result = agent.run(user_id, policy_knobs={})
        assert stub.call_count == 2, stub.calls
        assert result.corrective_retry_used is True
        assert result.created == 1, result.dropped

    def test_the_correction_carries_the_validators_own_reason(
        self, extractor, user_id, monkeypatch
    ) -> None:
        monkeypatch.setenv("AETHER_AGI_STORY_CORRECTION", "true")
        agent, stub = extractor([[_fabricated_story()], [_story()]])
        agent.run(user_id, policy_knobs={})
        assert stub.call_count == 2
        second_call_prompt = stub.calls[1]["user"]
        # The validator's OWN reason string names the fabricated number and
        # the source bullet id — verbatim, not paraphrased.
        assert "50" in second_call_prompt
        assert "B1" in second_call_prompt

    def test_a_story_still_rejected_after_correction_is_dropped_honestly(
        self, extractor, user_id, monkeypatch
    ) -> None:
        monkeypatch.setenv("AETHER_AGI_STORY_CORRECTION", "true")
        agent, stub = extractor(
            [[_fabricated_story()], [_fabricated_story(metrics={"Onboarding cost reduction": "70%"})]]
        )
        result = agent.run(user_id, policy_knobs={})
        # Bounded: exactly first pass + ONE corrective call, never a third.
        assert stub.call_count == 2, stub.calls
        assert result.created == 0
        assert result.criteria_failed_final == 1
        assert result.excluded_count == 1
        combined = " ".join(result.dropped)
        # BOTH reasons recorded — the original fabrication (50) AND the
        # still-failing corrective attempt's own fabrication (70).
        assert "50" in combined
        assert "70" in combined

    def test_correction_never_runs_before_first_pass_coverage(
        self, extractor, user_id, monkeypatch
    ) -> None:
        """R3 bound 1: a two-bullet résumé must have BOTH bullets attempted
        in the first pass before any corrective call fires."""
        monkeypatch.setenv("AETHER_AGI_STORY_CORRECTION", "true")
        two_bullet_resume = RESUME_TEXT + (
            "•\nRolled out a compliance dashboard adopted by all eight "
            "squads within one quarter.\n"
        )
        agent, stub = extractor(
            [[_fabricated_story()], [_story()]], resume_text=two_bullet_resume
        )
        agent.run(user_id, policy_knobs={})
        # First call must have been asked about BOTH bullets (B1 and B2),
        # proving the corrective call (call #2) was not interleaved before
        # bullet 2 was even attempted.
        assert "B1" in stub.calls[0]["user"]
        assert "B2" in stub.calls[0]["user"]

    def test_correction_is_skipped_when_flag_is_off(
        self, extractor, user_id, monkeypatch
    ) -> None:
        monkeypatch.delenv("AETHER_AGI_STORY_CORRECTION", raising=False)
        agent, stub = extractor([[_fabricated_story()], [_story()]])
        result = agent.run(user_id, policy_knobs={})
        assert stub.call_count == 1, stub.calls
        assert result.corrective_retry_used is False
        assert result.created == 0


# ---------------------------------------------------------------------------
# (d) standard vs strict
# ---------------------------------------------------------------------------


class TestStrictnessPolicy:
    def _borderline_story(self) -> dict[str, Any]:
        body = _n_chars("Led a full compliance review across ANZ retail lending.", 45)
        return {
            "sourceBulletId": "B1",
            "organisation": "ANZ",
            "title": "Compliance review across retail lending",
            "situation": body,
            "task": body,
            "action": body,
            "result": body,
            "metrics": {},
            "tags": [],
        }

    def test_standard_persists_with_verdict(self, extractor, user_id) -> None:
        agent, stub = extractor(
            [[self._borderline_story()]], resume_text=RESUME_TEXT_NONQUANT
        )
        result = agent.run(user_id, policy_knobs={})
        assert result.created == 1, result.dropped
        assert result.strictness_applied == "standard"
        assert result.excluded_count == 0

    def test_strict_excludes_the_same_story_with_an_honest_note(
        self, extractor, user_id
    ) -> None:
        agent, stub = extractor(
            [[self._borderline_story()]], resume_text=RESUME_TEXT_NONQUANT
        )
        result = agent.run(
            user_id, policy_knobs={"storyEvidenceStrictness": "strict"}
        )
        assert result.created == 0, result.story_ids
        assert result.strictness_applied == "strict"
        assert result.excluded_count == 1
        assert result.dropped, "strict exclusion must carry an honest note"

    def test_strict_only_narrows_never_accepts_something_standard_rejects(
        self, extractor, user_id
    ) -> None:
        """The ratchet property: anything strict accepts, standard also
        accepts (never the reverse). ``_story()`` is fully evidenced and well
        over both tiers' STAR-body floors, so BOTH tiers must accept it."""
        agent, _ = extractor([[_story()]])
        strict_result = agent.run(
            user_id, policy_knobs={"storyEvidenceStrictness": "strict"}
        )
        assert strict_result.created == 1, strict_result.dropped


# ---------------------------------------------------------------------------
# (e) kill-switch / flag OFF backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_no_policy_knobs_argument_still_works(self, extractor, user_id) -> None:
        """The pre-B1c call convention — ``agent.run(user_id)`` with NO
        keyword arguments at all — must still work unchanged."""
        agent, stub = extractor([[_story()]])
        result = agent.run(user_id)
        assert result.created == 1, result.dropped
        assert result.strictness_applied == "standard"
        assert result.corrective_retry_used is False

    def test_empty_knobs_reproduce_todays_behaviour_exactly(
        self, extractor, user_id, monkeypatch
    ) -> None:
        monkeypatch.delenv("AETHER_AGI_STORY_CORRECTION", raising=False)
        agent, stub = extractor([[_story(), _fabricated_story(sourceBulletId="B1")]])
        result = agent.run(user_id, policy_knobs={})
        assert stub.call_count == 1
        # Exactly one story persisted (the valid one); the fabricated one is
        # dropped with its ORIGINAL reason, untouched by any corrective
        # wording (the flag is off, so no correction occurs).
        assert result.created == 1, result.dropped
        combined = " ".join(result.dropped)
        assert "still failing after" not in combined
        assert "excluded under" not in combined

    def test_output_shape_is_additive_only(self, extractor, user_id) -> None:
        from dataclasses import fields
        from app.agents.story_extractor import StoryExtractionResult

        pre_b1c_fields = {"created", "dropped", "story_ids", "bullets", "merged", "stripped"}
        current_fields = {f.name for f in fields(StoryExtractionResult)}
        assert pre_b1c_fields <= current_fields, "no pre-existing field was removed/renamed"


# ---------------------------------------------------------------------------
# (f) the learning signal
# ---------------------------------------------------------------------------


class TestLearningSignal:
    def test_the_outcome_is_recorded_on_the_result(self, extractor, user_id) -> None:
        agent, _ = extractor([[_fabricated_story()]])
        result = agent.run(user_id, policy_knobs={})
        assert result.criteria_failed_first_pass == 1
        assert result.criteria_failed_final == 1
        assert result.corrective_retry_used is False
        assert result.strictness_applied == "standard"
        assert result.excluded_count == 1

    def test_directive_outcome_is_recorded_when_a_directive_was_active(
        self, extractor, user_id
    ) -> None:
        from app.repositories.agent_directive import AgentDirectiveRepository

        repo = AgentDirectiveRepository()
        directive_id = repo.issue(
            user_id,
            "storyExtractor",
            directive={"storyEvidenceStrictness": "strict"},
            rationale="test: hold the line on evidence",
            metrics_cited={"storyCount": 0},
        )
        agent, _ = extractor([[_story()]])
        agent.run(user_id, policy_knobs={"storyEvidenceStrictness": "strict"})
        history = repo.list_history(user_id, "storyExtractor")
        record = next(d for d in history if d["id"] == directive_id)
        assert record["outcome"] is not None
        assert "strictnessApplied" in record["outcome"]
        assert record["outcome"]["strictnessApplied"] == "strict"

    def test_no_outcome_write_when_no_directive_amended_this_run(
        self, extractor, user_id
    ) -> None:
        """A directive existing for a DIFFERENT field, or none at all, must
        never receive a fabricated outcome record."""
        from app.repositories.agent_directive import AgentDirectiveRepository

        repo = AgentDirectiveRepository()
        agent, _ = extractor([[_story()]])
        # No policy_knobs carrying storyEvidenceStrictness at all -> nothing
        # to attribute an outcome to.
        agent.run(user_id, policy_knobs={})
        history = repo.list_history(user_id, "storyExtractor")
        assert history == []


# ---------------------------------------------------------------------------
# (g) the missed surface — resumes.py upload path
# ---------------------------------------------------------------------------


class TestUploadPathSurfacesVerdicts:
    def _set_plan(self, user_id: str) -> None:
        from app.repositories.billing import ensure_user_billing

        ensure_user_billing(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                    'WHERE "userId"=%s',
                    ("pro", "active", user_id),
                )
                cur.execute(
                    'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=100,'
                    '"updatedAt"=now() WHERE "userId"=%s',
                    ("pro", user_id),
                )
            conn.commit()

    def test_the_upload_path_resolves_knobs_through_the_same_dispatch(
        self, client, auth_headers, test_user_id, monkeypatch
    ) -> None:
        """resumes.py:352-363 must call the same ``_dispatch`` binding as
        the agent route — proven by asserting the storyExtractor binding now
        receives ``policy_knobs`` (previously it received none at all)."""
        from app.agents.story_extractor import StoryExtractorAgent

        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        self._set_plan(test_user_id)

        seen: dict[str, Any] = {}
        real_run = StoryExtractorAgent.run

        def _spy(self, user_id, *, policy_knobs=None, **kwargs):
            seen["policy_knobs"] = policy_knobs
            return real_run(self, user_id, policy_knobs=policy_knobs, **kwargs)

        monkeypatch.setattr(StoryExtractorAgent, "run", _spy)
        res = client.post(
            "/resumes/upload",
            files={"file": ("r.txt", RESUME_TEXT.encode(), "text/plain")},
            data={"extract_stories": "true"},
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text
        # Pre-B1c the binding called ``.run(user_id)`` with NO keyword at
        # all, so the spy's own default (``None``) would be what lands here.
        # Post-B1c the binding resolves ``_policy_knobs(params)`` (always a
        # dict, ``{}`` at minimum) and passes it explicitly — a dict, never
        # None, is the honest signal that knob resolution now happens on
        # THIS call site exactly like tailor/coverLetter's.
        assert isinstance(seen.get("policy_knobs"), dict), seen

    def test_verdicts_surface_in_the_upload_response_not_swallowed(
        self, client, auth_headers, test_user_id, monkeypatch
    ) -> None:
        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        self._set_plan(test_user_id)
        res = client.post(
            "/resumes/upload",
            files={"file": ("r.txt", RESUME_TEXT.encode(), "text/plain")},
            data={"extract_stories": "true"},
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text
        extraction = res.json()["storyExtraction"]
        assert extraction is not None
        assert "error" not in extraction
        # The B1c learning-signal fields are present on the SUCCESS path —
        # not swallowed into a bare {"error": ...}.
        assert "strictnessApplied" in extraction or "strictness_applied" in extraction

    def test_a_genuine_extractor_failure_still_swallows_with_more_honesty(
        self, client, auth_headers, test_user_id, monkeypatch
    ) -> None:
        """The existing swallow contract (test_resume_upload.py) stays —
        but the error now also names the exception TYPE, so a loop failure
        is never LESS diagnosable than before."""
        from app.agents.story_extractor import StoryExtractorAgent

        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        self._set_plan(test_user_id)

        def _boom(self, user_id, **kwargs):
            raise RuntimeError("synthetic b1c failure")

        monkeypatch.setattr(StoryExtractorAgent, "run", _boom)
        res = client.post(
            "/resumes/upload",
            files={"file": ("r.txt", RESUME_TEXT.encode(), "text/plain")},
            data={"extract_stories": "true"},
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text
        extraction = res.json()["storyExtraction"]
        assert extraction["error"] == "synthetic b1c failure"
        assert extraction.get("errorType") == "RuntimeError"
