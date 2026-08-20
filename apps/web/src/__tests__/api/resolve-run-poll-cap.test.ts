/**
 * MON-020 — the client must not give up on a background run while the server
 * is still legitimately working on it.
 *
 * `resolveRun` polls a 202 enqueue envelope to a terminal state and, on its own
 * cap, throws "This is taking longer than expected…". That cap was 10 minutes,
 * chosen when only tailor/cover-letter runs used this path. Background discovery
 * changed the picture: a real scout pass measures 255-473s with a 968s (16 min)
 * worst case in the production discovery-cron log, and the worker's own ceiling
 * is now 1200s + a 120s watchdog margin. A client that stops at 10 minutes tells
 * the user the run is lost while the worker is mid-pass — the client-side twin
 * of the fabricated-timeout bug fixed server-side in `_job_stale_thresholds`.
 */
import { describe, expect, it, vi } from "vitest";

import { resolveRun } from "../../lib/api/agents";
import { ApiError } from "../../lib/api/client";

const MINUTE = 60 * 1000;

/**
 * Drive `resolveRun` on fake timers, answering every poll with `processing`
 * until `completeAfterMs` of virtual time has elapsed. Returns the promise plus
 * a pump that advances virtual time in poll-sized steps.
 */
function pollingHarness(completeAfterMs: number) {
  vi.useFakeTimers();
  const start = Date.now();
  const fetchMock = vi.fn(async () => {
    const elapsed = Date.now() - start;
    return {
      ok: true,
      status: 200,
      headers: new Headers({ "Content-Type": "application/json" }),
      text: async () => "",
      json: async () =>
        elapsed >= completeAfterMs
          ? { job_id: "bg-1", status: "completed", result: { persisted: 4 } }
          : { job_id: "bg-1", status: "processing" },
    } as unknown as Response;
  });
  vi.stubGlobal("fetch", fetchMock);

  const promise = resolveRun(
    { job_id: "bg-1", status: "enqueued" },
    { token: "t", baseUrl: "https://api.test" },
  );

  const pump = async (untilMs: number) => {
    for (let elapsed = 0; elapsed <= untilMs; elapsed += 3000) {
      await vi.advanceTimersByTimeAsync(3000);
    }
  };
  return { promise, pump, fetchMock };
}

describe("resolveRun — polling cap (MON-020)", () => {
  it("keeps polling past 10 minutes and returns a run that finishes at ~16 min", async () => {
    const { promise, pump } = pollingHarness(16 * MINUTE);
    const settled = promise.then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e }),
    );

    await pump(17 * MINUTE);
    const result = await settled;

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect((result.v as { persisted?: number }).persisted).toBe(4);
    }
    vi.useRealTimers();
  });

  it("still gives up eventually, with an honest message and no fabricated result", async () => {
    const { promise, pump } = pollingHarness(Number.POSITIVE_INFINITY);
    const settled = promise.then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e }),
    );

    await pump(24 * MINUTE);
    const result = await settled;

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.e).toBeInstanceOf(ApiError);
      const message = (result.e as ApiError).message;
      expect(message).toContain("still processing in the background");
      // Never invents an outcome for a run it stopped watching.
      expect(message.toLowerCase()).not.toContain("completed");
      expect(message.toLowerCase()).not.toContain("failed");
    }
    vi.useRealTimers();
  });
});

describe("resolveRun — LOOP-429 async job failure", () => {
  const RATE =
    "The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.";

  it("throws 503 carrying the job's Retry-After seconds, not a headerless 502", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ "Content-Type": "application/json" }),
        text: async () => "",
        json: async () => ({
          job_id: "bg-429",
          status: "failed",
          error: RATE,
          retryAfterSeconds: 812,
        }),
      })),
    );
    const pending = resolveRun(
      { job_id: "bg-429", status: "enqueued" },
      { token: "t", baseUrl: "https://api.test" },
    );
    const settled = pending.then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e }),
    );
    await vi.advanceTimersByTimeAsync(4_000);
    const result = await settled;
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.e).toBeInstanceOf(ApiError);
      const err = result.e as ApiError;
      expect(err.status).toBe(503);
      expect(err.retryAfterSeconds).toBe(812);
      expect(err.message).toBe(RATE);
    }
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });
});
