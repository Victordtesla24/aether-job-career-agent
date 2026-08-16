"""THE canonical home for Aether-OWNED transactional email templates.

Owner directive (2026-08-16): every email Aether sends **in its own voice**
— founder digests, password resets, and anything added after this — is
rendered here, so the obsidian-and-gilt brand is consistent by construction
instead of by copy-paste. **Add new Aether email templates to THIS module**;
do not hand-roll HTML at a call site.

Two things are deliberately NOT rendered here (design ruling, pinned by
``tests/test_brand_email_adoption.py::TestBrandingCarveOuts``):

* **User-authored application emails** (``application_submission``) are the
  candidate's own voice, sent from the candidate's own mailbox. Aether
  branding there would misrepresent the applicant to an employer and leak
  the fact that a tool was used.
* **Sales outreach to prospects** stays text-first for deliverability and
  keeps only its server-side compliance footer (``sales_branding`` owns that
  separate, marketing-specific template).

Design tokens are copied verbatim from ``apps/web/src/app/globals.css`` /
``tailwind.config.ts`` — gold ``#c9a84c`` (light ``#d4b65c``, pale
``#e8d5a3``, dark ``#b0923f``), the gold hairline ``rgba(201,168,76,0.2)``,
and the ink ramp ``#08080a`` → ``#26262c``. Keep them in sync with the web
app; a drifted hex is a brand break.

EMAIL-CLIENT RULES this module must never break (they are what separates a
branded email from a broken one):

* table-based layout, 600px cap, **every** style inline — Gmail strips
  ``<style>``, Outlook ignores flexbox/grid;
* **no external assets at all**: no images (so no broken-image boxes and no
  tracking pixel), no webfont links, no external CSS. Icons are unicode
  glyphs and the wordmark is text. The webfonts are named first in the font
  stacks purely so Apple Mail / webmail clients that already have them use
  them; the system fallbacks ARE the design;
* a hidden preheader span (it is what the inbox list preview shows);
* :func:`render_branded_email` returns ``(html, plain_text)`` and the plain
  text carries **every** value the HTML shows — a recipient on a text-only
  client must lose zero information. It is never a stub.
"""
from __future__ import annotations

import html as _html
from typing import Any, Iterable, Mapping, Sequence

#: Brand identity — MUST stay in lockstep with the web's canonical
#: ``apps/web/src/lib/brand.ts`` (owner directive 2026-08-16: one footnote
#: across the board). The superscript ² is unicode here (email/plain-text
#: safe); the web renders a semantic <sup>.
PRODUCT_NAME = "Aether CareerAI Agent"
COMPANY_NAME = "V² Group Pty. Ltd."
SUPPORT_EMAIL = "sarkar.vikram@gmail.com"
LEGAL_LINE = (
    f"© 2026 {PRODUCT_NAME} · A product of {COMPANY_NAME} · All rights reserved."
)

#: Brand tokens — verbatim from the web design system. Lowercase hex, because
#: that is how ``globals.css`` writes them and the tests compare literally.
PALETTE: dict[str, str] = {
    "gold": "#c9a84c",
    "goldLight": "#d4b65c",
    "goldPale": "#e8d5a3",
    "goldDark": "#b0923f",
    "goldBorder": "rgba(201,168,76,0.2)",
    "ink0": "#08080a",  # page ground
    "ink1": "#0f0f12",  # card
    "ink2": "#16161a",  # raised panel (stat rows)
    "ink3": "#1e1e23",
    "ink4": "#26262c",
    # Text: warm near-white, never pure #fff, at WCAG-readable contrast on
    # the ink grounds (#f2efe9 on #0f0f12 ≈ 15.6:1; #b9b3a6 ≈ 8.2:1;
    # #c9a84c ≈ 8.1:1).
    "text": "#f2efe9",
    "textMuted": "#b9b3a6",
    "textFaint": "#8d887d",
}

#: Email-safe font stacks. The webfonts lead (clients that have them use
#: them); the system fallbacks are what the layout is actually designed for.
BODY_FONT = "'AB Sans','Helvetica Neue',Arial,sans-serif"
DISPLAY_FONT = "'AB Marquee',Georgia,'Times New Roman',serif"

_MAX_WIDTH = "600px"


# --------------------------------------------------------------- block API
def paragraph(text: str) -> dict[str, Any]:
    """A prose block. Blank lines split it into separate paragraphs."""
    return {"type": "paragraph", "text": text}


