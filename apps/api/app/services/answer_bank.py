"""U5d-3 Pillar 1 — the Screening Answer Bank: matching, classes, seed set.

ADR-SUB-AUTON-1 (binding): *"the submission agent learns from every screening
question I answer so future applications don't wait for my response"* — while
the honesty floor stands unchanged: **the agent NEVER invents an answer. Full
autonomy is achieved by GROWING THE BANK, never by lowering this bar.**

This module is the part of the bank that decides things. It is PURE — no I/O,
no network, no clock beyond an injectable ``now`` — so every rule below is
pinned by ``tests/test_u5d3_answer_bank_matching.py`` rather than by luck.

WHY NOT EMBEDDINGS
------------------
The obvious implementation is "embed both questions, take the cosine". This
codebase already owns an embedding path (``ats_engine``: sentence-transformers
locally, HF Inference as fallback) and it is deliberately NOT used here:

* it is a heavyweight model load on a 2-CPU box, on the hot path of a live
  submission, for strings averaging eight words;
* it fails OPEN in the direction that matters least and closed in the direction
  that matters most — cosine similarity rates *"What is your current salary?"*
  and *"What are your salary expectations?"* as near-identical, because they
  are, lexically and semantically, about the same topic. They are opposite
  questions about the candidate, and answering one with the other publishes a
  number the candidate never said. That single failure mode is the whole risk
  surface of this feature;
* a remote embedding call adds a spend-capped network dependency to a path that
  must be able to say "no honest answer" instantly and offline.

So matching is CONCEPT-FIRST and lexical-second. A curated table of screening
CONCEPTS (:data:`CONCEPTS`) — the real question classes ATS platforms ask, with
the discriminating terms that separate the confusable pairs — decides whether
two questions are ABOUT THE SAME THING. Only then does wording similarity
(stdlib ``difflib`` + token-set overlap, no new dependency) decide how sure we
are. Two questions carrying DIFFERENT concepts score exactly 0.0 no matter how
similar their words are, which is precisely the guard an embedding lacks.

SAME CLASS IS NOT SAME QUESTION. Some classes carry a SUBJECT that decides what
the true answer is: the skill in *"how many years of Kubernetes"*, the employer
in *"why do you want to work at Northwind"*. Those concepts are marked
``subject_sensitive``, and two questions in them must agree on their subject
(:func:`question_subject`) or they score 0.0 — otherwise a general "11 years,
the last 5 in platform engineering" would be sent as a claim about Kubernetes,
and a paragraph about one employer would be sent to another. Both are
inventions in the honesty floor's sense: the user never said either thing.
Wording similarity cannot catch this — the pairs differ by one word and score
~0.95 — which is why the guard sits ahead of the threshold, not behind it.

THE THREE SENSITIVITY CLASSES, and what each one is allowed to do
-----------------------------------------------------------------
* ``factual`` — stable facts about the candidate (work rights, notice period,
  years per skill, relocation). Auto-answered from the bank above the
  confidence threshold.
* ``judgment`` — role-specific judgement calls (salary expectation, motivation
  prose). ADR: these *"start user-gated and may be widened to auto AFTER the
  user approves"*. Here that widening is one explicit per-item switch the user
  flips in the Answer Bank UI (``autoAnswerOptIn``); the ratchet that widens a
  whole class automatically is U5d-4 (Pillar 2).
* ``sensitive`` — background-check consent, diversity/EEO disclosures, criminal
  history, health/disability, and visa SPECIFICS (sponsorship need, subclass,
  expiry). **Never auto-answered. There is no opt-in.** This is stricter than
  ADR Pillar 2's "individually opt-in-able" wording, deliberately: the U5d-3
  brief pins these as always user-gated, and the honesty ratchet only ever
  turns one way (tighter is always allowed; looser needs an orchestrator
  ruling).

WHAT "user-gated" DOES NOT MEAN. A sensitive question is refused for
AUTO-answering from the bank — the silent reuse of an old answer on a new
employer's form. It is NOT refused when the user types the answer for THAT
application in the card right now: that is the user answering, not the agent
guessing. The per-application layer in :func:`build_resolver` carries exactly
that distinction.

ACKNOWLEDGEMENT IS NOT CONSENT (SUB-008). The ``acknowledgement`` class covers
the tick-boxes that restate what the applicant is already doing by applying —
"the information I have given is true", "I have read your privacy policy", "I
agree to your application terms". It is factual, so one banked answer covers
every form that asks. A box that grants PERMISSION — a background, police or
credit check, a medical, a diversity disclosure — is NOT in that class: those
keep their own sensitive concept (which wins by list order) and are vetoed by
``none_of`` on top, so no standing answer can ever tick one.

NOTE ON THE WORK-RIGHTS / VISA SPLIT (flagged for the orchestrator). The brief
names "visa specifics" as sensitive; the ADR names "work rights" as a factual
class in both the seed questionnaire and the ratchet. These are treated as two
different concepts here — ``work_rights`` ("are you legally allowed to work in
X", factual) versus ``visa_details`` (sponsorship / subclass / expiry,
sensitive). If the intended reading was that ALL work-authorisation questions
are sensitive, changing ``_CONCEPT_WORK_RIGHTS.sensitivity`` to
``SENSITIVITY_SENSITIVE`` is the entire change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Callable, Iterable, Sequence

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: A stable fact about the candidate. Auto-answerable once banked.
SENSITIVITY_FACTUAL = "factual"
#: A judgement call. User-gated until the user opts THIS item in.
SENSITIVITY_JUDGMENT = "judgment"
#: Sensitive / legal. NEVER auto-answered, regardless of bank contents.
SENSITIVITY_SENSITIVE = "sensitive"

#: Ordered weakest → strongest. The gate always takes the STRONGER of the
#: incoming question's class and the banked item's, so a mislabelled row can
#: never open a gate its question should have closed.
_SENSITIVITY_RANK = {
    SENSITIVITY_FACTUAL: 0,
    SENSITIVITY_JUDGMENT: 1,
    SENSITIVITY_SENSITIVE: 2,
}

#: Where a banked answer applies.
SCOPE_GLOBAL = "global"
SCOPE_COMPANY = "company"
SCOPE_JOB_FAMILY = "job_family"
SCOPES = frozenset({SCOPE_GLOBAL, SCOPE_COMPANY, SCOPE_JOB_FAMILY})

#: How an answer got into the bank. Every item carries one; there is no
#: "derived" or "assumed" provenance, because no such answer may exist.
PROVENANCE_USER_ANSWERED = "user_answered"
PROVENANCE_ONBOARDING = "onboarding"
PROVENANCE_PROFILE_CONFIRMED = "profile_confirmed"
PROVENANCES = frozenset(
    {PROVENANCE_USER_ANSWERED, PROVENANCE_ONBOARDING, PROVENANCE_PROFILE_CONFIRMED}
)

#: The confidence a match must reach before the agent will answer WITHOUT
#: asking. Anything below becomes an honest manual step — which then banks the
#: user's answer, so the same question never blocks twice.
#:
#: Calibrated against :data:`CONCEPTS`: a concept match starts at 0.90 and a
#: pure-wording match has to be almost verbatim to reach 0.86, so the failure
#: mode of a wrong threshold is "asks the user again", never "answers wrongly".
AUTO_ANSWER_CONFIDENCE = 0.86

#: Cap applied when exactly ONE of the two questions carries a recognised
#: concept. That asymmetry is evidence they are not the same question, so the
#: pair can never reach :data:`AUTO_ANSWER_CONFIDENCE` on wording alone.
_MIXED_CONCEPT_CAP = 0.85

#: Filler that carries no meaning in a screening question. "not"/"never"/"no"
#: are deliberately ABSENT — dropping a negation would let "do you require
#: sponsorship" answer "do you NOT require sponsorship".
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "am", "was", "were", "be", "been", "being",
        "do", "does", "did", "you", "your", "yours", "yourself", "have", "has",
        "had", "will", "would", "shall", "should", "can", "could", "may", "might",
        "must", "to", "of", "in", "on", "at", "for", "with", "and", "or", "as",
        "by", "from", "this", "that", "these", "those", "it", "its", "if", "we",
        "us", "our", "i", "me", "my", "mine", "please", "kindly", "there", "here",
        "about", "into", "over", "under", "than", "then", "so", "such", "please",
        "select", "choose", "enter", "provide", "tell", "describe", "briefly",
    }
)

_NON_WORD = re.compile(r"[^a-z0-9]+")

#: ``don't`` / ``doesn't`` / ``can't`` → ``do not`` / ``does not`` / ``can not``.
#: Expanded BEFORE punctuation is stripped, because stripping it first turns
#: "don't" into the tokens "don" + "t" and the negation disappears — which is
#: precisely the failure :func:`match_confidence`'s polarity guard exists to
#: prevent. Both ASCII and typographic apostrophes are handled.
_CONTRACTED_NOT = re.compile(r"n['’]t\b")

#: Words that flip a question's meaning. Kept deliberately SMALL and
#: unambiguous: every entry here forces a 0.0 match against a question that
#: lacks it, so a loose entry ("no", which appears innocently in "no
#: restrictions") would block legitimate matches rather than allow wrong ones.
#: Erring toward "ask the user again" is the correct direction, but needlessly
#: is still a cost.
_NEGATIONS = frozenset({"not", "never", "cannot", "unable", "neither", "nor"})


def normalize_question(text: str) -> str:
    """Lower-cased, punctuation-free, whitespace-collapsed question text.

    The canonical string every other function in this module compares. It is
    deliberately lossy about typography and nothing else: no stemming, no
    synonym substitution, no stopword removal happens here, so
    :func:`normalize_question` alone can never make two different questions
    look identical.

    The ONE substitution it does make is expanding ``n't`` to ``not``, so a
    contraction cannot smuggle a negation past the polarity guard.
    """
    lowered = _CONTRACTED_NOT.sub(" not", str(text or "").lower())
    return _NON_WORD.sub(" ", lowered).strip()


def is_negated(text: str) -> bool:
    """Whether a question carries a meaning-flipping negation."""
    return bool(question_tokens(text) & _NEGATIONS)


def _singular(token: str) -> str:
    """Crude de-pluralisation. Only ever removes a trailing "s" from a token
    long enough that doing so cannot create a different word ("years" →
    "year"), which is all these questions need."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def question_tokens(text: str) -> frozenset[str]:
    """The content tokens of a question — filler out, negations kept."""
    return frozenset(
        _singular(token)
        for token in normalize_question(text).split()
        if token and token not in _STOPWORDS
    )


