"use client";

/**
 * Agent Configuration grid (wireframe: agent-grid-ag14). The full agent catalog
 * as cards: category icon, keyboard-accessible recommendation tooltip, live
 * status dot (active/paused/error), assigned model, status label and an
 * enable/disable toggle. Runnable agents (real backend) also expose Run.
 *
 * Status + config are real: derived from GET /agents/catalog and mutated via
 * PUT /agents/config/{key} (see components/agents/api.ts).
 */
import { useId } from "react";

import type { CatalogAgent } from "./api";

const ACCENT_BG: Record<string, string> = {
  indigo: "bg-aether-indigo/15 text-aether-indigo",
  coral: "bg-aether-coral/15 text-aether-coral",
  amber: "bg-aether-amber/15 text-aether-amber",
  green: "bg-aether-green/15 text-aether-green",
};

const STATUS_DOT: Record<CatalogAgent["status"], string> = {
  active: "bg-aether-green",
  paused: "bg-aether-yellow",
  error: "bg-red-400",
  planned: "bg-white/25",
};

const STATUS_TEXT: Record<CatalogAgent["status"], string> = {
  active: "text-aether-green",
  paused: "text-aether-yellow",
  error: "text-red-400",
  planned: "text-aether-muted-dim",
};

const CARD_BORDER: Record<CatalogAgent["status"], string> = {
  active: "border-white/10 hover:border-white/20",
  paused: "border-white/10 hover:border-white/20",
  error: "border-red-400/30 hover:border-red-400/50",
  planned: "border-white/5 opacity-75",
};

const STATUS_LABEL: Record<CatalogAgent["status"], string> = {
  active: "Active",
  paused: "Paused",
  error: "Error",
  planned: "Planned",
};

function AgentCard({
  agent,
  busy,
  onToggle,
  onRun,
}: {
  agent: CatalogAgent;
  busy: boolean;
  onToggle: (key: string, enabled: boolean) => void;
  onRun: (key: string) => void;
}) {
  const tipId = useId();
  return (
    <div
      data-testid={`agent-card-${agent.key}`}
      className={`glass relative rounded-xl border p-4 transition ${CARD_BORDER[agent.status]}`}
    >
      <div className="mb-2 flex items-start justify-between">
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${ACCENT_BG[agent.accent] ?? ACCENT_BG.indigo}`}>
          <i className={`fa-solid ${agent.icon} text-xs`} aria-hidden="true" />
        </div>
        <div className="flex items-center gap-2">
          <span className="group relative inline-flex">
            <button
              type="button"
              data-testid={`agent-tip-${agent.key}`}
              aria-label={`Model recommendation for ${agent.name}`}
              aria-describedby={tipId}
              className="flex h-5 w-5 items-center justify-center rounded text-aether-muted-dim outline-none hover:text-white focus-visible:ring-2 focus-visible:ring-aether-coral/60"
            >
              <i className="fa-solid fa-circle-info text-xs" aria-hidden="true" />
            </button>
            <span
              id={tipId}
              role="tooltip"
              className="pointer-events-none absolute right-0 top-6 z-20 w-56 rounded-lg border border-white/10 bg-[#1C1C29] p-3 text-[11px] leading-relaxed text-aether-muted opacity-0 shadow-2xl transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100"
            >
              {agent.tip}
            </span>
          </span>
          <span
            className={`h-2 w-2 rounded-full ${STATUS_DOT[agent.status]}`}
            aria-hidden="true"
          />
        </div>
      </div>

      <p className="text-xs font-semibold">{agent.name}</p>
      <p
        className={`mt-1 font-mono text-[10px] ${agent.status === "error" ? "text-red-400" : "text-aether-indigo"}`}
      >
        {agent.model}
        {agent.status === "error" ? " · error" : ""}
      </p>

      <div className="mt-3 flex items-center justify-between gap-2">
        <span className={`text-[10px] ${STATUS_TEXT[agent.status]}`}>
          {STATUS_LABEL[agent.status]}
        </span>
        {agent.status === "planned" ? null : (
        <div className="flex items-center gap-2">
          {agent.runnable ? (
            <button
              type="button"
              data-testid={`agent-run-${agent.key}`}
              onClick={() => onRun(agent.key)}
              disabled={busy || !agent.enabled}
              className="rounded-md border border-white/15 px-2 py-0.5 text-[10px] font-semibold text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-40"
            >
              Run
            </button>
          ) : null}
          <button
            type="button"
            role="switch"
            aria-checked={agent.enabled}
            aria-label={`${agent.enabled ? "Disable" : "Enable"} ${agent.name}`}
            data-testid={`agent-toggle-${agent.key}`}
            onClick={() => onToggle(agent.key, !agent.enabled)}
            disabled={busy}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-end disabled:opacity-50 sm:min-h-0 sm:min-w-0"
          >
            <span
              className={`relative block h-4 w-8 rounded-full transition ${agent.enabled ? "bg-aether-coral" : "bg-white/12"}`}
            >
              <span
                className={`absolute top-0.5 h-3 w-3 rounded-full transition-all ${agent.enabled ? "right-0.5 bg-white" : "left-0.5 bg-aether-muted-dim"}`}
              />
            </span>
          </button>
        </div>
        )}
      </div>
    </div>
  );
}

export default function AgentConfigGrid({
  agents,
  counts,
  loading,
  busyKey,
  onToggle,
  onRun,
}: {
  agents: CatalogAgent[];
  counts: {
    total: number;
    active: number;
    paused: number;
    error: number;
    planned?: number;
  } | null;
  loading: boolean;
  busyKey: string | null;
  onToggle: (key: string, enabled: boolean) => void;
  onRun: (key: string) => void;
}) {
  return (
    <section data-testid="agent-configuration">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <i className="fa-solid fa-robot text-sm text-aether-coral" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Agent Configuration</h2>
          <span className="font-mono text-[11px] text-aether-muted-dim">
            {counts ? `${counts.total} agents` : "…"}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-aether-muted-dim">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-aether-green" />
            {counts ? `${counts.active} Active` : "Active"}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-aether-yellow" />
            {counts ? `${counts.paused} Paused` : "Paused"}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-red-400" />
            {counts ? `${counts.error} Error` : "Error"}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-white/25" />
            {counts ? `${counts.planned ?? 0} Planned` : "Planned"}
          </span>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4" aria-busy="true">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="glass h-28 animate-pulse rounded-xl border border-white/10" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          {agents.map((a) => (
            <AgentCard
              key={a.key}
              agent={a}
              busy={busyKey === a.key}
              onToggle={onToggle}
              onRun={onRun}
            />
          ))}
        </div>
      )}
    </section>
  );
}