def stats(items: Iterable[Any]) -> dict[str, Any]:
    """A label/value list — accepts ``(label, value)`` pairs or mappings with
    ``label``/``value`` keys. Values are stringified as given (callers format
    their own numbers, so the HTML and the text part can never disagree)."""
    normalised: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, Mapping):
            normalised.append((str(item.get("label", "")), str(item.get("value", ""))))
        else:
            label, value = item
            normalised.append((str(label), str(value)))
    return {"type": "stats", "items": normalised}


def divider() -> dict[str, Any]:
    """A gold hairline rule."""
    return {"type": "divider"}


# ------------------------------------------------------------- html pieces
def _esc(value: Any) -> str:
    return _html.escape(str(value if value is not None else ""))


def _paragraph_html(text: str) -> str:
    out: list[str] = []
    for chunk in str(text or "").strip().split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        body = _esc(chunk).replace("\n", "<br>")
        out.append(
            '<tr><td style="padding:0 0 16px 0;font-family:' + BODY_FONT + ";"
            f"font-size:15px;line-height:1.7;color:{PALETTE['text']};\">{body}</td></tr>"
        )
    return "\n".join(out)


def _stats_html(items: Sequence[tuple[str, str]]) -> str:
    if not items:
        return ""
    rows: list[str] = []
    for index, (label, value) in enumerate(items):
        border = (
            f"border-top:1px solid {PALETTE['goldBorder']};" if index else ""
        )
        rows.append(
            f'<tr><td style="{border}padding:10px 14px;font-family:{BODY_FONT};'
            f"font-size:13px;line-height:1.5;color:{PALETTE['textMuted']};\""
            f' align="left">{_esc(label)}</td>'
            f'<td style="{border}padding:10px 14px;font-family:{BODY_FONT};'
            f"font-size:14px;font-weight:700;line-height:1.5;color:{PALETTE['goldPale']};\""
            f' align="right">{_esc(value)}</td></tr>'
        )
    inner = "\n".join(rows)
    return (
        '<tr><td style="padding:0 0 18px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="width:100%;background-color:{PALETTE["ink2"]};'
        f'border:1px solid {PALETTE["goldBorder"]};border-radius:4px;">'
        f"{inner}</table></td></tr>"
    )


def _divider_html() -> str:
    return (
        '<tr><td style="padding:4px 0 20px 0;">'
        f'<div style="border-top:1px solid {PALETTE["goldBorder"]};'
        'font-size:0;line-height:0;height:0;">&nbsp;</div></td></tr>'
    )


def _blocks_html(blocks: Sequence[Mapping[str, Any]]) -> str:
    rendered: list[str] = []
    for block in blocks:
        kind = str(block.get("type", "paragraph"))
        if kind == "paragraph":
            rendered.append(_paragraph_html(str(block.get("text", ""))))
        elif kind == "stats":
            rendered.append(_stats_html(list(block.get("items", []))))
        elif kind == "divider":
            rendered.append(_divider_html())
        else:  # unknown block types are a programming error, not silent data loss
            raise ValueError(f"email_branding: unsupported block type {kind!r}")
    return "\n".join(part for part in rendered if part)


def _cta_html(cta: Mapping[str, Any]) -> str:
    label = _esc(cta.get("label", ""))
    url = _esc(cta.get("url", ""))
    if not label or not url:
        return ""
    return (
        '<tr><td align="center" style="padding:8px 0 26px 0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:0 auto;">'
        f'<tr><td align="center" style="background-color:{PALETTE["gold"]};'
        'border-radius:4px;">'
        f'<a href="{url}" style="display:inline-block;padding:14px 34px;'
        f"font-family:{BODY_FONT};font-size:14px;font-weight:700;"
        "letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;"
        f"background-color:{PALETTE['gold']};color:{PALETTE['ink0']};"
        'border-radius:4px;" target="_blank" rel="noopener noreferrer">'
        f"{label}</a></td></tr></table></td></tr>"
    )


