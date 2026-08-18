/**
 * Timeline GL geometry — pure layout shared by DOM and WebGL (SESSION TL-VIZ-R2).
 */
import { describe, expect, it } from "vitest";

import { BACKFILL_SOURCE, buildTimelineModel, type TimelinePayload } from "../timeline-model";
import {
  buildTimelineGlGeometry,
  laneTrackWidth,
  type TimelineGlBuildOpts,
} from "../timeline-gl-geometry";
import type { TrackerApplication } from "../tracker-api";

function app(over: Partial<TrackerApplication> = {}): TrackerApplication {
  return {
    id: "app-1",
    jobId: "job-1",
    resumeId: "resume-1",
    status: "interview",
    coverLetter: null,
    jobTitle: "Senior Product Owner",
    company: "Acme Corp",
    applyUrl: "https://example.com/1",
    createdAt: "2026-07-10T00:00:00Z",
    updatedAt: "2026-07-20T00:00:00Z",
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
        {
          id: "e2",
          applicationId: "app-1",
          fromStatus: "screening",
          toStatus: "interview",
          at: "2026-07-20T00:00:00Z",
          source: "test:move",
        },
      ],
    },
    {
      application: app({
        id: "app-2",
        jobTitle: "Staff Engineer",
        company: "Beta Ltd",
        status: "offer",
      }),
      events: [
        {
          id: "f0",
          applicationId: "app-2",
          fromStatus: null,
          toStatus: "offer",
          at: "2026-07-18T00:00:00Z",
          source: BACKFILL_SOURCE,
        },
      ],
    },
  ],
  range: { start: "2026-07-10T00:00:00Z", end: "2026-07-20T00:00:00Z" },
};

const BASE: TimelineGlBuildOpts = {
  width: 800,
  labelW: 200,
  padX: 24,
  laneH: 72,
  hoverId: null,
  hoverAppId: null,
  trackMinW: 1,
};

describe("buildTimelineGlGeometry", () => {
  it("returns no geometry for an empty model", () => {
    const model = buildTimelineModel({
      items: [],
      range: { start: null, end: null },
    });
    const geo = buildTimelineGlGeometry(model, BASE);
    expect(geo.nodes).toEqual([]);
    expect(geo.edges).toEqual([]);
    expect(geo.rails).toEqual([]);
  });

  it("places one node per event with status colour and lane y", () => {
    const model = buildTimelineModel(PAYLOAD);
    const geo = buildTimelineGlGeometry(model, BASE);
    expect(geo.nodes).toHaveLength(4);
    const e1 = geo.nodes.find((n) => n.id === "e1");
    expect(e1).toBeTruthy();
    expect(e1!.color).toBe("#7C93BE");
    expect(e1!.y).toBe(36);
    expect(e1!.applicationId).toBe("app-1");
    expect(e1!.genesis).toBe(false);
    const e0 = geo.nodes.find((n) => n.id === "e0");
    expect(e0!.genesis).toBe(true);
    expect(e0!.color).toBe("#7C93BE");
    const offer = geo.nodes.find((n) => n.id === "f0");
    expect(offer!.color).toBe("#6FAF8D");
    expect(offer!.y).toBe(36 + 72);
  });

  it("connects consecutive nodes on the same lane only", () => {
    const model = buildTimelineModel(PAYLOAD);
    const geo = buildTimelineGlGeometry(model, BASE);
    expect(geo.edges.map((e) => e.key).sort()).toEqual([
      "e0-e1",
      "e1-e2",
    ]);
    expect(geo.edges.every((e) => e.applicationId === "app-1")).toBe(true);
    expect(geo.rails).toHaveLength(2);
  });

  it("marks hover on the node and brightens its lane edges + rail", () => {
    const model = buildTimelineModel(PAYLOAD);
    const geo = buildTimelineGlGeometry(model, {
      ...BASE,
      hoverId: "e1",
      hoverAppId: "app-1",
    });
    expect(geo.nodes.find((n) => n.id === "e1")!.highlighted).toBe(true);
    expect(geo.nodes.find((n) => n.id === "e0")!.highlighted).toBe(false);
    expect(geo.edges.every((e) => e.highlighted)).toBe(true);
    expect(geo.rails.find((r) => r.applicationId === "app-1")!.highlighted).toBe(
      true,
    );
    expect(geo.rails.find((r) => r.applicationId === "app-2")!.highlighted).toBe(
      false,
    );
  });

  it("derives its track basis from the shared laneTrackWidth floor (TL-VIZ-R4 D2)", () => {
    const model = buildTimelineModel(PAYLOAD);
    // A row narrower than labelW + trackMinW: the GL basis must clamp to the
    // same floor the DOM lane track's minWidth uses, not to `width - labelW`.
    const narrow = buildTimelineGlGeometry(model, {
      ...BASE,
      width: 700,
      labelW: 220,
      trackMinW: 560,
    });
    const rail = narrow.rails[0]!;
    const expectedTrackW = laneTrackWidth(700, 220, 560);
    expect(rail.x1 - rail.x0).toBe(expectedTrackW - BASE.padX * 2);
    expect(expectedTrackW).toBe(560);
  });

  it("never invents coral or indigo hexes", () => {
    const model = buildTimelineModel(PAYLOAD);
    const geo = buildTimelineGlGeometry(model, BASE);
    const palette = [
      ...geo.nodes.map((n) => n.color),
      ...geo.edges.map((e) => e.color),
      ...geo.rails.map((r) => r.color),
    ].join(" ");
    expect(palette).not.toMatch(/#FF6B35|#4F46E5/i);
  });
});
