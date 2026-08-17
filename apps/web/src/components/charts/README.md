# Aether chart kit

Hand-built SVG/DOM chart primitives for the Dashboard and Analytics rebuild.
**No charting library** (S-UI-REBUILD-SPEC §4.1): every honesty rule below is a
*rendering* rule that a library's default renderer actively fights, so we would
spend more code overriding a dependency than writing this one.

```tsx
import { Funnel, Histogram, Radar10 } from "@/components/charts";

<Funnel
  title="Application funnel"
  windowLabel="all time — not affected by the period selector"
  steps={[
    { label: "Jobs found", value: 8358 },
    // AUD-META-1: never "Applied"/"Sent" for a count that is only
    // status <> 'draft' — the analytics page labels that stage "Prepared".
    { label: "Prepared", value: 287 },
    { label: "Screened", value: 0 },
  ]}
  mode="share-of-previous"
/>;
```

Charts own **no card, no border, no background**. The gridlines and axis labels
do all the framing (reference-pack rule 5); the card is `<Section>`'s job.

---

## The five laws, and the test that pins each

Every law is enforced mechanically. `assertChartLaws()` runs inside
`<ChartFrame>` before anything is drawn: it **throws** in development and in
tests (so a violation cannot be merged) and **reports via `console.error`** in
production (so a mislabelled chart never white-screens a paying user's
dashboard). It is never silent.

| Law | What it forbids | Enforced by | Pinned by |
|---|---|---|---|
| **C-1 Zero is not a colour** | A zero drawn as a filled coloured mark — the "0 screened / 0-19 ATS" bar that reads as "a few". A zero renders as a **1px hairline tick** at the origin plus a numeral in `state-neutral`. And the inverse: a real value drawn shorter than that tick. | `geometry.ts` → `markKind()` / `barLength()` / `barPercent()` — the one place **every bar-shaped chart** (`<Funnel>`, `<Histogram>`, `<DivergingBar>`) takes its length from; `<ZeroTickRect>` | `laws.test.tsx` › *C-1 — zero is not a colour* (4 cases, incl. "never returns a zero-length bar for a real value"); `funnel.test.tsx` › *C-1 — a zero step*; `histogram.test.tsx` › *C-1 — an empty bucket* **and** *a wide dynamic range cannot invert zero and a real value*; `diverging-bar.test.tsx` › *C-1 — a row that is genuinely level* **and** *a wide dynamic range cannot invert zero and a real value* |
| **C-2 Unmeasured ≠ zero** | `null` rendered as 0, or as an empty-looking mark. `null` renders `—` in `state-neutral`, and the hidden data table spells out **"not measured"** plus the reason. `<ChartFrame>` **throws** when a series mixes `0` and `null` without a `nullMeaning` prop. | `laws.ts` → `assertNullMeaning()`; `<UnmeasuredMark>`; `ChartFrame`'s data table | `laws.test.tsx` › *C-2 — unmeasured is not zero* (incl. "makes ChartFrame itself throw in dev on the ambiguous series"); `histogram.test.tsx` › *is refused outright when the caller does not say what null means*; the whole first block of `radar10.test.tsx` |
| **C-3 The window is part of the chart** | A chart with no stated sample window. `windowLabel` is a required prop (compile time) **and** a runtime assertion, and it renders verbatim in the caption. | `laws.ts` → `assertWindowLabel()` | `laws.test.tsx` › *C-3 — the window is part of the chart* (empty, whitespace-only, dev-throw, verbatim caption) |
| **C-4 Scale is declared** | A silent log scale or a silently truncated axis. `log` renders a `LOG SCALE` chip, `share-of-previous` renders a `SHARE OF PREVIOUS STEP` chip, and any baseline ≠ 0 must set `truncated: true` — otherwise the frame throws. | `laws.ts` → `assertScaleDeclared()`; `ChartFrame` chip + break glyph | `laws.test.tsx` › *C-4 — scale is declared*; `funnel.test.tsx` › *declares a log scale with a visible chip and never silently log-scales*; `trend-line.test.tsx` › *declares a truncated baseline instead of silently starting above zero* |
| **C-5 Colour is redundant** | A tone that carries meaning on its own. Every datum needs a label; every legend swatch sits next to a word; an unmeasured radar axis is struck through as well as greyed. | `laws.ts` → `assertColourRedundancy()` | `laws.test.tsx` › *C-5 — colour is redundant*; `donut.test.tsx` › *pairs every colour with a word (C-5)*; `radar10.test.tsx` › *strikes the axis label so colour is not the only signal*; `heatmap.test.tsx` › *labels every heat step with the value range it stands for* |

Production behaviour is itself pinned: `laws.test.tsx` › *reports loudly instead
of throwing, so a violation never white-screens a paying user*.

**What "the one place" covers, exactly.** `barLength()` owns the length of every
mark whose *length* encodes the value — the three bar-shaped charts named above,
and nothing else, because nothing else in the kit encodes a value as a length.
`<Donut>` encodes with arc angle, `<Radar10>` with vertex radius, `<Heatmap>`
with colour step, `<TrendLine>` with y position; each has its own C-1 rule in
its own section below. The guarantee `barLength()` provides is two-sided and
both sides are pinned by tests: a **zero** is exactly `ZERO_TICK_WIDTH` (1px)
and a **real value** is at least `MIN_VALUE_LENGTH` (1.5) — so a measured value
can never be drawn shorter than a measured nothing, at any dynamic range.
`barPercent()` carries that floor through the 2-decimal rounding used on
percentage-width bars, because rounding is the other way a real value can reach
`0%`. This was a shipped defect, not a hypothetical: `<Histogram>` and
`<DivergingBar>` originally did their own proportional maths, and against a
100,000 dominant a real count of 1 rendered at 0.0016px and 0% respectively —
both *less* visible than the zero beside them.

