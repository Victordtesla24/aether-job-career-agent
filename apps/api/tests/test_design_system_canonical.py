"""The Claude Aether Career Design System is the default for every artefact.

These tests pin the contract so a later coral/indigo revival, a missing agent
skill, or a wireframe that still paints `#FF6B35` fails the suite instead of
quietly drifting the brand.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DS = REPO / "design" / "aether-design-system"
FORBIDDEN_HEX = ("#FF6B35", "#ff6b35", "#4F46E5", "#4f46e5")
GILT = "#C9A84C"
INK = "#08080A"


class TestDesignSystemVendored:
    def test_skill_and_tokens_exist(self) -> None:
        assert (DS / "SKILL.md").is_file()
        assert (DS / "readme.md").is_file()
        colors = (DS / "tokens" / "colors.css").read_text()
        assert GILT in colors
        assert INK in colors
        for hex_ in FORBIDDEN_HEX:
            assert hex_ not in colors

    def test_archive_zip_is_present(self) -> None:
        assert (DS / "Aether-Design-System.zip").is_file()


class TestAgentInstructionsMandateTheSystem:
    def test_root_agent_guides_point_at_the_vendored_system(self) -> None:
        for rel in ("AGENTS.md", "CLAUDE.md"):
            text = (REPO / rel).read_text()
            assert "aether-design-system" in text
            assert "gilt" in text.lower() or GILT in text

    def test_cursor_rule_is_always_on(self) -> None:
        rule = (REPO / ".cursor" / "rules" / "aether-design-system.mdc").read_text()
        assert "alwaysApply: true" in rule
        assert "aether-design-system" in rule

    def test_claude_skill_exists(self) -> None:
        skill = REPO / ".claude" / "skills" / "aether-career-agent-design" / "SKILL.md"
        assert skill.is_file()
        text = skill.read_text()
        assert "aether-design-system" in text


class TestCanonicalDocsDropLegacyCoral:
    def test_design_md_is_obsidian_and_gilt(self) -> None:
        text = (REPO / "design" / "DESIGN.md").read_text()
        for hex_ in FORBIDDEN_HEX:
            assert hex_ not in text, f"design/DESIGN.md still carries {hex_}"
        assert GILT in text
        assert INK in text

    def test_readme_does_not_advertise_coral_or_indigo(self) -> None:
        text = (REPO / "README.md").read_text()
        for hex_ in FORBIDDEN_HEX:
            assert hex_ not in text, f"README.md still advertises {hex_}"
        assert "aether-design-system" in text

    def test_wireframes_do_not_use_legacy_coral_indigo(self) -> None:
        offenders: list[str] = []
        for path in (REPO / "design" / "screens").glob("*.html"):
            text = path.read_text()
            for hex_ in FORBIDDEN_HEX:
                if hex_ in text:
                    offenders.append(f"{path.name}:{hex_}")
        assert offenders == []


class TestBrandedMarkdownArtefact:
    def test_wrapper_uses_gilt_chrome_and_escapes_body(self) -> None:
        from app.services.branded_artefacts import render_branded_markdown_html

        html = render_branded_markdown_html(
            "Agent run report",
            "First paragraph.\n\n<script>alert(1)</script>",
        )
        lowered = html.lower()
        assert lowered.lstrip().startswith("<!doctype html>")
        assert GILT.lower() in lowered
        assert INK.lower() in lowered
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "Agent run report" in html
        assert "First paragraph." in html
        for hex_ in FORBIDDEN_HEX:
            assert hex_ not in html
