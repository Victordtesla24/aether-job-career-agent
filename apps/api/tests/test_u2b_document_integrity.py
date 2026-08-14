"""U2b CRITICAL round 3 — the tailored child must LOSE NOTHING of its parent.

Round 2 shipped a whole-document model and a whole-document completeness
contract, and the live artifact was still mutilated
(``uat/reports/evidence/agents-uplift/u2b/critical/REVIEWER-VERDICT-completeness-rerev-round2-sonnet-20260814.md``).
Two defects survived, both upstream of everything round 2 fixed:

1. ``strip_bullet_lines``' ``in_bullet`` latch. A bullet with no terminal
   punctuation (``"• Honors"``) stayed "open" until the next banner, so every
   ordinary line after it — the résumé's ENTIRE second degree, ``Bachelor of
   Engineering / Computer Science / University of Melbourne / 2007`` — was
   consumed as if it were that bullet's wrapped continuation and deleted.
2. ``render_tailored_raw_text``' strip-and-append. It stripped EVERY bullet
   from the whole document and re-appended only the tailoring loop's persisted
   subset as one flat trailing block, so on the live artifact both ``SKILLS``
   sections and ``CERTIFICATIONS`` rendered as bare headings, two skills
   bullets nobody had asked to rewrite were deleted outright, and the surviving
   ones were re-parented under ``WORK EXPERIENCE``.

The verifier could not see any of it, because it measured the tailored child
against the tailored child's own parse: a document that has already lost a
section's bullets has no slot left to report missing. A completeness check that
certifies a lossy record against itself is worthless.

So this module asserts the three contracts those defects broke, on the REAL
live artifact (résumé ``c12187d107bf994471844e09a`` and its parent):

* the latch — a bullet may not swallow lines that are not its own;
* the FULL parent-vs-child diff — every heading, every bullet, every line and
  every contact detail of the PARENT's own parse survives into the child, in
  its own section, with ONLY the tailoring rewrites mapped before → after;
* the completeness contract — built from the PARENT's inventory, so a child
  that lost content is FLAGGED (``complete=False``, naming the losses) instead
  of being certified against its own damage.

``live-tailored-child-corrupted-raw-text.txt`` is the byte-for-byte ``raw_text``
the pre-fix pipeline persisted for that résumé, captured before the fix landed;
it is what the repair path has to be able to recover from.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.repositories.resume import ResumeRepository
from app.routers.resumes import _branded_content
from app.services.format_verification import _normalize
from app.services.resume_completeness import build_resume_content, verify_completeness
from app.services.resume_document import (
    DocSection,
    parse_resume_document,
    rebuild_raw_text,
)
from app.services.resume_pdf import create_branded_resume_pdf
from app.services.resume_repair import raw_text_losses, repair_sections
from app.services.resume_tailor import (
    extract_bullets,
    render_tailored_raw_text,
    strip_bullet_lines,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "u2b"
LIVE_RAW_TEXT = (_FIXTURES / "live-two-column-resume-text.txt").read_text()
LIVE_BULLETS = json.loads((_FIXTURES / "live-persisted-bullets.json").read_text())
#: The ``raw_text`` the pre-fix tailoring pipeline actually persisted for the
#: live tailored child — the corruption this round has to detect and repair.
CORRUPTED_CHILD_RAW_TEXT = (
    _FIXTURES / "live-tailored-child-corrupted-raw-text.txt"
).read_text()

PARENT_ID = "cfe7a0f27991821dc73f265cd"
CHILD_ID = "c12187d107bf994471844e09a"

#: The résumé's two SKILLS bullets that the live corruption emptied out of
#: their section. The first one the tailoring loop DID rewrite (a genuine
#: before → after, overlap 0.5), so what the document owes the user there is
#: the approved rewrite; the second it never touched at all, so what it owes is
#: the user's own words, unchanged. Both were absent from the SKILLS sections
#: of the live download — the first re-parented under WORK EXPERIENCE, the
#: second deleted outright.
REWRITTEN_SKILLS_BULLET_BEFORE = (
    "AI/ML Solutions, LLM Pipelines (LangChain, Langfuse), Python, TypeScript,"
    " React/Next.js, Kubernetes, Docker, Terraform, GCP/AWS, Postgres/Supabase,"
    " Real-Time Telemetry."
)
REWRITTEN_SKILLS_BULLET_AFTER = (
    "Built AI/ML technology solutions including LLM pipelines, real-time"
    " telemetry, and full-stack applications with Python, TypeScript,"
    " React/Next.js, Kubernetes, Docker, Terraform, and cloud infrastructure."
)
NEVER_TAILORED_SKILLS_BULLET = (
    "Technical Program Management, Agile/Scrum/SAFe, Product Ownership,"
    " Roadmap & Backlog Management, Stakeholder Alignment,"
    " Risk & Budget Management ($5M+)."
)
NEVER_TAILORED_CERTIFICATION = "Certified Scrum Master (CSM) Scrum Alliance"
#: Bullets the tailoring loop never proposed a rewrite for: they carry the
#: user's own words and must reach the download untouched.
NEVER_TAILORED_BULLETS = (
    NEVER_TAILORED_SKILLS_BULLET,
    NEVER_TAILORED_CERTIFICATION,
)
#: The second academic entry the latch defect deleted. "Computer Science" is
#: deliberately not asserted as MISSING anywhere: the first degree is a "Master
#: of Computer Science", so that phrase survives on its own and a
#: present/absent check cannot speak to it either way.
SECOND_DEGREE_LINES = (
    "Bachelor of Engineering",
    "Computer Science",
    "University of Melbourne",
)
SECOND_DEGREE_UNIQUE_LINES = ("Bachelor of Engineering", "University of Melbourne")


def _parent_record() -> dict[str, Any]:
    return {
        "id": PARENT_ID,
        "label": "Vikram Deshpande — Senior Technical Program Manager",
        "sections": {
            "raw_text": LIVE_RAW_TEXT,
            "bullets": [{"text": text} for text in extract_bullets(LIVE_RAW_TEXT)],
        },
    }


def _child_record(raw_text: str) -> dict[str, Any]:
    return {
        "id": CHILD_ID,
        "label": "Tailored — Staff Software Engineer @ Canva",
        "parentId": PARENT_ID,
        "sections": {"raw_text": raw_text, "bullets": LIVE_BULLETS},
    }


def _tailored_child() -> dict[str, Any]:
    """The child the FIXED pipeline persists for this parent + these bullets."""
    return _child_record(render_tailored_raw_text(LIVE_RAW_TEXT, LIVE_BULLETS))


def _corrupted_child() -> dict[str, Any]:
    """The child the live system actually holds today."""
    return _child_record(CORRUPTED_CHILD_RAW_TEXT)


def _baseline_child() -> dict[str, Any]:
    """The parent's own document with ONLY the tailoring rewrites mapped in."""
    return {
        "id": CHILD_ID,
        "label": "Vikram Deshpande — Senior Technical Program Manager",
        "sections": {"raw_text": LIVE_RAW_TEXT, "bullets": LIVE_BULLETS},
    }


