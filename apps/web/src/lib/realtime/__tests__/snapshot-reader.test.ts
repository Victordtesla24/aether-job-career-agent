/**
 * S-UI-REBUILD §1.4 / §3 — the read-only snapshot selector.
 *
 * The whole telemetry layer of this rebuild rests on ONE claim: every new
 * surface is a *reader* over the single existing connection, never a new
 * one. The server admits 3 streams per user and 8 globally, so a reader that
 * quietly opened a connection would be a capacity bug (risk R-6) as well as
 * a behavioural-parity violation. Test 1 pins that.
 *
 * The rest pin the §3.2 mapping law at the source: what the store records is
 * exactly what the server said, with no back-filled history and no
 * substituted zeroes.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  __resetRealtimeStoreForTests,
  getRealtimeSnapshot,
  setRealtimeTransport,
  subscribeToRealtimeSnapshot,
  subscribeToResources,
} from "../store";
import type {
  RealtimeTransport,
  RealtimeTransportCallbacks,
  RealtimeTransportHandle,
} from "../transport-types";

function scriptedTransport() {
  const opens: RealtimeTransportCallbacks[] = [];
  const transport: RealtimeTransport = (callbacks): RealtimeTransportHandle => {
    opens.push(callbacks);
    return { close: () => undefined };
  };
  return { transport, opens, latest: () => opens[opens.length - 1]! };
}

let script = scriptedTransport();

beforeEach(() => {
  __resetRealtimeStoreForTests();
  script = scriptedTransport();
  setRealtimeTransport(script.transport);
});

afterEach(() => {
  __resetRealtimeStoreForTests();
});

describe("realtime snapshot reader (S-UI-REBUILD §1.4)", () => {
  it("opens NO connection — subscribing to the snapshot is a listener, nothing more", () => {
    const stop = subscribeToRealtimeSnapshot(() => undefined);
    expect(script.opens).toHaveLength(0);
    expect(getRealtimeSnapshot().resources).toEqual([]);
    expect(getRealtimeSnapshot().seededAt).toBeNull();
    stop();
  });

  it("seeds from `hello` with NO delta — a first observation is not a change", () => {
    subscribeToResources(["jobs"], () => undefined);
    script.latest().onEvent("hello", {
      resources: { jobs: { count: 8358, watermark: "2026-08-14T03:41:00Z" } },
    });

    const [jobs] = getRealtimeSnapshot().resources;
    expect(jobs?.resource).toBe("jobs");
    expect(jobs?.count).toBe(8358);
    // The honest value is "unknown", never 0 — a 0 here would render as
    // "8,358 new" on connect.
    expect(jobs?.previousCount).toBeNull();
    expect(jobs?.reason).toBeNull();
  });

  it("records a real count delta with the server's own previous count", () => {
    subscribeToResources(["jobs"], () => undefined);
    script.latest().onEvent("hello", { resources: { jobs: { count: 10, watermark: null } } });
    script.latest().onEvent("resource_changed", {
      resource: "jobs",
      count: 22,
      watermark: "2026-08-14T03:44:00Z",
      previousCount: 10,
      previousWatermark: null,
      reason: "count_changed",
    });

    const [jobs] = getRealtimeSnapshot().resources;
    expect(jobs?.count).toBe(22);
    expect(jobs?.previousCount).toBe(10);
    expect(jobs?.reason).toBe("count_changed");
  });

  it("keeps counts EQUAL for a watermark_advanced — the UI may not render a number", () => {
    subscribeToResources(["applications"], () => undefined);
    script.latest().onEvent("hello", {
      resources: { applications: { count: 540, watermark: "2026-08-14T03:12:00Z" } },
    });
    script.latest().onEvent("resource_changed", {
      resource: "applications",
      count: 540,
      watermark: "2026-08-14T03:50:00Z",
      previousCount: 540,
      previousWatermark: "2026-08-14T03:12:00Z",
      reason: "watermark_advanced",
    });

    const [applications] = getRealtimeSnapshot().resources;
    expect(applications?.count).toBe(540);
    expect(applications?.previousCount).toBe(540);
    expect(applications?.reason).toBe("watermark_advanced");
  });

  it("marks what moved across a reconnect as `reconnect_gap`, and leaves untouched rows alone", () => {
    subscribeToResources(["jobs", "applications"], () => undefined);
    script.latest().onEvent("hello", {
      resources: {
        jobs: { count: 10, watermark: "w1" },
        applications: { count: 5, watermark: "w2" },
      },
    });
    const seededApplications = getRealtimeSnapshot().resources.find(
      (row) => row.resource === "applications",
    );

    // A second `hello` on a fresh connection: jobs moved, applications did not.
    script.latest().onEvent("hello", {
      resources: {
        jobs: { count: 14, watermark: "w3" },
        applications: { count: 5, watermark: "w2" },
      },
    });

    const snapshot = getRealtimeSnapshot();
    const jobs = snapshot.resources.find((row) => row.resource === "jobs");
    const applications = snapshot.resources.find((row) => row.resource === "applications");
    expect(jobs?.reason).toBe("reconnect_gap");
    expect(jobs?.previousCount).toBe(10);
    expect(jobs?.count).toBe(14);
    // Unchanged resource keeps its original observation rather than being
    // overwritten with a fake "changed to the same value" event.
    expect(applications).toEqual(seededApplications);
  });

  it("notifies snapshot readers and hands back a stable reference between updates", () => {
    const seen: number[] = [];
    subscribeToRealtimeSnapshot((snapshot) => seen.push(snapshot.resources.length));
    subscribeToResources(["jobs"], () => undefined);
    script.latest().onEvent("hello", { resources: { jobs: { count: 1, watermark: null } } });

    expect(seen).toEqual([1]);
    expect(getRealtimeSnapshot()).toBe(getRealtimeSnapshot());
  });

  it("ignores resource keys the client does not know", () => {
    subscribeToResources(["jobs"], () => undefined);
    script.latest().onEvent("hello", {
      resources: { jobs: { count: 1, watermark: null }, unicorns: { count: 99, watermark: null } },
    });
    expect(getRealtimeSnapshot().resources.map((row) => row.resource)).toEqual(["jobs"]);
  });
});
