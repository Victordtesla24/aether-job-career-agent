"use client";

/**
 * The dashboard's ONE realtime connection, fanned out to every screen (W-RT).
 *
 * WHY A STORE AND NOT A HOOK PER SCREEN
 * -------------------------------------
 * The server admits 3 concurrent SSE streams per user and 8 globally
 * (`app/services/agent_run_stream.py`, `StreamSlots`), a budget derived from
 * the deployment-wide 25-connection Postgres ceiling. Eleven screens each
 * opening their own stream would have most of them refused with a 429 — and
 * would be a real DoS surface besides. So exactly one connection is opened for
 * the whole tab, by the first screen that subscribes, and closed when the last
 * one leaves. Screens receive only the resources they asked for.
 *
 * WHAT IT PROMISES, AND WHAT IT REFUSES TO PRETEND
 * ------------------------------------------------
 * The stream carries no domain payloads — a `resource_changed` event says only
 * that the rows behind a screen moved (see the API module docstring). Screens
 * respond by refetching through their ordinary API client, so what renders is
 * always what the API actually returns; nothing is ever reconstructed from the
 * stream.
 *
 * When the stream is not working, this store SAYS SO. `status` is never `live`
 * unless the server's own `hello` frame arrived on the current connection and
 * the server has been heard from within {@link STALE_AFTER_MS}. A silently
 * dead socket — no error event, just nothing arriving — is the failure mode
 * that would otherwise leave a screen showing hours-old data under a "Live"
 * badge, so it is detected by a watchdog rather than assumed away.
 *
 * A reconnect does not blindly refetch everything: the new connection's
 * `hello` snapshot is diffed against the last one held, and only genuinely
 * moved resources are replayed (`reason: "reconnect_gap"`). Both sides of that
 * comparison are server observations, so the replay is evidence-backed rather
 * than a "probably something changed" guess.
 */

import { openWorkspaceStream } from "./transport";
import type {
  RealtimeCloseReason,
  RealtimeResource,
  RealtimeTransport,
  RealtimeTransportHandle,
  ResourceChange,
  ResourceWatermark,
} from "./transport-types";
import { REALTIME_RESOURCES } from "./transport-types";

export type { RealtimeResource, ResourceChange } from "./transport-types";
export { REALTIME_RESOURCES } from "./transport-types";

/**
 * How long the store will call itself `live` without hearing anything at all.
 *
 * The server heartbeats every 15s by default
 * (`AETHER_SSE_HEARTBEAT_SECONDS`, `app/services/agent_run_stream.py`). Three
 * missed heartbeats is decisive evidence the connection is gone even though no
 * error surfaced, which happens routinely with proxies, sleeping laptops and
 * dropped mobile links.
 */
export const STALE_AFTER_MS = 45_000;

/** Retry schedule after a drop. Capped so a server that is down does not get
 * hammered, and never zero so a flapping connection cannot hot-loop. */
const RETRY_DELAYS_MS = [1_000, 2_000, 5_000, 10_000, 20_000, 30_000] as const;

/** How long the store waits before retrying a connection the server explicitly
 * REFUSED (429 stream cap / 503 capacity). Longer than a network retry: the
 * server has told us it has no room, so retrying quickly just burns its
 * admission checks. */
const REFUSED_RETRY_MS = 30_000;

export type RealtimeConnectionStatus =
  /** Nothing is subscribed; no connection is open and none is wanted. */
  | "idle"
  /** A connection is being established, or re-established for the first time. */
  | "connecting"
  /** The server's `hello` arrived on this connection and it is still talking. */
  | "live"
  /** It was working and stopped; the store is retrying. Data on screen is as
   * of `connectedAt` and may now be out of date. */
  | "reconnecting"
  /** Not connected and not usefully retrying soon — the server refused, the
   * session expired, or it reported an error. Data on screen is stale. */
  | "offline";

