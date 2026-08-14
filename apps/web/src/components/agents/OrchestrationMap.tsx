"use client";

/**
 * Agent Orchestration workflow map(s) — U-AX build spec item 5.
 *
 * Renders `GET /agents/orchestration-map`: every catalog agent placed into
 * one or more DEFINED end-to-end workflow maps (the backend ships 3 —
 * application-pipeline / learning-loop / enrichment — per
 * `apps/api/app/routers/agents.py::_ORCHESTRATION_MAPS`), each agent showing
 * its stage, its real-vs-planned status, the metrics it consumes, its
 * threshold responsibilities, its last-run policy tier and its trend.
 *
 * DISTINCT from `components/agents/Orchestration.tsx` (the task-queue /
 * performance / error-log widget) — this is the workflow GRAPH, not the live
 * run monitor.
 *
 * Honesty invariant enforced here, not just server-side: a `planned` agent
 * NEVER renders with an "implemented/live" badge — the backend's own
 * structural guarantee (`status` is `real` iff a backend key exists) is
 * echoed in the label so a roadmap card can never be mistaken for an
 * executing one.
 */
import type {
  OrchestrationMapAgent,
  OrchestrationMapData,
} from "../../lib/api/agentPolicy";

function slug(value: string): string {
  return value.toLowerCase().trim().replace(/\s+/g, "-");
}

function trendLabel(agent: OrchestrationMapAgent): string | null {
  const trend = agent.trend;
  if (!trend || !trend.direction) return null;
  const arrow = trend.direction === "improving" ? "↑" : trend.direction === "declining" ? "↓" : "→";
  return `${arrow} ${trend.direction}${trend.metric ? ` (${trend.metric})` : ""}`;
}

function AgentCard({ agent }: { agent: OrchestrationMapAgent }) {
  const isPlanned = agent.status === "planned";
  const trend = trendLabel(agent);
  return (
    <article
      data-testid={`orchestration-agent-${agent.agentKey}`}
      className={`rounded-lg border p-2.5 text-xs ${
        isPlanned
          ? "border-dashed border-white/15 bg-white/[0.02] text-aether-muted-dim"
          : "border-white/10 bg-white/5"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-aether-muted">{agent.name}</span>
        <span
          className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide ${
            isPlanned
              ? "border-white/15 text-aether-muted-dim"
              : "border-aether-green/40 text-aether-green"
          }`}
        >
          {isPlanned ? "Planned — roadmap" : "Implemented"}
        </span>
      </div>
      {!isPlanned && agent.metricsConsumed.length > 0 ? (
        <p className="mt-1 text-[10px] text-aether-muted-dim">
          Consumes: {agent.metricsConsumed.join(", ")}
        </p>
      ) : null}
      {!isPlanned && agent.thresholds.length > 0 ? (
        <p className="mt-0.5 text-[10px] text-aether-muted-dim">
          Threshold: {agent.thresholds.join("; ")}
        </p>
      ) : null}
      {!isPlanned && agent.lastRunPolicyTier ? (
        <p className="mt-0.5 text-[10px] text-aether-muted-dim">
          Last-run tier: <span className="font-semibold">{agent.lastRunPolicyTier}</span>
        </p>
      ) : null}
      {!isPlanned && trend ? (
        <p className="mt-0.5 text-[10px] text-aether-muted-dim">Trend: {trend}</p>
      ) : null}
      {!isPlanned && !agent.lastRunPolicyTier && !trend ? (
        <p className="mt-0.5 text-[10px] text-aether-muted-dim">No runs recorded yet.</p>
      ) : null}
    </article>
  );
}

export default function OrchestrationMap({ data }: { data: OrchestrationMapData }) {
  return (
    <div className="space-y-6" data-testid="orchestration-map">
      {data.maps.map((map) => (
        <section key={map.key} className="glass rounded-2xl border border-white/10 p-5">
          <h3 className="text-sm font-semibold">{map.name}</h3>
          {map.subtitle ? (
            <p className="mt-0.5 text-xs text-aether-muted-dim">{map.subtitle}</p>
          ) : null}
          <div className="mt-3 space-y-3">
            {map.stages.map((stage) => (
              <div key={stage.stage} data-testid={`orchestration-stage-${slug(stage.stage)}`}>
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-aether-muted-dim">
                  {stage.stage}
                </h4>
                <div className="mt-1.5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {stage.agents.map((agent) => (
                    <AgentCard key={agent.agentKey} agent={agent} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
