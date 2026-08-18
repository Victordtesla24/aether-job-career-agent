"""Orchestrator-built interview pack: branded PDFs + employer-facing artefacts.

The Supervisor records the plan, then delegates to the existing agents:

* companyResearch (deterministic, already inside interview-prep briefing)
* interviewPrep (STAR + trail briefing)
* tailor / coverLetter — reuse artefacts already produced for THIS job; run
  them only when ``run_missing`` is True and none exists

Résumé and cover-letter bytes come from the existing exporters (employer voice,
never gilt-branded). Interview-prep PDF and slides use
:mod:`app.services.interview_pack_pdf` (Aether chrome).
"""
from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import asdict, dataclass, field
from io import BytesIO
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts
from app.repositories.agent_run import AgentRunRepository
from app.services.interview_pack_pdf import render_prep_pdf, render_slides_pdf

logger = logging.getLogger(__name__)

_PLAN = ("companyResearch", "interviewPrep", "tailor", "coverLetter")

_table_ready = False


def _ensure_pack_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS "InterviewPack" (
                    "id"            text PRIMARY KEY,
                    "userId"        text NOT NULL,
                    "jobId"         text NOT NULL,
                    "applicationId" text,
                    "zip"           bytea NOT NULL,
                    "manifest"      jsonb NOT NULL,
                    "supervisorRunId" text,
                    "createdAt"     timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"     timestamptz NOT NULL DEFAULT now(),
                    UNIQUE ("userId", "jobId")
                )
                """
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "InterviewPack_user_job"'
                ' ON "InterviewPack" ("userId", "jobId")'
            )
        conn.commit()
    _table_ready = True


@dataclass
class PackFile:
    name: str
    kind: str
    branded: bool
    bytes_len: int
    agent: str
    note: str = ""


@dataclass
class InterviewPackResult:
    jobId: str
    files: list[PackFile] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=lambda: list(_PLAN))
    supervisorRunId: str | None = None
    downloadPath: str = ""
    llm_called: bool = False
    message: str = ""


def load_pack(user_id: str, job_id: str) -> dict[str, Any] | None:
    _ensure_pack_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, "jobId", "applicationId", manifest, "supervisorRunId",
                       "updatedAt", octet_length(zip) AS "zipBytes"
                FROM "InterviewPack"
                WHERE "userId" = %s AND "jobId" = %s
                """,
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def load_pack_zip(user_id: str, job_id: str) -> bytes | None:
    _ensure_pack_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT zip FROM "InterviewPack" WHERE "userId" = %s AND "jobId" = %s',
                (user_id, job_id),
            )
            row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return bytes(row[0])


def extract_pack_file(user_id: str, job_id: str, name: str) -> tuple[bytes, str] | None:
    blob = load_pack_zip(user_id, job_id)
    if not blob:
        return None
    safe = name.replace("\\", "/").lstrip("/")
    if ".." in safe.split("/"):
        return None
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = zf.namelist()
        match = None
        if safe in names:
            match = safe
        else:
            base = safe.rsplit("/", 1)[-1]
            for n in names:
                if n.rsplit("/", 1)[-1] == base:
                    match = n
                    break
        if match is None:
            return None
        data = zf.read(match)
    ctype = "application/pdf" if safe.endswith(".pdf") or match.endswith(".pdf") else "text/markdown; charset=utf-8"
    if match.endswith(".docx"):
        ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return data, ctype


