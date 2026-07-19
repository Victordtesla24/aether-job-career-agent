"""Per-user résumé grounding — the caller's OWN résumé, never a fixed one.

Every user-facing agent path that grounds a generated artifact or an analytic
on "the candidate résumé" MUST use these helpers so no account is ever grounded
on another user's — or the operator's — résumé (NF-final-B-001/002,
MV-story-bank-006). The bundled base PDF is a LAST-RESORT fallback used only
when the user has no résumé on file.
"""
from __future__ import annotations

from typing import Any


def resolve_user_resume_text(user_id: str) -> str:
    """The caller's OWN base résumé text.

    Reads the user's base (root) résumé (``sections.raw_text``, falling back to
    its bullets). Only when the user has NO résumé on file does it fall back to
    the bundled base PDF — preserving prior behaviour for brand-new accounts
    while guaranteeing an existing user is grounded on THEIR résumé, never a
    fixed operator-configured one.
    """
    from app.agents.fit_scorer import get_base_resume_path
    from app.repositories.resume import ResumeRepository
    from app.services.resume_parser import parse_resume_pdf

    base = ResumeRepository().get_base(user_id)
    if base:
        sections = base.get("sections") or {}
        text = sections.get("raw_text") or "\n".join(
            str(b.get("text", ""))
            for b in sections.get("bullets", [])
            if b.get("text")
        )
        if text and text.strip():
            return text
    return parse_resume_pdf(get_base_resume_path())["raw_text"]


def resolve_user_resume_contact(user_id: str) -> dict[str, Any]:
    """The caller's OWN base résumé contact block (name/email/phone/links).

    Whenever the user HAS a base résumé the contact is drawn from it — even when
    that contact is empty — so the operator's phone/LinkedIn can never be printed
    on another user's outbound letterhead (NF-final-B-001 class). Only a user
    with NO résumé at all falls back to the bundled base PDF's contact.
    """
    from app.agents.fit_scorer import get_base_resume_path
    from app.repositories.resume import ResumeRepository
    from app.services.resume_parser import parse_resume_pdf

    base = ResumeRepository().get_base(user_id)
    if base is not None:
        return dict((base.get("sections") or {}).get("contact") or {})
    return dict(parse_resume_pdf(get_base_resume_path())["contact"])
