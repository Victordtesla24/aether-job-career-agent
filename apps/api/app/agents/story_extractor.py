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
"""
from __future__ import annotations

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
    organisation_matches,
    strip_unevidenced_sentences,
    unevidenced_claims,
)
from app.services.resume_grounding import resolve_user_resume_text

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


class StoryExtractorAgent:
    def __init__(
        self, llm: LLMClient | None = None, stories: StoryRepository | None = None
    ) -> None:
        self._llm = llm or LLMClient()
        self._stories = stories or StoryRepository()

    def run(self, user_id: str) -> StoryExtractionResult:
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

        resume_lower = resume_text.lower()
        #: Every number the résumé states ANYWHERE. A narrative number outside
        #: this set was invented outright; one inside it but outside the cited
        #: bullet was borrowed from another achievement. The two get different
        #: remedies (see the module docstring), so both sets are needed.
        resume_numbers = bullet_numbers(resume_text)
        existing_ids = {s["id"] for s in self._stories.list_by_user(user_id)}
        covered = self._stories.live_achievement_keys(user_id)
        seen_keys: set[str] = set()
        candidates: list[Any] = []
        last_error: LLMUnavailableError | None = None
        succeeded = 0

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
            # EVERY call failed: this is a real outage, not a thin résumé. Raise
            # so the run is recorded as failed and the reserved quota refunded,
            # instead of reporting a successful extraction of nothing.
            raise last_error

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

            reason = self._reject_reason(story, bullet, resume_lower)
            if reason is not None:
                result.dropped.append(f"{title}: {reason}")
                continue

            story, reason, note = self._ground_narrative(
                story, bullet, resume_numbers
            )
            if reason is not None:
                result.dropped.append(f"{title}: {reason}")
                continue
            if note:
                result.stripped.append(f"{title}: {note}")

            key = achievement_key(user_id, bullet["text"])
            if key in seen_keys:
                # Two stories for one bullet in a SINGLE response: keep the
                # first, drop the rest, rather than letting them merge over
                # each other and leave the last writer's wording arbitrarily.
                result.dropped.append(
                    f"{title}: second story for source bullet {bullet['id']}"
                )
                continue
            seen_keys.add(key)

            created = self._stories.create(
                user_id,
                {
                    "title": story["title"],
                    "situation": story["situation"],
                    "task": story["task"],
                    "action": story["action"],
                    "result": story["result"],
                    "metrics": self._evidence_metrics(story.get("metrics")),
                    "tags": self._tags(story),
                    "achievementKey": key,
                },
            )
            result.story_ids.append(created["id"])
            result.created += 1
            if created["id"] in existing_ids:
                result.merged += 1
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
        self, story: dict[str, Any], bullet: dict[str, str], resume_lower: str
    ) -> str | None:
        """Why this story is not usable, or ``None`` when it is."""
        for field_name in _STAR_FIELDS:
            value = str(story.get(field_name) or "").strip()
            minimum = _MIN_TITLE_CHARS if field_name == "title" else _MIN_BODY_CHARS
            if len(value) < minimum:
                return (
                    f"{field_name} is {len(value)} chars, under the "
                    f"{minimum}-char minimum"
                )

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
        elif organisation.lower() not in resume_lower:
            # No header block was extractable from this layout: fall back to
            # the whole-résumé check rather than rejecting every story. This
            # is the OLD behaviour, kept only where the tighter one has no
            # evidence to work from — never used to weaken a bullet that DOES
            # know its employer.
            return f"organisation {organisation!r} does not appear in the resume"

        metrics = self._evidence_metrics(story.get("metrics"))
        evidenced = bullet_numbers(bullet["text"])
        for key, value in metrics.items():
            for number in claim_numbers(f"{key} {value}"):
                if number not in evidenced:
                    return (
                        f"metric {key!r}={value!r} uses {number!r}, which is not "
                        f"evidenced by source bullet {bullet['id']}"
                    )
        if is_quantified(bullet["text"]) and not metrics:
            return (
                f"source bullet {bullet['id']} is quantified but the story "
                "carries no metric"
            )
        return None

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
