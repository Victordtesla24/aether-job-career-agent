"""Per-user résumé grounding — the caller's OWN résumé, never a fixed one.

Every user-facing agent path that grounds a generated artifact or an analytic
on "the candidate résumé" MUST use these helpers so no account is ever grounded
on another user's — or the operator's — résumé (NF-final-B-001/002/005,
MV-story-bank-006).

Two fallback regimes:

* INTERNAL analytics (e.g. the story extractor) may keep the bundled base PDF as
  a last-resort fallback when the user has no résumé — nothing user-visible
  leaves the system (``allow_operator_fallback=True``, the default).
* OUTBOUND artifacts (cover letters, email drafts, refined letters, exported
  PDFs / attachments) MUST pass ``allow_operator_fallback=False`` and REFUSE to
  generate when the user has no résumé — emitting the bundled operator résumé
  into a third-party-visible artifact is a cross-account PII leak.
"""
from __future__ import annotations

from typing import Any


class MissingResumeError(Exception):
    """Raised by an OUTBOUND path when the caller has no résumé of their own.

    Callers surface this as an honest 4xx ("Add your resume before …") rather
    than grounding the artifact on a fixed operator résumé or fabricating from
    empty evidence.
    """


def _own_base_text(base: dict[str, Any] | None) -> str:
    if not base:
        return ""
    sections = base.get("sections") or {}
    return sections.get("raw_text") or "\n".join(
        str(b.get("text", ""))
        for b in sections.get("bullets", [])
        if b.get("text")
    )


def resolve_user_resume_text(
    user_id: str, *, allow_operator_fallback: bool = True
) -> str:
    """The caller's OWN base résumé text.

    Reads the user's base (root) résumé (``sections.raw_text``, falling back to
    its bullets). When the user has NO résumé on file the behaviour depends on
    ``allow_operator_fallback``: internal callers (default ``True``) fall back to
    the bundled base PDF; OUTBOUND callers pass ``False`` and receive an empty
    string so they can REFUSE rather than emit the operator résumé.
    """
    from app.agents.fit_scorer import get_base_resume_path
    from app.repositories.resume import ResumeRepository
    from app.services.resume_parser import parse_resume_pdf

    text = _own_base_text(ResumeRepository().get_base(user_id))
    if text and text.strip():
        return text
    if not allow_operator_fallback:
        return ""
    return parse_resume_pdf(get_base_resume_path())["raw_text"]


def resolve_user_resume_contact(
    user_id: str, *, allow_operator_fallback: bool = True
) -> dict[str, Any]:
    """The caller's OWN base résumé contact block (name/email/phone/links).

    Whenever the user HAS a base résumé the contact is drawn from it — even when
    that contact is empty — so the operator's phone/LinkedIn can never be printed
    on another user's outbound letterhead (NF-final-B-001 class). A user with NO
    résumé returns the bundled contact only when ``allow_operator_fallback`` is
    ``True`` (never on an outbound letterhead, which passes ``False``).
    """
    from app.agents.fit_scorer import get_base_resume_path
    from app.repositories.resume import ResumeRepository
    from app.services.resume_parser import parse_resume_pdf

    base = ResumeRepository().get_base(user_id)
    if base is not None:
        return dict((base.get("sections") or {}).get("contact") or {})
    if not allow_operator_fallback:
        return {}
    return dict(parse_resume_pdf(get_base_resume_path())["contact"])


def require_user_resume_text(user_id: str, message: str) -> str:
    """The caller's OWN résumé text for an OUTBOUND artifact, or raise.

    Never falls back to the bundled operator résumé — raises
    :class:`MissingResumeError` (with ``message``) when the user has no résumé so
    the caller refuses honestly instead of leaking operator content.
    """
    text = resolve_user_resume_text(user_id, allow_operator_fallback=False)
    if not text.strip():
        raise MissingResumeError(message)
    return text
