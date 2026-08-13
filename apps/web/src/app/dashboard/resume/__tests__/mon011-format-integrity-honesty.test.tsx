// @vitest-environment jsdom
/**
 * MON-011 (MONITORING-LEDGER.md) — Resume Studio's "Format Integrity Check"
 * claims layout preservation while EVERY real user upload re-flows into the
 * generic branded template on download (resume_pdf.py resolve_original_pdf
 * only matches the two bundled seed PDFs; resumes.py download_resume falls
 * through to the generic template for everything else).
 *
 * `formatIntact` (page.tsx ~237) is derived purely from
 * `selected.formatHash === baseHash` — a résumé compared to ITS OWN base.
 * For the base résumé itself that is a TRIVIAL self-comparison, always true,
 * and says nothing about whether the download path can reproduce the
 * original bytes/layout. So today's UI shows the affirmative "Layout hash
 * matches the base — ... preserved" claim for every real user's base résumé,
 * even though its download is the generic re-flowed template.
 *
 * Fix contract: the API sends an explicit `formatPreserved` boolean per
 * résumé (see test_mon011_honest_format_integrity.py for the backend half);
 * the frontend must render honest copy driven by THAT field instead of the
 * hash self-comparison — an unpreserved résumé gets an explicit "not
 * preserved" disclosure, a genuinely bundled-backed one keeps today's claim.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
}));

const fetchResumes = vi.fn();
const runTailorAgent = vi.fn();
const fetchResumeDiff = vi.fn();
const downloadResume = vi.fn();
vi.mock("../../../../lib/api/resumes", () => ({
  fetchResumes: (...args: unknown[]) => fetchResumes(...args),
  runTailorAgent: (...args: unknown[]) => runTailorAgent(...args),
  fetchResumeDiff: (...args: unknown[]) => fetchResumeDiff(...args),
  downloadResume: (...args: unknown[]) => downloadResume(...args),
}));

// eslint-disable-next-line import/first
import ResumePage from "../page";

/** A base (no-parent) résumé — the fixture's own hash never matches a
 *  bundled asset, exactly like a real upload. `formatPreserved: false` is
 *  the NEW field the fix must add and read; today's page.tsx ignores it
 *  entirely. */
function baseResumeFixture(formatPreserved: boolean) {
  return {
    id: "r-base",
    userId: "u1",
    version: 1,
    label: "My resume",
    sections: { bullets: [], raw_text: "Jordan Rivera\nSenior Program Manager" },
    sourceJobId: null,
    parentId: null,
    formatHash: "user-upload-hash-abc123",
    // eslint-disable-next-line @typescript-eslint/naming-convention -- API-shaped fixture field, not yet in the Resume type
    formatPreserved,
    approvalStatus: "approved",
    createdAt: "2026-07-15T00:00:00Z",
    updatedAt: "2026-07-15T00:00:00Z",
  };
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
  fetchResumes.mockReset();
  fetchResumeDiff.mockReset();
  runTailorAgent.mockReset();
});

async function openBaseResumeIntegrityPanel(formatPreserved: boolean) {
  const resume = baseResumeFixture(formatPreserved);
  fetchResumes.mockResolvedValue([resume]);
  fetchResumeDiff.mockResolvedValue({ resume_id: "r-base", parent_id: null, changes: [] });
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/jobs") return [];
    throw new Error(`unexpected apiRequest(${path})`);
  });

  render(<ResumePage />);
  const card = await screen.findByTestId("resume-version-card");
  fireEvent.click(card);
  return screen.findByTestId("integrity-status");
}

describe("MON-011 — honest Format Integrity Check copy", () => {
  it("shows an explicit NOT-preserved disclosure for a resume the download path cannot byte-preserve", async () => {
    const status = await openBaseResumeIntegrityPanel(false);
    const text = (status.textContent ?? "").toLowerCase();

    expect(text).toContain("aether standard template");
    expect(text).toContain("not preserved");
    expect(text).toContain("this upload");
    // The old, unconditional affirmative claim must NOT appear alongside it.
    expect(text).not.toContain("layout hash matches the base");
  });

  it("keeps the existing affirmative claim for a resume the download path genuinely byte-preserves", async () => {
    const status = await openBaseResumeIntegrityPanel(true);
    const text = (status.textContent ?? "").toLowerCase();

    expect(text).toContain("layout hash matches the base");
    expect(text).toContain("preserved");
  });
});
