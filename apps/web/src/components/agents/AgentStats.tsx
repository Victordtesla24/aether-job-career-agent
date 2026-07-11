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
          <div key={i} className="glass h-28 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </section>
    );
  }

  const most = stats.mostActiveAgent;
  return (
    <section className="grid grid-cols-2 gap-4 xl:grid-cols-4" data-testid="agent-stats">
      <div className="glass rounded-2xl border border-white/10 p-5" data-testid="stat-spend">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
            API Spend (Month)
          </span>
          <i className="fa-solid fa-dollar-sign text-sm text-aether-coral" aria-hidden="true" />
        </div>
        <div className="font-mono text-2xl font-bold">${stats.spendUsd.toFixed(2)}</div>
        <p className="mt-1 text-[11px] text-aether-muted-dim">
          across {stats.providerCount} providers ·{" "}
          <span className="font-mono text-aether-muted">
            ~${stats.avgCostPerRun.toFixed(3)}
          </span>{" "}
          avg / run
        </p>
      </div>

      <div className="glass rounded-2xl border border-white/10 p-5" data-testid="stat-tokens">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
            Tokens Used
          </span>
          <i className="fa-solid fa-coins text-sm text-aether-indigo" aria-hidden="true" />
        </div>
        <div className="font-mono text-2xl font-bold">{fmtTokens(stats.tokensTotal)}</div>
        <p className="mt-1 text-[11px] text-aether-muted-dim">
          {fmtTokens(stats.tokensIn)} in · {fmtTokens(stats.tokensOut)} out
        </p>
      </div>

      <div className="glass rounded-2xl border border-white/10 p-5" data-testid="stat-active">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
            Most Active Agent
          </span>
          <i className="fa-solid fa-file-pen text-sm text-aether-coral" aria-hidden="true" />
        </div>
        <div className="truncate text-lg font-bold">{most ? most.name : "—"}</div>
        <p className="mt-1 font-mono text-[11px] text-aether-muted-dim">
          {most ? `${most.tasks} tasks` : "no runs yet"}
        </p>
      </div>

      <div
        className="glass relative overflow-hidden rounded-2xl border border-white/10 p-5"
        data-testid="stat-success"
      >
        <div className="absolute -right-6 -top-6 h-20 w-20 rounded-full bg-aether-green/10 blur-2xl" />
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
            Success Rate
          </span>
          <i className="fa-solid fa-circle-check text-sm text-aether-green" aria-hidden="true" />
        </div>
        <div className="font-mono text-2xl font-bold text-aether-green">
          {stats.successRate.toFixed(1)}%
        </div>
        <p className="mt-1 text-[11px] text-aether-muted-dim">
          last {stats.taskCount.toLocaleString()} tasks
        </p>
      </div>
    </section>
  );
}
