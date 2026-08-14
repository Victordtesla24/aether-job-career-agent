"use client";

/**
 * Agent Orchestration — workflow node graph, task queue, performance metrics
 * and error log (wireframe: agent-monitor.html, DEF-001..004). Statuses and
 * log rows are derived from the live run history passed in by the Agents page.
 */
import {
  coverLetterDegraded,
  isInFlight,
  isLiveRun,
  isStalledRun,
  parseServerTime,
  stalledLabel,
  STALLED_RUN_ADVICE,
} from "../../lib/agent-run-health";
import type { AgentRun, AgentSummary } from "../../lib/api/agents";
import { useNow } from "../../hooks/useNow";

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
  { label: "Email", agent: "emailAgent", blurb: "Triages inbox · drafts grounded replies · imports job alerts" },
];

function nodeStatus(agent: string, agents: AgentSummary[], runs: AgentRun[], now: number) {
  // `runs` arrives newest-first (GET /agents/runs orders by createdAt DESC), so
  // the node reflects this agent's CURRENT run, not any older one.
  const newest = runs.find((r) => r.agentName === agent);
  if (newest && isInFlight(newest)) {
    // CRITICAL-2: only a run that could still plausibly be alive paints the
    // node as running. A `running` row older than the staleness window has no
    // worker behind it, and showing it as live is how a week of total
    // inactivity got hidden behind a coral badge.
    return isLiveRun(newest, now)
      ? { label: "running", cls: "text-aether-coral border-aether-coral/40" }
      : { label: stalledLabel(newest, now), cls: "text-aether-amber border-aether-amber/40" };
  }
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
  // CRITICAL-2: true for an in-flight run whose last movement is older than any
  // real run takes. It renders as an inert, honest "stalled for N" row — never
  // an indeterminate indicator, which would claim work is still happening.
  stalled?: boolean;
  // QA3-F-03: true for a letterless coverLetter degrade (GAP-P4-002) — the
  // run genuinely finished (not still in flight), but produced no letter, so
  // it must never render with the same green "success" treatment as a real
  // completion.
  degraded?: boolean;
}

function logLevel(run: AgentRun, now: number): { tag: string; cls: string } {
  if (run.status === "failed") return { tag: "ERR", cls: "text-red-300" };
  // CRITICAL-2: a run that stopped reporting is not still going. "RUN" for a
  // row that last moved eight days ago is a false present-tense claim.
  if (isStalledRun(run, now)) return { tag: "DEAD", cls: "text-aether-amber" };
  if (run.status === "running" || run.status === "queued")
    return { tag: "RUN", cls: "text-aether-amber" };
  // QA3-F-03: a letterless coverLetter degrade is recorded status='completed'
  // (the guard working is not a failure), but tagging it the same green "OK"
  // as a real success reads as an all-clear when 453/454 runs produced
  // nothing — use the same neutral treatment the dashboard feed's honest
  // "Unavailable" badge already applies to this exact run shape.
  if (coverLetterDegraded(run)) return { tag: "N/A", cls: "text-aether-muted-dim" };
  return { tag: "OK", cls: "text-aether-green" };
}

