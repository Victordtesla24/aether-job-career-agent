"""Score-aware iterative tailoring loop (GOLD-MASTER-V2 §5.3, gate G-C).

``app.services.resume_tailor.ResumeTailorService`` performs exactly ONE LLM
pass per call. :class:`TailoringLoop` wraps it (and the deterministic
:class:`~app.services.ats_engine.ATSEngine`) in a score-aware retry: tailor,
score, and — while the score stays below ``target_score`` and iterations
remain — re-run with a directive that names the score gap and the
still-missing JD keywords, so the next pass has something concrete to close.

Exit conditions (§5.3 item 1):

- ``ats_score >= target_score`` (default 85.0) — stop immediately, success.
- ``iteration == max_iterations`` (default 5) — stop, report the BEST score
  actually achieved and an honest sub-target warning. The loop NEVER reports
  success for a score below target, however close it got (§5.3.1 point 5).

The anti-fabrication entailment guard inside :class:`ResumeTailorService`
runs unmodified on every iteration — closing a keyword gap never means
inventing experience the candidate does not have. A directive that keeps
proposing an unsupported keyword is simply rejected again and again; the
loop's score-tracking already prefers whichever iteration scored highest, so
a run that can never close a gap truthfully honestly reports failure rather
than fabricating its way to 85.

Design note on the retry directive (REVISED, W-TAILOR-CONVERGE): the directive
is APPENDED to the real job description under :data:`DIRECTIVE_MARKER` — it is
never SUBSTITUTED for it. The original design passed the directive ALONE as
``ResumeTailorService.tailor``'s ``job_description`` argument, which made
every pass after the first blind to the actual posting: not only did the
rewrite prompt lose the role, but ``select_bullets_to_tailor`` then ranked
bullets against the directive's own boilerplate. The noise concern that
motivated the original design (ordinary JD prose contains contraction
fragments — "we're" tokenizes to "re" on the apostrophe — and generic words
like "about" that are not in ``app.services.ats_engine._STOPWORDS``) is
handled where it actually matters: :func:`clean_gap_keywords` still strips
that noise out of the KEYWORD LIST the directive asks for. Reproducing the
posting verbatim above the directive cannot poison that list, because the
list is derived from ``ATSScore.missing_keywords``, not from the directive
text.

Third design note (2026-08-03): that noise claim was OVERSTATED when it was
written. ``clean_gap_keywords`` stripped only the <= 2-character halves of a
split contraction, so "don" (from "don't") and a long tail of closed-class
function words — "other", "actually", "each", "more", "between" — sailed
straight through into BOTH the LLM's forbidden-keyword list AND the
user-facing sub-target warning. Verified by reading them back out of live
production ``Resume.sections->'tailoringSummary'->'gapKeywords'`` rows. The
filter now covers contraction prefixes, closed-class function words,
delexical light verbs and HTML entity names; see :func:`clean_gap_keywords`.

Second design note (W-TAILOR-CONVERGE): the directive only ever asks for gap
keywords the candidate's OWN EVIDENCE already contains
(:func:`split_gap_keywords`). A JD keyword absent from the résumé, story bank
and career data cannot be added without fabricating, so the entailment guard
would reject the rewrite anyway — asking for it just burns an iteration and
pushes the model toward exactly the invention the guard exists to stop. Those
keywords are reported as ``unreachable_keywords`` and named in the honest
sub-target warning instead. This is strictly STRICTER than before; the guard
itself is untouched.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from app.services.ats_engine import _STOPWORDS as _ATS_STOPWORDS
from app.services.llm_client import LLMUnavailableError, get_accumulated_usage
from app.services.quality_gate import evaluate_tailoring
from app.services.resume_tailor import _evidence_index, _stem, strip_bullet_lines

_logger = logging.getLogger(__name__)

#: §5.3 item 1: no existing cap governs a *multi-pass* tailoring loop —
#: ``AETHER_LLM_BUDGET_SECONDS`` / ``get_budget_seconds()`` bounds a single
#: LLM client's wall-clock life (armed once, shared by every call made on
#: that client instance — see ``LLMClient._remaining_budget``), not an
#: iteration count. Because :class:`TailoringLoop` is handed ONE
#: ``ResumeTailorService`` (and therefore one ``LLMClient``) and reuses it
#: across every iteration, that existing per-client budget already bounds the
#: loop's total live-call wall-clock time for free; on top of it, 5 is the
#: iteration ceiling this module adds.
DEFAULT_MAX_ITERATIONS = 5

#: §5.3 item 1 / hard rule: the ATS score at which tailoring is "done".
DEFAULT_TARGET_SCORE = 85.0

#: AUD-LLM-1 (RUN-20260818T0223Z item (a)): the counterpart to
#: ``max_iterations`` the loop never had — a REAL cumulative prompt+completion
#: TOKEN ceiling for one :meth:`TailoringLoop.run` call. Before this, the
#: ONLY things bounding a multi-iteration run's live-LLM spend were the
#: iteration cap itself and ``llm_client.get_budget_seconds()`` (a WALL-CLOCK
#: deadline armed once and shared across the whole client instance) —
#: nothing anywhere counted tokens (confirmed by the scout: zero matches for
#: token_budget/max_tokens/count_tokens/prompt_tokens as a LOOP stopping
#: condition).
#:
#: Default derived from MEASURED reality (AUD-ECON-2 scout,
#: docs/delivery/evidence/RUN-20260818T0223Z/AUD-ECON-2/
#: 01-scout-reproduction.log (a)): the 5 real, completed, standard-tier
#: (5-iteration) tailor runs in prod averaged 55,793 prompt + 5,196
#: completion tokens == ~60,989 tokens for a FULL 5-iteration run. The
#: heightened tier (quality_policy.py, 7 iterations) extrapolates linearly to
#: ~85,385 tokens for a full run. 100,000 sits above BOTH figures (~1.64x the
#: standard-tier average, ~1.17x the heightened-tier extrapolation) so a
#: genuinely convergent heightened-tier run is not clipped mid-way, while a
#: run burning tokens well past the measured norm (a pathological résumé/JD,
#: a directive loop that never converges) is still honestly bounded rather
#: than left to run on wall-clock budget alone. Overridable via
#: ``AETHER_TAILOR_TOKEN_BUDGET`` (:func:`get_token_budget`).
DEFAULT_TOKEN_BUDGET = 100_000


def get_token_budget() -> int:
    """Cumulative prompt+completion token ceiling for one tailoring run.

    ``AETHER_TAILOR_TOKEN_BUDGET`` env override, default
    :data:`DEFAULT_TOKEN_BUDGET` — mirrors
    ``llm_client.get_budget_seconds()``'s env-override pattern (same
    try/except-ValueError shape, same "default when unset or malformed").
    """
    try:
        return int(
            os.environ.get("AETHER_TAILOR_TOKEN_BUDGET", str(DEFAULT_TOKEN_BUDGET))
        )
    except ValueError:
        return DEFAULT_TOKEN_BUDGET

#: Every English contraction a job posting realistically contains, written out
#: in full so the fragment set below can be DERIVED from it rather than
#: hand-maintained. ``ats_engine._TOKEN_RE`` is ``[a-zA-Z][a-zA-Z0-9+#.\-]*``
#: — the apostrophe is not in that character class, so each of these splits at
#: the apostrophe and BOTH halves become candidate "keywords".
#:
#: The original set listed only the SUFFIX halves ("re", "ll", "ve"), all of
#: which happen to be <= 2 characters and were therefore already covered by the
#: length rule. The halves that actually leaked are the ``n``-final PREFIXES of
#: the negative contractions — "don" (from "don't"), "doesn", "isn", "won",
#: "couldn" — which are 3+ characters and sailed straight through. "don" was
#: observed in live production ``gapKeywords`` rows on 2026-08-03.
_CONTRACTIONS = """
    don't doesn't didn't isn't aren't wasn't weren't won't can't couldn't
    shouldn't wouldn't hasn't haven't hadn't mustn't needn't shan't mightn't
    ain't we're you're they're it's he's she's that's what's there's here's
    who's how's let's i'm i've we've you've they've i'd we'd you'd they'd
    he'd she'd i'll we'll you'll they'll he'll she'll it'll
