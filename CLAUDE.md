# Claude Code — Aether CareerAI Agent

You are working in the Aether CareerAI Agent monorepo. Before you create or restyle anything a human will see, load the design system.

## Design system (mandatory, default)

1. Read `design/aether-design-system/SKILL.md` then `design/aether-design-system/readme.md`.
2. Tokens live in `design/aether-design-system/tokens/` (`colors.css` is the palette of record).
3. Product restatement: `design/DESIGN.md`. Agent contract: `AGENTS.md`. Cursor always-on rule: `.cursor/rules/aether-design-system.mdc`.

Obsidian and gilt. Primary `#C9A84C`. Page ground `#08080A`. Sapphire `#3E5A8C` only for agent cues. **Never** coral `#FF6B35` or indigo `#4F46E5`. **Never** emoji.

### Artefact routing

| Artefact | Use |
|---|---|
| App / admin UI | `apps/web` tokens in `globals.css` + `tailwind.config.ts` (already remapped to gilt) |
| Aether-owned email (welcome, reset, founder digest, Stripe lifecycle, notification chrome, auto-reply) | `apps/api/app/services/email_branding.py` — Brand tab preview is the live renderer |
| Admin invoice / business card / document / all email previews | `apps/api/app/services/brand_documents.py` (Sales Agent → Brand tab) |
| Generated markdown / HTML reports | `apps/api/app/services/branded_artefacts.py` or `design/templates/artefact.html` |
| Charts | `apps/web/src/components/charts/tokens.ts` |
| Static wireframes | `design/screens/*.html` (gilt, not the 2026-07 coral comps) |

Carve-outs: candidate→employer application email and the printed résumé/cover-letter page stay unbranded (the candidate's voice).

## Safety

- Production URL: https://5cb5f0620.abacusai.cloud
- Runbook: `docs/delivery/DEPLOYMENT-RUNBOOK.md`
- Session claims: `docs/delivery/SESSION-COORDINATION.md`
- Pytest: `scripts/run-tests.sh` only. Never `source .env` then pytest.
- Parallel test gate (TEST-PAR-1): do NOT queue behind `/tmp/aether-pytest.lock`. Give your wave its own schema and lock —
  `scripts/test-schema.sh provision <wave>`, then
  `AETHER_TEST_SCHEMA=aether_test_<wave> flock /tmp/aether-pytest-<wave>.lock scripts/run-tests.sh -q`,
  then `scripts/test-schema.sh drop <wave>` when the wave closes. The shared `aether_test` schema + `/tmp/aether-pytest.lock`
  remain valid for anyone who wants the legacy default. Host budget (measured, do not extrapolate): this VM has ~8 GB
  and no swap; a full suite reaches ~1.5 GB RSS and was OOM-killed at 2.18 GB when THREE ran at once (2026-08-17).
  Two concurrent TARGETED batteries alongside another agent's full suite ran green; safe concurrency for FULL suites
  is unproven — check `free -m` before starting one, and prefer targeted per-wave batteries.
- Do not restart systemd units without a claimed deploy window. Foreign WIP in this tree must not ship.

## Non-negotiable constraints

Before writing any code in this repository, read and obey
`scripts/integrity/NON-NEGOTIABLE-CONSTRAINTS.md`. They are enforced by a
pre-commit hook, a blocking CI gate, and a systemd start-up guard. Bypassing an
enforcement point (e.g. `git commit --no-verify`) is itself a violation.
