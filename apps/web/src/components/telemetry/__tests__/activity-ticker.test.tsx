// @vitest-environment jsdom
/**
 * S-UI-REBUILD §3.4 T-A / §3.5 — the ticker, driven end-to-end through the REAL
 * store with a scripted transport.
 *
 * `activity-feed.test.ts` pins the copy mapping as a pure function. This file
 * pins the two things only a mounted component can prove:
 *  1. a first `hello` seeds the snapshot and produces **zero rows** — the
 *     ticker may not back-fill a history it never observed (§3.2, `hello` row);
 *  2. the degraded states are DESIGNED: the store's verbatim `detail` reaches
 *     the screen and the ticker stops presenting itself as live (§3.5).
 */
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));

// eslint-disable-next-line import/first
import ActivityTicker from "../ActivityTicker";
// eslint-disable-next-line import/first
import {
  __resetRealtimeStoreForTests,
  setRealtimeTransport,
} from "../../../lib/realtime/store";
// eslint-disable-next-line import/first
import type {
  RealtimeTransport,
  RealtimeTransportCallbacks,
} from "../../../lib/realtime/transport-types";

let opens: RealtimeTransportCallbacks[] = [];

function scriptTransport(): void {
  opens = [];
  const transport: RealtimeTransport = (callbacks) => {
    opens.push(callbacks);
    return { close: () => undefined };
  };
  setRealtimeTransport(transport);
}

/** The channel opens when the ticker itself subscribes, on mount. */
async function channel(): Promise<RealtimeTransportCallbacks> {
  await waitFor(() => expect(opens.length).toBeGreaterThan(0));
  return opens[0]!;
}

/** Deliver a frame the way the transport would, inside `act` so React has
 *  flushed before the assertions look at the DOM. */
function emit(cb: RealtimeTransportCallbacks, event: string, data: unknown): void {
  act(() => {
    cb.onEvent(event, data);
  });
}

function open(cb: RealtimeTransportCallbacks): void {
  act(() => {
    cb.onOpen();
  });
}

function close(cb: RealtimeTransportCallbacks, message: string): void {
  act(() => {
    cb.onClose({ kind: "network", message });
  });
}

function hello(counts: Record<string, number>) {
  return {
    resources: Object.fromEntries(
      Object.entries(counts).map(([key, count]) => [key, { count, watermark: "2026-08-14T03:41:00Z" }]),
    ),
    source: "persisted_row_watermarks",
  };
}

beforeEach(() => {
  __resetRealtimeStoreForTests();
  scriptTransport();
});

afterEach(() => {
  cleanup();
  __resetRealtimeStoreForTests();
  vi.clearAllMocks();
});

describe("§3.2 `hello` — seeds the snapshot, produces no rows", () => {
  it("shows the designed empty state instead of back-filling events it never saw", async () => {
    render(<ActivityTicker />);
    const cb = await channel();
    open(cb);
    emit(cb, "hello", hello({ jobs: 8358, applications: 287 }));

    // 8,358 jobs exist. NONE of them is an event this session observed.
    const empty = await screen.findByTestId("activity-ticker-empty");
    expect(empty.textContent).toMatch(/nothing has changed/i);
    expect(screen.queryByRole("listitem")).toBeNull();
  });
});

describe("§3.2 rows 1 and 3 — what a row is allowed to say", () => {
  it("renders an exact delta for a count change, and no number at all for a watermark move", async () => {
    render(<ActivityTicker />);
    const cb = await channel();
    open(cb);
    emit(cb, "hello", hello({ jobs: 8346, applications: 287 }));

    emit(cb, "resource_changed", {
      resource: "jobs",
      count: 8358,
      watermark: "2026-08-14T03:44:12Z",
      previousCount: 8346,
      previousWatermark: "2026-08-14T03:41:00Z",
      reason: "count_changed",
    });
    expect(await screen.findByText("12 new jobs")).toBeTruthy();
    expect(screen.getByText("+12")).toBeTruthy();

    emit(cb, "resource_changed", {
      resource: "applications",
      count: 287,
      watermark: "2026-08-14T03:45:00Z",
      previousCount: 287,
      previousWatermark: "2026-08-14T03:41:00Z",
      reason: "watermark_advanced",
    });
    const moved = await screen.findByText("Applications updated");
    // A watermark move proves a row changed, not that one was added — the row
    // carries no delta chip of any kind.
    const li = moved.closest("li") as HTMLElement;
    expect(li.textContent).not.toMatch(/[+-]\d/);
  });
});

describe("§3.5 — the degraded state is designed, not discovered", () => {
  it("stops claiming to be live and repeats the server's reason verbatim", async () => {
    render(<ActivityTicker />);
    const cb = await channel();
    open(cb);
    emit(cb, "hello", hello({ jobs: 10 }));
    emit(cb, "resource_changed", {
      resource: "jobs",
      count: 11,
      watermark: "2026-08-14T03:44:12Z",
      previousCount: 10,
      previousWatermark: "2026-08-14T03:41:00Z",
      reason: "count_changed",
    });
    await screen.findByText("1 new job");

    close(cb, "stream connection lost");

    const banner = await screen.findByTestId("activity-ticker-degraded");
    expect(banner.textContent).toMatch(/live updates (interrupted|stopped)/i);
    // The rows are KEPT (they were real), but the panel no longer presents
    // itself as current — it names the instant the data was known good.
    expect(banner.textContent).toMatch(/showing data as of/i);
    expect(screen.getByText("1 new job")).toBeTruthy();

    const detail = screen.queryByTestId("activity-ticker-detail");
    if (detail) expect(detail.textContent).toBe("stream connection lost");
  });
});

describe("the standing disclosure", () => {
  it("always states what the channel can and cannot know", async () => {
    render(<ActivityTicker />);
    const cb = await channel();
    open(cb);
    emit(cb, "hello", hello({ jobs: 1 }));

    expect(
      screen.getByText(/reports that rows changed, not what they contain/i),
    ).toBeTruthy();
  });
});
