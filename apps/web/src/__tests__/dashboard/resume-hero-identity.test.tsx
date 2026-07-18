// @vitest-environment jsdom
/**
 * MV-adv-resume-studio-006 — Resume Studio hero panes ("Original — Base
 * Resume" / "Tailored — Latest Version") must render the SIGNED-IN USER'S
 * real resume identity, not a hardcoded third party.
 *
 * Live-verified defect: apps/web/src/app/dashboard/resume/page.tsx hardcoded
 * "VIKRAM DESHPANDE / Senior Technical Program Manager · Melbourne, AU" in
 * both hero panes for EVERY user, while the version list/diff below already
 * rendered the real signed-in user's data (e.g. a user named
 * "Jordan Avery — Senior Software Engineer, Sydney" still saw
 * "VIKRAM DESHPANDE" in the hero panes).
 *
 * This test must FAIL against the pre-fix hardcoded strings and PASS once the
 * hero panes derive identity from the same `resumes` data the rest of the
 * page already consumes (real contact/raw_text, honest empty-state when
 * genuinely unavailable — never a fabricated name).
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Job } from "../../lib/api/jobs";
import type { Resume } from "../../lib/api/resumes";

const HARDCODED_NAME = /VIKRAM DESHPANDE/i;

vi.mock("../../lib/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => (path === "/jobs" ? ([] as Job[]) : [])),
}));

vi.mock("../../lib/api/resumes", () => ({
  fetchResumes: vi.fn().mockResolvedValue([]),
  fetchResumeDiff: vi.fn().mockResolvedValue({ resume_id: "r1", parent_id: null, changes: [] }),
  downloadResume: vi.fn().mockResolvedValue(undefined),
  runTailorAgent: vi.fn(),
}));

import ResumePage from "../../app/dashboard/resume/page";
import { fetchResumes } from "../../lib/api/resumes";

function resume(overrides: Partial<Resume> = {}): Resume {
  return {
    id: "r1",
    userId: "u1",
    version: 1,
    label: "Base resume",
    sections: {},
    sourceJobId: null,
    parentId: null,
    formatHash: "base-hash",
    approvalStatus: "approved",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MV-adv-resume-studio-006 — hero panes render the real signed-in user's identity", () => {
  it("shows the real user's name/title in both hero panes, never the hardcoded Vikram Deshpande placeholder", async () => {
    const base = resume({
      id: "base",
      version: 1,
      label: "Base resume",
      parentId: null,
      formatHash: "H",
      sections: {
        contact: { name: "Jordan Avery", title: "Senior Software Engineer, Sydney" },
        raw_text: "Jordan Avery\nSenior Software Engineer, Sydney\n...",
        bullets: [],
      },
    });
    const tailored = resume({
      id: "v2",
      version: 2,
      label: "Tailored — Backend Engineer",
      parentId: "base",
      formatHash: "H",
      sections: {
        contact: { name: "Jordan Avery", title: "Senior Software Engineer, Sydney" },
        raw_text: "Jordan Avery\nSenior Software Engineer, Sydney\n...",
        bullets: [],
      },
    });
    vi.mocked(fetchResumes).mockResolvedValue([tailored, base]);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());

    const originalName = await screen.findByTestId("hero-original-name");
    const originalTitle = await screen.findByTestId("hero-original-title");
    const tailoredName = await screen.findByTestId("hero-tailored-name");

    expect(originalName.textContent).toMatch(/Jordan Avery/);
    expect(originalTitle.textContent).toMatch(/Senior Software Engineer, Sydney/);
    expect(tailoredName.textContent).toMatch(/Jordan Avery/);

    // The hardcoded third-party identity must never appear anywhere on the page.
    expect(document.body.textContent).not.toMatch(HARDCODED_NAME);
  });

  it("falls back to the resume's own first text line when there is no explicit contact.name (still real data, not fabricated)", async () => {
    const base = resume({
      id: "base",
      version: 1,
      label: "Base resume",
      parentId: null,
      sections: {
        raw_text: "Priya Natarajan\nStaff Data Engineer, Melbourne\n...",
        bullets: [],
      },
    });
    vi.mocked(fetchResumes).mockResolvedValue([base]);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());

    const originalName = await screen.findByTestId("hero-original-name");
    expect(originalName.textContent).toMatch(/Priya Natarajan/);
    expect(document.body.textContent).not.toMatch(HARDCODED_NAME);
  });

  it("shows an honest empty-state when there is no base or tailored resume yet — never a fabricated identity", async () => {
    vi.mocked(fetchResumes).mockResolvedValue([]);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());

    const originalEmpty = await screen.findByTestId("hero-original-empty");
    const tailoredEmpty = await screen.findByTestId("hero-tailored-empty");

    expect(originalEmpty.textContent).toMatch(/no base resume/i);
    expect(tailoredEmpty.textContent).toMatch(/no tailored version/i);
    expect(document.body.textContent).not.toMatch(HARDCODED_NAME);
  });
});
