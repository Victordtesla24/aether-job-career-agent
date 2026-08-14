"use client";

/**
 * Operations — task queue, performance metrics and error log (wireframe:
 * agent-monitor.html, DEF-001..004). Statuses and log rows are derived from
 * the live run history passed in by the Agents page.
 *
 * ORCH-DEDUP (2026-08-14): this used to also render its own workflow
 * node-graph, section header ("Agent Orchestration" title + online/queue/
 * stalled counts) and Pause All / Manual Override controls. All three
 * duplicated content the page already renders once each — the DEFINED
 * end-to-end workflow map(s) (`OrchestrationMap`, mounted just above this
 * component in page.tsx) superseded the node-graph, and the page-level stat
 * rail (page.tsx, above the maps section) already carries the online/
 * running/stalled counts. Removed rather than kept as a second copy; see
 * git history for the prior version.
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
  runs,
}: {
  // ORCH-DEDUP: `agents` stays part of the contract even though this
  // stripped-down component no longer reads it. Its only two former
  // consumers here — the header's "N agents online" count and the
  // node-graph's per-node status lookup — were removed with the header and
  // the node-graph (see the file-header note). Dropping the prop from the
  // type would force every call site (page.tsx and both Orchestration test
  // files) to change for no behavioural gain, which the ORCH-DEDUP ruling
  // asks this fix to avoid ("keep page.tsx edits minimal — the mount +
  // section ordering only"; kept-panel tests stay unmodified where possible).
  agents: AgentSummary[];
  runs: AgentRun[];
}) {
  // Staleness is a function of elapsed time, not of any server event, so the
  // widget re-renders on a clock as well as on realtime refetches — otherwise a
  // run that goes stale while the screen is open keeps its spinner forever.
  const now = useNow();
  const queueRuns = runs.filter(isInFlight);
  const liveRuns = queueRuns.filter((r) => isLiveRun(r, now));
  const stalledRuns = queueRuns.filter((r) => isStalledRun(r, now));
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
      {/* ORCH-DEDUP: a single quiet eyebrow replaces the former "Agent
          Orchestration" title + online/queue/stalled status line (now the
          page-level stat rail's job, above the maps section in page.tsx) and
          the Pause All / Manual Override controls (removed with it — see the
          file-header note). This band is what remains: Task Queue,
          Performance and Error Log, in their existing restyled treatment. */}
      <h2 className="ag-eyebrow">
        <span>Operations</span>
      </h2>

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Task queue */}
        <div className="ag-panel min-w-0 p-5" data-testid="task-queue">
          <h3 className="ag-eyebrow mb-4">
            <span>Task Queue</span>
          </h3>
          {tasks.length === 0 ? (
            <p className="py-4 text-center text-xs text-aether-muted-dim">Queue is empty — trigger a run above.</p>
          ) : (
            <div className="space-y-3.5">
              {tasks.map((t) => (
                <div key={t.key}>
                  <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[11px]">
                    <span
                      className={`min-w-0 truncate ${t.stalled ? "text-aether-amber" : "capitalize text-aether-muted"}`}
                    >
                      {t.label}
                    </span>
                    {/* No fabricated percentage for in-progress work — only a
                        real, completed-run 100% is ever shown as a number. A
                        stalled run gets neither: "…" would imply it is still
                        thinking. */}
                    <span className="mono shrink-0 tabular-nums text-aether-muted-dim">
                      {t.progress !== null ? `${t.progress}%` : t.stalled ? "—" : "…"}
                    </span>
                  </div>
                  <div className="ag-meter">
                    {t.progress !== null ? (
                      <div
                        className={
                          t.degraded ? "bg-white/25" : t.active ? "bg-aether-coral" : "bg-aether-green"
                        }
                        style={{ width: `${t.progress}%` }}
                      />
                    ) : t.stalled ? (
                      // CRITICAL-2: inert and unanimated. No role="progressbar"
                      // either — nothing is progressing.
                      <div className="w-full bg-aether-amber/25" />
                    ) : (
                      <div
                        role="progressbar"
                        className="w-full animate-pulse bg-aether-coral/40"
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
        <div className="ag-panel min-w-0 p-5" data-testid="performance-metrics">
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
          <h3 className="ag-eyebrow mb-4">
            <span className="flex flex-wrap items-baseline gap-x-1.5">
              Performance
              <span className="text-[10px] font-normal normal-case tracking-[0.02em] text-aether-muted-dim">
                · last {runs.length.toLocaleString()} run{runs.length === 1 ? "" : "s"}
              </span>
            </span>
          </h3>
          {/* Rule 4: a big tabular figure with its unit demoted to a small
              suffix and a small grey caption beneath — the Mercury/Amplitude
              numeral hierarchy, not three equal-weight numbers in a row. */}
          <div className="grid grid-cols-3 gap-3">
            <div className="ag-stat">
              <span className="ag-stat-figure">{runs.length.toLocaleString()}</span>
              <span className="ag-stat-label">tasks run</span>
            </div>
            <div className="ag-stat">
              <span className="ag-stat-figure">
                {avgSecs}
                <span className="ag-stat-unit">s</span>
              </span>
              <span className="ag-stat-label">avg duration</span>
            </div>
            <div className="ag-stat">
              <span className="ag-stat-figure text-aether-green">
                {successRate}
                <span className="ag-stat-unit text-aether-green/70">%</span>
              </span>
              <span className="ag-stat-label">success rate</span>
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
        <div className="ag-panel min-w-0 p-5" data-testid="error-log">
          <h3 className="ag-eyebrow mb-3">
            <span>Error Log</span>
          </h3>
          {runs.length === 0 ? (
            <p className="py-4 text-center text-xs text-aether-muted-dim">No log entries yet.</p>
          ) : (
            // Raycast's metadata-list register: a fixed level column, a fixed
            // time column, then the message — aligned by grid, separated by a
            // whisper of a hairline rather than by boxes.
            <div className="mono text-[11px]">
              {runs.slice(0, 6).map((run) => {
                const level = logLevel(run, now);
                return (
                  <p key={run.id} className="ag-log-row">
                    <span className={`shrink-0 text-[9.5px] font-bold tracking-[0.08em] ${level.cls}`}>
                      {level.tag}
                    </span>
                    <span className="shrink-0 whitespace-nowrap tabular-nums text-aether-muted-dim">
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
