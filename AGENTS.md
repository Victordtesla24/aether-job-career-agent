# Agent instructions — Aether CareerAI Agent

This repository's **default design system** is the vendored Claude system:

**`design/aether-design-system/`** (zip: `design/aether-design-system/Aether-Design-System.zip`)

Read `design/aether-design-system/readme.md` and `design/aether-design-system/SKILL.md` before creating or restyling **any** artefact: UI, email, markdown, HTML, SVG, PDF chrome, admin document, chart, slide, or README block. Short restatement: `design/DESIGN.md`. Cursor rule: `.cursor/rules/aether-design-system.mdc`. Claude skill: `.claude/skills/aether-career-agent-design/SKILL.md`.

## Brand law

- Palette: obsidian `#08080A` / `#0F0F12` grounds, gilt `#C9A84C` as the single brand accent, sapphire `#3E5A8C` for agent-intelligence cues. State: ok `#6FAF8D`, warn `#C8873A` (copper, never gold), danger `#B9544B`, neutral `#8C8A82` (no data), degraded `#A08CB4`.
- Type: AB Marquee (display), AB Sans (body/UI), JetBrains Mono (data). No Inter as the brand face.
- No emoji. No coral `#FF6B35`. No electric indigo `#4F46E5`. Those values are retired (D-0043).
- Australian English. No exclamation marks. Unmeasured values say "not measured", never a fake `0`.
- Aether-owned email goes through `apps/api/app/services/email_branding.py` (welcome, password reset, founder digest, Stripe lifecycle, notification-digest chrome, inbound auto-reply). Every kind is previewable under `/admin/sales-agent` → Brand; preview HTML is the live renderer. Generated markdown/HTML docs go through `app.services.branded_artefacts` or `design/templates/artefact.html`. Business card: Brand tab kind `business_card`.
- Carve-outs (do **not** gilt-brand these): the candidate's application email to an employer; the employer-facing résumé/cover-letter page itself. Sales outreach stays text-first in `sales_branding`.

## Production

Live at https://5cb5f0620.abacusai.cloud. Deploy only via `docs/delivery/DEPLOYMENT-RUNBOOK.md`. Claim work in `docs/delivery/SESSION-COORDINATION.md`. Never source `.env` into pytest. Never restart `aether-api`/`aether-web`/`aether-worker` without a claimed deploy window.

## Tests

Backend: `scripts/run-tests.sh` (never against the production schema). Frontend: `pnpm --dir apps/web test`. Do not run Playwright against port 3000.

## Non-negotiable constraints

Before writing any code in this repository, read and obey
`scripts/integrity/NON-NEGOTIABLE-CONSTRAINTS.md`. They are enforced by a
pre-commit hook, a blocking CI gate, and a systemd start-up guard. Bypassing an
enforcement point (e.g. `git commit --no-verify`) is itself a violation.
