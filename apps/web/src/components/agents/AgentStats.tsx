"use client";

/**
 * Bottom quick-stats row (wireframe: quick-stats-ag15). All four figures are
 * derived from real AgentRun history via GET /agents/stats — no hardcoded
 * numbers. Shows a skeleton while loading and safe fallbacks when empty.
 */
import type { AgentStats } from "./api";
import { formatTokens as fmtTokens } from "./logic";

export default function AgentStatsRow({
  stats,
  loading,
}: {
  stats: AgentStats | null;
  loading: boolean;
}) {
  if (loading || !stats) {
    return (
      <section
        className="grid grid-cols-2 gap-4 xl:grid-cols-4"
        data-testid="agent-stats"
        aria-busy="true"
      >
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="ag-panel h-[110px] animate-pulse" />
        ))}
      </section>
    );
  }

  const most = stats.mostActiveAgent;
  return (
    <section className="grid grid-cols-2 gap-4 xl:grid-cols-4" data-testid="agent-stats">
      {/* Rule 4 — the figure leads, the label follows in small grey caps, and
          the supporting line stays a footnote. Same shell on all four; only
          density and colour separate them (rule 15). */}
      <div className="ag-panel p-5" data-testid="stat-spend">
        <div className="mb-3 flex items-center justify-between gap-2">
          <span className="ag-stat-label">API Spend (Month)</span>
          <i className="fa-solid fa-dollar-sign text-[11px] text-aether-coral/70" aria-hidden="true" />
        </div>
        <div className="ag-stat-figure">
          <span className="ag-stat-unit">$</span>
          {stats.spendUsd.toFixed(2)}
        </div>
        <p className="mt-2 text-[11px] leading-[1.5] text-aether-muted-dim">
          across {stats.providerCount} providers ·{" "}
          <span className="font-mono tabular-nums text-aether-muted">
            ~${stats.avgCostPerRun.toFixed(3)}
          </span>{" "}
          avg / run
        </p>
      </div>

      <div className="ag-panel p-5" data-testid="stat-tokens">
        <div className="mb-3 flex items-center justify-between gap-2">
          <span className="ag-stat-label">Tokens Used</span>
          <i className="fa-solid fa-coins text-[11px] text-aether-indigo/70" aria-hidden="true" />
        </div>
        <div className="ag-stat-figure">{fmtTokens(stats.tokensTotal)}</div>
        <p className="mt-2 font-mono text-[11px] tabular-nums leading-[1.5] text-aether-muted-dim">
          {fmtTokens(stats.tokensIn)} in · {fmtTokens(stats.tokensOut)} out
        </p>
      </div>

      <div className="ag-panel p-5" data-testid="stat-active">
        <div className="mb-3 flex items-center justify-between gap-2">
          <span className="ag-stat-label">Most Active Agent</span>
          <i className="fa-solid fa-file-pen text-[11px] text-aether-coral/70" aria-hidden="true" />
        </div>
        {/* A name, not a numeral — so it takes the sans face at display weight
            instead of pretending to be a figure. */}
        <div className="truncate text-[19px] font-semibold leading-[1.15] tracking-[-0.02em]">
          {most ? most.name : "—"}
        </div>
        <p className="mt-2 font-mono text-[11px] tabular-nums leading-[1.5] text-aether-muted-dim">
          {most ? `${most.tasks} tasks` : "no runs yet"}
        </p>
      </div>

      <div className="ag-panel relative overflow-hidden p-5" data-testid="stat-success">
        <div className="pointer-events-none absolute -right-8 -top-10 h-24 w-24 rounded-full bg-aether-green/10 blur-2xl" />
        <div className="mb-3 flex items-center justify-between gap-2">
          <span className="ag-stat-label">Success Rate</span>
          <i className="fa-solid fa-circle-check text-[11px] text-aether-green/70" aria-hidden="true" />
        </div>
        <div className="ag-stat-figure text-aether-green">
          {stats.successRate.toFixed(1)}
          <span className="ag-stat-unit text-aether-green/70">%</span>
        </div>
        <p className="mt-2 text-[11px] leading-[1.5] text-aether-muted-dim">
          last {stats.taskCount.toLocaleString()} tasks
          {/* QA3-F-03: degraded (letterless coverLetter) runs are excluded
              from the success-rate numerator above — disclose the count
              distinctly instead of leaving it invisible. */}
          {stats.degradedCount ? ` · ${stats.degradedCount} degraded` : ""}
        </p>
      </div>
    </section>
  );
}