export default function Orchestration({
  agents,
  runs,
}: {
  agents: AgentSummary[];
  runs: AgentRun[];
}) {
  // Staleness is a function of elapsed time, not of any server event, so the
  // widget re-renders on a clock as well as on realtime refetches — otherwise a
  // run that goes stale while the screen is open keeps its spinner forever.
  const now = useNow();
  const online = agents.filter((a) => a.status !== "offline").length;
  const queueRuns = runs.filter(isInFlight);
  const liveRuns = queueRuns.filter((r) => isLiveRun(r, now));
  const stalledRuns = queueRuns.filter((r) => isStalledRun(r, now));
  // CRITICAL-2: stalled work is NOT queued work. Counting a dead row here is
  // what put "1 task in queue" on screen for eight days.
  const queued = liveRuns.length;
  // QA3-F-03: a letterless coverLetter degrade is recorded status='completed'
  // (GAP-P4-002 — the guard working is not a failure), but it is NOT a
  // success — exclude it from the numerator (counted distinctly below)
  // instead of letting it silently inflate the success rate.
  const degraded = runs.filter(coverLetterDegraded).length;
  const completed = runs.filter((r) => r.status === "completed" && !coverLetterDegraded(r)).length;
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
  //
  // CRITICAL-2: a stalled run keeps its row here — it is real, and the user
  // needs to see it — but never the indeterminate pulsing indicator, which is
  // a claim that something is happening. It gets `stalled: true`, an inert
  // bar, and a label that states how long it has been dead.
  const active: TaskItem[] = [...stalledRuns, ...liveRuns]
    .slice(0, 3)
    .map((r) =>
      isStalledRun(r, now)
        ? {
            key: r.id,
            label: `${r.agentName} · ${stalledLabel(r, now)}`,
            progress: null,
            active: false,
            stalled: true,
          }
        : {
            key: r.id,
            label: `${r.agentName} · ${r.status === "running" ? "in progress" : "queued"}`,
            progress: null,
            active: true,
          },
    );
  const recentDone: TaskItem[] = runs
    .filter((r) => r.status === "completed")
    .slice(0, Math.max(0, 3 - active.length))
    .map((r) =>
      coverLetterDegraded(r)
        ? { key: r.id, label: `${r.agentName} · unavailable`, progress: 100, active: false, degraded: true }
        : { key: r.id, label: `${r.agentName} · completed`, progress: 100, active: false },
    );
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
            {stalledRuns.length > 0 ? (
              // CRITICAL-2: stalled work is reported separately and never
              // folded into the queue count, which would read as live work.
              <span className="text-aether-amber" data-testid="orchestration-stalled-count">
                {" "}
                · {stalledRuns.length} stalled
              </span>
            ) : null}
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
            className="cursor-not-allowed rounded-md border border-hairline px-3 py-1.5 text-[12px] font-semibold text-aether-muted-dim opacity-50"
          >
            <i className="fa-solid fa-pause mr-1.5" aria-hidden="true" />
            Pause All
          </button>
          <button
            type="button"
            disabled
            title="Not yet available"
            aria-disabled="true"
            className="cursor-not-allowed rounded-md border border-hairline px-3 py-1.5 text-[12px] font-semibold text-aether-muted-dim opacity-50"
          >
            Manual Override
          </button>
        </div>
      </div>

      {/* Workflow graph */}
      <div className="elev-1 relative overflow-hidden rounded-2xl p-5" data-testid="node-graph">
        <h3 className="mb-1 text-[13px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">
          Live Run Monitor
        </h3>
        {/* Named apart from the workflow MAP above it: that one is the DEFINED
            22-agent topology from GET /agents/orchestration-map; this one is
            the 7 implemented backends and what each is doing right now. */}
        <p className="mb-4 text-[11px] leading-[1.5] text-aether-muted-dim">
          The implemented agents and the state of each one&apos;s current run.
        </p>
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
              const status = nodeStatus(node.agent, agents, runs, now);
              return (
                <article
                  key={node.label}
                  data-testid={`workflow-node-${node.label.toLowerCase()}`}
                  className="elev-1 rounded-xl p-3.5 transition-[border-color,background-color] duration-[var(--dur)] hover:border-hairline-strong hover:bg-surface-2"
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
        <div className="elev-1 min-w-0 rounded-2xl p-5" data-testid="task-queue">
          <h3 className="mb-3 text-[13px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">Task Queue</h3>
          {tasks.length === 0 ? (
            <p className="py-4 text-center text-xs text-aether-muted-dim">Queue is empty — trigger a run above.</p>
          ) : (
            <div className="space-y-3">
              {tasks.map((t) => (
                <div key={t.key}>
                  <div className="mb-1 flex justify-between text-[11px]">
                    <span className={t.stalled ? "text-aether-amber" : "capitalize text-aether-muted"}>
                      {t.label}
                    </span>
                    {/* No fabricated percentage for in-progress work — only a
                        real, completed-run 100% is ever shown as a number. A
                        stalled run gets neither: "…" would imply it is still
                        thinking. */}
                    <span className="mono">
                      {t.progress !== null ? `${t.progress}%` : t.stalled ? "—" : "…"}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/10">
                    {t.progress !== null ? (
                      <div
                        className={`h-1.5 rounded-full ${
                          t.degraded ? "bg-white/25" : t.active ? "bg-aether-coral" : "bg-aether-green"
                        }`}
                        style={{ width: `${t.progress}%` }}
                      />
                    ) : t.stalled ? (
                      // CRITICAL-2: inert and unanimated. No role="progressbar"
                      // either — nothing is progressing.
                      <div className="h-1.5 w-full rounded-full bg-aether-amber/25" />
                    ) : (
                      <div
                        role="progressbar"
                        className="h-1.5 w-full animate-pulse rounded-full bg-aether-coral/40"
                        aria-label="in progress, no measured completion percentage available"
                      />
                    )}
                  </div>
                </div>
              ))}
              {tasks.some((t) => t.stalled) ? (
                // Said once for the whole queue rather than repeated per row.
                <p className="pt-1 text-[10px] leading-snug text-aether-muted-dim">
                  {STALLED_RUN_ADVICE}
                </p>
              ) : null}
            </div>
          )}
        </div>

        {/* Performance */}
        <div className="elev-1 min-w-0 rounded-2xl p-5" data-testid="performance-metrics">
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
          <h3 className="mb-3 flex flex-wrap items-baseline gap-x-1.5 text-[13px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">
            Performance
            <span className="normal-case text-[11px] font-normal tracking-normal text-aether-muted-dim">
              · last {runs.length.toLocaleString()} run{runs.length === 1 ? "" : "s"}
            </span>
          </h3>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <div className="font-mono text-[22px] font-bold tabular-nums">{runs.length.toLocaleString()}</div>
              <div className="text-[11px] text-aether-muted-dim">tasks run</div>
            </div>
            <div>
              <div className="font-mono text-[22px] font-bold tabular-nums">{avgSecs}s</div>
              <div className="text-[11px] text-aether-muted-dim">avg duration</div>
            </div>
            <div>
              <div className="font-mono text-[22px] font-bold tabular-nums text-aether-green">{successRate}%</div>
              <div className="text-[11px] text-aether-muted-dim">success rate</div>
            </div>
          </div>
          {degraded > 0 ? (
            // QA3-F-03: degraded (letterless) runs are counted distinctly
            // rather than silently absorbed into — or dropped from — the
            // success figure above.
            <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-[11px] text-aether-muted-dim">
              {/* Rule D-1: a degrade is neither success-green nor failure-red. */}
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-state-degraded" aria-hidden="true" />
              {degraded} degraded run{degraded === 1 ? "" : "s"} excluded from success
            </p>
          ) : null}
        </div>

        {/* Error log */}
        <div className="elev-1 min-w-0 rounded-2xl p-5" data-testid="error-log">
          <h3 className="mb-3 text-[13px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">Error Log</h3>
          {runs.length === 0 ? (
            <p className="py-4 text-center text-xs text-aether-muted-dim">No log entries yet.</p>
          ) : (
            <div className="mono space-y-1.5 text-[11px]">
              {runs.slice(0, 6).map((run) => {
                const level = logLevel(run, now);
                return (
                  <p key={run.id} className="flex items-start gap-2">
                    <span className={`w-8 shrink-0 font-bold ${level.cls}`}>{level.tag}</span>
                    <span className="shrink-0 text-aether-muted-dim">
                      {/* parseServerTime, not `new Date`: the API's naive UTC
                          stamps carry no timezone designator, so a bare parse
                          prints them in the viewer's own offset — ten hours
                          wrong for this product's en-AU owner. */}
                      {parseServerTime(run.startedAt) !== null
                        ? new Date(parseServerTime(run.startedAt) as number).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "--:--"}
                    </span>
                    <span className="truncate text-aether-muted">
                      {isStalledRun(run, now)
                        ? `${run.agentName} ${stalledLabel(run, now)} — no worker attached`
                        : (run.error ??
                          (coverLetterDegraded(run)
                            ? `${run.agentName} unavailable (degraded)`
                            : `${run.agentName} ${run.status}`))}
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
