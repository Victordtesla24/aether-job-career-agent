// @vitest-environment jsdom
/**
 * SETUP-1 — first-run prompt on /dashboard after signup.
 *
 * Signup still lands on /dashboard (existing contract). Until the screening
 * answers live in Settings, a new subscriber has no reason to open that
 * screen, and the Submission Agent stops on the first application form
 * question it cannot invent. This card is the interstitial: it must send
 * them to Settings → Screening Answers, and it must never dress a failed
 * check up as "0 answers saved".
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchReadinessMock = vi.fn();
vi.mock("../../../lib/api/answer-bank", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/answer-bank")>();
  return {
    ...actual,
    fetchAnswerBankReadiness: (...args: unknown[]) => fetchReadinessMock(...args),
  };
});

// eslint-disable-next-line import/first
import ScreeningSetupPrompt from "../ScreeningSetupPrompt";

const INCOMPLETE = {
  seedTotal: 12,
  seedCovered: 0,
  seedRemaining: [],
  essentialTotal: 10,
  essentialCovered: 0,
  setupComplete: false,
  liveAnswers: 0,
  expiredAnswers: 0,
  autoAnswerable: 0,
  gatedAnswers: 0,
  timesAnswered: 0,
  learnedFromApplications: 0,
  applicationsWaiting: 0,
  autoAnswerThreshold: 0.86,
};

beforeEach(() => {
  fetchReadinessMock.mockResolvedValue(INCOMPLETE);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScreeningSetupPrompt", () => {
  it("sends an incomplete subscriber to Settings → Screening Answers", async () => {
    render(<ScreeningSetupPrompt />);
    const card = await screen.findByTestId("screening-setup-prompt");
    expect(card.textContent).toMatch(/application forms ask/i);
    const link = screen.getByTestId("screening-setup-cta");
    expect(link.getAttribute("href")).toBe("/dashboard/settings?section=screening");
  });

  it("states measured reusable coverage, never a blended score", async () => {
    fetchReadinessMock.mockResolvedValue({
      ...INCOMPLETE,
      essentialCovered: 3,
      liveAnswers: 3,
      autoAnswerable: 3,
    });
    render(<ScreeningSetupPrompt />);
    const headline = await screen.findByTestId("screening-setup-headline");
    expect(headline.textContent).toContain("3 of 10");
    expect(headline.textContent).not.toMatch(/%/);
    expect(headline.textContent).not.toContain("of 12");
  });

  it("renders nothing once every reusable answer is saved", async () => {
    fetchReadinessMock.mockResolvedValue({
      ...INCOMPLETE,
      essentialCovered: 10,
      setupComplete: true,
      liveAnswers: 10,
      autoAnswerable: 10,
    });
    render(<ScreeningSetupPrompt />);
    await waitFor(() => expect(fetchReadinessMock).toHaveBeenCalled());
    expect(screen.queryByTestId("screening-setup-prompt")).toBeNull();
    expect(screen.queryByTestId("screening-setup-cta")).toBeNull();
  });

  it("says the check failed rather than claiming zero saved answers", async () => {
    fetchReadinessMock.mockRejectedValue(new Error("GET /answer-bank/readiness failed (503)"));
    render(<ScreeningSetupPrompt />);
    const error = await screen.findByTestId("screening-setup-error");
    expect(error.textContent).toMatch(/couldn.?t check/i);
    expect(screen.queryByTestId("screening-setup-headline")).toBeNull();
    expect(screen.queryByText(/0 of /)).toBeNull();
    expect(screen.queryByText(/^0$/)).toBeNull();
    expect(screen.getByTestId("screening-setup-cta").getAttribute("href")).toBe(
      "/dashboard/settings?section=screening",
    );
  });

  it("does not flash measured zeros while the check is in flight", () => {
    fetchReadinessMock.mockReturnValue(new Promise(() => undefined));
    render(<ScreeningSetupPrompt />);
    expect(screen.queryByTestId("screening-setup-prompt")).toBeNull();
    expect(screen.queryByTestId("screening-setup-headline")).toBeNull();
    expect(screen.queryByText(/0 of 10/)).toBeNull();
  });

  it("uses no emoji and no exclamation mark", async () => {
    render(<ScreeningSetupPrompt />);
    const card = await screen.findByTestId("screening-setup-prompt");
    expect(card.textContent).not.toMatch(/[!😀-🙏]/u);
  });
});
