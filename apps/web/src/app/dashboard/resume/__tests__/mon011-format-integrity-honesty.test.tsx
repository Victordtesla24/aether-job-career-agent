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

import ResumePage from "../page";

/** A base (no-parent) résumé — the fixture's own hash never matches a
 *  bundled asset, exactly like a real upload. `formatPreserved` is a field
 *  already present on the `Resume` type (resumes.ts). Omit the argument to
 *  simulate a payload that leaves the flag out entirely (older cached
 *  payload / API predating the field) — the fail-open regression case. */
function baseResumeFixture(formatPreserved?: boolean) {
  return {
    id: "r-base",
    userId: "u1",
    version: 1,
    label: "My resume",
    sections: { bullets: [], raw_text: "Jordan Rivera\nSenior Program Manager" },
    sourceJobId: null,
    parentId: null,
    formatHash: "user-upload-hash-abc123",
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
  downloadResume.mockReset();
});

async function renderWithBaseResume(formatPreserved?: boolean) {
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
}

async function openBaseResumeIntegrityPanel(formatPreserved?: boolean) {
  await renderWithBaseResume(formatPreserved);
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

describe("MON-011 fix-round-2 — a MISSING formatPreserved flag reads as unknown, never as preserved (FE-MON011-C, mon-batch-1-fe-opus-review-verdict.json)", () => {
  it("does not fall through to the hash self-comparison and claim preservation when the API omits the flag", async () => {
    const status = await openBaseResumeIntegrityPanel(undefined);
    const text = (status.textContent ?? "").toLowerCase();

    // Reviewer probe (12:07:09Z) proved this exact fixture rendered the
    // affirmative claim pre-fix via the base résumé's trivial self-hash-match.
    expect(text).not.toContain("layout hash matches the base");
    expect(text).not.toContain("not preserved");
    expect(text).toContain("unknown");
  });
});

describe("MON-011 fix-round-2 — honest download-completion copy (FE-MON011-A, mon-batch-1-fe-opus-review-verdict.json)", () => {
  it("does not claim a format-preserving PDF was saved for a resume the download path cannot byte-preserve", async () => {
    downloadResume.mockResolvedValue(undefined);
    await renderWithBaseResume(false);

    fireEvent.click(await screen.findByTestId("download-resume-btn"));
    const note = await screen.findByTestId("download-note");
    const text = (note.textContent ?? "").toLowerCase();

    expect(text).not.toContain("format-preserving pdf saved");
    expect(text).toContain("not preserved");
  });

  it("does not claim preservation either way for a resume whose formatPreserved flag is missing", async () => {
    downloadResume.mockResolvedValue(undefined);
    await renderWithBaseResume(undefined);

    fireEvent.click(await screen.findByTestId("download-resume-btn"));
    const note = await screen.findByTestId("download-note");
    const text = (note.textContent ?? "").toLowerCase();

    expect(text).not.toContain("format-preserving pdf saved");
    expect(text).toContain("unknown");
  });

  it("keeps the affirmative download-completion claim for a resume the download path genuinely byte-preserves", async () => {
    downloadResume.mockResolvedValue(undefined);
    await renderWithBaseResume(true);

    fireEvent.click(await screen.findByTestId("download-resume-btn"));
    const note = await screen.findByTestId("download-note");

    expect((note.textContent ?? "").toLowerCase()).toContain("format-preserving pdf saved");
  });
});
