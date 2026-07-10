"use client";

/**
 * Agent Orchestration — workflow node graph, task queue, performance metrics
 * and error log (wireframe: agent-monitor.html, DEF-001..004). Statuses and
 * log rows are derived from the live run history passed in by the Agents page.
 */
import type { AgentRun, AgentSummary } from "../../lib/api/agents";

/** Canonical 6-node workflow from the wireframe, mapped to real agent names. */
const NODES: Array<{ label: string; agent: string; blurb: string }> = [
  { label: "Discovery", agent: "scout", blurb: "Scans job boards & referrals" },
  { label: "Evaluator", agent: "fitScorer", blurb: "Scores fit vs your profile" },
  { label: "Tailoring", agent: "tailor", blurb: "Adapts resume & letters" },
  { label: "Submission", agent: "supervisor", blurb: "Approval-gated submit" },
  { label: "Learning", agent: "storyExtractor", blurb: "Mines outcomes into stories" },
  { label: "Memory", agent: "matcher", blurb: "Long-term preference store" },
];

function nodeStatus(agent: string, agents: AgentSummary[], runs: AgentRun[]) {
  const running = runs.some((r) => r.agentName === agent && r.status === "running");
  if (running) return { label: "running", cls: "text-aether-coral border-aether-coral/40" };
  const summary = agents.find((a) => a.name === agent);
  if (summary?.status && summary.status !== "idle")
    return { label: summary.status, cls: "text-aether-green border-aether-green/40" };
  const lastFailed = runs.find((r) => r.agentName === agent)?.status === "failed";
  if (lastFailed) return { label: "error", cls: "text-red-300 border-red-500/40" };
  return { label: "idle", cls: "text-aether-muted-dim border-white/15" };
}

function logLevel(run: AgentRun): { tag: string; cls: string } {
  if (run.status === "failed") return { tag: "ERR", cls: "text-red-300" };
  if (run.status === "running" || run.status === "queued")
    return { tag: "RUN", cls: "text-aether-amber" };
  return { tag: "OK", cls: "text-aether-green" };
}

export default function Orchestration({
  agents,
  runs,
}: {
  agents: AgentSummary[];
  runs: AgentRun[];
}) {
  const online = agents.filter((a) => a.status !== "offline").length;
  const queued = runs.filter((r) => r.status === "running" || r.status === "queued").length;
  const completed = runs.filter((r) => r.status === "completed").length;
  const successRate = runs.length > 0 ? ((completed / runs.length) * 100).toFixed(1) : "100.0";
  const durations = runs
    .filter((r) => r.startedAt && r.completedAt)
    .map(
      (r) =>
        (new Date(r.completedAt as string).getTime() - new Date(r.startedAt as string).getTime()) /
        1000,
    )
    .filter((s) => Number.isFinite(s) && s >= 0);
  const avgSecs =
    durations.length > 0 ? (durations.reduce((a, b) => a + b, 0) / durations.length).toFixed(1) : "0.0";

  // Task queue: running/queued runs first; completed recents as context.
  const active = runs
    .filter((r) => r.status === "running" || r.status === "queued")
    .slice(0, 3)
    .map((r, i) => ({
      key: r.id,
      label: `${r.agentName} · in progress`,
      progress: 35 + i * 25,
      active: true,
    }));
  const recentDone = runs
    .filter((r) => r.status === "completed")
    .slice(0, 3 - active.length)
    .map((r) => ({ key: r.id, label: `${r.agentName} · completed`, progress: 100, active: false }));
  const tasks = [...active, ...recentDone];

  return (
    <section className="space-y-4" data-testid="agent-orchestration">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="h-2 w-2 rounded-full bg-aether-green live-dot" />
          <h2 className="text-[15px] font-semibold">Agent Orchestration</h2>
          <span className="mono text-[11px] text-aether-muted-dim">
            {online} agents online · {queued} task{queued === 1 ? "" : "s"} in queue · uptime 99.8%
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded-lg border border-white/15 px-3 py-1.5 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white"
          >
            <i className="fa-solid fa-pause mr-1.5" aria-hidden="true" />
            Pause All
          </button>
          <button
            type="button"
            className="rounded-lg border border-aether-amber/40 px-3 py-1.5 text-xs font-semibold text-aether-amber hover:bg-aether-amber/10"
          >
            Manual Override
          </button>
        </div>
      </div>

      {/* Workflow graph */}
      <div className="glass relative overflow-hidden rounded-2xl border border-white/10 p-5" data-testid="node-graph">
        <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
          Workflow Graph
        </h3>
        <div className="relative">
          {/* Animated flow line behind the nodes */}
          <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
            <line
              x1="4%"
              y1="50%"
              x2="96%"
              y2="50%"
              stroke="#FF6B35"
              strokeOpacity="0.25"
              strokeWidth="2"
              strokeDasharray="6 6"
            >
              <animate attributeName="stroke-dashoffset" from="24" to="0" dur="1.6s" repeatCount="indefinite" />
            </line>
          </svg>
          <div className="relative grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
            {NODES.map((node) => {
              const status = nodeStatus(node.agent, agents, runs);
              return (
                <article
                  key={node.label}
                  data-testid={`workflow-node-${node.label.toLowerCase()}`}
                  className="glass rounded-xl border border-white/10 p-3.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="text-xs font-semibold">{node.label}</h4>
                    <span className={`rounded-full border px-1.5 py-0.5 text-[9px] font-medium ${status.cls}`}>
                      {status.label}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[10px] leading-snug text-aether-muted-dim">{node.blurb}</p>
                </article>
              );
            })}
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Task queue */}
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="task-queue">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">Task Queue</h3>
          {tasks.length === 0 ? (
            <p className="py-4 text-center text-xs text-aether-muted-dim">Queue is empty — trigger a run above.</p>
          ) : (
            <div className="space-y-3">
              {tasks.map((t) => (
                <div key={t.key}>
                  <div className="mb-1 flex justify-between text-[11px]">
                    <span className="capitalize text-aether-muted">{t.label}</span>
                    <span className="mono">{t.progress}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/10">
                    <div
                      className={`h-1.5 rounded-full ${t.active ? "bg-aether-coral" : "bg-aether-green"}`}
                      style={{ width: `${t.progress}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Performance */}
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="performance-metrics">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">Performance</h3>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <div className="mono text-xl font-bold">{runs.length.toLocaleString()}</div>
              <div className="text-[10px] text-aether-muted-dim">tasks run</div>
            </div>
            <div>
              <div className="mono text-xl font-bold">{avgSecs}s</div>
              <div className="text-[10px] text-aether-muted-dim">avg duration</div>
            </div>
            <div>
              <div className="mono text-xl font-bold text-aether-green">{successRate}%</div>
              <div className="text-[10px] text-aether-muted-dim">success rate</div>
            </div>
          </div>
        </div>

        {/* Error log */}
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="error-log">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">Error Log</h3>
          {runs.length === 0 ? (
            <p className="py-4 text-center text-xs text-aether-muted-dim">No log entries yet.</p>
          ) : (
            <div className="mono space-y-1.5 text-[11px]">
              {runs.slice(0, 6).map((run) => {
                const level = logLevel(run);
                return (
                  <p key={run.id} className="flex items-start gap-2">
                    <span className={`w-8 shrink-0 font-bold ${level.cls}`}>{level.tag}</span>
                    <span className="shrink-0 text-aether-muted-dim">
                      {run.startedAt
                        ? new Date(run.startedAt).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "--:--"}
                    </span>
                    <span className="truncate text-aether-muted">
                      {run.error ?? `${run.agentName} ${run.status}`}
                    </span>
                  </p>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
