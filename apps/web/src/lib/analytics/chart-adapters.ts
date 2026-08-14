/**
 * S-UI-REBUILD §4 — pure adapters from already-fetched API shapes to chart-kit
 * props.
 *
 * They exist as pure functions for one reason: the honesty rules that live in
 * the DATA can then be pinned without mounting a page. `<Histogram>` renders a
 * zero-count bucket as a baseline tick and a `null` bucket as "not measured" —
 * but that is only worth anything if the adapter did not quietly turn one into
 * the other on the way in.
 *
 * No adapter here fetches, caches or reshapes wiring. Each one takes what a
 * page already has and hands it to the kit.
 */
import type { FunnelStep, HistogramBucket, RadarDimension } from "../../components/charts";
import type { AtsDistribution, Funnel } from "../api/analytics";

/**
 * The application funnel's five stages, in order.
 *
 * Every stage here is MEASURED — the endpoint counts rows, and a stage with no
 * rows is a real zero, not an absent measurement. So no value is ever `null`,
 * and the kit's C-1 zero tick (not C-2's "—") is the correct rendering.
 */
export function funnelSteps(funnel: Funnel): FunnelStep[] {
  return [
    {
      label: "Jobs found",
      value: funnel.jobs_found,
      // M-04/M-06: this is cumulative all-time discovery and is legitimately
      // larger than the Jobs board's live list (open, un-archived postings).
      // Saying so is what stops the two numbers reading as a data bug.
      note: "Every job discovered for you across all time — the Jobs board lists only currently-open postings, so its count is usually lower.",
    },
    { label: "Applied", value: funnel.applied },
    { label: "Screened", value: funnel.screened },
    { label: "Interviewed", value: funnel.interviewed },
    { label: "Offers", value: funnel.offers },
  ];
}

/**
 * ATS score distribution.
 *
 * The API returns a count per band and every band it returns was counted, so a
 * `0` stays a `0`. The `range` string is passed through whole: the current page
 * renders `range.split("-")[0]`, which turns the band "0-19" into the axis
 * value "0" and loses the width of the bucket.
 */
export function atsBuckets(ats: AtsDistribution): HistogramBucket[] {
  return ats.buckets.map((bucket) => ({ range: bucket.range, count: bucket.count }));
}

/**
 * The 10-dimension fit profile.
 *
 * Source: `AgentPolicy.metricSnapshot.dimensionScores` — a record of the
 * dimensions the scorer actually evaluated, already fetched by the Analytics
 * page via `GET /analytics/agent-policy`. **No new endpoint**, per §5.2.
 *
 * A dimension absent from that record was NOT scored, and this is the single
 * most dangerous chart in the product: collapsing an unmeasured dimension to
 * the centre would draw a specific false claim about the candidate. So the
 * unmeasured arm carries no `score` field at all — the same fail-closed shape
 * `lib/scoring/provenance.ts` uses — and the kit renders it as a hollow marker
 * on the outer ring with a struck-through label.
 *
 * `expected` names how many dimensions the scorer is supposed to produce. A
 * shortfall is stated by the chart, never padded with invented spokes.
 */
export const FIT_DIMENSION_LABELS = [
  "Role alignment",
  "Seniority",
  "Domain",
  "Tech stack",
  "Responsibilities",
  "Impact",
  "Team fit",
  "Location",
  "Compensation",
  "Growth",
] as const;

export function fitDimensions(
  dimensionScores: Record<string, number>,
  // Annotated `number`, not inferred: `FIT_DIMENSION_LABELS` is `as const`, so
  // its `.length` is the literal type `10` and would make every other arity a
  // type error at the call site.
  expected: number = FIT_DIMENSION_LABELS.length,
): RadarDimension[] {
  const measuredLabels = Object.keys(dimensionScores);
  const dims: RadarDimension[] = measuredLabels.map((label) => ({
    label,
    measured: true,
    score: dimensionScores[label],
  }));

  // Name the dimensions the scorer is expected to produce but did not, using
  // the canonical list, so the gap is legible instead of merely a short chart.
  const placeholders = FIT_DIMENSION_LABELS.filter(
    (label) => !measuredLabels.includes(label),
  );

  let i = 0;
  while (dims.length < expected) {
    const label = placeholders[i] ?? `Dimension ${dims.length + 1}`;
    i += 1;
    dims.push({
      label,
      measured: false,
      // `reason` (not `note`) is the kit's field on the unmeasured arm — it is
      // what reaches the hidden data table as "not measured — <reason>".
      reason: "Not scored yet — no agent run has evaluated this dimension for you.",
    });
  }

  return dims.slice(0, Math.max(expected, measuredLabels.length));
}

/*
 * NOT PROVIDED: a `sourceSegments` adapter for `<Donut>`.
 *
 * `GET /analytics/market-pulse` returns `sources[].value` as an INTEGER
 * PERCENTAGE, largest-remainder rounded so the slices sum to exactly 100
 * (`apps/api/app/routers/analytics.py` — `raw_pcts`/`floored`), and the backend
 * has already grouped its own "Other" slice. It does NOT send per-source
 * counts.
 *
 * `<Donut>` refuses to "show a percentage with no denominator": it puts
 * absolute counts beside every share and the real total in the centre. Feeding
 * it percentages would make the centre read "100" and print each percentage
 * where a count belongs — and deriving counts as `pct * sourcesTotal / 100`
 * would invent precision the server deliberately rounded away.
 *
 * So the source-mix donut stays on its existing (correct for percentages)
 * rendering this batch, and moving it to the kit is blocked on the API
 * exposing a per-source count. Recorded as a finding rather than papered over.
 */