def _shape(sections: tuple[DocSection, ...]) -> list[tuple[str, tuple[str, ...]]]:
    """``[(heading, ("bullet:…"/"line:…", …)), …]`` — the whole document, in order."""
    return [
        (
            section.heading,
            tuple(f"{item.kind}:{_normalize(item.text)}" for item in section.items),
        )
        for section in sections
    ]


def _render(resume: dict[str, Any]) -> bytes:
    name, title, objective, sections, contact = _branded_content(resume)
    return create_branded_resume_pdf(
        name, title, objective, sections, None, contact=contact
    )


class TestTheBulletLatch:
    """A bullet may only consume its OWN wrapped continuation lines."""

    def test_a_short_bullet_does_not_delete_the_lines_after_it(self) -> None:
        # "• Honors" carries no terminal punctuation. The entire second degree
        # follows it as ordinary EDUCATION lines and must survive.
        kept = strip_bullet_lines(LIVE_RAW_TEXT)
        for line in SECOND_DEGREE_LINES + ("2007",):
            assert line in kept, f"{line!r} deleted by the bullet latch"

    def test_the_second_degree_is_education_prose_not_bullet_text(self) -> None:
        education = [
            section
            for section in parse_resume_document(_parent_record()).sections
            if section.heading == "EDUCATION"
        ]
        assert len(education) == 1
        lines = " ".join(education[0].lines)
        for line in SECOND_DEGREE_LINES:
            assert line in lines, f"{line!r} is not an EDUCATION line: {lines!r}"
        assert education[0].bullets == ("Honors",)

    def test_an_indented_wrapped_bullet_is_still_rejoined_whole(self) -> None:
        # The live layout's own signal: a continuation is printed INSIDE the
        # bullet's text column. Rejoining it is the GAP-P4-044 behaviour and
        # must not regress.
        raw = (
            "EDUCATION\n"
            "Master of Science\n"
            "• Led the migration of the billing platform to a\n"
            "  cloud-native stack, cutting run cost by 30%.\n"
            "Bachelor of Engineering\n"
        )
        assert extract_bullets(raw) == [
            "Led the migration of the billing platform to a cloud-native stack,"
            " cutting run cost by 30%."
        ]
        assert "Bachelor of Engineering" in strip_bullet_lines(raw)

    def test_a_flat_text_layer_keeps_joining_its_wrapped_bullets(self) -> None:
        # A text layer with no indentation at all carries no column signal, so
        # the walk keeps its existing boundaries there — the bundled résumés
        # are extracted exactly like this.
        raw = (
            "WORK EXPERIENCE\n"
            "• Led the migration of the billing platform to a\n"
            "cloud-native stack, cutting run cost by 30%.\n"
        )
        assert extract_bullets(raw) == [
            "Led the migration of the billing platform to a cloud-native stack,"
            " cutting run cost by 30%."
        ]


