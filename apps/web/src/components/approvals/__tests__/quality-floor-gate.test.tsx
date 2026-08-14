// @vitest-environment jsdom
/**
 * U2c — the human must be TOLD, in the modal, before approving a below-floor
 * artifact.
 *
 * The backend refuses an un-acknowledged approve with a 409. That refusal is
 * a backstop, not a user experience: without a surface, the only thing a user
 * would see is a decision that mysteriously failed. These tests pin the
 * surface — the failing dimensions rendered VERBATIM from the run's real
 * scores, and an explicit acknowledgment that carries through to the API call.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Approval } from "../../../lib/api/approvals";

vi.mock("../../../lib/api/resumes", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/resumes")>();
  return { ...actual, fetchResumeFidelity: vi.fn().mockRejectedValue(new Error("n/a")) };
});

// eslint-disable-next-line import/first
import { ApprovalModal } from "../ApprovalModal";

const BELOW_FLOOR_GATE = {
  artifact: "resume_tailor",
  floor: 80,
  passed: false,
  closable: true,
  dimensions: [],
  failing: [
    {
      key: "keywordMatch",
      label: "Keyword Match",
      score: 61.4,
      floor: 80,
      measured: true,
      passed: false,
      unmeasuredReason: null,
    },
    {
      key: "experienceMatch",
      label: "Experience Match",
      score: 70,
      floor: 80,
      measured: true,
      passed: false,
      unmeasuredReason: null,
    },
  ],
  failingLabels: ["Keyword Match", "Experience Match"],
  summary:
    "Below quality floor: 2 dimensions did not clear the 80% floor — Keyword Match (61.4% vs 80% floor); Experience Match (70.0% vs 80% floor).",
  acknowledgementLabel: "Approve anyway — 2 dimensions below floor",
};

function approval(payload: Record<string, unknown> = {}): Approval {
  return {
    id: "appr-1",
    userId: "u1",
    applicationId: null,
    type: "application_submit",
    status: "pending",
    payload: {
      kind: "resume_tailor",
      resume_id: "resume-42",
      job_title: "Backend Engineer",
      company: "Acme",
      ...payload,
    },
    createdAt: new Date().toISOString(),
    resolvedAt: null,
  } as unknown as Approval;
}

afterEach(cleanup);

describe("below-floor approvals", () => {
  it("shows the failing dimensions with their real scores", () => {
    render(
      <ApprovalModal
        approval={approval({ qualityGate: BELOW_FLOOR_GATE })}
        onClose={() => {}}
        onDecide={async () => {}}
      />,
    );
    const banner = screen.getByTestId("modal-quality-floor");
    expect(banner.textContent).toContain("Keyword Match");
    expect(banner.textContent).toContain("61.4");
    expect(banner.textContent).toContain("Experience Match");
    expect(banner.textContent).toContain("70.0");
    expect(banner.textContent).toContain("80");
  });

  it("blocks approval until the user acknowledges, with the exact label", () => {
    render(
      <ApprovalModal
        approval={approval({ qualityGate: BELOW_FLOOR_GATE })}
        onClose={() => {}}
        onDecide={async () => {}}
      />,
    );
    const approve = screen.getByTestId("modal-approve-btn") as HTMLButtonElement;
    expect(approve.disabled).toBe(true);

    const ack = screen.getByTestId("below-floor-ack-checkbox") as HTMLInputElement;
    expect(ack.closest("label")?.textContent).toContain(
      "Approve anyway — 2 dimensions below floor",
    );
    fireEvent.click(ack);
    expect(approve.disabled).toBe(false);
  });

  it("never blocks REJECTING a below-floor artifact", () => {
    render(
      <ApprovalModal
        approval={approval({ qualityGate: BELOW_FLOOR_GATE })}
        onClose={() => {}}
        onDecide={async () => {}}
      />,
    );
    expect((screen.getByTestId("modal-reject-btn") as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("sends the acknowledgment with the approve decision", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalModal
        approval={approval({ qualityGate: BELOW_FLOOR_GATE })}
        onClose={() => {}}
        onDecide={onDecide}
      />,
    );
    fireEvent.click(screen.getByTestId("below-floor-ack-checkbox"));
    fireEvent.click(screen.getByTestId("modal-approve-btn"));
    expect(onDecide).toHaveBeenCalledWith(
      "approve",
      expect.objectContaining({ acknowledgeBelowFloor: true }),
    );
  });

  it("says so plainly when a dimension could not be measured", () => {
    render(
      <ApprovalModal
        approval={approval({
          qualityGate: {
            ...BELOW_FLOOR_GATE,
            closable: false,
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
            failingLabels: ["Semantic Similarity"],
            summary:
              "Below quality floor: 1 dimension did not clear the 80% floor — Semantic Similarity (not measured — semantic scoring was degraded).",
            acknowledgementLabel: "Approve anyway — 1 dimension below floor",
          },
        })}
        onClose={() => {}}
        onDecide={async () => {}}
      />,
    );
    const banner = screen.getByTestId("modal-quality-floor");
    expect(banner.textContent).toContain("not measured");
    expect(banner.textContent).not.toContain("0.0%");
  });

  it("renders nothing and blocks nothing when the artifact cleared the floor", () => {
    render(
      <ApprovalModal
        approval={approval({
          qualityGate: { ...BELOW_FLOOR_GATE, passed: true, failing: [], failingLabels: [] },
        })}
        onClose={() => {}}
        onDecide={async () => {}}
      />,
    );
    expect(screen.queryByTestId("modal-quality-floor")).toBeNull();
    expect((screen.getByTestId("modal-approve-btn") as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("does not invent a verdict for an approval that was never gated", () => {
    render(
      <ApprovalModal approval={approval()} onClose={() => {}} onDecide={async () => {}} />,
    );
    expect(screen.queryByTestId("modal-quality-floor")).toBeNull();
    expect((screen.getByTestId("modal-approve-btn") as HTMLButtonElement).disabled).toBe(
      false,
    );
  });
});
