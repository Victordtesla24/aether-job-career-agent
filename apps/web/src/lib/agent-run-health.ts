/**
 * Honest health of an agent run — the one place the UI decides whether work is
 * actually happening (CRITICAL-2).
 *
 * WHY THIS EXISTS. On 2026-08-03 a single `tailor` AgentRun had been sitting at
 * status='running' since 2026-07-26 03:41 UTC — 192.6 hours. Nothing was
 * attached to it: the worker had been restarted in between, which kills any
 * real job, and no server-side reaper ever reconciles an AgentRun row, so it
 * survives restarts forever. Every screen read that row's raw `status` and
 * painted it as work in progress — a coral "running" node, an indefinite
 * pulsing progress bar, "1 task in queue", "Agents Active". The product
 * therefore concealed a week of total inactivity behind a spinner.
 *
 * WHAT SIGNAL IS ACTUALLY AVAILABLE. Only what the row itself records — this
 * module invents nothing. A run that reports progress (`heartbeatAt`, stamped
 * by the executing worker) is alive by that evidence alone, however long it has
 * been going. Every row written before that column existed carries no stamp at
 * all, so the only remaining evidence is the row's own database-stamped anchor
 * (`startedAt`, falling back to `createdAt`): a run in flight longer than the
 * staleness window the BACKEND already applies to its own background jobs
 * cannot have a live worker behind it.
 *
 * The windows below are deliberately the SAME numbers as
 * `apps/api/app/routers/agents.py::_job_stale_thresholds` (enqueued > 15 min,
 * processing > 12 min), so the client's verdict about a dead run and the
 * server's watchdog verdict about a dead job cannot drift apart. They are
 * generous: a real synchronous pipeline run is ~30–120 s.
 *
 * WHAT THIS MODULE DOES NOT DO. It never mutates a run, never claims a run was
 * cancelled, and never invents a completion percentage. "Stalled" is a
 * statement about what the UI can honestly observe — the run has produced no
 * transition for longer than any real run takes — not a claim that the server
 * has given up on it.
 */
import type { AgentRun, AgentSummary } from "./api/agents";

/** A `running` run older than this has no live worker behind it (12 min). */
export const RUNNING_STALE_MS = 12 * 60_000;
/** A `queued` run older than this was never picked up (15 min). */
export const QUEUED_STALE_MS = 15 * 60_000;
/** How long an agent may go without producing output before we say so (24 h). */
export const NO_OUTPUT_GAP_MS = 24 * 60 * 60_000;

/** True when a completed coverLetter run degraded gracefully and produced no
 * letter (QA-RES-F). The cover-letter agent/worker set this exact flag on
 * every honest degrade path (LLM unavailable on first draft, fabrication/
 * structural guard rejection) — see apps/api/app/agents/cover_letter_agent.py,
 * apps/api/app/workers/tasks.py and apps/api/app/routers/agents.py, all of
 * which mark the run `completed` with `output.coverLetterUnavailable = true`
 * and `cover_letter_id: None`. Genuine successes always carry a real
 * `cover_letter_id` and never set this flag.
 *
 * Defined HERE (re-exported from components/dashboard/feed for the callers that
 * already import it there) so the output-gap accounting below and the feed
 * badges share one definition rather than two that can drift. */
export function coverLetterDegraded(run: AgentRun): boolean {
  if (run.agentName !== "coverLetter") return false;
  const out = run.output ?? {};
  return out.coverLetterUnavailable === true;
}

/** True when an autopilot (`boardSweep`) run is an honest SKIP rather than work
 * done (AUD-COV-2).
 *
 * The board-sweep autopilot does not auto-generate a cover letter for a job
 * below the user's own `agentConfig.matchThreshold` (or one that has never been
 * fit-scored) — writing a "direct match" opener for a role the fit-scorer
 * rejected is a claim the evidence does not support. It records that decision
 * as a zero-cost `boardSweep` run with `output.skipped = true`, which is
 * `completed` on purpose: nothing failed, and a red row for a correct refusal
 * would be dishonest the other way (the same reasoning GAP-P4-002 applied to
 * the cover-letter guard degrade above).
 *
 * But `completed` alone would let the run count as work produced, so — exactly
 * like `coverLetterDegraded` — the shape is named here once and read by both
 * `runProducedOutput` and the runs table's status cell. `=== true`, never a
 * truthy coercion, matching the strictness of the SQL and of the degrade check
 * above so no unrelated output shape can be misread as a skip. */
