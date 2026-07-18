"use client";

/**
 * Agent Orchestration — workflow node graph, task queue, performance metrics
 * and error log (wireframe: agent-monitor.html, DEF-001..004). Statuses and
 * log rows are derived from the live run history passed in by the Agents page.
 */
import type { AgentRun, AgentSummary } from "../../lib/api/agents";

/**
 * The REAL 7-agent topology, in pipeline order (supervisor → scout →
 * fitScorer → matcher → tailor → coverLetter, plus on-demand storyExtractor).
 * Labels and blurbs describe what each agent actually does — no phantom nodes.
 */
const NODES: Array<{ label: string; agent: string; blurb: string }> = [
  { label: "Supervisor", agent: "supervisor", blurb: "Plans & sequences the pipeline" },
  { label: "Discovery", agent: "scout", blurb: "Scrapes job boards & APIs" },
  { label: "Evaluator", agent: "fitScorer", blurb: "10-dim fit + ATS scoring" },
  { label: "Matcher", agent: "matcher", blurb: "Selects the best-fit target job" },
  { label: "Tailoring", agent: "tailor", blurb: "Evidence-grounded resume rewrite" },
  { label: "Cover Letter", agent: "coverLetter", blurb: "Drafts letter · approval-gated" },
  { label: "Stories", agent: "storyExtractor", blurb: "Mines resume into STAR+R stories" },
  { label: "Email", agent: "emailAgent", blurb: "Triages inbox · drafts grounded replies · applies labels" },
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

/**
 * A Task Queue row. `progress` is `null` for anything still in flight — there
 * is no real progress-fraction signal to report, so the UI must not invent
 * one (MV-agent-monitor-002). Only a completed run's real 100% is a number.
 */
interface TaskItem {
  key: string;
  label: string;
  progress: number | null;
  active: boolean;
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
  // AgentRun carries no real progress-fraction field (status is only
  // queued/running/completed/failed), so an in-progress row's `progress` is
  // `null` — the UI renders an honest indeterminate indicator for it instead
  // of a fabricated percentage (MV-agent-monitor-002). Only a genuinely
  // completed run gets the real, backend-confirmed 100%.
  const active: TaskItem[] = runs
    .filter((r) => r.status === "running" || r.status === "queued")
    .slice(0, 3)
    .map((r) => ({
      key: r.id,
      label: `${r.agentName} · ${r.status === "running" ? "in progress" : "queued"}`,
      progress: null,
      active: true,
    }));
  const recentDone: TaskItem[] = runs
    .filter((r) => r.status === "completed")
    .slice(0, 3 - active.length)
    .map((r) => ({ key: r.id, label: `${r.agentName} · completed`, progress: 100, active: false }));
  const tasks: TaskItem[] = [...active, ...recentDone];

  return (
    <section className="space-y-4" data-testid="agent-orchestration">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="h-2 w-2 rounded-full bg-aether-green live-dot" />
          <h2 className="text-[15px] font-semibold">Agent Orchestration</h2>
          <span className="mono text-[11px] text-aether-muted-dim">
            {/* ADV-agent-monitor-001: there is no real uptime signal backing
                a percentage here (checked apps/api/app/routers/agents.py —
                no uptime/health-history endpoint exists), so the fabricated
                "uptime 99.8%" literal has been removed rather than grounded
                in a fake number. */}
            {online} agents online · {queued} task{queued === 1 ? "" : "s"} in queue
          </span>
        </div>
        <div className="flex gap-2">
          {/*
            MV-agent-monitor-001: there is no backend "pause all" or "manual
            override" capability (checked apps/api/app/routers/agents.py —
            only per-agent enable/disable and per-agent run trigger exist, no
            bulk-pause or manual-override endpoint). Rather than wire these to
            a fake action, they are honestly disabled with a tooltip so no
            control appears live when it does nothing.
          */}
          <button
            type="button"
            disabled
            title="Not yet available"
            aria-disabled="true"
            className="cursor-not-allowed rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-aether-muted-dim opacity-50"
          >
            <i className="fa-solid fa-pause mr-1.5" aria-hidden="true" />
            Pause All
          </button>
          <button
            type="button"
            disabled
            title="Not yet available"
            aria-disabled="true"
            className="cursor-not-allowed rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-aether-muted-dim opacity-50"
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
                    {/* No fabricated percentage for in-progress work — only a
                        real, completed-run 100% is ever shown as a number. */}
                    <span className="mono">{t.progress !== null ? `${t.progress}%` : "…"}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/10">
                    {t.progress !== null ? (
                      <div
                        className={`h-1.5 rounded-full ${t.active ? "bg-aether-coral" : "bg-aether-green"}`}
                        style={{ width: `${t.progress}%` }}
                      />
                    ) : (
                      <div
                        className="h-1.5 w-full animate-pulse rounded-full bg-aether-coral/40"
                        aria-label="in progress, no measured completion percentage available"
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Performance */}
        <div className="glass rounded-2xl border border-white/10 p-5" data-testid="performance-metrics">
          {/*
            MV-agent-monitor-003: this card's success rate is computed
            client-side from the `runs` prop, which the Agents page fetches
            via GET /agents/runs (server default limit=50) — a DIFFERENT
            sample window than the separate Agent Stats "Success Rate" card
            (GET /agents/stats, server limit=200). Both numbers are real, but
            without disclosure they read as contradicting each other. Label
            this card's own window explicitly, matching the disclosure
            pattern already used by the Agent Stats card ("last N tasks").
          */}
          <h3 className="mb-3 flex flex-wrap items-baseline gap-x-1.5 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
            Performance
            <span className="normal-case text-[10px] font-normal tracking-normal text-aether-muted-dim/70">
              · last {runs.length.toLocaleString()} run{runs.length === 1 ? "" : "s"}
            </span>
          </h3>
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
