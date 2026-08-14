"use client";

/**
 * P1-B — the "Run everything" state machine.
 *
 * POST /agents/orchestration/run-everything answers 202 with a PLAN ID and
 * hands the work to ONE queue job (ADR-AGI-3: 19 competing jobs would defeat
 * the ordering, the spacing and the SSE admission cap in a single move). The
 * response therefore proves only that a plan was ADMITTED — it says nothing
 * about what the plan did. So this hook claims nothing from it: every outcome
 * it reports is read back off the recorded plan row, which is the only place a
 * step transition is persisted.
 *
 * FOUR BEHAVIOURS WORTH NAMING:
 *  - a 409 is not an error to shrug at. The server refuses a SECOND plan while
 *    one is live (R-1) and hands back the id of the plan that IS running, so
 *    this attaches to that plan and shows the server's sentence, rather than
 *    telling the user "nothing happened" while 19 dispatches are in flight.
 *  - polling stops the moment the row reaches a terminal status. There is no
 *    "poll forever" path.
 *  - a transient poll failure does NOT invent a terminal state; the last known
 *    record stands and the honest transport message is surfaced beside it.
 *  - after the watch window the hook stops polling and SAYS it stopped. The
 *    plan keeps running server-side; claiming otherwise would be a lie about
 *    someone else's process.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, describeApiError } from "../../lib/api/client";
import {
  fetchRunPlan as defaultFetchRunPlan,
  isTerminalPlanStatus,
  startRunEverything as defaultStartRunEverything,
  type RunEverythingAccepted,
  type RunPlanRecord,
} from "../../lib/api/orchestrationPlan";

export type RunEverythingPhase = "idle" | "starting" | "running" | "settled" | "error";

export interface RunEverythingState {
  phase: RunEverythingPhase;
  /** The plan being watched — never invented; null until the server names one. */
  planId: string | null;
  /** The last RECORDED plan row read back, or null before the first read. */
  record: RunPlanRecord | null;
  /** An honest message from the server or the transport; null when there is none. */
  error: string | null;
}

export interface UseRunEverythingOptions {
  start?: () => Promise<RunEverythingAccepted>;
  fetchPlan?: (planId: string) => Promise<RunPlanRecord>;
  intervalMs?: number;
}

const DEFAULT_INTERVAL_MS = 3000;

/**
 * How long this console keeps watching one plan.
 *
 * A 19-dispatch plan spaced 5s apart, with discovery legitimately measuring
 * 255–473s (968s worst case, production discovery-cron), can run for a long
 * time; the server's own watchdog releases a plan whose worker died. 45 minutes
 * sits above the realistic tail and below "watch forever".
 */
const WATCH_CAP_MS = 45 * 60 * 1000;

const WATCH_CAP_MESSAGE =
  "This console stopped watching after 45 minutes. The plan keeps running on " +
  "the server — reopen this page to pick up its recorded state.";

const IDLE: RunEverythingState = { phase: "idle", planId: null, record: null, error: null };

/** The plan id the server hands back on a 409 "already running", if it did. */
function livePlanIdFrom(error: unknown): { planId: string; message: string } | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const detail = error.detail;
  const planId = detail && typeof detail.planId === "string" ? detail.planId : null;
  if (!planId) return null;
  const message =
    detail && typeof detail.message === "string" && detail.message.trim().length > 0
      ? detail.message
      : "A run plan is already in flight for this account.";
  return { planId, message };
}

export function useRunEverything(options: UseRunEverythingOptions = {}): {
  state: RunEverythingState;
  run: () => Promise<void>;
  dismiss: () => void;
} {
  const { start, fetchPlan, intervalMs = DEFAULT_INTERVAL_MS } = options;
  const [state, setState] = useState<RunEverythingState>(IDLE);
  const startedAt = useRef<number>(0);
  // Kept in refs so changing an injected function cannot restart a live poll.
  // Written in an effect rather than during render: a render-phase mutation is
  // exactly what StrictMode's double-invoke exists to catch.
  const startRef = useRef(start);
  const fetchRef = useRef(fetchPlan);
  useEffect(() => {
    startRef.current = start;
    fetchRef.current = fetchPlan;
  }, [start, fetchPlan]);

  const run = useCallback(async () => {
    let blocked = false;
    setState((prev) => {
      if (prev.phase === "starting" || prev.phase === "running") {
        blocked = true;
        return prev;
      }
      return { phase: "starting", planId: null, record: null, error: null };
    });
    if (blocked) return;
    try {
      const accepted = await (startRef.current ?? defaultStartRunEverything)();
      startedAt.current = Date.now();
      setState({ phase: "running", planId: accepted.planId, record: null, error: null });
    } catch (e) {
      const live = livePlanIdFrom(e);
      if (live) {
        startedAt.current = Date.now();
        setState({ phase: "running", planId: live.planId, record: null, error: live.message });
        return;
      }
      setState({
        phase: "error",
        planId: null,
        record: null,
        error: describeApiError(e, "Starting the plan failed."),
      });
    }
  }, []);

  const dismiss = useCallback(() => setState(IDLE), []);

  const planId = state.planId;
  const watching = state.phase === "running" && planId !== null;

  useEffect(() => {
    if (!watching || !planId) return undefined;
    let cancelled = false;
    const timer = setInterval(() => {
      void (async () => {
        if (Date.now() - startedAt.current > WATCH_CAP_MS) {
          clearInterval(timer);
          if (!cancelled) setState((prev) => ({ ...prev, error: WATCH_CAP_MESSAGE }));
          return;
        }
        try {
          const record = await (fetchRef.current ?? defaultFetchRunPlan)(planId);
          if (cancelled) return;
          setState((prev) =>
            prev.planId !== planId
              ? prev
              : {
                  phase: isTerminalPlanStatus(record.status) ? "settled" : prev.phase,
                  planId,
                  record,
                  error: null,
                },
          );
        } catch (e) {
          if (cancelled) return;
          // The plan is still whatever the server says it is; only the READ
          // failed, so the last record stands and the failure is named.
          setState((prev) =>
            prev.planId !== planId
              ? prev
              : { ...prev, error: describeApiError(e, "Reading the plan's state failed.") },
          );
        }
      })();
    }, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [watching, planId, intervalMs]);

  return { state, run, dismiss };
}
