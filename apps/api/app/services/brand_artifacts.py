# ruff: noqa: E501  # SVG markup is intentionally kept legible in one template.
"""Deterministic Aether-branded marketing poster rendering.

This is intentionally SVG-only: it uses the existing public Aether mark and
sales-branding design tokens, needs no image-generation dependency or external
service, and makes every rendered creative reproducible from its recorded
input hash. It does not generate claims, metrics, or social-media actions.
"""
from __future__ import annotations

import hashlib
import html
import json

from app.services.sales_branding import BRAND, brand_logo_url

ARTIFACT_KIND = "poster"
PRODUCT_NAME = "Aether Career Job Agent"
_MAX_TITLE = 120
_MAX_MESSAGE = 400
_MAX_CTA = 120


def poster_input(title: str, message: str, cta: str) -> dict[str, str]:
    """Normalize bounded, human-supplied poster copy for stable deduplication."""
    values = {
        "title": " ".join((title or "").split()),
        "message": " ".join((message or "").split()),
        "cta": " ".join((cta or "").split()),
    }
    limits = {"title": _MAX_TITLE, "message": _MAX_MESSAGE, "cta": _MAX_CTA}
    for key, value in values.items():
        if not value:
            raise ValueError(f"{key} is required")
        if len(value) > limits[key]:
            raise ValueError(f"{key} exceeds its maximum length")
    return values


def input_hash(payload: dict[str, str]) -> str:
    """Content-address the normalized rendering contract, not a timestamp."""
    canonical = json.dumps(
        {"kind": ARTIFACT_KIND, **payload}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_poster(payload: dict[str, str]) -> str:
    """Render a self-contained SVG poster grounded in current Aether tokens."""
    title = html.escape(payload["title"])
    message = html.escape(payload["message"])
    cta = html.escape(payload["cta"])
    g = BRAND
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1500" viewBox="0 0 1200 1500" role="img" aria-labelledby="title description">
  <title id="title">{title}</title>
  <desc id="description">A branded Aether Career Job Agent marketing poster.</desc>
  <defs>
    <linearGradient id="gilt" x1="0" x2="1"><stop stop-color="{g['goldDark']}"/><stop offset=".38" stop-color="{g['gold']}"/><stop offset=".62" stop-color="{g['goldPale']}"/><stop offset="1" stop-color="{g['gold']}"/></linearGradient>
  </defs>
  <rect width="1200" height="1500" fill="{g['bg']}"/>
  <rect x="56" y="56" width="1088" height="1388" rx="8" fill="{g['surface']}" stroke="{g['gold']}" stroke-opacity=".2"/>
  <rect x="56" y="56" width="1088" height="12" fill="url(#gilt)"/>
  <image href="{brand_logo_url().replace('.png', '.svg')}" x="96" y="118" width="92" height="92"/>
  <text x="210" y="158" fill="{g['gold']}" font-family="Arial, sans-serif" font-size="25" font-weight="700" letter-spacing="5">AETHER CAREER JOB AGENT</text>
  <line x1="96" y1="288" x2="1104" y2="288" stroke="{g['gold']}" stroke-opacity=".2"/>
  <text x="96" y="430" fill="{g['cream']}" font-family="Georgia, serif" font-size="76" font-weight="700">{title}</text>
  <text x="96" y="570" fill="{g['cream']}" fill-opacity=".75" font-family="Arial, sans-serif" font-size="34">{message}</text>
  <rect x="96" y="1240" width="690" height="92" rx="46" fill="url(#gilt)"/>
  <text x="142" y="1298" fill="{g['bg']}" font-family="Arial, sans-serif" font-size="29" font-weight="700">{cta}</text>
  <text x="96" y="1386" fill="{g['cream']}" fill-opacity=".46" font-family="Arial, sans-serif" font-size="22">Human-approved job search support</text>
</svg>'''


def build_poster(title: str, message: str, cta: str) -> tuple[dict[str, str], str, str]:
    """Return normalized source, stable hash, and deterministic SVG."""
    payload = poster_input(title, message, cta)
    return payload, input_hash(payload), render_poster(payload)


def render_business_card_svg() -> str:
    """90mm × 50mm calling card at 300 dpi-ish (1063 × 591 viewBox).

    Self-contained SVG: no external images, so the Brand-tab preview and a
    print shop both see the same obsidian-and-gilt lockup. Contact lines are
    merge fields — this is a template, not a fabricated sample person.
    """
    g = BRAND
    url = "5cb5f0620.abacusai.cloud"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1050" height="600" viewBox="0 0 1050 600" role="img" aria-labelledby="card-title card-desc">
  <title id="card-title">Aether Career Job Agent business card</title>
  <desc id="card-desc">Obsidian ground, gilt wordmark, merge-field contact lines.</desc>
  <defs>
    <linearGradient id="card-gilt" x1="0" x2="1"><stop stop-color="{g['goldDark']}"/><stop offset=".38" stop-color="{g['gold']}"/><stop offset=".62" stop-color="{g['goldPale']}"/><stop offset="1" stop-color="{g['gold']}"/></linearGradient>
  </defs>
  <rect width="1050" height="600" fill="{g['bg']}"/>
  <rect x="28" y="28" width="994" height="544" fill="{g['surface']}" stroke="{g['gold']}" stroke-opacity=".28"/>
  <rect x="28" y="28" width="994" height="8" fill="url(#card-gilt)"/>
  <rect x="28" y="564" width="994" height="8" fill="url(#card-gilt)"/>
  <text x="72" y="160" fill="{g['gold']}" font-family="Georgia, 'Times New Roman', serif" font-size="42" font-weight="700" letter-spacing="14">AETHER</text>
  <text x="72" y="198" fill="{g['cream']}" fill-opacity=".55" font-family="Arial, Helvetica, sans-serif" font-size="16" font-weight="700" letter-spacing="4">CAREERAI AGENT</text>
  <line x1="72" y1="228" x2="360" y2="228" stroke="{g['gold']}" stroke-opacity=".35"/>
  <text x="72" y="300" fill="{g['cream']}" font-family="Georgia, 'Times New Roman', serif" font-size="28" font-weight="700">{{{{name}}}}</text>
  <text x="72" y="342" fill="{g['gold']}" font-family="Arial, Helvetica, sans-serif" font-size="16" letter-spacing="2">{{{{role}}}}</text>
  <text x="72" y="420" fill="{g['cream']}" fill-opacity=".78" font-family="Arial, Helvetica, sans-serif" font-size="16">{{{{email}}}}</text>
  <text x="72" y="452" fill="{g['cream']}" fill-opacity=".78" font-family="Arial, Helvetica, sans-serif" font-size="16">{{{{phone}}}}</text>
  <text x="72" y="520" fill="{g['gold']}" font-family="Arial, Helvetica, sans-serif" font-size="14" letter-spacing="1">{url}</text>
</svg>'''


def render_business_card_preview_html() -> str:
    """HTML wrapper so the Brand-tab iframe can show the SVG on ink."""
    svg = render_business_card_svg()
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Aether business card</title></head>"
        f"<body style=\"margin:0;padding:48px 16px;background-color:{BRAND['bg']};"
        'text-align:center;">'
        f"{svg}</body></html>"
    )
