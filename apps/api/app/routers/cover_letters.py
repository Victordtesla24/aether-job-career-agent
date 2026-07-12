"""Cover letters router (P2-S06) + Cover Letter Studio intelligence (R11).

Beyond list/get, the studio endpoints ground the wireframe's right rail in
real data (cover-letter-studio.html cl05–cl16):

- ``GET  /cover-letters/{id}/insights`` — evidence trace (letter × Story Bank ×
  resume corpus), JD keyword coverage, voice metrics and the per-job version
  chain, all computed deterministically from the persisted rows.
- ``POST /cover-letters/{id}/refine`` — "Request Changes" / Voice-DNA-driven
  redraft: fabrication-guarded LLM revision stored as a new draft with a
  pending ApprovalRequest (same human gate as the Cover Letter Agent).
- ``GET  /cover-letters/{id}/pdf`` — real PDF export of the letter.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.agents.fit_scorer import get_base_resume_path
from app.middleware.auth import CurrentUser
from app.repositories.approval import ApprovalRepository
from app.repositories.cover_letter import CoverLetterRepository
from app.repositories.job import JobRepository
from app.repositories.story import StoryRepository
from app.services.fabrication_guard import FabricationGuard
from app.services.llm_client import LLMClient, LLMUnavailableError, get_model
from app.services.resume_parser import parse_resume_pdf

router = APIRouter()

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./-]*")

#: Connective words excluded from keyword/evidence matching.
_STOPWORDS = frozenset(
    """
    a an and are as at be been by for from has have i in is it its my of on
    or our that the their this to was we were will with you your who what
    how when across own more most very than then also both each
    """.split()
)


@lru_cache(maxsize=1)
def _resume_text() -> str:
    """Base resume text, parsed once — the PDF never changes at runtime."""
    return parse_resume_pdf(get_base_resume_path())["raw_text"]


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "")}


def _meaningful(text: str) -> list[str]:
    """Ordered, deduped content words (≥3 chars, non-stopword)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _WORD_RE.findall(text or ""):
        low = raw.lower()
        if len(low) < 3 or low in _STOPWORDS or low in seen:
            continue
        seen.add(low)
        out.append(raw)
    return out


def _story_corpus(story: dict[str, Any]) -> str:
    parts = [story.get("title") or "", " ".join(story.get("tags") or [])]
    for key in ("situation", "task", "action", "result"):
        parts.append(story.get(key) or "")
    return " ".join(parts)


def _find_phrase(letter_lower: str, letter: str, phrase: str) -> str | None:
    """Return the phrase as it literally appears in the letter, else None."""
    idx = letter_lower.find(phrase.lower())
    if idx < 0:
        return None
    return letter[idx : idx + len(phrase)]


