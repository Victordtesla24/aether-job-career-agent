"""Story extractor agent — SOURCE-GROUNDED STAR entries from the user's résumé.

Uses the STRUCTURED model tier through the record-replay LLM client.

STORY-BANK-REBUILD-2026-08-02
-----------------------------
This agent used to hand the model the whole résumé and accept whatever STAR
stories came back, keeping any story whose metric numbers appeared ANYWHERE in
the résumé and deduping on title equality. Audited live on the production DB,
that produced 43 story rows describing only ~10 distinct achievements (33
near-duplicate re-tellings — four separate rows for the single "JIRA Analytics
Dashboard" bullet alone), two of them with no metric at all, while ~17 real
résumé achievements had no story whatsoever. A Story Bank in that state is not
reusable material for tailoring and cover letters; it is noise that crowds out
the evidence the downstream agents actually need.

Three things changed, and every one of them makes the output MORE grounded,
never less:

1. CITED EVIDENCE. The résumé is split deterministically into its real
   achievement bullets (``app.services.resume_bullets``), each with a stable
   ``B<n>`` handle. Every story must cite exactly one of them. A story citing
   an unknown handle is dropped — the model can no longer produce a story
   about an achievement the résumé does not contain.
2. METRICS SCOPED TO THEIR OWN BULLET. The old guard accepted any number found
   anywhere in the résumé, so a war-room story could "evidence" the 92% effort
   reduction that belongs to a completely different bullet. Numbers are now
   checked against THE CITED BULLET only. And when the cited bullet DOES carry
   numbers, the story must carry at least one metric: an unquantified story
   drawn from a quantified bullet is throwing away the evidence that makes it
   usable.
3. DETERMINISTIC DEDUP. Each story is stamped with the per-user
   ``achievementKey`` of its cited bullet, so a reworded re-telling of the same
   achievement UPDATES the existing row instead of inserting a duplicate —
   no matter how far the title drifts. The repository enforces it
   (``StoryRepository.create`` layer 0) and so does a partial unique index
   (``app.db.ensure_story_achievement_column``).

The anti-fabrication posture is unchanged in direction and strictly tightened
in degree: nothing here loosens a check, and no number, organisation or claim
is ever accepted that the user's own résumé does not evidence.

STORY-NARRATIVE-GROUNDING-2026-08-03
------------------------------------
Everything above validated the ``metrics`` DICT. The agents that consume the
Story Bank — ``tailor_agent.build_story_evidence`` and the cover-letter
evidence block — read the STAR PROSE, not ``metrics``. So the guard was
pointed at a field the consumers ignore, and the prose was completely
unchecked. Audited live on the production DB (17 stories, the owner's own
résumé, ``scripts/story_narrative_audit.py``):

* 15 of 17 carried a number in situation/task/action/result that their OWN
  cited bullet does not evidence;
* 7 of 17 carried a number that appears NOWHERE in the résumé —
  "MTTR from 4.2 hours to 3.8 hours", "234 architectural decisions",
  "120+ regulatory obligations", "37 missing controls".

The narrative is now held to the same standard the metrics dict already was,
with the remedy graded by what the failure actually proves:

* FABRICATED (the number appears nowhere in the résumé) — the story is
  REJECTED. A model that invented a measurement has proven it will assert
  things the évidence does not contain, so the unverifiable prose around it is
  not salvageable either.
* BORROWED (the number is real but belongs to a DIFFERENT bullet) — the one
  sentence carrying it is STRIPPED, nothing is rewritten, and the story is
  rejected anyway if what survives is too thin to be usable. Stripping keeps a
  genuinely grounded story instead of discarding the bullet's only coverage
  over a misattributed clause; the claim itself never survives.
* A TITLE has no sentences to strip, so an unevidenced number there rejects
  the story.

And the organisation check no longer asks "does this string occur anywhere in
the résumé" (which any past employer, university or skill satisfies for any
bullet) but "is this the employer of the section the CITED BULLET sits in".

STORY-ORG-SUBSTRING-2026-08-03
-----------------------------
Binding the organisation to the cited bullet was right; the comparison behind
it was not. ``organisation_matches`` tested ``wanted in known or known in
wanted`` over the space-delimited name — still a substring test, just a
word-bounded one. So an organisation whose name is a word-run INSIDE a genuine
employer's name, or that CONTAINS one, passed the guard: on the owner's own
résumé that accepted "ANZ Stadium" and "Australia Bank" for the ANZ bullets,
"Australian Taxation" for the ATO bullets, and "Telstra Super Pty Ltd" for the
Telstra bullets — a foreign employer for all 21 of its bullets. A guard that
looks bound and is not is worse than none, because the claim ships labelled
"grounded". Names are now compared as whole normalized token sequences
(identity, not containment), and the no-header fallback is word-bound too.

B1C-CORRECTIVE-LOOP-2026-08-14 (ORCH-B1-BLUEPRINT-2026-08-14.md §3.3/§4.3/§6.1)
---------------------------------------------------------------------------
Three additions, all additive to the guard above, never a relaxation of it:

1. VALIDATION CRITERIA AS DATA (``STORY_VALIDATION_CRITERIA``). The STAR
   length floor and the metrics-evidence check that already gated
   acceptance are factored into small, named, independently-testable
   functions and registered in a module-level table — adding a criterion is
   a data change, not a new branch (the binding U-AGI design law).
2. ONE BOUNDED CORRECTIVE RETRY (``AETHER_AGI_STORY_CORRECTION``, default
   OFF). After the FULL first pass over every résumé chunk (never
   interleaved — a résumé's later bullets must never go unattempted because
   an earlier one needed fixing), any story a validator rejected gets ONE
   re-prompt carrying the validator's OWN reason back to the model verbatim.
   Still-failing after that is dropped honestly, with BOTH reasons on
   record — never a second corrective attempt, and never silently accepted.
   Gated by the identical budget floor (``_MIN_CHUNK_SECONDS``) the first
   pass already uses, so a résumé upload (the ONLY other call site — see
   ``routers/resumes.py``) can never be pushed over its edge budget by this.
3. ``storyEvidenceStrictness`` ("standard"/"strict", whitelisted by B1b in
   ``services/agent_directives.py`` but consumer-less until now) is
   consumed here: it can only NARROW acceptance (a higher STAR-body floor,
   and — when a bullet carries no employer header of its own — no
   résumé-wide fallback match), never loosen it. With no directive active,
   or with the B1b directive kill switch off, the resolved knobs never
   carry this key and behaviour is standard-tier, byte-identical to the
   pre-B1c guard.

The learning signal (ADR-AGI-2's outcome/efficacy substrate): every run
records {criteria_failed_first_pass, corrective_retry_used,
criteria_failed_final, strictness_applied, excluded_count} on its OWN
result (so ``AgentRun.output`` — and, if a directive amended THIS run's
strictness, ``AgentDirective.outcome`` via the B1b repository's
``record_outcome`` hook) — never a new write path, never touching a
directive's immutable ``directive``/``rationale``.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.repositories.story import StoryRepository
from app.services.llm_client import (
    LLMClient,
    LLMUnavailableError,
    get_budget_seconds,
    get_model,
    remaining_budget_seconds,
    shared_budget,
)
from app.services.resume_bullets import (
    achievement_key,
    bullet_numbers,
    claim_numbers,
    extract_resume_bullets,
    find_bullet,
    is_quantified,
    organisation_appears_in_text,
    organisation_matches,
    resume_employers,
    strip_unevidenced_sentences,
    unevidenced_claims,
)
from app.services.resume_grounding import resolve_user_resume_text

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a career-story analyst. You are given a candidate's résumé and a "
    "numbered list of the achievement bullets it contains. Write ONE STAR "
    "(Situation, Task, Action, Result) interview story for EACH bullet you can "
    "support, and cite that bullet's id in sourceBulletId.\n"
    "HARD RULES — a story breaking any of these is discarded:\n"
    "1. Every story cites exactly one bullet id from the list. Never merge two "
    "bullets into one story and never write two stories for one bullet.\n"
    "2. Every number in metrics MUST appear in the cited bullet. Never invent, "
    "round, extrapolate or borrow a number from another bullet.\n"
    "3. If the cited bullet contains numbers, the story MUST carry at least "
    "one metric drawn from them.\n"
    "3b. EVERY number in the title, situation, task, action and result must "
    "also appear in the cited bullet. Do not add durations, counts, dates, "
    "percentages or team sizes the bullet does not state, and do not borrow "
    "them from another bullet — write those parts without numbers instead.\n"
    "4. organisation must be the employer/client named in the résumé for that "
    "bullet, spelled exactly as the résumé spells it.\n"
    "5. Write in the first person, past tense, concrete and specific. Each of "
    "situation, task, action and result must be a full, self-contained "
    "paragraph of at least 40 characters — no fragments, no placeholders.\n"
    "Respond with JSON: "
    '{"stories": [{"sourceBulletId": "B1", "organisation": "...", '
    '"title": "...", "situation": "...", "task": "...", "action": "...", '
    '"result": "...", "metrics": {"...": "..."}, "tags": ["..."]}]}'
)

#: B1c: the corrective-retry system prompt (§3.3). Same HARD RULES as
#: ``SYSTEM_PROMPT`` — correction narrows nothing about what counts as
#: evidenced, it only gets ONE more attempt at meeting the same bar.
_CORRECTION_SYSTEM_PROMPT = (
    "You are a career-story analyst correcting your own PREVIOUS attempt at "
    "some STAR (Situation, Task, Action, Result) stories. Each one below was "
    "REJECTED by an automated validator, which told you exactly why. Rewrite "
    "ONLY the stories listed, fixing EXACTLY the stated problem — the same "
    "HARD RULES as before still apply in full:\n"
    "1. Cite exactly one bullet id in sourceBulletId — the one you were "
    "asked to correct.\n"
    "2. Every number in metrics, and every number anywhere in the title, "
    "situation, task, action and result, MUST appear in the cited bullet. "
    "Never invent, round, extrapolate or borrow a number from another "
    "bullet or from anywhere else in the résumé — this is the single most "
    "common reason a story is rejected.\n"
    "3. If the cited bullet contains numbers, the story MUST carry at least "
    "one metric drawn from them.\n"
    "4. organisation must be the employer/client named in the résumé for "
    "that bullet, spelled exactly as the résumé spells it.\n"
    "5. Each of situation, task, action and result must be a full, "
    "self-contained paragraph of at least 40 characters.\n"
    "If a number cannot be evidenced, remove it and describe the outcome "
    "in words instead of inventing a figure to replace it.\n"
    "Respond with JSON: "
    '{"stories": [{"sourceBulletId": "B1", "organisation": "...", '
    '"title": "...", "situation": "...", "task": "...", "action": "...", '
    '"result": "...", "metrics": {"...": "..."}, "tags": ["..."]}]}'
)

_STAR_FIELDS = ("title", "situation", "task", "action", "result")

#: The prose fields a sentence can be stripped from. ``title`` is deliberately
#: absent: it is a single unit, so there is nothing to remove short of the
#: whole story.
_BODY_FIELDS = ("situation", "task", "action", "result")

#: Minimum length of each STAR body field. Below this a "story" is a fragment
#: that cannot ground a cover-letter paragraph or answer an interview
#: question — the two things the Story Bank exists to feed.
_MIN_BODY_CHARS = 40
_MIN_TITLE_CHARS = 10

#: Control keys stored inside ``metrics`` that are flags, not evidence
#: (mirrors ``app.routers.stories._RESERVED_METRIC_KEYS``).
_RESERVED_METRIC_KEYS = {"__starred"}

#: Résumé bullets per LLM call. Extraction used to demand every story in ONE
#: response; on the owner's real 21-bullet résumé that call blew the live
#: wall-clock budget outright (``LLMUnavailableError: exceeded hard budget of
#: 38.7s``) and produced nothing at all. Small batches keep each response short
#: enough to finish and to stay well clear of a token-limit truncation, and
#: they make the run PARTIALLY successful under pressure — a failed batch costs
#: its own four bullets, not the entire Story Bank.
_BULLETS_PER_CALL = 4

#: Don't start another batch with less than this left in the window: firing a
#: call that cannot finish burns budget and returns nothing.
_MIN_CHUNK_SECONDS = 15.0

#: B1c: the strict evidence policy's raised STAR-body floor
#: (ORCH-B1-BLUEPRINT-2026-08-14.md §6.1 — "strict raises the STAR body
#: minimum"). Title minimum is unchanged: narrowing an already-short title
#: buys no additional evidence-grounding.
_STRICT_MIN_BODY_CHARS = 60

#: Env values that keep the corrective retry OFF — same convention as
#: ``routers/agents.py``'s ``_ASYNC_OFF``/``_DIRECTIVES_OFF`` (read at call
#: time so a hot env change takes effect and no flag is baked into source).
_STORY_CORRECTION_OFF = frozenset({"false", "0", "no", "off", ""})


def story_correction_enabled() -> bool:
    """Whether the ONE bounded corrective retry (B1c) may run.

    Code default OFF (``AETHER_AGI_STORY_CORRECTION``,
    ORCH-B1-BLUEPRINT-2026-08-14.md §9.1). OFF skips the corrective pass
    only — knob consumption (criteria/strictness) still applies, because the
    live honesty defect it closes (§4.3: the run recorded a policyTier it
    never obeyed) is not behind this cost flag.
    """
    return os.environ.get(
        "AETHER_AGI_STORY_CORRECTION", "false"
    ).strip().lower() not in _STORY_CORRECTION_OFF


@dataclass(frozen=True)
class StoryCriteria:
    """Validation thresholds as DATA (§3.3). ``standard`` reproduces today's
    shipped constants exactly; ``strict`` may only narrow them."""

    min_title_chars: int = _MIN_TITLE_CHARS
    min_body_chars: int = _MIN_BODY_CHARS
    strictness: str = "standard"
    #: strict-only: when a bullet carries no employer header of its own,
    #: reject rather than falling back to a résumé-wide organisation match.
    require_own_employer: bool = False


def _field_length_reason(story: dict[str, Any], criteria: "StoryCriteria") -> str | None:
    """STAR completeness: every field present and at least ``criteria``'s
    minimum length. The SAME function backs both ``_reject_reason`` (the
    acceptance gate) and the ``star_completeness`` table entry below — one
    definition, never two that could drift apart."""
    for field_name in _STAR_FIELDS:
        value = str(story.get(field_name) or "").strip()
        minimum = (
            criteria.min_title_chars if field_name == "title" else criteria.min_body_chars
        )
        if len(value) < minimum:
            return (
                f"{field_name} is {len(value)} chars, under the "
                f"{minimum}-char minimum"
            )
    return None


def _metric_evidence_reason(story: dict[str, Any], bullet: dict[str, Any]) -> str | None:
    """No fabricated metrics: every quantified claim in ``metrics`` must be
    evidenced by the CITED bullet — mirrors the fabrication guard's own
    source-grounding shape, reusing ``bullet_numbers``/``claim_numbers``
    rather than re-deriving a second definition of "evidenced"."""
    metrics = StoryExtractorAgent._evidence_metrics(story.get("metrics"))
    evidenced = bullet_numbers(bullet["text"])
    for key, value in metrics.items():
        for number in claim_numbers(f"{key} {value}"):
            if number not in evidenced:
                return (
                    f"metric {key!r}={value!r} uses {number!r}, which is not "
                    f"evidenced by source bullet {bullet['id']}"
                )
    return None


def _check_minimum_story_count(
    stories: list[dict[str, Any]],
    bullets_total: int,
    achievement_keys: list[str],
    criteria: "StoryCriteria",
) -> str | None:
    """Run-level sanity, never a persistence gate: a résumé that HAD
    achievement bullets should not walk away with zero accepted stories."""
    if bullets_total and not stories:
        return f"0 stories accepted from {bullets_total} available bullet(s)"
    return None


def _check_dedup_safety(
    stories: list[dict[str, Any]],
    bullets_total: int,
    achievement_keys: list[str],
    criteria: "StoryCriteria",
) -> str | None:
    """Run-level: confirms the extractor never handed the dedup layer
    (``StoryRepository.create``, ADR-GMV4-STORY-DEDUP-SAFETY) two stories
    for the same achievement in one run — the invariant the repository and
    its partial unique index both already enforce; this is a self-check,
    never a second, competing enforcement path."""
    if len(achievement_keys) != len(set(achievement_keys)):
        return "two stories persisted in this run share the same achievementKey"
    return None


@dataclass(frozen=True)
class StoryValidationCriterion:
    """One entry in the validation table (§3.3 / DESIGN-PRINCIPLE.md:
    "validation criteria = DATA, not bespoke branching"). ``scope`` selects
    the calling convention: ``"story"`` checks receive
    ``(story, bullet, criteria)``; ``"run"`` checks receive
    ``(stories, bullets_total, achievement_keys, criteria)``. Adding a
    criterion is adding a row here — never a new branch in ``run()``."""

    key: str
    description: str
    scope: str  # "story" | "run"
    check: Callable[..., str | None]


#: THE validation criteria table. Extending validation is a data change —
#: add a row, never a bespoke branch in ``run()`` (the binding U-AGI design
#: law: DESIGN-PRINCIPLE.md).
STORY_VALIDATION_CRITERIA: tuple[StoryValidationCriterion, ...] = (
    StoryValidationCriterion(
        key="star_completeness",
        description=(
            "Situation, Task, Action and Result are each present and meet "
            "the active minimum length."
        ),
        scope="story",
        check=lambda story, bullet, criteria: _field_length_reason(story, criteria),
    ),
    StoryValidationCriterion(
        key="no_fabricated_metrics",
        description=(
            "Every quantified claim in `metrics` is evidenced by the cited "
            "source bullet — mirrors the anti-fabrication guard's "
            "source-grounding check."
        ),
        scope="story",
        check=lambda story, bullet, criteria: _metric_evidence_reason(story, bullet),
    ),
    StoryValidationCriterion(
        key="minimum_story_count",
        description=(
            "At least one story is accepted when the résumé has achievement "
            "bullets to draw from."
        ),
        scope="run",
        check=_check_minimum_story_count,
    ),
    StoryValidationCriterion(
        key="dedup_safety",
        description=(
            "No two stories persisted in one run collide on the same "
            "achievementKey (ADR-GMV4-STORY-DEDUP-SAFETY)."
        ),
        scope="run",
        check=_check_dedup_safety,
    ),
)


@dataclass
class _Rejection:
    """One first-pass (or still-failing post-correction) validation
    failure, carrying everything a corrective re-prompt needs: the bullet
    it cites, the model's own candidate, the validator's OWN reason text
    (fed back verbatim, never paraphrased), and WHERE its message lives in
    ``result.dropped`` so a later fix can remove it cleanly without
    disturbing any other message's order."""

    bullet: dict[str, Any]
    story: dict[str, Any]
    reason: str
    dropped_index: int


