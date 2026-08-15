"use client";

/**
 * Real-Time Market Pulse — activity heatmap, jobs-by-source donut,
 * top skills, job-search progress index, employer activity, recruiter trends,
 * market-vs-you and trend indicators (wireframe: analytics.html an09–an17,
 * DEF-005..011). Backed by GET /analytics/market-pulse.
 */
import { useEffect, useState } from "react";

import {
  CHART_PALETTE,
  HAIRLINE_STRONG,
  STATE,
  TRACK,
  ZERO_TICK_WIDTH,
  barLength,
  barPercent,
} from "../charts";
import { fetchMarketPulse, type MarketPulse as MarketPulseData } from "../../lib/api/workspaces";
import MetricTooltip from "../MetricTooltip";

const HEAT = ["bg-white/5", "bg-aether-coral/20", "bg-aether-coral/40", "bg-aether-coral/70", "bg-aether-coral"];

function donutSegments(sources: MarketPulseData["sources"]) {
  const C = 2 * Math.PI * 40; // r=40
  let offset = 0;
  return sources.map((s) => {
    const len = (s.value / 100) * C;
    const seg = { ...s, dasharray: `${len} ${C - len}`, dashoffset: -offset };
    offset += len;
    return seg;
  });
}

/**
 * Render a value the way its unit calls for (D-0042 / I2 BRIEF-B): "A$" is a
 * PREFIX with thousands separators (A$147,925); any other unit (e.g. "%")
 * stays a SUFFIX as before; no unit is just the formatted number.
 */
function formatMarketValue(value: number, unit?: string): string {
  const formatted = new Intl.NumberFormat("en-AU").format(value);
  if (unit === "A$") return `A$${formatted}`;
  return unit ? `${formatted}${unit}` : formatted;
}

/**
 * Human-readable "data as of" text for an ISO-8601 timestamp, formatted in a
 * FIXED locale + timezone (en-AU / UTC) so it renders identically in SSR and
 * in tests regardless of the host machine's local timezone. Returns `null` on
 * an unparseable string — the caller omits the label entirely rather than
 * rendering "Invalid Date"/"NaN" (guard required by BRIEF-B).
 */
function formatDataAsOf(iso: string): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-AU", {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

/** Freshness mini-label used both per-row and in the top-level attribution
 * line. Renders nothing (not even a wrapper) for a null/unparseable `iso` —
 * never a crash, never "Invalid Date"/"NaN" text. */
function DataAsOfLabel({ iso, className }: { iso: string | null; className?: string }) {
  if (!iso) return null;
  const label = formatDataAsOf(iso);
  if (label === null) return null;
  return (
    <span className={className}>
      data as of <time dateTime={iso}>{label}</time>
    </span>
  );
}

/**
 * One market-vs-you bar, drawn to the chart kit's rules (ANALYTICS-VIZ round
 * 2, F2). It replaces a hand-rolled `<div style="width: (value/max)*70%">`
 * that had two honesty defects the kit exists to prevent:
 *
 *   · a measured 0 drew a bar of width 0 — indistinguishable from a row that
 *     was never measured at all. `barLength` returns `kind: "zero"`, which is
 *     drawn as the kit's 1px hairline tick in HAIRLINE, never in the series
 *     colour (law C-1);
 *   · there was no track, so the bar's length claimed a scale the reader
 *     could not see. The track IS the shared scale: both bars in a row are
 *     drawn against the same `max`, so their lengths are comparable.
 *
 * `data-mark` is the kit's own marker attribute (see `DivergingBar`), which
 * is what makes these rows genuine marks rather than decorated numerals.
 * The numerals beside each bar remain the proof of magnitude; the bar is
 * never the only place a figure appears.
 */
function ComparisonMark({
  value,
  max,
  colour,
  title,
}: {
  value: number | null;
  max: number;
  colour: string;
  title: string;
}) {
  const { kind, length } = barLength({ value, max, extent: 100, mode: "linear" });
  return (
    <span
      className="relative block h-2 min-w-0 flex-1 overflow-hidden rounded-full"
      style={{ backgroundColor: TRACK }}
      title={title}
    >
      {kind === "value" ? (
        <span
          data-mark="value"
          className="absolute inset-y-0 left-0 block rounded-full"
          style={{ width: barPercent(length), backgroundColor: colour }}
        />
      ) : null}
      {kind === "zero" ? (
        <span
          data-mark="zero"
          data-tone="neutral"
          className="absolute inset-y-0 left-0 block"
          style={{ width: `${ZERO_TICK_WIDTH}px`, backgroundColor: HAIRLINE_STRONG }}
        />
      ) : null}
    </span>
  );
}

/** Most recent `dataAsOf` among CONNECTED rows, skipping unparseable values
 * (never lets one broken row block the freshness line for the others). */
