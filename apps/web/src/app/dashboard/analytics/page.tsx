"use client";

/**
 * Analytics — funnel, ATS score distribution and agent ROI, backed by
 * GET /analytics/funnel, /analytics/ats-distribution and /analytics/agent-roi.
 */
import { useCallback, useEffect, useState } from "react";

import MarketPulse from "../../../components/analytics/MarketPulse";
import {
  fetchAgentRoi,
  fetchAtsDistribution,
  fetchConversion,
  fetchFunnel,
  type AgentRoi,
  type AtsDistribution,
  type Conversion,
  type Funnel,
  type Period,
} from "../../../lib/api/analytics";

const PERIODS: Period[] = ["7d", "30d", "90d", "all"];

export default function AnalyticsPage() {
  const [period, setPeriod] = useState<Period>("all");
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [ats, setAts] = useState<AtsDistribution | null>(null);
  const [roi, setRoi] = useState<AgentRoi | null>(null);
  const [conversion, setConversion] = useState<Conversion | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [funnelData, atsData, roiData, conversionData] = await Promise.all([
        fetchFunnel(period),
        fetchAtsDistribution(),
        fetchAgentRoi(),
        fetchConversion(period),
      ]);
      setFunnel(funnelData);
      setAts(atsData);
      setRoi(roiData);
      setConversion(conversionData);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    }
  }, [period]);

  useEffect(() => {
    void load();
  }, [load]);

  const funnelStages = funnel
    ? ([
        ["Jobs Found", funnel.jobs_found],
        ["Applied", funnel.applied],
        ["Screened", funnel.screened],
        ["Interviewed", funnel.interviewed],
        ["Offers", funnel.offers],
      ] as const)
    : null;

  const maxStage = funnelStages ? Math.max(1, ...funnelStages.map(([, v]) => v)) : 1;
  const maxBucket = ats ? Math.max(1, ...ats.buckets.map((b) => b.count)) : 1;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Analytics</h1>
          <p className="text-sm text-aether-muted">
            Funnel conversion, ATS score quality and agent spend.
          </p>
        </div>
        <div className="flex gap-1 rounded-xl border border-white/10 p-1" data-testid="period-selector">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className={`rounded-lg px-3 py-1 text-sm ${
                period === p ? "bg-aether-coral font-semibold text-white" : "text-aether-muted"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </header>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      <section className="glass rounded-2xl border border-white/10 p-5" data-testid="funnel-chart">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
          Application funnel ({period})
        </h2>
        {funnelStages === null ? (
          <div className="mt-4 space-y-3" aria-busy="true">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-8 animate-pulse rounded-lg bg-white/5" />
            ))}
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {funnelStages.map(([label, value]) => (
              <div key={label} className="flex items-center gap-3">
                <span className="w-28 shrink-0 text-sm text-aether-muted">{label}</span>
                <div className="h-8 flex-1 overflow-hidden rounded-lg bg-white/5">
                  <div
                    className="flex h-full items-center rounded-lg bg-gradient-to-r from-aether-coral/70 to-aether-violet/70 px-3"
                    style={{ width: `${Math.max(4, (value / maxStage) * 100)}%` }}
                  >
                    <span className="mono text-xs font-semibold text-white">{value}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="glass rounded-2xl border border-white/10 p-5" data-testid="conversion-rates">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
          Stage conversion ({period})
        </h2>
        {conversion === null ? (
          <div className="mt-4 h-24 animate-pulse rounded-lg bg-white/5" aria-busy="true" />
        ) : (
          <dl className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
            {(
              [
                ["Found → Applied", conversion.found_to_applied],
                ["Applied → Screened", conversion.applied_to_screened],
                ["Screened → Interview", conversion.screened_to_interview],
                ["Interview → Offer", conversion.interview_to_offer],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono text-2xl font-bold text-aether-violet">{value}%</dd>
                <dt className="mt-1 text-xs text-aether-muted">{label}</dt>
              </div>
            ))}
          </dl>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="glass rounded-2xl border border-white/10 p-5" data-testid="ats-distribution">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
            ATS score distribution
          </h2>
          {ats === null ? (
            <div className="mt-4 h-40 animate-pulse rounded-lg bg-white/5" aria-busy="true" />
          ) : (
            <div className="mt-4 flex h-40 items-end gap-1.5">
              {ats.buckets.map((bucket) => (
                <div key={bucket.range} className="flex flex-1 flex-col items-center gap-1">
                  <div
                    className="w-full rounded-t bg-aether-violet/60"
                    style={{ height: `${Math.max(2, (bucket.count / maxBucket) * 100)}%` }}
                    title={`${bucket.range}: ${bucket.count}`}
                  />
                  <span className="mono text-[9px] text-aether-muted-dim">
                    {bucket.range.split("-")[0]}
                  </span>
                </div>
              ))}
            </div>
          )}
          {ats ? (
            <p className="mt-2 text-xs text-aether-muted-dim">{ats.total} scored jobs</p>
          ) : null}
        </section>

        <section className="glass rounded-2xl border border-white/10 p-5" data-testid="agent-roi">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
            Agent ROI
          </h2>
          {roi === null ? (
            <div className="mt-4 h-40 animate-pulse rounded-lg bg-white/5" aria-busy="true" />
          ) : (
            <dl className="mt-4 grid grid-cols-3 gap-4">
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono text-2xl font-bold text-aether-green">
                  ${roi.total_cost_usd.toFixed(2)}
                </dd>
                <dt className="mt-1 text-xs text-aether-muted">Total spend</dt>
              </div>
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono text-2xl font-bold">{roi.total_runs}</dd>
                <dt className="mt-1 text-xs text-aether-muted">Agent runs</dt>
              </div>
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono text-2xl font-bold text-aether-amber">
                  {Math.round(roi.avg_duration_ms)}ms
                </dd>
                <dt className="mt-1 text-xs text-aether-muted">Avg duration</dt>
              </div>
            </dl>
          )}
        </section>
      </div>

      <MarketPulse />
    </div>
  );
}
