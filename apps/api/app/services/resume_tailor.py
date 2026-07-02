"""Resume bullet tailoring (P1-S04 — stub).

`tailor_bullets` is the seam where an LLM will later rewrite a resume's bullet
points to emphasise the skills a specific job description asks for, while
preserving the resume's exact format (keyed off the format hash from
`resume_parser.compute_format_hash`).

For this foundation slice it is a **lossless passthrough**: it returns the input
bullets unchanged. This keeps the contract and call sites in place without
fabricating tailored content before the LLM integration lands (Phase 2). The
signature is stable so wiring the model in later is a drop-in change.
"""
from __future__ import annotations

from typing import Optional


def tailor_bullets(
    bullets: list[str],
    job_description: str,
    *,
    model: Optional[str] = None,
) -> list[str]:
    """Return bullets tailored to ``job_description``.

    Stub behaviour: returns ``bullets`` unchanged (a lossless copy). ``model``
    will select the OpenRouter model once tailoring is implemented.
    """
    # Return a shallow copy so callers cannot mutate the input list by identity.
    return list(bullets)