function freshestDataAsOf(comparisons: MarketPulseData["marketVsYou"]["comparisons"]): string | null {
  let best: { iso: string; t: number } | null = null;
  for (const c of comparisons) {
    if (!c.connected || !c.dataAsOf) continue;
    const t = new Date(c.dataAsOf).getTime();
    if (Number.isNaN(t)) continue;
    if (!best || t > best.t) best = { iso: c.dataAsOf, t };
  }
  return best?.iso ?? null;
}

/**
 * MON-016: the trend-indicator tooltip literally claims "vs. the prior
 * period" (the last COMPLETE data point vs. the one immediately before it)
 * — so the rendered up/down signal is derived straight from the series'
 * own tail, rather than trusting a separately-computed `direction` field
 * that could (and, in a live 2026-08-13 audit, did) disagree with what the
 * series itself shows for the most recent period.
 *
 * AX-REV-01 (2026-08-13 re-audit): every `series` passed here is a weekly
 * rollup whose backend query has no upper bound short of "now" — the LAST
 * point is always the current, still-in-progress Melbourne week, never a
 * complete one (mirrors analytics.py's `_pct_delta`, which drops it for the
 * same reason). Comparing it directly against the point before it divides a
 * partial week against a complete one, biasing the signal toward "down"
 * without bound the earlier in the week the page loads. This now always
 * excludes that trailing in-progress point before comparing.
 *
 * R-01/RULING-B: an AVERAGE series (e.g. "Avg job fit score") carries
 * honest `null` gaps for weeks with nothing measured — skipped here (never
 * treated as 0) to find the two most recent COMPLETE weeks that actually
 * have data, mirroring analytics.py's `_pct_delta_avg`.
 */
function priorPeriodDirection(series: Array<number | null>): "up" | "down" | "flat" {
  const complete = series.slice(0, -1).filter((v): v is number => v !== null);
  if (complete.length < 2) return "flat";
  const last = complete[complete.length - 1];
  const prior = complete[complete.length - 2];
  if (last === prior) return "flat";
  return last > prior ? "up" : "down";
}

/**
 * R-03 (AX re-review round 2): splits a trend-indicator series into drawable
 * polyline segments so the chart can never visually contradict the badge/
 * tooltip next to it, both of which exclude the trailing in-progress week
 * (RULING-A) — the ORIGINAL single-polyline render plotted that point
 * unmarked and indistinguishable from a completed week. Returns:
 *   - `complete`: the solid line through every point up to (not including)
 *     the last index — always drawn at full opacity.
 *   - `partial`: the short trailing segment connecting the last KNOWN point
 *     to the final (in-progress) point, rendered at reduced opacity, or
 *     `null` when the final week has no data yet (RULING-B: a `null` final
 *     entry has nothing to draw, which is itself honest — no line is
 *     fabricated across it).
 * Internal `null` gaps (an unscored week in the middle of an average
 * series) simply break the `complete` line rather than being interpolated
 * across, so a genuine data gap reads as a gap, not a flat 0.
 */
function sparkSegments(series: Array<number | null>, w = 120, h = 36) {
  const known = series.filter((v): v is number => v !== null);
  const max = Math.max(...known, 1);
  const min = known.length ? Math.min(...known) : 0;
  const range = max - min || 1;
  const n = series.length;
  const xy = (i: number, v: number) => {
    const x = n > 1 ? (i / (n - 1)) * w : w / 2;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  };

  const lastIdx = n - 1;
  const lastVal = series[lastIdx];

  // A single isolated known point (no adjacent known point on either side)
  // has no line to draw — pushing it as a 1-point "polyline" would render
  // nothing visible anyway, so only runs of 2+ points become a segment.
  const completeRuns: string[] = [];
  let run: string[] = [];
  for (let i = 0; i < lastIdx; i++) {
    const v = series[i];
    if (v === null) {
      if (run.length >= 2) completeRuns.push(run.join(" "));
      run = [];
      continue;
    }
    run.push(xy(i, v));
  }
  if (run.length >= 2) completeRuns.push(run.join(" "));

  let partial: string | null = null;
  if (lastVal !== null) {
    let priorKnownIdx = -1;
    for (let i = lastIdx - 1; i >= 0; i--) {
      if (series[i] !== null) {
        priorKnownIdx = i;
        break;
      }
    }
    partial =
      priorKnownIdx >= 0
        ? `${xy(priorKnownIdx, series[priorKnownIdx] as number)} ${xy(lastIdx, lastVal)}`
        : null; // a single trailing point with no prior data has no line to draw
  }

  return { completeRuns, partial };
}

