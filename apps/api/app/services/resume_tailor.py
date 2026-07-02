"""LLM-powered resume bullet tailoring with anti-fabrication guards (P2-S05).

The service rewords existing resume bullets to emphasise keywords from a job
description. Hard guarantees:

- **No invention**: any bullet containing a token absent from the original
  resume text is rejected (the original bullet is kept instead).
- **Evidence trace**: every bullet returned carries an ``evidenceRef``
  pointing at the original bullet it derives from.
- **Format preservation**: the source PDF is never touched — tailoring works
  on extracted text only, keyed by the resume's format hash.

The LLM call goes through :mod:`app.services.llm_client` (record-replay), so
tests and CI never hit the network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.llm_client import LLMClient, get_model

SYSTEM_PROMPT = (
    "You are a precision resume editor. Only reword existing bullets to match "
    "keywords. Never add skills, titles, employers not in original. Each "
    "rewritten bullet must trace to an evidenceRef. Respond with JSON: "
    '{"bullets": [{"text": "...", "evidenceRef": "bullet-N"}], '
    '"evidenceRefs": ["bullet-N", ...]}'
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_BULLET_MARKERS = ("•", "●", "▪", "- ")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def extract_bullets(raw_text: str) -> list[str]:
    """Pull bullet-point lines out of extracted resume text."""
    bullets: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(_BULLET_MARKERS):
            bullets.append(stripped.lstrip("•●▪- ").strip())
    return bullets


@dataclass
class TailorResult:
    """Validated output of a tailoring run."""

    bullets: list[dict[str, str]] = field(default_factory=list)
    #: Number of bullets whose text actually changed vs the original.
    changes: int = 0
    #: Bullets the guard rejected (invented tokens / missing evidenceRef).
    rejected: list[str] = field(default_factory=list)


class ResumeTailorService:
    """Rewrites bullets via the LLM, then validates against the source resume."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm or LLMClient()

    def tailor(self, resume_text: str, job_description: str) -> TailorResult:
        bullets = extract_bullets(resume_text)
        original_tokens = _tokens(resume_text)
        user_prompt = (
            "Job description:\n" + job_description + "\n\nOriginal bullets:\n"
            + "\n".join(f"bullet-{i}: {b}" for i, b in enumerate(bullets))
        )
        raw = self._llm.complete_json(
            "tailor",
            SYSTEM_PROMPT,
            user_prompt,
            model=get_model("REASONING"),
            temperature=0.0,
        )
        return self._validate(raw, bullets, original_tokens)

    def _validate(
        self, raw: Any, originals: list[str], original_tokens: set[str]
    ) -> TailorResult:
        result = TailorResult()
        by_ref = {f"bullet-{i}": b for i, b in enumerate(originals)}
        for item in raw.get("bullets", []):
            text = (item.get("text") or "").strip()
            ref = item.get("evidenceRef")
            if not text or not ref or ref not in by_ref:
                result.rejected.append(text or "<empty>")
                continue
            if not _tokens(text) <= original_tokens:
                # Fabrication guard: invented token → keep the original bullet.
                result.rejected.append(text)
                text = by_ref[ref]
            result.bullets.append({"text": text, "evidenceRef": ref})
            if text != by_ref[ref]:
                result.changes += 1
        return result


def tailor_bullets(
    bullets: list[str],
    job_description: str,
    *,
    model: Optional[str] = None,  # noqa: ARG001 — kept for P1 signature stability
) -> list[str]:
    """Legacy P1 seam — lossless passthrough retained for existing callers."""
    return list(bullets)
