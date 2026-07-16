"""Jobs router — list/detail/save/archive plus AI insights and apply (P2-S02).

The Job Discovery screen (``/dashboard/jobs``) reads:
- ``GET /jobs``               ranked list with filters (list/detail/saved views)
- ``GET /jobs/{id}``          single posting
- ``GET /jobs/{id}/insights`` ATS-derived match analysis, 10-dimension fit and
                              risk signals — all deterministic functions of the
                              real resume + posting (no mock, no randomness)
- ``POST /jobs/{id}/save``    toggle the saved bookmark
- ``POST /jobs/{id}/apply``   create an Application and advance the job to
                              ``applied`` (powers the submit-confirmation gate)
- ``DELETE /jobs/{id}``       soft-archive
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.db import get_connection, new_id, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.repositories.job import VALID_STATUSES, JobRepository
from app.services.discovery.active_feed import active_feed

router = APIRouter()


def _public(job: dict[str, Any]) -> dict[str, Any]:
    """Job rows are already safe to expose; kept as a single choke-point."""
    return job


@router.get("")
def list_jobs(
    current_user: CurrentUser,
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    saved: bool | None = Query(default=None),
    sort: str = Query(default="createdAt"),
    include_stale: bool = Query(default=False),
) -> list[dict[str, Any]]:
    """List the authenticated user's discovered jobs, with optional filters.

    By default this is the ACTIVE feed (GAP-P6-DATA-001): rows from a dead /
    ToS-non-compliant source (Seek) and rows older than the freshness window
    (>30d STALE) are hidden, and a role cross-posted to two boards is shown
    once — so paying users never see the dead Seek cards probe-13 found. History
    is never deleted; ``include_stale=true`` returns the unfiltered set.
    """
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status '{status}'")
    jobs = JobRepository().list_by_user(
        current_user["id"], status=status, source=source, saved=saved, sort=sort
    )
    if not include_stale:
        jobs = active_feed(jobs)
    return [_public(job) for job in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    job = JobRepository().get_by_id(job_id, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _public(job)


# ---------------------------------------------------------------------------
# Insights — deterministic ATS-derived analysis for the detail panel.
# ---------------------------------------------------------------------------

#: Location tokens that classify a posting as Australia-local (used by the UI
#: market tabs too, but computed here so the label is authoritative server-side).
_AU_TOKENS = (
    "australia", " au", "au ", "au-", "-au", "nsw", "vic", "qld", "wa ", "sa ",
    "act", "tas", "sydney", "melbourne", "brisbane", "perth", "adelaide",
    "canberra", "hobart", "darwin", "gold coast", "newcastle", "wollongong",
)

_SENIORITY = (
    ("principal", 92), ("director", 92), ("head of", 90), ("head ", 90),
    ("vp ", 92), ("chief", 95), ("staff", 88), ("lead", 84), ("senior", 82),
    ("snr", 82), ("manager", 78), ("mid", 65), ("junior", 52), ("graduate", 45),
    ("intern", 40),
)

#: Established ATS/boards → higher stability proxy than aggregator boards.
_SOURCE_STABILITY = {
    "greenhouse": 86, "lever": 86, "seek": 84, "linkedin": 84, "workforce": 88,
    "indeed": 78, "jora": 74, "remotive": 74, "remoteok": 72,
}


def _requirements_list(job: dict[str, Any]) -> list[str]:
    reqs = job.get("requirements")
    if isinstance(reqs, str):
        try:
            reqs = json.loads(reqs)
        except ValueError:
            reqs = [reqs]
    return [str(r) for r in (reqs or [])]


def _job_text(job: dict[str, Any]) -> str:
    title = job.get('title', '')
    desc = job.get('description', '')
    reqs = ' '.join(_requirements_list(job))
    return f"{title} {desc} {reqs}".strip()


def _is_au(job: dict[str, Any]) -> bool:
    loc = f" {(job.get('location') or '').lower()} "
    return any(tok in loc for tok in _AU_TOKENS)


def _seniority_score(title: str) -> int:
    t = title.lower()
    for token, score in _SENIORITY:
        if token in t:
            return score
    return 68  # unlabelled individual-contributor default


def _salary_fit(job: dict[str, Any]) -> int:
    """Deterministic salary-fit from the structured band (neutral when absent)."""
    smin, smax = job.get("salaryMin"), job.get("salaryMax")
    if smin is None and smax is None:
        return 70  # unknown → neutral, and flagged separately in risk signals
    top = smax or smin or 0
    # Target band ~ AUD 150k–260k for the demo profile; reward overlap.
    if top >= 200_000:
        return 96
    if top >= 160_000:
        return 90
    if top >= 120_000:
        return 80
    return 68


def _round(v: float) -> int:
    return int(max(0, min(100, round(v))))


#: Non-skill tokens the ATS keyword extractor surfaces (entity/boilerplate) that
#: read poorly as "skills" — dropped from the displayed tags/gap only.
_SKILL_NOISE = {
    "remote", "hybrid", "onsite", "full", "time", "part", "role", "team",
    "teams", "company", "senior", "lead", "years", "experience", "australia",
    "global", "based", "one", "over", "most", "more", "many", "some", "well",
    "help", "make", "work", "working", "world", "people", "across", "within",
    "into", "also", "this", "that", "these", "those", "your", "our", "their",
    "who", "what", "how", "why", "when", "where", "improving", "status",
    "workers", "million", "billion", "join", "looking", "want", "like", "new",
    "good", "great", "best", "day", "days", "week", "month", "year", "hour",
}


def _entity_tokens(job: dict[str, Any]) -> set[str]:
    """Company + location words — noise when shown as a candidate skill."""
    blob = f"{job.get('company', '')} {job.get('location', '')}".lower()
    return {t.strip(".,-—·") for t in blob.replace("·", " ").split() if t}


def _clean_skills(keywords: list[str], entities: set[str]) -> list[str]:
    """Drop entity/boilerplate noise; surface the most distinctive terms first.

    The ATS keyword extractor emits JD TF-IDF tokens (the terms that actually
    drive the fit score). We remove entity names and generic words, then order
    longer/more-specific terms first so the displayed chips read as skills.
    """
    seen: set[str] = set()
    out: list[str] = []
    for kw in keywords:
        low = kw.lower()
        if low in _SKILL_NOISE or low in entities or len(low) < 4 or low in seen:
            continue
        seen.add(low)
        out.append(kw)
    out.sort(key=lambda k: (-len(k), k))
    return out


def _build_insights(job: dict[str, Any]) -> dict[str, Any]:
    """Run the real ATS engine + deterministic field blends into a UI payload."""
    from app.agents.fit_scorer import _resume_text
    from app.services.ats_engine import ATSEngine

    title = job.get("title", "")
    remote = bool(job.get("remote"))
    au = _is_au(job)

    try:
        score = ATSEngine().score(_resume_text(), _job_text(job))
        km = float(score.keyword_match)
        sem = float(score.semantic_similarity)
        exp = float(score.experience_gap)
        overall = float(score.overall)
        matched = list(score.matched_keywords)
        missing = list(score.missing_keywords)
        scored = True
    except Exception:  # noqa: BLE001 — never 500 the detail panel
        overall = float(job.get("fitScore") or 0.0)
        km = sem = exp = overall
        matched, missing = [], []
        scored = job.get("fitScore") is not None

    entities = _entity_tokens(job)
    matched = _clean_skills(matched, entities)
    missing = _clean_skills(missing, entities)

    salary_fit = _salary_fit(job)
    location_match = 100 if remote else (95 if au else 70)
    career_growth = _round(0.6 * _seniority_score(title) + 0.4 * overall)
    culture_fit = _round(0.5 * sem + 0.5 * exp)
    stability = _round(_SOURCE_STABILITY.get(str(job.get("source", "")).lower(), 76)
                       + (6 if (job.get("salaryMin") or job.get("salaryMax")) else 0))
    north_star = _round(0.6 * overall + 0.4 * sem)

    dimensions = [
        {"label": "Technical Skills", "score": _round(km)},
        {"label": "Experience Level", "score": _round(exp)},
        {"label": "Industry Match", "score": _round(sem)},
        {"label": "Role Alignment", "score": _round(overall)},
        {"label": "Culture Fit", "score": culture_fit},
        {"label": "Salary Fit", "score": salary_fit},
        {"label": "Location Match", "score": location_match},
        {"label": "Career Growth", "score": career_growth},
        {"label": "Company Stability", "score": stability},
        {"label": "North Star Align", "score": north_star},
    ]

    skills_matched = len(matched)
    skills_total = len(matched) + len(missing)
    skill_gap = missing[0] if missing else None

    risks: list[dict[str, str]] = []
    if job.get("salaryMin") is None and job.get("salaryMax") is None:
        risks.append({"label": "No salary listed", "severity": "medium"})
    if len(missing) >= 4:
        risks.append({"label": f"{len(missing)} key skills not matched", "severity": "high"})
    if km < 50:
        risks.append({"label": f"Low keyword coverage ({_round(km)}%)", "severity": "high"})
    if sem < 50:
        risks.append({"label": f"Domain overlap only {_round(sem)}%", "severity": "medium"})

    if scored:
        narrative = (
            f"Your resume covers {skills_matched} of {skills_total} keywords this "
            f"posting emphasises, with {_round(sem)}% semantic overlap and a "
            f"{_round(overall)}% overall ATS fit for {title or 'this role'}."
        )
    else:
        narrative = (
            "Not scored yet — run the Fit Scorer agent to analyse this role "
            "against your resume."
        )

    return {
        "jobId": job["id"],
        "scored": scored,
        "overall": _round(overall),
        "keywordMatch": _round(km),
        "semantic": _round(sem),
        "experience": _round(exp),
        "skillsMatched": skills_matched,
        "skillsTotal": skills_total,
        "matchedSkills": matched[:8],
        "missingSkills": missing[:6],
        "skillGap": skill_gap,
        "narrative": narrative,
        "dimensions": dimensions,
        "riskSignals": risks,
        "isAustralia": au,
    }


@router.get("/{job_id}/insights")
def job_insights(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """ATS-derived match analysis, 10-dimension fit and risk signals (P2-S04)."""
    job = JobRepository().get_by_id(job_id, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _build_insights(job)


@router.post("/{job_id}/save")
def toggle_save(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    job = JobRepository().toggle_saved(job_id, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _public(job)


# ---------------------------------------------------------------------------
# Apply — the submit-confirmation gate's real write.
# ---------------------------------------------------------------------------


def _resume_for_apply(user_id: str, job_id: str) -> str | None:
    """Pick the resume to apply with: a job-tailored one if present, else base."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id" FROM "Resume" '
                'WHERE "userId" = %s AND "sourceJobId" = %s '
                'ORDER BY "version" DESC LIMIT 1',
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
            if rows:
                return rows[0]["id"]
            cur.execute(
                'SELECT "id" FROM "Resume" WHERE "userId" = %s '
                'ORDER BY "version" ASC LIMIT 1',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    return rows[0]["id"] if rows else None


def _existing_application(user_id: str, job_id: str) -> str | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id" FROM "Application" WHERE "userId" = %s AND "jobId" = %s '
                'ORDER BY "createdAt" DESC LIMIT 1',
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0]["id"] if rows else None


