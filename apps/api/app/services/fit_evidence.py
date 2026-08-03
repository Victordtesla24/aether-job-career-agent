"""The evidence gate for fit scoring — one definition, shared by every path.

A posting with almost no text scores spuriously HIGH: the ATS engine measures
keyword overlap plus semantic similarity, so with nearly nothing to mismatch,
emptiness reads as a near-perfect fit. Production measurement that produced
:data:`MIN_SCORABLE_CHARS` (2026-08-02): rows carrying <200 chars of
description averaged 58.9 (max 78.6) while rows with a real description
averaged 40.8 (max 56.5) — and a posting with an EMPTY description scored
74.63, the top of the board.

These primitives live in this LEAF module (no repository, no ATS engine, no
model loading) so that:

* :mod:`app.agents.fit_scorer` — the write path — and
* :mod:`app.services.fit_score_remediation` — the retire-the-old-scores path,
  which runs at application startup

use the byte-for-byte SAME rule without importing each other and without
dragging the embedding model into the startup import graph. Two hand-rolled
copies of "is this scorable?" would inevitably drift, and the drift would show
up as junk back at the top of a user's board.
"""
from __future__ import annotations

import json
from typing import Any

#: Minimum characters of real posting text before a fit score means anything.
#: MEASURED, not guessed — see the module docstring.
MIN_SCORABLE_CHARS = 200


def has_scorable_evidence(job_text: str | None) -> bool:
    """True when a posting carries enough real text for a score to mean anything."""
    return len((job_text or "").strip()) >= MIN_SCORABLE_CHARS


def job_evidence_text(job: dict[str, Any]) -> str:
    """The exact text the ATS engine would be given for ``job``.

    The gate is applied to THIS string — not to the description alone — so a
    posting is judged on everything the scorer would actually see.
    """
    requirements = job.get("requirements")
    if isinstance(requirements, str):
        try:
            requirements = json.loads(requirements)
        except ValueError:
            requirements = [requirements]
    if isinstance(requirements, list):
        req_text = " ".join(str(item) for item in requirements)
    elif requirements is None:
        req_text = ""
    else:  # a JSON object/scalar — not the shape we write, but never crash on it
        req_text = str(requirements)
    return f"{job.get('title') or ''} {job.get('description') or ''} {req_text}".strip()