""".split()

#: Contraction fragments that a naive apostrophe split leaves behind
#: ("we're" -> "we" + "re", "don't" -> "don" + "t", "I've" -> "i" + "ve").
_CONTRACTION_FRAGMENTS = frozenset(
    fragment
    for contraction in _CONTRACTIONS
    for fragment in contraction.split("'")
    if fragment
)

#: Closed-class English function words: determiners, quantifiers, pronouns,
#: conjunctions, prepositions, degree/frequency adverbs and modals.
#:
#: The choice of a CLOSED class is the whole point, and is what makes this list
#: safe to apply to a keyword gap: closed classes take no new members, so no
#: present or future skill, tool, employer or certification can ever be one of
#: these words. (Contrast an open-class guess like "delivery" or "platform",
#: which really can be part of a skill phrase — those are deliberately NOT
#: here.) Words already in ``ats_engine._STOPWORDS`` are omitted; this set only
#: fills that list's gaps.
#:
#: These were read back out of real persisted
#: ``Resume.sections->'tailoringSummary'->'gapKeywords'`` rows in the production
#: ``aether`` schema on 2026-08-03 — i.e. they had already survived
#: ``clean_gap_keywords`` and reached both the user-facing honesty warning and
#: the LLM's forbidden-keyword list: "other", "actually", "more", "between",
#: "every", "such", "around", "yourself", "behind", "continue", "answering".
_FUNCTION_WORDS = frozenset(
    """
    other others another same own such
    each every everyone everything everybody anyone anybody anything
    someone something nobody none
    more most less least much many few fewer several enough
    between within without among amongst upon onto through throughout
    around behind beneath beside besides beyond toward towards
    against above below over under during
    actually really simply just very quite rather too even still yet
    always often sometimes usually never already again once
    myself yourself himself herself itself ourselves yourselves themselves
    however therefore moreover furthermore otherwise thus hence
    although though whilst while whereas because unless whether either neither
    must should shall may might cannot
    """.split()
)

#: Delexical ("light") verbs and a few contentless discourse verbs. These are
#: open-class words, so — unlike ``_FUNCTION_WORDS`` — they are listed one by
#: one on their own merits rather than by category: each is a verb whose
#: meaning lives entirely in its object ("make progress", "take ownership"),
#: so it can never itself be the skill an ATS is matching on. Job postings are
#: dense with them, and "continue"/"answering" were observed live.
_LIGHT_VERBS = frozenset(
    """
    get gets getting got make makes making made take takes taking taken
    give gives giving given put puts putting keep keeps keeping kept
    come comes coming go goes going gone continue continues continuing
    say says saying said tell tells telling told ask asks asking asked
    answer answers answering answered let lets
    know knows knowing known think thinks thinking thought
    see sees seeing seen look looks looking
    """.split()
)

#: Generic non-skill words the docstring/tests call out explicitly — carry no
#: checkable skill signal even though they are not in ``ats_engine._STOPWORDS``.
#: Kept separate from ``_FUNCTION_WORDS`` because these are open-class words
#: judged case by case, not a whole grammatical category.
_GENERIC_NOISE = frozenset({"use", "uses", "used", "using", "about"})

#: HTML entity NAMES that survive a crude tag-strip of a scraped posting and
#: then tokenize as ordinary words. "nbsp" (from ``&nbsp;``) was observed in
#: live production ``gapKeywords`` on 2026-08-03.
_HTML_ENTITIES = frozenset(
    """
    nbsp amp quot apos lt gt ndash mdash rsquo lsquo rdquo ldquo hellip
    bull middot times divide copy reg trade deg permil laquo raquo shy zwj zwnj
    """.split()
)

#: Header that separates the (verbatim) job description from the loop's own
#: retry directive inside the ``job_description`` argument handed to
#: ``ResumeTailorService.tailor`` on iteration 2+. Exported so callers/tests
#: can split the two halves apart deterministically.
DIRECTIVE_MARKER = "--- AETHER TAILORING DIRECTIVE ---"


#: Union of every non-skill vocabulary above, built once. Membership is the
#: whole test — order of the individual sets is irrelevant, so collapsing them
#: keeps ``clean_gap_keywords`` a single hash lookup per token.
_NON_SKILL_TOKENS = (
    _CONTRACTION_FRAGMENTS
    | _FUNCTION_WORDS
    | _LIGHT_VERBS
    | _GENERIC_NOISE
    | _HTML_ENTITIES
    | _ATS_STOPWORDS
)


def clean_gap_keywords(raw: list[str]) -> list[str]:
    """Strip tokenization noise from ``ATSScore.missing_keywords``.

    Drops, in order of how they arise:

    * bare 1-2 char fragments ("re", "ll", "ve", "xz", "a", ...);
    * contraction fragments of BOTH halves — critically the ``n``-final
      prefixes ("don" from "don't", "doesn", "isn", "won", "couldn"), which
      are 3+ characters and used to survive the length rule;
    * HTML entity names left by a crude tag-strip of a scraped posting
      ("nbsp");
    * closed-class function words ("other", "each", "more", "between",
      "actually") and delexical light verbs ("make", "take", "continue");
    * ``ats_engine._STOPWORDS`` and generic non-skill words ("use", "about");
    * duplicates.

    Real multi-char skill keywords and their first-seen order are preserved,
    so both consumers of this list stay honest: the per-iteration directive
    only asks the model to surface real, checkable skill terms, and the
    user-facing sub-target warning only names words that genuinely are a
    keyword gap.

    This is a pure NOISE filter. It never changes what the anti-fabrication /
    entailment guard will accept — it only shrinks the set of words the loop
    bothers to ask about, which is strictly stricter, never looser.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_kw in raw:
        token = (raw_kw or "").strip().lower()
        if len(token) <= 2:
            continue
        if token in _NON_SKILL_TOKENS:
            continue
        if token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def split_gap_keywords(
    keywords: list[str], evidence_corpus: str
) -> tuple[list[str], list[str]]:
    """Partition cleaned gap keywords into ``(supported, unsupported)``.

    "Supported" means the keyword (or its stem) is genuinely present in the
    candidate's own evidence corpus — their résumé text plus any Story Bank /
    career-data evidence. That is EXACTLY the precondition
    ``ResumeTailorService``'s deterministic anti-fabrication guard checks
    before it will accept a rewritten bullet containing that token (it builds
    the same token+stem index via ``_evidence_index``), so this partition
    predicts, rather than second-guesses, what the guard will allow.

    A keyword in the UNSUPPORTED half is not "hard" — it is impossible to add
    truthfully. Naming it in a retry directive can only produce a rewrite the
    guard rejects. The loop therefore stops asking for it and reports it as
    unreachable, which is strictly stricter than the previous behaviour: the
    guard is never consulted less, only asked to reject less.
    """
    stems, _numbers = _evidence_index(evidence_corpus or "")
    supported: list[str] = []
    unsupported: list[str] = []
    for keyword in keywords:
        token = keyword.lower()
        if token in stems or _stem(token) in stems:
            supported.append(keyword)
        else:
            unsupported.append(keyword)
    return supported, unsupported


