// @vitest-environment jsdom
/**
 * TRACK D / D3 (audit wf_9a87f76f-eaa, Architect decision CLI-D3): the
 * board's safety-gate banner must state the ENFORCED contract Track B landed
 * (apps/api/app/workers/apply_sweep.py +
 * apps/api/app/services/application_submission.py):
 *
 *   - the user's `matchThreshold` gates AUTOMATIC submission — a job scoring
 *     below it, or carrying no fitScore at all, is never auto-sent;
 *   - the user's explicit approve-and-execute on a specific application
 *     BYPASSES the threshold by design ("a personal decision on a specific
 *     application outranks the account-wide bar");
 *   - the threshold comparison is inclusive (>=), so the banner may not
 *     print the strict ">" the old copy carried.
 *
 * The old sentence ("Only applications with Match Score > X% and your
 * explicit approval will be submitted") overclaimed twice: an explicitly
 * executed application BELOW the threshold IS submitted, and an autonomous
 * send (auto-apply on, approval gate off) carries no per-application human
 * approval (it records an `autonomous` approval row instead). These specs pin
 * the corrected copy at equal strictness.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import ApplicationsPage from "../page";

function mockWithConfig(agentConfig: Record<string, unknown>) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/applications") return [];
    if (path === "/jobs") return [];
    if (path.startsWith("/approvals")) return [];
    if (path === "/workspaces/settings") return { agentConfig };
    // fetchApplySweepStatus and other progressive-enhancement calls: reject
    // honestly; the page degrades to its safe defaults.
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("Auto-apply safety banner states the ENFORCED contract (CLI-D3 / D1+D2)", () => {
  it("says the threshold gates AUTO-submission (inclusive), unscored jobs are never auto-sent, and explicit execute bypasses", async () => {
    mockWithConfig({ autoApply: false, approvalGate: true, matchThreshold: 85 });
    render(<ApplicationsPage />);

    const banner = await screen.findByTestId("auto-apply-banner");
    const text = banner.textContent ?? "";

    expect(text).toMatch(/high-risk/i);
    // The user's REAL threshold, from GET /workspaces/settings.
    expect(text).toContain("85%");
    expect(text).toMatch(/match score/i);
    // The claim is about AUTOMATIC submission specifically.
    expect(text).toMatch(/auto-?submit/i);
    // An unscored job is below every threshold by definition (D2/D6).
    expect(text).toMatch(/unscored|not yet scored|no (fit )?score/i);
    // The explicit approve-and-execute path bypasses the account-wide bar.
    expect(text).toMatch(/bypass/i);
    // Live on/off state survives the rewrite.
    expect(text).toMatch(/currently\s*off/i);

    // The old overclaims are gone: no strict ">" comparison (the backend's
    // meets_match_threshold is >=), and no unconditional "your explicit
    // approval" promise that autonomous mode would falsify.
    expect(text).not.toMatch(/Match Score\s*>\s*85%/);
    expect(text).not.toMatch(/and your explicit approval will be submitted/i);
  });

  it("reflects the user's own threshold and reports auto-apply ON when enabled", async () => {
    mockWithConfig({ autoApply: true, approvalGate: true, matchThreshold: 70 });
    render(<ApplicationsPage />);

    const banner = await screen.findByTestId("auto-apply-banner");
    const text = banner.textContent ?? "";
    expect(text).toContain("70%");
    expect(text).toMatch(/currently\s*on/i);
    expect(text).not.toMatch(/currently\s*off/i);
  });
});
