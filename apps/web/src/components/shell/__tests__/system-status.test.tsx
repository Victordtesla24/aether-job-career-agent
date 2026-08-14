// @vitest-environment jsdom
/**
 * S-UI-REBUILD §1.4 + the §3.2 MAPPING LAW.
 *
 * Law T-1: nothing in the telemetry layer may render a fact the wire does not
 * carry. The two ways this popover could break that law are:
 *
 *   1. rendering a count as "new" when the counts did not actually rise — a
 *      `watermark_advanced` frame means "something touched these rows", not
 *      "N were added", and the `coverLetters` superset makes that distinction
 *      load-bearing rather than pedantic;
 *   2. animating while the channel is NOT live — a pulsing dot over a dead
 *      socket is the exact "quietly stale under a Live badge" failure the
 *      whole realtime store exists to prevent.
 *
 * Both are asserted here, plus the third honesty rule: a connect-time
 * observation has no delta and must render none.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// eslint-disable-next-line import/first
import { SystemStatus, describeDelta } from "../SystemStatus";
// eslint-disable-next-line import/first
import {
  __resetRealtimeStoreForTests,
  setRealtimeTransport,
  subscribeToResources,
} from "../../../lib/realtime/store";
// eslint-disable-next-line import/first
import type {
  RealtimeTransport,
  RealtimeTransportCallbacks,
} from "../../../lib/realtime/transport-types";

function observation(overrides: Partial<Parameters<typeof describeDelta>[0]> = {}) {
  return {
    resource: "jobs" as const,
    count: 10,
    watermark: null,
    previousCount: null,
    previousWatermark: null,
    reason: null,
    observedAt: Date.now(),
    ...overrides,
  };
}

let opens: RealtimeTransportCallbacks[] = [];

function openChannel(): RealtimeTransportCallbacks {
  opens = [];
  const transport: RealtimeTransport = (callbacks) => {
    opens.push(callbacks);
    return { close: () => undefined };
  };
  setRealtimeTransport(transport);
  subscribeToResources(["jobs", "applications"], () => undefined);
  return opens[0]!;
}

beforeEach(() => {
  __resetRealtimeStoreForTests();
});

afterEach(() => {
  cleanup();
  __resetRealtimeStoreForTests();
  vi.clearAllMocks();
});

describe("§3.2 mapping law — describeDelta", () => {
  it("states an exact rise as 'new'", () => {
    expect(describeDelta(observation({ count: 22, previousCount: 10, reason: "count_changed" }))).toEqual(
      { glyph: "↑12", word: "new", tone: "ok" },
    );
  });

  it("never calls a fall 'new', and never tones it as a healthy rise", () => {
    const result = describeDelta(
      observation({ count: 7, previousCount: 10, reason: "count_changed" }),
    );
    expect(result.glyph).toBe("↓3");
    expect(result.word).toBe("removed");
    expect(result.tone).not.toBe("ok");
  });

  it("renders NO NUMBER for a watermark_advanced with equal counts — 'updated', never 'N new'", () => {
    expect(
      describeDelta(observation({ count: 540, previousCount: 540, reason: "watermark_advanced" })),
    ).toEqual({ glyph: "·", word: "updated", tone: "neutral" });
  });

  it("says nothing at all about a connect-time observation — a first sighting is not a change", () => {
    expect(describeDelta(observation({ count: 8358, previousCount: null }))).toEqual({
      glyph: "·",
      word: "",
      tone: "neutral",
    });
  });
});

describe("SystemStatus popover", () => {
  it("renders nothing at all when nothing on the page subscribes (hideWhenIdle parity)", () => {
    const { container } = render(<SystemStatus />);
    expect(container.textContent).toBe("");
  });

  it("shows the server's own row observations, with counts and no invented deltas", async () => {
    const channel = openChannel();
    render(<SystemStatus />);
    channel.onEvent("hello", {
      resources: {
        jobs: { count: 8358, watermark: "2026-08-14T03:41:00Z" },
        applications: { count: 540, watermark: "2026-08-14T03:12:00Z" },
      },
    });

    fireEvent.click(await screen.findByTestId("system-status-trigger"));
    const jobs = await screen.findByTestId("system-status-row-jobs");
    expect(jobs.textContent).toContain("8358");
    expect(jobs.getAttribute("data-delta")).toBe("·");

    channel.onEvent("resource_changed", {
      resource: "jobs",
      count: 8370,
      watermark: "2026-08-14T03:44:00Z",
      previousCount: 8358,
      previousWatermark: "2026-08-14T03:41:00Z",
      reason: "count_changed",
    });
    await waitFor(() =>
      expect(screen.getByTestId("system-status-row-jobs").getAttribute("data-delta")).toBe("↑12"),
    );
  });

  it("carries the honesty footnote about what the channel does and does not know", async () => {
    const channel = openChannel();
    render(<SystemStatus />);
    channel.onEvent("hello", { resources: { jobs: { count: 1, watermark: null } } });

    fireEvent.click(await screen.findByTestId("system-status-trigger"));
    const popover = await screen.findByTestId("system-status-popover");
    expect(popover.textContent).toMatch(/carries no\s+record contents|carries no record contents/);
    expect(popover.textContent).toMatch(/server.s own row\s*observations/i);
  });

  it("PULSES only while live, and goes STATIC the moment the channel is not", async () => {
    const channel = openChannel();
    render(<SystemStatus />);
    channel.onEvent("hello", { resources: { jobs: { count: 1, watermark: null } } });

    await waitFor(() =>
      expect(screen.getByTestId("realtime-status-dot").getAttribute("data-motion")).toBe("pulse"),
    );

    // The server explains a refusal: the store goes offline with a real
    // reason. Nothing may keep animating as if it were still working.
    channel.onEvent("stream_error", {
      message: "Too many live agent-run streams.",
      detail: "cap reached",
    });
    await waitFor(() =>
      expect(screen.getByTestId("realtime-status-dot").getAttribute("data-motion")).toBe("static"),
    );
  });

  it("shows the server's refusal verbatim rather than a paraphrase", async () => {
    const channel = openChannel();
    render(<SystemStatus />);
    channel.onEvent("hello", { resources: { jobs: { count: 1, watermark: null } } });
    channel.onEvent("stream_error", {
      message: "Too many live agent-run streams.",
      detail: "cap reached",
    });

    fireEvent.click(await screen.findByTestId("system-status-trigger"));
    const detail = await screen.findByTestId("system-status-detail");
    expect(detail.textContent).toContain("Too many live agent-run streams.");
    expect(detail.textContent).toContain("cap reached");
  });
});
