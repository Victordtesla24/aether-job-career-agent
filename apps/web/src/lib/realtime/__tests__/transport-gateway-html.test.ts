/**
 * MON-020 round-2 (review FAIL-2) — CLASS COMPLETION for the realtime wire.
 *
 * `openWorkspaceStream` refuses honestly when the server says no, and it passes
 * the server's OWN words through so a 429 stream-cap or 503 capacity message
 * reaches the user verbatim. That is right for our API — but the same
 * intermediary that 524s a Sync also fronts `GET /events/stream`, and the
 * non-JSON fallback took the first 300 characters of the body:
 *
 *     } else if (body.trim()) { message = body.trim().slice(0, 300); }
 *
 * For a proxy error page those 300 characters are literal
 * `<!DOCTYPE html><html class="no-js">…` markup, which the realtime store then
 * shows as the connection's close reason. Bounded, but the same class of leak:
 * an intermediary's page rendered as if it were something we said.
 *
 * Contract: an HTML (or otherwise non-API) body is replaced by the SAME honest
 * sentence `apiRequest` uses — reusing the shared helpers, so the two paths
 * cannot drift — while a real `{"detail": "…"}` from our API is still passed
 * through word for word.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  RealtimeCloseReason,
  RealtimeTransportCallbacks,
} from "../transport-types";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return {
    ...actual,
    // The only thing stubbed: the browser session. Every helper under test
    // (isNonApiHtmlBody / gatewayErrorMessage) stays the REAL implementation.
    getToken: async () => "test-token",
    apiBaseUrl: () => "https://api.test",
  };
});

const { openWorkspaceStream } = await import("../transport");

const CF_524_HTML = `<!DOCTYPE html>
<html class="no-js" lang="en-US">
<head><title>aether.example | 524: A timeout occurred</title></head>
<body><div id="cf-error-details"><h1>Error <span>524</span></h1>
<p>Ray ID: 9a1b2c3d4e5f6789 &bull; 2026-08-13 23:06:11 UTC</p></div></body>
</html>`;

function refusal(status: number, body: string, contentType: string): Response {
  return {
    ok: false,
    status,
    headers: new Headers({ "Content-Type": contentType }),
    text: async () => body,
  } as unknown as Response;
}

/** Drive one connection attempt and resolve with the close reason it reports. */
function connectAndClose(): Promise<RealtimeCloseReason> {
  return new Promise<RealtimeCloseReason>((resolve) => {
    const callbacks: RealtimeTransportCallbacks = {
      onOpen: () => undefined,
      onEvent: () => undefined,
      onComment: () => undefined,
      onClose: (reason) => resolve(reason),
    };
    openWorkspaceStream(callbacks);
  });
}

describe("openWorkspaceStream — non-API refusal bodies (MON-020)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("never surfaces an intermediary's HTML as the close reason", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => refusal(524, CF_524_HTML, "text/html; charset=UTF-8")),
    );

    const reason = await connectAndClose();

    expect(reason.kind).toBe("refused");
    expect(reason.status).toBe(524);
    expect(reason.message).not.toContain("<");
    expect(reason.message.toLowerCase()).not.toContain("doctype");
    expect(reason.message).not.toContain("Ray ID");
    expect(reason.message.toLowerCase()).toContain("too long");
  });

  it("detects the HTML page even when the proxy mislabels the Content-Type", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => refusal(502, CF_524_HTML, "text/plain")));

    const reason = await connectAndClose();
    expect(reason.message).not.toContain("<");
    expect(reason.message.toLowerCase()).toContain("temporarily unavailable");
  });

  it("still passes our API's own refusal message through verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        refusal(
          429,
          JSON.stringify({ detail: "Too many live connections for this account." }),
          "application/json",
        ),
      ),
    );

    const reason = await connectAndClose();
    expect(reason.status).toBe(429);
    expect(reason.message).toBe("Too many live connections for this account.");
  });

  it("keeps a plain-text refusal body (not markup) as-is", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => refusal(503, '"capacity reached"', "application/json")),
    );

    const reason = await connectAndClose();
    expect(reason.message).toBe('"capacity reached"');
  });
});
