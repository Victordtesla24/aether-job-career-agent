// @vitest-environment jsdom
/**
 * DEF-EXT-002 regression guard.
 *
 * jobs.ts previously baked
 * `process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"` into a
 * MODULE-LOAD-TIME constant. Next.js inlines that fallback into the browser
 * bundle at build time (the env var is unset in prod builds), so every
 * jobs-API call from a real user's browser hit http://127.0.0.1:8000 — the
 * SERVER's own loopback address, unreachable from the client (mixed-content
 * + connection-refused, killing the /dashboard/jobs screen for every
 * external user). The fix routes jobs.ts's request() through client.ts's
 * window-aware `apiBaseUrl()`, which resolves to same-origin "/api" in the
 * browser instead of the SSR-only localhost fallback.
 *
 * This test pins that contract: with `NEXT_PUBLIC_API_BASE_URL` unset and
 * `window` defined (jsdom), fetchJobs must call fetch with a same-origin
 * "/api/..." URL, not the loopback fallback — i.e. the base URL must be
 * resolved at call time via apiBaseUrl(), not read from a module-load-time
 * constant.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchJobs } from "../../lib/api/jobs";

const JOB_FIXTURE = {
  id: "cjob123456789012345678901",
  title: "Senior Software Engineer (Python)",
  company: "Canva",
  location: "Sydney NSW",
  remote: false,
  description: "Build the backend platform.",
  source: "seek",
  sourceUrl: "https://www.seek.com.au/job/82650341",
  status: "discovered",
  fitScore: null,
  atsScore: null,
  saved: false,
};

describe("jobs API client — base URL resolution (DEF-EXT-002)", () => {
  const originalEnv = process.env.NEXT_PUBLIC_API_BASE_URL;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    if (originalEnv === undefined) {
      delete process.env.NEXT_PUBLIC_API_BASE_URL;
    } else {
      process.env.NEXT_PUBLIC_API_BASE_URL = originalEnv;
    }
  });

  it('resolves to same-origin "/api" in a browser environment, not the SSR loopback fallback', async () => {
    // Sanity check this test is actually running in a browser-like (jsdom) env.
    expect(typeof window).not.toBe("undefined");

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([JOB_FIXTURE]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchJobs(undefined, { token: "test-token" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/^\/api\/jobs/);
    expect(String(url)).not.toContain("127.0.0.1:8000");
  });
});