def _evidence_trace(
    letter: str, stories: list[dict[str, Any]], job: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Claim → source rows: green when a Story Bank entry backs the phrase,
    amber when the letter echoes the JD with no personal evidence behind it."""
    letter_lower = letter.lower()
    letter_tokens = _tokens(letter)
    rows: list[dict[str, Any]] = []
    claimed: set[str] = set()

    for story in stories:
        # Prefer verbatim multi-word phrases (tags, then title fragments).
        candidates = list(story.get("tags") or [])
        title = story.get("title") or ""
        candidates.append(title)
        best: str | None = None
        for cand in candidates:
            if len(cand) < 3:
                continue
            hit = _find_phrase(letter_lower, letter, cand)
            if hit and (best is None or len(hit) > len(best)):
                best = hit
        if best is None:
            # Fall back to token overlap: ≥2 meaningful story words in letter.
            words = [w for w in _meaningful(title) if w.lower() in letter_tokens]
            if len(words) >= 2:
                best = _find_phrase(letter_lower, letter, words[0]) or words[0]
        if best and best.lower() not in claimed:
            claimed.add(best.lower())
            rows.append(
                {
                    "claim": best,
                    "storyId": story["id"],
                    "storyTitle": story["title"],
                    "grounded": True,
                }
            )
        if len(rows) >= 4:
            break

    # JD-echo claims with no personal evidence: in the letter and the job
    # description, but absent from resume + story corpora → "add or soften".
    personal = _tokens(_resume_text()).union(*(_tokens(_story_corpus(s)) for s in stories))
    jd_tokens = _tokens(f"{(job or {}).get('title', '')} {(job or {}).get('description', '')}")
    for word in _meaningful(letter):
        low = word.lower()
        if low in jd_tokens and low not in personal and low not in claimed and len(low) > 4:
            claimed.add(low)
            rows.append({"claim": word, "storyId": None, "storyTitle": None, "grounded": False})
            if sum(1 for r in rows if not r["grounded"]) >= 2:
                break
    return rows


def _keyword_coverage(letter: str, job: dict[str, Any] | None) -> dict[str, Any]:
    jd = f"{(job or {}).get('title', '')} {(job or {}).get('description', '')}"
    keywords = _meaningful(jd)[:10]
    letter_tokens = _tokens(letter)
    items = [{"keyword": k, "covered": k.lower() in letter_tokens} for k in keywords]
    return {
        "covered": sum(1 for i in items if i["covered"]),
        "total": len(items),
        "items": items,
    }


def _voice_metrics(letter: str, corpus: str) -> dict[str, Any]:
    """Evidence-support heuristics behind the header badges (cl03).

    Authenticity = share of the letter's content words backed by the evidence
    corpus (resume + job + stories). Detection risk shrinks as grounding
    grows — a guard-passed letter sits in single digits.
    """
    words = _meaningful(letter)
    corpus_tokens = _tokens(corpus)
    supported = sum(1 for w in words if w.lower() in corpus_tokens)
    authenticity = round(100 * supported / len(words)) if words else 0
    risk = max(1, round((100 - authenticity) / 2))
    return {
        "authenticity": authenticity,
        "aiDetectionRisk": risk,
        "aiDetectionLabel": "Safe" if risk < 20 else "Review",
    }


def _load_letter(letter_id: str, user_id: str) -> dict[str, Any]:
    letter = CoverLetterRepository().get_by_id(letter_id, user_id)
    if letter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cover letter not found")
    return letter


@router.get("")
def list_cover_letters(current_user: CurrentUser) -> list[dict[str, Any]]:
    return CoverLetterRepository().list_by_user(current_user["id"])


@router.get("/{letter_id}")
def get_cover_letter(letter_id: str, current_user: CurrentUser) -> dict[str, Any]:
    return _load_letter(letter_id, current_user["id"])


@router.get("/{letter_id}/insights")
def cover_letter_insights(letter_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Studio rail data — computed from the real letter/job/story rows."""
    user_id = current_user["id"]
    letter = _load_letter(letter_id, user_id)
    text = letter["coverLetter"] or ""
    job = JobRepository().get_by_id(letter["jobId"], user_id)
    stories = StoryRepository().list_by_user(user_id)

    corpus = " ".join(
        [_resume_text(), (job or {}).get("title", ""), (job or {}).get("company", ""),
         (job or {}).get("description", "")]
        + [_story_corpus(s) for s in stories]
    )
    siblings = [
        lt for lt in CoverLetterRepository().list_by_user(user_id)
        if lt["jobId"] == letter["jobId"]
    ]
    siblings.sort(key=lambda lt: lt["createdAt"])
    versions = [
        {
            "id": lt["id"],
            "version": i + 1,
            "createdAt": lt["createdAt"],
            "current": i == len(siblings) - 1,
        }
        for i, lt in enumerate(siblings)
    ]
    return {
        "letterId": letter["id"],
        "jobId": letter["jobId"],
        "jobTitle": (job or {}).get("title"),
        "company": (job or {}).get("company"),
        "wordCount": len(text.split()),
        "evidence": _evidence_trace(text, stories, job),
        "keywords": _keyword_coverage(text, job),
        "voice": _voice_metrics(text, corpus),
        "versions": versions,
    }


_REFINE_SYSTEM_PROMPT = (
    "You are a truthful cover-letter editor. Revise the letter body as "
    "instructed. Use ONLY facts present in the candidate's resume text. "
    "Never invent skills, employers, titles, metrics or achievements. Do not "
    "name any company other than the target company. "
    'Respond with JSON: {"body": "<2-3 paragraphs>"}'
)

_TONE_LABELS = ["confident and direct", "warm and professional", "enthusiastic and personable"]
_FORMALITY_LABELS = ["conversational", "balanced", "formal"]


def _scale_label(value: int, labels: list[str]) -> str:
    return labels[min(len(labels) - 1, value * len(labels) // 101)]


class RefineRequest(BaseModel):
    instructions: str = Field("", max_length=2000)
    tone: int | None = Field(None, ge=0, le=100)
    formality: int | None = Field(None, ge=0, le=100)


@router.post("/{letter_id}/refine")
def refine_cover_letter(
    letter_id: str, body: RefineRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Fabrication-guarded revision → new draft + pending approval (P2-S07)."""
    user_id = current_user["id"]
    letter = _load_letter(letter_id, user_id)
    job = JobRepository().get_by_id(letter["jobId"], user_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job for this letter not found")

    resume_text = _resume_text()
    guard = FabricationGuard()
    corpus = " ".join(
        [resume_text, job["title"], job["company"], job.get("description") or ""]
    )
    asks: list[str] = []
    if body.instructions.strip():
        asks.append(f"Requested changes: {body.instructions.strip()}")
    if body.tone is not None:
        asks.append(f"Tone: {_scale_label(body.tone, _TONE_LABELS)}.")
    if body.formality is not None:
        asks.append(f"Formality: {_scale_label(body.formality, _FORMALITY_LABELS)}.")
    base_prompt = (
        f"Target role: {job['title']} at {job['company']}.\n"
        f"Job description: {job.get('description') or ''}\n\n"
        f"Current letter body:\n{letter['coverLetter']}\n\n"
        + "\n".join(asks)
        + f"\n\nCandidate resume:\n{resume_text}"
    )

    llm = LLMClient()

    def _draft(prompt: str, fixture_key: str) -> tuple[str, list[str]]:
        raw = llm.complete_json(
            "cover_letter_refine",
            _REFINE_SYSTEM_PROMPT,
            prompt,
            model=get_model("REASONING"),
            temperature=0.0,
            fixture_key=fixture_key,
        )
        text = (raw.get("body") or "").strip()
        full = (
            f"Dear Hiring Team at {job['company']},\n\n"
            f"I am writing to express my interest in the {job['title']} "
            f"position at {job['company']}.\n\n{text}\n\n"
            f"Thank you for your consideration.\n"
        )
        return full, guard.check(full, corpus)

    try:
        revised, flagged = _draft(base_prompt, "default")
        if flagged:
            retry_prompt = (
                f"{base_prompt}\n\nIMPORTANT: your previous draft mentioned terms "
                f"with no evidence in the resume or job description: {flagged}. "
                "Rewrite WITHOUT those terms, using ONLY words that appear "
                "verbatim in the resume or job description above."
            )
            revised, flagged = _draft(retry_prompt, "retry")
    except LLMUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "LLM backend unavailable"
        ) from None
    if flagged:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Revision blocked by fabrication guard: {flagged}",
        )

    stored = CoverLetterRepository().create(
        user_id, letter["jobId"], letter["resumeId"], revised
    )
    approval = ApprovalRepository().create(
        user_id,
        "application_submit",
        {
            "kind": "cover_letter",
            "cover_letter_id": stored["id"],
            "job_id": letter["jobId"],
            "job_title": job["title"],
            "company": job["company"],
            "refined_from": letter["id"],
            "instructions": body.instructions.strip(),
        },
        application_id=stored["id"],
    )
    return {
        "cover_letter_id": stored["id"],
        "cover_letter": revised,
        "approval_id": approval["id"],
        "approval_status": approval["status"],
    }


# --- Branded PDF export (dark glassmorphism letterhead, cl05/cl12) -----------
#: Palette lifted verbatim from the studio wireframe (cover-letter-studio.html).
_PDF_BG = "#0A0A0F"
_PDF_INK = "#F4F4F8"
_PDF_CORAL = "#FF6B35"
_PDF_MUTED = "#6B6B82"

#: The Aether lightning-bolt mark as a normalized (y-up) polygon.
_BOLT = [
    (0.50, 1.00), (0.10, 0.48), (0.38, 0.48),
    (0.22, 0.00), (0.90, 0.52), (0.52, 0.52),
]

#: Vendored fonts live beside the app package so export works off-CDN in CI/prod.
_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


@lru_cache(maxsize=1)
def _pdf_fonts() -> tuple[str, str]:
    """Embed Inter (regular, bold); fall back to Helvetica when unavailable."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular, bold = _FONT_DIR / "Inter-Regular.ttf", _FONT_DIR / "Inter-Bold.ttf"
    try:
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("Inter", str(regular)))
            pdfmetrics.registerFont(TTFont("Inter-Bold", str(bold)))
            return "Inter", "Inter-Bold"
    except Exception:  # pragma: no cover - corrupt font on disk
        pass
    return "Helvetica", "Helvetica-Bold"


def _draw_bolt(page: Any, x: float, y: float, box: float, color: Any) -> None:
    """Fill the Aether bolt inside the coral logo tile anchored at (x, y)."""
    inset = box * 0.30
    span = box - 2 * inset
    path = page.beginPath()
    for i, (px, py) in enumerate(_BOLT):
        point = (x + inset + px * span, y + inset + py * span)
        (path.moveTo if i == 0 else path.lineTo)(*point)
    path.close()
    page.setFillColor(color)
    page.drawPath(path, stroke=0, fill=1)


@router.get("/{letter_id}/pdf")
def export_cover_letter_pdf(letter_id: str, current_user: CurrentUser) -> Response:
    """Render the letter as a branded, dark-theme PDF (Export PDF, cl12)."""
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas

    letter = _load_letter(letter_id, current_user["id"])
    job = JobRepository().get_by_id(letter["jobId"], current_user["id"])
    company = (job or {}).get("company") or "the team"

    regular, bold = _pdf_fonts()
    bg, ink = HexColor(_PDF_BG), HexColor(_PDF_INK)
    coral, muted = HexColor(_PDF_CORAL), HexColor(_PDF_MUTED)

    buf = io.BytesIO()
    page = pdf_canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 25 * mm
    usable = width - 2 * margin
    now = datetime.now()
    date_line = f"{now.day} {now:%B %Y}"

    def _chrome() -> None:
        """Dark page fill + gray generated-by footer, repainted per page."""
        page.setFillColor(bg)
        page.rect(0, 0, width, height, stroke=0, fill=1)
        page.setFillColor(muted)
        page.setFont(regular, 8)
        page.drawCentredString(
            width / 2, 15 * mm, f"Generated by Aether Career Agent | {date_line}"
        )

    y = height - margin

    def _line(text: str, font: str, size: float, color: Any) -> None:
        nonlocal y
        if y < margin + 12 * mm:  # keep clear of the footer band
            page.showPage()
            _chrome()
            y = height - margin
        page.setFillColor(color)
        page.setFont(font, size)
        page.drawString(margin, y, text)
        y -= size * 1.15  # 1.15x line spacing

    def _paragraph(text: str, font: str, size: float, color: Any) -> None:
        buff = ""
        for word in text.split():
            trial = f"{buff} {word}".strip()
            if buff and page.stringWidth(trial, font, size) > usable:
                _line(buff, font, size, color)
                buff = word
            else:
                buff = trial
        if buff:
            _line(buff, font, size, color)

    _chrome()

    # Letterhead — coral logo tile + white bolt + Aether wordmark.
    tile = 9 * mm
    page.setFillColor(coral)
    page.roundRect(margin, y - tile, tile, tile, 2.2 * mm, stroke=0, fill=1)
    _draw_bolt(page, margin, y - tile, tile, white)
    page.setFillColor(ink)
    page.setFont(bold, 15)
    page.drawString(margin + tile + 3.5 * mm, y - tile * 0.46, "Aether")
    page.setFillColor(muted)
    page.setFont(regular, 8)
    page.drawString(margin + tile + 3.5 * mm, y - tile * 0.86, "Career Agent")
    y -= tile + 7 * mm

    # Coral rule, then a right-aligned date line.
    page.setStrokeColor(coral)
    page.setLineWidth(1.2)
    page.line(margin, y, width - margin, y)
    y -= 8 * mm
    page.setFillColor(muted)
    page.setFont(regular, 10)
    page.drawRightString(width - margin, y, date_line)
    y -= 11 * mm

    # Bold salutation, then 11pt body paragraphs.
    raw = (letter["coverLetter"] or "").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if paragraphs and paragraphs[0].lower().startswith("dear"):
        salutation = paragraphs.pop(0)
    else:
        salutation = f"Dear Hiring Team at {company},"
    _paragraph(" ".join(salutation.split()), bold, 12, ink)
    y -= 4 * mm
    for para in paragraphs:
        _paragraph(" ".join(para.split()), regular, 11, ink)
        y -= 5 * mm

    page.save()

    slug = re.sub(r"[^a-z0-9]+", "-", ((job or {}).get("company") or "letter").lower()).strip("-")
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="cover-letter-{slug}.pdf"'
        },
    )