export interface RealtimeState {
  status: RealtimeConnectionStatus;
  /** Epoch ms of the last frame of ANY kind genuinely received (event or
   * heartbeat). `null` before the first one. */
  lastMessageAt: number | null;
  /** Epoch ms at which the current — or most recent — connection last received
   * its `hello`. This is the honest "data was known-current as of" instant a
   * stale banner should quote. */
  connectedAt: number | null;
  /** The real reason the stream is not live, verbatim from the server when the
   * server gave one. `null` while live or idle — never a placeholder. */
  detail: string | null;
  /** Consecutive failed/ended connections since the last successful `hello`. */
  attempts: number;
}

const IDLE_STATE: RealtimeState = {
  status: "idle",
  lastMessageAt: null,
  connectedAt: null,
  detail: null,
  attempts: 0,
};

type ResourceHandler = (change: ResourceChange) => void;
type StateHandler = (state: RealtimeState) => void;

interface Subscription {
  resources: ReadonlySet<RealtimeResource>;
  handler: ResourceHandler;
}

const KNOWN_RESOURCES: ReadonlySet<string> = new Set(REALTIME_RESOURCES);

// --- module singleton state -------------------------------------------------

let transportFactory: RealtimeTransport | null = null;
let subscriptions = new Set<Subscription>();
let stateHandlers = new Set<StateHandler>();
let state: RealtimeState = IDLE_STATE;

let handle: RealtimeTransportHandle | null = null;
/** Identifies the connection a callback belongs to, so a late callback from a
 * connection we already abandoned cannot resurrect it or move the state. */
let generation = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let watchdogTimer: ReturnType<typeof setInterval> | null = null;
/** The last snapshot the server reported, used for reconnect-gap detection. */
let lastSnapshot: Record<string, ResourceWatermark> | null = null;

function setState(patch: Partial<RealtimeState>): void {
  const next = { ...state, ...patch };
  if (
    next.status === state.status &&
    next.lastMessageAt === state.lastMessageAt &&
    next.connectedAt === state.connectedAt &&
    next.detail === state.detail &&
    next.attempts === state.attempts
  ) {
    return;
  }
  state = next;
  stateHandlers.forEach((handler) => {
    try {
      handler(state);
    } catch {
      // A misbehaving status indicator must not take the channel down with it.
    }
  });
}

export function getRealtimeState(): RealtimeState {
  return state;
}

export function subscribeToRealtimeState(handler: StateHandler): () => void {
  stateHandlers.add(handler);
  return () => {
    stateHandlers.delete(handler);
  };
}

/**
 * Replace the transport. Used by tests to script a stream, and available to
 * the app if the wire ever changes. Passing `null` restores the real one.
 */
export function setRealtimeTransport(transport: RealtimeTransport | null): void {
  transportFactory = transport;
}

/** Tear everything down — for tests, so one file's connection cannot leak into
 * the next. */
export function __resetRealtimeStoreForTests(): void {
  closeConnection();
  subscriptions = new Set();
  stateHandlers = new Set();
  transportFactory = null;
  lastSnapshot = null;
  state = IDLE_STATE;
}

// --- fan-out ---------------------------------------------------------------

function deliver(change: ResourceChange): void {
  subscriptions.forEach((subscription) => {
    if (!subscription.resources.has(change.resource)) return;
    try {
      subscription.handler(change);
    } catch (error) {
      // One screen's refetch handler throwing must not stop the other ten from
      // being told. Reported, never swallowed silently.
      // eslint-disable-next-line no-console
      console.error("[realtime] subscriber threw while handling a change", error);
    }
  });
}

function asWatermarkMap(value: unknown): Record<string, ResourceWatermark> | null {
  if (!value || typeof value !== "object") return null;
  const out: Record<string, ResourceWatermark> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (!raw || typeof raw !== "object") continue;
    const entry = raw as { count?: unknown; watermark?: unknown };
    if (typeof entry.count !== "number") continue;
    out[key] = {
      count: entry.count,
      watermark: typeof entry.watermark === "string" ? entry.watermark : null,
    };
  }
  return out;
}