class _TailorServiceLike(Protocol):
    def tailor(
        self,
        resume_text: str,
        job_description: str,
        originals: Any = None,
        evidence_extra: str = "",
    ) -> Any: ...


class _ATSEngineLike(Protocol):
    def score(self, resume_text: str, job_description: str) -> Any: ...


@dataclass
class TailoringLoopResult:
    """Outcome of a full :meth:`TailoringLoop.run` — every iteration's output
    + score (so the UI can show progress honestly, §5.3.3), plus the winning
    iteration and an honest verdict (§5.3.1 point 5)."""

    #: One entry per iteration actually run:
    #: {"iteration", "score", "bullets", "changes", "gapKeywords", "rejected"}.
    iterations: list[dict[str, Any]] = field(default_factory=list)
    #: Bullets of the BEST-scoring iteration (never a lower-scoring later one).
    final_bullets: list[dict[str, str]] = field(default_factory=list)
    best_score: float = 0.0
    #: 1-based index into ``iterations`` of the best-scoring pass.
    best_iteration: int = 0
    #: True iff ``best_score >= target_score`` — NEVER true otherwise.
    success: bool = False
    #: == ``not success``. Wired to the existing ``ATSScore.requires_review``
    #: signal's spirit: a sub-target result always needs a human look.
    requires_review: bool = True
    #: Populated iff ``requires_review``; always names the best score achieved.
    warning: str | None = None
    #: W-TAILOR-CONVERGE: JD keywords still missing at the end of the run that
    #: the candidate's evidence does NOT support — no truthful rewrite can
    #: ever add them, so they are a permanent, honest ceiling on
    #: ``keyword_match`` for this résumé/posting pair, not a loop failure.
    #: Order-preserving, taken from the best-scoring iteration.
    unreachable_keywords: list[str] = field(default_factory=list)
    #: Why the loop stopped: ``"target_reached"``, ``"iteration_cap"``,
    #: ``"quality_gate_cap"`` (U2c: the ATS target WAS reached but a dimension
    #: stayed below the 80% quality floor after every bounded gate attempt), or
    #: ``"llm_budget_exhausted"`` (a live generation ran out of wall-clock
    #: budget part-way through, so fewer passes ran than the cap allowed).
    #: Never a euphemism — a capped-out or cut-short run says so, and the
    #: warning repeats it in words.
    stop_reason: str = "iteration_cap"
    #: U2c: the winning iteration's 80%-all-dimensions verdict
    #: (``services.quality_gate.GateVerdict.as_dict``), or ``None`` when the
    #: caller never armed the gate. A below-floor verdict NEVER suppresses
    #: ``final_bullets`` — the artifact ships, flagged, with the failing
    #: dimensions' real numbers.
    quality_gate: dict[str, Any] | None = None
    #: How many of the gate's bounded extra attempts this run actually spent.
    #: 0 for every run whose score target was never reached — the gate cannot
    #: raise a sub-target run's worst-case LLM spend.
    gate_attempts_used: int = 0