export function autopilotSkipped(run: AgentRun): boolean {
  if (run.agentName !== "boardSweep") return false;
  const out = run.output ?? {};
  return out.skipped === true;
}

/** The autopilot's own sentence explaining a skip, or `""` when the run is not
 * one. Quoted verbatim by the UI rather than restated, so the reason a user
 * reads is the reason the backend recorded. */
export function autopilotSkipMessage(run: AgentRun): string {
  if (!autopilotSkipped(run)) return "";
  const message = (run.output ?? {}).message;
  return typeof message === "string" ? message : "";
}

/** `queued` / `running` — the statuses that claim work is still happening. */
export function isInFlight(run: Pick<AgentRun, "status">): boolean {
  return run.status === "running" || run.status === "queued";
}

/** Matches an explicit UTC marker or numeric offset at the end of a timestamp. */
const TZ_SUFFIX = /(?:Z|z|[+-]\d{2}:?\d{2})$/;

/**
 * Parse a timestamp as the server meant it, not as the browser guesses.
 *
 * `AgentRun.startedAt` / `completedAt` / `createdAt` are naive Postgres
 * `timestamp` columns written with `NOW()` in UTC, and FastAPI serialises them
 * with NO timezone designator ("2026-07-26T03:41:20.278000"). ECMAScript says a
 * date-time form without an offset is LOCAL time, so `new Date()` silently
 * shifts every one of them by the viewer's UTC offset.
 *
 * That is not cosmetic here. This product's owner runs in Australia (the UI
 * formats with "en-AU"); at UTC+10 every run would be read as ten hours older
 * than it is, so a run started sixty seconds ago would cross the twelve-minute
 * window instantly and the whole screen would report healthy live work as
 * "stalled" — replacing one lie with another. Anchoring a naive stamp to UTC
 * matches exactly how the backend reads the same columns (`_job_age_seconds`:
 * "A naive timestamp is read as UTC").
 *
 * A stamp that DOES carry an offset is respected untouched.
 */
export function parseServerTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const normalized = TZ_SUFFIX.test(iso) ? iso : `${iso}Z`;
  const ms = new Date(normalized).getTime();
  return Number.isFinite(ms) ? ms : null;
}

/** Milliseconds since a timestamp, or `null` if it is missing/unparseable.
 *
 * Clamped at zero for the same reason the backend's `_job_age_seconds` clamps:
 * the hosted Postgres clock has been measured ~3 s AHEAD of the app server, so
 * a row read immediately after insertion can otherwise yield a negative age.
 * A negative age is nonsense to render, and clamping keeps the staleness
 * verdict fail-safe (a future-stamped row reads as brand new, never as old). */
export function ageMs(iso: string | null | undefined, now: number = Date.now()): number | null {
  const then = parseServerTime(iso);
  if (then === null) return null;
  return Math.max(0, now - then);
}

/**
 * The anchor a run's liveness is measured from.
 *
 * A worker that is genuinely executing stamps `heartbeatAt` as it goes, so a
 * FRESH heartbeat is positive evidence of life and outranks wall-clock age
 * entirely — a legitimately long run is never called stalled while it keeps
 * reporting. With no stamp at all (every row written before that column
 * existed, or a process that died before execution began) the only evidence
 * available is when the run started, falling back to when the row was created
 * (a queued run has no `startedAt`).
 */
export function runAnchor(run: AgentRun): string | null {
  return run.heartbeatAt ?? run.startedAt ?? run.createdAt ?? null;
}

/**
 * How long a run has been stalled, or `null` if it is not stalled.
 *
 * `null` for anything terminal (completed/failed — however old) and for an
 * in-flight run still inside its window: those are honest states already.
 *
 * The value returned is the time since the run's last observable movement,
 * which is what the UI reports ("stalled for 8 days") — not the run's total age.
 */
export function stalledForMs(run: AgentRun, now: number = Date.now()): number | null {
  if (!isInFlight(run)) return null;
  const age = ageMs(runAnchor(run), now);
  if (age === null) return null;
  return age >= staleLimitFor(run.status) ? age : null;
}

