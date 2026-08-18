/**
 * Shared lane-track width math (TL-VIZ-R4 / D2).
 *
 * The DOM lane track's inline `minWidth` and the GL geometry's `trackW`
 * basis must resolve to the exact same pixel value at every viewport width
 * — otherwise the WebGL auras/ribbons drift off the interactive DOM dots.
 * This is the one function both call; if the two ever diverge again, this
 * test (and the geometry-level check in timeline-gl-geometry.test.ts) is
 * the regression signal.
 */
import { describe, expect, it } from "vitest";

import { laneTrackWidth } from "../timeline-gl-geometry";

const LABEL_W = 220;
const LANE_TRACK_MIN = 560;

describe("laneTrackWidth", () => {
  it.each([
    [320, 560],
    [560, 560],
    [700, 560],
    [780, 560],
    [1440, 1220],
  ])("resolves a %dpx row to a %dpx track", (rowWidth, expected) => {
    expect(laneTrackWidth(rowWidth, LABEL_W, LANE_TRACK_MIN)).toBe(expected);
  });

  it("never drops below the shared floor, even at zero or negative width", () => {
    expect(laneTrackWidth(0, LABEL_W, LANE_TRACK_MIN)).toBe(LANE_TRACK_MIN);
    expect(laneTrackWidth(-100, LABEL_W, LANE_TRACK_MIN)).toBe(LANE_TRACK_MIN);
  });

  it("grows past the floor once the row leaves room for it", () => {
    // 780 is exactly labelW + floor: the boundary where growth starts.
    expect(laneTrackWidth(781, LABEL_W, LANE_TRACK_MIN)).toBe(561);
  });
});
