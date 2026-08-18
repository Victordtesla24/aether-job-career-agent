// @vitest-environment jsdom
/**
 * ApplicationTimeline — DOM contract (SESSION TL-VIZ).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import ApplicationTimeline from "../ApplicationTimeline";
import { BACKFILL_SOURCE, type TimelinePayload } from "../timeline-model";
import type { TrackerApplication } from "../tracker-api";

function app(over: Partial<TrackerApplication> = {}): TrackerApplication {
  return {
    id: "app-1",
    jobId: "job-1",
    resumeId: "resume-1",
    status: "submitted",
    coverLetter: null,
    jobTitle: "Senior Product Owner",
    company: "Acme Corp",
    applyUrl: "https://example.com/1",
    createdAt: "2026-07-10T00:00:00Z",
    updatedAt: "2026-07-14T00:00:00Z",
    fitScore: 88,
    ...over,
  } as TrackerApplication;
}

const PAYLOAD: TimelinePayload = {
  items: [
    {
      application: app(),
      events: [
        {
          id: "e0",
          applicationId: "app-1",
          fromStatus: null,
          toStatus: "submitted",
          at: "2026-07-10T00:00:00Z",
          source: BACKFILL_SOURCE,
        },
        {
          id: "e1",
          applicationId: "app-1",
          fromStatus: "submitted",
          toStatus: "screening",
          at: "2026-07-14T00:00:00Z",
          source: "test:move",
        },
      ],
    },
  ],
  range: { start: "2026-07-10T00:00:00Z", end: "2026-07-14T00:00:00Z" },
};

afterEach(() => {
  cleanup();
});

beforeAll(() => {
  // jsdom lacks PointerEvent capture APIs used by the pan handler
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
});

describe("ApplicationTimeline", () => {
  it("renders empty honesty copy with no invented dates", () => {
    render(
      <ApplicationTimeline
        payload={{ items: [], range: { start: null, end: null } }}
        onOpenDetail={vi.fn()}
      />,
    );
    const root = screen.getByTestId("timeline-view");
    expect(root.textContent).toContain("No applications yet.");
    expect(root.textContent).not.toMatch(/\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/);
    expect(root.innerHTML).not.toMatch(/#FF6B35|#4F46E5|aether-coral|coral/i);
  });

  it("renders horizontal lanes and opens detail on node activate", () => {
    const onOpen = vi.fn();
    render(<ApplicationTimeline payload={PAYLOAD} onOpenDetail={onOpen} />);
    expect(screen.getByTestId("timeline-view")).toBeTruthy();
    expect(screen.getByTestId("timeline-legend")).toBeTruthy();
    expect(screen.getByText("Senior Product Owner")).toBeTruthy();
    expect(screen.getByText("Acme Corp")).toBeTruthy();
    expect(screen.getAllByText("Earlier transitions were not observed.").length).toBeGreaterThanOrEqual(1);
    const node = screen.getByTestId("timeline-node-e1");
    fireEvent.mouseEnter(node);
    expect(screen.getByTestId("timeline-focus").textContent).toMatch(/In review/);
    fireEvent.click(node);
    expect(onOpen).toHaveBeenCalledWith("app-1");
    fireEvent.keyDown(node, { key: "Enter" });
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("surfaces load errors without fabricating tracks", () => {
    render(
      <ApplicationTimeline
        payload={null}
        error="Couldn't load the timeline — request failed."
        onRetry={vi.fn()}
        onOpenDetail={vi.fn()}
      />,
    );
    expect(screen.getByTestId("timeline-view").textContent).toContain(
      "Couldn't load the timeline — request failed.",
    );
    expect(screen.getByTestId("timeline-retry")).toBeTruthy();
    expect(screen.queryByTestId("timeline-lane-app-1")).toBeNull();
  });

  it("allows vertical scroll when many lanes exceed the viewport (adv P0)", () => {
    const many: TimelinePayload = {
      items: Array.from({ length: 14 }, (_, i) => ({
        application: app({
          id: `app-${i}`,
          jobId: `job-${i}`,
          jobTitle: `Role ${i}`,
          company: `Co ${i}`,
        }),
        events: [
          {
            id: `e-${i}`,
            applicationId: `app-${i}`,
            fromStatus: null,
            toStatus: "submitted",
            at: "2026-07-10T00:00:00Z",
            source: BACKFILL_SOURCE,
          },
        ],
      })),
      range: { start: "2026-07-10T00:00:00Z", end: "2026-07-10T00:00:00Z" },
    };
    render(<ApplicationTimeline payload={many} onOpenDetail={vi.fn()} />);
    const scroller = screen.getByTestId("timeline-scroller");
    expect(scroller.className).toMatch(/overflow-y-auto/);
  });

  it("insets SVG connectors to match node PAD_X positioning (adv P1)", () => {
    render(<ApplicationTimeline payload={PAYLOAD} onOpenDetail={vi.fn()} />);
    const svg = screen.getByTestId("timeline-connectors");
    expect(svg.getAttribute("style") || "").toMatch(/left:\s*28px/);
    expect(svg.getAttribute("style") || "").toMatch(/right:\s*28px/);
  });

  it("suppresses node click after a drag pan (adv P1)", () => {
    const onOpen = vi.fn();
    render(<ApplicationTimeline payload={PAYLOAD} onOpenDetail={onOpen} />);
    const track = screen.getByTestId("timeline-track");

    const dispatchPointer = (
      type: "pointerdown" | "pointermove" | "pointerup",
      clientX: number,
    ) => {
      const ev = new Event(type, { bubbles: true, cancelable: true }) as Event & {
        button: number;
        buttons: number;
        clientX: number;
        pointerId: number;
      };
      Object.assign(ev, {
        button: 0,
        buttons: type === "pointerup" ? 0 : 1,
        clientX,
        pointerId: 1,
      });
      fireEvent(track, ev);
    };

    dispatchPointer("pointerdown", 100);
    dispatchPointer("pointermove", 160);
    expect(track.getAttribute("style") || "").toMatch(/translateX\(48px\)/);
    dispatchPointer("pointerup", 160);
    fireEvent.click(screen.getByTestId("timeline-node-e1"));
    expect(onOpen).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("timeline-node-e1"));
    expect(onOpen).toHaveBeenCalledWith("app-1");
  });
});
