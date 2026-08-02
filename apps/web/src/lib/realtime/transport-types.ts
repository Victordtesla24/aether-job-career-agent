/**
 * The seam between the realtime store and the wire (W-RT).
 *
 * The store owns connection lifecycle, fan-out and the honest state machine;
 * the transport owns bytes. Keeping them apart is what lets the store be
 * tested against a scripted stream with no network, and lets the transport be
 * swapped without touching a single screen.
 */

/** Resource keys the server can report on.
 *
 * Kept in sync with `REALTIME_RESOURCES` in
 * `apps/api/app/services/workspace_event_stream.py`. The server also serves
 * this list at `GET /events/resources`, so a drift is discoverable at runtime
 * rather than silent.
 */
export const REALTIME_RESOURCES = [
  "jobs",
  "applications",
  "coverLetters",
  "resumes",
  "stories",
  "emails",
  "contacts",
  "outreach",
  "interviews",
  "offers",
  "approvals",
  "agentRuns",
] as const;

export type RealtimeResource = (typeof REALTIME_RESOURCES)[number];

/** One resource's observed state, exactly as the server reported it. */
export interface ResourceWatermark {
  count: number;
  watermark: string | null;
}

/**
 * A change the client is told about. `reason` names the evidence:
 *  - `count_changed` / `watermark_advanced` — the server observed it live.
 *  - `reconnect_gap` — the store itself observed it, by diffing the snapshot in
 *    the new connection's `hello` against the last snapshot it held. That is a
 *    real, checkable difference between two server-reported observations, not
 *    an assumption that "something probably happened".
 */
export interface ResourceChange {
  resource: RealtimeResource;
  count: number;
  watermark: string | null;
  previousCount: number | null;
  previousWatermark: string | null;
  reason: "count_changed" | "watermark_advanced" | "reconnect_gap";
}

/** Why a connection ended. Drives whether the store retries and what it tells
 * the user — a refusal the server explained must never be shown as a generic
 * network blip, and vice versa. */
export interface RealtimeCloseReason {
  /**
   * - `network` — the connection dropped or could not be established. Retry.
   * - `refused` — the server answered with a non-2xx and a real reason
   *   (429 stream cap, 503 capacity/unreadable state, 401 session expired).
   * - `ended`   — the body ended cleanly without the server saying why.
   */
  kind: "network" | "refused" | "ended";
  status?: number;
  message: string;
}

export interface RealtimeTransportCallbacks {
  /** The HTTP response arrived and the body is being read. NOT proof the
   * stream works end to end — only the server's `hello` frame is that. */
  onOpen(): void;
  onEvent(event: string, data: unknown): void;
  /** An SSE comment line (`: heartbeat …`) — traffic, not an event. */
  onComment(text: string): void;
  onClose(reason: RealtimeCloseReason): void;
}

export interface RealtimeTransportHandle {
  close(): void;
}

export type RealtimeTransport = (
  callbacks: RealtimeTransportCallbacks,
) => RealtimeTransportHandle;
