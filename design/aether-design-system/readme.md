# Aether Career Agent — Design System

> **Obsidian & gilt.** Melbourne-built autonomous career agent, dressed in the black-and-gold cinematic language of the AB Entertainment baseline.

## What this is

A design system for **Aether — Job & Career Agent** (`AEther Career Job Agent`), an autonomous AI career agent that discovers roles, scores them against your résumé, tailors documents from evidence you have already given it, and holds every outbound action for your approval.

It was built by taking the **AB Entertainment Design System** as the visual baseline — obsidian grounds, gilt accents, the AB Marquee / AB Sans type pair, the ornamental rule, the house easing curve — and applying it to Aether's real product structure, read from the codebase. The result reads royal and elegant while keeping the honesty laws the product's own UI doctrine is built on.

**What this system replaced:** the 2026-07 coral-and-indigo command-center language on `#0A0A0F`. The shipping product and this system use **gilt (`#C9A84C`) + royal sapphire (`#3E5A8C`) on obsidian (`#08080A`)**, AB Marquee display type (not Inter), and the baseline's sharper radii. Structure, information architecture, component contracts and copy are the product's own.

### Sources read
| Source | What came from it |
|---|---|
| `https://github.com/Victordtesla24/aether-job-career-agent` (branch `main`) | Component contracts, shell geometry, screen structure, copy, state semantics. Files listed in the screen map below. |
| `design/DESIGN.md` + `design/canvas.json` in that repo | Approved screen list (17 screens), original token intent, do's and don'ts. |
| `apps/web/tailwind.config.ts`, `apps/web/src/app/globals.css` | Elevation ladder, hairline weights, motion tokens, the six-tone state palette and its honesty rules. |
| AB Entertainment Design System (bound baseline) | Colour lineage, both self-hosted type families, ornament, easing, glass/gilt card, container width. |
| `https://5cb5f0620.abacusai.cloud/dashboard` | **Not read** — a logged-in session could not be reached from this environment. Everything visual is grounded in the repository instead. |

### Products / surfaces
- **Command center** (`/dashboard/*`) — 13-section workspace behind a 248px rail: Dashboard, Jobs, Resume Studio, Cover Letter Studio, Story Bank, Applications, Interview Center, Networking, Email Center, Agents, Analytics, Offers, Settings.
- **Public site + auth** (`/pricing`, `/login`, `/signup`, legal pages) — `/pricing` is the real public landing page.
- **Admin** (`/admin`, `/admin-login`) — password-gated health and content views. Not recreated here.

---

## CONTENT FUNDAMENTALS

### Voice
**Precise, calm, accountable.** The product is a machine acting on your behalf, so the interface's first duty is to say exactly what happened and what it did not do. The baseline's theatrical register survives in the *display* type and the ceremony of the public site; the working copy stays plain.

- **Second person for the user** ("your search", "waiting on you"), **third person for agents** ("Scout discovered 14 new roles").
- Agents are named actors — Scout, Analyst, Tailor, Scribe, Courier, Envoy — and sentences read *actor · verb · object*.
- **Australian English** (`colour`, `organisation`, `AEST`), prices in AUD, GST stated inline.
- **No emoji, anywhere.** Icons are stroked SVG glyphs.
- Sentences end. No exclamation marks, no cheerleading, no "just".

### The honesty register (load-bearing)
Copy and colour never claim more than the data supports. These phrasings are canonical:

- Unmeasured: `"not measured"`, `"no scored roles yet"`, `"no usage quota on record"` — never a `0`.
- Degraded: `"The cover-letter agent returned no draft. Nothing was sent."` — a guard that worked is not a failure.
- Stalled: `"1 stalled run · none running"` — never "active".
- Basis disclosed: `"all time — every stage counted since your first discovery run"`, `"7 of 39 applied"`.
- Failure: `"Couldn't load the approval queue — request failed."` Plain, no stack, no blame.
- Pricing: `"Every plan uses the same AI models — plans differ by monthly agent-run quota and feature access, not model quality."`

### Casing
| Element | Casing |
|---|---|
| Hero / page titles (`.type-page`, `.type-display`) | ALL CAPS, display face, 0.03–0.05em tracking |
| Card titles (`.type-card-title`) | ALL CAPS, display face, 0.06em |
| Eyebrows, section labels, nav, button labels | UPPERCASE, body face, 0.10–0.14em |
| Body, notes, footnotes, tooltips | Sentence case |
| Numbers, IDs, timestamps, money | Data face, tabular figures |

