"""Brand-templated email rendering for the Sales Agent — the Aether Career
Job Agent brand, built from the definitive **Aether Career Design System**
tokens (``~/aether_design_system``) translated into EMAIL-CLIENT-SAFE HTML.
The product name rendered in emails is ALWAYS "Aether Career Job Agent" —
the design system contributes colors/type/logo only, never its own name.

Email clients strip ``<style>`` blocks, ignore web fonts and choke on flexbox,
so every rule here is inlined and the layout is a centred single-column table.
Design-system tokens used (from ``tokens/colors.css`` + ``typography.css``):

* grounds ``#08080A`` (--ink-0, page) / ``#0F0F12`` (--ink-1, card) /
  ``#16161A`` (--ink-2, raised)
* gilt palette ``#C9A84C`` (--gold) · ``#D4B65C`` light · ``#E8D5A3`` pale
  · ``#B0923F`` dark · gilt gradient
  ``96deg #B0923F → #C9A84C 38% → #E8D5A3 62% → #C9A84C``
* text: warm parchment ``#F5F1E8`` (--fg-1) and its 0.62 / 0.46 alphas
  (--fg-2/--fg-3) — never pure white; gold hairline ``rgba(201,168,76,.20)``
* type: display 'AB Marquee' → Playfair Display → Georgia serif; body
  'AB Sans' → DM Sans → Helvetica sans (web fonts DON'T load in most email
  clients — the serif/sans system fallbacks ARE the design here)

COMPLIANCE INVARIANT (§6 hard gate): the plain-text body handed to
:func:`render_branded_email` already carries the server-side compliance
footer (``append_compliance_footer`` runs FIRST). This wrapper only splits
that footer out visually into the branded footer zone — the footer TEXT is
preserved verbatim inside the rendered HTML, so no template or brand styling
can strip the Spam Act 2003 sender-identification + unsubscribe lines.
"""
from __future__ import annotations

import html as _html
import os

#: Aether Career Design System tokens (tokens/colors.css) — visual only.
BRAND = {
    "bg": "#08080A",  # --ink-0 page ground
    "surface": "#0F0F12",  # --ink-1 card
    "surface2": "#16161A",  # --ink-2 raised
    "footerBg": "#08080A",  # footer sits back on the page ground
    "gold": "#C9A84C",  # --gold signature gilt
    "goldLight": "#D4B65C",  # --gold-light
    "goldPale": "#E8D5A3",  # --gold-pale (gradient high note)
    "goldDark": "#B0923F",  # --gold-dark
    "goldAccessible": "#C9A84C",  # gold reads AA on the ink grounds
    "cream": "#F5F1E8",  # --fg-1 warm parchment
    "fg1": "#F5F1E8",  # --fg-1 — never pure #FFF
    "fg2": "rgba(245,241,232,0.62)",  # --fg-2
    "fg3": "rgba(245,241,232,0.46)",  # --fg-3
    "hairline": "rgba(201,168,76,0.20)",  # --gold-border
    "cardBorder": "rgba(201,168,76,0.20)",  # --gold-border
    # Email-safe font stacks — the DS web fonts never load in email clients,
    # so the stacks lead with them but are DESIGNED around the fallbacks.
    "displayFont": "'AB Marquee','Playfair Display',Georgia,'Times New Roman',serif",
    "bodyFont": "'AB Sans','DM Sans',Helvetica,Arial,sans-serif",
    # Gilt gradient — the DS's single "gilded gesture", 96deg four-stop.
    "gradient": (
        "linear-gradient(96deg,#B0923F 0%,#C9A84C 38%,#E8D5A3 62%,#C9A84C 100%)"
    ),
}

#: The compliance footer separator written by ``append_compliance_footer``.
_FOOTER_SEPARATOR = "\n\n--\n"


def brand_logo_url() -> str:
    """Absolute production URL of the Aether brand mark (served by the web app
    from ``apps/web/public/brand/aether-mark.png`` — the design system's
    canonical raster mark)."""
    base = (
        os.environ.get("AETHER_PUBLIC_URL") or "https://5cb5f0620.abacusai.cloud"
    ).rstrip("/")
    return f"{base}/brand/aether-mark.png"


