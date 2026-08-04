"""Role-family scout query builder (GAP-SRC-001, gate 6).

The keyword-searchable sources (Seek, Wellfound) take a single free-text
query string. Handing them a lone narrow title — e.g. the profile's literal
``targetRole`` of "Senior Technical Program Manager" — starves discovery
volume: it excludes the dozens of synonymous titles (Product Owner, Business
Analyst, Delivery Manager, Scrum Master, Transformation Manager, ...) the
same candidate is equally qualified for, and that ``relevance.py`` already
recognizes as on-target (``TARGET_ROLE_RE``).

``build_scout_query`` BROADENS a role the caller actually has. It never
invents one:

- No target role at all -> ``ValueError``. This function used to answer that
  case with the full role-family query, and that substitution is how a data
  scientist ended up with project-management postings (F-02). Fabricating a
  search for a user who configured none is the defect, not a fallback, so the
  honest answer now lives one layer up: ``agents.py::_resolve_scout_target``
  refuses with a 422 naming the missing profile field before anything reaches
  here. An empty role arriving at this function is therefore a programming
  error, and says so instead of inventing a persona. No caller needs the old
  behaviour: the ONLY production caller is that same dispatch seam.
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

#: The whole family as one comma-joined string — the shape a broadened query
#: takes. NOT a fallback: since F-02 nothing substitutes it for a user who
#: configured no target role (see the module docstring).
ROLE_FAMILY_QUERY = ", ".join(ROLE_FAMILY_TERMS)


def build_scout_query(target_role: str | None) -> str:
    """Return the query string the scout should hand to keyword sources.

    :raises ValueError: when ``target_role`` is empty/blank. Callers resolve
        the user's own target first and refuse honestly when there is none
        (F-02) — this function broadens a real role, it never supplies one.
    """
    role = (target_role or "").strip()
    if not role:
        raise ValueError(
            "build_scout_query requires a target role — it broadens the role a "
            "user actually chose and never invents one. A caller with no target "
            "role must refuse the run (see _resolve_scout_target), not search "
            "for somebody else's job."
        )
    if not relevance.is_target_role(role):
        # Outside the recognised family — profile-driven, not overridden.
        return role
    existing = [term.strip() for term in role.split(",") if term.strip()]
    already_present = {term.lower() for term in existing}
    extra = [term for term in ROLE_FAMILY_TERMS if term not in already_present]
    return ", ".join(existing + extra)
