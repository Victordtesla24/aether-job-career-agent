"""Role-family scout query builder (GAP-SRC-001, gate 6).

The keyword-searchable sources (Seek, Wellfound) take a single free-text
query string. Handing them a lone narrow title — e.g. the profile's literal
``targetRole`` of "Senior Technical Program Manager" — starves discovery
volume: it excludes the dozens of synonymous titles (Product Owner, Business
Analyst, Delivery Manager, Scrum Master, Transformation Manager, ...) the
same candidate is equally qualified for, and that ``relevance.py`` already
recognizes as on-target (``TARGET_ROLE_RE``).

``build_scout_query`` derives a multi-term query from whatever the caller
provides:

- No target role at all -> the full role-family query.
- A target role that is itself a member of the recognised role family (per
  ``relevance.is_target_role`` — the SAME regex ``relevance.filter_relevant``
  uses to keep results, so the query and the filter never disagree about
  what counts as "on target") -> broadened to the full family, with the
  caller's own wording kept first so an exact-title match still ranks
  highest on sources that respect term order. Terms already present
  (case-insensitively) are not duplicated.
- Any other target role (a future user targeting something outside this
  family, e.g. "Software Engineer") -> passed through UNCHANGED. This module
  never invents a query for a role nobody asked for.
"""
from __future__ import annotations

from app.services.discovery import relevance

#: Representative search terms for the role family ``relevance.py`` filters
#: for. Comma-separated, matching the existing scout-query convention so
#: Seek's ``keywords=`` search and Wellfound's role-slug segment (which reads
#: the first term) keep working unchanged.
ROLE_FAMILY_TERMS: tuple[str, ...] = (
    "business analyst",
    "product owner",
    "product manager",
    "program manager",
    "project manager",
    "delivery manager",
    "technical program manager",
    "scrum master",
    "agile coach",
    "transformation manager",
)

#: The role-family query used when no profile target role is configured.
ROLE_FAMILY_QUERY = ", ".join(ROLE_FAMILY_TERMS)


def build_scout_query(target_role: str | None) -> str:
    """Return the query string the scout should hand to keyword sources."""
    role = (target_role or "").strip()
    if not role:
        return ROLE_FAMILY_QUERY
    if not relevance.is_target_role(role):
        # Outside the recognised family — profile-driven, not overridden.
        return role
    existing = [term.strip() for term in role.split(",") if term.strip()]
    already_present = {term.lower() for term in existing}
    extra = [term for term in ROLE_FAMILY_TERMS if term not in already_present]
    return ", ".join(existing + extra)
