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


def find_unsupported_entities(generated: str, evidence_corpus: str) -> list[str]:
    """Return entities/metrics in ``generated`` that lack evidence support."""
    evidence = _tokens(evidence_corpus)
    flagged: list[str] = []
    for raw in _TOKEN_RE.findall(generated):
        lower = _norm(raw)
        if not lower:
            continue
        if lower in _EXEMPT or lower in evidence:
            continue
        is_capitalized = raw[0].isupper()
        has_number = bool(_NUMBER_RE.search(raw))
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
