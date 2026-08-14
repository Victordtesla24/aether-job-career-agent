"""U2b round 4 — ONE bullet-boundary walk, and it holds for FLAT text layers.

Round 3 closed the ``in_bullet`` latch (an unpunctuated bullet swallowing every
following line up to the next banner) only where the PDF text layer preserved
the column each line starts in. The platform's own two bundled seed résumés
extract as 100% FLAT text through the exact call production ingests with
(``routers/resumes.py`` → ``page.get_text()``), so they received none of that
protection: ``• Honors`` still swallowed an entire second degree, and
``verify_completeness`` reported ``complete=True`` in BOTH modes — self-measured
AND measured against a parent — because the same buggy parse produced the
"expected" and the "actual" side
(``uat/reports/evidence/agents-uplift/u2b/critical/REVIEWER-VERDICT-completeness-round3-sonnet-20260814.md``,
Finding 1).

The same review's Finding 2: ``extract_bullets``, ``strip_bullet_lines`` and
``resume_document._parse_sections`` were three independently hand-written
state machines that had to agree. Round 3's boundary was hand-added to all
three, and the flat-text case was, by the same token, hand-omitted from all
three. They are now ONE walk — :func:`app.services.resume_tailor.walk_blocks` —
and the tests in :class:`TestOneBulletBoundaryWalk` fail if a second one is
ever written.
"""
from __future__ import annotations

import inspect

import fitz
import pytest

from app.agents.fit_scorer import get_base_resume_path
from app.routers.resumes import _branded_content
from app.services import resume_document, resume_tailor
from app.services.format_verification import extract_artifact_text
from app.services.resume_completeness import build_resume_content, verify_completeness
from app.services.resume_document import parse_resume_document
from app.services.resume_pdf import create_branded_resume_pdf
from app.services.resume_tailor import (
    extract_bullets,
    marks_wrapping_by_indent,
    reading_order,
    render_tailored_raw_text,
    strip_bullet_lines,
    walk_blocks,
)

#: A FLAT single-column résumé: no leading whitespace on any line, which is
#: what ``page.get_text()`` returns for most single-column PDFs and for BOTH
#: bundled seed résumés. ``• Honors`` carries no terminal punctuation, and the
#: whole second degree follows it as ordinary prose.
FLAT_RESUME = (
    "JORDAN OKONKWO\n"
    "EDUCATION\n"
    "Master of Data Science\n"
    "Curtin University\n"
    "2015 Perth\n"
    "• Honors\n"
    "Bachelor of Information Technology\n"
    "Curtin University\n"
    "2011 Perth\n"
    "SKILLS\n"
    "• Python, SQL, Airflow.\n"
)

SECOND_DEGREE = "Bachelor of Information Technology"

_MAIN_PDF = get_base_resume_path()
_BA_PDF = _MAIN_PDF.parent / "Vik_Resume_BA_Final.pdf"


def _pdf_text(path) -> str:
    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _record(raw: str, ident: str, parent: str | None = None) -> dict:
    record = {
        "id": ident,
        "label": "Jordan Okonkwo",
        "sections": {
            "raw_text": raw,
            "bullets": [{"text": text} for text in extract_bullets(raw)],
        },
    }
    if parent:
        record["parentId"] = parent
    return record


def _render(record: dict) -> bytes:
    name, title, objective, sections, contact = _branded_content(record)
    return create_branded_resume_pdf(
        name, title, objective, sections, None, contact=contact
    )