---

## The seven charts

| Component (spec alias) | What it refuses to do |
|---|---|
| `<Funnel>` (`<FunnelBars>`) | Make 8,358 → 287 → 0 unreadable. `mode="share-of-previous"` or `"log"` makes small steps legible, and **says which encoding is on screen**. The numeral always sits outside the fill in its own mono column. Zero rows get the C-1 tick. |
| `<TrendLine>` | Invent a trend. Fewer than **3 measured points and nothing is drawn**. A gap is drawn as a gap — the stroke stops, a dashed bridge spans it, and the legend says "no data for that interval". A non-zero baseline is an axis break, not a silent exaggeration. Above 2,000 points it switches to canvas (`CANVAS_POINT_THRESHOLD`, the only canvas in the kit) and says so if the browser gives it no drawing context. |
| `<Histogram>` | Draw a 2px bar for an empty bucket (today's analytics page does exactly that via `Math.max(2, …)`). Real y-axis, gridlines, **range** labels (`0-19`, not `0`), per-bucket counts on hover. |
| `<Radar10>` (`<RadarPlot>`) | Collapse an unmeasured dimension to the centre — "the single most dangerous chart in the product", because a centre vertex is a specific false claim about a candidate. An unmeasured dimension gets **no vertex at any radius**, a hollow neutral marker on the outer ring, a dashed bridging edge, a struck-through label, a legend count and a reason in the data table. A stray `score` on a `measured: false` dimension is ignored (fail closed, same rule as `lib/scoring/provenance.ts`). |
| `<Donut>` | Show a percentage with no denominator. Absolute counts sit next to every share, the centre holds the total, sub-2% slivers group into "Other" whose members are named in the tooltip **and still listed individually** in the data table. Percentages are taken against the measured total only. |
| `<DivergingBar>` | Render an unavailable market comparison as "no difference". `available: false` / `connected: false` ⇒ `—` plus the caller's **verbatim** reason and no bar of any length; a real 0 keeps the C-1 tick and its own words ("0 days"). Freshness stamps travel with the value. |
| `<Heatmap>` | Paint "no data" as the lightest heat step. An unmeasured cell gets `surface-1` + a diagonal hatch + "no data" and its reason on hover, and is excluded from the ramp maximum. A measured zero is an empty hairline cell — never step 1 of the ramp. |

---

## Motion

One animation exists: a **one-time reveal on first mount**. Doctrine D-β
("nothing moves unless something moved") and §5.2 ("charts do not animate on
refetch — a chart that re-grows every 30s implies change that may not have
happened") leave no room for more.

`useChartMotion()` runs `off → initial → animating → settled`. After `settled`
the transition styles are **removed**, so a later data update changes values
with no animation — that is what makes "no re-grow on refetch" true rather than
merely intended. Under `prefers-reduced-motion: reduce` the phase stays `off`:
no transform, no transition, no stagger delay, no opacity — the chart is simply
already there (`data-motion="off"` on the frame, asserted in every chart's
*motion* block). The server render and the first client paint also produce final
values, so a chart is never invisible when JavaScript is slow or blocked.

---

## Accessibility

`<ChartFrame>` renders the plot as one `role="img"` with a generated summary,
followed by a visually-hidden `<table>` carrying **every** value in words —
including `not measured — <reason>` for each null. Series longer than 200 rows
are summarised (count, min, max, first, last, unmeasured count) and the caption
says the table is summarised, so a summary is never mistaken for the whole
series.

---

## Two reconciliations worth knowing

1. **Histogram zero buckets.** §4.3 says "zero-count buckets render nothing
   above the baseline"; this slice's brief says "zero-count = 1px tick". Both
   hold: the tick is 1px of `hairline` **on** the baseline, marking where the
   bucket is in the border colour, and rises nothing above the axis in any
   series colour. `histogram.test.tsx` › *sits at the baseline, not above it*
   pins it.
2. **Radar fill with a missing dimension.** The polygon fill still spans the
   measured vertices when a dimension is missing (at 10% instead of 18%,
   `data-partial="true"`), because a chart that drops its fill entirely on one
   missing axis is harder to read, not more honest. What the spec actually
   forbids — a *vertex* implying a value — never happens: the dashed bridge,
   hollow marker, struck label and legend count all name the gap.

## Files

- `ChartFrame.tsx` — chrome, laws, summary, hidden data table, scale chips
- `laws.ts` — `assertChartLaws` and the individual assertions
- `geometry.ts` — `markKind` / `barLength` / `barPercent` (C-1), scales, polar maths, formatting
- `motion.ts` — the reveal phases and reduced-motion contract
- `primitives.tsx` — gridlines, axis labels, zero tick, unmeasured mark, threshold line, empty plot
- `tokens.ts` — palette, heat ramp, state colours, hairlines, durations
- `__tests__/` — 126 assertions, no pixel snapshots: every test queries DOM/SVG structure