/**
 * The staleness window that applies to an in-flight status.
 *
 * Exported so a surface holding only a STATUS + a TIMESTAMP (no full run row —
 * e.g. the per-agent `lastRunStatus`/`lastRunAt` pair on
 * `GET /agents/orchestration-map`) applies the identical window rather than
 * inventing its own. Anything that is not `queued` is measured against the
 * running window, which is the shorter of the two: a status we do not
 * recognise never buys extra time to look alive.
 */
export function staleLimitFor(status: string): number {
  return status === "queued" ? QUEUED_STALE_MS : RUNNING_STALE_MS;
}

export function isStalledRun(run: AgentRun, now: number = Date.now()): boolean {
  return stalledForMs(run, now) !== null;
}

/** In flight AND still within its window — work that may genuinely be happening. */
export function isLiveRun(run: AgentRun, now: number = Date.now()): boolean {
  return isInFlight(run) && stalledForMs(run, now) === null;
}

/** "14 min" / "3 hr" / "8 days" — the unit a person actually reads. */
export function humanizeDuration(ms: number): string {
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${Math.max(0, mins)} min`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `${hrs} hr`;
  return `${Math.floor(hrs / 24)} days`;
}

/**
 * "stalled for 8 days" — ONE definition of the phrase, shared by every surface.
 *
 * `null` (no usable timestamp) deliberately still says "stalled": a row we
 * cannot date is not evidence of life, so it degrades to the honest word
 * without a fabricated duration.
 */
export function stalledPhrase(ms: number | null): string {
  return ms === null ? "stalled" : `stalled for ${humanizeDuration(ms)}`;
}

/** "stalled for 8 days" — the label every surface shows in place of a spinner. */
export function stalledLabel(run: AgentRun, now: number = Date.now()): string {
  return stalledPhrase(stalledForMs(run, now));
}

/**
 * What the user can actually do about a stalled run.
 *
 * There is no cancel/clear endpoint for an AgentRun (checked
 * apps/api/app/routers/agents.py — the only mutating agent routes are the
 * per-agent `/run` triggers, `/pipeline/run`, `/test-run` and provider/config
 * writes), so this deliberately offers only the action that really exists:
 * start a new run. It never promises the dead row will disappear.
 */
export const STALLED_RUN_ADVICE =
  "Nothing is working on it any more, and it will never finish on its own — " +
  "start a new run when you want this work done. The old row stays in the " +
  "audit trail.";

// ---------------------------------------------------------------------------
// "This agent has produced nothing since <date>"
// ---------------------------------------------------------------------------

/**
 * Did this run actually produce something?
 *
 * A `completed` run counts, EXCEPT a letterless coverLetter degrade, which is
 * recorded `completed` on purpose (the guard working is not a failure) but
 * produced no artefact. Anything queued/running/failed produced nothing yet.
 *
 * AUD-COV-2 adds the second such shape for the identical reason: an autopilot
 * low-fit SKIP is `completed` on purpose and produced nothing.
 */
export function runProducedOutput(run: AgentRun): boolean {
  return (
    run.status === "completed" && !coverLetterDegraded(run) && !autopilotSkipped(run)
  );
}

export interface AgentOutputGap {
  agent: string;
  /** ISO timestamp of the newest run that really produced something, or `null`
   *  when there is none in the window examined (we then claim no date). */
  lastProducedAt: string | null;
  /** Runs by this agent since then that produced nothing. */
  attempts: number;
  /** Oldest run examined for this agent — the honest bound on a `null` date. */
  oldestExaminedAt: string | null;
  /** True when at least one of those attempts is a stalled in-flight run. */
  stalled: boolean;
}

/**
 * Agents whose latest run produced nothing AND that have produced nothing for
 * at least `gapMs`.
 *
 * Derived entirely from the runs handed in — no agent name is hardcoded, and an
 * agent absent from the window is never mentioned (absence of data is not
 * evidence of failure). `runs` is expected newest-first, exactly as
 * `GET /agents/runs` returns it; it is re-sorted defensively anyway.
 */
export function agentOutputGaps(
  runs: AgentRun[],
  now: number = Date.now(),
  gapMs: number = NO_OUTPUT_GAP_MS,
): AgentOutputGap[] {
  const byAgent = new Map<string, AgentRun[]>();
  for (const run of runs) {
    const list = byAgent.get(run.agentName);
    if (list) list.push(run);
    else byAgent.set(run.agentName, [run]);
  }

  const gaps: AgentOutputGap[] = [];
  for (const [agent, list] of byAgent) {
    const ordered = [...list].sort(
      (a, b) => (parseServerTime(b.createdAt) ?? 0) - (parseServerTime(a.createdAt) ?? 0),
    );
    // The newest run producing output means the agent is working — say nothing.
    if (ordered.length === 0 || runProducedOutput(ordered[0])) continue;
    const producedIdx = ordered.findIndex(runProducedOutput);
    const productive = producedIdx === -1 ? null : ordered[producedIdx];
    const attempts = producedIdx === -1 ? ordered.length : producedIdx;
    const lastProducedAt = productive
      ? (productive.completedAt ?? productive.createdAt)
      : null;
    const oldestExaminedAt = ordered[ordered.length - 1]?.createdAt ?? null;
    // Anchor the "how long" on the last real output; with none in the window,
    // fall back to the oldest run we can actually see, so a fresh burst of
    // failures is not dressed up as a long-running drought.
    const anchor = lastProducedAt ?? oldestExaminedAt;
    const age = ageMs(anchor, now);
    if (age === null || age < gapMs) continue;
    gaps.push({
      agent,
      lastProducedAt,
      attempts,
      oldestExaminedAt,
      stalled: ordered.slice(0, Math.max(attempts, 1)).some((r) => isStalledRun(r, now)),
    });
  }
  return gaps.sort((a, b) => a.agent.localeCompare(b.agent));
}

/** The sentence shown for one gap. Never states a date it does not have. */
export function outputGapMessage(gap: AgentOutputGap, now: number = Date.now()): string {
  const attempts = `${gap.attempts} run${gap.attempts === 1 ? "" : "s"} since`;
  if (gap.lastProducedAt) {
    const when = new Date(parseServerTime(gap.lastProducedAt) ?? Date.now());
    const ms = ageMs(gap.lastProducedAt, now);
    const forHow = ms === null ? "" : ` (${humanizeDuration(ms)})`;
    return (
      `${gap.agent} has produced nothing since ${when.toLocaleString("en-AU")}${forHow} — ` +
      `${attempts}, none produced output.`
    );
  }
  const oldest = gap.oldestExaminedAt
    ? ` (recorded activity goes back to ${new Date(
        parseServerTime(gap.oldestExaminedAt) ?? Date.now(),
      ).toLocaleString("en-AU")})`
    : "";
  return (
    `${gap.agent} has no output at all in its ${gap.attempts} most recent ` +
    `run${gap.attempts === 1 ? "" : "s"}${oldest}.`
  );
}

// ---------------------------------------------------------------------------
// Sidebar Agent Pulse
// ---------------------------------------------------------------------------

export interface AgentPulse {
  running: number;
  stalled: number;
  total: number;
  /** Agents the user has not paused. Stop All makes this 0 — never "N ready". */
  ready: number;
}

/**
 * The sidebar pulse, computed from `GET /agents` summaries.
 *
 * A summary carries only the LATEST run's status plus its `last_run` timestamp,
 * so the same staleness window applies: an agent whose latest run says
 * "running" but started 8 days ago is stalled, not active, and "Agents Active"
 * must not light up for it.
 */
export function agentPulse(agents: AgentSummary[], now: number = Date.now()): AgentPulse {
  let running = 0;
  let stalled = 0;
  let ready = 0;
  for (const agent of agents) {
    if (agent.enabled !== false) ready += 1;
    if (agent.status !== "running" && agent.status !== "queued") continue;
    const age = ageMs(agent.last_run, now);
    const limit = agent.status === "queued" ? QUEUED_STALE_MS : RUNNING_STALE_MS;
    // No timestamp at all is not evidence of life — treat it as stalled rather
    // than lighting up "Agents Active" on a row we cannot date.
    if (age === null || age >= limit) stalled += 1;
    else running += 1;
  }
  return { running, stalled, total: agents.length, ready };
}
