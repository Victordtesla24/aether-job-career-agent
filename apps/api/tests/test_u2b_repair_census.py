"""U2b round 4 — the repair census must be able to see the damage it repairs.

``scripts/repair_tailored_raw_text.py`` refuses to rewrite a version whose
census reports nothing lost, which is correct: a no-op rewrite churns history
and buries the real repairs. But the census only asked whether the résumé's
text was PRESENT somewhere, and the pre-fix "strip and re-append" corruption
does not delete text — it moves it. Run against the live artifact of record
(résumé ``c12187d107bf994471844e09a``), the census therefore reported
``intact`` while the stored document put all 25 bullets — every job's work — in
a single trailing ``CERTIFICATIONS`` block, left ``WORK EXPERIENCE`` with no
bullets at all and one ``SKILLS`` heading completely empty
(``uat/reports/evidence/agents-uplift/u2b/critical/round4-live-artifact-state-OUTPUT-20260814.json``).

A bullet filed under the wrong employer is not a cosmetic difference: it is the
résumé claiming the person did that work somewhere they did not. It is
therefore a loss, it is named as one, and the repair tool can now actually
repair the artifact it was written for.
"""
from __future__ import annotations

from app.services.resume_document import parse_resume_document
from app.services.resume_repair import raw_text_losses, repair_sections
from app.services.resume_tailor import extract_bullets, strip_bullet_lines

PARENT_TEXT = (
    "PRIYA NARAYANAN\n"
    "WORK EXPERIENCE\n"
    "Delivery Lead\n"
    "Northwind Bank\n"
    "2019 - 2024 | Sydney\n"
    "  • Ran the payments migration to a cloud-native stack.\n"
    "  • Cut release lead time from six weeks to four days.\n"
    "SKILLS\n"
    "  • Python, Terraform, Postgres.\n"
    "CERTIFICATIONS\n"
    "  • Certified Scrum Master.\n"
)

REWRITE = "Ran the payments migration to a cloud-native stack, cutting run cost 30%."


def _parent() -> dict:
    return {
        "id": "parent-1",
        "label": "Priya Narayanan",
        "sections": {
            "raw_text": PARENT_TEXT,
            "bullets": [{"text": t} for t in extract_bullets(PARENT_TEXT)],
        },
    }


def _persisted() -> list[dict]:
    """The tailored bullet set: one rewrite, the rest unchanged."""
    return [
        {"text": REWRITE if t.startswith("Ran the payments") else t}
        for t in extract_bullets(PARENT_TEXT)
    ]


def _damaged_child() -> dict:
    """A child persisted the pre-fix way: strip every bullet, re-append them.

    This is the exact shape ``render_tailored_raw_text`` used to write and that
    the live artifact still stores — the bullets land in one flat block under
    whichever heading happened to be open last.
    """
    bullets = [b["text"] for b in _persisted()]
    raw = strip_bullet_lines(PARENT_TEXT) + "\n" + "\n".join(f"• {t}" for t in bullets)
    return {
        "id": "child-damaged",
        "parentId": "parent-1",
        "sections": {"raw_text": raw, "bullets": _persisted()},
    }


def _headings_of_bullets(record: dict) -> dict[str, str]:
    document = parse_resume_document(record)
    return {
        text: section.heading
        for section in document.sections
        for text in section.bullets
    }


class TestTheCensusSeesMisfiledBullets:
    def test_the_damaged_child_really_does_misfile_its_bullets(self) -> None:
        # The premise, stated as a fact about the fixture rather than assumed:
        # every bullet ends up under the last heading, not its own.
        where = _headings_of_bullets(_damaged_child())
        assert set(where.values()) == {"CERTIFICATIONS"}

    def test_a_misfiled_bullet_is_censused_as_a_loss(self) -> None:
        losses = raw_text_losses(_damaged_child(), _parent())
        assert losses, "the census reported the mutilated document as intact"
        assert any("WORK EXPERIENCE" in item for item in losses)

    def test_the_loss_names_the_bullet_and_both_headings(self) -> None:
        losses = raw_text_losses(_damaged_child(), _parent())
        misfiled = [item for item in losses if "filed under" in item]
        assert misfiled
        assert any("CERTIFICATIONS" in item and "WORK EXPERIENCE" in item for item in misfiled)

    def test_the_repair_puts_every_bullet_back_under_its_own_heading(self) -> None:
        repaired = repair_sections(_damaged_child(), _parent())
        assert repaired is not None
        fixed = {**_damaged_child(), "sections": repaired}
        where = _headings_of_bullets(fixed)
        assert where[REWRITE] == "WORK EXPERIENCE"
        assert where["Cut release lead time from six weeks to four days."] == "WORK EXPERIENCE"
        assert where["Python, Terraform, Postgres."] == "SKILLS"
        assert where["Certified Scrum Master."] == "CERTIFICATIONS"

    def test_the_repair_is_re_censused_clean(self) -> None:
        repaired = repair_sections(_damaged_child(), _parent())
        assert repaired is not None
        assert raw_text_losses({**_damaged_child(), "sections": repaired}, _parent()) == ()

    def test_the_repair_stays_additive(self) -> None:
        original = _damaged_child()
        before = dict(original["sections"])
        repaired = repair_sections(original, _parent())
        assert repaired is not None
        assert original["sections"] == before, "the input record was mutated"
        assert repaired["rawTextRepair"]["previousRawText"] == before["raw_text"]
        assert repaired["bullets"] == before["bullets"]

    def test_an_intact_child_is_still_left_completely_alone(self) -> None:
        # The census must not become so eager that every historical version
        # gets rewritten: a healthy record is still a no-op.
        from app.services.resume_tailor import render_tailored_raw_text

        healthy = {
            "id": "child-healthy",
            "parentId": "parent-1",
            "sections": {
                "raw_text": render_tailored_raw_text(PARENT_TEXT, _persisted()),
                "bullets": _persisted(),
            },
        }
        assert raw_text_losses(healthy, _parent()) == ()
        assert repair_sections(healthy, _parent()) is None