# ------------------------------------------------------------- plain text
def _blocks_text(blocks: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for block in blocks:
        kind = str(block.get("type", "paragraph"))
        if kind == "paragraph":
            text = str(block.get("text", "")).strip()
            if text:
                out.append(text)
        elif kind == "stats":
            items = list(block.get("items", []))
            if items:
                out.append("\n".join(f"{label}: {value}" for label, value in items))
        elif kind == "divider":
            out.append("-" * 46)
        else:
            raise ValueError(f"email_branding: unsupported block type {kind!r}")
    return out


# ----------------------------------------------------------------- render
def render_branded_email(
    title: str,
    blocks: Sequence[Mapping[str, Any]],
    *,
    cta: Mapping[str, Any] | None = None,
    footer_note: str | None = None,
    preheader: str | None = None,
) -> tuple[str, str]:
    """Render an Aether-owned email; returns ``(html, plain_text)``.

    ``blocks`` is a sequence built with :func:`paragraph`, :func:`stats` and
    :func:`divider`. ``cta`` is ``{"label": ..., "url": ...}``. Both returned
    parts carry the SAME information — the plain text is a real alternative,
    not a placeholder — so callers hand them to
    ``email_sender.send_email(..., html_body=html)`` (or
    ``GmailService.send(..., html_body=html)``) as a multipart/alternative
    message. Pure function: no I/O, no environment reads, no network.
    """
    title = str(title or "").strip()
    preheader_text = str(preheader or title).strip()
    blocks = list(blocks)

    body_rows = _blocks_html(blocks)
    cta_row = _cta_html(cta) if cta else ""
    note_row = ""
    if footer_note:
        note_row = (
            f'<tr><td align="center" style="padding:18px 40px 0 40px;'
            f"font-family:{BODY_FONT};font-size:12px;line-height:1.6;"
            f'color:{PALETTE["textFaint"]};">{_esc(footer_note)}</td></tr>'
        )
    # The legal footer renders on EVERY branded email (owner directive
    # 2026-08-16): the canonical line plus a real support mailto.
    footer_row = (
        note_row
        + f'<tr><td align="center" style="padding:18px 40px 26px 40px;'
        f'border-top:1px solid {PALETTE["goldBorder"]};'
        f"font-family:{BODY_FONT};font-size:11px;line-height:1.7;"
        f'color:{PALETTE["textFaint"]};">{_esc(LEGAL_LINE)}<br>'
        f'Support: <a href="mailto:{SUPPORT_EMAIL}" '
        f'style="color:{PALETTE["gold"]};text-decoration:none;">'
        f"{SUPPORT_EMAIL}</a></td></tr>"
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
</head>
<body style="margin:0;padding:0;background-color:{PALETTE['ink0']};">
<span style="display:none;max-height:0;max-width:0;overflow:hidden;opacity:0;\
visibility:hidden;mso-hide:all;font-size:1px;line-height:1px;\
color:{PALETTE['ink0']};">{_esc(preheader_text)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;margin:0;padding:0;background-color:{PALETTE['ink0']};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;max-width:{_MAX_WIDTH};background-color:{PALETTE['ink1']};
 border:1px solid {PALETTE['goldBorder']};border-radius:6px;">
<tr><td style="height:3px;line-height:3px;font-size:0;\
background-color:{PALETTE['gold']};border-radius:6px 6px 0 0;">&nbsp;</td></tr>
<tr><td align="center" style="padding:30px 40px 6px 40px;">
<div style="font-family:{DISPLAY_FONT};font-size:23px;font-weight:700;\
letter-spacing:0.34em;line-height:1.2;color:{PALETTE['gold']};">AETHER</div>
<div style="padding-top:7px;font-family:{BODY_FONT};font-size:10px;\
font-weight:700;letter-spacing:0.22em;text-transform:uppercase;\
color:{PALETTE['textFaint']};">CareerAI Agent</div>
</td></tr>
<tr><td align="center" style="padding:16px 40px 0 40px;">
<div style="font-family:{DISPLAY_FONT};font-size:24px;font-weight:700;\
line-height:1.35;color:{PALETTE['goldPale']};">{_esc(title)}</div>
<div style="width:44px;height:1px;font-size:0;line-height:1px;\
margin:14px auto 0 auto;background-color:{PALETTE['gold']};">&nbsp;</div>
</td></tr>
<tr><td style="padding:22px 40px 0 40px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;">
{body_rows}
</table>
</td></tr>
{cta_row}
{footer_row}
<tr><td style="height:2px;line-height:2px;font-size:0;\
background-color:{PALETTE['goldDark']};border-radius:0 0 6px 6px;">&nbsp;</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    text_parts: list[str] = [f"AETHER - {PRODUCT_NAME}"]
    if title:
        text_parts.append(title)
        text_parts.append("=" * min(len(title), 46))
    text_parts.extend(_blocks_text(blocks))
    if cta:
        label = str(cta.get("label", "")).strip()
        url = str(cta.get("url", "")).strip()
        if label and url:
            text_parts.append(f"{label}: {url}")
    if footer_note:
        text_parts.append(str(footer_note).strip())
    text_parts.append(f"{LEGAL_LINE}\nSupport: {SUPPORT_EMAIL}")
    plain_text = "\n\n".join(part for part in text_parts if part) + "\n"

    return html, plain_text
