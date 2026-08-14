"""Recover tailored résumé versions whose stored ``raw_text`` lost content.

Until the U2b round-3 fix, a tailored version's ``raw_text`` was regenerated as
``strip_bullet_lines(parent) + every persisted bullet`` — a bullet-free skeleton
with the tailoring loop's own bullets appended as one flat trailing block. On
the live artifact (résumé ``c12187d107bf994471844e09a``) that deleted two skills
bullets and an entire academic degree outright, emptied both ``SKILLS`` sections
and ``CERTIFICATIONS`` to bare headings, and re-parented the surviving skills
bullets under ``WORK EXPERIENCE``. Every version persisted before the fix still
carries that damaged text, and the download a subscriber would send an employer
is drawn from it.

The parent record is intact — it is the user's own upload and the tailoring
pipeline never rewrites it — so the loss is recoverable exactly: re-run the
FIXED rebuild over the parent's text and this version's persisted bullets, which
is by construction the same text the pipeline would persist today.

Repair is ADDITIVE and reversible. The damaged value is kept verbatim under
``sections["rawTextRepair"]["previousRawText"]`` together with what was found
missing and when, so a repair can be audited or undone; nothing is overwritten
silently and no row is deleted. A version that has lost nothing is left
completely alone (:func:`repair_sections` returns ``None``) — a no-op rewrite
would churn history for no reason and make a real repair harder to find.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.format_verification import _coverage, _normalize
from app.services.resume_completeness import _PRESENT_COVERAGE, baseline_record
from app.services.resume_document import parse_resume_document, rebuild_raw_text


def _present(item: str, haystack: str) -> bool:
    normalized = _normalize(item)
    if not normalized:
        return True
    return normalized in haystack or _coverage(item, haystack) >= _PRESENT_COVERAGE


def raw_text_losses(
    resume: dict[str, Any], parent: dict[str, Any]
) -> tuple[str, ...]:
    """What the version's own ``raw_text`` no longer states, NAMED.

    Measured the only way that can see the damage: the PARENT's document with
    this version's rewrites mapped in — every heading, bullet, line and contact
    detail the résumé is supposed to hold — against the version's own parse.
    Asking the damaged record what it contains and comparing it with itself is
    what let the loss ship in the first place.
    """
    expected = parse_resume_document(baseline_record(resume, parent))
    actual = parse_resume_document(resume)
    haystack = _normalize(
        " ".join(
            (actual.name, actual.title)
            + actual.headings
            + actual.bullets
            + actual.lines
            + actual.contact
        )
    )
    lost: list[str] = []
    for heading in expected.headings:
        if not _present(heading, haystack):
            lost.append(f"section “{heading}”")
    for text in expected.bullets:
        if not _present(text, haystack):
            lost.append(f"bullet “{text}”")
    for text in expected.lines:
        if not _present(text, haystack):
            lost.append(f"line “{text}”")
    for text in expected.contact:
        if not _present(text, haystack):
            lost.append(f"contact detail “{text}”")
    return tuple(lost)


def repair_sections(
    resume: dict[str, Any],
    parent: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """A repaired ``sections`` payload for a damaged version, else ``None``.

    The regenerated text comes from the parent's own document and this
    version's persisted bullets through :func:`rebuild_raw_text` — the same
    call the tailoring pipeline now makes — so a repaired version is
    indistinguishable from one tailored today. The persisted bullets are NOT
    touched: they are the approved rewrites, and they are already correct.
    """
    lost = raw_text_losses(resume, parent)
    if not lost:
        return None
    payload = dict(resume.get("sections") or {})
    previous = str(payload.get("raw_text", "") or "")
    parent_text = str((parent.get("sections") or {}).get("raw_text", "") or "")
    persisted = [
        str(bullet.get("text", "")).strip()
        for bullet in (payload.get("bullets") or [])
        if isinstance(bullet, dict) and str(bullet.get("text", "")).strip()
    ]
    payload["raw_text"] = rebuild_raw_text(parent_text, persisted)
    payload["rawTextRepair"] = {
        "repairedAt": (now or datetime.now(timezone.utc)).isoformat(),
        "reason": (
            "raw_text regenerated from the parent baseline: the pre-fix tailoring"
            " pipeline stripped every bullet from the document and re-appended"
            " only the tracked rewrites (U2b round-3)"
        ),
        "parentId": parent.get("id"),
        "lost": list(lost),
        "previousRawText": previous,
    }
    return payload
