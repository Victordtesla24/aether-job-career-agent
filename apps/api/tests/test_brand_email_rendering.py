"""``app/services/email_branding.py`` — the canonical Aether email template.

Owner directive (2026-08-16): every Aether-OWNED email carries the obsidian +
gilt brand. These tests pin the *bulletproof-email* rules that make that
directive survivable in real mail clients, and the honesty rule that the
plain-text alternative is never a stub:

* the exact brand tokens from ``apps/web/src/app/globals.css`` are the ones
  rendered (a drifted hex is a brand break, not a nit);
* EVERY style is inline — no ``<style>``/``<link>``/``<script>`` and no
  external asset of any kind (images, webfonts, tracking pixels). Gmail and
  Outlook strip the first three; the rest turn a branded email into a
  privacy leak or a broken-image box;
* the hidden preheader exists (it is what the inbox list preview shows);
* the plain-text part carries EVERY value the HTML shows — a recipient whose
  client refuses HTML must lose zero information.
"""
from __future__ import annotations

import re

import pytest

from app.services import email_branding as eb


# --------------------------------------------------------------- palette
class TestPalette:
    def test_palette_matches_the_web_design_tokens(self):
        """These five values are copied from globals.css / tailwind.config.ts."""
        assert eb.PALETTE["gold"] == "#c9a84c"
        assert eb.PALETTE["goldLight"] == "#d4b65c"
        assert eb.PALETTE["goldPale"] == "#e8d5a3"
        assert eb.PALETTE["goldDark"] == "#b0923f"
        assert eb.PALETTE["goldBorder"] == "rgba(201,168,76,0.2)"

    def test_palette_inks_match_the_web_design_tokens(self):
        assert eb.PALETTE["ink0"] == "#08080a"
        assert eb.PALETTE["ink1"] == "#0f0f12"
        assert eb.PALETTE["ink2"] == "#16161a"


@pytest.fixture
def rendered():
    html, text = eb.render_branded_email(
        "Daily digest",
        [
            eb.paragraph("Here is where the numbers landed today."),
            eb.stats(
                [
                    ("Mode", "LIVE"),
                    ("Signups", "42"),
                    ("Reply rate", "not observable (no real sends yet)"),
                ]
            ),
            eb.divider(),
            eb.paragraph("Every number above is a live database query."),
        ],
        cta={"label": "Open the dashboard", "url": "https://5cb5f0620.abacusai.cloud/admin"},
        footer_note="You receive this because you are the Aether account owner.",
        preheader="42 signups today",
    )
    return html, text


# ------------------------------------------------------ bulletproof HTML
class TestBulletproofHtml:
    def test_returns_html_and_plain_text(self, rendered):
        html, text = rendered
        assert isinstance(html, str) and isinstance(text, str)
        assert html.lstrip().lower().startswith("<!doctype html>")
        assert "<" not in text, "the text part must not be HTML"

    def test_brand_colors_are_present_in_the_html(self, rendered):
        html, _ = rendered
        lowered = html.lower()
        assert eb.PALETTE["gold"] in lowered
        assert eb.PALETTE["ink0"] in lowered
        assert eb.PALETTE["ink1"] in lowered

    def test_no_style_link_or_script_elements(self, rendered):
        html, _ = rendered
        lowered = html.lower()
        assert "<link" not in lowered, "email clients strip <link>; styles must be inline"
        assert "<script" not in lowered, "scripts never run in email and trip spam filters"
        assert "<style" not in lowered, "Gmail strips <style> in forwarded/clipped mail"

    def test_no_external_assets_at_all(self, rendered):
        """No images (so no broken-image boxes and no tracking pixel), and no
        webfont/CSS fetch — the only http(s) URLs allowed are ones a human
        clicks."""
        html, _ = rendered
        lowered = html.lower()
        assert "<img" not in lowered
        assert "src=" not in lowered
        assert "@import" not in lowered
        assert "fonts.googleapis" not in lowered
        assert "background-image" not in lowered

    def test_every_style_is_inline(self, rendered):
        """Every declaration block lives in a style="..." attribute."""
        html, _ = rendered
        # No CSS rule syntax outside attributes: a bare `selector { ... }`.
        assert not re.search(r"^\s*[.#a-zA-Z][^\n{}]*\{", html, re.MULTILINE)
        assert html.count("style=") >= 10

    def test_layout_is_table_based_and_600px_capped(self, rendered):
        html, _ = rendered
        assert "<table" in html.lower()
        assert "max-width:600px" in html.lower().replace(" ", "")
        assert "<div" in html.lower()  # preheader; the layout itself is tables

    def test_hidden_preheader_carries_the_supplied_text(self, rendered):
        html, _ = rendered
        assert "42 signups today" in html
        preheader = re.search(
            r'<span[^>]*style="([^"]*)"[^>]*>\s*42 signups today', html
        )
        assert preheader is not None, "preheader must be a hidden <span>"
        style = preheader.group(1).replace(" ", "")
        assert "display:none" in style
        assert "max-height:0" in style

    def test_wordmark_is_text_not_an_image(self, rendered):
        html, _ = rendered
        assert "AETHER" in html
        assert "AB Marquee" in html, "display stack for the wordmark"
        assert "AB Sans" in html, "body stack"

    def test_cta_is_a_bulletproof_table_button_in_brand_gold(self, rendered):
        html, _ = rendered
        assert "https://5cb5f0620.abacusai.cloud/admin" in html
        assert "Open the dashboard" in html
        anchor = re.search(
            r'<a\s[^>]*href="https://5cb5f0620\.abacusai\.cloud/admin"[^>]*style="([^"]*)"',
            html,
        )
        assert anchor is not None
        style = anchor.group(1).lower().replace(" ", "")
        assert f"background-color:{eb.PALETTE['gold']}" in style
        assert f"color:{eb.PALETTE['ink0']}" in style

    def test_html_escapes_user_supplied_values(self):
        html, text = eb.render_branded_email(
            "Report & <review>",
            [eb.paragraph("5 < 6 & \"quotes\"")],
        )
        assert "<review>" not in html
        assert "&lt;review&gt;" in html
        assert "5 &lt; 6" in html
        # The text part keeps the real characters — it is not HTML.
        assert "Report & <review>" in text
        assert '5 < 6 & "quotes"' in text


