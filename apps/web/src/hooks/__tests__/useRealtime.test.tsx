// @vitest-environment jsdom
/**
 * W-RT — the React seam onto the shared realtime channel.
 *
 * The store (`lib/realtime/store.ts`) owns the single connection; these hooks
 * are how a screen joins it. What has to hold, and is pinned below:
 *
 *  - Mounting N screens still opens ONE connection (the store's ref-count is
 *    respected: the hook must not resubscribe on every render).
 *  - A screen's refetch callback can change between renders (it usually closes
 *    over filter state) WITHOUT tearing the subscription down and back up —
 *    otherwise a screen with a changing callback would churn the shared
 *    connection.
 *  - Unmounting a screen unsubscribes it, so no refetch fires into a dead
 *    component.
 *  - `useRealtimeStatus` re-renders on transitions, because a stale/reconnecting
 *    banner that does not update is worse than none.
 */
import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  __resetRealtimeStoreForTests,
  setRealtimeTransport,
} from "../../lib/realtime/store";
import type {
  RealtimeTransport,
  RealtimeTransportCallbacks,
} from "../../lib/realtime/transport-types";
import { useRealtimeResources, useRealtimeStatus } from "../useRealtime";
import { RealtimeStatusBadge } from "../../components/realtime/RealtimeStatusBadge";

let opens: RealtimeTransportCallbacks[] = [];

const transport: RealtimeTransport = (callbacks) => {
  opens.push(callbacks);
  return { close: () => undefined };
};

const HELLO = {
  channel: "workspace:u1",
  source: "persisted_row_watermarks",
  resources: { jobs: { count: 1, watermark: "a" } },
};

function emit(event: string, data: unknown): void {
  act(() => {
    opens[opens.length - 1]!.onEvent(event, data);
  });
}

beforeEach(() => {
  opens = [];
  __resetRealtimeStoreForTests();
  setRealtimeTransport(transport);
});

afterEach(() => {
  __resetRealtimeStoreForTests();
});