# ---------------------------------------------------------------------------
# Concepts — the real screening-question classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Concept:
    """One screening-question class.

    ``any_of`` is an OR of ANDs: the concept matches when EVERY term of at
    least one inner tuple appears in the normalised question. ``none_of``
    vetoes the match — that is what separates the confusable pairs (a salary
    question mentioning "current" is not a salary EXPECTATION question).

    ``stale_days`` is the staleness policy the ADR asks for: how long an
    answer to this class of question stays true. ``None`` means "does not go
    stale" (work rights, references) — an expiry invented for those would make
    the agent re-ask a question whose answer never changed.

    ``subject_sensitive`` marks a class whose questions carry a SUBJECT that
    changes what the true answer is — the named skill in "how many years of
    <X>", the named employer in "why do you want to work at <Y>". For those,
    sharing the class is not enough to reuse an answer; see
    :func:`question_subject`.
    """

    key: str
    sensitivity: str
    stale_days: int | None
    any_of: tuple[tuple[str, ...], ...]
    none_of: tuple[str, ...] = ()
    subject_sensitive: bool = False

    def matches(self, normalized: str) -> bool:
        padded = f" {normalized} "
        for veto in self.none_of:
            if f" {veto} " in padded:
                return False
        for group in self.any_of:
            if all(f" {term} " in padded for term in group):
                return True
        return False

    def vocabulary(self) -> frozenset[str]:
        """Every term this concept recognises itself by.

        These are the words that put a question IN the class, so they cannot
        also be what distinguishes two questions within it.
        """
        return frozenset(
            _singular(term) for group in self.any_of for term in group
        )


