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
from app.services.resume_completeness import (
    _PRESENT_COVERAGE,
    baseline_bullets,
    baseline_record,
)
from app.services.resume_document import parse_resume_document, rebuild_raw_text


def _present(item: str, haystack: str) -> bool:
    normalized = _normalize(item)
    if not normalized:
        return True
    return normalized in haystack or _coverage(item, haystack) >= _PRESENT_COVERAGE


def _bullet_headings(document: Any) -> dict[str, str]:
    """``{normalized bullet text: the heading it is filed under}``."""
    return {
        _normalize(text): section.heading
        for section in document.sections
        for text in section.bullets
        if _normalize(text)
    }


def raw_text_losses(
    resume: dict[str, Any], parent: dict[str, Any]
) -> tuple[str, ...]:
    """What the version's own ``raw_text`` no longer states, NAMED.

    Measured the only way that can see the damage: the PARENT's document with
    this version's rewrites mapped in — every heading, bullet, line and contact
    detail the résumé is supposed to hold — against the version's own parse.
    Asking the damaged record what it contains and comparing it with itself is
    what let the loss ship in the first place.

    A bullet filed under the WRONG heading counts as lost even though its words
    are still on the page. The pre-fix corruption did not delete the bullets it
    re-appended, it moved them: on the live artifact
    (``c12187d107bf994471844e09a``) all 25 bullets — every job's work — ended up
    in one trailing ``CERTIFICATIONS`` block with ``WORK EXPERIENCE`` left
    holding none, and a presence-only census called that record intact, so the
    repair tool declined to repair the very artifact it was written for
    (``uat/reports/evidence/agents-uplift/u2b/critical/round4-live-artifact-state-OUTPUT-20260814.json``).
    A résumé that says the person did that work at another employer is not a
    formatting difference; it is the document making a false claim, which is
    the failure this module exists to undo.
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
    filed = _bullet_headings(actual)
    for text, heading in _bullet_headings(expected).items():
        where = filed.get(text)
        if where is None or where == heading:
            continue
        if not heading:
            # The ground truth itself files this bullet under NO heading — it is
            # one the parent persists but never states in its own ``raw_text``
            # (the positional PDF read; on the live artifact, 10 of 25), so the
            # document model appends it headingless rather than invent a section
            # for it. There is no original heading it can have been moved away
            # from, and writing a headingless bullet back out necessarily lands
            # it under whichever section precedes it — so reporting that as a
            # mis-filing would be both false and, being unfixable by the very
            # rebuild that repairs the row, a permanent FAILED census.
            continue
        lost.append(
            f"bullet “{text}” filed under “{where or '(no heading)'}”,"
            f" not “{heading or '(no heading)'}”"
        )
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
    # The SAME inventory the census measured against (round 5): the parent's own
    # bullets with this version's approved rewrites mapped in. Rebuilding from
    # the child's persisted list alone would regenerate a document that still
    # lacks every bullet the tailoring run never carried — the census would
    # re-flag the row it had just "repaired" and the operator script would exit
    # non-zero on a write it had made itself.
    payload["raw_text"] = rebuild_raw_text(
        parent_text, baseline_bullets(resume, parent)
    )
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
