// @vitest-environment jsdom
/**
 * MV-resume-studio FE honesty guards (Cluster E):
 *
 * - MV-resume-studio-003: an honest no-op tailor run renders an INFORMATIONAL
 *   notice ("… not charged"), never a scary error and never a phantom
 *   conversion-impact panel.
 * - MV-resume-studio-004: the Format Integrity Check reflects a REAL per-version
 *   signal (formatHash vs the base) instead of an unconditional green claim.
 * - MV-resume-studio-005: the Versions list paginates instead of rendering an
 *   unbounded scroll.
 * - MV-resume-studio-001: a pending tailored version surfaces its review state.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { fetchResumes, runTailorAgent } from "../../lib/api/resumes";

function resume(overrides: Partial<Resume> = {}): Resume {
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
  };
}

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

describe("MV-resume-studio-003 — honest no-op tailoring", () => {
  it("shows an informational notice and no conversion panel, not an error", async () => {
    vi.mocked(runTailorAgent).mockResolvedValue({
      resume_id: null,
      changes: 0,
      rejected: ["Rewrote a bullet the evidence could not verify"],
      conversionMetrics: null,
      noChangesApplied: true,
      approvalRequired: false,
      message:
        "No verifiable changes could be applied — your résumé is unchanged and you were not charged.",
    });

    await runTailorClick();

    const notice = await screen.findByTestId("tailor-notice", {}, { timeout: 2000 });
    expect(notice.textContent).toMatch(/not charged/i);
    // No phantom "ATS Conversion Impact" panel for a run that produced nothing.
    expect(screen.queryByTestId("conversion-metrics")).toBeNull();
  });
});

describe("MV-resume-studio-004 — format integrity reflects a real signal", () => {
  it("is green when the version's formatHash matches the base, amber when it differs", async () => {
    const base = resume({ id: "base", version: 1, parentId: null, formatHash: "H" });
    const intact = resume({
      id: "v2",
      version: 2,
      label: "Tailored — X",
      parentId: "base",
      formatHash: "H",
    });
    const broken = resume({
      id: "v3",
      version: 3,
      label: "Tailored — Y",
      parentId: "base",
      formatHash: "DIFFERENT",
    });
    vi.mocked(fetchResumes).mockResolvedValue([broken, intact, base]);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());

    // Nothing selected → neutral prompt (no unconditional green claim).
    expect(screen.getByTestId("integrity-status").textContent).toMatch(/select a version/i);

    const cards = await screen.findAllByTestId("resume-version-card");
    // Select the format-intact version → green "matches the base".
    fireEvent.click(cards[1]);
    await waitFor(() =>
      expect(screen.getByTestId("integrity-status").textContent).toMatch(/matches the base/i),
    );

    // Select the format-diverged version → amber "differs from the base".
    fireEvent.click(cards[0]);
    await waitFor(() =>
      expect(screen.getByTestId("integrity-status").textContent).toMatch(/differs from the base/i),
    );
  });
});

describe("MV-resume-studio-005 — versions pagination", () => {
  it("caps the initial list and reveals more on demand", async () => {
    const many = Array.from({ length: 11 }, (_, i) =>
      resume({ id: `r${i}`, version: 11 - i, label: `Tailored ${i}`, parentId: "base" }),
    );
    vi.mocked(fetchResumes).mockResolvedValue(many);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());

    let cards = await screen.findAllByTestId("resume-version-card");
    expect(cards.length).toBe(8); // VERSIONS_PAGE_SIZE
    const showMore = screen.getByTestId("versions-show-more");
    fireEvent.click(showMore);

    await waitFor(() => {
      cards = screen.getAllByTestId("resume-version-card");
      expect(cards.length).toBe(11);
    });
  });
});

describe("MV-resume-studio-001 — pending review surfaced", () => {
  it("badges a pending tailored version and hints at the approval", async () => {
    const base = resume({ id: "base", version: 1 });
    const pending = resume({
      id: "v2",
      version: 2,
      label: "Tailored — X",
      parentId: "base",
      approvalStatus: "pending",
    });
    vi.mocked(fetchResumes).mockResolvedValue([pending, base]);

    render(<ResumePage />);
    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());

    expect(screen.getByTestId("version-pending-badge").textContent).toMatch(/pending/i);

    const cards = await screen.findAllByTestId("resume-version-card");
    fireEvent.click(cards[0]);
    const hint = await screen.findByTestId("version-approval-hint");
    expect(within(hint).getByText(/approve or request changes/i)).not.toBeNull();
  });
});
