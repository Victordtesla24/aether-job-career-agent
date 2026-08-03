// @vitest-environment jsdom
/**
 * GOLD-MASTER-V2 §5.3.1 point 5 / §5.3.6 — the score-aware TailoringLoop
 * (``apps/api/app/services/tailoring_loop.py``) can stop at its 5-iteration
 * cap below the 85 ATS target. When it does, the backend already returns an
 * honest signal on the tailor-run response:
 *
 *   - top-level ``warning`` (string | null) — a human-readable sentence
 *     naming the iteration count AND the best score actually achieved
 *     (``apps/api/app/routers/agents.py:2309``, sourced from
 *     ``TailoringLoopResult.warning`` in tailoring_loop.py).
 *   - ``conversionMetrics.requires_review`` (bool) — wired in
 *     ``apps/api/app/agents/tailor_agent.py`` (``conversion_metrics[
 *     "requires_review"] = loop_result.requires_review``), true exactly when
 *     the loop did NOT reach the target.
 *
 * CURRENT STATE (measured this run): neither ``TailorRunResult`` nor
 * ``ConversionMetrics`` in ``apps/web/src/lib/api/resumes.ts`` even declare
 * these fields, and ``runTailor()`` in
 * ``apps/web/src/app/dashboard/resume/page.tsx`` only reads
 * ``result.conversionMetrics`` / ``result.noChangesApplied`` — ``result.
 * warning`` is never looked at, so a real sub-85 stop is silently dropped:
 * the existing "ATS Conversion Impact" banner (pre-existing, working,
 * NOT under test here) just shows the before/after numbers with no
 * indication the run fell short of the 85 target and needs a human look.
 *
 * ASSUMED contract (test-author defines it; not yet implemented): once a
 * tailor run resolves with a truthy ``warning`` (equivalently
 * ``conversionMetrics.requires_review === true``), the Resume Studio renders
 * a ``data-testid="tailor-score-warning"`` element that:
 *   (a) contains the backend's own warning text verbatim (so the
 *       best-achieved score, e.g. "72.4/100", is visibly surfaced — never
 *       just the raw number with no context), and
 *   (b) is styled as a WARNING, not a success — following this same file's
 *       existing convention for every other non-error, needs-attention
 *       notice (``tailor-notice``, ``downloadNote``,
 *       ``version-approval-hint`` for a pending review all use the
 *       `aether-amber` treatment, never `aether-green`).
 * On a clean run that reached the target (``warning: null`` /
 * ``requires_review: false``), that element must NOT render at all — a
 * false-positive guard exactly as important as the positive case, since a
 * warning shown on every run would be just as dishonest as one shown on
 * none.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Job } from "../../lib/api/jobs";

const { JOB, WARNING_TEXT } = vi.hoisted(() => ({
  JOB: {
    id: "job-1",
    title: "Senior Program Manager",
    company: "Acme Corp",
    location: "Melbourne, AU",
    remote: false,
    description: "Own delivery across a portfolio of platform initiatives.",
    requirements: [],
    source: "manual",
    sourceUrl: null,
    status: "matched",
    fitScore: 82,
    atsScore: 74,
    saved: false,
    postedAt: null,
  } satisfies Job,
  // Verbatim shape of TailoringLoop's own message (tailoring_loop.py) — the
  // UI contract is to surface this text, not paraphrase or drop it.
  WARNING_TEXT:
    "Tailoring stopped after 5 iteration(s) without reaching the target ATS " +
    "score of 85. Best score achieved: 72.4/100. Please review this resume " +
    "manually before submitting.",
}));

vi.mock("../../lib/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => (path === "/jobs" ? [JOB] : [])),
}));

vi.mock("../../lib/api/resumes", () => ({
  fetchResumes: vi.fn().mockResolvedValue([]),
  fetchResumeDiff: vi.fn().mockResolvedValue({ resume_id: "r1", parent_id: null, changes: [] }),
  downloadResume: vi.fn().mockResolvedValue(undefined),
  runTailorAgent: vi.fn(),
}));

import ResumePage from "../../app/dashboard/resume/page";
import { fetchResumes, runTailorAgent } from "../../lib/api/resumes";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function runTailorClick() {
  render(<ResumePage />);
  await waitFor(() => expect(fetchResumes).toHaveBeenCalled());
  const select = (await screen.findByLabelText(
    "Select a job to tailor for",
  )) as HTMLSelectElement;
  await waitFor(() =>
    expect(screen.getByRole("option", { name: /Senior Program Manager/i })).not.toBeNull(),
  );
  fireEvent.change(select, { target: { value: JOB.id } });
  fireEvent.click(screen.getByTestId("run-tailor-btn"));
}

describe("W-C tailoring-loop sub-85 warning surfacing (GOLD-MASTER-V2 §5.3.1 pt 5 / §5.3.6)", () => {
  it("surfaces the honest sub-85 warning including the best-achieved score, never framed as success", async () => {
    vi.mocked(runTailorAgent).mockResolvedValue({
      resume_id: "r1",
      changes: 3,
      rejected: [],
      conversionMetrics: {
        baselineATSScore: 58,
        tailoredATSScore: 72.4,
        estimatedConversionLift: "+1.8%",
        methodology: "Like-for-like ATS delta (shared context) x population baseline (2.5%)",
        confidence: "model-estimated",
        // Backend field wired in tailor_agent.py; not yet in the FE type.
        requires_review: true,
        // ADR-GMV4-004(2): declare provenance explicitly rather than relying
        // on absence to mean "trusted" — this fixture asserts the trusted
        // (measured) path, so it must say so.
        baselineDegraded: false,
        tailoredDegraded: false,
        scoringDegraded: false,
      } as never,
      // Backend field returned by agents.py:2309; not yet in the FE type.
      warning: WARNING_TEXT,
    } as never);

    await runTailorClick();

    // The pre-existing before/after banner still renders (not under test).
    await screen.findByTestId("conversion-metrics", {}, { timeout: 2000 });

    // The NEW honest warning must also render, verbatim including the
    // best-achieved score (72.4/100) that the backend already computed.
    const warningEl = await screen.findByTestId(
      "tailor-score-warning",
      {},
      { timeout: 2000 },
    );
    expect(warningEl.textContent).toContain("72.4");
    expect(warningEl.textContent).toMatch(/review this resume manually/i);

    // Never an unqualified success: this file's own convention marks every
    // other needs-attention notice amber, never green — a sub-85 result
    // must not borrow the "success" treatment.
    expect(warningEl.className).not.toMatch(/aether-green/);
    expect(screen.queryByText(/tailored successfully/i)).toBeNull();
  });

  it("does not show a spurious warning on a clean run that reached the target score", async () => {
    vi.mocked(runTailorAgent).mockResolvedValue({
      resume_id: "r2",
      changes: 2,
      rejected: [],
      conversionMetrics: {
        baselineATSScore: 61,
        tailoredATSScore: 91,
        estimatedConversionLift: "+4.9%",
        methodology: "Like-for-like ATS delta (shared context) x population baseline (2.5%)",
        confidence: "model-estimated",
        requires_review: false,
        // ADR-GMV4-004(2): declare provenance explicitly rather than relying
        // on absence to mean "trusted" — this fixture asserts the trusted
        // (measured) path, so it must say so.
        baselineDegraded: false,
        tailoredDegraded: false,
        scoringDegraded: false,
      } as never,
      warning: null,
    } as never);

    await runTailorClick();

    await screen.findByTestId("conversion-metrics", {}, { timeout: 2000 });

    // False-positive guard: a run that genuinely hit the target must never
    // display the warning banner.
    expect(screen.queryByTestId("tailor-score-warning")).toBeNull();
  });
});
