---
name: "Aether CareerAI Agent"
colors:
  primary: "#C9A84C"
  secondary: "#3E5A8C"
  accent: "#C9A84C"
  gold: "#C9A84C"
  goldLight: "#D4B65C"
  goldPale: "#E8D5A3"
  goldDark: "#B0923F"
  sapphire: "#3E5A8C"
  burgundy: "#722F37"
  neutral: "#8C8A82"
  background: "#08080A"
  backgroundAlt: "#0F0F12"
  surface: "#0F0F12"
  surfaceRaised: "#16161A"
  border: "#26262C"
  textPrimary: "#F5F1E8"
  textSecondary: "rgba(245,241,232,0.62)"
  textMuted: "rgba(245,241,232,0.46)"
  success: "#6FAF8D"
  warning: "#C8873A"
  error: "#B9544B"
  info: "#7C93BE"
  degraded: "#A08CB4"
typography:
  display:
    fontFamily: "AB Marquee"
    fontSize: 2.5rem
    fontWeight: 700
  heading:
    fontFamily: "AB Sans"
    fontSize: 1.375rem
    fontWeight: 600
  body:
    fontFamily: "AB Sans"
    fontSize: 0.9375rem
    fontWeight: 400
  label:
    fontFamily: "AB Sans"
    fontSize: 0.75rem
    fontWeight: 500
  mono:
    fontFamily: "JetBrains Mono"
    fontSize: 0.8125rem
    fontWeight: 400
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
rounded:
  xs: "2px"
  sm: "4px"
  md: "8px"
  lg: "14px"
  full: "9999px"
---

# Aether CareerAI Agent — design language

**Canonical source:** [`aether-design-system/`](aether-design-system/readme.md) (Claude design-system zip, vendored). Every artefact this product creates — UI, email, markdown, SVG, admin document, chart — is drawn from that system. This file is the short product-facing restatement. If this file and the design system disagree, the design system wins.

The 2026-07 coral-and-indigo language is **retired**. Historical delivery notes that mention it are superseded by D-0043.

## Overview

Aether is an autonomous AI career agent's command center — obsidian grounds, gilt punctuation, royal sapphire only for agent-intelligence cues. Target audience: ambitious professionals who delegate their job search to AI agents and want oversight without noise. Emotional intent: confident, ceremonial, trustworthy. The bar is the AB Entertainment baseline applied to this product's own information architecture.

## Colour usage

One ground, four elevations: `#08080A` page · `#0F0F12` card · `#16161A` raised · `#1E1E23` hover. Gilt `#C9A84C` is the **single** brand accent — primary CTAs, the wordmark, one gilded gesture per screen. Gold is never a state. Royal sapphire `#3E5A8C` carries agent-intelligence cues; burgundy `#722F37` is ceremonial (offers/negotiation only). Never two secondaries on one surface.

State tones are load-bearing: ok `#6FAF8D` · warn `#C8873A` (copper, never gold) · danger `#B9544B` · info `#7C93BE` · neutral `#8C8A82` (no data / not measured — **never** ok) · degraded `#A08CB4` (produced nothing but did not fail). The word always carries the meaning; colour is redundant reinforcement.

Charts use the validated gilt/sapphire/rose/sky set in `apps/web/src/components/charts/tokens.ts`. No fifth hue: top-4 + Other.

## Typography

AB Marquee for display (all caps, page and card titles). AB Sans for body, nav, labels, buttons. JetBrains Mono with tabular figures for every number, score, ID, timestamp and salary. Fallbacks: Playfair Display / DM Sans. One display weight per screen. The one gilded gesture: gilt gradient text on a single heading, never on body copy.

## Layout

Persistent 248px left rail + 64px command bar. Content padding 28–32px. Data surfaces are opaque; blur is chrome-only (command bar, overlays, ceremonial gilt cards). Radii stay sharp: 2px controls, 14px sections.

## Voice

Precise, calm, accountable. Australian English. Second person for the user, third person for named agents. No emoji, anywhere. No exclamation marks, no cheerleading. Unmeasured values read "not measured", never a fabricated `0`.

## Do's and Don'ts

- Do: start from `design/aether-design-system/readme.md` and its tokens before creating any artefact.
- Do: reserve gilt `#C9A84C` for the primary action and brand pulse; use sapphire `#3E5A8C` for AI/agent cues.
- Do: use JetBrains Mono for every number, score, timestamp, and ID.
- Do: wrap Aether-owned email in `app.services.email_branding` (subscriber welcome, password reset, founder digest).
- Don't: use coral, electric indigo, Inter as the brand face, or emoji as icons.
- Don't: paint gold as a status. Warn is copper.
- Don't: brand the candidate's own application email or résumé PDF in gilt — those stay the candidate's voice (carve-out pinned in `tests/test_brand_email_adoption.py`).
