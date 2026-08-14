/**
 * MF-A (round-5 re-review) — `apps/web/src/lib/api` never bounded ANY fetch
 * with a timeout (see the reviewer's never-settling-mock probe,
 * `uat/reports/evidence/models-live/u2b-r5-probe-20260814/
 * reviewer-probe-failure-paths.test.tsx` PROBE A), which let a hung
 * `GET /resumes/{id}/fidelity` connection leave `ApprovalModal`'s frozen
 * "Original layout preserved" claim on screen indefinitely — see
 * `components/approvals/__tests__/live-fidelity.test.tsx` for that half of
 * the fix. This file locks the other half: `apiRequest`'s opt-in
 * `timeoutMs` actually aborts a stalled request, and `fetchResumeFidelity`
 * uses it by default.
 *
 * Driven on fake timers (the `resolveRun` polling-cap precedent,
 * `__tests__/api/resolve-run-poll-cap.test.ts`) so this suite is fast and
 * deterministic rather than waiting out real wall-clock seconds.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "../client";
import { FIDELITY_FETCH_TIMEOUT_MS, fetchResumeFidelity } from "../resumes";

const OPTIONS = { token: "test-token", baseUrl: "https://api.test" } as const;

/** A `fetch` stub that never resolves on its own — only an abort of the
 *  request's own `signal` ever settles it, exactly like a real stalled
 *  connection reacting to `AbortController.abort()`. */
function hangingFetchRespectingAbort() {
  return vi.fn((_input: unknown, init?: { signal?: AbortSignal }) => {
    return new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        reject(new DOMException("The operation was aborted.", "AbortError"));
      });
    });
  });
}

function settle<T>(promise: Promise<T>) {
  return promise.then(
    (v) => ({ ok: true as const, v }),
    (e: unknown) => ({ ok: false as const, e }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("apiRequest — timeoutMs (MF-A)", () => {
  it("aborts and rejects honestly once timeoutMs elapses against a hung connection", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetchRespectingAbort());

    const settled = settle(
      apiRequest("/resumes/r1/fidelity", { ...OPTIONS, timeoutMs: 5000 }),
    );
    await vi.advanceTimersByTimeAsync(5000);
    const result = await settled;

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.e).toBeInstanceOf(Error);
    const message = (result.e as Error).message;
    // Honest and readable — never the opaque native AbortError string.
    expect(message.toLowerCase()).toContain("timed out");
    expect(message).toContain("5000ms");
    expect(message).not.toMatch(/^AbortError/);
  });

  it("never fires before timeoutMs — a response that lands just under the deadline still resolves", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(
      (_input: unknown, init?: { signal?: AbortSignal }) =>
        new Promise((resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          setTimeout(
            () =>
              resolve({
                ok: true,
                status: 200,
                headers: new Headers({ "Content-Type": "application/json" }),
                text: async () => "{}",
                json: async () => ({ ok: true }),
              } as Response),
            4000,
          );
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const settled = settle(apiRequest<{ ok: boolean }>("/ping", { ...OPTIONS, timeoutMs: 5000 }));
    await vi.advanceTimersByTimeAsync(4000);
    const result = await settled;

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.v).toEqual({ ok: true });
  });

  it("omitting timeoutMs keeps today's unbounded fetch — no AbortController, no timer, request still resolves after an arbitrarily long wait", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(
      (_input: unknown, _init?: RequestInit) =>
        new Promise((resolve) => {
          setTimeout(
            () =>
              resolve({
                ok: true,
                status: 200,
                headers: new Headers({ "Content-Type": "application/json" }),
                text: async () => "{}",
                json: async () => ({ ok: true }),
              } as Response),
            60_000,
          );
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const settled = settle(apiRequest<{ ok: boolean }>("/whatever", OPTIONS));
    await vi.advanceTimersByTimeAsync(60_000);
    const result = await settled;

    expect(result.ok).toBe(true);
    // The stub was called without a signal — confirms no AbortController was
    // constructed for this call (byte-identical to the pre-MF-A behavior).
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.signal).toBeUndefined();
  });
});

describe("fetchResumeFidelity — bounded by FIDELITY_FETCH_TIMEOUT_MS by default (MF-A)", () => {
  it("rejects once FIDELITY_FETCH_TIMEOUT_MS elapses against a hung connection, instead of hanging forever", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetchRespectingAbort());

    const settled = settle(fetchResumeFidelity("r1", OPTIONS));
    await vi.advanceTimersByTimeAsync(FIDELITY_FETCH_TIMEOUT_MS);
    const result = await settled;

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect((result.e as Error).message.toLowerCase()).toContain("timed out");
  });

  it("an explicit caller-supplied timeoutMs overrides the default", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetchRespectingAbort());

    const settled = settle(fetchResumeFidelity("r1", { ...OPTIONS, timeoutMs: 1000 }));
    await vi.advanceTimersByTimeAsync(1000);
    const result = await settled;

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect((result.e as Error).message).toContain("1000ms");
  });
});