# ----------------------------------------------------- plain-text parity
class TestPlainTextParity:
    def test_text_part_carries_every_stat_value(self, rendered):
        _, text = rendered
        assert "Mode: LIVE" in text
        assert "Signups: 42" in text
        assert "Reply rate: not observable (no real sends yet)" in text

    def test_text_part_carries_title_paragraphs_cta_and_footer(self, rendered):
        _, text = rendered
        assert "Daily digest" in text
        assert "Here is where the numbers landed today." in text
        assert "Every number above is a live database query." in text
        assert "Open the dashboard" in text
        assert "https://5cb5f0620.abacusai.cloud/admin" in text
        assert "You receive this because you are the Aether account owner." in text

    def test_text_part_is_never_a_stub(self, rendered):
        html, text = rendered
        assert len(text.strip()) > 120
        for token in ("AETHER", "Daily digest"):
            assert token in text and token in html

    def test_divider_renders_in_both_parts(self, rendered):
        html, text = rendered
        assert "---" in text
        assert "border-top" in html.lower()

    def test_optional_arguments_are_genuinely_optional(self):
        html, text = eb.render_branded_email("Minimal", [eb.paragraph("Just this.")])
        assert "Just this." in html and "Just this." in text
        # No CTA supplied → no button rendered. (The bare `<a ` proxy became
        # too broad on 2026-08-16 when the mandatory legal footer gained a
        # support mailto — the ONLY anchor a CTA-less email may carry.)
        anchors = re.findall(r'<a href="([^"]+)"', html)
        assert anchors == [f"mailto:{eb.SUPPORT_EMAIL}"], (
            "a CTA-less email carries exactly the footer support mailto and "
            f"no other anchor: {anchors}"
        )
        assert html.lower().count("<table") >= 1

    def test_preheader_defaults_to_the_title_when_omitted(self):
        html, _ = eb.render_branded_email("Reset your Aether password", [eb.paragraph("x")])
        preheader = re.search(r'<span[^>]*display:none[^>]*>([^<]*)</span>', html)
        assert preheader is not None
        assert "Reset your Aether password" in preheader.group(1)


class TestLegalFooterDirective:
    """Owner directive 2026-08-16: the canonical legal line + support mailto
    render on EVERY branded email, in BOTH parts, even with no footer_note."""

    def test_legal_line_and_support_in_both_parts(self):
        from app.services import email_branding as eb

        html, text = eb.render_branded_email("Any title", [eb.paragraph("Hi.")])
        assert eb.LEGAL_LINE in text
        assert f"Support: {eb.SUPPORT_EMAIL}" in text
        # HTML escapes but must carry the same content + a real mailto.
        assert "V² Group Pty. Ltd." in html
        assert "All rights reserved." in html
        assert f'href="mailto:{eb.SUPPORT_EMAIL}"' in html

    def test_identity_matches_the_web_brand_module(self):
        from app.services import email_branding as eb

        assert eb.PRODUCT_NAME == "Aether CareerAI Agent"
        assert eb.COMPANY_NAME == "V² Group Pty. Ltd."
        assert eb.SUPPORT_EMAIL == "sarkar.vikram@gmail.com"
