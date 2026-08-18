// @vitest-environment jsdom
/**
 * AUD-COV-2 — an EXPLICITLY requested low-fit letter shows its honest
 * disclosure in the Studio, not only in the JSON.
 *
 * Autopilot refuses to auto-generate a letter for a role below the user's own
 * `agentConfig.matchThreshold` (board sweep + pipeline gates). A user who asks
 * for one HERSELF still gets it — Aether does not decide for her — but the
 * backend attaches `fit_disclosure`, a sentence naming the job's score and her
 * own bar, precisely because the letter's opener reads as a confident match.
 *
 * A disclosure that only ever reaches the API response is not a disclosure to
 * the person deciding whether to send the letter. This pins that the Studio
 * renders it on the low-fit path, and stays silent on the good-fit path so the
 * warning keeps its meaning.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const fetchCoverLetters = vi.fn();
const runCoverLetterAgent = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
}));

vi.mock("../../../../lib/api/coverLetters", () => ({
  fetchCoverLetters: (...args: unknown[]) => fetchCoverLetters(...args),
  runCoverLetterAgent: (...args: unknown[]) => runCoverLetterAgent(...(args as [string])),
}));

// eslint-disable-next-line import/first
import CoverLettersPage from "../page";

const JOB = { id: "job-1", title: "Backend Engineer", company: "Acme Co" };

/** The backend's own sentence (application_submission.low_fit_disclosure). */
const DISCLOSURE =
  "Low fit: this role scored 21 against your profile, below your match " +
  "threshold of 75. You asked for this letter explicitly — autopilot would " +
  "not have generated it. Check its claims against the posting before you " +
  "send it.";

const INSIGHTS = {
  letterId: "cl-1",
  jobId: "job-1",
  jobTitle: "Backend Engineer",
  company: "Acme Co",
  wordCount: 42,
  evidence: [],
  keywords: { covered: 0, total: 0, items: [] },
  voice: { authenticity: 90, aiDetectionRisk: 5, aiDetectionLabel: "Low" },
  versions: [],
};

function mockLoads() {
  fetchCoverLetters.mockResolvedValue([]);
  apiRequest.mockImplementation((path: string) => {
    if (path === "/jobs") return Promise.resolve([JOB]);
    if (path === "/cover-letters/cl-1/insights") return Promise.resolve(INSIGHTS);
    throw new Error(`unexpected apiRequest call: ${path}`);
  });
}

async function selectJobAndGenerate() {
  await waitFor(() => screen.getByRole("option", { name: /Backend Engineer/i }));
  fireEvent.change(screen.getByTestId("cover-letter-job-select"), {
    target: { value: "job-1" },
  });
  fireEvent.click(screen.getByTestId("run-cover-letter-btn"));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AUD-COV-2 low-fit disclosure in the Cover Letter Studio", () => {
  it("shows the backend's disclosure verbatim beside an explicitly generated low-fit letter", async () => {
    mockLoads();
    runCoverLetterAgent.mockResolvedValue({
      cover_letter_id: "cl-1",
      cover_letter: "Dear hiring manager...",
      approval_id: "ap-1",
      approval_status: "pending",
      fit_disclosure: DISCLOSURE,
    });

    render(<CoverLettersPage />);
    await waitFor(() => expect(fetchCoverLetters).toHaveBeenCalledTimes(1));
    await selectJobAndGenerate();

    const notice = await screen.findByTestId("cover-letter-fit-disclosure");
    // Verbatim: the user reads the sentence the backend recorded, not a
    // restatement of it that could drift from the real bar.
    expect(notice.textContent).toBe(DISCLOSURE);
    // The letter WAS generated — the disclosure is a warning, not a refusal.
    await waitFor(() => expect(fetchCoverLetters).toHaveBeenCalledTimes(2));
  });

  it("shows nothing for a letter that clears the user's own bar", async () => {
    mockLoads();
    runCoverLetterAgent.mockResolvedValue({
      cover_letter_id: "cl-1",
      cover_letter: "Dear hiring manager...",
      approval_id: "ap-1",
      approval_status: "pending",
      fit_disclosure: "",
    });

    render(<CoverLettersPage />);
    await waitFor(() => expect(fetchCoverLetters).toHaveBeenCalledTimes(1));
    await selectJobAndGenerate();

    await waitFor(() => expect(fetchCoverLetters).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("cover-letter-fit-disclosure")).toBeNull();
  });
});
