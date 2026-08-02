/**
 * W-RT — the client half of the one shared realtime channel.
 *
 * BEFORE THIS FILE: `grep -rn "EventSource" apps/web/src` returned ZERO
 * matches. No screen consumed any stream; jobs/applications/stories polled on
 * their own `setInterval`, and resume, cover-letters, email, networking,
 * analytics and interviews never refreshed at all after their mount-time
 * fetch. An agent writing a résumé or a letter was invisible until the user
 * reloaded the page by hand.
 *
 * These tests pin the store that fixes that. Three properties matter and each
 * has a test that fails loudly if it regresses:
 *
 *  1. ONE CONNECTION. Eleven screens subscribing must open exactly one
 *     transport, because the server admits only 3 streams per user and 8
 *     globally (`app/services/agent_run_stream.py` StreamSlots) against a
 *     25-connection Postgres ceiling. A connection per screen would refuse
 *     most screens outright.
 *  2. TARGETED FAN-OUT. A `jobs` change must not wake the applications screen
 *     into a needless refetch, and must wake every jobs subscriber.
 *  3. HONEST DEGRADATION. When the stream drops, stalls, or is refused, the
 *     store's state must say so — never keep reporting `live` while the data
 *     on screen quietly ages.
 *
 * The transport is injected, so these tests exercise the real store logic with
 * a scripted stream instead of a real network.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  __resetRealtimeStoreForTests,
  getRealtimeState,
  setRealtimeTransport,
  subscribeToRealtimeState,
  subscribeToResources,
  STALE_AFTER_MS,
} from "../store";
import type {
  RealtimeTransport,
  RealtimeTransportCallbacks,
  RealtimeTransportHandle,
} from "../transport-types";

interface ScriptedTransport {
  transport: RealtimeTransport;
  /** One entry per time the store opened a connection. */
  opens: RealtimeTransportCallbacks[];
  closedCount: () => number;
  latest: () => RealtimeTransportCallbacks;
}

function scriptedTransport(): ScriptedTransport {
  const opens: RealtimeTransportCallbacks[] = [];
  let closed = 0;
  const transport: RealtimeTransport = (callbacks): RealtimeTransportHandle => {
    opens.push(callbacks);
    return {
      close: () => {
        closed += 1;
      },
    };
  };
  return {
    transport,
    opens,
    closedCount: () => closed,
    latest: () => opens[opens.length - 1]!,
  };
}

const HELLO = {
  channel: "workspace:u1",
  source: "persisted_row_watermarks",
  pollSeconds: 3,
  resources: {
    jobs: { count: 2, watermark: "w-jobs-1" },
    applications: { count: 1, watermark: "w-apps-1" },
  },
};

function change(resource: string, overrides: Record<string, unknown> = {}) {
  return {
    channel: "workspace:u1",
    source: "persisted_row_watermarks",
    resource,
    count: 3,
    watermark: `${resource}-w2`,
    previousCount: 2,
    previousWatermark: `${resource}-w1`,
    reason: "count_changed",
    ...overrides,
  };
}

let scripted: ScriptedTransport;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-02T00:00:00Z"));
  scripted = scriptedTransport();
  __resetRealtimeStoreForTests();
  setRealtimeTransport(scripted.transport);
});

afterEach(() => {
  __resetRealtimeStoreForTests();
  vi.useRealTimers();
});

describe("one connection, fanned out client-side", () => {
  it("opens exactly one transport no matter how many screens subscribe", () => {
    const unsubs = [
      subscribeToResources(["jobs"], vi.fn()),
      subscribeToResources(["applications"], vi.fn()),
      subscribeToResources(["resumes", "coverLetters"], vi.fn()),
      subscribeToResources(["stories"], vi.fn()),
      subscribeToResources(["emails"], vi.fn()),
    ];
    expect(scripted.opens).toHaveLength(1);
    unsubs.forEach((u) => u());
  });

  it("keeps the connection open until the LAST subscriber leaves", () => {
    const a = subscribeToResources(["jobs"], vi.fn());
    const b = subscribeToResources(["applications"], vi.fn());
    a();
    expect(scripted.closedCount()).toBe(0);
    b();
    expect(scripted.closedCount()).toBe(1);
    expect(getRealtimeState().status).toBe("idle");
  });

  it("does not open a connection when nothing is subscribed", () => {
    expect(scripted.opens).toHaveLength(0);
    expect(getRealtimeState().status).toBe("idle");
  });
});