_CONCEPT_WORK_RIGHTS = Concept(
    key="work_rights",
    sensitivity=SENSITIVITY_FACTUAL,
    stale_days=None,
    any_of=(
        ("legally", "work"),
        ("right", "work"),
        ("rights", "work"),
        ("authorised", "work"),
        ("authorized", "work"),
        ("eligible", "work"),
        ("permitted", "work"),
        ("work", "entitlement"),
    ),
    # A question that mentions sponsorship or a visa subclass is a visa
    # SPECIFICS question (sensitive), not the stable yes/no work-rights one.
    none_of=("sponsorship", "sponsor", "subclass", "visa", "expiry", "expires"),
)

#: Order is meaningful: the FIRST concept that matches wins, so the sensitive
#: and the narrower classes are listed before the broad ones they could be
#: confused with.
CONCEPTS: tuple[Concept, ...] = (
    # ---- sensitive / legal: never auto-answered -------------------------
    Concept(
        key="background_check",
        sensitivity=SENSITIVITY_SENSITIVE,
        stale_days=None,
        any_of=(
            ("background", "check"),
            ("police", "check"),
            ("criminal", "check"),
            ("criminal", "record"),
            ("criminal", "history"),
            ("convicted",),
            ("conviction",),
            ("vetting",),
            ("working", "children", "check"),
        ),
    ),
    Concept(
        key="diversity",
        sensitivity=SENSITIVITY_SENSITIVE,
        stale_days=None,
        any_of=(
            ("gender",),
            ("ethnicity",),
            ("ethnic",),
            ("race",),
            ("racial",),
            ("aboriginal",),
            ("torres", "strait"),
            ("indigenous",),
            ("disability",),
            ("disabilities",),
            ("veteran",),
            ("sexual", "orientation"),
            ("eeo",),
            ("equal", "opportunity"),
            ("pronoun",),
        ),
    ),
    Concept(
        key="visa_details",
        sensitivity=SENSITIVITY_SENSITIVE,
        stale_days=None,
        any_of=(
            ("sponsorship",),
            ("sponsor",),
            ("visa",),
            ("work", "permit"),
            ("immigration",),
            ("citizenship",),
            ("residency",),
        ),
    ),
    Concept(
        key="health_disclosure",
        sensitivity=SENSITIVITY_SENSITIVE,
        stale_days=None,
        any_of=(
            ("medical", "condition"),
            ("health", "condition"),
            ("drug", "test"),
            ("drug", "screening"),
            ("pre", "employment", "medical"),
            ("vaccination",),
            ("vaccinated",),
        ),
    ),
    Concept(
        key="security_clearance",
        sensitivity=SENSITIVITY_SENSITIVE,
        stale_days=None,
        any_of=(
            ("security", "clearance"),
            ("baseline", "clearance"),
            ("nv1",),
            ("nv2",),
        ),
    ),
    # ---- recurring form furniture (SUB-008) -----------------------------
    # Two classes every ATS asks and the bank had no word for, so a user who
    # had answered them ten times still met a manual step on the eleventh.
    #
    # WHERE THEY SIT, AND WHY. After the sensitive block, because order breaks
    # ties: a tick that CONSENTS to a check ("I acknowledge that a police
    # check will be carried out") must reach its own sensitive class first,
    # whatever acknowledgement-shaped words it also carries. Before the broad
    # factual classes, because those recognise themselves by single common
    # words ("remote", "notice", "reference") that a referral or an
    # acknowledgement sentence can mention in passing.
    Concept(
        key="referral_source",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=None,
        any_of=(
            ("how", "hear"),
            ("where", "hear"),
            ("how", "learn"),
            ("where", "learn"),
            ("how", "find", "out"),
            ("how", "come", "across"),
            ("where", "see", "advertised"),
            ("where", "advertised"),
            ("referral", "source"),
        ),
        # A compound question that also asks WHY belongs to ``motivation`` —
        # judgement, user-gated. Answering "LinkedIn" to "why do you want to
        # work here, and how did you hear about us?" would be both wrong and
        # ungated, so the veto hands the whole question to the stricter class.
        none_of=("why", "motivate", "motivation", "salary"),
    ),
    Concept(
        key="acknowledgement",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=None,
        # PURE acknowledgements only: a statement the applicant is already
        # making by applying ("what I have written is true", "I have read your
        # privacy policy", "I agree to your application terms"). Each group
        # pairs a commitment verb with what is being committed to, so an
        # employer's free-text question that merely MENTIONS a privacy policy
        # does not land here.
        any_of=(
            ("acknowledge",),
            ("acknowledgement",),
            ("acknowledgment",),
            ("certify",),
            ("confirm", "true"),
            ("confirm", "accurate"),
            ("confirm", "correct"),
            ("information", "true"),
            ("information", "accurate"),
            ("declare", "true"),
            ("declaration", "true"),
            ("read", "understood"),
            ("read", "agree"),
            ("read", "accept"),
            ("read", "privacy"),
            ("agree", "term"),
            ("agree", "condition"),
            ("agree", "privacy"),
            ("accept", "term"),
            ("accept", "condition"),
            ("accept", "privacy"),
        ),
        # The line between "acknowledgement" and "consent". A tick that grants
        # PERMISSION (a background, police or credit check, a medical, a
        # diversity disclosure), or that carries another class's subject
        # matter at all, is not a pure acknowledgement and must never be
        # ticked from a standing answer. The sensitive concepts above already
        # win by order; this veto is the second lock, and it fails toward
        # "ask the user" — the only safe direction.
        none_of=(
            "consent", "consents", "consenting", "authorise", "authorize",
            "authorisation", "authorization", "permission",
            "background", "criminal", "police", "conviction", "convictions",
            "convicted", "vetting",
            "medical", "health", "drug", "drugs", "vaccination", "vaccinated",
            "visa", "visas", "sponsorship", "sponsor", "immigration",
            "citizenship", "residency",
            "gender", "ethnicity", "ethnic", "race", "racial", "disability",
            "disabilities", "veteran", "eeo", "aboriginal", "indigenous",
            "clearance",
            "salary", "salaries", "remuneration", "compensation",
            "work", "working", "employment", "licence", "license",
            "reference", "references", "referee", "referees", "credit",
            "notice period", "relocate", "relocation", "travel",
        ),
    ),
    # ---- judgement: user-gated until the user opts the item in ----------
    Concept(
        key="salary_current",
        sensitivity=SENSITIVITY_JUDGMENT,
        stale_days=180,
        any_of=(
            ("current", "salary"),
            ("current", "remuneration"),
            ("current", "package"),
            ("present", "salary"),
            ("existing", "salary"),
        ),
    ),
    Concept(
        key="salary_expectation",
        sensitivity=SENSITIVITY_JUDGMENT,
        stale_days=180,
        any_of=(
            ("salary",),
            ("remuneration",),
            ("compensation",),
            ("pay", "expectation"),
            ("expected", "rate"),
            ("day", "rate"),
            ("hourly", "rate"),
        ),
        none_of=("current", "present", "existing"),
    ),
    Concept(
        key="motivation",
        sensitivity=SENSITIVITY_JUDGMENT,
        stale_days=None,
        any_of=(
            ("why", "want", "work"),
            ("why", "interested"),
            ("why", "applying"),
            ("why", "you"),
            ("motivate",),
            ("motivation",),
            ("cover", "letter"),
        ),
        # "Why do you want to work at Northwind?" answered from an answer
        # written about Harbourline would send an employer a paragraph
        # enthusing about a DIFFERENT company. The subject is the employer.
        subject_sensitive=True,
    ),
    # ---- factual: auto-answerable once banked ---------------------------
    _CONCEPT_WORK_RIGHTS,
    Concept(
        key="notice_period",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=180,
        any_of=(
            ("notice", "period"),
            ("notice",),
            ("resignation", "period"),
        ),
    ),
    Concept(
        key="start_date",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=90,
        any_of=(
            ("start", "date"),
            ("available", "start"),
            ("availability", "start"),
            ("commence",),
            ("earliest", "start"),
            ("when", "start"),
        ),
    ),
    Concept(
        key="relocation",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=None,
        any_of=(
            ("relocate",),
            ("relocation",),
            ("willing", "move"),
        ),
    ),
    Concept(
        key="remote_preference",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=None,
        any_of=(
            ("remote",),
            ("hybrid",),
            ("work", "home"),
            ("onsite",),
            ("office", "day"),
            ("flexible", "working"),
        ),
    ),
    Concept(
        key="references",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=None,
        any_of=(
            ("reference",),
            ("referee",),
        ),
    ),
    Concept(
        key="notice_of_travel",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=None,
        any_of=(
            ("willing", "travel"),
            ("travel", "requirement"),
        ),
    ),
    Concept(
        key="years_experience",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=365,
        any_of=(
            ("year", "experience"),
            ("how", "many", "year"),
            ("year", "commercial"),
        ),
        # Employers ask this PER SKILL. "11 years, the last 5 in platform
        # engineering" is a true answer about a career and a FABRICATED one
        # about Kubernetes — the subject is the skill, and it must agree.
        subject_sensitive=True,
    ),
    Concept(
        key="drivers_licence",
        sensitivity=SENSITIVITY_FACTUAL,
        stale_days=None,
        any_of=(
            ("driver", "licence"),
            ("driver", "license"),
            ("drivers", "licence"),
            ("drivers", "license"),
        ),
    ),
)


