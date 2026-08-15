// @vitest-environment jsdom
/**
 * RFMT-2 — Résumé Studio: Download gives the clean file, Preview shows the tint.
 *
 * The peach/coral wash behind a reworded bullet is a Studio affordance, not
 * part of the résumé. Until this slice the server drew it unconditionally, so
 * the employer-facing download carried it (nine bullets across three pages on a
 * live tailored résumé), and the Studio told the user so in as many words:
 * "the same lines the download washes in coral".
 *
 * These tests pin the corrected contract on the screen:
 *
 * 1. the Download button calls `downloadResume` and asks for NO diff variant;
 * 2. a separate, explicit affordance requests the tinted PREVIEW
 *    (`previewTailoredResume` → `?diff=true`) and opens it, releasing the blob;
 * 3. the copy no longer tells the user their download is washed in coral.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
}));

const fetchResumes = vi.fn();
const fetchResumeDiff = vi.fn();
const runTailorAgent = vi.fn();
const downloadResume = vi.fn();
const previewTailoredResume = vi.fn();
vi.mock("../../../../lib/api/resumes", () => ({
  fetchResumes: (...args: unknown[]) => fetchResumes(...args),
  fetchResumeDiff: (...args: unknown[]) => fetchResumeDiff(...args),
  runTailorAgent: (...args: unknown[]) => runTailorAgent(...args),
  downloadResume: (...args: unknown[]) => downloadResume(...args),
  previewTailoredResume: (...args: unknown[]) => previewTailoredResume(...args),
}));

import ResumePage from "../page";

const BASELINE = {
  id: "r-base",
  userId: "u1",
  version: 1,
  label: "Baseline",
  sections: {
    bullets: [{ text: "Delivered the payments migration on schedule." }],
    raw_text: "Jordan Rivera\nSenior Program Manager",
  },
  sourceJobId: null,
  parentId: null,
  formatHash: "hash-base",
  formatPreserved: true,
  approvalStatus: "approved",
  createdAt: "2026-08-14T00:00:00Z",
  updatedAt: "2026-08-14T00:00:00Z",
};

const TAILORED = {
  ...BASELINE,
  id: "r-tailored",
  version: 2,
  label: "Tailored — Delivery Manager",
  parentId: "r-base",
  sections: {
    bullets: [{ text: "Delivered the payments migration two weeks early." }],
    raw_text: "Jordan Rivera\nSenior Program Manager",
  },
};

/** The verified report for the open version — a clean, fully applied splice. */
const FIDELITY = {
  resume_id: "r-tailored",
  formatPreserved: true,
  method: "pdf-in-place-splice",
  confidence: "high",
  note: "Your original PDF is edited in place — reworded bullets are redrawn on the page.",
  verification: "post-render-text-extraction",
  changesRequested: 1,
  changesApplied: 1,
  changesDropped: 0,
  droppedChanges: [],
};

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
  fetchResumes.mockReset();
  fetchResumeDiff.mockReset();
  runTailorAgent.mockReset();
  downloadResume.mockReset();
  previewTailoredResume.mockReset();
});

async function openTailoredVersion() {
  fetchResumes.mockResolvedValue([TAILORED, BASELINE]);
  fetchResumeDiff.mockResolvedValue({
    resume_id: "r-tailored",
    parent_id: "r-base",
    changes: [
      {
        before: "Delivered the payments migration on schedule.",
        after: "Delivered the payments migration two weeks early.",
        evidenceRef: "bullet-0",
      },
    ],
  });
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/jobs") return [];
    if (path === "/resumes/r-tailored/fidelity") return FIDELITY;
    return {};
  });
  render(<ResumePage />);
  const cards = await screen.findAllByTestId("resume-version-card");
  fireEvent.click(cards[0]!);
  await screen.findByTestId("download-resume-btn");
}

describe("RFMT-2 — Studio download vs preview", () => {
  it("the Download button asks for the clean file (no diff variant)", async () => {
    await openTailoredVersion();
    downloadResume.mockResolvedValue(undefined);

    fireEvent.click(screen.getByTestId("download-resume-btn"));
    await waitFor(() => expect(downloadResume).toHaveBeenCalled());

    expect(previewTailoredResume).not.toHaveBeenCalled();
    const [, options] = downloadResume.mock.calls[0]!;
    // No option at all, or an explicit non-diff one — never a request for the
    // marked-up variant.
    expect((options as { diff?: boolean } | undefined)?.diff ?? false).toBe(false);
  });

  it("the preview affordance requests the tinted variant and releases the blob", async () => {
    await openTailoredVersion();
    const revoke = vi.fn();
    previewTailoredResume.mockResolvedValue({ url: "blob:preview", revoke });
    const opened = { location: { href: "" }, opener: {} as unknown, close: vi.fn() };
    const openSpy = vi
      .spyOn(window, "open")
      .mockReturnValue(opened as unknown as Window);

    fireEvent.click(screen.getByTestId("preview-highlights-btn"));
    await waitFor(() => expect(previewTailoredResume).toHaveBeenCalledWith("r-tailored"));

    expect(openSpy).toHaveBeenCalled();
    await waitFor(() => expect(opened.location.href).toBe("blob:preview"));
    expect(downloadResume).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("a blocked pop-up is disclosed, never silently swallowed", async () => {
    await openTailoredVersion();
    const revoke = vi.fn();
    previewTailoredResume.mockResolvedValue({ url: "blob:preview", revoke });
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);

    fireEvent.click(screen.getByTestId("preview-highlights-btn"));
    const note = await screen.findByTestId("download-note");
    expect(note.textContent?.toLowerCase()).toContain("pop-up");
    expect(revoke).toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("no copy on the screen claims the downloaded file is washed in coral", async () => {
    await openTailoredVersion();
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/the download washes in coral/i);
    expect(body).not.toMatch(/washed in coral in the document you download/i);
  });
});