class TestTheFlatTextLatch:
    """A bullet with no terminal punctuation on a text layer with no columns."""

    def test_the_bundled_seed_resumes_really_are_flat(self) -> None:
        # Everything below matters only because this is the shape production
        # actually ingests. If a future extraction change makes these documents
        # column-aware, this assertion is the first thing that should say so.
        for pdf in (_MAIN_PDF, _BA_PDF):
            _lines, indents = reading_order(_pdf_text(pdf))
            assert not marks_wrapping_by_indent(indents), (
                f"{pdf.name} is no longer a flat text layer"
            )
        _lines, indents = reading_order(FLAT_RESUME)
        assert not marks_wrapping_by_indent(indents)

    def test_an_unpunctuated_bullet_does_not_swallow_the_next_degree(self) -> None:
        assert extract_bullets(FLAT_RESUME) == ["Honors", "Python, SQL, Airflow."]

    def test_the_stripped_skeleton_still_holds_every_education_line(self) -> None:
        stripped = strip_bullet_lines(FLAT_RESUME)
        assert SECOND_DEGREE in stripped
        assert stripped.count("Curtin University") == 2
        assert "2011 Perth" in stripped

    def test_the_document_model_keeps_the_degree_as_its_own_lines(self) -> None:
        document = parse_resume_document(_record(FLAT_RESUME, "flat-baseline"))
        education = [s for s in document.sections if s.heading == "EDUCATION"]
        assert len(education) == 1
        assert education[0].bullets == ("Honors",)
        for line in (SECOND_DEGREE, "Curtin University", "2011 Perth"):
            assert line in education[0].lines, f"{line!r} lost from EDUCATION"

    def test_the_rendered_pdf_prints_the_degree_outside_the_bullet(self) -> None:
        # What the subscriber actually sends an employer. The degree must be
        # its own line of the document, not words inside a "Honors" bullet.
        artifact = _render(_record(FLAT_RESUME, "flat"))
        printed = (extract_artifact_text(artifact, "application/pdf") or "").splitlines()
        assert SECOND_DEGREE in [line.strip() for line in printed]
        for line in printed:
            assert not ("Honors" in line and "Bachelor" in line), (
                f"the degree is printed inside the bullet: {line!r}"
            )

    def test_a_tailored_child_of_a_flat_parent_keeps_the_whole_document(self) -> None:
        # The round-3 headline mechanism (measure the child against its PARENT)
        # on a flat parent: the regenerated raw_text must still carry every
        # education line, and completeness must be able to say so honestly.
        parent = _record(FLAT_RESUME, "flat-parent")
        tailored = render_tailored_raw_text(
            FLAT_RESUME, [{"text": text} for text in extract_bullets(FLAT_RESUME)]
        )
        assert SECOND_DEGREE in tailored
        child = _record(tailored, "flat-child", parent="flat-parent")
        result = verify_completeness(
            _render(child), "application/pdf", build_resume_content(child, parent)
        )
        assert result.complete, f"missing: {result.missing} {result.missing_lines}"

    def test_completeness_can_now_see_a_flat_document_losing_that_degree(self) -> None:
        # The blind spot Finding 1 named: before this fix BOTH sides of the
        # comparison came from the same buggy parse, so a child that had
        # already lost the degree still verified complete=True. It must now be
        # reported missing.
        parent = _record(FLAT_RESUME, "flat-parent")
        damaged = FLAT_RESUME.replace(f"{SECOND_DEGREE}\n", "")
        child = _record(damaged, "flat-child", parent="flat-parent")
        result = verify_completeness(
            _render(child), "application/pdf", build_resume_content(child, parent)
        )
        assert not result.complete
        assert any(SECOND_DEGREE in item for item in result.missing_lines)

    def test_a_flat_wrapped_bullet_is_still_rejoined_whole(self) -> None:
        # GAP-P4-044 must not regress: with no column signal, a genuine wrapped
        # continuation still belongs to its bullet.
        raw = (
            "WORK EXPERIENCE\n"
            "• Led the migration of the billing platform to a\n"
            "cloud-native stack, cutting run cost by 30%.\n"
        )
        assert extract_bullets(raw) == [
            "Led the migration of the billing platform to a cloud-native stack,"
            " cutting run cost by 30%."
        ]

    def test_a_marker_alone_on_its_line_still_owns_the_lines_below_it(self) -> None:
        # Both bundled résumés print the marker on its own line and the bullet's
        # text underneath; the first line under such a marker is the bullet's
        # own first line, never a wrap of anything.
        raw = (
            "SKILLS\n"
            "•\n"
            "AI/ML Solutions, LLM Pipelines\n"
            "(LangChain, Langfuse), Python,\n"
            "Real-Time Telemetry.\n"
        )
        assert extract_bullets(raw) == [
            "AI/ML Solutions, LLM Pipelines (LangChain, Langfuse), Python,"
            " Real-Time Telemetry."
        ]

    @pytest.mark.parametrize("pdf", [_MAIN_PDF, _BA_PDF], ids=lambda p: p.name)
    def test_the_bundled_resumes_reconstruct_the_same_bullets_as_before(self, pdf) -> None:
        # Real-data regression guard for the new flat boundary: the seed
        # résumés' 25 bullets, including the four-line wrapped Agile bullet,
        # must come back exactly as they did before this round.
        bullets = extract_bullets(_pdf_text(pdf))
        assert len(bullets) == 25
        agile = [b for b in bullets if b.startswith("Agile Delivery Leadership")]
        assert len(agile) == 1
        assert agile[0].rstrip().endswith("executive status reporting.")


