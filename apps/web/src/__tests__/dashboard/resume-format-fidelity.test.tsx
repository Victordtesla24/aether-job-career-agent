// @vitest-environment jsdom
/**
 * U2b (R-F4) — FE honesty contract for format fidelity (2026-08-14).
 *
 * TDD-first: written BEFORE the implementation exists. U-PLAN.md rulings:
 *   R-F2: "the Format Integrity strip must state the truth for re-flowed
 *   documents ('rendered in Aether template; original layout preservation
 *   coming for this upload type')."
 *   R-F4: "low confidence -> faithful re-render + EXPLICIT fidelity report
 *   (never silent claims)."
 *
 * The backend contract this pins (test_u2b_format_engine.py,
 * test_reflowed_pdf_baseline_carries_an_explicit_honest_fidelity_report) adds
 * a `formatFidelity: { method, confidence, note }` object to each résumé
 * payload alongside the existing boolean `formatPreserved`. Today's Resume
 * Studio page only ever renders a HARD-CODED, mechanism-agnostic string for
 * the unpreserved case ("download renders in the Aether standard template")
 * and a hash-comparison string for the preserved case — neither reflects the
 * API's own real, per-version report, so a genuinely native DOCX-preserved
 * version and a low-confidence PDF re-flow render IDENTICAL copy today.
 *
 * Expected RED today: the page has no `format-fidelity-detail` element at
 * all (the `formatFidelity` field is not read anywhere in page.tsx), so both
 * `findByTestId` calls below time out.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Job } from "../../lib/api/jobs";
import type { Resume } from "../../lib/api/resumes";

const { JOB } = vi.hoisted(() => ({
  JOB: {
    id: "job-1",
    title: "Senior Program Manager",
    company: "Acme Corp",
    location: "Melbourne, AU",
    remote: false,
    description: "Own delivery across a portfolio.",
    requirements: [],
    source: "manual",
    sourceUrl: null,
    status: "matched",
    fitScore: 82,
    atsScore: 74,
    saved: false,
    postedAt: null,
  } satisfies Job,
}));

vi.mock("../../lib/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => (path === "/jobs" ? [JOB] : [])),
}));

vi.mock("../../lib/api/resumes", () => ({
  fetchResumes: vi.fn().mockResolvedValue([]),
  fetchResumeDiff: vi
    .fn()
    .mockResolvedValue({ resume_id: "r1", parent_id: null, changes: [] }),
  downloadResume: vi.fn().mockResolvedValue(undefined),
  runTailorAgent: vi.fn(),
}));

import ResumePage from "../../app/dashboard/resume/page";
import { fetchResumes } from "../../lib/api/resumes";

// `formatFidelity` is not yet part of the `Resume` zod type (U2b, not built),
// so fixtures here carry it as an extra untyped field the way the real API
// payload will — a plain object literal, not a `Resume`-typed value.
function resume(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    userId: "u1",
    version: 1,
    label: "Base resume",
    sections: { bullets: [] },
    sourceJobId: null,
    parentId: null,
    formatHash: "base-hash",
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

describe("U2b — format-fidelity honesty in Resume Studio", () => {
  it("shows the API's own honest re-flow note for a low-confidence version, not a generic hard-coded string", async () => {
    const base = resume({
      id: "base",
      version: 1,
      parentId: null,
      formatHash: "H",
      formatPreserved: false,
      formatFidelity: {
        method: "reflow-template",
        confidence: "low",
        note:
          "Rendered in the Aether template; original layout preservation is " +
          "not yet available for this upload type.",
      },
    });
    vi.mocked(fetchResumes).mockResolvedValue([base]);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());
    const cards = await screen.findAllByTestId("resume-version-card");
    fireEvent.click(cards[0]);

    const detail = await screen.findByTestId("format-fidelity-detail", {}, { timeout: 2000 });
    expect(detail.textContent).toMatch(/aether template/i);
    expect(detail.textContent).toMatch(/not yet available/i);
  });

  it("distinguishes genuine docx-native preservation from a bundled-PDF hash match", async () => {
    const base = resume({
      id: "base",
      version: 1,
      parentId: null,
      formatHash: "H",
      formatPreserved: true,
      formatFidelity: {
        method: "docx-native",
        confidence: "high",
        note:
          "Preserved via native document editing — your original DOCX " +
          "structure, fonts and styles are kept exactly.",
      },
    });
    vi.mocked(fetchResumes).mockResolvedValue([base]);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());
    const cards = await screen.findAllByTestId("resume-version-card");
    fireEvent.click(cards[0]);

    const detail = await screen.findByTestId("format-fidelity-detail", {}, { timeout: 2000 });
    expect(detail.textContent).toMatch(/native document editing/i);
    // The generic hash-comparison copy must not stand in for the real report.
    expect(detail.textContent).not.toMatch(/layout hash matches the base/i);
  });
});
