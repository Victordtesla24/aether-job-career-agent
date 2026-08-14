// @vitest-environment jsdom
/**
 * U2b truth round — Resume Studio must show the VERIFIED fidelity report.
 *
 * Live production evidence (uat/reports/evidence/agents-uplift/u2b/verify/,
 * 2026-08-14) caught this panel telling the owner
 * "pdf-in-place-splice · high confidence — Only the reworded bullets are
 * redrawn on your original PDF — every other element is identical to the
 * source document." for a tailored résumé whose downloaded PDF still carried
 * the ORIGINAL text of one of its four reworded bullets.
 *
 * The listing (`GET /resumes`) cannot re-render every version, so its row now
 * says the per-change check is pending. The authoritative answer comes from
 * `GET /resumes/{id}/fidelity`, which re-reads the produced document. This
 * pins that Resume Studio renders THAT report — counts and the named
 * un-applied rewrite included — for the version the user opened.
 *
 * Expected RED before the fix: the page never calls the fidelity endpoint, so
 * it keeps rendering the listing's own row and no `format-fidelity-counts`
 * element exists.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Resume } from "../../lib/api/resumes";

const VERIFIED_REPORT = {
  resume_id: "tailored",
  method: "pdf-in-place-splice",
  confidence: "partial",
  note:
    "Your original PDF is edited in place — reworded bullets are redrawn on " +
    "the page and every other element is the source document's own. 1 of 2 " +
    "tailoring changes could not be applied to the PDF layout — the full " +
    "tailored wording is in this version's text (Resume Studio's change " +
    "summary), not in the downloaded file.",
  verification: "post-render-text-extraction",
  changesRequested: 2,
  changesApplied: 1,
  changesDropped: 1,
  droppedChanges: [
    { before: "AI/ML Solutions, LLM Pipelines", after: "Technical background in…", coverage: 0.087 },
  ],
  formatPreserved: true,
};

vi.mock("../../lib/api/client", () => ({
  apiRequest: vi.fn(async (path: string) =>
    path.endsWith("/fidelity") ? VERIFIED_REPORT : [],
  ),
}));

vi.mock("../../lib/api/resumes", () => ({
  fetchResumes: vi.fn().mockResolvedValue([]),
  fetchResumeDiff: vi
    .fn()
    .mockResolvedValue({ resume_id: "tailored", parent_id: "base", changes: [] }),
  downloadResume: vi.fn().mockResolvedValue(undefined),
  runTailorAgent: vi.fn(),
}));

import ResumePage from "../../app/dashboard/resume/page";
import { fetchResumes } from "../../lib/api/resumes";

function resume(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    userId: "u1",
    version: 1,
    label: "Base resume",
    sections: { bullets: [] },
    sourceJobId: null,
    parentId: null,
    formatHash: "H",
    approvalStatus: "approved",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  } as unknown as Resume;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("U2b truth round — verified fidelity in Resume Studio", () => {
  it("renders the verified per-change report for the opened version, not the listing's pending claim", async () => {
    const tailored = resume({
      id: "tailored",
      version: 2,
      label: "Tailored — Delivery Manager",
      parentId: "base",
      formatPreserved: true,
      formatFidelity: {
        method: "pdf-in-place-splice",
        confidence: "unverified",
        note:
          "Your original PDF is edited in place. Each reworded bullet is " +
          "verified against the file itself when this version is rendered.",
      },
    });
    vi.mocked(fetchResumes).mockResolvedValue([tailored, resume({ id: "base" })]);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());
    const cards = await screen.findAllByTestId("resume-version-card");
    const card = cards.find((c) => c.textContent?.includes("Tailored"));
    expect(card).toBeTruthy();
    fireEvent.click(card as HTMLElement);

    const detail = await screen.findByTestId("format-fidelity-detail", {}, { timeout: 2000 });
    await waitFor(() => expect(detail.textContent).toMatch(/could not be applied/i));
    expect(detail.textContent).toMatch(/partial/i);
    expect(detail.textContent).not.toMatch(/every other element is identical/i);

    const counts = await screen.findByTestId("format-fidelity-counts", {}, { timeout: 2000 });
    expect(counts.textContent).toMatch(/1 of 2/);
    expect(counts.textContent).toMatch(/could not be applied/i);
  });
});