def detect_concept(text: str) -> Concept | None:
    """The screening-question class ``text`` belongs to, or ``None``.

    ``None`` is a first-class, common answer — most employer-specific
    questions ("Describe a time you disagreed with your manager") belong to no
    class, and the matcher then falls back to wording similarity alone.
    """
    normalized = normalize_question(text)
    if not normalized:
        return None
    # Match on the singularised token stream too, so "years of experience"
    # and "year of experience" reach the same concept.
    singular = " ".join(_singular(token) for token in normalized.split())
    for concept in CONCEPTS:
        if concept.matches(normalized) or concept.matches(singular):
            return concept
    return None


#: Words that generalise a question without naming a subject. Removing them is
#: what makes "how many years of PROFESSIONAL experience in your FIELD" and
#: "how many years of experience" the same (subject-free) question, while
#: leaving "Kubernetes" as the thing that distinguishes a skill-specific one.
#: Deliberately small: anything wrongly listed here would let two genuinely
#: different subjects look identical, which is the failure this guard exists to
#: prevent — so a term earns its place only by being pure filler in EVERY
#: subject-sensitive class.
_GENERIC_SUBJECT_TERMS = frozenset(
    {
        "professional",
        "total",
        "overall",
        "relevant",
        "field",
        "industry",
        "career",
        "hand",  # "hands-on"
        "role",
        "position",
        "job",
        "company",
        "organisation",
        "organization",
        "team",
        "opportunity",
        "vacancy",
        "here",
    }
)


def question_subject(text: str, concept: "Concept | None" = None) -> frozenset[str]:
    """What a question is ABOUT, beyond the class it belongs to.

    The content tokens left after removing the concept's own vocabulary (the
    words that put the question in the class) and the generic modifiers that
    carry no subject. For "how many years of Kubernetes experience" that is
    ``{"kubernete"}``; for "how many years of professional experience in your
    field" it is the EMPTY set — the question names no subject, so an answer to
    it is a general one.

    An empty set is therefore meaningful, not missing: it says "this question
    is the general form of its class".
    """
    resolved = concept if concept is not None else detect_concept(text)
    if resolved is None:
        return frozenset()
    return frozenset(
        token
        for token in question_tokens(text)
        if token not in resolved.vocabulary() and token not in _GENERIC_SUBJECT_TERMS
    )