def assemble_interview_pack(
    user_id: str,
    job_id: str,
    *,
    current_user: dict[str, Any] | None = None,
    run_missing: bool = False,
    prep_output: dict[str, Any] | None = None,
) -> InterviewPackResult:
    """Build the zip folder. Never fabricates résumé/cover-letter content."""
    from app.repositories.job import JobRepository
    from app.repositories.user import UserRepository

    job = JobRepository().get_by_id(job_id, user_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found for user")

    user = current_user or UserRepository().get_by_id(user_id) or {"id": user_id}
    if "id" not in user:
        user = {**user, "id": user_id}

    runs = AgentRunRepository()
    supervisor = runs.start(
        user_id,
        "supervisor",
        {"plan": list(_PLAN), "job_id": job_id, "source": "interview_pack"},
    )
    result = InterviewPackResult(
        jobId=job_id,
        supervisorRunId=str(supervisor["id"]),
        downloadPath=f"/workspaces/interviews/pack/download?job_id={job_id}",
    )

    prep = prep_output or _latest_prep_output(user_id, job_id)
    if prep is None:
        from app.agents.interview_prep_agent import InterviewPrepAgent

        child = runs.start(
            user_id, "interviewPrep", {"job_id": job_id, "source": "interview_pack"},
            parent_run_id=str(supervisor["id"]),
        )
        try:
            prep_result = InterviewPrepAgent().run(user_id, job_id=job_id)
            prep = asdict(prep_result)
            llm_called = prep.pop("llm_called", True)
            result.llm_called = bool(llm_called)
            if not llm_called:
                prep["noLlmCall"] = True
            runs.finish(child["id"], "completed", output=prep, cost_usd=0.0)
        except Exception as exc:  # noqa: BLE001 — pack still ships trail PDFs
            logger.warning("interview pack prep failed: %s", exc)
            runs.finish(child["id"], "failed", error=str(exc)[:2000])
            prep = {
                "jobId": job_id,
                "jobTitle": job.get("title"),
                "company": job.get("company"),
                "briefing": {},
                "predictedQuestions": [],
            }
            result.gaps.append(
                "Interview Prep did not finish, so STAR sketches are absent. "
                "Logistics PDFs still use the email trail where evidenced."
            )

    briefing = prep.get("briefing") if isinstance(prep, dict) else {}
    if not isinstance(briefing, dict):
        briefing = {}
    questions = prep.get("predictedQuestions") if isinstance(prep, dict) else []
    if not isinstance(questions, list):
        questions = []

    title = str((prep or {}).get("jobTitle") or job.get("title") or "Interview")
    company = str((prep or {}).get("company") or job.get("company") or "")

    members: list[tuple[str, bytes, PackFile]] = []
    prep_pdf = render_prep_pdf(
        title=title, company=company, briefing=briefing, questions=questions
    )
    members.append(
        (
            "01-interview-prep.pdf",
            prep_pdf,
            PackFile(
                "01-interview-prep.pdf",
                "interview_prep",
                True,
                len(prep_pdf),
                "interviewPrep",
                "Aether-branded brief from the trail, stories and career sources.",
            ),
        )
    )
    slides = render_slides_pdf(
        title=title, company=company, briefing=briefing, questions=questions
    )
    members.append(
        (
            "02-interview-slides.pdf",
            slides,
            PackFile(
                "02-interview-slides.pdf",
                "slides",
                True,
                len(slides),
                "interviewPrep",
                "Four landscape slides: logistics, traps, STAR, ask and close.",
            ),
        )
    )
    md = str(briefing.get("documentMarkdown") or "").encode("utf-8")
    if md:
        members.append(
            (
                "05-briefing.md",
                md,
                PackFile(
                    "05-briefing.md",
                    "markdown",
                    True,
                    len(md),
                    "interviewPrep",
                    "Plain-text twin of the branded brief.",
                ),
            )
        )

    resume_bytes, resume_name, resume_note = _employer_resume(
        user_id, job_id, user, run_missing=run_missing, parent_id=str(supervisor["id"])
    )
    if resume_bytes:
        members.append(
            (
                resume_name,
                resume_bytes,
                PackFile(
                    resume_name,
                    "resume",
                    False,
                    len(resume_bytes),
                    "tailor",
                    resume_note,
                ),
            )
        )
    else:
        result.gaps.append(resume_note)

    cover_bytes, cover_note = _employer_cover(
        user_id, job_id, user, run_missing=run_missing, parent_id=str(supervisor["id"])
    )
    if cover_bytes:
        members.append(
            (
                "04-cover-letter.pdf",
                cover_bytes,
                PackFile(
                    "04-cover-letter.pdf",
                    "cover_letter",
                    False,
                    len(cover_bytes),
                    "coverLetter",
                    cover_note,
                ),
            )
        )
    else:
        result.gaps.append(cover_note)

    folder = _folder_name(company, title)
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data, meta in members:
            zf.writestr(f"{folder}/{name}", data)
            result.files.append(meta)

    zip_bytes = zip_buf.getvalue()
    result.message = (
        f"Interview pack for {title} at {company}: {len(result.files)} file(s). "
        + (
            "Gaps: " + " ".join(result.gaps)
            if result.gaps
            else "Résumé and cover letter included from artefacts already on file."
        )
    )
    _upsert_pack(
        user_id,
        job_id,
        zip_bytes,
        {
            "folder": folder,
            "files": [asdict(f) for f in result.files],
            "gaps": result.gaps,
            "plan": list(_PLAN),
            "message": result.message,
        },
        supervisor_run_id=str(supervisor["id"]),
    )
    runs.finish(
        supervisor["id"],
        "completed",
        output={
            "plan": list(_PLAN),
            "jobId": job_id,
            "files": [asdict(f) for f in result.files],
            "gaps": result.gaps,
            "llm_called": False,
        },
        cost_usd=0.0,
    )
    return result


def pack_payload(user_id: str, job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    row = load_pack(user_id, job_id)
    if not row:
        return None
    manifest = row.get("manifest") or {}
    return {
        "jobId": row["jobId"],
        "assembledAt": row.get("updatedAt").isoformat()
        if hasattr(row.get("updatedAt"), "isoformat")
        else row.get("updatedAt"),
        "folder": manifest.get("folder"),
        "files": manifest.get("files") or [],
        "gaps": manifest.get("gaps") or [],
        "plan": manifest.get("plan") or list(_PLAN),
        "message": manifest.get("message") or "",
        "downloadPath": f"/workspaces/interviews/pack/download?job_id={job_id}",
        "zipBytes": row.get("zipBytes"),
    }


def _folder_name(company: str, title: str) -> str:
    raw = f"Interview pack — {company or 'employer'} — {title or 'role'}"
    cleaned = "".join(ch if ch not in '\\/:*?"<>|' else "-" for ch in raw)
    return cleaned[:80].strip() or "Interview pack"


def _latest_prep_output(user_id: str, job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT output FROM "AgentRun"
                WHERE "userId" = %s AND "agentName" = 'interviewPrep'
                  AND status = 'completed'
                  AND jsonb_typeof(output) = 'object'
                  AND output->>'jobId' = %s
                ORDER BY "startedAt" DESC
                LIMIT 1
                """,
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    out = rows[0]["output"] if rows else None
    return out if isinstance(out, dict) else None


def _employer_resume(
    user_id: str,
    job_id: str,
    current_user: dict[str, Any],
    *,
    run_missing: bool,
    parent_id: str,
) -> tuple[bytes | None, str, str]:
    from app.repositories.resume import ResumeRepository

    repo = ResumeRepository()
    tailored = repo.get_tailored_for_job(user_id, job_id)
    if tailored is None and run_missing:
        tailored = _run_tailor(user_id, job_id, parent_id)
    if tailored is None:
        return (
            None,
            "03-resume.pdf",
            "No job-tailored résumé for this role yet. Run the Tailor agent, "
            "then assemble the pack again. Aether will not put a résumé written "
            "for a different job in this folder.",
        )
    from fastapi import HTTPException
    from app.routers.resumes import _render_resume

    try:
        rendered = _render_resume(
            str(tailored["id"]), user_id, branded=False, highlight=False
        )
    except HTTPException as exc:
        return None, "03-resume.pdf", str(exc.detail)
    suffix = ".pdf"
    name = str(getattr(rendered, "filename", "") or "resume.pdf")
    if "." in name:
        suffix = "." + name.rsplit(".", 1)[-1]
    return (
        bytes(rendered.content),
        f"03-resume{suffix}",
        "Employer-facing tailored résumé (your document, not Aether chrome).",
    )


def _run_tailor(user_id: str, job_id: str, parent_id: str) -> dict[str, Any] | None:
    from app.agents.tailor_agent import TailorAgent
    from app.repositories.resume import ResumeRepository
    from app.services.resume_grounding import MissingResumeError

    runs = AgentRunRepository()
    child = runs.start(
        user_id, "tailor", {"job_id": job_id, "source": "interview_pack"},
        parent_run_id=parent_id,
    )
    try:
        TailorAgent().run(user_id, job_id)
        runs.finish(child["id"], "completed", output={"jobId": job_id}, cost_usd=0.0)
        return ResumeRepository().get_tailored_for_job(user_id, job_id)
    except (LookupError, MissingResumeError) as exc:
        runs.finish(child["id"], "failed", error=str(exc)[:2000])
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("interview pack tailor failed: %s", exc)
        runs.finish(child["id"], "failed", error=str(exc)[:2000])
        return None


def _employer_cover(
    user_id: str,
    job_id: str,
    current_user: dict[str, Any],
    *,
    run_missing: bool,
    parent_id: str,
) -> tuple[bytes | None, str]:
    letter = _cover_for_job(user_id, job_id)
    if letter is None and run_missing:
        letter = _run_cover(user_id, job_id, parent_id)
    if letter is None:
        return (
            None,
            "No cover letter for this application yet. Run the Cover Letter "
            "agent, then assemble the pack again.",
        )
    from fastapi import HTTPException
    from app.routers.cover_letters import export_cover_letter_pdf

    try:
        resp = export_cover_letter_pdf(str(letter["id"]), current_user)
    except HTTPException as exc:
        return None, str(exc.detail)
    return bytes(resp.body), "Employer-facing cover letter (your voice, not Aether chrome)."


def _cover_for_job(user_id: str, job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM "Application"
                WHERE "userId" = %s AND "jobId" = %s
                  AND "coverLetter" IS NOT NULL
                ORDER BY "updatedAt" DESC
                LIMIT 1
                """,
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _run_cover(user_id: str, job_id: str, parent_id: str) -> dict[str, Any] | None:
    from app.agents.cover_letter_agent import CoverLetterAgent
    from app.services.resume_grounding import MissingResumeError

    runs = AgentRunRepository()
    child = runs.start(
        user_id, "coverLetter", {"job_id": job_id, "source": "interview_pack"},
        parent_run_id=parent_id,
    )
    try:
        CoverLetterAgent().run(user_id, job_id)
        runs.finish(child["id"], "completed", output={"jobId": job_id}, cost_usd=0.0)
        return _cover_for_job(user_id, job_id)
    except (LookupError, MissingResumeError) as exc:
        runs.finish(child["id"], "failed", error=str(exc)[:2000])
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("interview pack cover letter failed: %s", exc)
        runs.finish(child["id"], "failed", error=str(exc)[:2000])
        return None


def _application_id(user_id: str, job_id: str) -> str | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM "Application"
                WHERE "userId" = %s AND "jobId" = %s
                ORDER BY "updatedAt" DESC LIMIT 1
                """,
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    return str(rows[0]["id"]) if rows else None


def _upsert_pack(
    user_id: str,
    job_id: str,
    zip_bytes: bytes,
    manifest: dict[str, Any],
    *,
    supervisor_run_id: str | None,
) -> None:
    _ensure_pack_table()
    app_id = _application_id(user_id, job_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "InterviewPack"
                    ("id","userId","jobId","applicationId","zip","manifest",
                     "supervisorRunId","createdAt","updatedAt")
                VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,now(),now())
                ON CONFLICT ("userId", "jobId") DO UPDATE SET
                    zip = EXCLUDED.zip,
                    manifest = EXCLUDED.manifest,
                    "applicationId" = EXCLUDED."applicationId",
                    "supervisorRunId" = EXCLUDED."supervisorRunId",
                    "updatedAt" = now()
                """,
                (
                    new_id(),
                    user_id,
                    job_id,
                    app_id,
                    zip_bytes,
                    json.dumps(manifest),
                    supervisor_run_id,
                ),
            )
        conn.commit()