class TestTheFullParentChildDiff:
    """Every line of the parent's OWN parse, in its own section, in the child."""

    def test_the_child_document_equals_the_parents_with_rewrites_mapped(self) -> None:
        expected = parse_resume_document(_baseline_child())
        actual = parse_resume_document(_tailored_child())
        assert _shape(actual.sections) == _shape(expected.sections)

    def test_the_rewrite_map_only_changes_bullets_the_loop_rewrote(self) -> None:
        parent = parse_resume_document(_parent_record())
        mapped = parse_resume_document(_baseline_child())
        assert _shape(mapped.sections) != _shape(parent.sections)
        persisted = {_normalize(b["text"]) for b in LIVE_BULLETS}
        original = {_normalize(text) for text in parent.bullets}
        for section, before in zip(mapped.sections, parent.sections, strict=True):
            assert section.heading == before.heading
            assert section.lines == before.lines
            for text in section.bullets:
                assert _normalize(text) in persisted | original

    def test_no_bullet_moves_to_another_heading(self) -> None:
        parent = parse_resume_document(_parent_record())
        child = parse_resume_document(_tailored_child())
        headings = {
            _normalize(text): section.heading
            for section in child.sections
            for text in section.bullets
        }
        for section in parent.sections:
            for text in section.bullets:
                key = _normalize(text)
                if key in headings:
                    assert headings[key] == section.heading, (
                        f"{text[:60]!r} moved from {section.heading!r} to"
                        f" {headings[key]!r}"
                    )

    def test_the_skills_and_certifications_sections_keep_their_items(self) -> None:
        child = parse_resume_document(_tailored_child())
        filled = [
            section
            for section in child.sections
            if section.heading in ("SKILLS", "CERTIFICATIONS")
        ]
        assert len(filled) == 3, [s.heading for s in filled]
        for section in filled:
            assert section.bullets, f"{section.heading} rendered as a bare heading"
        every = _normalize(" ".join(text for s in filled for text in s.bullets))
        for bullet in (
            REWRITTEN_SKILLS_BULLET_AFTER,
            NEVER_TAILORED_SKILLS_BULLET,
            NEVER_TAILORED_CERTIFICATION,
        ):
            assert _normalize(bullet) in every, f"{bullet[:50]!r} lost from its section"
        # The rewrite replaced the original in place — it did not join it.
        assert _normalize(REWRITTEN_SKILLS_BULLET_BEFORE) not in every

    def test_the_regenerated_raw_text_reparses_to_itself(self) -> None:
        once = rebuild_raw_text(LIVE_RAW_TEXT, [b["text"] for b in LIVE_BULLETS])
        twice = rebuild_raw_text(once, [b["text"] for b in LIVE_BULLETS])
        assert _shape(parse_resume_document(_child_record(twice)).sections) == _shape(
            parse_resume_document(_child_record(once)).sections
        )