def classify_sensitivity(text: str) -> str:
    """The sensitivity class of a question, from its own words.

    Falls back to :data:`SENSITIVITY_FACTUAL` for an unrecognised question:
    that is safe here because an unrecognised question can only ever be
    auto-answered from an item the USER wrote for that same question, and the
    sensitive vocabulary above is matched on the QUESTION AS ASKED before any
    such item is consulted.
    """
    concept = detect_concept(text)
    return concept.sensitivity if concept else SENSITIVITY_FACTUAL


def stale_days_for(text: str) -> int | None:
    """The staleness policy for a question's class; ``None`` = never stales."""
    concept = detect_concept(text)
    return concept.stale_days if concept else None


def semantic_key(text: str) -> str:
    """A stable retrieval key for a question.

    Two phrasings of the SAME concept share a key (``concept:work_rights``),
    which is what lets the bank be looked up by index rather than scanned. A
    question belonging to no concept gets a key built from its own sorted
    content tokens, so exact re-asks still hit the index — and two questions
    about different things never collide, because their token sets differ.

    For a SUBJECT-SENSITIVE concept the subject is part of the key
    (``concept:years_experience:kubernete``). The key is also the bank's
    uniqueness constraint, so without this the user's Kubernetes answer and
    their Python answer would be one row overwriting the other — losing an
    answer they gave, which is the same honesty failure as inventing one.
    """
    concept = detect_concept(text)
    if concept is not None:
        if concept.subject_sensitive:
            subject = "-".join(sorted(question_subject(text, concept)))
            return f"concept:{concept.key}:{subject}"
        return f"concept:{concept.key}"
    tokens = sorted(question_tokens(text))
    return "tokens:" + "-".join(tokens) if tokens else "tokens:"


def concept_of(key: str) -> str:
    """The concept name inside a semantic key, or ``""`` for a token key.

    The inverse of the ``concept:`` half of :func:`semantic_key`, and the ONLY
    sanctioned way to read a concept back out of a stored key: a
    subject-sensitive class appends its subject
    (``concept:years_experience:kubernete``), so stripping the prefix alone
    yields ``years_experience:kubernete`` and silently fails to match the
    concept it names.
    """
    if not key.startswith("concept:"):
        return ""
    return key.removeprefix("concept:").split(":", 1)[0]


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def match_confidence(asked: str, banked: str) -> tuple[float, str]:
    """How sure we are that ``asked`` and ``banked`` are the same question.

    Returns ``(confidence, method)`` where method is one of ``exact``,
    ``concept``, ``lexical`` or ``concept_mismatch``.

    The rules, in order:

    1. **Identical after normalisation** → 1.0. Nothing to be unsure about.
    2. **Opposite polarity** → exactly 0.0. Two questions can share a concept
       AND nearly every word and still be opposites — "are you authorised to
       work here" vs "are you NOT authorised to work here". Checked BEFORE the
       concept rule precisely because the concept rule would otherwise score
       that pair ~0.98 and publish the reverse of what the candidate said.
    3. **Two DIFFERENT recognised concepts** → exactly 0.0, whatever the words
       look like. This is the guard that stops "current salary" answering
       "salary expectations", and it is the reason this function is not a
       similarity metric.
    4. **The same concept** → 0.90, lifted toward 1.0 by how much of the
       wording also agrees. Same class + same words is as close to certain as
       this product gets without asking.
    5. **Neither carries a concept** → wording only: token-set overlap (60%)
       and character-level similarity (40%). Reaching 0.86 on wording alone
       takes a near-verbatim re-ask, which is exactly when it is safe.
    6. **Exactly one carries a concept** → wording only, capped below the auto
       threshold, so it always becomes an honest manual step.
    """
    left_norm, right_norm = normalize_question(asked), normalize_question(banked)
    if not left_norm or not right_norm:
        return 0.0, "lexical"
    if left_norm == right_norm:
        return 1.0, "exact"

    if is_negated(asked) != is_negated(banked):
        return 0.0, "polarity_mismatch"

    left_concept, right_concept = detect_concept(asked), detect_concept(banked)
    if left_concept is not None and right_concept is not None:
        if left_concept.key != right_concept.key:
            return 0.0, "concept_mismatch"
        if left_concept.subject_sensitive and question_subject(
            asked, left_concept
        ) != question_subject(banked, right_concept):
            # Same class, different subject. These two questions differ by a
            # single word and would score ~0.95 on wording, which is exactly
            # why the check is here and not left to the threshold.
            return 0.0, "subject_mismatch"

    left_tokens, right_tokens = question_tokens(asked), question_tokens(banked)
    lexical = 0.6 * _jaccard(left_tokens, right_tokens) + 0.4 * SequenceMatcher(
        None, left_norm, right_norm
    ).ratio()

    if left_concept is not None and right_concept is not None:
        return round(min(1.0, 0.90 + 0.10 * lexical), 4), "concept"
    if left_concept is None and right_concept is None:
        return round(lexical, 4), "lexical"
    return round(min(_MIXED_CONCEPT_CAP, lexical), 4), "lexical"


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnswerBankMatch:
    """One auto-answer, with everything an audit needs to re-check it.

    ADR honesty floor 3: *"every auto-answer is auditable (which banked
    answer, which match confidence)"*. That is this dataclass — the answer
    never travels without the three facts that justify it, and
    ``question_as_seen`` is the employer's OWN wording, kept so a later reader
    can judge the match rather than take it on trust.
    """

    item_id: str
    answer: str
    confidence: float
    method: str
    question_as_seen: str
    banked_question: str
    sensitivity: str
    provenance: str
    #: True when this came from the answers the user typed for THIS
    #: application (Pillar 4a), rather than from the standing bank.
    per_application: bool = False


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _is_expired(item: dict[str, Any], now: datetime) -> bool:
    expires = _as_datetime(item.get("expiresAt"))
    return expires is not None and expires <= now


