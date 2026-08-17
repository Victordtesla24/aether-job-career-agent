"""Branded HTML wrapper for generated documents (markdown, run reports, notes).

The Claude Aether Career Design System at ``design/aether-design-system`` is
the visual source. This module translates those tokens into a single-column,
inline-styled HTML document so an agent-written artefact carries the same
obsidian-and-gilt chrome as transactional email — without depending on a
markdown library or external CSS.

Not for employer-facing application mail (that stays the candidate's voice)
and not for sales outreach (``sales_branding.render_sales_outreach_html``
owns that path; Brand-tab kind ``sales_outreach``).
"""
from __future__ import annotations

import html as _html
from typing import Any

from app.services.email_branding import (
    BODY_FONT,
    DISPLAY_FONT,
    LEGAL_LINE,
    PALETTE,
    PRODUCT_NAME,
)

_MAX_WIDTH = "760px"


def render_branded_markdown_html(title: str, markdown_body: str) -> str:
    """Escape ``markdown_body`` and wrap it in design-system chrome.

    Blank-line-separated blocks become paragraphs; the body is HTML-escaped
    so a generated report cannot inject markup. Agents that need lists or
    headings should emit them as plain text here, or copy
    ``design/templates/artefact.html`` and fill it against the tokens in
    ``design/aether-design-system/tokens/``.
    """
    title_text = str(title or "").strip() or PRODUCT_NAME
    paragraphs: list[str] = []
    for block in str(markdown_body or "").strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        body = _html.escape(block).replace("\n", "<br>")
        paragraphs.append(
            f'<p style="margin:0 0 16px 0;font-family:{BODY_FONT};'
            f"font-size:15px;line-height:1.7;color:{PALETTE['text']};"
            f'">{body}</p>'
        )
    inner = "\n".join(paragraphs)
    g: dict[str, Any] = PALETTE
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html.escape(title_text)}</title>
</head>
<body style="margin:0;padding:0;background-color:{g['ink0']};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;margin:0;padding:0;background-color:{g['ink0']};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="760" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;max-width:{_MAX_WIDTH};background-color:{g['ink1']};
 border:1px solid {g['goldBorder']};">
<tr><td style="height:3px;line-height:3px;font-size:0;
background-color:{g['gold']};">&nbsp;</td></tr>
<tr><td align="center" style="padding:28px 40px 8px 40px;">
<div style="font-family:{DISPLAY_FONT};font-size:22px;font-weight:700;
 letter-spacing:0.34em;color:{g['gold']};">AETHER</div>
<div style="padding-top:6px;font-family:{BODY_FONT};font-size:10px;font-weight:700;
 letter-spacing:0.22em;text-transform:uppercase;color:{g['textFaint']};">
{_html.escape(PRODUCT_NAME)}</div>
</td></tr>
<tr><td align="center" style="padding:12px 40px 0 40px;">
<div style="font-family:{DISPLAY_FONT};font-size:26px;font-weight:700;
 line-height:1.3;color:{g['goldPale']};">{_html.escape(title_text)}</div>
<div style="width:44px;height:1px;font-size:0;line-height:1px;
 margin:14px auto 18px auto;background-color:{g['gold']};">&nbsp;</div>
</td></tr>
<tr><td style="padding:0 40px 28px 40px;">{inner}</td></tr>
<tr><td align="center" style="padding:18px 40px 24px 40px;
 border-top:1px solid {g['goldBorder']};font-family:{BODY_FONT};
 font-size:11px;line-height:1.7;color:{g['textFaint']};">
{_html.escape(LEGAL_LINE)}</td></tr>
<tr><td style="height:2px;line-height:2px;font-size:0;
background-color:{g['goldDark']};">&nbsp;</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