class TailoringLoop:
    """Score-aware wrapper around a tailor service + ATS engine.

    ``service``/``ats_engine`` are duck-typed to
    ``ResumeTailorService``/``ATSEngine`` (see module docstring) so tests can
    pin the loop's own mechanics with lightweight stubs while production code
    wires the real, LLM-backed instances — every iteration's tailoring call
    goes through the app's real configured LLM routing exactly like the
    single-pass path did; the loop only decides whether to call it again.
    """

    def __init__(
        self,
        service: _TailorServiceLike,
        ats_engine: _ATSEngineLike,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        target_score: float = DEFAULT_TARGET_SCORE,
        dimension_floor: float | None = None,
        gate_extra_attempts: int = 0,
        token_budget: int | None = None,
        usage_provider: Callable[[], dict[str, int] | None] = get_accumulated_usage,
    ) -> None:
        """``dimension_floor`` arms the U2c quality gate (U2c RULES item 1).

        When set, an iteration only counts as DONE if it both reaches
        ``target_score`` AND clears the floor on every measured ATS dimension
        (``services.quality_gate.evaluate_tailoring``). ``None`` — the default —
        leaves this loop byte-identical to the shipped behaviour, so arming the
        gate is opt-in at the one production seam that owns the decision.

        ``gate_extra_attempts`` is the BOUNDED extra budget the gate may spend
        on top of ``max_iterations``, and only for a run whose score target was
        already reached: the gate is the reason that run would otherwise have
        stopped early, so the extra attempts are the gate's own cost. A run
        that never reaches ``target_score`` has an open SCORE gap, not a
        dimension-gate problem, and is still bounded by ``max_iterations``
        alone — arming the gate can never raise every run's worst case.

        ``token_budget`` (AUD-LLM-1 item (a)) is the cumulative
        prompt+completion token ceiling for this run's ENTIRE call sequence.
        ``None`` — the default — resolves :func:`get_token_budget` (the env
        knob), so unlike ``dimension_floor`` this is NOT opt-in: every loop is
        token-bounded unless the caller deliberately passes a huge number.
        ``usage_provider`` is the callable consulted after every iteration for
        the run's real accumulated usage — defaults to
        ``llm_client.get_accumulated_usage``, the SAME chars-in/chars-out
        accumulation ``routers/agents.py`` already costs a run against.
        Injectable so tests can pin the stop condition deterministically
        without a real LLM client or ``served_model_capture()`` scope open;
        production code never needs to pass it.
        """
        self._service = service
        self._ats = ats_engine
        self.max_iterations = max_iterations
        self.target_score = target_score
        self.dimension_floor = dimension_floor
        self.gate_extra_attempts = max(0, int(gate_extra_attempts))
        self.token_budget = get_token_budget() if token_budget is None else token_budget
        self._usage_provider = usage_provider

    def run(
        self,
        resume_text: str,
        job_description: str,
        *,
        originals: Any = None,
        evidence_extra: str = "",
    ) -> TailoringLoopResult:
        iterations: list[dict[str, Any]] = []
        best_bullets: list[dict[str, str]] = []
        best_score = -1.0
        best_iteration = 0
        #: U2c ranking key of the current winner. ``(gate_passed, score)`` when
        #: the gate is armed, so a draft that actually cleared every dimension
        #: beats a higher-scoring one that did not — ranking on the raw score
        #: alone would throw the only compliant draft away. Reduces to the
        #: score alone when the gate is disarmed (unchanged behaviour).
        best_rank: tuple[int, float] = (0, -1.0)

        current_originals = originals
        current_jd = job_description
        # W-TAILOR-CONVERGE: the ONLY corpus a truthful rewrite may draw on —
        # the same text the fabrication/entailment guards treat as evidence.
        # Used to decide which gap keywords are actually closable.
        evidence_corpus = "\n".join(p for p in (resume_text, evidence_extra) if p)
        # Refs already rewritten by an earlier pass, so the service's top-K
        # selector can give untouched bullets their turn instead of handing the
        # model the same k bullets on every iteration (see
        # ``select_bullets_to_tailor``). Only forwarded when the injected
        # service actually accepts it, so lightweight test doubles that pin
        # loop mechanics with the historic 4-argument signature keep working.
        already_tailored: set[str] = set()
        supports_rotation = self._service_accepts("already_tailored_refs")
        stop_reason = "iteration_cap"
        llm_error: str | None = None
        #: AUD-LLM-1 item (a): the real cumulative token count observed at the
        #: moment the token budget stopped the run, for the honest warning
        #: below. ``None`` unless that stop condition actually fired.
        token_usage_at_stop: int | None = None
        # U2c bounded gate budget. ``budget`` starts at the shipped iteration
        # cap and is extended ONE attempt at a time, at the cap boundary only,
        # and only when the ATS target has genuinely been reached and the
        # quality gate is the sole thing still open. Worst case is therefore
        # exactly ``max_iterations + gate_extra_attempts`` calls, and a run
        # that never reaches the target spends none of the extra budget.
        budget = self.max_iterations
        gate_attempts_used = 0
        gate_verdict: dict[str, Any] | None = None

        i = 0
        while i < budget:
            i += 1
            extra_kwargs: dict[str, Any] = (
                {"already_tailored_refs": frozenset(already_tailored)}
                if supports_rotation
                else {}
            )
            try:
                tailor_result = self._service.tailor(
                    resume_text,
                    current_jd,
                    originals=current_originals,
                    evidence_extra=evidence_extra,
                    **extra_kwargs,
                )
            except LLMUnavailableError as exc:
                # W-TAILOR-CONVERGE. Measured live (2026-08-02, Megaport
                # "Technical Business Analyst", real deepseek-v4-pro calls): a
                # 5-iteration loop does not always fit inside the worker's
                # 300 s budget, and a single slow generation then raises
                # ``LLM call exceeded hard budget of 68.6s``. That exception
                # used to escape the loop and destroy EVERY completed
                # iteration's work — a run that had already produced a real,
                # guard-passed, higher-scoring résumé came back to the user as
                # a 503 with nothing to show.
                #
                # Iteration 1 has nothing to keep, so it still propagates (the
                # caller refunds the reserved run and reports the outage
                # honestly). From iteration 2 on we STOP and return the best
                # draft actually achieved, with a stop reason that names the
                # cause. This is not a silent degrade: ``success`` is still
                # decided purely by ``best_score >= target_score``, and the
                # warning below states plainly that the run was cut short.
                if i == 1:
                    raise
                _logger.warning(
                    "TailoringLoop stopping at iteration %d of %d: %s",
                    i, self.max_iterations, exc,
                )
                stop_reason = "llm_budget_exhausted"
                llm_error = str(exc)
                break
            prior_text = {
                b.get("evidenceRef"): b.get("text")
                for b in (tailor_result.originals or [])
            }
            for cur in tailor_result.bullets:
                ref = cur.get("evidenceRef")
                if ref and ref in prior_text and cur.get("text") != prior_text[ref]:
                    already_tailored.add(ref)
            corpus = self._corpus(resume_text, tailor_result.bullets)
            ats_score = self._ats.score(corpus, job_description)
            gap_keywords = clean_gap_keywords(list(ats_score.missing_keywords))
            supported_gaps, unsupported_gaps = split_gap_keywords(
                gap_keywords, evidence_corpus
            )
            # GMV4-ats-002: which path produced this iteration's `overall` —
            # ``ats_score.overall`` is 40% built from ``semantic_similarity``,
            # so an iteration whose semantic component came back "degraded"
            # (ats_engine.py's ATSScore.semantic_path) is contaminated by a
            # neutral placeholder, not a genuine measurement. Recorded on
            # every iteration (never just the winner) so the caller/UI can
            # see exactly which passes were trustworthy.
            semantic_path = getattr(ats_score, "semantic_path", "untracked")
            # U2c: this attempt's own 80%-all-dimensions verdict, computed from
            # the REAL scores it just produced. Recorded on EVERY attempt (not
            # only the winner) — the Supervisor's directive loop (ADR-AGI-2)
            # consumes the per-attempt trail, and a user reading the progress
            # list must see which pass closed which dimension.
            iteration_gate = (
                evaluate_tailoring(ats_score, floor=self.dimension_floor).as_dict()
                if self.dimension_floor is not None
                else None
            )
            gate_ok = iteration_gate is None or bool(iteration_gate["passed"])

            iterations.append({
                "iteration": i,
                "score": ats_score.overall,
                "bullets": tailor_result.bullets,
                "changes": tailor_result.changes,
                "gapKeywords": gap_keywords,
                #: The closable half — keywords the candidate's own evidence
                #: already proves, so a truthful rewrite can surface them.
                "supportedGapKeywords": supported_gaps,
                #: The half no truthful rewrite can ever close.
                "unsupportedGapKeywords": unsupported_gaps,
                "rejected": tailor_result.rejected,
                "semanticPath": semantic_path,
                "qualityGate": iteration_gate,
            })

            rank = (1 if gate_ok else 0, ats_score.overall)
            if rank > best_rank:
                best_rank = rank
                best_score = ats_score.overall
                best_bullets = tailor_result.bullets
                best_iteration = i
                gate_verdict = iteration_gate

            reached_target = ats_score.overall >= self.target_score
            if reached_target and gate_ok:
                stop_reason = "target_reached"
                break
            if (
                reached_target
                and iteration_gate is not None
                and not gate_ok
                and not iteration_gate["closable"]
            ):
                # Every failing dimension is one that could not be MEASURED —
                # a degraded semantic score, not a weak draft. No rewrite can
                # move it, so iterating is paid effort bought for nothing (the
                # same reasoning ``split_gap_keywords`` applies to unreachable
                # keywords). Stop, and let the verdict below report it honestly
                # — the run is NOT a pass (``success`` stays False below), it
                # is a run whose quality could not be certified.
                stop_reason = "quality_gate_unmeasurable"
                break
            if reached_target and i >= budget:
                # U2c bounded gate budget. The score target is met, so without
                # the gate this run would already be finished — every further
                # attempt exists solely to close a dimension, and is paid for
                # out of the gate's own small, env-capped budget. Extended one
                # attempt at a time so the worst case is exactly
                # ``max_iterations + gate_extra_attempts``.
                if gate_attempts_used < self.gate_extra_attempts:
                    budget += 1
                    gate_attempts_used += 1
                else:
                    stop_reason = "quality_gate_cap"
                    break

            # AUD-LLM-1 item (a): the REAL cumulative token ceiling — read
            # from the LLM client's own usage reporting (the SAME chars-in/
            # chars-out accumulation ``routers/agents.py`` already costs a
            # run against), never the shared wall-clock deadline alone or the
            # iteration count alone. Checked every iteration so a
            # pathological run (a directive loop that never converges, an
            # oversized résumé/JD) is stopped BEFORE it burns another full
            # pass — honestly, with the best draft achieved so far. Mirrors
            # a6fae64a's ``llm_budget_exhausted`` handling one level up: never
            # a fake success, and never nothing to show for a run that DID
            # produce a real, guard-passed draft. ``usage_provider`` returns
            # ``None`` outside a real ``served_model_capture()`` scope
            # (replay/fixture-mode tests, lightweight test doubles) — that is
            # "no observation", never a licence to guess, so the check is a
            # no-op then, exactly like every other consumer of this signal.
            usage = self._usage_provider()
            if usage:
                used_tokens = (
                    max(0, int(usage.get("charsIn", 0))) // 4
                    + max(0, int(usage.get("charsOut", 0))) // 4
                )
                if used_tokens >= self.token_budget:
                    stop_reason = "token_budget_exhausted"
                    token_usage_at_stop = used_tokens
                    break

            # Prepare the next pass. Seed it with the BEST draft so far, not
            # simply the latest: when an iteration scores WORSE than an earlier
            # one, feeding its output forward compounds the regression, and the
            # run ultimately returns the best draft anyway — so every later pass
            # was refining text that would be thrown away.
            current_originals = best_bullets
            # The real posting is kept VERBATIM and the directive appended
            # under DIRECTIVE_MARKER — a pass that cannot see the job
            # description can neither mirror its terminology nor let the top-K
            # selector rank bullets against the actual role.
            directive = self._build_directive(
                ats_score.overall, supported_gaps, unsupported_gaps, iteration_gate
            )
            current_jd = f"{job_description}\n\n{directive}"

        # ADR-GMV4-001 (CONVERGE-BUT-FLAG): a degraded iteration's `overall`
        # is 40% a neutral placeholder, not a measurement, so it can never be
        # allowed to declare success — however cleanly it appears to clear
        # `target_score`. The tailored bullets are still returned (the
        # rewrite work is real and valuable even when the measurement is
        # not); only the automated success/failure VERDICT is withheld.
        # GMV4-ats-002 round 3: this check deliberately stays the narrower
        # ``== "degraded"`` test rather than the whitelist used by the
        # OTHER consumers (resumes.py/jobs.py/tailor_agent.py). Here,
        # "no provenance tracked at all" (semantic_path missing/"untracked")
        # means the CALLER opted out of this dimension entirely (e.g. a test
        # double pinning loop mechanics only) — it is not evidence that
        # scoring degraded, so it must not flip a real, converged pass to
        # requires_review. Only the engine's own explicit "degraded" verdict
        # — which real ``ATSEngine.score()`` calls always set unambiguously —
        # may withhold success here.
        # W-TAILOR-CONVERGE: the JD keywords still missing at the end of the
        # WINNING pass that the candidate's evidence cannot support. These are
        # a real, permanent ceiling on ``keyword_match`` for this pairing —
        # naming them is what makes a sub-target result honest rather than a
        # bare "we tried 5 times".
        unreachable_keywords: list[str] = []
        if best_iteration:
            unreachable_keywords = list(
                iterations[best_iteration - 1].get("unsupportedGapKeywords") or []
            )
        any_degraded = any(it.get("semanticPath") == "degraded" for it in iterations)
        degraded_count = sum(1 for it in iterations if it.get("semanticPath") == "degraded")
        reached_target = best_score >= self.target_score
        # U2c ENFORCEMENT: the 80%-all-dimensions floor is now a CONDITION of
        # success, not a number printed beside it. A run that clears the
        # headline ATS target with a dimension below the floor is honestly
        # sub-standard, and says so — the artifact still ships (below), but the
        # automated verdict is withheld exactly as it is for a degraded score.
        gate_passed = gate_verdict is None or bool(gate_verdict["passed"])
        success = reached_target and not any_degraded and gate_passed
        requires_review = not success
        warning = None
        if requires_review:
            if reached_target and not gate_passed and gate_verdict is not None:
                gate_summary = str(gate_verdict["summary"])
                # The failing dimensions, verbatim from the winning attempt's
                # REAL scores — never a rounded restatement, never a euphemism.
                warning = (
                    f"Best score achieved: {best_score:.1f}/100, which reaches "
                    f"the target of {self.target_score:.0f}/100 — but this "
                    f"résumé is {gate_summary[0].lower()}{gate_summary[1:]} "
                    f"Tailoring ran {len(iterations)} attempt(s), including "
                    f"{gate_attempts_used} extra attempt(s) spent trying to "
                    "close those dimensions truthfully. The result is "
                    "delivered as-is: nothing was inflated, and no claim your "
                    "evidence does not support was added to reach the floor. "
                    "Please review it before submitting."
                )
                if any_degraded:
                    warning += (
                        f" Note: semantic scoring was also DEGRADED on "
                        f"{degraded_count} of {len(iterations)} iteration(s), "
                        "so part of the score above is a placeholder rather "
                        "than a measurement."
                    )
            elif any_degraded and reached_target:
                warning = (
                    f"Best score achieved: {best_score:.1f}/100, which reaches "
                    f"the target of {self.target_score:.0f}/100 — but semantic "
                    f"scoring was DEGRADED on {degraded_count} of "
                    f"{len(iterations)} iteration(s) (no genuine embedding "
                    "model or HF Inference API was available), so part of "
                    "that score is a neutral placeholder rather than a real "
                    "measurement. This result cannot be accepted as a "
                    "verified pass — please review this resume manually "
                    "before submitting."
                )
            else:
                warning = (
                    f"Tailoring stopped after {len(iterations)} iteration(s) "
                    f"without reaching the target ATS score of "
                    f"{self.target_score:.0f}. Best score achieved: "
                    f"{best_score:.1f}/100. Please review this resume manually "
                    "before submitting."
                )
                if stop_reason == "llm_budget_exhausted":
                    warning += (
                        " The run was also CUT SHORT before its iteration "
                        "budget was spent because the writing model ran out "
                        f"of time ({llm_error}) — the score above is what the "
                        "completed passes actually achieved, not an estimate "
                        "of what further passes would have reached."
                    )
                if stop_reason == "token_budget_exhausted":
                    warning += (
                        " The run was also CUT SHORT before its iteration "
                        "budget was spent because it reached its token budget "
                        f"({token_usage_at_stop} tokens used of a "
                        f"{self.token_budget}-token ceiling) — the score "
                        "above is what the completed passes actually "
                        "achieved, not an estimate of what further passes "
                        "would have reached."
                    )
                if unreachable_keywords:
                    shown = ", ".join(unreachable_keywords[:12])
                    more = len(unreachable_keywords) - 12
                    if more > 0:
                        shown += f" (+{more} more)"
                    warning += (
                        " The remaining gap is not something a rewrite can "
                        "close: these job-description keywords appear nowhere "
                        "in your résumé, story bank or career data, so adding "
                        "them would be fabrication and was refused — "
                        f"{shown}."
                    )
                if any_degraded:
                    warning += (
                        f" Note: semantic scoring was also DEGRADED on "
                        f"{degraded_count} of {len(iterations)} iteration(s), "
                        "so even this best score is only partially genuine."
                    )
                if gate_verdict is not None and not gate_passed:
                    warning += f" {gate_verdict['summary']}"

        return TailoringLoopResult(
            iterations=iterations,
            final_bullets=best_bullets,
            best_score=best_score,
            best_iteration=best_iteration,
            success=success,
            requires_review=requires_review,
            warning=warning,
            unreachable_keywords=unreachable_keywords,
            stop_reason=stop_reason,
            quality_gate=gate_verdict,
            gate_attempts_used=gate_attempts_used,
        )

    # -- internals -------------------------------------------------------

    def _service_accepts(self, parameter: str) -> bool:
        """True when the injected tailor service's ``tailor`` really accepts
        ``parameter`` (or absorbs it via ``**kwargs``).

        ``service`` is duck-typed (see the class docstring): production wires
        the real :class:`~app.services.resume_tailor.ResumeTailorService`,
        while tests pin loop mechanics with small stubs written against the
        historic 4-argument signature. Introspecting once — instead of
        catching ``TypeError`` around the call, which would also swallow a
        genuine ``TypeError`` raised INSIDE a real tailoring pass — keeps both
        working without ever hiding a real failure.
        """
        import inspect

        try:
            params = inspect.signature(self._service.tailor).parameters
        except (TypeError, ValueError):  # pragma: no cover — exotic callables
            return False
        if parameter in params:
            return True
        return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())

    @staticmethod
    def _corpus(resume_text: str, bullets: list[dict[str, str]]) -> str:
        """Résumé context (skills/summary/headers) + bullet text — the same
        like-for-like corpus ``_compute_conversion_metrics`` scores, so the
        loop's own convergence decisions match what the UI ultimately shows.
        """
        context = strip_bullet_lines(resume_text)
        bullet_text = "\n".join(b.get("text", "") for b in bullets)
        return f"{context}\n{bullet_text}" if context else bullet_text

    def _build_directive(
        self,
        score: float,
        supported_gaps: list[str],
        unsupported_gaps: list[str],
        gate: dict[str, Any] | None = None,
    ) -> str:
        """The retry directive appended BELOW the verbatim job description.

        It names the score gap and — crucially — only the gap keywords the
        candidate's own evidence already proves. Keywords the evidence cannot
        support are listed explicitly as forbidden, so the model is told not
        to reach for them rather than being left to guess (which previously
        produced a steady stream of rewrites the entailment guard rejected).

        U2c: when the quality gate is armed, the directive additionally names
        the DIMENSIONS still under the floor with their real numbers. Telling
        the model "keyword match is 61% and must exceed 80%" is a concrete,
        checkable objective; leaving it to infer that from a keyword list is
        how a pass wanders. The prohibition below is restated either way —
        naming a target a rewrite must hit never licenses inventing the
        evidence to hit it, and the guard adjudicates the result unchanged.
        """
        gap = max(0.0, self.target_score - score)
        lines = [
            DIRECTIVE_MARKER,
            "Iterative refinement retry. The job description above is "
            "unchanged and still authoritative.",
            f"The previous draft scored {score:.1f}/100 against an ATS "
            f"target of {self.target_score:.0f}/100 (a gap of {gap:.1f} "
            "points).",
        ]
        if gate is not None and not gate.get("passed"):
            failing = [
                d for d in (gate.get("failing") or []) if d.get("measured")
            ]
            if failing:
                lines.append(
                    "These quality dimensions are still below the "
                    f"{gate['floor']:.0f}% floor and are what this pass must "
                    "raise: "
                    + "; ".join(
                        f"{d['label']} {float(d['score']):.1f}%" for d in failing
                    )
                    + "."
                )
        if supported_gaps:
            lines.append(
                "Close the gap by TRUTHFULLY surfacing these still-missing, "
                "job-relevant keywords, each of which the candidate's own "
                "evidence already proves — rewrite the bullets where that "
                "evidence lives so the job description's own word for it "
                "appears: "
                + ", ".join(supported_gaps)
                + "."
            )
        else:
            lines.append(
                "Every job-relevant keyword the candidate's evidence supports "
                "is already present. Continue strengthening the resume's "
                "alignment with the role using only truthful, evidence-backed "
                "language — do not add new claims."
            )
        # Always restate the prohibition, and name the specific terms that
        # trip it, whether or not there is anything left to close.
        forbidden = (
            "NEVER invent or fabricate a skill, tool, employer, certification "
            "or achievement the candidate does not have."
        )
        if unsupported_gaps:
            forbidden += (
                " In particular, the job description mentions the following, "
                "and the candidate's evidence proves NONE of them — they must "
                "stay out of the resume entirely: "
                + ", ".join(unsupported_gaps)
                + "."
            )
        lines.append(forbidden)
        return "\n".join(lines)
