"""GAP-P5-PDF (§11.2) — two-column resume bullets extract as COMPLETE units.

A live writer-audit found the base resume's *stored* bullets were truncated /
corrupted because ``Vik_Resume_Final.pdf`` is a two-column layout: the main work
column wraps each bullet across several visual lines while a left sidebar
(Skills / Education / Certifications) is interleaved between them in the flat
text stream. Two concrete defects fed the tailoring model broken fragments:

1.  **Soft-hyphen corruption.** A bullet that wraps at a hyphenated compound —
    ``COBOL/mainframe test-\nevidence`` — was rejoined by the positional
    extractor as ``test- evidence`` (a stray space), not ``test-evidence``.
    Same for ``re-baselining`` and ``on-time``. The audit cited these verbatim.

2.  **Stale stored bullets never heal.** ``ensure_base_resume`` only re-derived
    bullets when ``raw_text`` was *missing*, so a base persisted with the legacy
    line-based fragments (each bullet truncated to its first visual line, with
    sidebar Skills lines merged in) kept serving those fragments forever.

The ``raw_text`` field always held the full correct sentences, and the
column-aware positional detector already de-interleaves the two columns — it
just mis-joined the hyphen breaks. This suite pins both the extractor's
completeness and heal-on-read, and asserts the format hash is untouched.
"""
from __future__ import annotations

import re

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_parser import compute_format_hash, parse_resume_pdf
from app.services.resume_pdf import extract_pdf_bullets

# SHA-256 of the read-only bundled base PDF — its format identity. The bullet
# fix must NOT touch the source file, so this value is immutable.
EXPECTED_FORMAT_HASH = (
    "0700d1aa1a48de5dc9ca308968ff5a6049b2b0ea38adac5550353279b0768a25"
)

_TERMINAL = (".", "!", "?", ":")
_TRAIL = ")\"']"


def _work_fragments(bullets: list[str]) -> list[str]:
    """Work-experience bullets that end mid-sentence (truncated fragments).

    A work bullet opens with a bold lead-in ("Agile Delivery Leadership:") and
    must close with terminal punctuation. Sidebar skills / certification lines
    legitimately lack a period, so a bullet is only counted as a *truncated*
    fragment when it starts like a work bullet yet ends without one.
    """
    return [
        b
        for b in bullets
        if ":" in b[:60] and not b.rstrip().rstrip(_TRAIL).endswith(_TERMINAL)
    ]


class TestPositionalBulletCompleteness:
    def test_source_pdf_and_format_hash_untouched(self) -> None:
        """The fix changes only extracted TEXT — never the source bytes/hash."""
        assert compute_format_hash(get_base_resume_path()) == EXPECTED_FORMAT_HASH

    def test_no_bullet_truncated_mid_sentence(self) -> None:
        bullets = extract_pdf_bullets(get_base_resume_path())
        assert bullets, "expected work bullets from the bundled base resume"
        frags = _work_fragments(bullets)
        assert not frags, f"truncated work bullets: {frags}"

    def test_soft_hyphen_breaks_rejoined_without_stray_space(self) -> None:
        """``test-\\nevidence`` must become ``test-evidence``, not ``test- evidence``.

        These three compounds are the exact corruptions the writer-audit cited.
        A ``word- word`` sequence (letter, hyphen, space, letter) is the
        signature of a mis-joined hyphenated line break.
        """
        bullets = extract_pdf_bullets(get_base_resume_path())
        joined = "\n".join(bullets)
        assert "test-evidence" in joined
        assert "re-baselining" in joined
        assert "deliver on-time" in joined
        stray = [b for b in bullets if re.search(r"[A-Za-z]- [A-Za-z]", b)]
        assert not stray, f"stray-space hyphen breaks: {stray}"

    def test_first_bullet_is_the_complete_sentence(self) -> None:
        """The lead work bullet the audit saw truncated at "...Agile Kookaburras"
        is now the full sentence through its terminal period."""
        bullets = extract_pdf_bullets(get_base_resume_path())
        lead = next(
            (b for b in bullets if b.startswith("Agile Delivery Leadership:")), None
        )
        assert lead is not None, "lead work bullet missing"
        assert lead.rstrip().endswith("executive status reporting.")

    def test_sidebar_lines_not_merged_into_work_bullets(self) -> None:
        """Left-rail Skills / Education / Certification content must never leak
        into the work-experience bullet list (the column filter must hold)."""
        bullets = extract_pdf_bullets(get_base_resume_path())
        joined = "\n".join(bullets)
        for sidebar in (
            "LLM Pipelines (LangChain",
            "Certified Scrum Master",
            "Cloud/Data Certifications",
            "Master of Computer Science",
            "Monash University",
            "University of Melbourne",
        ):
            assert sidebar not in joined, f"sidebar content merged into bullets: {sidebar!r}"


class TestHealOnRead:
    def test_ensure_base_resume_heals_truncated_stored_bullets(
        self, client, auth_headers, test_user_id
    ) -> None:
        """A base persisted with legacy truncated fragments (but with raw_text
        present, so the old heal gate skipped it) is repaired on read into
        complete bullets, with the format hash preserved and un-rewritten."""
        from app.agents.tailor_agent import TailoringAgent
        from app.repositories.resume import ResumeRepository

        repo = ResumeRepository()
        raw_text = parse_resume_pdf(get_base_resume_path())["raw_text"]
        # Legacy shape: first-visual-line fragments + a leaked sidebar line.
        truncated = [
            {
                "text": "Agile Delivery Leadership: Lead end-to-end delivery for the Agile Kookaburras",
                "evidenceRef": "bullet-0",
            },
            {
                "text": "AI/ML Solutions, LLM Pipelines (LangChain, Langfuse), Python,",
                "evidenceRef": "bullet-1",
            },
        ]
        seeded = repo.create(
            test_user_id,
            {"raw_text": raw_text, "bullets": truncated, "contact": {}},
            EXPECTED_FORMAT_HASH,
            label="Base resume",
            version=1,
        )

        healed = TailoringAgent().ensure_base_resume(test_user_id)

        assert healed["id"] == seeded["id"], "heal must update in place, not fork"
        bullets = [b["text"] for b in healed["sections"]["bullets"]]
        assert not _work_fragments(bullets), f"still truncated after heal: {bullets}"
        assert any(
            b.startswith("Agile Delivery Leadership:")
            and b.rstrip().endswith("executive status reporting.")
            for b in bullets
        ), "lead bullet not restored to its complete sentence"
        assert not any(
            "LLM Pipelines (LangChain" in b for b in bullets
        ), "sidebar skills line still present after heal"
        # Format identity is carried through unchanged.
        assert healed["formatHash"] == EXPECTED_FORMAT_HASH

    def test_healthy_base_is_not_reforked_on_read(
        self, client, auth_headers, test_user_id
    ) -> None:
        """A base already holding complete bullets is returned untouched — heal
        must be idempotent and must not fabricate a second base row."""
        from app.agents.tailor_agent import TailoringAgent
        from app.repositories.resume import ResumeRepository

        agent = TailoringAgent()
        first = agent.ensure_base_resume(test_user_id)
        again = agent.ensure_base_resume(test_user_id)
        assert first["id"] == again["id"]
        repo = ResumeRepository()
        bases = [
            r for r in repo.list_by_user(test_user_id) if r.get("parentId") is None
        ]
        assert len(bases) == 1, f"heal forked extra base rows: {len(bases)}"
        assert not _work_fragments(
            [b["text"] for b in again["sections"]["bullets"]]
        )