@dataclass
class StoryExtractionResult:
    created: int = 0
    dropped: list[str] = field(default_factory=list)
    story_ids: list[str] = field(default_factory=list)
    #: How many résumé bullets were available to write stories from. Makes the
    #: run self-auditing: ``created`` far below this means the model under-
    #: covered the résumé, not that the résumé was thin.
    bullets: int = 0
    #: Bullets that already had a live story and were refreshed rather than
    #: duplicated (the dedup layer doing its job, reported honestly).
    merged: int = 0
    #: Sentences removed from a KEPT story because they carried a number that
    #: belongs to a different bullet. Reported, never silent: the stored story
    #: is not verbatim what the model wrote and the operator must be able to
    #: see exactly what was taken out and why.
    stripped: list[str] = field(default_factory=list)
    # -- B1c additions (additive only — StoryExtractionResult is a dataclass;
    #    _to_output()/asdict() adds these as NEW keys, never renaming or
    #    removing any of the six fields above) -----------------------------
    #: {criterion_key: None-if-passed-else-an-honest-reason}, evaluated once
    #: at the end of the run over the STORIES ACTUALLY PERSISTED.
    criteria_verdicts: dict[str, str | None] = field(default_factory=dict)
    #: Whether the ONE bounded corrective retry actually fired this run.
    corrective_retry_used: bool = False
    #: Validator rejections observed on the first pass, before correction.
    criteria_failed_first_pass: int = 0
    #: Validator rejections still standing after the (possible) correction.
    criteria_failed_final: int = 0
    #: "standard" | "strict" — the strictness this run actually applied.
    strictness_applied: str = "standard"
    #: Stories excluded from persistence for failing validation (== the
    #: final failure count; a distinct field per the B1c learning-signal
    #: contract, kept in step with ``criteria_failed_final`` by construction).
    excluded_count: int = 0


