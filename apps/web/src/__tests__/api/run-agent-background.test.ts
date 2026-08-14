/**
 * MON-020 — the Agents screen's Run button reaches scout through the SAME
 * `/agents/scout/run` endpoint the Jobs Sync button uses, so it inherited the
 * identical Cloudflare 524. `runAgent` gained an explicit opt-in that asks the
 * endpoint to enqueue; it must be opt-in only, and it must still resolve to the
 * run's real terminal result (never a bare "enqueued" envelope handed to the
 * caller as if it were an outcome).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { runAgent } from "../../lib/api/agents";

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "Content-Type": "application/json" }),
    text: async () => JSON.stringify(payload),
    json: async () => payload,
  } as unknown as Response;
}

const OPTIONS = { token: "t", baseUrl: "https://api.test" } as const;

describe("runAgent — background opt-in (MON-020)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("stays synchronous by default — no query param is added", async () => {
    const fetchMock = vi.fn(async (_url: unknown) =>
      jsonResponse({ status: "completed", scored: 2 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const out = await runAgent("fit-scorer", {}, OPTIONS);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.test/agents/fit-scorer/run",
    );
    expect(out.scored).toBe(2);
  });

  it("asks for background mode when opted in, then resolves the REAL result", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async (url: unknown) => {
      if (String(url).includes("/agents/scout/run")) {
        return jsonResponse({ job_id: "bg-9", status: "enqueued" });
      }
      return jsonResponse({
        job_id: "bg-9",
        status: "completed",
        result: { persisted: 5, updated: 1, errors: [] },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const promise = runAgent("scout", { query: "q", location: "l" }, OPTIONS, {
      background: true,
    });
    const settled = promise.then((v) => v);
    await vi.advanceTimersByTimeAsync(6000);
    const out = await settled;

    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.test/agents/scout/run?background=true",
    );
    expect(String(fetchMock.mock.calls[1][0])).toBe("https://api.test/agents/jobs/bg-9");
    // The caller gets the run's real counts, not the enqueue envelope.
    expect(out.persisted).toBe(5);
    expect(out.status).toBeUndefined();
    vi.useRealTimers();
  });
});