def _paragraphs_html(text: str, color: str, size: str = "15px") -> str:
    """Escape plain text and convert blank-line-separated blocks into
    inline-styled paragraphs (single newlines become ``<br>``)."""
    parts = []
    for block in (text or "").strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        escaped = _html.escape(block).replace("\n", "<br>")
        parts.append(
            f'<p style="margin:0 0 16px 0;font-family:{BRAND["bodyFont"]};'
            f"font-size:{size};line-height:1.7;color:{color};"
            f'-webkit-font-smoothing:antialiased;">{escaped}</p>'
        )
    return "\n".join(parts)


def split_compliance_footer(body_text: str) -> tuple[str, str]:
    """Split ``(main_body, footer)`` on the LAST ``\\n\\n--\\n`` separator —
    the server-appended compliance footer. If absent, footer is empty (the
    caller appends it before rendering, so this is only a defensive path)."""
    body_text = body_text or ""
    idx = body_text.rfind(_FOOTER_SEPARATOR)
    if idx == -1:
        return body_text, ""
    return body_text[:idx], body_text[idx + len(_FOOTER_SEPARATOR):]


def render_branded_email(subject: str, body_text: str) -> str:
    """Render a plain-text sales email (footer already appended) into the
    AB-branded, email-client-safe HTML document. Pure function — no I/O."""
    main, footer = split_compliance_footer(body_text)
    subject_html = _html.escape((subject or "").strip())
    body_html = _paragraphs_html(main, BRAND["fg2"])
    footer_html = _paragraphs_html(footer, BRAND["fg3"], size="12px") or (
        # Defensive only: render_branded_email is always called AFTER
        # append_compliance_footer, so this branch shouldn't trigger.
        ""
    )
    g = BRAND
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{subject_html}</title>
</head>
<body style="margin:0;padding:0;background-color:{g['bg']};">
<div style="display:none;max-height:0;overflow:hidden;">{subject_html}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background-color:{g['bg']};padding:0;margin:0;">
  <tr><td align="center" style="padding:32px 16px;">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
           style="max-width:600px;width:100%;">
      <!-- gold signature gradient bar -->
      <tr><td style="height:3px;line-height:3px;font-size:0;
                     background:{g['gold']};
                     background-image:{g['gradient']};">&nbsp;</td></tr>
      <!-- header -->
      <tr><td style="background-color:{g['surface']};padding:28px 40px 20px 40px;
                     border-left:1px solid {g['cardBorder']};
                     border-right:1px solid {g['cardBorder']};" align="center">
        <img src="{brand_logo_url()}" alt="Aether Career Job Agent" width="72"
             style="display:block;width:72px;height:auto;margin:0 auto 12px auto;">
        <div style="font-family:{g['bodyFont']};font-size:11px;font-weight:700;
                    letter-spacing:.25em;text-transform:uppercase;
                    color:{g['goldAccessible']};">Aether Career Job Agent</div>
      </td></tr>
      <!-- subject as display heading -->
      <tr><td style="background-color:{g['surface']};padding:0 40px 8px 40px;
                     border-left:1px solid {g['cardBorder']};
                     border-right:1px solid {g['cardBorder']};" align="center">
        <h1 style="margin:0 0 8px 0;font-family:{g['displayFont']};
                   font-size:24px;font-weight:700;line-height:1.3;
                   color:{g['fg1']};">{subject_html}</h1>
        <div style="width:48px;height:1px;margin:12px auto 0 auto;font-size:0;
                    line-height:1px;background-color:{g['hairline']};">&nbsp;</div>
      </td></tr>
      <!-- body -->
      <tr><td style="background-color:{g['surface']};padding:24px 40px 32px 40px;
                     border-left:1px solid {g['cardBorder']};
                     border-right:1px solid {g['cardBorder']};" align="left">
{body_html}
      </td></tr>
      <!-- compliance footer zone (verbatim server-side footer text) -->
      <tr><td style="background-color:{g['footerBg']};padding:20px 40px 24px 40px;
                     border-left:1px solid {g['cardBorder']};
                     border-right:1px solid {g['cardBorder']};
                     border-top:1px solid {g['hairline']};" align="center">
{footer_html}
      </td></tr>
      <!-- closing gradient bar -->
      <tr><td style="height:2px;line-height:2px;font-size:0;
                     background:{g['goldDark']};
                     background-image:{g['gradient']};">&nbsp;</td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""
