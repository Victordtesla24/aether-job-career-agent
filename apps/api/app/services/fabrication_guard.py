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
#: afternoon AEST"), not an experience claim about the candidate — so they
#: are exempt from evidence matching entirely. Kept narrow and explicit; do
#: not widen without a new documented finding.
_TIMEZONE_ALLOWLIST = frozenset(
    {
        "aest", "aedt", "acst", "acdt", "awst",
        "utc", "gmt", "bst", "cet", "cest",
        "est", "edt", "cst", "cdt", "mst", "mdt", "pst", "pdt",
    }
)

#: Generic team/size descriptor nouns that pair with a resume-evidenced
#: NUMBER without needing their own independent evidence match — "6-person
#: team" is a faithful paraphrase of "led 6 engineers": the NUMBER is the
#: claim, "person" is a generic size descriptor, not a new fact. A specific
#: role/skill/achievement noun (e.g. "6-patent", "6-certification") is NOT in
#: this list, so it still requires its own evidence via the stem check below.
_SIZE_NOUNS = frozenset(
    {"person", "people", "member", "members", "team", "teams", "staff", "employee", "employees"}
)

#: A NUMBER immediately followed by a WORD, joined by a hyphen or glued
#: directly together — "200ms", "200-ms", "6-person", "6-engineer".
_NUMBER_WORD_RE = re.compile(r"^(\d+(?:\.\d+)?)-?([a-z]+)$")

#: Same NUMBER+WORD shape scanned across the raw evidence text (not just its
#: token set), so a resume stating "200 ms" (number and unit as two SEPARATE
#: tokens, space-separated) is still recognized as the same measurement as a
#: glued/hyphenated candidate token.
_EVIDENCE_MEASURE_RE = re.compile(r"(\d+(?:\.\d+)?)[ \t]*-?[ \t]*([A-Za-z]+)")


def _stem(word: str) -> str:
    """Cheap plural-suffix stripper — only needs to be consistent between the
    two sides of the comparison, not linguistically perfect."""
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("es") and len(word) > 2:
        return word[:-2]
    if word.endswith("s") and len(word) > 1:
        return word[:-1]
    return word


def _evidence_measurements(evidence_corpus: str) -> set[tuple[str, str]]:
    """Canonical (number, unit) pairs found in the evidence text, however
    they were formatted there (glued, hyphenated, or space-separated)."""
    out: set[tuple[str, str]] = set()
    for m in _EVIDENCE_MEASURE_RE.finditer(evidence_corpus):
        number, unit = m.group(1), m.group(2).lower()
        if unit in _UNITS:
            out.add((number, unit))
    return out


def _verified_number_word_compound(
    token: str,
    evidence: set[str],
    evidence_stems: set[str],
    measurements: set[tuple[str, str]],
) -> bool:
    """True when a NUMBER+WORD compound token is a verified restatement of
    the evidence corpus, per the ML-W15 normalization rules above."""
    m = _NUMBER_WORD_RE.match(token)
    if not m:
        return False
    number, word = m.group(1), m.group(2)
    if word in _UNITS:
        # Measurement compound: number AND unit must match verbatim as a
        # pair, however the evidence formatted them.
        return (number, word) in measurements
    # Team-size / role-noun compound: the NUMBER must be resume-evidenced,
    # and the WORD must either be a generic size descriptor or stem-match an
    # evidenced word (e.g. "engineer" ~ "engineers").
    if number not in evidence:
        return False
    return word in evidence or _stem(word) in evidence_stems or word in _SIZE_NOUNS


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
    evidence_stems = {_stem(t) for t in evidence}
    measurements = _evidence_measurements(evidence_corpus)
    flagged: list[str] = []
    for match in _TOKEN_RE.finditer(generated):
        raw = match.group()
        lower = _norm(raw)
        if not lower:
            continue
        if lower in _EXEMPT or lower in evidence or lower in _TIMEZONE_ALLOWLIST:
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
            # including an inflated/deflated number in the same shape.
            if has_number and _verified_number_word_compound(
                lower, evidence, evidence_stems, measurements
            ):
                continue
            if raw not in flagged:
                flagged.append(raw)
    return flagged


class FabricationGuard:
    """Object wrapper so agents can dependency-inject / mock the guard."""

    def check(self, generated: str, evidence_corpus: str) -> list[str]:
        return find_unsupported_entities(generated, evidence_corpus)
