// @vitest-environment jsdom
/**
 * CR-P2-1 (RUN-20260818T0223Z) — /dashboard/answer-bank must never render a
 * raw, off-palette indigo hex (`#818CF8`) on the Edit textarea focus ring,
 * the "Save answer" button, the "Where it was used" toggle, or the
 * "application" usage link. The design system's palette of record
 * (`design/aether-design-system/tokens/colors.css`) has exactly one accent
 * for this kind of user-owned, non-agent-cue control: gilt (`--gold
 * #C9A84C`, exposed here as the `aether-coral` Tailwind alias). This test
 * renders the real component and asserts the forbidden hex never appears in
 * the DOM, in both the collapsed and the editing/expanded states, and that
 * the gilt token is the one actually applied.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchAnswerBankMock = vi.fn();
const fetchQuestionnaireMock = vi.fn();
const updateAnswerMock = vi.fn();

vi.mock("../../../../lib/api/answer-bank", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/answer-bank")>();
  return {
    ...actual,
    fetchAnswerBank: (...args: unknown[]) => fetchAnswerBankMock(...args),
    fetchQuestionnaire: (...args: unknown[]) => fetchQuestionnaireMock(...args),
    updateAnswer: (...args: unknown[]) => updateAnswerMock(...args),
  };
});

// eslint-disable-next-line import/first
import AnswerBankClient from "../answer-bank-client";

const ITEM = {
  id: "ans_1",
  questionText: "What is your notice period?",
  semanticKey: "concept:notice_period",
  answer: "4 weeks",
  scope: "global",
  scopeValue: "",
  provenance: "onboarding",
  provenanceDetail: null,
  sensitivity: "factual",
  staleDays: 180,
  expiresAt: null,
  expired: false,
  autoAnswerOptIn: true,
  autoAnswers: true,
  canOptIn: true,
  gateReason: "Sent automatically — a stable fact you confirmed.",
  timesUsed: 1,
  lastUsedAt: "2026-08-01T00:00:00Z",
  createdAt: "2026-07-01T00:00:00Z",
  updatedAt: "2026-08-01T00:00:00Z",
  usedOn: [
    {
      applicationId: "app_42",
      jobId: "job_7",
      questionAsSeen: "What is your notice period?",
      matchConfidence: 0.94,
      matchMethod: "semantic",
      usedAt: "2026-08-01T00:00:00Z",
    },
  ],
};

// Every raw off-palette indigo hex the audit could plausibly regress to —
// the exact forbidden value plus its nearby Tailwind-indigo siblings.
const FORBIDDEN_HEX = /#(818cf8|4f46e5|6366f1|a5b4fc|c7d2fe|312e81|3730a3|4338ca)/i;

describe("CR-P2-1 — Answer Bank forbidden-token guard", () => {
  beforeEach(() => {
    fetchAnswerBankMock.mockResolvedValue({
      items: [ITEM],
      autoAnswerThreshold: 0.86,
    });
    fetchQuestionnaireMock.mockResolvedValue({
      questions: [],
      answeredConcepts: [],
      autoAnswerThreshold: 0.86,
    });
    updateAnswerMock.mockResolvedValue({ ...ITEM, answer: "6 weeks" });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("never renders the forbidden indigo hex in the collapsed row", async () => {
    const { container } = render(<AnswerBankClient />);
    await waitFor(() => expect(screen.getByTestId(`bank-item-${ITEM.id}`)).toBeTruthy());

    expect(container.innerHTML).not.toMatch(FORBIDDEN_HEX);
  });

  it("edit mode (textarea + Save answer) uses gilt, not raw indigo hex", async () => {
    render(<AnswerBankClient />);
    await waitFor(() => expect(screen.getByTestId(`bank-item-${ITEM.id}`)).toBeTruthy());

    fireEvent.click(screen.getByTestId(`bank-edit-${ITEM.id}`));

    const textarea = screen.getByTestId(`bank-answer-input-${ITEM.id}`);
    const saveButton = screen.getByTestId(`bank-save-${ITEM.id}`);

    expect(textarea.className).not.toMatch(FORBIDDEN_HEX);
    expect(saveButton.className).not.toMatch(FORBIDDEN_HEX);
    // Positive assertion: the real design-system accent token is applied.
    expect(textarea.className).toContain("aether-coral");
    expect(saveButton.className).toContain("aether-coral");
  });

  it("the 'Where it was used' toggle and its application link use gilt, not raw indigo hex", async () => {
    render(<AnswerBankClient />);
    await waitFor(() => expect(screen.getByTestId(`bank-item-${ITEM.id}`)).toBeTruthy());

    const toggle = screen.getByTestId(`bank-usage-toggle-${ITEM.id}`);
    expect(toggle.className).not.toMatch(FORBIDDEN_HEX);
    expect(toggle.className).toContain("aether-coral");

    fireEvent.click(toggle);

    const usageList = await screen.findByTestId(`bank-usage-list-${ITEM.id}`);
    expect(usageList.innerHTML).not.toMatch(FORBIDDEN_HEX);

    const applicationLink = screen.getByRole("link", { name: "application" });
    expect(applicationLink.className).not.toMatch(FORBIDDEN_HEX);
    expect(applicationLink.className).toContain("aether-coral");
  });
});