def _scope_applies(item: dict[str, Any], company: str | None, job_family: str | None) -> bool:
    scope = str(item.get("scope") or SCOPE_GLOBAL)
    if scope == SCOPE_GLOBAL:
        return True
    target = normalize_question(item.get("scopeValue") or "")
    if not target:
        return False
    if scope == SCOPE_COMPANY:
        return bool(company) and normalize_question(company or "") == target
    if scope == SCOPE_JOB_FAMILY:
        return bool(job_family) and normalize_question(job_family or "") == target
    return False


def _effective_sensitivity(asked: str, item: dict[str, Any]) -> str:
    """The STRONGER of the question's own class and the banked item's.

    Reading both is what makes the gate un-bypassable: an item stored (or
    edited) with a soft class cannot open a gate that the question as asked
    would have closed.
    """
    question_class = classify_sensitivity(asked)
    item_class = str(item.get("sensitivity") or SENSITIVITY_FACTUAL)
    if _SENSITIVITY_RANK.get(item_class, 0) > _SENSITIVITY_RANK.get(question_class, 0):
        return item_class
    return question_class


def effective_sensitivity(item: dict[str, Any]) -> str:
    """The class that actually governs a STORED row.

    The public form of :func:`_effective_sensitivity`. Callers outside the
    matcher must use this rather than reading the ``sensitivity`` column, so
    that a row stored with a softer class than its own wording is reported —
    and gated — as the stronger of the two, exactly as the agent treats it.
    """
    return _effective_sensitivity(str(item.get("questionText") or ""), item)