class StoryExtractorAgent:
    def __init__(
        self, llm: LLMClient | None = None, stories: StoryRepository | None = None
    ) -> None:
        self._llm = llm or LLMClient()
        self._stories = stories or StoryRepository()

    def run(
        self,
        user_id: str,
        *,
        policy_knobs: Mapping[str, Any] | None = None,
    ) -> StoryExtractionResult:
        """UNCHANGED default behaviour when ``policy_knobs`` is ``None``/
        ``{}`` — the exact contract tailor/coverLetter already have (``{}``
        means "use the callee's shipped defaults", ``agents.py:2298-2309``).
        ``policy_knobs["storyEvidenceStrictness"]`` (B1b, whitelisted) may
        only NARROW acceptance; its absence is standard-tier, byte-identical
        to the pre-B1c guard."""
        resume_text = self._resolve_resume_text(user_id)
        bullets = extract_resume_bullets(resume_text)
        result = StoryExtractionResult(bullets=len(bullets))
        if not bullets:
            # An honest empty result — the user has no résumé of their own, or
            # it contains no achievement bullets. Never fall back to another
            # résumé and never emit a story with no evidence behind it.
            result.dropped.append(
                "no achievement bullets found in the user's own resume"
            )
            return result

        criteria = self._criteria(policy_knobs)
        resume_lower = resume_text.lower()
        #: Every number the résumé states ANYWHERE. A narrative number outside
        #: this set was invented outright; one inside it but outside the cited
        #: bullet was borrowed from another achievement. The two get different
        #: remedies (see the module docstring), so both sets are needed.
        resume_numbers = bullet_numbers(resume_text)
        #: Every employer the résumé names anywhere. Used ONLY for a bullet
        #: whose own section yielded no header — never to widen a bullet that
        #: does know its employer.
        all_employers = resume_employers(resume_text)
        existing_ids = {s["id"] for s in self._stories.list_by_user(user_id)}
        covered = self._stories.live_achievement_keys(user_id)
        seen_keys: set[str] = set()
        candidates: list[Any] = []
        last_error: LLMUnavailableError | None = None
        succeeded = 0
        #: (grounded_story, achievementKey, bullet) for everything that
        #: passed validation — persisted once the whole loop (first pass +
        #: optional correction) is settled.
        to_persist: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
        rejections: list[_Rejection] = []
        corrective_retry_used = False
        criteria_failed_first_pass = 0

        # ONE window for the whole run, never shrinking a MORE generous one the
        # caller already granted (``not_below_active`` — GAP-P7-COV-WORKER-001:
        # an agent that opens its own edge-tuned window inside the async
        # worker's 300/480 s budget starves itself down to the HTTP number).
        with shared_budget(get_budget_seconds(), not_below_active=True):
            for chunk in self._chunks(bullets, covered, user_id):
                if succeeded and remaining_budget_seconds() < _MIN_CHUNK_SECONDS:
                    # Honest partial coverage, not a silent truncation. Re-running
                    # is safe and additive: the achievement key makes an already
                    # covered bullet refresh in place, and uncovered bullets are
                    # attempted FIRST, so consecutive runs converge on the whole
                    # résumé instead of redoing the same few bullets.
                    result.dropped.append(
                        "LLM budget exhausted before source bullets "
                        f"{', '.join(b['id'] for b in chunk)} — re-run the "
                        "extractor to cover them"
                    )
                    continue
                try:
                    raw = self._llm.complete_json(
                        "story_extractor",
                        SYSTEM_PROMPT,
                        self._build_prompt(resume_text, chunk),
                        model=get_model("STRUCTURED"),
                        temperature=0.0,
                    )
                except LLMUnavailableError as exc:
                    last_error = exc
                    result.dropped.append(
                        f"LLM unavailable for source bullets "
                        f"{', '.join(b['id'] for b in chunk)}: {exc}"
                    )
                    if not exc.retryable:
                        # CRITICAL-3: a non-retryable refusal (402 out of
                        # credits / 401 bad key) answers the question for the
                        # WHOLE run — every remaining chunk would present the
                        # same credential to the same provider and be refused
                        # the same way. Stop, and say so in `dropped` (which is
                        # surfaced on the run record) instead of walking the
                        # rest of the résumé one paid-API refusal at a time.
                        result.dropped.append(
                            f"stopped after a non-retryable provider refusal "
                            f"({exc.failure_class}); remaining source bullets "
                            "were not attempted"
                        )
                        break
                    continue
                batch = raw.get("stories") if isinstance(raw, dict) else None
                if not isinstance(batch, list):
                    result.dropped.append(
                        "model response for source bullets "
                        f"{', '.join(b['id'] for b in chunk)} carried no "
                        "'stories' array"
                    )
                    continue
                succeeded += 1
                candidates.extend(batch)

            if not succeeded and last_error is not None:
                # EVERY call failed: this is a real outage, not a thin résumé.
                # Raise so the run is recorded as failed and the reserved
                # quota refunded, instead of reporting a successful
                # extraction of nothing. Still inside the budget window —
                # exiting via an exception unwinds it exactly like a normal
                # return (the ``with`` block's own ``finally``).
                raise last_error

            # -- first pass: validate every candidate (R3 bound 1 — this runs
            # ONLY after every chunk above has been attempted; the corrective
            # pass below never interleaves with first-pass coverage) --------
            for story in candidates:
                if not isinstance(story, dict):
                    result.dropped.append(f"non-object story entry: {story!r:.60}")
                    continue
                title = str(story.get("title") or "").strip() or "<untitled>"
                bullet = find_bullet(bullets, story.get("sourceBulletId"))
                if bullet is None:
                    result.dropped.append(
                        f"{title}: cites unknown source bullet "
                        f"{story.get('sourceBulletId')!r}"
                    )
                    continue

                grounded, reason, note = self._validate_candidate(
                    story, bullet, resume_lower, all_employers, resume_numbers,
                    criteria,
                )
                if reason is not None:
                    message = f"{title}: {reason}"
                    result.dropped.append(message)
                    rejections.append(_Rejection(
                        bullet=bullet, story=story, reason=message,
                        dropped_index=len(result.dropped) - 1,
                    ))
                    continue
                if note:
                    result.stripped.append(f"{title}: {note}")

                key = achievement_key(user_id, bullet["text"])
                if key in seen_keys:
                    # Two stories for one bullet in a SINGLE response: keep
                    # the first, drop the rest, rather than letting them
                    # merge over each other and leave the last writer's
                    # wording arbitrarily.
                    result.dropped.append(
                        f"{title}: second story for source bullet {bullet['id']}"
                    )
                    continue
                seen_keys.add(key)
                to_persist.append((grounded, key, bullet))

            criteria_failed_first_pass = len(rejections)

            # -- ONE bounded corrective retry (R3 bound 3): never a loop, and
            # never attempted before first-pass coverage is complete -------
            fixed_indices: set[int] = set()
            if (
                rejections
                and story_correction_enabled()
                and remaining_budget_seconds() >= _MIN_CHUNK_SECONDS
            ):
                corrective_retry_used = True
                try:
                    corrected = self._correct_once(rejections, resume_text)
                except LLMUnavailableError as exc:
                    corrected = []
                    result.dropped.append(f"correction unavailable: {exc}")

                # Same-bullet-id lookup: a rejection can only be corrected by
                # a candidate citing the SAME bullet it was rejected for —
                # never a story out of scope of what was actually asked.
                pending = {r.bullet["id"]: r for r in rejections}
                for cand in corrected:
                    if not isinstance(cand, dict):
                        continue
                    orig = pending.pop(cand.get("sourceBulletId"), None)
                    if orig is None:
                        continue
                    title = str(cand.get("title") or "").strip() or "<untitled>"
                    grounded, reason, note = self._validate_candidate(
                        cand, orig.bullet, resume_lower, all_employers,
                        resume_numbers, criteria,
                    )
                    if reason is not None:
                        # BOTH reasons recorded, honestly — the correction
                        # was attempted and still failed.
                        result.dropped[orig.dropped_index] = (
                            f"{orig.reason} — still failing after one "
                            f"corrective attempt: {reason}"
                        )
                        continue
                    key = achievement_key(user_id, orig.bullet["text"])
                    if key in seen_keys:
                        result.dropped[orig.dropped_index] = (
                            f"{orig.reason} — a corrective attempt fixed it, "
                            f"but source bullet {orig.bullet['id']} already "
                            "has a story from this run"
                        )
                        continue
                    seen_keys.add(key)
                    if note:
                        result.stripped.append(f"{title}: {note}")
                    to_persist.append((grounded, key, orig.bullet))
                    fixed_indices.add(orig.dropped_index)
                # anything the correction response never addressed keeps its
                # original first-pass message, untouched.

        if fixed_indices:
            result.dropped = [
                message for i, message in enumerate(result.dropped)
                if i not in fixed_indices
            ]
        criteria_failed_final = criteria_failed_first_pass - len(fixed_indices)

        for grounded, key, _bullet in to_persist:
            created = self._stories.create(
                user_id,
                {
                    "title": grounded["title"],
                    "situation": grounded["situation"],
                    "task": grounded["task"],
                    "action": grounded["action"],
                    "result": grounded["result"],
                    "metrics": self._evidence_metrics(grounded.get("metrics")),
                    "tags": self._tags(grounded),
                    "achievementKey": key,
                },
            )
            result.story_ids.append(created["id"])
            result.created += 1
            if created["id"] in existing_ids:
                result.merged += 1

        result.criteria_verdicts = self._criteria_verdicts(
            to_persist, len(bullets), criteria
        )
        result.corrective_retry_used = corrective_retry_used
        result.criteria_failed_first_pass = criteria_failed_first_pass
        result.criteria_failed_final = criteria_failed_final
        result.strictness_applied = criteria.strictness
        result.excluded_count = criteria_failed_final

        if policy_knobs and "storyEvidenceStrictness" in policy_knobs:
            self._record_directive_outcome_if_active(
                user_id,
                {
                    "criteriaFailedFirstPass": criteria_failed_first_pass,
                    "correctiveRetryUsed": corrective_retry_used,
                    "criteriaFailedFinal": criteria_failed_final,
                    "strictnessApplied": criteria.strictness,
                    "excludedCount": criteria_failed_final,
                },
            )
        return result

    # -- prompt ------------------------------------------------------------

    @staticmethod
    def _chunks(
        bullets: list[dict[str, str]], covered: dict[str, Any], user_id: str
    ) -> list[list[dict[str, str]]]:
        """Bullets grouped into per-call batches, UNCOVERED ONES FIRST.

        A bullet whose achievement already has a live story is worth far less
        this run than one with no story at all, so when the budget only allows
        some batches the ones that ADD coverage go first. That is what makes a
        second run converge on the whole résumé instead of re-deriving the same
        opening bullets every time.

        Covered bullets are then ordered OLDEST-REFRESHED first. Without that
        the order was stable across runs, so the same rows were rewritten every
        time and the rest never got their refresh — which is why stale content
        written by a superseded extraction (a wrong organisation tag) survived
        several re-runs.
        """
        def _rank(bullet: dict[str, str]) -> tuple[int, Any]:
            refreshed = covered.get(achievement_key(user_id, bullet["text"]))
            return (0, "") if refreshed is None else (1, refreshed)

        ordered = sorted(bullets, key=_rank)
        return [
            ordered[i : i + _BULLETS_PER_CALL]
            for i in range(0, len(ordered), _BULLETS_PER_CALL)
        ]

    @staticmethod
    def _build_prompt(resume_text: str, bullets: list[dict[str, str]]) -> str:
        listing = "\n".join(f"{b['id']}: {b['text']}" for b in bullets)
        return (
            f"Resume:\n{resume_text}\n\n"
            f"Achievement bullets (cite one id per story):\n{listing}\n\n"
            f"Write one STAR story for each of the {len(bullets)} bullets above."
        )

    # -- validation --------------------------------------------------------

    def _reject_reason(
        self,
        story: dict[str, Any],
        bullet: dict[str, str],
        resume_lower: str,
        all_employers: list[str],
        criteria: "StoryCriteria" = StoryCriteria(),
    ) -> str | None:
        """Why this story is not usable, or ``None`` when it is.

        ``criteria`` (B1c, default ``StoryCriteria()`` — the shipped
        constants, so every pre-existing caller of this method is
        byte-unaffected) supplies the STAR length floor and, under
        ``strict``, drops the résumé-wide organisation fallback for a bullet
        with no employer header of its own (§6.1 — narrows only, never
        loosens).
        """
        reason = _field_length_reason(story, criteria)
        if reason is not None:
            return reason

        organisation = str(story.get("organisation") or "").strip()
        if not organisation:
            return "no organisation given"
        employers = list(bullet.get("employers") or [])
        if employers:
            # BOUND TO THE CITED BULLET. "Does this string occur anywhere in
            # the résumé" let any past employer — or any word inside one —
            # evidence any bullet; live, an Independent-consulting project was
            # tagged with the ATO. The employer list is the header block the
            # cited bullet actually sits under.
            if not organisation_matches(organisation, employers):
                return (
                    f"organisation {organisation!r} is not the employer for "
                    f"source bullet {bullet['id']} ({', '.join(employers)})"
                )
        elif criteria.require_own_employer:
            # STRICT ONLY (§6.1): a bullet with no employer header of its own
            # gets no résumé-wide fallback at all — narrows what standard
            # already accepts, never the reverse.
            return (
                f"source bullet {bullet['id']} has no employer of its own; "
                "the strict evidence policy requires a per-bullet employer "
                "binding rather than a résumé-wide match"
            )
        elif all_employers:
            # This bullet sits under no header of its own, but the résumé DOES
            # name employers elsewhere — so the claim must still be one of
            # them. Weaker than the per-bullet binding above, far stronger
            # than "occurs somewhere in the file".
            if not organisation_matches(organisation, all_employers):
                return (
                    f"organisation {organisation!r} is not an employer named "
                    f"in the resume ({', '.join(all_employers)})"
                )
        elif not (
            organisation.lower() in resume_lower
            and organisation_appears_in_text(organisation, resume_lower)
        ):
            # Last resort: the layout yields NO employer structure at all, so
            # the whole résumé is the only evidence there is. Both the old raw
            # containment AND a whole-word match are required, so this branch
            # accepts strictly less than it did — "Taxation Offic" no longer
            # "appears" in a résumé that says "Taxation Office".
            return f"organisation {organisation!r} does not appear in the resume"

        reason = _metric_evidence_reason(story, bullet)
        if reason is not None:
            return reason
        metrics = self._evidence_metrics(story.get("metrics"))
        if is_quantified(bullet["text"]) and not metrics:
            return (
                f"source bullet {bullet['id']} is quantified but the story "
                "carries no metric"
            )
        return None

    def _validate_candidate(
        self,
        story: dict[str, Any],
        bullet: dict[str, Any],
        resume_lower: str,
        all_employers: list[str],
        resume_numbers: set[str],
        criteria: "StoryCriteria",
    ) -> tuple[dict[str, Any], str | None, str]:
        """The full accept/reject pipeline for ONE candidate against ONE
        bullet — ``_reject_reason`` then ``_ground_narrative`` — used
        identically for a first-pass candidate and a corrective-pass
        candidate, so correction is judged by the EXACT same bar."""
        reason = self._reject_reason(
            story, bullet, resume_lower, all_employers, criteria
        )
        if reason is not None:
            return story, reason, ""
        return self._ground_narrative(story, bullet, resume_numbers)

    @staticmethod
    def _ground_narrative(
        story: dict[str, Any], bullet: dict[str, Any], resume_numbers: set[str]
    ) -> tuple[dict[str, Any], str | None, str]:
        """Hold the STAR PROSE to the cited bullet's evidence.

        Returns ``(story, reject_reason, strip_note)``. The returned story is
        a copy whose body fields have had any sentence carrying a borrowed
        number removed; ``reject_reason`` is set when the story cannot be
        salvaged at all. Nothing is ever rewritten or added — the only edit
        this method can make is a deletion.
        """
        evidenced = bullet_numbers(bullet["text"])
        grounded = dict(story)
        removed: list[str] = []

        for field_name in _STAR_FIELDS:
            text = str(story.get(field_name) or "")
            invented = [n for n in unevidenced_claims(text, evidenced)
                        if n not in resume_numbers]
            if invented:
                # FABRICATION: the résumé does not state this number anywhere.
                return (
                    grounded,
                    f"{field_name} claims {', '.join(invented)}, which the "
                    "resume does not state anywhere",
                    "",
                )

        borrowed_title = unevidenced_claims(str(story.get("title") or ""), evidenced)
        if borrowed_title:
            return (
                grounded,
                f"title claims {', '.join(borrowed_title)}, which source "
                f"bullet {bullet['id']} does not evidence",
                "",
            )

        for field_name in _BODY_FIELDS:
            text = str(story.get(field_name) or "")
            if not unevidenced_claims(text, evidenced):
                continue
            cleaned, gone = strip_unevidenced_sentences(text, evidenced)
            if len(cleaned.strip()) < _MIN_BODY_CHARS:
                return (
                    grounded,
                    f"{field_name} rests on {', '.join(gone)}, which source "
                    f"bullet {bullet['id']} does not evidence; nothing usable "
                    "remains once that is removed",
                    "",
                )
            grounded[field_name] = cleaned.strip()
            removed.extend(f"{field_name}:{n}" for n in gone)

        note = (
            f"stripped sentences carrying {', '.join(removed)} — not evidenced "
            f"by source bullet {bullet['id']}"
            if removed
            else ""
        )
        return grounded, None, note

    @staticmethod
    def _evidence_metrics(metrics: Any) -> dict[str, Any]:
        if not isinstance(metrics, dict):
            return {}
        return {
            str(k): v
            for k, v in metrics.items()
            if str(k) not in _RESERVED_METRIC_KEYS and str(v).strip()
        }

    @staticmethod
    def _tags(story: dict[str, Any]) -> list[str]:
        """The model's tags plus the organisation (already résumé-verified).

        The organisation is what makes a story searchable and reusable — "the
        ANZ cloud-native one" is how a person actually recalls it — and it
        feeds the Story Bank screen's category derivation.
        """
        tags = [str(t).strip() for t in (story.get("tags") or []) if str(t).strip()]
        organisation = str(story.get("organisation") or "").strip()
        if organisation:
            tags.append(organisation)
        return list(dict.fromkeys(tags))

    # -- B1c: rigor policy, corrective loop, learning signal ---------------

    @staticmethod
    def _criteria(policy_knobs: Mapping[str, Any] | None) -> "StoryCriteria":
        """Validation thresholds as DATA (§3.3). ``None``/``{}``/no
        recognised value all resolve to today's shipped defaults — the exact
        ``{}`` == "use the callee's shipped defaults" contract
        tailor/coverLetter already have."""
        strictness = "standard"
        if policy_knobs:
            requested = policy_knobs.get("storyEvidenceStrictness")
            if requested in ("standard", "strict"):
                strictness = requested
        if strictness == "strict":
            return StoryCriteria(
                min_title_chars=_MIN_TITLE_CHARS,
                min_body_chars=_STRICT_MIN_BODY_CHARS,
                strictness="strict",
                require_own_employer=True,
            )
        return StoryCriteria(strictness="standard")

    def _correct_once(
        self, rejections: Sequence["_Rejection"], resume_text: str
    ) -> list[dict[str, Any]]:
        """ONE bounded corrective re-prompt (R3 bound 3 — never a loop, no
        attempt count). Carries each rejection's OWN validator reason back
        to the model VERBATIM — ``_reject_reason``/``_ground_narrative``
        already produce precise, human-readable, per-story reasons, and this
        feeds them exactly as the correction instruction, no paraphrase.

        Returns whatever the model responds with, UNVALIDATED — the caller
        re-runs the identical validation pipeline on the result, so a
        correction can never be judged by a looser bar than the first pass.
        A call failure is NOT caught here — the caller catches
        ``LLMUnavailableError`` and degrades to an honest drop, mirroring
        the first pass's own per-chunk handling; this method never turns a
        failed correction into anything other than what it is.
        """
        prompt = self._build_correction_prompt(resume_text, rejections)
        raw = self._llm.complete_json(
            "story_extractor_correction",
            _CORRECTION_SYSTEM_PROMPT,
            prompt,
            model=get_model("STRUCTURED"),
            temperature=0.0,
        )
        batch = raw.get("stories") if isinstance(raw, dict) else None
        return batch if isinstance(batch, list) else []

    @staticmethod
    def _build_correction_prompt(
        resume_text: str, rejections: Sequence["_Rejection"]
    ) -> str:
        # Same bullet cited twice among the rejections (rare: two candidates
        # for one bullet, both rejected) collapses to ONE correction request
        # for that bullet — asking the model to fix the same bullet twice in
        # one call would be meaningless.
        by_bullet: dict[str, "_Rejection"] = {r.bullet["id"]: r for r in rejections}
        listing = "\n\n".join(
            f"{r.bullet['id']}: {r.bullet['text']}\n"
            f"Your previous story for {r.bullet['id']} failed validation: "
            f"{r.reason}"
            for r in by_bullet.values()
        )
        return (
            f"Resume:\n{resume_text}\n\n"
            "The following stories you previously wrote were rejected by "
            "validation. Rewrite ONLY these stories, fixing EXACTLY the "
            "stated problem, still following every HARD RULE above (every "
            "number must be evidenced by the cited bullet; never invent, "
            "round, extrapolate or borrow a number from another bullet or "
            "from anywhere else in the résumé).\n\n"
            f"{listing}\n\n"
            f"Write one corrected STAR story for each of the "
            f"{len(by_bullet)} bullet(s) above, citing its id in "
            "sourceBulletId."
        )

    @staticmethod
    def _criteria_verdicts(
        to_persist: list[tuple[dict[str, Any], str, dict[str, Any]]],
        bullets_total: int,
        criteria: "StoryCriteria",
    ) -> dict[str, str | None]:
        """{criterion_key: None-if-passed-else-an-honest-reason}, evaluated
        once over the stories ACTUALLY PERSISTED this run — an honest
        confirmation (never a second, competing gate) that the data-driven
        criteria table agrees with what the acceptance pipeline already
        decided."""
        stories = [g for g, _, _ in to_persist]
        keys = [k for _, k, _ in to_persist]
        verdicts: dict[str, str | None] = {}
        for criterion in STORY_VALIDATION_CRITERIA:
            if criterion.scope == "run":
                verdicts[criterion.key] = criterion.check(
                    stories, bullets_total, keys, criteria
                )
                continue
            failing = [
                str(g.get("title") or "<untitled>")
                for g, _, b in to_persist
                if criterion.check(g, b, criteria) is not None
            ]
            verdicts[criterion.key] = (
                None if not failing
                else f"post-gate re-check failed for: {', '.join(failing)}"
            )
        return verdicts

    def _record_directive_outcome_if_active(
        self, user_id: str, outcome: dict[str, Any]
    ) -> None:
        """B1c learning signal (ADR-AGI-2's outcome/efficacy substrate).
        Called ONLY when this run's resolved knobs actually carried
        ``storyEvidenceStrictness`` (the caller's own gate) — i.e. an active
        directive genuinely amended THIS run, never a directive that merely
        exists. Feeds the loop's outcome onto it via the B1b repository's
        own hook — never a new write path, and never touching
        ``directive``/``rationale`` (``AgentDirectiveRepository
        .record_outcome``'s own immutable-history contract). Best-effort:
        telemetry must never fail an otherwise-successful extraction run.
        """
        try:
            from app.repositories.agent_directive import AgentDirectiveRepository

            repo = AgentDirectiveRepository()
            for directive in repo.list_active(user_id, "storyExtractor"):
                content = directive.get("directive")
                if isinstance(content, dict) and "storyEvidenceStrictness" in content:
                    repo.record_outcome(directive["id"], outcome)
        except Exception:  # noqa: BLE001 — telemetry is best-effort
            logger.warning(
                "story extractor: failed to record directive outcome for "
                "user %s", user_id, exc_info=True,
            )

    # -- grounding ---------------------------------------------------------

    @staticmethod
    def _resolve_resume_text(user_id: str) -> str:
        """The caller's OWN resume text (MV-story-bank-006) — delegates to the
        shared per-user grounding helper with ``allow_operator_fallback=False``
        (ML-audit-story-leak-001). STAR stories extracted here are PERSISTED
        into the calling user's OWN Story Bank, so — unlike a purely internal
        computation — they ARE user-visible; the OPERATOR's bundled résumé
        must never ground them. A user with no résumé of their own therefore
        gets an honest empty resume corpus (and so extracts zero stories this
        run) instead of stories silently derived from the operator's real
        personal history, mirroring every other per-user grounding call site
        (email_agent.py, cover_letters.py, jobs.py)."""
        return resolve_user_resume_text(user_id, allow_operator_fallback=False)
