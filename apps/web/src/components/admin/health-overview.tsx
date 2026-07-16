"use client";

/**
 * Health overview (GAP-P6-ADMIN-001, §15). Shared by /admin and /admin/health.
 * Renders genuine service/agent/LLM/cron/provider status from GET
 * /api/admin/health — no fabricated metrics; agent success-rate is derived from
 * real AgentRun status counts server-side.
 */
import { useEffect, useState } from "react";

import { fetchAdminHealth, type AdminHealth } from "../../lib/api/admin";

function statusTone(value: string): string {
  const v = value.toLowerCase();
  if (v === "ok") return "bg-aether-green/15 text-aether-green border-aether-green/25";
  if (v === "error" || v === "down")
    return "bg-red-500/10 text-red-300 border-red-500/25";
  return "bg-white/5 text-aether-muted-dim border-white/10";
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">{children}</div>
  );
}

export function HealthOverview() {
  const [health, setHealth] = useState<AdminHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAdminHealth()
      .then((h) => !cancelled && setHealth(h))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Failed to load"));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p className="text-sm text-red-300">{error}</p>;
  if (!health) return <p className="text-sm text-aether-muted">Loading health…</p>;

  const rate = health.agents.successRate;
  const ratePct = rate === null ? "—" : `${(rate * 100).toFixed(1)}%`;

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <Card>
        <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Services</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(health.services).map(([name, value]) => (
            <span
              key={name}
              className={`rounded-full border px-2.5 py-1 text-xs ${statusTone(value)}`}
            >
              {name}: {value}
            </span>
          ))}
        </div>
      </Card>

      <Card>
        <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Agent success rate</p>
        <p className="mt-2 text-2xl font-semibold text-aether-text">{ratePct}</p>
        <p className="mt-1 text-xs text-aether-muted">
          {health.agents.succeeded} succeeded / {health.agents.failed} failed of{" "}
          {health.agents.totalRuns} runs ({health.agents.running} running)
        </p>
      </Card>

      <Card>
        <p className="text-xs uppercase tracking-wide text-aether-muted-dim">LLM mode</p>
        <p className="mt-2 text-lg font-medium text-aether-text">{health.llm.mode}</p>
        <p className="mt-1 text-xs text-aether-muted">
          Providers configured: {health.providers.count}
          {health.providers.configuredTiers.length > 0
            ? ` (${health.providers.configuredTiers.join(", ")})`
            : ""}
        </p>
      </Card>

      <Card>
        <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Cron / scheduler</p>
        <div className="mt-2 flex items-center gap-2">
          <span className={`rounded-full border px-2.5 py-1 text-xs ${statusTone(health.cron.status)}`}>
            {health.cron.status}
          </span>
        </div>
        <p className="mt-2 text-xs text-aether-muted">{health.cron.detail}</p>
      </Card>
    </div>
  );
}