class TestOneBulletBoundaryWalk:
    """Three call sites, one state machine — Finding 2."""

    CORPUS = (
        FLAT_RESUME,
        _pdf_text(_MAIN_PDF),
        _pdf_text(_BA_PDF),
        # Column-aware: the round-3 shape, whose boundary is the printed column.
        "EDUCATION\n"
        "Master of Science\n"
        "• Honors\n"
        "Bachelor of Engineering\n"
        "University of Melbourne\n"
        "SKILLS\n"
        "• Led the migration of the billing platform to a\n"
        "  cloud-native stack, cutting run cost by 30%.\n",
        # A bullet that ends on its marker line, then unrelated prose.
        "CERTIFICATIONS\n• Certified Scrum Master.\nAWS Solutions Architect\n",
        # Nothing but prose.
        "PROFILE\nA delivery lead with fifteen years in banking.\n",
    )

    def test_the_three_call_sites_share_one_walk(self) -> None:
        # The structural guarantee, not just a behavioural one: a future
        # boundary change edited into one of these cannot be forgotten in the
        # other two, because there is nothing to forget.
        for func in (
            resume_tailor.extract_bullets,
            resume_tailor.strip_bullet_lines,
            resume_document._parse_sections,
        ):
            source = inspect.getsource(func)
            body = source.split('"""')[-1]
            assert "walk_blocks(" in body, f"{func.__qualname__} does not use the walk"
            for latch in ("_ends_bullet(", "_is_bullet_marker(", "_job_header_indices("):
                assert latch not in body, (
                    f"{func.__qualname__} re-implements the bullet boundary ({latch})"
                )

    @pytest.mark.parametrize("raw", CORPUS, ids=range(len(CORPUS)))
    def test_every_line_lands_in_exactly_one_place(self, raw: str) -> None:
        # The invariant the three walks exist to keep: every non-empty line of
        # the résumé is either kept as prose or folded into exactly one bullet.
        # Nothing is dropped, nothing is drawn twice.
        lines, _indents = reading_order(raw)
        kept = strip_bullet_lines(raw).splitlines()
        bullets = extract_bullets(raw)
        joined = " ".join(kept) + " " + " ".join(bullets)
        for line in lines:
            if not line or resume_tailor._is_bullet_marker(line):
                continue
            assert line.replace("-\n", "") in joined or line in joined, (
                f"{line!r} is in neither the stripped prose nor any bullet"
            )

    @pytest.mark.parametrize("raw", CORPUS, ids=range(len(CORPUS)))
    def test_the_document_model_agrees_with_the_ingestion_walk(self, raw: str) -> None:
        document = parse_resume_document(_record(raw, "corpus"))
        assert list(document.bullets) == extract_bullets(raw)

    @pytest.mark.parametrize("raw", CORPUS, ids=range(len(CORPUS)))
    def test_the_walk_partitions_the_document_it_walked(self, raw: str) -> None:
        lines, indents = reading_order(raw)
        blocks = walk_blocks(lines, indents)
        prose = [b.text for b in blocks if b.kind == "line"]
        assert prose == strip_bullet_lines(raw).splitlines()
        assert [b.text for b in blocks if b.kind == "bullet"] == extract_bullets(raw)