def item_is_expired(item: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Has this banked answer passed its staleness policy?

    The public form of the check :func:`find_match` applies internally, so a
    caller outside the matcher (the bank page, the readiness figures) reads
    expiry from the same rule the agent obeys instead of re-deriving it.
    """
    return _is_expired(item, now or datetime.now(timezone.utc))


def item_auto_answers(item: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Will Aether send this answer WITHOUT asking the user first?

    The single source of truth for the one fact a user looking at their bank
    most needs, so a page, a progress figure and the agent can never tell three
    different stories about the same row.

    Note this reads :func:`effective_sensitivity` and not the stored column
    alone. That matters for a row whose stored class is softer than its wording
    (a legacy or hand-edited row): the matcher would gate it, so claiming it
    auto-answers would be a promise the agent does not keep.
    """
    if item_is_expired(item, now=now):
        return False
    sensitivity = effective_sensitivity(item)
    if sensitivity == SENSITIVITY_SENSITIVE:
        return False
    if sensitivity == SENSITIVITY_FACTUAL:
        return True
    return bool(item.get("autoAnswerOptIn"))


def find_match(
    asked: str,
    items: Sequence[dict[str, Any]],
    *,
    company: str | None = None,
    job_family: str | None = None,
    now: datetime | None = None,
    ignore_sensitivity_gate: bool = False,
) -> AnswerBankMatch | None:
    """The one banked answer that may be used for ``asked``, or ``None``.

    ``None`` means "no honest answer" and the caller MUST turn it into a manual
    step. It is returned for every one of these, all pinned by tests:

    * nothing in the bank is confident enough (< :data:`AUTO_ANSWER_CONFIDENCE`);
    * the best item's staleness policy has expired it;
    * the item's scope does not cover this employer;
    * the question (or the item) is SENSITIVE — always, no opt-in, no override
      from bank contents;
    * the question is a JUDGEMENT call and the user has not opted that
      individual item in.

    ``ignore_sensitivity_gate`` exists for exactly one caller: the answers the
    user typed for THIS application in the card a moment ago (Pillar 4a). Those
    are the user answering their own form, not the agent reusing an old answer,
    so the class gate does not apply to them. It is never set for the standing
    bank.
    """
    moment = now or datetime.now(timezone.utc)
    best: AnswerBankMatch | None = None
    best_rank: tuple[float, int] = (0.0, -1)
    for item in items:
        if not str(item.get("answer") or "").strip():
            continue
        if not _scope_applies(item, company, job_family):
            continue
        if _is_expired(item, moment):
            continue
        confidence, method = match_confidence(asked, str(item.get("questionText") or ""))
        if confidence < AUTO_ANSWER_CONFIDENCE:
            continue
        if not ignore_sensitivity_gate:
            sensitivity = _effective_sensitivity(asked, item)
            if sensitivity == SENSITIVITY_SENSITIVE:
                continue
            if sensitivity == SENSITIVITY_JUDGMENT and not item.get("autoAnswerOptIn"):
                continue
        # A narrower scope beats a broader one at equal confidence: an answer
        # the user wrote FOR THIS COMPANY is more true here than their default.
        specificity = 1 if str(item.get("scope") or SCOPE_GLOBAL) != SCOPE_GLOBAL else 0
        rank = (confidence, specificity)
        if rank <= best_rank:
            continue
        best_rank = rank
        best = AnswerBankMatch(
            item_id=str(item.get("id") or ""),
            answer=str(item["answer"]),
            confidence=confidence,
            method=method,
            question_as_seen=asked,
            banked_question=str(item.get("questionText") or ""),
            sensitivity=_effective_sensitivity(asked, item),
            provenance=str(item.get("provenance") or PROVENANCE_USER_ANSWERED),
            per_application=bool(item.get("perApplication")),
        )
    return best


# ---------------------------------------------------------------------------
# Resolver — what the apply-executor actually calls
# ---------------------------------------------------------------------------


def per_application_items(screening_answers: Any) -> list[dict[str, Any]]:
    """The answers the user typed for ONE application, as matchable items.

    ``Application.answers.screeningAnswers`` is a ``{question: answer}`` map
    written by the in-card answer endpoint. These are not bank items: they have
    no id, they never expire, and they carry the ``perApplication`` marker so
    an audit can tell "the user just answered this" apart from "the agent
    reused a banked answer".
    """
    if not isinstance(screening_answers, dict):
        return []
    items: list[dict[str, Any]] = []
    for question, answer in screening_answers.items():
        text = str(question or "").strip()
        value = str(answer or "").strip()
        if not text or not value:
            continue
        items.append(
            {
                "id": "",
                "questionText": text,
                "answer": value,
                "scope": SCOPE_GLOBAL,
                "scopeValue": "",
                "provenance": PROVENANCE_USER_ANSWERED,
                "sensitivity": classify_sensitivity(text),
                "autoAnswerOptIn": False,
                "expiresAt": None,
                "perApplication": True,
            }
        )
    return items


def question_text_for_field(field: dict[str, Any]) -> str:
    """The words the EMPLOYER used for this form field.

    Label first, because that is what a human reads; the field name only when
    there is no label. Never a paraphrase, never a prettified version — the
    audit trail is worth nothing if the question it records is not the one the
    page asked.
    """
    label = str(field.get("label") or "").strip()
    return label or str(field.get("name") or "").strip()


def build_resolver(
    bank_items: Sequence[dict[str, Any]],
    *,
    screening_answers: Any = None,
    company: str | None = None,
    job_family: str | None = None,
    now: datetime | None = None,
) -> Callable[[dict[str, Any]], AnswerBankMatch | None]:
    """A ``field -> AnswerBankMatch | None`` callable for the apply-executor.

    Two layers, highest authority first:

    1. **This application's own answers** — what the user typed in the card for
       THIS employer (Pillar 4a). Matched by the same matcher, but the
       sensitivity gate does not apply: the user is answering their own form.
    2. **The standing bank** — fully gated.

    Returning ``None`` is the normal, honest outcome for a question nobody has
    answered yet, and the executor turns it into a manual step.
    """
    local = per_application_items(screening_answers)

    def resolve(field: dict[str, Any]) -> AnswerBankMatch | None:
        asked = question_text_for_field(field)
        if not asked:
            return None
        match = find_match(
            asked,
            local,
            company=company,
            job_family=job_family,
            now=now,
            ignore_sensitivity_gate=True,
        )
        if match is not None:
            return match
        return find_match(
            asked, bank_items, company=company, job_family=job_family, now=now
        )

    return resolve


# ---------------------------------------------------------------------------
# Seed questionnaire (ADR Pillar 1, "SEED (upfront)")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedQuestion:
    """One question in the onboarding questionnaire.

    It carries NO answer and no suggested answer — a questionnaire that
    pre-fills its own responses is a fabrication engine wearing a form. The
    user's words are the only thing that ever becomes an ``answer``.
    """

    concept: str
    question: str
    sensitivity: str
    helper: str
    placeholder: str


def _seed(concept_key: str, question: str, helper: str, placeholder: str) -> SeedQuestion:
    concept = next((c for c in CONCEPTS if c.key == concept_key), None)
    sensitivity = concept.sensitivity if concept else SENSITIVITY_FACTUAL
    return SeedQuestion(
        concept=concept_key,
        question=question,
        sensitivity=sensitivity,
        helper=helper,
        placeholder=placeholder,
    )


#: The ADR's "most common real screening questions across ATS platforms".
#: Wording is the plainest phrasing of each class, because the matcher works on
#: CONCEPTS — an employer asking the same thing in their own words still hits
#: the banked answer.
SEED_QUESTIONS: tuple[SeedQuestion, ...] = (
    _seed(
        "work_rights",
        "Are you legally entitled to work in the country you are applying in?",
        "Asked on nearly every application. Answer in your own words — Aether "
        "sends exactly what you type here, never a rewrite of it.",
        "e.g. Yes — I am an Australian citizen with full working rights.",
    ),
    _seed(
        "notice_period",
        "What is your notice period?",
        "Kept for 6 months, then Aether asks you to confirm it again rather "
        "than sending an answer that may have gone stale.",
        "e.g. 4 weeks from the date I accept.",
    ),
    _seed(
        "salary_expectation",
        "What are your salary expectations?",
        "A judgement call, so it stays user-gated: Aether will not send this "
        "automatically until you switch this answer on in the Answer Bank.",
        "e.g. AUD 180,000 base plus super, negotiable for the right role.",
    ),
    _seed(
        "relocation",
        "Are you willing to relocate for this role?",
        "Answer once and every future application that asks it is covered.",
        "e.g. Yes, for Sydney or Melbourne; not interstate otherwise.",
    ),
    _seed(
        "remote_preference",
        "What is your preferred working arrangement (remote, hybrid or onsite)?",
        "Covers the 'flexible working' and 'days in office' variants too.",
        "e.g. Hybrid — 2 days in office, Sydney CBD.",
    ),
    _seed(
        "start_date",
        "What is the earliest date you could start?",
        "Kept for 3 months, because a start date goes stale faster than any "
        "other answer here.",
        "e.g. Four weeks from an offer, or sooner by agreement.",
    ),
    _seed(
        "years_experience",
        "How many years of professional experience do you have in your field?",
        "Employers ask this per-skill too; answering the general version gives "
        "Aether a starting point, and it will still ask about a specific skill "
        "it has no answer for.",
        "e.g. 12 years, the last 6 in platform engineering.",
    ),
    _seed(
        "references",
        "Are you able to provide professional references on request?",
        "Aether never sends a referee's contact details it was not given.",
        "e.g. Yes — two former managers, contactable after a first interview.",
    ),
    _seed(
        "drivers_licence",
        "Do you hold a current driver's licence?",
        "Common for roles with any travel component.",
        "e.g. Yes — full NSW licence, no restrictions.",
    ),
    _seed(
        "notice_of_travel",
        "Are you willing to travel for this role?",
        "Answer once; Aether reuses it wherever the question appears.",
        "e.g. Yes, up to 20% domestic travel.",
    ),
    _seed(
        "referral_source",
        "How did you hear about the roles you apply for?",
        "Nearly every application form asks this. Aether sends what you write "
        "here word for word — it never substitutes the job board it happened "
        "to find a role on. If one application came from somewhere else, edit "
        "that application's answer before it is sent.",
        "e.g. LinkedIn Jobs — that is where I find most of the roles I apply for.",
    ),
    _seed(
        "acknowledgement",
        "Do you confirm that the information in your application is true, and "
        "agree to an employer's standard application terms and privacy policy?",
        "This covers plain tick-boxes only — \"I certify the information is "
        "true\", \"I have read the privacy policy\", \"I agree to the terms\". A "
        "box that gives CONSENT rather than an acknowledgement — a background "
        "check, a criminal or police check, a medical, a diversity disclosure "
        "— is never ticked from this answer: Aether stops and asks you, every "
        "time.",
        "e.g. Yes — everything I put in an application is true and complete.",
    ),
)


def seed_question_payload() -> list[dict[str, Any]]:
    """The questionnaire as the API returns it — including the honest note on
    which answers will and will not ever be sent automatically."""
    return [
        {
            "concept": question.concept,
            "question": question.question,
            "sensitivity": question.sensitivity,
            "helper": question.helper,
            "placeholder": question.placeholder,
            "staleDays": stale_days_for(question.question),
            "autoAnswerable": question.sensitivity == SENSITIVITY_FACTUAL,
        }
        for question in SEED_QUESTIONS
    ]


#: The seed concepts that actually unblock an unattended submission. A
#: judgement or sensitive class is user-gated BY DESIGN, so counting it as
#: outstanding set-up would draw a progress bar that can never reach the end.
ESSENTIAL_SEED_CONCEPTS: tuple[str, ...] = tuple(
    question.concept
    for question in SEED_QUESTIONS
    if question.sensitivity == SENSITIVITY_FACTUAL
)


def readiness_summary(
    items: Sequence[dict[str, Any]], *, now: datetime | None = None
) -> dict[str, Any]:
    """How much of the screening set the bank can answer — measured, not estimated.

    Every figure here is either a count of rows that exist or coverage over the
    fixed seed set. Nothing is projected or smoothed, and there is deliberately
    no single blended "autonomy score": a percentage mixing occurrence counts
    (how many times an answer was reused) with question counts (how many
    distinct questions are known) is a number with no unit — a fabricated
    metric in the honesty floor's sense even though every input to it is real.

    A user who has answered nothing gets zeros and an empty covered set. That
    is the honest state, and the UI renders it as "not set up yet" rather than
    as a flattering fraction of something.
    """
    moment = now or datetime.now(timezone.utc)
    live = [item for item in items if not item_is_expired(item, now=moment)]
    covered = {
        concept
        for concept in (concept_of(str(item.get("semanticKey") or "")) for item in live)
        if concept
    }

    essential_covered = [key for key in ESSENTIAL_SEED_CONCEPTS if key in covered]
    return {
        "seedTotal": len(SEED_QUESTIONS),
        "seedCovered": len([q for q in SEED_QUESTIONS if q.concept in covered]),
        "seedRemaining": [
            {
                "concept": question.concept,
                "question": question.question,
                "sensitivity": question.sensitivity,
            }
            for question in SEED_QUESTIONS
            if question.concept not in covered
        ],
        # The subset that decides whether an application can go out unattended.
        "essentialTotal": len(ESSENTIAL_SEED_CONCEPTS),
        "essentialCovered": len(essential_covered),
        "setupComplete": len(essential_covered) == len(ESSENTIAL_SEED_CONCEPTS),
        "liveAnswers": len(live),
        # An expired row is still the user's answer — it needs re-confirming,
        # not deleting, so it is reported rather than quietly dropped.
        "expiredAnswers": len(items) - len(live),
        "autoAnswerable": len([i for i in live if item_auto_answers(i, now=moment)]),
        "gatedAnswers": len([i for i in live if not item_auto_answers(i, now=moment)]),
        # Recorded occurrences: every time the agent answered from the bank
        # instead of stopping to ask. Read from the item counters that the usage
        # audit advances in the same transaction as each recorded use.
        "timesAnswered": sum(int(item.get("timesUsed") or 0) for item in items),
        # The learning loop, as a count of its actual output: answers that
        # entered the bank because a real application asked something new.
        "learnedFromApplications": len(
            [
                item
                for item in items
                if str(item.get("provenance") or "") == PROVENANCE_USER_ANSWERED
                and str(item.get("provenanceDetail") or "").strip()
            ]
        ),
    }


def describe_gate(asked: str, item: dict[str, Any] | None = None) -> str:
    """Plain-English reason a question is user-gated, for the UI to render."""
    sensitivity = (
        _effective_sensitivity(asked, item) if item else classify_sensitivity(asked)
    )
    if sensitivity == SENSITIVITY_SENSITIVE:
        return (
            "This is a sensitive or legal question. Aether never answers it for "
            "you from a saved answer — you decide it on every application."
        )
    if sensitivity == SENSITIVITY_JUDGMENT:
        return (
            "This is a judgement call, so it stays user-gated until you switch "
            "this saved answer on in your Answer Bank."
        )
    return "Answer it once and Aether can answer it for you next time."


def coerce_scope(scope: Any) -> str:
    """A caller-supplied scope, or ``global``. Never raises on junk input."""
    value = str(scope or "").strip() or SCOPE_GLOBAL
    return value if value in SCOPES else SCOPE_GLOBAL


def coerce_provenance(provenance: Any) -> str:
    value = str(provenance or "").strip() or PROVENANCE_USER_ANSWERED
    return value if value in PROVENANCES else PROVENANCE_USER_ANSWERED


def iter_unanswered(
    fields: Iterable[dict[str, Any]], resolve: Callable[[dict[str, Any]], Any]
) -> list[dict[str, Any]]:
    """Required fields the bank still cannot answer — the manual-step set."""
    return [
        field
        for field in fields
        if field.get("required") and resolve(field) is None
    ]
