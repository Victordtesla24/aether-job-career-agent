// @vitest-environment jsdom
/**
 * NF-final-resid-002 regression guard (Cover Letter Studio, final
 * adversarial sweep — adjacent frontend gap next to the NF-final-PII-002
 * backend fix).
 *
 * The async cover-letter generation job can complete honestly with a
 * no-résumé REFUSAL instead of a drafted letter: the backend's completed
 * BackgroundJob result carries `missingResume: true` and a user-actionable
 * `message` ("Add your resume before generating a cover letter."), and NO
 * `cover_letter_id` (confirmed shape in apps/api/app/workers/tasks.py's
 * `except MissingResumeError` handler — `honest_result = {"resume_id": None,
 * "missingResume": True, "message": honest_message}`).
 *
 * Before the fix, `generate()` in ../page.tsx treated ANY completed result
 * as a success: it called `load(result.cover_letter_id)` — undefined for a
 * refusal — and `setError(null)`, silently swallowing the honest refusal.
 * The user saw no message, no letter, no error: a silent no-op.
 *
 * This test drives the real page against a mocked refusal payload and
 * asserts the honest message is surfaced through the page's existing
 * `role="alert"` error UI, AND that no pointless `load(undefined)` reload
 * happens (the letters list is not re-fetched for a refusal that created
 * nothing). A second test guards the untouched success path so the fix
 * doesn't overcorrect and start treating real drafts as refusals.
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

const JOB = {
  id: "job-1",
  title: "Backend Engineer",
  company: "Acme Co",
};

const REFUSAL_MESSAGE = "Add your resume before generating a cover letter.";

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

describe("NF-final-resid-002: async no-résumé refusal surfacing", () => {
  it("surfaces the honest refusal message instead of a silent no-op", async () => {
    fetchCoverLetters.mockResolvedValue([]);
    apiRequest.mockImplementation((path: string) => {
      if (path === "/jobs") return Promise.resolve([JOB]);
      throw new Error(`unexpected apiRequest call: ${path}`);
    });
    // Exact completed-BackgroundJob refusal shape from workers/tasks.py.
    runCoverLetterAgent.mockResolvedValue({
      resume_id: null,
      missingResume: true,
      message: REFUSAL_MESSAGE,
    });

    render(<CoverLettersPage />);
    await waitFor(() => expect(fetchCoverLetters).toHaveBeenCalledTimes(1));

    await selectJobAndGenerate();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(REFUSAL_MESSAGE);

    // No load(undefined) side effect: the letters list must not be
    // re-fetched for a refusal that generated nothing.
    expect(fetchCoverLetters).toHaveBeenCalledTimes(1);
  });

  it("still loads the new draft and clears errors on a real completed letter (no overcorrection)", async () => {
    fetchCoverLetters.mockResolvedValue([]);
    apiRequest.mockImplementation((path: string) => {
      if (path === "/jobs") return Promise.resolve([JOB]);
      throw new Error(`unexpected apiRequest call: ${path}`);
    });
    runCoverLetterAgent.mockResolvedValue({
      cover_letter_id: "cl-1",
      cover_letter: "Dear hiring manager...",
      approval_id: "ap-1",
      approval_status: "pending",
    });
    apiRequest.mockImplementation((path: string) => {
      if (path === "/jobs") return Promise.resolve([JOB]);
      if (path === "/cover-letters/cl-1/insights") {
        // Minimal valid LetterInsightsSchema payload — the insights rail
        // fetch that fires once `expanded` becomes "cl-1" after load().
        return Promise.resolve({
          letterId: "cl-1",
          jobId: "job-1",
          jobTitle: "Backend Engineer",
          company: "Acme Co",
          wordCount: 42,
          evidence: [],
          keywords: { covered: 0, total: 0, items: [] },
          voice: { authenticity: 90, aiDetectionRisk: 5, aiDetectionLabel: "Low" },
          versions: [],
        });
      }
      throw new Error(`unexpected apiRequest call: ${path}`);
    });

    render(<CoverLettersPage />);
    await waitFor(() => expect(fetchCoverLetters).toHaveBeenCalledTimes(1));

    await selectJobAndGenerate();

    // A successful draft reloads the letters list (load(result.cover_letter_id)).
    await waitFor(() => expect(fetchCoverLetters).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
