"""Fabrication guard — flags entities not backed by the evidence corpus (P2-S06).

Lightweight by design (no spaCy in CI): candidate "entities" are capitalized
tokens and number-bearing tokens (metrics). Any candidate whose lowercase form
is absent from the evidence corpus token set is flagged as a potential
fabrication. Common sentence-starters/pronouns are exempt.
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./%-]*")
_NUMBER_RE = re.compile(r"\d")

#: Words that are legitimately capitalized without being entities.
_EXEMPT = frozenset(
    """
    i i'm i've a an and the my your our their this that these those as at in
    on of to for with dear hiring team regards sincerely thank you it he she
    we they having during while additionally furthermore finally moreover
    please best january february march april may june july august september
    october november december monday tuesday wednesday thursday friday
    saturday sunday
    """.split()
)


#: Trailing punctuation stripped before comparison so tokenization is
#: symmetric between generated text and evidence (e.g. "Amp." vs "Amp").
_TRAILING = ".-/#+%"


def _norm(token: str) -> str:
    return token.rstrip(_TRAILING).lower()


def _tokens(text: str) -> set[str]:
    return {_norm(t) for t in _TOKEN_RE.findall(text)}


# ---------------------------------------------------------------------------
# ML-W15: NUMBER-BEARING COMPOUND normalization.
#
# Live production runs rejected faithful restatements of a résumé's own
# numbers purely because of formatting: "200ms." / "200-ms" vs. the résumé's
# "200 ms"; "6-person" / "6-engineer" vs. the résumé's "Led 6 engineers".
# Both sides are normalized deterministically before comparison so these
# formatting variants are recognized as the SAME claim — while a letter that
# actually CHANGES the number (6 -> 8, 200ms -> 50ms) still gets flagged, so
# the fix adds precision, not permissiveness.
# ---------------------------------------------------------------------------

#: Unit abbreviations recognized for NUMBER+UNIT normalization (glued,
#: hyphenated, or space-separated all mean the same claim — "200ms",
#: "200-ms", "200 ms"). Deliberately narrow: only common time/data/rate
#: abbreviations that plausibly appear as a suffix directly on a number. This
#: is NOT a unit-conversion table — the unit text itself must still match
#: verbatim ("200ms" is not verified by evidence stating "200 seconds").
_UNITS = frozenset(
    """
    ms s sec secs min mins hr hrs hz khz mhz ghz
    kb mb gb tb pb kbps mbps gbps
    px pt em rem pct x
    """.split()
)

#: Timezone abbreviations are scheduling/logistics context ("Thursday
#: afternoon AEST"), not an experience claim about the candidate. They are
#: exempt ONLY when the surrounding sentence is itself scheduling context
#: (see ``_is_scheduling_context``) — wave-3.5 adversarial review (NTH-R11)
#: found a context-free exemption let a real employer name slip through
#: ("EST Holdings", "at CET"). Kept narrow and explicit; do not widen
#: without a new documented finding.
_TIMEZONE_ALLOWLIST = frozenset(
    {
        "aest", "aedt", "acst", "acdt", "awst",
        "utc", "gmt", "bst", "cet", "cest",
        "est", "edt", "cst", "cdt", "mst", "mdt", "pst", "pdt",
    }
)

#: Day/time vocabulary that marks a sentence as scheduling/logistics context
#: ("I'm available Thursday afternoon AEST"). Deliberately narrow — a
#: weekday name, a time-of-day word, or an explicit clock time — NOT generic
#: words like "available"/"call" that could co-occur with an unrelated claim.
_WEEKDAYS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)
_TIME_OF_DAY_WORDS = frozenset({"morning", "afternoon", "evening", "tonight", "noon", "midnight"})
_CLOCK_TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", re.IGNORECASE)


def _sentence_containing(text: str, pos: int) -> str:
    """The sentence (bounded by ``_SENTENCE_ENDERS``) that contains ``pos``."""
    start = pos
    while start > 0 and text[start - 1] not in _SENTENCE_ENDERS:
        start -= 1
    end = pos
    while end < len(text) and text[end] not in _SENTENCE_ENDERS:
        end += 1
    return text[start:end]


def _is_scheduling_context(sentence: str) -> bool:
    """True when ``sentence`` names a weekday, a time-of-day word, or an
    explicit clock time — the only contexts a timezone abbreviation is
    logistics rather than a claim."""
    if _CLOCK_TIME_RE.search(sentence):
        return True
    words = {_norm(t) for t in _TOKEN_RE.findall(sentence)}
    return bool(words & (_WEEKDAYS | _TIME_OF_DAY_WORDS))


#: Generic team/size descriptor nouns that pair with a resume-evidenced
#: NUMBER without needing their OWN independent evidence match — "6-person
#: team" is a faithful paraphrase of "led 6 engineers": the NUMBER is the
#: claim, "person" is a generic size descriptor, not a new fact. A specific
#: role/skill/achievement noun (e.g. "6-patent", "6-certification") is NOT in
#: this list, so it still requires its own evidence via the stem check below.
_SIZE_NOUNS = frozenset(
    {"person", "people", "member", "members", "team", "teams", "staff", "employee", "employees"}
)

#: Words that follow a number in the evidence WITHOUT that number denoting a
#: headcount/quantity-of-things claim ("40 percent", "3 years", "5 hours") —
#: excluded from the generic _SIZE_NOUNS pairing so a number used elsewhere
#: in the resume for a date/percentage/duration cannot be repurposed as an
#: unrelated team size (wave-3.5 adversarial review MF-3: "40-person" was
#: accepted against a résumé whose only "40" was "improving throughput 40
#: percent" — truth was "6 engineers").
_NON_HEADCOUNT_WORDS = _UNITS | frozenset(
    """
    percent pct percentage dollar dollars cent cents
    time times year years month months week weeks day days
    hour hours minute minutes second seconds
    """.split()
)

#: A NUMBER immediately followed by a WORD, joined by a hyphen or glued
#: directly together — "200ms", "200-ms", "6-person", "6-engineer".
_NUMBER_WORD_RE = re.compile(r"^(\d+(?:\.\d+)?)-?([a-z]+)$")

#: Same NUMBER+WORD shape scanned across the raw evidence text (not just its
#: token set), so a resume stating "200 ms" / "6 engineers" (number and word
#: as two SEPARATE tokens, space-separated) is still recognized as the same
#: pairing as a glued/hyphenated candidate token — and, critically, so the
#: number and word must have actually occurred TOGETHER in the evidence, not
#: merely both exist somewhere in it (wave-3.5 review MF-3).
_EVIDENCE_NUMBER_WORD_RE = re.compile(r"(\d+(?:\.\d+)?)[ \t]*-?[ \t]*([A-Za-z]+)")


def _stem(word: str) -> str:
    """Minimal, ORTHOGRAPHICALLY-GUARDED singular/plural fold — only needs to
    be consistent between the two sides of the comparison, not a real
    lemmatizer. wave-3.5 review NTH-R12: the previous unconditional
    strip-trailing-s collapsed unrelated words ("cares" -> "car", "bus" ->
    "bu") and was asymmetric (stem("process") != stem("processes")). This
    version only treats a trailing "s" as a plural marker when the word does
    NOT already end in a bare sibilant ("ss", "us", "is" — process, bus,
    axis), and only strips "-es" when the word is a genuine sibilant plural
    (boxes, watches, buses) — so both directions of a real plural now fold
    to the same stem, and singular words ending in "s" are left alone."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _evidence_number_word_index(
    evidence_corpus: str,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Scan the evidence text for every NUMBER+WORD adjacency, however it was
    formatted (glued, hyphenated, or space-separated). Returns two pair sets:

    * ``measurements`` — (number, unit) pairs, exact unit text (lowercased,
      unstemmed — units are abbreviations, not plurals).
    * ``pairs`` — (number, stem(word)) pairs for EVERY adjacency, used to
      require that a claimed NUMBER+NOUN compound actually co-occurred in
      the evidence, not merely that each half exists somewhere in it.
    """
    measurements: set[tuple[str, str]] = set()
    pairs: set[tuple[str, str]] = set()
    for m in _EVIDENCE_NUMBER_WORD_RE.finditer(evidence_corpus):
        number, word = m.group(1), m.group(2).lower()
        pairs.add((number, _stem(word)))
        if word in _UNITS:
            measurements.add((number, word))
    return measurements, pairs


def _verified_number_word_compound(
    token: str,
    measurements: set[tuple[str, str]],
    pairs: set[tuple[str, str]],
) -> bool:
    """True when a NUMBER+WORD compound token is a verified restatement of
    the evidence corpus, per the ML-W15 normalization rules above. Every
    branch requires the NUMBER and the WORD to have occurred TOGETHER in the
    evidence (wave-3.5 review MF-3) — never independent membership tests."""
    m = _NUMBER_WORD_RE.match(token)
    if not m:
        return False
    number, word = m.group(1), m.group(2)
    if word in _UNITS:
        # Measurement compound: number AND unit must match verbatim as a
        # pair, however the evidence formatted them.
        return (number, word) in measurements
    if word in _SIZE_NOUNS:
        # Generic team-size descriptor: the number must be paired, in
        # evidence, with SOME headcount-shaped noun (i.e. the number is
        # actually counting people/things there, not a date/percentage/
        # duration that happens to share the digits).
        return any(
            pair_number == number and pair_word not in _NON_HEADCOUNT_WORDS
            for pair_number, pair_word in pairs
        )
    # Specific role/skill noun: the number must be paired, in evidence, with
    # THIS noun (stem-matched) specifically — "6-engineer" verified only by
    # an evidenced "6 engineers", never by an unrelated evidenced "6".
    return (number, _stem(word)) in pairs


#: Characters that terminate a sentence — a title-case word right after one of
#: these is ordinary sentence case, not an entity name.
_SENTENCE_ENDERS = ".!?:;\n\r\"'"


def _is_sentence_start(text: str, start: int) -> bool:
    """True when the token at ``start`` begins the text or follows a sentence end."""
    i = start - 1
    while i >= 0 and text[i] in " \t":
        i -= 1
    return i < 0 or text[i] in _SENTENCE_ENDERS


def find_unsupported_entities(generated: str, evidence_corpus: str) -> list[str]:
    """Return entities/metrics in ``generated`` that lack evidence support."""
    evidence = _tokens(evidence_corpus)
    measurements, pairs = _evidence_number_word_index(evidence_corpus)
    flagged: list[str] = []
    for match in _TOKEN_RE.finditer(generated):
        raw = match.group()
        lower = _norm(raw)
        if not lower:
            continue
        if lower in _EXEMPT or lower in evidence:
            continue
        if lower in _TIMEZONE_ALLOWLIST and _is_scheduling_context(
            _sentence_containing(generated, match.start())
        ):
            continue
        has_number = bool(_NUMBER_RE.search(raw))
        is_capitalized = raw[0].isupper()
        # Sentence-initial Title-case words ("Throughout my career…") are
        # ordinary sentence case, not entities. All-caps acronyms (GCP, AWS)
        # and number-bearing tokens are still flagged wherever they appear.
        is_title_case = is_capitalized and raw[1:].islower() if len(raw) > 1 else False
        if is_title_case and _is_sentence_start(generated, match.start()):
            is_capitalized = False
        if is_capitalized or has_number:
            # ML-W15: a NUMBER+WORD compound ("6-person", "200ms") that is a
            # verified formatting variant / faithful paraphrase of the
            # evidence is not a fabrication — everything else still is,
            # including an inflated/deflated number, or an evidenced number
            # paired with an unrelated evidenced noun, in the same shape.
            if has_number and _verified_number_word_compound(lower, measurements, pairs):
                continue
            if raw not in flagged:
                flagged.append(raw)
    return flagged


class FabricationGuard:
    """Object wrapper so agents can dependency-inject / mock the guard."""

    def check(self, generated: str, evidence_corpus: str) -> list[str]:
        return find_unsupported_entities(generated, evidence_corpus)
