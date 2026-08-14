// @vitest-environment jsdom
/**
 * P1-B — the "Run everything" state machine (ADR-AGI-3 P1-B: the global
 * control over POST /agents/orchestration/run-everything).
 *
 * The endpoint answers 202 with a PLAN ID and does the work on the queue, so
 * the console cannot know an outcome from the response — it has to read the
 * recorded plan. Everything this hook may claim therefore comes from a
 * persisted transition, which is exactly what these tests pin:
 *
 *   1. accepting the 202 puts the console in `running`, never in a success;
 *   2. the plan record is polled until the SERVER records a terminal state,
 *      and the terminal state is reported as recorded (`partial` stays
 *      partial);
 *   3. a 409 "already running" attaches to the plan that IS running and shows
 *      the API's message — it never starts a second plan;
 *   4. a start failure is an honest error, with no plan id invented;
 *   5. polling stops once the plan is terminal (no unbounded traffic).
 *
 * Written BEFORE the implementation.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api/client";
import { useRunEverything } from "../../components/agents/use-run-everything";
import type { RunPlanRecord } from "../../lib/api/orchestrationPlan";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.useFakeTimers();
});

const ACCEPTED = {
  job_id: "job-1",
  planId: "plan-1",
  status: "enqueued",
  stepCount: 19,
  cardCount: 21,
  concurrency: 1,
};

function planRecord(over: Partial<RunPlanRecord> = {}): RunPlanRecord {
  return {
    id: "plan-1",
    status: "running",
    initiator: "user",
    concurrency: 1,
    spacingSeconds: 5,
    steps: [],
    summary: null,
    haltedAtStep: null,
    haltReason: null,
    startedAt: "2026-08-14T09:00:00",
    finishedAt: null,
    createdAt: "2026-08-14T09:00:00",
    updatedAt: "2026-08-14T09:00:00",
    ...over,
  } as RunPlanRecord;
}

/** Minimal harness — the hook is driven through a real component. */
function Harness({
  start,
  fetchPlan,
}: {
  start: () => Promise<typeof ACCEPTED>;
  fetchPlan: (planId: string) => Promise<RunPlanRecord>;
}) {
  const { state, run } = useRunEverything({ start, fetchPlan, intervalMs: 1000 });
  return (
    <div>
      <button type="button" data-testid="go" onClick={() => void run()}>
        go
      </button>
      <span data-testid="phase">{state.phase}</span>
      <span data-testid="plan-id">{state.planId ?? ""}</span>
      <span data-testid="status">{state.record?.status ?? ""}</span>
      <span data-testid="error">{state.error ?? ""}</span>
    </div>
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("RUN EVERYTHING — the state machine only claims what the server recorded", () => {
  it("goes running on the 202 and reports no outcome yet", async () => {
    const start = vi.fn().mockResolvedValue(ACCEPTED);
    const fetchPlan = vi.fn().mockResolvedValue(planRecord());
    render(<Harness start={start} fetchPlan={fetchPlan} />);

    await act(async () => {
      screen.getByTestId("go").click();
    });
    await flush();

    expect(start).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("phase").textContent).toBe("running");
    expect(screen.getByTestId("plan-id").textContent).toBe("plan-1");
    expect(screen.getByTestId("error").textContent).toBe("");
  });

  it("polls the recorded plan and settles on the state the server recorded", async () => {
    const start = vi.fn().mockResolvedValue(ACCEPTED);
    const fetchPlan = vi
      .fn()
      .mockResolvedValueOnce(planRecord({ status: "running" }))
      .mockResolvedValue(
        planRecord({ status: "partial", finishedAt: "2026-08-14T09:30:00" }),
      );
    render(<Harness start={start} fetchPlan={fetchPlan} />);

    await act(async () => {
      screen.getByTestId("go").click();
    });
    await flush();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId("phase").textContent).toBe("running");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId("phase").textContent).toBe("settled");
    expect(screen.getByTestId("status").textContent).toBe("partial");

    const callsAtSettle = fetchPlan.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchPlan.mock.calls.length).toBe(callsAtSettle);
  });

  it("attaches to the plan already running on a 409 instead of starting a second", async () => {
    const start = vi.fn().mockRejectedValue(
      new ApiError("conflict", 409, undefined, {
        error: "plan_already_running",
        message: "A run plan is already in flight for this account",
        planId: "plan-live",
        planStatus: "running",
      }),
    );
    const fetchPlan = vi.fn().mockResolvedValue(planRecord({ id: "plan-live" }));
    render(<Harness start={start} fetchPlan={fetchPlan} />);

    await act(async () => {
      screen.getByTestId("go").click();
    });
    await flush();

    expect(screen.getByTestId("plan-id").textContent).toBe("plan-live");
    expect(screen.getByTestId("phase").textContent).toBe("running");
    expect(screen.getByTestId("error").textContent).toContain(
      "A run plan is already in flight for this account",
    );
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("reports an honest error and invents no plan id when the start is refused", async () => {
    const start = vi
      .fn()
      .mockRejectedValue(new ApiError("background generation is disabled", 503));
    const fetchPlan = vi.fn();
    render(<Harness start={start} fetchPlan={fetchPlan} />);

    await act(async () => {
      screen.getByTestId("go").click();
    });
    await flush();

    expect(screen.getByTestId("phase").textContent).toBe("error");
    expect(screen.getByTestId("plan-id").textContent).toBe("");
    expect(screen.getByTestId("error").textContent).toContain(
      "background generation is disabled",
    );
    expect(fetchPlan).not.toHaveBeenCalled();
  });
});
