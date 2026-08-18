// @vitest-environment jsdom
/**
 * SETUP-1 — Screening Answers on the Settings screen.
 *
 * The Submission Agent stops on any screening question it has no stored answer
 * for, and it will never invent one. Before this panel existed the ONLY place to
 * supply those answers was `/dashboard/answer-bank`, a page absent from the
 * 13-item sidebar (`lib/navigation.ts`) — so a new subscriber had no route to
 * the one input the agent needs most, and their first application stopped
 * without them understanding why.
 *
 * These specs pin the honesty properties of the panel, not its styling:
 *
 *  * a failed readiness check must NOT render as "0 answers saved" — "we could
 *    not check" and "you have nothing saved" are different facts, and showing
 *    the second for the first tells a fully set-up user to start over;
 *  * the panel states measured counts, and the headline must reflect the
 *    ESSENTIAL (reusable) subset rather than every seed question, since
 *    judgement and sensitive classes are user-gated by design;
 *  * a user with applications stopped on a question is told so, and given the
 *    route to them.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchSettingsMock = vi.fn();
const fetchCareerDataMock = vi.fn();
const saveSettingsMock = vi.fn();
vi.mock("../../../../lib/api/workspaces", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/workspaces")>();
  return {
    ...actual,
    fetchSettings: (...args: unknown[]) => fetchSettingsMock(...args),
    fetchCareerData: (...args: unknown[]) => fetchCareerDataMock(...args),
    saveSettings: (...args: unknown[]) => saveSettingsMock(...args),
  };
});

const fetchSubscriptionMock = vi.fn();
const fetchPlansMock = vi.fn();
vi.mock("../../../../lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/billing")>();
  return {
    ...actual,
    fetchSubscription: (...args: unknown[]) => fetchSubscriptionMock(...args),
    fetchPlans: (...args: unknown[]) => fetchPlansMock(...args),
  };
});

const fetchApplySweepStatusMock = vi.fn();
vi.mock("../../../../lib/api/applications", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/applications")>();
  return {
    ...actual,
    fetchApplySweepStatus: (...args: unknown[]) => fetchApplySweepStatusMock(...args),
  };
});

const fetchReadinessMock = vi.fn();
const fetchQuestionnaireMock = vi.fn();
const submitQuestionnaireMock = vi.fn();
vi.mock("../../../../lib/api/answer-bank", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/answer-bank")>();
  return {
    ...actual,
    fetchAnswerBankReadiness: (...args: unknown[]) => fetchReadinessMock(...args),
    fetchQuestionnaire: (...args: unknown[]) => fetchQuestionnaireMock(...args),
    submitQuestionnaire: (...args: unknown[]) => submitQuestionnaireMock(...args),
  };
});

// eslint-disable-next-line import/first
import SettingsPage from "../page";

const SETTINGS = {
  profile: {
    fullName: "Jamie Rivera",
    email: "jamie@example.com",
    targetRole: "Staff Engineer",
    location: "Sydney, AU",
  },
  resume: { activeFile: "resume.pdf", uploadedAt: "2026-07-01", versions: 3 },
  portfolio: { url: null, cadence: null, lastSynced: null },
  agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 80 },
  integrations: [],
  connectedAccounts: [],
};

const READINESS = {
  seedTotal: 12,
  seedCovered: 4,
  seedRemaining: [
    { concept: "relocation", question: "Are you willing to relocate?", sensitivity: "factual" },
  ],
  essentialTotal: 10,
  essentialCovered: 4,
  setupComplete: false,
  liveAnswers: 4,
  expiredAnswers: 0,
  autoAnswerable: 3,
  gatedAnswers: 1,
  timesAnswered: 7,
  learnedFromApplications: 2,
  applicationsWaiting: 0,
  autoAnswerThreshold: 0.86,
};

const QUESTIONNAIRE = {
  questions: [
    {
      concept: "work_rights",
      question: "Are you legally entitled to work in the country you are applying in?",
      sensitivity: "factual",
      helper: "Asked on nearly every application.",
      placeholder: "e.g. Yes — Australian citizen.",
      staleDays: null,
      autoAnswerable: true,
    },
    {
      concept: "salary_expectation",
      question: "What are your salary expectations?",
      sensitivity: "judgment",
      helper: "A judgement call, so it stays user-gated.",
      placeholder: "e.g. AUD 180,000 base.",
      staleDays: null,
      autoAnswerable: false,
    },
  ],
  answeredConcepts: ["work_rights"],
  autoAnswerThreshold: 0.86,
};

beforeEach(() => {
  fetchSettingsMock.mockResolvedValue(SETTINGS);
  fetchCareerDataMock.mockResolvedValue({ sources: [], linkedinNote: "" });
  fetchSubscriptionMock.mockResolvedValue({
    plan: { id: "pro", name: "Pro", modelTier: "advanced" },
    status: "active",
    interval: "month",
    currentPeriodEnd: "2026-09-01T00:00:00Z",
    cancelAtPeriodEnd: false,
    quota: {
      runsUsed: 15,
      runsAllowed: 100,
      spendUsedUsd: 0.074688,
      spendCapUsd: 15.0,
      periodEnd: "2026-09-01T00:00:00Z",
    },
  });
  fetchPlansMock.mockResolvedValue({ plans: [] });
  fetchApplySweepStatusMock.mockResolvedValue(false);
  saveSettingsMock.mockResolvedValue(SETTINGS);
  fetchReadinessMock.mockResolvedValue(READINESS);
  fetchQuestionnaireMock.mockResolvedValue(QUESTIONNAIRE);
  submitQuestionnaireMock.mockResolvedValue({
    banked: 1,
    skipped: 0,
    items: [],
    detail: "Saved 1 answer to your Answer Bank.",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/dashboard/settings");
});

describe("Settings — Screening Answers", () => {
  it("renders the panel with the résumé and links, on the default tab", async () => {
    render(<SettingsPage />);
    expect(await screen.findByTestId("settings-screening")).toBeTruthy();
    // Same tab as the résumé upload and the career links: one place.
    expect(screen.getByTestId("settings-resume")).toBeTruthy();
  });

  it("offers Screening Answers as its own sub-nav entry", async () => {
    render(<SettingsPage />);
    expect(await screen.findByTestId("settings-nav-screening")).toBeTruthy();
  });

  it("states the measured counts it was given", async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByTestId("screening-readiness")).toBeTruthy());
    expect(screen.getByTestId("screening-stat-saved").textContent).toBe("4");
    expect(screen.getByTestId("screening-stat-auto").textContent).toBe("3");
    expect(screen.getByTestId("screening-stat-reused").textContent).toBe("7");
    expect(screen.getByTestId("screening-stat-waiting").textContent).toBe("0");
  });

  it("counts progress against the reusable subset, not every seed question", async () => {
    /* 4 of 10 essential — never "4 of 12", which would include the
       judgement/sensitive classes Aether refuses to auto-send, i.e. a bar that
       can never be completed. */
    render(<SettingsPage />);
    const headline = await screen.findByTestId("screening-readiness-headline");
    expect(headline.textContent).toContain("4 of 10");
    expect(headline.textContent).not.toContain("of 12");
  });

  it("credits the learning loop with what real applications taught it", async () => {
    render(<SettingsPage />);
    const learned = await screen.findByTestId("screening-learned");
    expect(learned.textContent).toContain("2");
  });

  it("says the check failed rather than claiming zero saved answers", async () => {
    fetchReadinessMock.mockRejectedValue(new Error("GET /answer-bank/readiness failed (503)"));
    render(<SettingsPage />);
    expect(await screen.findByTestId("screening-readiness-error")).toBeTruthy();
    expect(screen.queryByTestId("screening-readiness")).toBeNull();
    expect(screen.queryByTestId("screening-stat-saved")).toBeNull();
  });

  it("routes the user to applications that are stopped on a question", async () => {
    fetchReadinessMock.mockResolvedValue({ ...READINESS, applicationsWaiting: 3 });
    render(<SettingsPage />);
    const link = await screen.findByTestId("screening-waiting-link");
    expect(link.getAttribute("href")).toBe("/dashboard/applications");
    expect(link.textContent).toContain("3");
  });

  it("does not claim applications are waiting when none are", async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByTestId("screening-readiness")).toBeTruthy());
    expect(screen.queryByTestId("screening-waiting-link")).toBeNull();
  });

  it("tells a fully set-up user the reusable answers are saved, not that every phrasing is covered", async () => {
    fetchReadinessMock.mockResolvedValue({
      ...READINESS,
      essentialCovered: 10,
      setupComplete: true,
    });
    render(<SettingsPage />);
    const headline = await screen.findByTestId("screening-readiness-headline");
    expect(headline.textContent).toMatch(/reusable answers are saved/i);
    expect(headline.textContent).toMatch(/still comes back/i);
    expect(headline.textContent).not.toMatch(/will not stop/i);
  });

  it("warns when a saved answer has gone stale instead of sending it", async () => {
    fetchReadinessMock.mockResolvedValue({ ...READINESS, expiredAnswers: 2 });
    render(<SettingsPage />);
    const expired = await screen.findByTestId("screening-expired");
    expect(expired.textContent).toContain("re-confirming");
  });

  it("links to the Answer Bank for the full audited list", async () => {
    render(<SettingsPage />);
    const link = await screen.findByTestId("screening-bank-link");
    expect(link.getAttribute("href")).toBe("/dashboard/answer-bank");
  });

  it("opens Screening Answers alone from ?section=screening", async () => {
    window.history.replaceState(null, "", "/dashboard/settings?section=screening");
    render(<SettingsPage />);
    expect(await screen.findByTestId("settings-screening")).toBeTruthy();
    expect(screen.getByTestId("settings-nav-screening").getAttribute("aria-pressed")).toBe(
      "true",
    );
    // Deep-link focuses the screening panel; résumé stays on its own tab.
    expect(screen.queryByTestId("settings-resume")).toBeNull();
    expect(await screen.findByTestId("bank-questionnaire")).toBeTruthy();
  });

  it("does not offer profile Save Changes on the Screening Answers tab", async () => {
    window.history.replaceState(null, "", "/dashboard/settings?section=screening");
    render(<SettingsPage />);
    expect(await screen.findByTestId("bank-questionnaire-save")).toBeTruthy();
    expect(screen.queryByTestId("save-settings-btn")).toBeNull();
    expect(saveSettingsMock).not.toHaveBeenCalled();
  });

  it("banks screening drafts when Save Changes is pressed on the Profile tab", async () => {
    render(<SettingsPage />);
    const input = await screen.findByTestId("seed-input-work_rights");
    fireEvent.change(input, { target: { value: "Yes — Australian citizen." } });
    fireEvent.click(screen.getByTestId("save-settings-btn"));
    await waitFor(() =>
      expect(submitQuestionnaireMock).toHaveBeenCalledWith([
        {
          question: "Are you legally entitled to work in the country you are applying in?",
          answer: "Yes — Australian citizen.",
        },
      ]),
    );
    expect(saveSettingsMock).toHaveBeenCalled();
  });

  it("mounts the shared questionnaire, expanded while set-up is incomplete", async () => {
    render(<SettingsPage />);
    expect(await screen.findByTestId("bank-questionnaire")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByTestId("seed-input-work_rights")).toBeTruthy(),
    );
    // No suggested answers: every field is empty until the user types.
    expect((screen.getByTestId("seed-input-work_rights") as HTMLInputElement).value).toBe("");
  });
});