describe("useRealtimeResources", () => {
  it("subscribes once and refetches when its resource really changes", () => {
    const refetch = vi.fn();
    renderHook(() => useRealtimeResources(["jobs"], refetch));
    expect(opens).toHaveLength(1);

    emit("hello", HELLO);
    expect(refetch).not.toHaveBeenCalled();

    emit("resource_changed", {
      resource: "jobs",
      count: 2,
      watermark: "b",
      previousCount: 1,
      previousWatermark: "a",
      reason: "count_changed",
    });
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(refetch.mock.calls[0][0]).toMatchObject({ resource: "jobs" });
  });

  it("collapses one poll's burst of changes into a single refetch", () => {
    // A pipeline run writes Job, Application and AgentRun rows at once, so a
    // single server poll emits three `resource_changed` frames back to back. A
    // screen subscribed to all three would otherwise fire three identical full
    // reloads in the same tick — the Analytics screen is four API calls each.
    // One refetch already reflects all three writes.
    const refetch = vi.fn();
    renderHook(() => useRealtimeResources(["jobs", "applications", "agentRuns"], refetch));
    act(() => {
      const cb = opens[opens.length - 1]!;
      cb.onEvent("hello", HELLO);
      cb.onEvent("resource_changed", { resource: "jobs", count: 2, watermark: "b", reason: "count_changed" });
      cb.onEvent("resource_changed", { resource: "applications", count: 2, watermark: "b", reason: "count_changed" });
      cb.onEvent("resource_changed", { resource: "agentRuns", count: 2, watermark: "b", reason: "count_changed" });
    });
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("does not collapse changes that arrive in separate polls", async () => {
    const refetch = vi.fn();
    renderHook(() => useRealtimeResources(["jobs"], refetch));
    emit("hello", HELLO);
    emit("resource_changed", { resource: "jobs", count: 2, watermark: "b", reason: "count_changed" });
    await act(async () => {
      await Promise.resolve();
    });
    emit("resource_changed", { resource: "jobs", count: 3, watermark: "c", reason: "count_changed" });
    expect(refetch).toHaveBeenCalledTimes(2);
  });

  it("does not fire for a resource it did not subscribe to", () => {
    const refetch = vi.fn();
    renderHook(() => useRealtimeResources(["resumes"], refetch));
    emit("hello", HELLO);
    emit("resource_changed", { resource: "jobs", count: 2, watermark: "b", reason: "count_changed" });
    expect(refetch).not.toHaveBeenCalled();
  });

  it("does not churn the shared connection when the callback identity changes", () => {
    const { rerender } = renderHook(
      ({ cb }: { cb: () => void }) => useRealtimeResources(["jobs"], cb),
      { initialProps: { cb: () => undefined } },
    );
    rerender({ cb: () => undefined });
    rerender({ cb: () => undefined });
    // One connection, and no resubscribe storm behind it.
    expect(opens).toHaveLength(1);
  });

  it("uses the LATEST callback, not the one captured at subscribe time", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(
      ({ cb }: { cb: () => void }) => useRealtimeResources(["jobs"], cb),
      { initialProps: { cb: first } },
    );
    rerender({ cb: second });
    emit("hello", HELLO);
    emit("resource_changed", { resource: "jobs", count: 2, watermark: "b", reason: "count_changed" });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("stops refetching after unmount", () => {
    const refetch = vi.fn();
    const { unmount } = renderHook(() => useRealtimeResources(["jobs"], refetch));
    emit("hello", HELLO);
    unmount();
    // The connection is gone with the last subscriber; pushing another frame
    // through the abandoned callbacks must not reach the unmounted screen.
    act(() => {
      opens[0]!.onEvent("resource_changed", {
        resource: "jobs",
        count: 5,
        watermark: "c",
        reason: "count_changed",
      });
    });
    expect(refetch).not.toHaveBeenCalled();
  });

  it("two screens share one connection", () => {
    const a = vi.fn();
    const b = vi.fn();
    renderHook(() => useRealtimeResources(["jobs"], a));
    renderHook(() => useRealtimeResources(["applications"], b));
    expect(opens).toHaveLength(1);
  });

  it("can be disabled, so a screen with nothing loaded does not hold the channel open", () => {
    const refetch = vi.fn();
    renderHook(() => useRealtimeResources(["jobs"], refetch, { enabled: false }));
    expect(opens).toHaveLength(0);
  });
});

describe("useRealtimeStatus / RealtimeStatusBadge — truthful degradation", () => {
  it("re-renders the consumer on every transition", () => {
    const { result } = renderHook(() => {
      const status = useRealtimeStatus();
      useRealtimeResources(["jobs"], vi.fn());
      return status;
    });
    expect(result.current.status).toBe("connecting");
    emit("hello", HELLO);
    expect(result.current.status).toBe("live");
    act(() => {
      opens[opens.length - 1]!.onClose({ kind: "network", message: "Failed to fetch" });
    });
    expect(result.current.status).toBe("reconnecting");
  });

  function Harness() {
    useRealtimeResources(["jobs"], vi.fn());
    return <RealtimeStatusBadge />;
  }

  it("says 'Live' only once the server's hello has arrived", () => {
    render(<Harness />);
    expect(screen.getByTestId("realtime-status").textContent ?? "").toMatch(/connecting/i);
    emit("hello", HELLO);
    expect(screen.getByTestId("realtime-status").textContent ?? "").toMatch(/live/i);
  });

  it("tells the user the data may be stale when the stream drops — never silently keeps 'Live'", () => {
    render(<Harness />);
    emit("hello", HELLO);
    act(() => {
      opens[opens.length - 1]!.onClose({ kind: "network", message: "Failed to fetch" });
    });
    const badge = screen.getByTestId("realtime-status");
    expect((badge.textContent ?? "").trim()).not.toMatch(/^live$/i);
    expect(badge.textContent ?? "").toMatch(/reconnect/i);
    expect(badge.getAttribute("title") ?? "").toContain("Failed to fetch");
  });

  it("shows the server's own refusal reason verbatim", () => {
    render(<Harness />);
    act(() => {
      opens[opens.length - 1]!.onClose({
        kind: "refused",
        status: 429,
        message: "Too many live agent-run streams open for this account (3 at a time).",
      });
    });
    const badge = screen.getByTestId("realtime-status");
    expect(badge.textContent ?? "").toMatch(/offline|unavailable/i);
    expect(badge.getAttribute("title") ?? "").toContain("Too many live agent-run streams");
  });
});