describe("targeted fan-out", () => {
  it("delivers a change only to subscribers of that resource", () => {
    const onJobs = vi.fn();
    const onApps = vi.fn();
    const un1 = subscribeToResources(["jobs"], onJobs);
    const un2 = subscribeToResources(["applications"], onApps);

    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onEvent("resource_changed", change("jobs"));

    expect(onJobs).toHaveBeenCalledTimes(1);
    expect(onJobs.mock.calls[0][0]).toMatchObject({ resource: "jobs", count: 3 });
    expect(onApps).not.toHaveBeenCalled();
    un1();
    un2();
  });

  it("delivers to EVERY subscriber of a resource, and to multi-resource subscribers once per change", () => {
    const first = vi.fn();
    const second = vi.fn();
    const both = vi.fn();
    const un = [
      subscribeToResources(["jobs"], first),
      subscribeToResources(["jobs"], second),
      subscribeToResources(["jobs", "applications"], both),
    ];

    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onEvent("resource_changed", change("jobs"));
    scripted.latest().onEvent("resource_changed", change("applications"));

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
    expect(both).toHaveBeenCalledTimes(2);
    un.forEach((u) => u());
  });

  it("a throwing subscriber cannot starve the others", () => {
    const boom = vi.fn(() => {
      throw new Error("render crashed");
    });
    const ok = vi.fn();
    const un = [
      subscribeToResources(["jobs"], boom),
      subscribeToResources(["jobs"], ok),
    ];
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    expect(() => scripted.latest().onEvent("resource_changed", change("jobs"))).not.toThrow();
    expect(ok).toHaveBeenCalledTimes(1);
    un.forEach((u) => u());
  });

  it("ignores a change for a resource nobody subscribed to", () => {
    const onJobs = vi.fn();
    const un = subscribeToResources(["jobs"], onJobs);
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onEvent("resource_changed", change("offers"));
    expect(onJobs).not.toHaveBeenCalled();
    un();
  });
});