export default function MarketPulse() {
  const [data, setData] = useState<MarketPulseData | null>(null);
  const [error, setError] = useState<string | null>(null);
  /*
   * S-UI-REBUILD-SPEC §5.1 — "per-widget error card with retry (one widget
   * failing must never blank the page)". This widget had the error card and
   * not the retry: a transient 502 on `GET /analytics/market-pulse` (which
   * takes 8–15s in production) left a dead red strip at the bottom of BOTH
   * flagship screens with no way back short of a full page reload.
   *
   * `attempt` is the effect's only re-run trigger. Mount still issues exactly
   * one request — the network trace for the healthy path is unchanged — and a
   * retry is a user-initiated repeat of the SAME call with the SAME contract.
   */
  const [attempt, setAttempt] = useState(0);
  /*
   * B1 judge round 2, item 1 — the Market view stacked FOUR full-width
   * block-rows (vs. three on Overview and Quality & ROI) and put 7+ distinct
   * visualization types on one screen, reading as assembled rather than
   * composed. The three activity panels below (weekly heatmap, employer
   * hiring list, recruiter sparkline) are the ones a user consults, not the
   * ones they scan — so they start collapsed behind a control that NAMES all
   * three, and expand in place. Nothing is unmounted: every panel, testid and
   * string still exists in the DOM at all times; only what competes for
   * attention on first paint changed.
   */
  const [activityOpen, setActivityOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchMarketPulse()
      .then((next) => {
        if (!cancelled) setData(next);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load market pulse");
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (error) {
    /*
     * D-θ / reference rule 7: the failure is drawn, not dumped. It says which
     * panel failed, states that the rest of the page is unaffected (true — no
     * other widget reads this endpoint), shows the server's own message
     * VERBATIM rather than a friendlier substitute, and offers the one action
     * that can change the state.
     */
    return (
      <section className="space-y-4" data-testid="market-pulse-error">
        <div className="flex items-center gap-2.5">
          <span className="h-2 w-2 shrink-0 rounded-full bg-aether-coral" />
          <h2 className="text-[15px] font-semibold">Real-Time Market Pulse</h2>
          <span className="type-mono-micro text-aether-muted-dim">could not load</span>
        </div>
        <div
          className="elev-1 rounded-[14px] border-l-2 border-l-aether-coral p-5"
          role="alert"
          aria-live="polite"
        >
          <p data-prose="status" className="text-sm font-semibold text-aether-coral">
            Market pulse could not be loaded
          </p>
          <p data-prose="status" className="type-meta mt-1.5">
            Every other figure on this page is unaffected — only this panel failed to load.
          </p>
          <p
            data-prose="status"
            data-prose-source="server"
            className="type-mono-micro mt-3 break-words rounded-lg border border-white/10 bg-black/30 p-2.5 text-aether-muted"
            data-testid="market-pulse-error-detail"
          >
            {error}
          </p>
          <button
            type="button"
            onClick={() => setAttempt((n) => n + 1)}
            data-testid="market-pulse-retry"
            className="mt-4 rounded-lg border border-white/15 bg-white/[0.06] px-3 py-1.5 text-xs font-semibold text-white transition-colors duration-[--dur-fast] hover:border-white/25 hover:bg-white/[0.1] active:translate-y-px"
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  if (data === null) {
    /*
     * X-10 (P1) — this branch WAS three bare `h-56` bordered boxes with no
     * heading, no label and no text of any kind. Because
     * `GET /analytics/market-pulse` takes 8–15s in production (measured:
     * `uat/.../s-ui/b1/before/before-notes.json` — the skeleton is still
     * mounted at 1s/2s/4s/8s and resolved by 15s, on BOTH pages that render
     * this component), those three empty boxes are the state a user meets
     * FIRST, for many seconds, at the bottom of the Dashboard and Analytics.
     * That is what the audit screenshotted four times and filed as "3 empty
     * ghost cards".
     *
     * An unlabelled card is an implicit claim that content exists there
     * (doctrine D-θ; reference-pack rule 7). So the loading state now SAYS
     * what it is doing, in words, at the geometry of the real panel — it can
     * be mistaken neither for an empty card nor for content that has arrived.
     */
    return (
      <section
        className="space-y-4"
        aria-busy="true"
        aria-label="Loading real-time market pulse"
        data-testid="market-pulse-skeleton"
      >
        <div className="flex items-center gap-2.5">
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-aether-violet/60" />
          <h2 className="text-[15px] font-semibold text-aether-muted">Real-Time Market Pulse</h2>
          <span className="type-mono-micro text-aether-muted-dim">loading market data…</span>
        </div>
        {/* Same geometry as the resolved panel, so nothing shifts when it
            lands (the CLS lesson from the analytics summary strip). */}
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="elev-1 rounded-[14px] p-4">
              <div className="h-2.5 w-20 animate-pulse rounded bg-white/10" />
              <div className="mt-3 h-9 w-full animate-pulse rounded bg-white/5" />
            </div>
          ))}
        </div>
        <div className="grid gap-4 xl:grid-cols-3">
          {["Jobs by source", "Top skills in demand", "Market vs you"].map((label) => (
            <div key={label} className="elev-1 rounded-[14px] p-5">
              <p className="type-section">{label}</p>
              <div className="mt-4 h-32 animate-pulse rounded-xl bg-white/5" />
              <p data-prose="status" className="type-meta mt-3">Loading…</p>
            </div>
          ))}
        </div>
      </section>
    );
  }

  const ringC = 2 * Math.PI * 42;
  const prob = data.probability;
  const score = prob.score;

  return (
    <section className="space-y-4" data-testid="market-pulse">
      <div className="flex items-center gap-2.5">
        <span className="h-2 w-2 rounded-full bg-aether-violet live-dot" />
        <h2 className="text-[15px] font-semibold">Real-Time Market Pulse</h2>
        <span className="mono text-[11px] text-aether-muted-dim">hiring &amp; recruitment trends · AU</span>
        <MetricTooltip
          value=""
          tooltip="A live snapshot of hiring-market activity in your target region — job-source mix, in-demand skills, employer and recruiter activity, and how your metrics compare to the market."
        />
      </div>

      {/* Trend indicator tiles */}
      <div data-testid="trend-indicators">
        <h3 className="mb-3 type-section">Trend Indicators</h3>
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {data.trendIndicators.map((t) => {
          // MON-016/AX-REV-01: derive the rendered signal from the series'
          // own last two COMPLETE points (the true "prior period" the
          // tooltip claims), not from `t.direction` alone.
          const isUp = priorPeriodDirection(t.series) === "up";
          // R-04/RULING-C: "new"/"insufficient-data" are not a percentage
          // and must never render through green/coral percent styling —
          // a neutral badge, matched by tooltip copy that states the real
          // reason instead of the generic "percentage change" claim.
          const isPercent = t.deltaKind === "percent";
          const badgeClass = !isPercent
            ? "text-aether-muted-dim"
            : isUp
              ? "text-aether-green"
              : "text-aether-coral";
          const strokeColor = !isPercent ? "#8C8A82" : isUp ? "#6FAF8D" : "#B9544B";
          const tooltipCopy =
            t.deltaKind === "new"
              ? `${t.label}: no prior completed period to compare — this is new activity.`
              : t.deltaKind === "insufficient-data"
                ? `${t.label}: not enough completed-period data yet to compute a change.`
                : `${t.label}: percentage change vs. the prior period (this week's still-in-progress data isn't counted yet).`;
          const { completeRuns, partial } = sparkSegments(t.series);
          return (
            <div key={t.label} className="elev-1 rounded-[14px] p-4" data-testid="trend-indicator-tile">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-aether-muted-dim">{t.label}</span>
                <MetricTooltip
                  value={t.delta}
                  tooltip={tooltipCopy}
                  className={`mono text-xs font-bold ${badgeClass}`}
                />
              </div>
              <svg viewBox="0 0 120 36" className="mt-2 h-9 w-full" aria-hidden="true">
                {completeRuns.map((points, i) => (
                  <polyline
                    key={i}
                    points={points}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                ))}
                {partial && (
                  // RULING-A: the trailing point is always the current,
                  // still-in-progress week — excluded from the delta above,
                  // so it renders visually distinct (reduced opacity) here
                  // too, rather than looking like a completed data point.
                  <polyline
                    points={partial}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeOpacity="0.35"
                    data-testid="trend-partial-segment"
                  />
                )}
              </svg>
            </div>
          );
        })}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Jobs by source donut */}
        <div className="elev-1 rounded-[14px] p-5" data-testid="sources-donut">
          <h3 className="mb-4 type-section">
            Jobs by Source
          </h3>
          <div className="flex items-center gap-5">
            <svg viewBox="0 0 100 100" className="h-32 w-32 -rotate-90" role="img" aria-label="Jobs by source">
              {donutSegments(data.sources).map((s) => (
                <circle
                  key={s.label}
                  cx="50"
                  cy="50"
                  r="40"
                  fill="none"
                  stroke={s.color}
                  strokeWidth="12"
                  strokeDasharray={s.dasharray}
                  strokeDashoffset={s.dashoffset}
                />
              ))}
              <text
                x="50"
                y="46"
                textAnchor="middle"
                transform="rotate(90 50 50)"
                className="font-mono tabular-nums"
                fill="#F5F1E8"
                fontSize="16"
                fontWeight="700"
              >
                {data.sourcesTotal}
              </text>
              <text x="50" y="60" textAnchor="middle" transform="rotate(90 50 50)" fill="rgba(245,241,232,0.46)" fontSize="7">
                {data.sourcesLabel}
              </text>
            </svg>
            <div className="space-y-2">
              {data.sources.map((s) => (
                <div key={s.label} className="flex items-center gap-2 text-xs">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: s.color }} />
                  <span className="text-aether-muted">{s.label}</span>
                  <span className="mono text-aether-muted-dim">{s.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Top skills */}
        <div className="elev-1 rounded-[14px] p-5" data-testid="top-skills">
          <h3 className="mb-4 type-section">
            Top Skills in Demand
          </h3>
          {data.topSkills.length === 0 ? (
            // Honest empty state (MV-mobile-dashboard-006 / MV-analytics-006)
            // — matches the pattern already used elsewhere on this screen
            // (e.g. "Market data: not connected") instead of a silent blank
            // area that reads as a rendering bug.
            <p data-prose="empty" className="text-xs italic text-aether-muted-dim">
              Not enough job data yet to surface top skills — matched jobs with
              recognized skill keywords will populate this.
            </p>
          ) : (
            <div className="space-y-3">
              {data.topSkills.map((s) => (
                <div key={s.skill}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-aether-muted">{s.skill}</span>
                    <span className="mono">{s.demand}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/10">
                    <div className="h-1.5 rounded-full bg-aether-violet" style={{ width: `${s.demand}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Job-search progress index (PROD-UAT-2026-08-03 F-04).
         *
         * This panel used to headline "Your Job Probability Score — likelihood
         * of landing an offer in the next 60 days", one of whose factors was
         * the user's own saved-job count relabelled "Market demand", on the
         * same screen as the "Market data: not connected" banner below. Both
         * the market factor and the offer-likelihood claim are gone; every
         * string rendered here now comes from the API so the copy cannot drift
         * away from what the server actually computed.
         *
         * `score` / `value` are `number | null`, so a not-measured signal is a
         * compile error to render as a number — it takes the "not measured"
         * branch, matching LetterQualityPanel and the Resume Studio panels. */}
        <div className="elev-1 rounded-[14px] p-5" data-testid="probability-score">
          <h3 className="mb-3 flex items-center gap-1.5 type-section">
            <MetricTooltip label={prob.label} value="" tooltip={prob.methodology} />
          </h3>
          <div className="flex items-center gap-5">
            {score === null ? (
              <div
                className="flex h-28 w-28 shrink-0 items-center justify-center rounded-full border border-dashed border-white/15 text-center text-[10px] leading-tight text-aether-muted-dim"
                role="img"
                aria-label={`${prob.label}: not measured`}
                data-testid="probability-not-measured"
              >
                not
                <br />
                measured
              </div>
            ) : (
              <svg viewBox="0 0 100 100" className="h-28 w-28 -rotate-90" role="img" aria-label={`${prob.label} ${score}%`}>
                <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="10" />
                <circle
                  cx="50"
                  cy="50"
                  r="42"
                  fill="none"
                  stroke="#6FAF8D"
                  strokeWidth="10"
                  strokeLinecap="round"
                  strokeDasharray={`${(score / 100) * ringC} ${ringC}`}
                />
                <text x="50" y="55" textAnchor="middle" transform="rotate(90 50 50)" className="fill-white" fontSize="20" fontWeight="700">
                  {score}%
                </text>
              </svg>
            )}
            <div className="flex-1 space-y-2">
              {prob.factors.map((f) => (
                <div key={f.label}>
                  <div className="mb-0.5 flex justify-between text-[10px]">
                    <span className="text-aether-muted-dim">{f.label}</span>
                    {f.value === null ? (
                      <span className="italic text-aether-muted-dim">not measured</span>
                    ) : (
                      <span className="mono">{f.value}</span>
                    )}
                  </div>
                  {f.value === null ? null : (
                    <div className="h-1 rounded-full bg-white/10">
                      <div className="h-1 rounded-full bg-aether-green" style={{ width: `${f.value}%` }} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
          <p
            data-prose="caption"
            data-prose-source="server"
            className="mt-3 text-[11px] text-aether-muted-dim"
          >
            {score === null ? prob.unmeasuredReason : prob.note}
          </p>
          {!prob.marketDataConnected && (
            // DECOUPLED (D-0042 / R5): governed ONLY by probability.marketDataConnected.
            // The "Market vs. Your Performance" banner below is derived independently
            // from comparisons[].connected — the two surfaces are explicitly allowed
            // to disagree once Market vs. You has live Adzuna data.
            <p
              data-prose="caption"
              className="mt-2 text-[11px] italic text-aether-muted-dim"
              data-testid="probability-market-data-state"
            >
              Market data: not connected — this figure uses only your own recorded activity.
            </p>
          )}
        </div>
      </div>

      {/*
        THE CLOSING BAND — recomposed twice (doctrine D-δ: density is a
        decision).

        ROUND 1 fixed the padding waste: `grid gap-4 xl:grid-cols-4` stretched
        four wildly unequal panels to their tallest sibling, so three compact
        signals carried ~300px of dead space apiece. That became a 7/5 split.

        ROUND 2 (B1 judge, items 1 and 2) fixes what the 7/5 split could not:
        the band still put four block-rows and 7+ visualization types on the
        Market view at once, and "Market vs. Your Performance" was still the
        densest panel in Dashboard+Analytics — three stacked comparisons, each
        carrying a market bar, a you bar, a freshness stamp AND a multi-line
        italic footnote, ~560px of small type in one column.

        The band is now ONE composed row plus a named disclosure:
          - Market vs. Your Performance runs the full width as three compact
            side-by-side comparisons. The per-row prose (`marketNote`,
            `footnote`) renders VERBATIM on the row it qualifies — never
            truncated, never paraphrased. ROUND 3 (ANALYTICS-VIZ F2) moved it
            out of the info-icon popover and onto the row itself: the panel's
            floating summary paragraph was deleted, and a qualifier of a
            number that is on screen may not be reachable only by hovering
            (U-AX law). The three-across grid is what makes that affordable —
            the density this popover was introduced to fix came from the same
            notes stacked in ONE narrow column.
          - The honesty state itself does NOT move: "Market data: not
            connected" stays inline, on the row, next to the number it
            qualifies, exactly as before. A caveat is only ever collapsed
            together with the claim it governs, never away from it.
          - Weekly Activity, Employer Hiring Activity and Recruiter Activity
            move behind a control that names all three, collapsed by default.
        Same panels, same data, same strings, same testids — what changed is
        how much of it competes for attention at once.
      */}
      <div className="space-y-4">
        {/* Market vs you — the band's headline row. */}
        <div className="elev-1 rounded-[14px] p-5" data-testid="market-vs-you">
          <h3 className="mb-4 type-section">
            Market vs. Your Performance
          </h3>

          {(() => {
            const anyConnected = data.marketVsYou.comparisons.some((c) => c.connected);
            if (!anyConnected) {
              return (
                <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                  <p data-prose="status" className="text-xs font-semibold text-amber-300">External market benchmark unavailable</p>
                  <p data-prose="caption" className="mt-1 text-[11px] leading-relaxed text-aether-muted-dim">
                    Provider: none configured — your figures are derived from your saved jobs and applications.
                  </p>
                </div>
              );
            }
            return (
              <div
                className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-aether-muted-dim"
                data-testid="market-vs-you-attribution"
              >
                <span>Market data: Adzuna Australia</span>
                <DataAsOfLabel iso={freshestDataAsOf(data.marketVsYou.comparisons)} />
              </div>
            );
          })()}

          <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
            {data.marketVsYou.comparisons.map((c, i) => {
              // Narrowed to a local const so JSX below can treat it as
              // `number` without a non-null assertion (BRIEF-B: connected &&
              // market !== null is the ONLY condition that draws the bar).
              const marketValue = c.connected ? c.market : null;
              const max = Math.max(c.market ?? 0, c.you ?? 0, 1);
              // B1 judge round 2, item 2: the server's own explanatory prose,
              // JOINED not edited — every character the API sent still renders
              // in this row, so the definition of "market" and the caveat on
              // "you" stay attached to the numbers they qualify.
              //
              // ANALYTICS-VIZ round 2 (F2): it is now the row's VISIBLE
              // caption rather than the row's popover. The panel-level
              // paragraph that used to carry this panel's provenance is gone,
              // and a qualifier of a number that is on screen may not be
              // hover-only (U-AX law) — so the qualifier moves to where the
              // number it qualifies is drawn, one caption per comparison.
              const detail = [c.marketNote, c.footnote].filter(Boolean).join(" ");
              return (
                // `flex-1` on the market half pins every card's "you" line to
                // the same baseline, so the three comparisons read as one row
                // even though a disconnected row is a line shorter than a
                // connected one carrying a freshness stamp.
                <div key={c.label} className="flex min-w-0 flex-col" data-testid={`market-comparison-row-${i}`}>
                  <p className="mb-2 text-xs text-aether-muted">{c.label}</p>
                  <div className="flex-1 space-y-0.5">
                    {marketValue !== null ? (
                      <>
                        <div className="flex items-center gap-2">
                          <ComparisonMark
                            value={marketValue}
                            max={max}
                            colour={STATE.neutral}
                            title={`Market: ${formatMarketValue(marketValue, c.unit)}`}
                          />
                          <span className="mono shrink-0 text-[10px] text-aether-muted-dim">
                            market {formatMarketValue(marketValue, c.unit)}
                          </span>
                        </div>
                        <DataAsOfLabel iso={c.dataAsOf} className="block text-[10px] text-aether-muted-dim" />
                      </>
                    ) : (
                      <p data-prose="caption" className="text-[10px] italic text-aether-muted-dim">Market data: not connected</p>
                    )}
                  </div>
                  {c.you === null ? (
                    <p className="mt-1.5 text-[10px] text-aether-coral">—</p>
                  ) : (
                    <div className="mt-1.5 flex items-center gap-2">
                      <ComparisonMark
                        value={c.you}
                        max={max}
                        colour={CHART_PALETTE[0]}
                        title={`You: ${formatMarketValue(c.you, c.unit)}`}
                      />
                      <span className="mono shrink-0 text-[10px] text-aether-coral">
                        you {formatMarketValue(c.you, c.unit)}
                      </span>
                    </div>
                  )}
                  {detail ? (
                    <p
                      data-prose="caption"
                      data-prose-source="server"
                      data-testid={`market-comparison-note-${i}`}
                      className="mt-2 text-[10px] leading-[1.5] text-aether-muted-dim"
                    >
                      {detail}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
          {/*
            THE PANEL-LEVEL SUMMARY PARAGRAPH IS GONE (round 2, finding F2).

            `marketVsYou.summary` was three sentences and 300+ characters
            floating under three comparisons, qualifying none of them in
            particular. Every figure it stated is drawn above it, on the row
            that owns it, with that row's own server-authored note now VISIBLE
            beside the mark instead of behind a hover:
              · "N live postings (last 30 days) for your target role in X" →
                the Applications/month row: its market mark, its numeral, its
                freshness stamp, and its `marketNote`, which states the same
                count, location, provider and role-family scope — and adds the
                caveat the summary never had (employer demand is not
                applications sent by other candidates).
              · "Adzuna reports a mean advertised salary of A$X for that same
                search" → the Advertised salary row: same mark, numeral,
                freshness and `marketNote`.
              · The provider attribution and its as-of stamp → the panel's
                attribution line above the grid.
              · "No market data source connected" (the no-provider variant) →
                the amber banner above, which is rendered on exactly the
                condition that matters (no row connected) rather than on
                `postingsLast30d is None`, which could leave the paragraph
                claiming nothing was connected while the salary row was.

            What is NOT re-expressed, and is deliberately not paraphrased into
            a chart it has no data for: the summary's optional 12-month
            all-roles salary range and modal-band sentences. Those two facts
            reach the browser ONLY as prose inside this string — the wire type
            carries no `salaryTrend12m` / `salaryHistogram` field to draw — and
            `apps/api` is untouchable in this slice. Escalated to the
            orchestrator: put those series on the payload and they become a
            real distribution mark on the salary row.
          */}
        </div>

        {/* The disclosure control. It names every panel it holds, so a
            collapsed band is never a claim that nothing is there. */}
        <button
          type="button"
          id="market-activity-toggle"
          aria-expanded={activityOpen}
          aria-controls="market-activity-detail"
          onClick={() => setActivityOpen((open) => !open)}
          data-testid="market-activity-toggle"
          className="elev-1 flex w-full items-center justify-between gap-4 rounded-[14px] px-5 py-3.5 text-left transition-colors duration-[--dur-fast] hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/60"
        >
          <span className="min-w-0">
            <span className="block type-section">Activity detail</span>
            <span className="mt-1 block type-meta">
              Weekly activity, employer hiring signals and recruiter trends
            </span>
          </span>
          <span className="mono flex shrink-0 items-center gap-2 text-[11px] text-aether-muted-dim">
            {activityOpen ? "hide" : "show"}
            <i
              className={`fa-solid text-[10px] ${activityOpen ? "fa-chevron-up" : "fa-chevron-down"}`}
              aria-hidden="true"
            />
          </span>
        </button>

        {/* Mounted always, removed from the layout with the `hidden`
            attribute when collapsed — the same contract the Analytics views
            themselves use (analytics/page.tsx `panelProps`). No display
            utility on this wrapper, so `[hidden]` is free to do its job and
            the parent's `space-y-4` (authored as
            `> :not([hidden]) ~ :not([hidden])`) drops the gap with it. */}
        <div
          id="market-activity-detail"
          role="region"
          aria-labelledby="market-activity-toggle"
          hidden={!activityOpen}
          data-testid="market-activity-detail"
        >
          <div className="grid gap-4 sm:grid-cols-2 sm:items-start xl:grid-cols-3">
        {/* Activity heatmap */}
        <div className="elev-1 rounded-[14px] p-5" data-testid="activity-heatmap">
          <h3 className="mb-1 type-section">
            Weekly Activity
          </h3>
          {/* MON-015: disclose which calendar the day/week boundaries below
           * actually use — sourced from the API, never hardcoded, so this
           * can never drift out of sync with the bucketing it describes. */}
          {data.timezone && (
            <p data-prose="legend" className="mb-3 text-[10px] text-aether-muted-dim" data-testid="heatmap-timezone-label">
              Days bucketed in {data.timezone} time
            </p>
          )}
          <div className="grid grid-cols-7 gap-1.5">
            {data.activityHeatmap.flatMap((week, wi) =>
              week.map((v, di) => (
                <span
                  key={`${wi}-${di}`}
                  className={`aspect-square rounded ${HEAT[Math.min(v, 4)]}`}
                  title={`Week ${wi + 1}, day ${di + 1}: intensity ${v}`}
                />
              )),
            )}
          </div>
          <div className="mt-3 flex items-center gap-1.5 text-[10px] text-aether-muted-dim">
            less
            {HEAT.map((c) => (
              <span key={c} className={`h-2.5 w-2.5 rounded ${c}`} />
            ))}
            more
          </div>
        </div>

        {/* Employer activity */}
        <div className="elev-1 rounded-[14px] p-5" data-testid="employer-activity">
          <h3 className="mb-4 type-section">
            Employer Hiring Activity
          </h3>
          <div className="space-y-3">
            {data.employerActivity.map((e) => (
              <div key={`${e.company}-${e.event}`} className="flex items-start gap-2.5">
                <span
                  className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                    e.signal === "hot" ? "bg-aether-coral" : e.signal === "warm" ? "bg-aether-amber" : "bg-aether-violet"
                  }`}
                />
                <div>
                  <p className="text-xs">
                    <span className="font-semibold">{e.company}</span>{" "}
                    <span className="text-aether-muted">{e.event}</span>
                  </p>
                  <p className="mono text-[10px] text-aether-muted-dim">{e.when}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recruiter trends — the sparkline is a 120-unit viewBox stretched
            to the panel width, so width is the thing it actually needs. It
            takes the full row at the 2-up measure (where it would otherwise
            sit alone in a half-width cell) and its own third at the 3-up. */}
        <div className="elev-1 rounded-[14px] p-5 sm:col-span-2 xl:col-span-1" data-testid="recruiter-trends">
          <h3 className="mb-4 type-section">
            Recruiter Activity
          </h3>
          {(() => {
            // MUST-FIX-1 (AX round-3 final re-review): this used to be a
            // single fully-opaque sparkPoints() polyline, so the trailing
            // in-progress Melbourne week was indistinguishable from a
            // completed one — while the "Avg runs / week" delta directly
            // beneath it (backend _pct_delta) EXCLUDES that same week.
            // sparkSegments() is the SAME remedy already applied to the
            // Trend Indicators tiles (R-03): the trailing segment renders
            // separately, at reduced opacity, so the chart can never
            // visually contradict the badge beside it (RULING-A, applied to
            // every sparkline/series render, not only named instances).
            const { completeRuns, partial } = sparkSegments(data.recruiterTrends.series);
            return (
              <svg viewBox="0 0 120 36" className="h-16 w-full" aria-hidden="true">
                {completeRuns.map((points, i) => (
                  <polyline
                    key={i}
                    points={points}
                    fill="none"
                    stroke="#8FA8CE"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                ))}
                {partial && (
                  <polyline
                    points={partial}
                    fill="none"
                    stroke="#8FA8CE"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeOpacity="0.35"
                    data-testid="trend-partial-segment"
                  />
                )}
              </svg>
            );
          })()}
          <div className="mt-3 space-y-2">
            {data.recruiterTrends.rows.map((r) => {
              // MUST-FIX-1 COMPOUNDING (AX round-3 final re-review): this
              // used to render className="mono text-aether-green"
              // UNCONDITIONALLY — _pct_delta can return a count-only
              // "total" (no comparison at all), "no change"/negative
              // percentages, or "new activity", and all painted success
              // green. Same isPercent/isUp branch the Trend Indicators
              // tiles already use (R-04/RULING-C) — a non-percent kind
              // never carries directional styling, and a percent kind
              // matches its own direction (mirrors the sibling tile's
              // isUp-only convention: "flat"/"down" both render coral).
              const isPercent = r.deltaKind === "percent";
              const deltaClass = !isPercent
                ? "text-aether-muted-dim"
                : r.direction === "up"
                  ? "text-aether-green"
                  : "text-aether-coral";
              return (
                <div key={r.label} className="flex items-center justify-between text-xs">
                  <span className="text-aether-muted">{r.label}</span>
                  <span className={`mono ${deltaClass}`}>{r.delta}</span>
                </div>
              );
            })}
          </div>
        </div>
          </div>
        </div>
      </div>
    </section>
  );
}
