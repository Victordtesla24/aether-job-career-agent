// @vitest-environment jsdom
/**
 * ApplicationTimeline — DOM contract (SESSION TL-VIZ).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
    expect(screen.getByText("Senior Product Owner")).toBeTruthy();
    expect(screen.getByText("Acme Corp")).toBeTruthy();
    expect(screen.getAllByText("Earlier transitions were not observed.").length).toBeGreaterThanOrEqual(1);
    const node = screen.getByTestId("timeline-node-e1");
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
});
