"use client";

/**
 * The wire for the shared realtime channel (W-RT).
 *
 * WHY NOT `EventSource`
 * ---------------------
 * This API authenticates with a bearer token held in `localStorage`
 * (`lib/api/client.ts`). `EventSource` cannot send request headers, so using it
 * would mean putting the JWT in the query string, where it lands in nginx
 * access logs, browser history and any referrer — a real credential leak for a
 * cosmetic convenience. `fetch` + a `ReadableStream` reader carries the same
 * `Authorization: Bearer` header as every other call, and gives honest access
 * to the HTTP status when the server refuses (429 stream cap, 503 capacity,
 * 401 expired session) instead of `EventSource`'s opaque `onerror`.
 *
 * FAILURE HANDLING
 * ----------------
 * Every exit path calls `onClose` exactly once with a REAL reason. Nothing here
 * retries; the store owns backoff, so retry policy lives in one place.
 */

import { apiBaseUrl, getToken } from "../api/client";
import type {
  RealtimeTransportCallbacks,
  RealtimeTransportHandle,
} from "./transport-types";

const STREAM_PATH = "/events/stream";

/** Split an SSE frame into its event name, data payload and comment lines. */
function parseFrame(frame: string): {
  event: string | null;
  data: string;
  comments: string[];
} {
  let event: string | null = null;
  const dataLines: string[] = [];
  const comments: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) {
      comments.push(line.slice(1).trim());
    } else if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }
  return { event, data: dataLines.join("\n"), comments };
}

/**
 * Open the workspace stream. Returns a handle whose `close()` aborts the
 * request; `onClose` still fires for the abort, and the store ignores it
 * because the connection generation has already moved on.
 */
export function openWorkspaceStream(
  callbacks: RealtimeTransportCallbacks,
): RealtimeTransportHandle {
  const controller = new AbortController();
  let closed = false;

  const finish = (reason: Parameters<RealtimeTransportCallbacks["onClose"]>[0]): void => {
    if (closed) return;
    closed = true;
    callbacks.onClose(reason);
  };

  void (async () => {
    let response: Response;
    try {
      const token = await getToken();
      response = await fetch(`${apiBaseUrl()}${STREAM_PATH}`, {
        method: "GET",
        headers: { Accept: "text/event-stream", Authorization: `Bearer ${token}` },
        signal: controller.signal,
        cache: "no-store",
      });
    } catch (error) {
      finish({
        kind: controller.signal.aborted ? "ended" : "network",
        message:
          error instanceof Error
            ? error.message
            : "Could not reach the server to open the live update stream.",
      });
      return;
    }

    if (!response.ok) {
      // The server said no and said why (StreamSlots 429/503, auth 401). Pass
      // its own words through untouched — the UI shows them verbatim.
      let message = `The server declined the live update stream (HTTP ${response.status}).`;
      try {
        const body = await response.text();
        const parsed = JSON.parse(body) as { detail?: unknown };
        if (typeof parsed.detail === "string" && parsed.detail.trim()) {
          message = parsed.detail;
        } else if (body.trim()) {
          message = body.trim().slice(0, 300);
        }
      } catch {
        // Non-JSON error body — the status-based message above stands.
      }
      finish({ kind: "refused", status: response.status, message });
      return;
    }

    if (!response.body) {
      finish({
        kind: "network",
        message: "The live update stream returned no readable body.",
      });
      return;
    }

    callbacks.onOpen();

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          finish({
            kind: "ended",
            message: "The live update stream ended without a reason from the server.",
          });
          return;
        }
        buffer += decoder.decode(value, { stream: true });
        let split = buffer.indexOf("\n\n");
        while (split !== -1) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          const { event, data, comments } = parseFrame(frame);
          comments.forEach((comment) => callbacks.onComment(comment));
          if (event) {
            let payload: unknown = data;
            try {
              payload = data ? JSON.parse(data) : {};
            } catch {
              // A frame we cannot parse is passed through as its raw text
              // rather than dropped, so nothing is silently lost.
            }
            callbacks.onEvent(event, payload);
          }
          split = buffer.indexOf("\n\n");
        }
      }
    } catch (error) {
      finish({
        kind: controller.signal.aborted ? "ended" : "network",
        message:
          error instanceof Error
            ? error.message
            : "The live update stream was interrupted.",
      });
    }
  })();

  return {
    close: () => {
      closed = true;
      controller.abort();
    },
  };
}