/** Resources whose server-reported observation genuinely moved between two
 * snapshots. A resource missing from either side is not reported — an absence
 * is not evidence of a change. */
function diffSnapshots(
  previous: Record<string, ResourceWatermark>,
  next: Record<string, ResourceWatermark>,
): ResourceChange[] {
  const changes: ResourceChange[] = [];
  for (const [key, now] of Object.entries(next)) {
    if (!KNOWN_RESOURCES.has(key)) continue;
    const before = previous[key];
    if (!before) continue;
    if (before.count === now.count && before.watermark === now.watermark) continue;
    changes.push({
      resource: key as RealtimeResource,
      count: now.count,
      watermark: now.watermark,
      previousCount: before.count,
      previousWatermark: before.watermark,
      reason: "reconnect_gap",
    });
  }
  return changes;
}

// --- connection lifecycle ---------------------------------------------------

function clearRetry(): void {
  if (retryTimer !== null) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
}

function startWatchdog(): void {
  if (watchdogTimer !== null) return;
  watchdogTimer = setInterval(() => {
    if (state.status !== "live") return;
    const last = state.lastMessageAt;
    if (last === null) return;
    if (Date.now() - last < STALE_AFTER_MS) return;
    // Silence past three heartbeat intervals. Say so and rebuild the
    // connection rather than keep rendering a "Live" badge over ageing data.
    const seconds = Math.round((Date.now() - last) / 1000);
    reconnect({
      kind: "network",
      message: `No heartbeat from the server for ${seconds}s — the live connection appears to have dropped.`,
    });
  }, 5_000);
}

function stopWatchdog(): void {
  if (watchdogTimer !== null) {
    clearInterval(watchdogTimer);
    watchdogTimer = null;
  }
}

function closeConnection(): void {
  clearRetry();
  stopWatchdog();
  generation += 1;
  if (handle) {
    try {
      handle.close();
    } catch {
      // Closing an already-dead connection is not an error worth surfacing.
    }
    handle = null;
  }
}

function retryDelay(): number {
  const index = Math.min(state.attempts, RETRY_DELAYS_MS.length - 1);
  return RETRY_DELAYS_MS[index]!;
}

function scheduleRetry(delayMs: number): void {
  clearRetry();
  if (subscriptions.size === 0) return;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    if (subscriptions.size === 0) return;
    connect();
  }, delayMs);
}

function reconnect(reason: RealtimeCloseReason): void {
  const attempts = state.attempts + 1;
  closeConnection();
  if (subscriptions.size === 0) {
    setState({ ...IDLE_STATE });
    return;
  }
  if (reason.kind === "refused") {
    // The server gave a real reason (cap, capacity, expired session). Show it
    // verbatim; do not dress a refusal up as a transient blip.
    setState({ status: "offline", detail: reason.message, attempts });
    scheduleRetry(REFUSED_RETRY_MS);
    return;
  }
  setState({ status: "reconnecting", detail: reason.message, attempts });
  scheduleRetry(retryDelay());
}

function handleHello(data: unknown): void {
  const payload = (data ?? {}) as { resources?: unknown };
  const snapshot = asWatermarkMap(payload.resources);
  const now = Date.now();
  setState({
    status: "live",
    detail: null,
    attempts: 0,
    connectedAt: now,
    lastMessageAt: now,
  });
  if (!snapshot) return;
  if (lastSnapshot) {
    // Anything that moved while we were disconnected. Replayed as real changes
    // because both snapshots are server observations.
    diffSnapshots(lastSnapshot, snapshot).forEach(deliver);
  }
  lastSnapshot = snapshot;
}