describe("honest connection state", () => {
  it("is 'connecting' until the server's hello actually arrives", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    expect(getRealtimeState().status).toBe("connecting");
    scripted.latest().onOpen();
    // A transport-level open is NOT proof the stream works end to end; only
    // the server's own hello frame is.
    expect(getRealtimeState().status).toBe("connecting");
    scripted.latest().onEvent("hello", HELLO);
    expect(getRealtimeState().status).toBe("live");
    expect(getRealtimeState().detail).toBeNull();
    un();
  });

  it("reports 'reconnecting' with a real reason when the stream drops", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onClose({ kind: "network", message: "Failed to fetch" });

    const state = getRealtimeState();
    expect(state.status).toBe("reconnecting");
    expect(state.detail).toContain("Failed to fetch");
    // The last moment the data on screen was known-current must be preserved,
    // so the UI can say WHEN it went stale rather than pretend it is current.
    expect(state.connectedAt).not.toBeNull();
    un();
  });

  it("reconnects after a drop and returns to 'live'", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onClose({ kind: "network", message: "Failed to fetch" });

    expect(scripted.opens).toHaveLength(1);
    vi.advanceTimersByTime(60_000);
    expect(scripted.opens.length).toBeGreaterThan(1);

    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    expect(getRealtimeState().status).toBe("live");
    un();
  });

  it("backs off instead of hot-looping when reconnection keeps failing", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onClose({ kind: "network", message: "Failed to fetch" });
    const attemptsAfter = (ms: number) => {
      vi.advanceTimersByTime(ms);
      return scripted.opens.length;
    };
    // Ten seconds of retries must not produce anything like ten-per-second.
    let opens = attemptsAfter(1_000);
    for (let i = 0; i < 9; i += 1) {
      scripted.latest().onClose({ kind: "network", message: "Failed to fetch" });
      opens = attemptsAfter(1_000);
    }
    expect(opens).toBeLessThan(12);
    expect(getRealtimeState().attempts).toBeGreaterThan(0);
    un();
  });

  it("surfaces a server refusal verbatim and stops claiming to be live", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onClose({
      kind: "refused",
      status: 429,
      message: "Too many live agent-run streams open for this account (3 at a time).",
    });
    const state = getRealtimeState();
    expect(state.status).toBe("offline");
    expect(state.detail).toContain("Too many live agent-run streams");
    un();
  });

  it("treats the server's own stream_error as offline, carrying its message", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onEvent("stream_error", {
      channel: "workspace:u1",
      message: "Could not read your workspace state; stream closed.",
      detail: "OperationalError: connection refused",
    });
    const state = getRealtimeState();
    expect(state.status).toBe("offline");
    expect(state.detail).toContain("Could not read your workspace state");
    un();
  });

  it("treats the server's bounded-lifetime stream_timeout as a reconnect, not a failure", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onEvent("stream_timeout", {
      channel: "workspace:u1",
      message: "Stream reached its bounded lifetime. Reconnect to keep receiving live updates.",
    });
    expect(getRealtimeState().status).toBe("reconnecting");
    vi.advanceTimersByTime(60_000);
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    expect(getRealtimeState().status).toBe("live");
    un();
  });

  it("stops claiming 'live' when the server goes silent past the heartbeat window", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    expect(getRealtimeState().status).toBe("live");

    // The server heartbeats every 15s; silence well past that means the socket
    // is dead even though no error was ever delivered. Reporting "live" here
    // is exactly the silent-stale-data failure this channel must not have.
    vi.advanceTimersByTime(STALE_AFTER_MS + 1_000);
    const state = getRealtimeState();
    expect(state.status).not.toBe("live");
    expect(state.detail).toMatch(/heartbeat|silent|stale/i);
    un();
  });

  it("counts a heartbeat comment as proof of life", () => {
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);

    vi.advanceTimersByTime(STALE_AFTER_MS - 2_000);
    scripted.latest().onComment("heartbeat 1785000000");
    vi.advanceTimersByTime(STALE_AFTER_MS - 2_000);

    expect(getRealtimeState().status).toBe("live");
    un();
  });

  it("notifies state subscribers on every transition", () => {
    const seen: string[] = [];
    const unState = subscribeToRealtimeState((s) => seen.push(s.status));
    const un = subscribeToResources(["jobs"], vi.fn());
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onClose({ kind: "network", message: "gone" });
    expect(seen).toContain("connecting");
    expect(seen).toContain("live");
    expect(seen).toContain("reconnecting");
    un();
    unState();
  });
});

describe("gap recovery across a reconnect", () => {
  it("replays exactly the resources whose snapshot really moved while disconnected", () => {
    const onJobs = vi.fn();
    const onApps = vi.fn();
    const un = [
      subscribeToResources(["jobs"], onJobs),
      subscribeToResources(["applications"], onApps),
    ];

    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    scripted.latest().onClose({ kind: "network", message: "gone" });
    vi.advanceTimersByTime(60_000);

    // Jobs moved while we were disconnected; applications did not. Replaying
    // applications too would tell that screen its data is stale when the
    // server says it is not.
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", {
      ...HELLO,
      resources: {
        jobs: { count: 9, watermark: "w-jobs-2" },
        applications: { count: 1, watermark: "w-apps-1" },
      },
    });

    expect(onJobs).toHaveBeenCalledTimes(1);
    expect(onJobs.mock.calls[0][0]).toMatchObject({
      resource: "jobs",
      count: 9,
      previousCount: 2,
      reason: "reconnect_gap",
    });
    expect(onApps).not.toHaveBeenCalled();
    un.forEach((u) => u());
  });

  it("does not replay anything on the FIRST hello — that is a snapshot, not a change", () => {
    const onJobs = vi.fn();
    const un = subscribeToResources(["jobs"], onJobs);
    scripted.latest().onOpen();
    scripted.latest().onEvent("hello", HELLO);
    expect(onJobs).not.toHaveBeenCalled();
    un();
  });
});