### Copy examples
- Dashboard: *"Your search, right now"* / *"Every figure below is fetched live from your workspace."*
- Jobs: *"Every role below was discovered by your agents and scored against your résumé."*
- Resume Studio: *"Every rewritten line, and the evidence behind it"* / *"A highlighted preview only — the file you download is unmarked."*
- Approvals: *"Queue clear — nothing is waiting on you right now."*
- Agents: *"Nothing leaves the system without your approval."*
- CTAs: `RUN EVERYTHING` · `TAILOR & APPLY` · `APPROVE` / `REJECT` · `SUBSCRIBE TO PRO`

---

## VISUAL FOUNDATIONS

### Colour
Obsidian and gilt. No pastels, no bright primaries, no two accents on one surface.

**Grounds** — one ground, four elevations: `--ink-0 #08080A` page · `--ink-1 #0F0F12` card · `--ink-2 #16161A` raised · `--ink-3 #1E1E23` hover · `--ink-4 #26262C` well. Depth is luminance, never hue.

**Gilt** (inherited verbatim) — `--gold #C9A84C`, `--gold-light #D4B65C`, `--gold-pale #E8D5A3`, `--gold-dark #B0923F`, borders at 8% / 20% / 45% alpha. Gold is punctuation: one gold-filled control per surface, hairlines and active indicators elsewhere. **Gold is a brand colour and is never a state.**

**Royal secondaries** — `--sapphire #3E5A8C` (+ `--sapphire-light #8FA8CE` for text) carries agent-intelligence cues, replacing Aether's indigo; `--burgundy #722F37` (+ `--burgundy-light`) is ceremonial and appears on offers/negotiation only. Never both on one screen.

**Text** — warm parchment `--fg-1 #F5F1E8` down through 62% / 46% / 34%. Body copy never sits at pure white.

**State** — six load-bearing tones: `ok #6FAF8D` · `warn #C8873A` (copper, never gold) · `danger #B9544B` · `info #7C93BE` · `neutral #8C8A82` (no data / not measured — **never** ok) · `degraded #A08CB4` (produced nothing but did not fail — never ok, never danger). The word always carries the meaning; colour is redundant reinforcement.

**Selection** `rgba(201,168,76,.30)` on `#FDF8F1`. **Focus** 2px `#C9A84C` at 2px offset with a 5px `rgba(201,168,76,.15)` glow. **Scrollbar** gold gradient thumb on a transparent track.

### Typography
- **Display — AB Marquee** (self-hosted, 300/400/500/700/900). Stencil face with two horizontal cuts through every letter; all caps by design (lowercase codepoints render as capitals). Every heading, the wordmark, pull quotes.
- **Body / UI — AB Sans** (self-hosted, 300–900). Full lowercase humanist sans. All prose, nav, labels, buttons, metadata.
- **Data — JetBrains Mono** (Google Fonts). **Substitution:** the baseline ships no monospace and every Aether numeral is tabular. Every number, score, ID, timestamp and salary uses it with `font-variant-numeric: tabular-nums`.
- Fallbacks: `Playfair Display, Georgia, serif` / `DM Sans, Helvetica Neue, sans-serif`.
- Scale: 12 · 13 · 14 · 15 · 18 · 22 · 28 · 36 · 48 · 72px. Tracking widens as size drops. One display weight per screen.
- **The one gilded gesture:** `.text-gilt` (static gold gradient text) or `.shimmer-gilt` (3s sweep) on a single heading per screen. Never on body copy.

### Backgrounds & texture
- `.atmos-page` — obsidian with a bounded vignette, a gold bloom at top-left and a sapphire counterweight at top-right, `background-attachment: fixed`. No gradient on the base layer of a card.
- `.atmos-hero` — a light *rig* behind the title band: a tight gold core, a wide faint bloom, a sapphire counterweight, blurred 26px, closed by a 1px horizon rule that fades to nothing. Entirely static.
- `.film-grain` — fractal-noise SVG at 1.5% opacity on ceremonial bands.
- `.band-recessed` — separates sections with a few points of white lift, never a border.
- Photography, when used: `saturate(0.85) contrast(1.1)` under a heavy scrim. There is no illustration system.

