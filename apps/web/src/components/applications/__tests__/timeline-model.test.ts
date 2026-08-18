/**
 * Application Timeline model — pure layout + honesty rules (SESSION TL-VIZ).
 */
import { describe, expect, it } from "vitest";

import type { TrackerApplication } from "../tracker-api";
import {
  BACKFILL_SOURCE,
  GENESIS_NOTE,
  STATUS_NODE_COLOR,
  buildTimelineModel,
  type TimelinePayload,
} from "../timeline-model";

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
    ...over,
  } as TrackerApplication;
}

describe("buildTimelineModel", () => {
  it("empty payload yields no lanes and null range (never invents today)", () => {
    const payload: TimelinePayload = {
      items: [],
      range: { start: null, end: null },
    };
    const model = buildTimelineModel(payload);
    expect(model.lanes).toEqual([]);
    expect(model.range.start).toBeNull();
    expect(model.range.end).toBeNull();
    expect(model.empty).toBe(true);
    expect(model.axisTicks).toEqual([]);
  });

  it("maps events to nodes with status colours — never coral or indigo", () => {
    const payload: TimelinePayload = {
      items: [
        {
          application: app({ status: "interview" }),
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
              at: "2026-07-12T00:00:00Z",
              source: "test:move",
            },
            {
              id: "e2",
              applicationId: "app-1",
              fromStatus: "screening",
              toStatus: "interview",
              at: "2026-07-14T00:00:00Z",
              source: "test:move",
            },
          ],
        },
      ],
      range: { start: "2026-07-10T00:00:00Z", end: "2026-07-14T00:00:00Z" },
    };
    const model = buildTimelineModel(payload);
    expect(model.empty).toBe(false);
    expect(model.lanes).toHaveLength(1);
    const lane = model.lanes[0]!;
    expect(lane.applicationId).toBe("app-1");
    expect(lane.company).toBe("Acme Corp");
    expect(lane.jobTitle).toBe("Senior Product Owner");
    expect(lane.nodes).toHaveLength(3);
    expect(lane.nodes[0]!.genesis).toBe(true);
    expect(lane.nodes[0]!.note).toBe(GENESIS_NOTE);
    expect(lane.nodes[1]!.genesis).toBe(false);
    for (const n of lane.nodes) {
      expect(n.color).not.toMatch(/#FF6B35|#4F46E5/i);
      expect(n.color).toBe(STATUS_NODE_COLOR[n.toStatus as keyof typeof STATUS_NODE_COLOR]);
    }
    expect(STATUS_NODE_COLOR.draft).toBe("#C9A84C"); // gilt = ready action only
    expect(STATUS_NODE_COLOR.offer).toBe("#6FAF8D");
    expect(STATUS_NODE_COLOR.rejected).toBe("#B9544B");
  });

  it("places nodes on [0,1] x-axis from observed range", () => {
    const payload: TimelinePayload = {
      items: [
        {
          application: app(),
          events: [
            {
              id: "e0",
              applicationId: "app-1",
              fromStatus: "draft",
              toStatus: "submitted",
              at: "2026-07-10T00:00:00Z",
              source: "test",
            },
            {
              id: "e1",
              applicationId: "app-1",
              fromStatus: "submitted",
              toStatus: "screening",
              at: "2026-07-14T00:00:00Z",
              source: "test",
            },
          ],
        },
      ],
      range: { start: "2026-07-10T00:00:00Z", end: "2026-07-14T00:00:00Z" },
    };
    const model = buildTimelineModel(payload);
    expect(model.lanes[0]!.nodes[0]!.x).toBeCloseTo(0, 5);
    expect(model.lanes[0]!.nodes[1]!.x).toBeCloseTo(1, 5);
  });

  it("filter and sort reuse tracker card helpers", () => {
    const payload: TimelinePayload = {
      items: [
        {
          application: app({
            id: "a-low",
            company: "Zeta",
            jobTitle: "A",
            fitScore: 70,
            updatedAt: "2026-07-10T00:00:00Z",
          }),
          events: [
            {
              id: "e0",
              applicationId: "a-low",
              fromStatus: null,
              toStatus: "submitted",
              at: "2026-07-10T00:00:00Z",
              source: BACKFILL_SOURCE,
            },
          ],
        },
        {
          application: app({
            id: "a-high",
            company: "Alpha",
            jobTitle: "B",
            fitScore: 92,
            updatedAt: "2026-07-14T00:00:00Z",
          }),
          events: [
            {
              id: "e1",
              applicationId: "a-high",
              fromStatus: null,
              toStatus: "submitted",
              at: "2026-07-14T00:00:00Z",
              source: BACKFILL_SOURCE,
            },
          ],
        },
      ],
      range: { start: "2026-07-10T00:00:00Z", end: "2026-07-14T00:00:00Z" },
    };
    const highOnly = buildTimelineModel(payload, { filter: "high-fit", sort: "company" });
    expect(highOnly.lanes.map((l) => l.applicationId)).toEqual(["a-high"]);

    const byCompany = buildTimelineModel(payload, { filter: "all", sort: "company" });
    expect(byCompany.lanes.map((l) => l.company)).toEqual(["Alpha", "Zeta"]);
  });
});