class TestTheCompletenessContractIsTheParents:
    """Ground truth is the PARENT's inventory — never the damaged child's."""

    def test_the_contract_carries_the_parents_whole_inventory(self) -> None:
        # Built from the CORRUPTED child — whose own parse holds none of this.
        content = build_resume_content(_corrupted_child(), _parent_record())
        every = _normalize(" ".join(content.bullets))
        for bullet in (REWRITTEN_SKILLS_BULLET_AFTER,) + NEVER_TAILORED_BULLETS:
            assert _normalize(bullet) in every, f"{bullet[:50]!r} absent from contract"
        lines = _normalize(" ".join(content.lines))
        for line in SECOND_DEGREE_LINES:
            assert _normalize(line) in lines, f"{line!r} absent from contract"
        assert content.headings.count("SKILLS") == 2
        assert "CERTIFICATIONS" in content.headings

    def test_the_live_corruption_is_flagged_not_certified(self) -> None:
        child, parent = _corrupted_child(), _parent_record()
        result = verify_completeness(
            _render(child), "application/pdf", build_resume_content(child, parent)
        )
        assert result.complete is False
        named = _normalize(" ".join(result.missing))
        for bullet in NEVER_TAILORED_BULLETS:
            assert _normalize(bullet)[:60] in named, f"{bullet[:50]!r} loss unreported"
        for line in SECOND_DEGREE_UNIQUE_LINES:
            assert _normalize(line) in named, f"{line!r} loss unreported"

    def test_the_fixed_pipeline_produces_a_complete_document(self) -> None:
        child, parent = _tailored_child(), _parent_record()
        result = verify_completeness(
            _render(child), "application/pdf", build_resume_content(child, parent)
        )
        assert result.missing == ()
        assert result.complete is True

    def test_a_baseline_resume_without_a_parent_is_measured_against_itself(
        self,
    ) -> None:
        parent = _parent_record()
        result = verify_completeness(
            _render(parent), "application/pdf", build_resume_content(parent)
        )
        assert result.missing == ()


class TestTheDataRepair:
    """Existing damaged children are regenerated — recoverably, never wiped."""

    def test_the_live_child_is_censused_as_damaged(self) -> None:
        losses = raw_text_losses(_corrupted_child(), _parent_record())
        assert losses
        named = _normalize(" ".join(losses))
        for bullet in NEVER_TAILORED_BULLETS:
            assert _normalize(bullet)[:60] in named
        for line in SECOND_DEGREE_UNIQUE_LINES:
            assert _normalize(line) in named

    def test_a_healthy_child_needs_no_repair(self) -> None:
        assert raw_text_losses(_tailored_child(), _parent_record()) == ()
        assert repair_sections(_tailored_child(), _parent_record()) is None

    def test_repair_keeps_the_damaged_value_recoverable(self) -> None:
        repaired = repair_sections(_corrupted_child(), _parent_record())
        assert repaired is not None
        note = repaired["rawTextRepair"]
        assert note["previousRawText"] == CORRUPTED_CHILD_RAW_TEXT
        assert note["repairedAt"]
        assert note["lost"]
        assert repaired["bullets"] == LIVE_BULLETS
        assert repaired["raw_text"] != CORRUPTED_CHILD_RAW_TEXT

    def test_the_repaired_live_child_verifies_complete_against_its_parent(
        self,
    ) -> None:
        parent = _parent_record()
        repaired = repair_sections(_corrupted_child(), parent)
        assert repaired is not None
        child = {**_corrupted_child(), "sections": repaired}
        result = verify_completeness(
            _render(child), "application/pdf", build_resume_content(child, parent)
        )
        assert result.missing == ()
        assert result.complete is True
        assert raw_text_losses(child, parent) == ()

    def test_the_repair_survives_a_round_trip_through_the_database(
        self, client, auth_headers, test_user_id
    ) -> None:
        """The stored rows, not just the in-memory dicts (U2b round-3 item 5)."""
        repo = ResumeRepository()
        parent = repo.create(
            test_user_id,
            _parent_record()["sections"],
            "u2b-round3-parent",
            label="Vikram Deshpande — Senior Technical Program Manager",
        )
        child = repo.create(
            test_user_id,
            {"raw_text": CORRUPTED_CHILD_RAW_TEXT, "bullets": LIVE_BULLETS},
            "u2b-round3-child",
            label="Tailored — Staff Software Engineer @ Canva",
            version=2,
            parent_id=parent["id"],
        )
        stored_child = repo.get_by_id(child["id"], test_user_id)
        stored_parent = repo.get_by_id(parent["id"], test_user_id)
        assert stored_child is not None and stored_parent is not None
        assert raw_text_losses(stored_child, stored_parent)

        repaired = repair_sections(stored_child, stored_parent)
        assert repaired is not None
        written = repo.update_sections(
            child["id"], test_user_id, repaired, stored_child["formatHash"]
        )
        assert written is not None
        assert raw_text_losses(written, stored_parent) == ()
        # The damaged text is still recoverable from the stored row itself.
        assert (
            written["sections"]["rawTextRepair"]["previousRawText"]
            == CORRUPTED_CHILD_RAW_TEXT
        )
        result = verify_completeness(
            _render(written),
            "application/pdf",
            build_resume_content(written, stored_parent),
        )
        assert result.missing == ()
        assert result.complete is True
