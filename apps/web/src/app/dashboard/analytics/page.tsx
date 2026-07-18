"use client";

/**
 * Analytics — funnel, ATS score distribution and agent ROI, backed by
 * GET /analytics/funnel, /analytics/ats-distribution and /analytics/agent-roi.
 */
import { useCallback, useEffect, useState } from "react";

import MarketPulse from "../../../components/analytics/MarketPulse";
import MetricTooltip from "../../../components/MetricTooltip";
import {
  fetchAgentRoi,
  fetchAtsDistribution,
  fetchConversion,
  fetchDashboard,
  fetchFunnel,
  type AgentRoi,
  type AtsDistribution,
  type Conversion,
  type Dashboard,
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
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      // Fetch from working sub-endpoints first — these must not block the page.
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

      // Dashboard summary is fetched separately so a 404 on the dashboard
      // endpoint does not take down the entire page (GAP-P4-005 / P4-016).
      // Forwards the selected period (MV-analytics-004) — the backend has
      // always supported it; only the panels below (ATS distribution,
      // Agent ROI) have no period support server-side, so they carry an
      // explicit "all time" label instead of silently ignoring the selector.
      try {
        const dashboardData = await fetchDashboard(period);
        setDashboard(dashboardData);
      } catch {
        // Dashboard endpoint not yet deployed — degrade gracefully.
        setDashboard(null);
      }
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

  const SUMMARY_TIP: Record<string, string> = {
    // Honest about what's counted (data-consistency ruling,
    // MV-analytics-005): this is the canonical, unqualified "Applications"
    // figure — every Application record you have, including drafts you
    // haven't submitted yet — not the narrower "Applied"/submitted count
    // shown in the funnel below.
    Applications: "Every application record you have — draft through offer or rejection — across all sources and time periods.",
    Interviews: "Applications that have progressed to at least one interview stage.",
    Offers: "Applications where an employer has extended a formal offer.",
    "Jobs Found": "Roles discovered by the Scout agent and matched against your profile.",
    "Avg Fit Score": "Average ATS/AI fit score (0–100) across all scored jobs — how well your resume matches each posting.",
    "Agent Runs": "Total number of agent executions (discovery, tailoring, scoring, etc.) in this period.",
    "Agent Spend": "Total LLM API cost incurred by agent runs in this period.",
  };

  const CONVERSION_TIP: Record<string, string> = {
    "Found → Applied": "Share of discovered jobs you went on to apply for.",
    "Applied → Screened": "Share of applications that advanced to a recruiter screen.",
    "Screened → Interview": "Share of screened applications that reached an interview.",
    "Interview → Offer": "Share of interviews that resulted in a formal offer.",
  };

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

      {dashboard ? (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="dashboard-summary">
          {(
            [
              ["Applications", dashboard.totalApplications, "text-aether-coral"],
              ["Interviews", dashboard.interviews, "text-aether-violet"],
              ["Offers", dashboard.offers, "text-aether-green"],
              ["Jobs Found", dashboard.jobsFound, "text-aether-amber"],
              ["Avg Fit Score", `${dashboard.avgFitScore}%`, "text-aether-coral"],
              ["Agent Runs", dashboard.agentRuns, "text-aether-violet"],
              ["Agent Spend", `$${dashboard.agentCostUsd.toFixed(2)}`, "text-aether-green"],
            ] as const
          ).map(([label, value, color]) => (
            <div key={label} className="glass rounded-2xl border border-white/10 p-4">
              <dt className="text-xs text-aether-muted">{label}</dt>
              <dd className={`mono mt-1 text-2xl font-bold ${color}`}>
                <MetricTooltip value={value} tooltip={SUMMARY_TIP[label] ?? "See the analytics glossary for how this metric is calculated."} />
              </dd>
            </div>
          ))}
        </section>
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
                <dd className="mono flex items-center justify-center text-2xl font-bold text-aether-violet">
                  <MetricTooltip value={`${value}%`} tooltip={CONVERSION_TIP[label] ?? "Conversion rate between two consecutive funnel stages."} />
                </dd>
                <dt className="mt-1 text-xs text-aether-muted">{label}</dt>
              </div>
            ))}
          </dl>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="glass rounded-2xl border border-white/10 p-5" data-testid="ats-distribution">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-aether-muted">
            <MetricTooltip
              label="ATS score distribution"
              value=""
              tooltip="How your scored jobs are spread across ATS/AI fit-score bands (0–100) — higher bands mean stronger keyword and experience matches."
            />
            {/* This panel has no period support server-side (MV-analytics-004)
                — say so honestly instead of silently ignoring the selector
                above like it applies here too. */}
            <span className="text-[10px] font-normal normal-case text-aether-muted-dim">
              (all time — not affected by the period selector)
            </span>
          </h2>
          {ats === null ? (
            <div className="mt-4 h-40 animate-pulse rounded-lg bg-white/5" aria-busy="true" />
          ) : (
            <div className="mt-4 flex h-40 items-end gap-1.5">
              {ats.buckets.map((bucket) => (
                <div
                  key={bucket.range}
                  className="flex h-full flex-1 flex-col items-center justify-end gap-1"
                >
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
          <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-aether-muted">
            Agent ROI
            {/* No period support server-side (MV-analytics-004) — honest
                label instead of silently ignoring the selector above. */}
            <span className="text-[10px] font-normal normal-case text-aether-muted-dim">
              (all time — not affected by the period selector)
            </span>
          </h2>
          {roi === null ? (
            <div className="mt-4 h-40 animate-pulse rounded-lg bg-white/5" aria-busy="true" />
          ) : (
            <dl className="mt-4 grid grid-cols-3 gap-4">
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono flex items-center justify-center text-2xl font-bold text-aether-green">
                  <MetricTooltip
                    value={`$${roi.total_cost_usd.toFixed(2)}`}
                    tooltip="Cumulative LLM API cost across all agent runs in this period."
                  />
                </dd>
                <dt className="mt-1 text-xs text-aether-muted">Total spend</dt>
              </div>
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono flex items-center justify-center text-2xl font-bold">
                  <MetricTooltip value={roi.total_runs} tooltip="Total number of agent executions recorded in this period." />
                </dd>
                <dt className="mt-1 text-xs text-aether-muted">Agent runs</dt>
              </div>
              <div className="rounded-xl border border-white/10 p-4 text-center">
                <dd className="mono flex items-center justify-center text-2xl font-bold text-aether-amber">
                  <MetricTooltip
                    value={`${(roi.avg_duration_ms / 1000).toFixed(1)}s`}
                    tooltip="Average wall-clock time per agent run in this period."
                  />
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
