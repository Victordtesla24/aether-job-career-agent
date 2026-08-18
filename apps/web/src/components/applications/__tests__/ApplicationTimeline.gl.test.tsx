// @vitest-environment jsdom
/**
 * GL overlay gating — Three.js must not load under reduced motion / no WebGL.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../hooks/useRenderCapabilities", () => ({
  useRenderCapabilities: vi.fn(),
}));

vi.mock("next/dynamic", () => ({
  __esModule: true,
  default: () => {
    const Mock = () => <div data-testid="timeline-gl-mock" />;
    Mock.displayName = "DynamicTimelineGL";
    return Mock;
  },
}));

import { useRenderCapabilities } from "../../../hooks/useRenderCapabilities";
import ApplicationTimeline from "../ApplicationTimeline";
import { BACKFILL_SOURCE, type TimelinePayload } from "../timeline-model";
import type { TrackerApplication } from "../tracker-api";

const caps = useRenderCapabilities as unknown as ReturnType<typeof vi.fn>;

function app(): TrackerApplication {
  return {
    id: "app-1",
    jobId: "job-1",
    resumeId: "resume-1",
    status: "submitted",
    coverLetter: null,
    jobTitle: "Senior Product Owner",
    company: "Acme Corp",
    applyUrl: null,
    createdAt: "2026-07-10T00:00:00Z",
    updatedAt: "2026-07-14T00:00:00Z",
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
      ],
    },
  ],
  range: { start: "2026-07-10T00:00:00Z", end: "2026-07-14T00:00:00Z" },
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ApplicationTimeline GL gating", () => {
  it("mounts the GL overlay when allowGl is true", async () => {
    caps.mockReturnValue({ reducedMotion: false, webgl: true, allowGl: true });
    render(<ApplicationTimeline payload={PAYLOAD} onOpenDetail={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId("timeline-gl-mock")).toBeTruthy();
    });
  });

  it("does not mount GL when reduced motion / no WebGL", () => {
    caps.mockReturnValue({ reducedMotion: true, webgl: false, allowGl: false });
    render(<ApplicationTimeline payload={PAYLOAD} onOpenDetail={vi.fn()} />);
    expect(screen.queryByTestId("timeline-gl-mock")).toBeNull();
    expect(screen.getByText("Senior Product Owner")).toBeTruthy();
  });
});
