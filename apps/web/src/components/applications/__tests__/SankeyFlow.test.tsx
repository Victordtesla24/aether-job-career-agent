// @vitest-environment jsdom
/**
 * MV-application-tracker-006 regression guard (defense-in-depth).
 *
 * The backend's cumulative funnel model keeps every dropoff >= 0, but a
 * prior stage-EXCLUSIVE model let a dropoff go negative (e.g. -3), which
 * this component rendered as the broken literal "−-3 · no response /
 * screened out" (double-negative nonsense) — SankeyFlow.tsx:104 concatenated
 * a literal "−" with whatever `dropoff.count` was, with no guard. This
 * renders the real component with a deliberately negative dropoff (as if a
 * future backend regression reintroduced one) and asserts the displayed
 * text is never a double-negative — it clamps to "−0" instead.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import SankeyFlow from "../SankeyFlow";
import type { SankeyData } from "../tracker-api";

afterEach(() => {
  cleanup();
});

const BASE_DATA: SankeyData = {
  stages: [
    { key: "jobs_found", label: "Jobs Found", value: 10, color: "#4F46E5" },
    { key: "applied", label: "Applied", value: 4, color: "#818CF8" },
    { key: "screened", label: "Screened", value: 0, color: "#FF6B35" },
    { key: "interviewed", label: "Interviewed", value: 3, color: "#F59E0B" },
    { key: "offers", label: "Offers", value: 1, color: "#34D399" },
  ],
  dropoffs: [
    { after: "jobs_found", count: 6, reason: "below match threshold" },
    { after: "applied", count: 4, reason: "not shortlisted" },
    // Deliberately negative — simulates a data anomaly / backend regression
    // reaching the frontend, exactly the "screened=0, interviewed=3" shape
    // the reviewer reproduced against be7b240.
    { after: "screened", count: -3, reason: "no response / screened out" },
    { after: "interviewed", count: 2, reason: "not selected" },
  ],
  insight: "10 jobs found, 4 applied.",
};

describe("SankeyFlow dropoff rendering (MV-application-tracker-006)", () => {
  it("never renders a double-negative dropoff like '−-3' — clamps to '−0'", () => {
    const { container } = render(<SankeyFlow data={BASE_DATA} />);
    const svgText = container.querySelector("svg")?.textContent ?? "";

    expect(svgText).not.toMatch(/−-\d/);
    expect(svgText).toContain("−0 · no response / screened out");
  });

  it("still renders genuine non-negative dropoffs unchanged", () => {
    const { container } = render(<SankeyFlow data={BASE_DATA} />);
    const svgText = container.querySelector("svg")?.textContent ?? "";

    expect(svgText).toContain("−6 · below match threshold");
    expect(svgText).toContain("−4 · not shortlisted");
    expect(svgText).toContain("−2 · not selected");
  });
});
