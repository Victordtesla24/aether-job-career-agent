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
    flagged: list[str] = []
    for match in _TOKEN_RE.finditer(generated):
        raw = match.group()
        lower = _norm(raw)
        if not lower:
            continue
        if lower in _EXEMPT or lower in evidence:
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
            if raw not in flagged:
                flagged.append(raw)
    return flagged


class FabricationGuard:
    """Object wrapper so agents can dependency-inject / mock the guard."""

    def check(self, generated: str, evidence_corpus: str) -> list[str]:
        return find_unsupported_entities(generated, evidence_corpus)

    def is_clean(self, generated: str, evidence_corpus: str) -> bool:
        return not self.check(generated, evidence_corpus)