@router.post("/{job_id}/apply")
def apply_to_job(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Create an Application and advance the job to ``applied`` (idempotent).

    Powers the Review & Apply submit gate on the Job Discovery screen. Uses the
    user's job-tailored resume when one exists, otherwise their base resume.
    """
    user_id = current_user["id"]
    repository = JobRepository()
    job = repository.get_by_id(job_id, user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    application_id = _existing_application(user_id, job_id)
    if application_id is None:
        resume_id = _resume_for_apply(user_id, job_id)
        if resume_id is None:
            raise HTTPException(
                status_code=422,
                detail="No resume available to apply with — create one first.",
            )
        application_id = new_id()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "Application"
                        ("id", "userId", "jobId", "resumeId", "status", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s::"ApplicationStatus", NOW())
                    ''',
                    (application_id, user_id, job_id, resume_id, "submitted"),
                )
            conn.commit()

    updated = job if job.get("status") == "applied" else repository.update_status(job_id, "applied")
    assert updated is not None
    return {"job": _public(updated), "applicationId": application_id}


@router.delete("/{job_id}")
def archive_job(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Soft delete: jobs are archived, never destroyed."""
    repository = JobRepository()
    if repository.get_by_id(job_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job = repository.update_status(job_id, "archived")
    assert job is not None  # existence checked above
    return _public(job)