### Cards & elevation
- `.elev-1` card · `.elev-2` raised/selected · `.elev-3` overlay (the only content-adjacent blur) · `.gilt-card` ceremonial glass with a gold hairline and a diagonal shine that sweeps on hover.
- **Blur is chrome-only:** command bar, mobile sheet, tab bar, `.elev-3`. Content surfaces stay opaque so a hundred scrolling rows never composite a hundred blurs.
- Hover on a card: border brightens to `--hairline-strong` (or `--gold-border-strong` when selected), `translateY(-2px)` on gilt cards only. Selected rows gain a 3px gold left rail — never a colour wash.
- Press: no shrink. Lift plus glow is the whole interaction language.

### Radii
`2px` buttons/chips/badges (the baseline's sharp-edge nod) · `4px` small · `6px` inputs · `8px` inner panels · `10px` list rows and tiles · `14px` sections, stat blocks, modals · `9999px` dots and quota tracks only.

### Shadows
`0 0 20px rgba(201,168,76,.28)` gilt glow (primary hover only) · `0 1px 2px rgba(0,0,0,.45)` raised · `0 16px 40px -12px rgba(0,0,0,.8)` overlay · `0 10px 40px rgba(0,0,0,.55)` deep. Never a shadow on every element; depth signals hierarchy.

### Motion
One curve — `cubic-bezier(0.25, 1, 0.5, 1)`. Durations 120ms (colour) / 180ms (lift, border) / 260ms (enter, overlay) / 700ms (shine) / 3s (gilt shimmer). Entrances fade, slide 12px, or scale from 0.97. **Only a genuinely live thing animates:** `ok` pulses, `warn` breathes, everything else is still — a moving background would be a claim that something moved. `prefers-reduced-motion` clamps every animation and transition to one frame.

### Layout
- Rail 248px (64px collapsed), viewport-pinned, colour-flat against the page with a hairline right edge — never its own panel.
- Command bar 64px, sticky, `chrome-blur`.
- Content padding 28–32px; grid gaps 16–22px; card padding 20–24px. Public sections breathe at 112px.
- `.container-ae` = 85% width, max 1400px (90% at 1024, 92% at 768).
- Grids: KPI strip 4-up (auto-fit at 190px), work surfaces 7/5, two-pane browsers 400px + fluid, studio 3-pane.
- Touch targets never below 44px at mobile widths.

### Transparency & blur
Used for chrome and for the ceremonial `.gilt-card` only. Data surfaces are opaque; a translucent panel over a scrolling list is a performance cost with no visual gain on an opaque ground.

---

## ICONOGRAPHY

- **Font Awesome 6** (`fa-solid`) is the product's icon set — the codebase renders `<i className="fa-solid fa-gauge-high" />` throughout, loaded from `https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css`. This system keeps it; every card and kit links that CDN.
- Icons inherit `currentColor` — usually `--gold` inside a bordered tile, `--text-secondary` inline, a state colour when they mark a state.
- Sizes: 10px metadata · 11–12px in buttons and tiles · 13px nav and command bar · 15px feature marks.
- Canonical glyphs: `fa-gauge-high` dashboard · `fa-magnifying-glass` jobs/search · `fa-file-lines` resume · `fa-envelope-open-text` cover letters · `fa-book-bookmark` story bank · `fa-paper-plane` applications · `fa-microphone-lines` interviews · `fa-handshake` networking · `fa-robot` agents · `fa-chart-line` analytics · `fa-scale-balanced` offers · `fa-gear` settings · `fa-shield-halved` approvals · `fa-satellite-dish` discovery · `fa-pen-nib` tailoring · `fa-bolt` run · `fa-circle-info` disclosure.
- **No emoji. No custom illustration. No hand-drawn SVG.** The only bitmap asset is the product's own mark.

### Logo
`assets/aether-mark.png` (256px) and `assets/aether-mark-512.png` are the product's real icons, copied from `apps/web/src/app/icon.png` / `apple-icon.png`: a gold compass-and-orbit "A" on black. Never redraw, recolour or reconstruct it. Clear space equals half the mark's width. `assets/favicon.ico` is the browser icon. There is no separate horizontal logotype in the sources — the lockup sets the name in AB Marquee beside the mark (`Wordmark`).

---

## INDEX

### Root
| File | What it is |
|---|---|
| `readme.md` | This guide |
| `SKILL.md` | Agent-skill manifest |
| `github.md` | Source-repo association and sync record |
| `styles.css` | The single CSS entry point — `@import` list only |
| `tokens/` | `fonts.css` `colors.css` `typography.css` `spacing.css` `elevation.css` `motion.css` |
| `fonts/` | AB Marquee + AB Sans, 10 self-hosted `.ttf` files |
| `assets/` | `aether-mark.png` `aether-mark-512.png` `favicon.ico` |
| `guidelines/` | 18 foundation specimen cards (Colors, Type, Spacing, Brand) |
| `preview/ds-preview-loader.js` | Preview-only shim so cards render before the bundle is compiled |

### Components — `window.<Namespace>`
| Group | Components |
|---|---|
| `components/core/` | **Button** · **StatusBadge** · **Chip** |
| `components/surfaces/` | **Section** · **ListCard** · **StatBlock** |
| `components/navigation/` | **PageHeader** · **SegmentedControl** |
| `components/brand/` | **Wordmark** · **OrnamentDivider** |
| `components/feedback/` | **MetricTooltip** · **InlineNotice** |

Every component maps to a primitive the source defines: `Button`/`Chip`/`ListCard` from `components/ui/recipes.ts`, `StatusBadge` and `StatBlock` and `Section` and `SegmentedControl` from `components/ui/*`, `PageHeader` from `components/shell/PageHeader.tsx`, `MetricTooltip` from `components/MetricTooltip.tsx`.

**Intentional additions**
- **Wordmark** — the sources build the lockup inline in four places (rail, login, pricing, footer); one component keeps the mark from being redrawn.
- **OrnamentDivider** — inherited from the baseline, not present in Aether. It is what makes the public surface read as ceremonial rather than merely dark.
- **InlineNotice** — the sources hand-roll the same bordered message band on eight screens (widget errors, checkout notices, quality-floor disclosures, quota warnings). Consolidated so the degrade tone cannot drift into red or green.

### UI kits
| Kit | Screens |
|---|---|
| `ui_kits/app/` | Command center — Dashboard hub, Job Discovery, Resume Studio, Agent Orchestration, plus the rail/command-bar shell and a placeholder for the nine sections not recreated |
| `ui_kits/public/` | Public site — Pricing, Sign in / Create account, signed-in hand-off, nav and footer |

### Screen map
| Kit screen | Built from |
|---|---|
| `ui_kits/app/Shell.jsx` | `components/shell/Rail.tsx`, `components/shell/CommandBar.tsx`, `components/mobile-tab-bar.tsx`, `lib/navigation.ts`, `lib/navigation-groups.ts` |
| `ui_kits/app/DashboardScreen.jsx` | `app/dashboard/page.tsx`, `components/dashboard/DashboardStats.tsx`, `components/telemetry/ActivityTicker.tsx`, `components/charts/Funnel.tsx` |
| `ui_kits/app/JobsScreen.jsx` | `app/dashboard/jobs/page.tsx` |
| `ui_kits/app/ResumeScreen.jsx` | `app/dashboard/resume/page.tsx`, `components/resume/ChangeList.tsx`, `components/cover-letters/KeywordCoveragePanel.tsx`, `EvidenceTracePanel.tsx` |
| `ui_kits/app/AgentsScreen.jsx` | `app/dashboard/agents/page.tsx`, `components/agents/{AgentConfigGrid,ConductorBand,AgentPolicyPanel,ProviderConnections}.tsx` |
| `ui_kits/public/PricingScreen.jsx` | `app/pricing/page.tsx` |
| `ui_kits/public/AuthScreen.jsx` | `app/login/page.tsx`, `components/PublicFooter.tsx` |

---

## Using it

```html
<link rel="stylesheet" href="styles.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<body class="atmos-page">
```

Then load React and the compiled bundle, and compose from the namespace:

```js
const { Button, Section, StatBlock, PageHeader } = window.<Namespace>;
```

Style against the tokens (`var(--gold)`, `var(--ink-1)`, `var(--font-display)`) and the role classes (`.type-page`, `.type-meta`, `.mono`, `.elev-1`) rather than literal values.

## Caveats
- The live deployment could not be signed into from this environment, so nothing here is derived from the running app — only from the repository.
- Plan prices, feature bullets, job listings, agent names and all figures in the kits are **fixtures**. The product reads them from its API.
- The data face (JetBrains Mono) is a CDN substitution; the two brand faces are self-hosted.
- Charts are represented by the funnel and the meter patterns only — the source's 12-chart kit (`components/charts/`) is not recreated.
- Mobile surfaces (`mobile-dashboard`, `mobile-approval`, the tab bar and nav sheet) are documented but not built as screens.
