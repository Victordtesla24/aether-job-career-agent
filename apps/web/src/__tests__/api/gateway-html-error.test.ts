/**
 * MON-020 — an intermediary's HTML error page must never reach the user.
 *
 * The Jobs "Sync" button POSTed a request that Cloudflare timed out at ~100s.
 * Cloudflare answers with its own `text/html` error page; `apiRequest` embedded
 * that body verbatim into `ApiError.message` (`${method} ${path} failed
 * (${status}): ${detail}`), and every screen that renders `e.message` dumped raw
 * Cloudflare markup ("<!DOCTYPE html>… Error 524 … cf-error-details …") into the
 * page.
 *
 * This is a defect in the SHARED helper, so the fix belongs there: any error
 * body that is HTML (or otherwise not something our API produced) is replaced
 * with an honest, human sentence keyed off the real status. Nothing is
 * fabricated — the status stays on `ApiError.status`, and a JSON body from our
 * own API is passed through completely unchanged.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, describeApiError } from "../../lib/api/client";

const CF_524_HTML = `<!DOCTYPE html>
<html class="no-js" lang="en-US">
<head>
<title>aether.example | 524: A timeout occurred</title>
<style>body{margin:0;padding:0}</style>
</head>
<body>
<div id="cf-error-details" class="p-0">
  <h1>Error <span>524</span></h1>
  <h2 class="cf-subheadline">A timeout occurred</h2>
  <p>Ray ID: 9a1b2c3d4e5f6789 &bull; 2026-08-13 23:06:11 UTC</p>
</div>
</body>
</html>`;

function htmlResponse(status: number, body = CF_524_HTML): Response {
  return {
    ok: false,
    status,
    headers: new Headers({ "Content-Type": "text/html; charset=UTF-8" }),
    text: async () => body,
    json: async () => {
      throw new SyntaxError("Unexpected token <");
    },
  } as unknown as Response;
}

function jsonErrorResponse(status: number, payload: unknown): Response {
  return {
    ok: false,
    status,
    headers: new Headers({ "Content-Type": "application/json" }),
    text: async () => JSON.stringify(payload),
    json: async () => payload,
  } as unknown as Response;
}

const OPTIONS = { token: "test-token", baseUrl: "https://api.test" } as const;

describe("apiRequest — non-JSON gateway error bodies (MON-020)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("never leaks Cloudflare's HTML into the error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => htmlResponse(524)));

    const err = await apiRequest("/agents/scout/run", {
      ...OPTIONS,
      method: "POST",
    }).then(
      () => null,
      (e: unknown) => e,
    );

    expect(err).toBeInstanceOf(ApiError);
    const message = (err as ApiError).message;
    expect(message).not.toContain("<");
    expect(message.toLowerCase()).not.toContain("doctype");
    expect(message.toLowerCase()).not.toContain("cf-error-details");
    expect(message).not.toContain("Ray ID");
    // Honest: it says the request timed out and that the work may still be
    // running server-side — it does NOT claim success or claim failure.
    expect(message.toLowerCase()).toContain("too long");
    expect((err as ApiError).status).toBe(524);
  });

  it("renders the friendly sentence through describeApiError too", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => htmlResponse(524)));

    const err = await apiRequest("/agents/scout/run", {
      ...OPTIONS,
      method: "POST",
    }).catch((e: unknown) => e);

    const text = describeApiError(err, "Discovery run failed");
    expect(text).not.toContain("<");
    expect(text.length).toBeLessThanOrEqual(300);
    expect(text.toLowerCase()).toContain("too long");
  });

  it("classifies a 502/503 HTML page as temporarily unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => htmlResponse(502, "<html><body>Bad Gateway</body></html>")));

    const err = (await apiRequest("/jobs", OPTIONS).catch((e: unknown) => e)) as ApiError;
    expect(err.message).not.toContain("<");
    expect(err.message.toLowerCase()).toContain("temporarily unavailable");
  });

  it("detects an HTML body even when the Content-Type header lies", async () => {
    const res = {
      ok: false,
      status: 500,
      headers: new Headers({ "Content-Type": "text/plain" }),
      text: async () => CF_524_HTML,
      json: async () => ({}),
    } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn(async () => res));

    const err = (await apiRequest("/jobs", OPTIONS).catch((e: unknown) => e)) as ApiError;
    expect(err.message).not.toContain("<");
    expect(err.message).not.toContain("Ray ID");
  });

  it("leaves a real JSON error from our own API completely untouched", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonErrorResponse(422, { detail: "job_id is required" })),
    );

    const err = (await apiRequest("/agents/tailor/run", {
      ...OPTIONS,
      method: "POST",
    }).catch((e: unknown) => e)) as ApiError;

    expect(err.message).toBe(
      'POST /agents/tailor/run failed (422): {"detail":"job_id is required"}',
    );
  });

  it("still lifts the structured detail object from a JSON quota 429", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonErrorResponse(429, {
          detail: { code: "quota_exceeded", runsUsed: 100, runsAllowed: 100 },
        }),
      ),
    );

    const err = (await apiRequest("/agents/tailor/run", {
      ...OPTIONS,
      method: "POST",
    }).catch((e: unknown) => e)) as ApiError;

    expect(err.detail?.code).toBe("quota_exceeded");
    expect(err.detail?.runsUsed).toBe(100);
  });
});