function handleResourceChanged(data: unknown): void {
  const payload = (data ?? {}) as {
    resource?: unknown;
    count?: unknown;
    watermark?: unknown;
    previousCount?: unknown;
    previousWatermark?: unknown;
    reason?: unknown;
  };
  const resource = typeof payload.resource === "string" ? payload.resource : null;
  if (resource === null || !KNOWN_RESOURCES.has(resource)) return;
  const count = typeof payload.count === "number" ? payload.count : 0;
  const watermark = typeof payload.watermark === "string" ? payload.watermark : null;
  const change: ResourceChange = {
    resource: resource as RealtimeResource,
    count,
    watermark,
    previousCount:
      typeof payload.previousCount === "number" ? payload.previousCount : null,
    previousWatermark:
      typeof payload.previousWatermark === "string" ? payload.previousWatermark : null,
    reason: payload.reason === "watermark_advanced" ? "watermark_advanced" : "count_changed",
  };
  if (lastSnapshot) {
    lastSnapshot = { ...lastSnapshot, [resource]: { count, watermark } };
  }
  deliver(change);
}

function connect(): void {
  if (subscriptions.size === 0) return;
  closeConnection();
  const myGeneration = generation;
  // A first connection reports `connecting`. A RETRY keeps whatever the store
  // already told the user (`reconnecting` / `offline`, with the real reason)
  // until the new connection's `hello` proves it is working again — flipping to
  // a neutral "connecting" in between would quietly drop the explanation for
  // why their data may be stale.
  if (state.status === "idle") {
    setState({ status: "connecting", detail: null });
  }
  startWatchdog();

  const factory = transportFactory ?? openWorkspaceStream;
  handle = factory({
    onOpen: () => {
      if (myGeneration !== generation) return;
      // Deliberately does NOT set `live`: an HTTP 200 with a body we have not
      // read a single frame from is not proof the stream works.
    },
    onComment: () => {
      if (myGeneration !== generation) return;
      setState({ lastMessageAt: Date.now() });
    },
    onEvent: (event, data) => {
      if (myGeneration !== generation) return;
      setState({ lastMessageAt: Date.now() });
      switch (event) {
        case "hello":
          handleHello(data);
          break;
        case "resource_changed":
          handleResourceChanged(data);
          break;
        case "stream_timeout": {
          // The server's bounded lifetime elapsed. Expected and healthy — but
          // until the replacement connection says hello, this tab is NOT live.
          const message =
            typeof (data as { message?: unknown })?.message === "string"
              ? ((data as { message: string }).message)
              : "The live connection reached its time limit and is being renewed.";
          reconnect({ kind: "ended", message });
          break;
        }
        case "stream_error": {
          const payload = (data ?? {}) as { message?: unknown; detail?: unknown };
          const message =
            typeof payload.message === "string"
              ? payload.message
              : "The server could not read your workspace state.";
          const detail = typeof payload.detail === "string" ? ` (${payload.detail})` : "";
          reconnect({ kind: "refused", message: `${message}${detail}` });
          break;
        }
        default:
          // Unknown event names are ignored rather than guessed at.
          break;
      }
    },
    onClose: (reason) => {
      if (myGeneration !== generation) return;
      reconnect(reason);
    },
  });
}

// --- public subscription API ------------------------------------------------

/**
 * Subscribe a screen to one or more resources.
 *
 * The handler is called once per genuine change to a subscribed resource. It
 * should refetch through the ordinary API client; it is never handed domain
 * data by this channel.
 *
 * Returns an unsubscribe function. The connection is opened on the first
 * subscription and closed when the last one goes away.
 */
export function subscribeToResources(
  resources: readonly RealtimeResource[],
  handler: ResourceHandler,
): () => void {
  const subscription: Subscription = {
    resources: new Set(resources),
    handler,
  };
  subscriptions.add(subscription);
  if (subscriptions.size === 1) {
    setState({ status: "connecting", detail: null, attempts: 0 });
    connect();
  }
  return () => {
    subscriptions.delete(subscription);
    if (subscriptions.size === 0) {
      closeConnection();
      setState({ ...IDLE_STATE });
    }
  };
}
