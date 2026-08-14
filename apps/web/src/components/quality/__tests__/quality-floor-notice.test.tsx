// @vitest-environment jsdom
/**
 * U2c — the Studio surfaces must show the failing dimensions VERBATIM.
 *
 * The run's honest terminal state is only honest if a user can see it. These
 * tests pin the shared notice both Studios render, plus the parsing rules that
 * decide when a surface is entitled to say anything at all.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LetterQualityPanel } from "../../cover-letters/LetterQualityPanel";
import { acknowledgementLabelFor, describeDimension, qualityGateFrom } from "../../../lib/quality-gate";
import { QualityFloorNotice } from "../QualityFloorNotice";

const FAILING_GATE = {
  artifact: "resume_tailor",
  floor: 80,
  passed: false,
  closable: true,
  dimensions: [],
  failing: [
    {
      key: "keywordMatch",
      label: "Keyword Match",
      score: 61.42,
      floor: 80,
      measured: true,
      passed: false,
      unmeasuredReason: null,
    },
  ],
  failingLabels: ["Keyword Match"],
  summary: "Below quality floor: 1 dimension did not clear the 80% floor.",
  acknowledgementLabel: "Approve anyway — 1 dimension below floor",
};

afterEach(cleanup);

describe("qualityGateFrom", () => {
  it("returns null for an artifact that was never gated", () => {
    expect(qualityGateFrom(undefined)).toBeNull();
    expect(qualityGateFrom(null)).toBeNull();
    expect(qualityGateFrom({})).toBeNull();
    expect(qualityGateFrom("passed")).toBeNull();
  });

  it("preserves the real scores rather than re-deriving them", () => {
    const gate = qualityGateFrom(FAILING_GATE)!;
    expect(gate.passed).toBe(false);
    expect(gate.failing[0].score).toBe(61.42);
    expect(gate.floor).toBe(80);
  });
});

describe("describeDimension", () => {
  it("quotes the measured score against its floor", () => {
    expect(describeDimension(qualityGateFrom(FAILING_GATE)!.failing[0])).toBe(
      "Keyword Match: 61.4% (floor 80%)",
    );
  });

  it("says 'not measured' instead of showing a placeholder number", () => {
    const gate = qualityGateFrom({
      ...FAILING_GATE,
      failing: [
        {
          key: "semanticSimilarity",
          label: "Semantic Similarity",
          score: null,
          floor: 80,
          measured: false,
          passed: false,
          unmeasuredReason: "semantic scoring was degraded",
        },
      ],
    })!;
    const text = describeDimension(gate.failing[0]);
    expect(text).toContain("not measured");
    expect(text).toContain("semantic scoring was degraded");
    expect(text).not.toContain("0.0%");
  });
});

describe("acknowledgementLabelFor", () => {
  it("matches the server's wording exactly, including the singular", () => {
    expect(acknowledgementLabelFor(1)).toBe("Approve anyway — 1 dimension below floor");
    expect(acknowledgementLabelFor(3)).toBe("Approve anyway — 3 dimensions below floor");
  });
});

describe("QualityFloorNotice", () => {
  it("names each failing dimension with its real score", () => {
    render(<QualityFloorNotice gate={qualityGateFrom(FAILING_GATE)} />);
    const notice = screen.getByTestId("quality-floor-notice");
    expect(notice.textContent).toContain("Keyword Match");
    expect(notice.textContent).toContain("61.4");
    expect(notice.textContent).toContain("80% quality floor");
  });

  it("renders nothing for a passing verdict or no verdict at all", () => {
    const { rerender } = render(
      <QualityFloorNotice gate={qualityGateFrom({ ...FAILING_GATE, passed: true })} />,
    );
    expect(screen.queryByTestId("quality-floor-notice")).toBeNull();
    rerender(<QualityFloorNotice gate={null} />);
    expect(screen.queryByTestId("quality-floor-notice")).toBeNull();
  });
});

describe("LetterQualityPanel", () => {
  const quality = {
    overall: 88,
    jdAlignment: 90,
    grounding: 61.4,
    structure: 100,
    targetScore: 85,
    reachedTarget: true,
    jdAlignmentMeasured: true,
    missingKeywords: [],
    unreachableKeywords: [],
    initialScore: 80,
    finalScore: 88,
    delta: 8,
    methodology: "Deterministic.",
  };

  it("flags a letter that cleared the headline target but not the floor", () => {
    render(
      <LetterQualityPanel
        loading={false}
        quality={{
          ...quality,
          qualityGate: {
            ...FAILING_GATE,
            artifact: "cover_letter",
            failing: [
              {
                key: "grounding",
                label: "Evidence Grounding",
                score: 61.4,
                floor: 80,
                measured: true,
                passed: false,
                unmeasuredReason: null,
              },
            ],
            failingLabels: ["Evidence Grounding"],
          },
        }}
      />,
    );
    // The old surface said only "Reached the 85% quality target" — which was
    // true and, on its own, misleading.
    expect(screen.getByTestId("letter-quality-target").textContent).toContain("Reached");
    const notice = screen.getByTestId("letter-quality-floor");
    expect(notice.textContent).toContain("Evidence Grounding");
    expect(notice.textContent).toContain("61.4");
  });

  it("shows no floor notice for a letter scored before the gate existed", () => {
    render(<LetterQualityPanel loading={false} quality={quality} />);
    expect(screen.queryByTestId("letter-quality-floor")).toBeNull();
  });
});
