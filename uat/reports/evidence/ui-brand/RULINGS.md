# UI-BRAND run — Binding orchestrator rulings (2026-08-15)

Ground truth: `/home/ubuntu/aether_design_system` (readme.md + tokens/). Audit: `audit/` (102 findings, 4 auditors, wf_fe8e6922-cd5). These rulings bind every fixer/reviewer in this run.

## R-VIZ — Validated chart token palette (dataviz-skill validator: ALL PASS, dark mode, vs #0F0F12 AND #08080A, adjacent pairs)
- `CHART_PALETTE` (fixed order, never cycled, never reassigned on filter):
  1. `#AE8E32` chart-gold (brand gold hue 90 snapped into OKLCH L band)
  2. `#4F74B5` chart-sapphire (hue 261)
  3. `#C16F7B` chart-rose (burgundy-light hue 11)
  4. `#439FC8` chart-sky (light sapphire step)
- Overflow/"Other" bucket: `#8C8A82` (--state-neutral). Charts needing >4 hues use top-4 + Other — never a 5th hue.
- `CHART_HEAT` = gilt alpha ramp rgba(201,168,76, .10/.25/.42/.62/.85).
- `DIVERGING` = #B9544B / #8C8A82 / #6FAF8D (state semantics).
- `STATE` = ok #6FAF8D · warn #C8873A · danger #B9544B · info #7C93BE · neutral #8C8A82 · degraded #A08CB4 (verbatim DS tones).
- SURFACE.s0 → #08080A; point-halo/donut-gap stroke = the card ground #0F0F12. Axis/labels from parchment fg ladder; every numeral JetBrains Mono tabular-nums; no fill-white.
- EASE → cubic-bezier(0.25, 1, 0.5, 1). DUR_REVEAL stays 500ms (reveal, not transition).
- Single-series charts (spark, trend, funnel) use chart-gold; UI gold #C9A84C stays for large ≥18%-alpha area fills and non-chart accents.
- offers-lib WEIGHT_COLORS → ordinal gilt ramp (one measure = ordinal, not categorical).
- analytics.py server donut palette → CHART_PALETTE order, top-4 + Other (#8C8A82).

## R1 — Gold is never a state. "Live/running" = --state-ok #6FAF8D
Applies to agents-console.css:390 running badge, OrchestrationMap live edges/particles/glow (SVG), OrchestrationMapGL live/active materials + aura. Gold remains: selected-node rail, focus ring, brand chrome. Idle nodes = state-neutral #8C8A82; planned = fg-4 alpha. Glow rgba always matches the rendered dot colour.

## R2 — Branded document template rebrand (cover-letters CL_PANEL/CL_ACCENT)
The in-app letter preview mirrors the export template — preview honesty is load-bearing, so BOTH move together: rebrand the branded-template accent constants (web cover-letters/page.tsx CL_PANEL/CL_ACCENT + their source constants in apps/api resume/letter PDF rendering) from coral #F4715C/#FCD9CF to gilt (accent #C9A84C, panel wash #F5EEDB-family). COLOURS/FONT-COLOUR CONSTANTS ONLY — zero layout/structure changes. HARD CONSTRAINT: RFMT-5 format-preserved outbound paths (baseline-format documents are NEVER branded) must be untouched — cite the existing tests proving it in the slice evidence. Precedent: 95bae7de rebranded sales-agent docs the same way.

## R3 — Pricing semantics: marketing emphasis is gold/parchment; state-ok green is reserved for completed/connected. Feature checkmarks → gold; "save more" → gold-pale.

## R4 — Public surface typography: every public/auth heading gets the display treatment (.type-display/.type-page, AB Marquee, ALL CAPS, tracking) per ui_kits/public/{AuthScreen,PricingScreen,PublicShell}.jsx; one gilded gesture (.text-gilt) per screen max.

## R5 — Admin surfaces are part of the product: primary CTAs = gold-filled (one per surface); sapphire only as agent-intelligence cue; same ink ladder/typography as the command center.

## R6 — Categorical identity anywhere in the UI (story categories, source chips, weight bars) draws from R-VIZ CHART_PALETTE order — never a bespoke rainbow. Chips/labels always carry the name (colour is reinforcement).

## R7 — Add the DS gold scrollbar + selection styles globally (spec: gold gradient thumb, transparent track; selection rgba(201,168,76,.30) on #FDF8F1).

## R8 — Pre-existing RSC-prefetch console errors on /dashboard/* are OUT OF SCOPE (recorded pre-run; not introduced by us; tracked as a monitoring row, not a brand defect). No fix in this run.

## Process laws (unchanged, binding)
- Visual-only: no behaviour, route, API-contract, copy-semantics, or testid changes (copy changes only where a finding names copy glyphs, e.g. "✓" in labels).
- Tests pinning legacy values are updated IN THE SAME COMMIT as their component (9 known files; grep before closing each slice).
- Shared tree: `git commit --only <paths>`; verify `git show --stat HEAD` afterwards; never stage foreign files (FOREIGN-WIP-MOVED.md, .abacus.donotdelete, deleted evidence logs, sales_agent fixtures, test_blocker010).
- One heavy job at a time (nice -n 10, flock /tmp/aether-deploy.lock for build+deploy; vitest --maxWorkers=2).
- Author ≠ reviewer ≠ verifier; reviewer runs a different model than the fixer.
