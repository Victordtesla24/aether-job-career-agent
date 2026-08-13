"use client";

/**
 * Real-Time Market Pulse — activity heatmap, jobs-by-source donut,
 * top skills, job-search progress index, employer activity, recruiter trends,
 * market-vs-you and trend indicators (wireframe: analytics.html an09–an17,
 * DEF-005..011). Backed by GET /analytics/market-pulse.
 */
import { useEffect, useState } from "react";

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

function sparkPoints(series: number[], w = 120, h = 36) {
  // A 0/1-point series would divide by zero below (NaN polyline coords);
  // render a flat line instead.
  const pts = series.length >= 2 ? series : [series[0] ?? 0, series[0] ?? 0];
  const max = Math.max(...pts, 1);
  const min = Math.min(...pts);
  const range = max - min || 1;
  return pts
    .map((v, i) => `${(i / (pts.length - 1)) * w},${h - ((v - min) / range) * (h - 4) - 2}`)
    .join(" ");
}

export default function MarketPulse() {
  const [data, setData] = useState<MarketPulseData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMarketPulse()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load market pulse"));
  }, []);

  if (error) {
    return <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>;
  }

  if (data === null) {
    return (
      <div className="grid gap-4 xl:grid-cols-3" aria-busy="true" data-testid="market-pulse-skeleton">
        {[0, 1, 2].map((i) => (
          <div key={i} className="glass h-56 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </div>
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
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">Trend Indicators</h3>
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {data.trendIndicators.map((t) => (
          <div key={t.label} className="glass rounded-2xl border border-white/10 p-4">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-aether-muted-dim">{t.label}</span>
              <MetricTooltip
                value={t.delta}
                tooltip={`${t.label}: percentage change vs. the prior period.`}
                className={`mono text-xs font-bold ${t.direction === "up" ? "text-aether-green" : "text-aether-coral"}`}
              />
            </div>
            <svg viewBox="0 0 120 36" className="mt-2 h-9 w-full" aria-hidden="true">
              <polyline
                points={sparkPoints(t.series)}
                fill="none"
                stroke={t.direction === "up" ? "#34D399" : "#FF6B35"}
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        ))}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Jobs by source donut */}
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="sources-donut">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
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
              <text x="50" y="46" textAnchor="middle" transform="rotate(90 50 50)" className="fill-white" fontSize="16" fontWeight="700">
                {data.sourcesTotal}
              </text>
              <text x="50" y="60" textAnchor="middle" transform="rotate(90 50 50)" className="fill-white/40" fontSize="7">
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
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="top-skills">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
            Top Skills in Demand
          </h3>
          {data.topSkills.length === 0 ? (
            // Honest empty state (MV-mobile-dashboard-006 / MV-analytics-006)
            // — matches the pattern already used elsewhere on this screen
            // (e.g. "Market data: not connected") instead of a silent blank
            // area that reads as a rendering bug.
            <p className="text-xs italic text-aether-muted-dim">
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
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="probability-score">
          <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
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
                  stroke="#34D399"
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
          <p className="mt-3 text-[11px] text-aether-muted-dim">
            {score === null ? prob.unmeasuredReason : prob.note}
          </p>
          {!prob.marketDataConnected && (
            // Driven by the SAME server flag as the "Market vs. Your
            // Performance" banner below, so the two surfaces cannot disagree.
            <p
              className="mt-2 text-[11px] italic text-aether-muted-dim"
              data-testid="probability-market-data-state"
            >
              Market data: not connected — this figure uses only your own recorded activity.
            </p>
          )}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-4">
        {/* Activity heatmap */}
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="activity-heatmap">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
            Weekly Activity
          </h3>
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
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="employer-activity">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
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

        {/* Recruiter trends */}
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="recruiter-trends">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
            Recruiter Activity
          </h3>
          <svg viewBox="0 0 120 36" className="h-16 w-full" aria-hidden="true">
            <polyline
              points={sparkPoints(data.recruiterTrends.series)}
              fill="none"
              stroke="#818CF8"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
          <div className="mt-3 space-y-2">
            {data.recruiterTrends.rows.map((r) => (
              <div key={r.label} className="flex items-center justify-between text-xs">
                <span className="text-aether-muted">{r.label}</span>
                <span className="mono text-aether-green">{r.delta}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Market vs you */}
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="market-vs-you">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
            Market vs. Your Performance
          </h3>

          {(() => {
            const anyConnected = data.marketVsYou.comparisons.some((c) => c.connected);
            if (!anyConnected) {
              return (
                <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                  <p className="text-xs font-semibold text-amber-300">External market benchmark unavailable</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-aether-muted-dim">
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

          <div className="space-y-4">
            {data.marketVsYou.comparisons.map((c, i) => {
              // Narrowed to a local const so JSX below can treat it as
              // `number` without a non-null assertion (BRIEF-B: connected &&
              // market !== null is the ONLY condition that draws the bar).
              const marketValue = c.connected ? c.market : null;
              const max = Math.max(c.market ?? 0, c.you ?? 0, 1);
              return (
                <div key={c.label} data-testid={`market-comparison-row-${i}`}>
                  <p className="mb-1.5 text-xs text-aether-muted">{c.label}</p>
                  <div className="space-y-1">
                    {marketValue !== null ? (
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <div
                            className="h-2 rounded-full bg-white/20"
                            style={{ width: `${(marketValue / max) * 70}%` }}
                          />
                          <span className="mono text-[10px] text-aether-muted-dim">
                            market {formatMarketValue(marketValue, c.unit)}
                          </span>
                        </div>
                        {c.marketNote && <p className="text-[10px] text-aether-muted-dim">{c.marketNote}</p>}
                        <DataAsOfLabel iso={c.dataAsOf} className="block text-[10px] text-aether-muted-dim" />
                      </div>
                    ) : (
                      <p className="text-[10px] italic text-aether-muted-dim">Market data: not connected</p>
                    )}
                    {c.you === null ? (
                      <p className="text-[10px] text-aether-coral">—</p>
                    ) : (
                      <div className="flex items-center gap-2">
                        <div className="h-2 rounded-full bg-aether-coral" style={{ width: `${(c.you / max) * 70}%` }} />
                        <span className="mono text-[10px] text-aether-coral">
                          you {formatMarketValue(c.you, c.unit)}
                        </span>
                      </div>
                    )}
                  </div>
                  {c.footnote && <p className="mt-1 text-[10px] italic text-aether-muted-dim">{c.footnote}</p>}
                </div>
              );
            })}
          </div>
          <p className="mt-4 text-[11px] text-aether-muted-dim">{data.marketVsYou.summary}</p>
        </div>
      </div>
    </section>
  );
}
