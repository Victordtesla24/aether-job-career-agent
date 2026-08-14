// @vitest-environment jsdom
/**
 * U2b coherence round — the Format Integrity panel must state ONE truth.
 *
 * Live production evidence (uat/reports/evidence/agents-uplift/u2b/
 * verify-truthround/, 2026-08-14) for tailored résumé
 * `c34ec9016096f3ad0ec06a733`, rendered by THIS panel:
 *
 *   listing row  → { formatPreserved: true, formatHash: <same as base>,
 *                    formatFidelity: { confidence: "unverified", … } }
 *   GET /fidelity → { changesRequested: 4, changesApplied: 3,
 *                     changesDropped: 1, confidence: "partial", … }
 *
 * The panel then rendered BOTH of these, one under the other, for the same
 * version:
 *
 *   green  "Layout hash matches the base — typography, spacing, columns &
 *           margins preserved."
 *   amber  "Verified on the produced file: 3 of 4 tailored changes applied —
 *           1 could not be applied to this layout…"
 *
 * The green headline is derived from the LISTING row, which by design cannot
 * know whether a rewrite landed in the document (it never re-renders one); the
 * amber line is derived from the verified report, which does. When the two
 * disagree the verified report is the one that measured the artifact, so the
 * affirmative headline must yield to it — a subscriber must never be told
 * their layout is preserved directly above a notice that part of their
 * tailoring is missing from the file.
 *
 * These tests query BOTH testids in the same render, which is the only way to
 * catch an incoherence that neither element shows on its own.
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

/** The live shape: a tailored child carrying its base's formatHash and the
 *  listing's affirmative-but-unverified `formatPreserved` flag. */
const BASE_HASH = "f0c8a4e1b2d3";

function baseResume() {
  return {
    id: "r-base",
    userId: "u1",
    version: 431,
    label: "Uploaded — Vik_Resume_Final",
    sections: { bullets: [], raw_text: "Vikram Deshpande\nSenior Technical Program Manager" },
    sourceJobId: null,
    parentId: null,
    formatHash: BASE_HASH,
    formatPreserved: true,
    approvalStatus: "approved",
    createdAt: "2026-08-13T14:29:28Z",
    updatedAt: "2026-08-13T14:29:28Z",
  };
}

function tailoredResume() {
  return {
    ...baseResume(),
    id: "r-tailored",
    version: 432,
    label: "Tailored — Technical Product Delivery Manager @ Nearmap",
    parentId: "r-base",
    sourceJobId: null,
    createdAt: "2026-08-14T03:00:00Z",
    updatedAt: "2026-08-14T03:00:00Z",
  };
}

/** The verified report live production returned for that version. */
const PARTIAL_FIDELITY = {
  resume_id: "r-tailored",
  formatPreserved: false,
  method: "pdf-in-place-splice",
  confidence: "partial",
  note:
    "Your original PDF is edited in place — reworded bullets are redrawn on the page. " +
    "1 of 4 tailoring changes could not be applied to the PDF layout.",
  verification: "post-render-text-extraction",
  changesRequested: 4,
  changesApplied: 3,
  changesDropped: 1,
  droppedChanges: [
    {
      before: "AI/ML Solutions, LLM Pipelines (LangChain, Langfuse), Python, TypeScript",
      after: "Technical background in software development and AI/ML product delivery",
      coverage: 0.087,
      originalRemains: true,
    },
  ],
};

const COMPLETE_FIDELITY = {
  ...PARTIAL_FIDELITY,
  formatPreserved: true,
  confidence: "high",
  note: "Your original PDF is edited in place — reworded bullets are redrawn on the page.",
  changesApplied: 4,
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
});

async function openTailoredVersion(
  fidelity: Record<string, unknown>,
  listingFlag: boolean | undefined = true,
) {
  fetchResumes.mockResolvedValue([
    { ...tailoredResume(), formatPreserved: listingFlag },
    baseResume(),
  ]);
  fetchResumeDiff.mockResolvedValue({
    resume_id: "r-tailored",
    parent_id: "r-base",
    changes: [{ before: "old bullet", after: "new bullet", evidenceRef: "bullet-1" }],
  });
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/jobs") return [];
    if (path === "/resumes/r-tailored/fidelity") return fidelity;
    throw new Error(`unexpected apiRequest(${path})`);
  });

  render(<ResumePage />);
  const cards = await screen.findAllByTestId("resume-version-card");
  fireEvent.click(cards[0]);
  // The verified report is fetched inside the click handler; wait for the
  // element it drives before asserting on the panel as a whole.
  await screen.findByTestId("format-fidelity-counts");
}

describe("U2b — the integrity headline and the verified counts cannot contradict each other", () => {
  it("does not claim the layout is preserved above a notice that a tailored change is missing", async () => {
    await openTailoredVersion(PARTIAL_FIDELITY);

    const counts = (
      await screen.findByTestId("format-fidelity-counts")
    ).textContent?.toLowerCase();
    const status = (await screen.findByTestId("integrity-status")).textContent?.toLowerCase();

    // The verified line still tells the whole truth…
    expect(counts).toContain("3 of 4");
    expect(counts).toContain("could not be applied");

    // …and the headline above it no longer contradicts it.
    expect(status).not.toContain("layout hash matches the base");
    expect(status).not.toContain("margins preserved");
    // It states the same measured fact, in the headline's own words.
    expect(status).toContain("1 of 4");
    expect(status).toMatch(/could not be applied|missing/);
  });

  it("states the measured loss even when the listing row carries no preservation flag", async () => {
    // An older cached listing payload (or one that simply omits the flag) used
    // to render "status is unknown" — a weaker claim than the verified report
    // standing right below it, which measured exactly what is missing.
    await openTailoredVersion(PARTIAL_FIDELITY, undefined);

    const status = (await screen.findByTestId("integrity-status")).textContent?.toLowerCase();

    expect(status).toContain("1 of 4");
    expect(status).not.toContain("unknown");
  });

  it("does not promise a format-preserving file in the download note either", async () => {
    downloadResume.mockResolvedValue(undefined);
    await openTailoredVersion(PARTIAL_FIDELITY);

    fireEvent.click(await screen.findByTestId("download-resume-btn"));
    const note = (await screen.findByTestId("download-note")).textContent?.toLowerCase();

    expect(note).not.toContain("format-preserving pdf saved");
    expect(note).toContain("could not be applied");
  });

  it("keeps the affirmative headline when the verified report says every change landed", async () => {
    await openTailoredVersion(COMPLETE_FIDELITY);

    const counts = (
      await screen.findByTestId("format-fidelity-counts")
    ).textContent?.toLowerCase();
    const status = (await screen.findByTestId("integrity-status")).textContent?.toLowerCase();

    expect(counts).toContain("all 4 tailored changes are present");
    expect(status).toContain("layout hash matches the base");
    expect(status).toContain("preserved");
  });
});
