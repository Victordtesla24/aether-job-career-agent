// @vitest-environment jsdom
/**
 * SETUP-1 — the shared screening questionnaire.
 *
 * One component serves both surfaces that ask for these answers (Settings →
 * Screening Answers, and /dashboard/answer-bank). It exists as a single
 * component precisely because its copy makes promises about what Aether will
 * and will not send automatically, and two drifting copies of that copy is how
 * such a promise becomes untrue on one screen only.
 *
 * The properties pinned here are the honesty ones:
 *
 *  * no field is ever pre-filled — a questionnaire that suggests its own
 *    answers is a fabrication engine wearing a form, and `placeholder` must
 *    stay a placeholder (it is never submittable);
 *  * a blank field banks nothing and is not an error, because "I would rather
 *    answer that per application" is a legitimate choice;
 *  * a question Aether will NOT auto-answer says so before the user types.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchQuestionnaireMock = vi.fn();
const submitQuestionnaireMock = vi.fn();
vi.mock("../../../lib/api/answer-bank", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/answer-bank")>();
  return {
    ...actual,
    fetchQuestionnaire: (...args: unknown[]) => fetchQuestionnaireMock(...args),
    submitQuestionnaire: (...args: unknown[]) => submitQuestionnaireMock(...args),
  };
});

// eslint-disable-next-line import/first
import ScreeningQuestionnaire from "../ScreeningQuestionnaire";

const QUESTIONNAIRE = {
  questions: [
    {
      concept: "work_rights",
      question: "Are you legally entitled to work in the country you are applying in?",
      sensitivity: "factual",
      helper: "Asked on nearly every application.",
      placeholder: "e.g. Yes — Australian citizen with full working rights.",
      staleDays: null,
      autoAnswerable: true,
    },
    {
      concept: "salary_expectation",
      question: "What are your salary expectations?",
      sensitivity: "judgment",
      helper: "A judgement call, so it stays user-gated.",
      placeholder: "e.g. AUD 180,000 base plus super.",
      staleDays: null,
      autoAnswerable: false,
    },
    {
      concept: "notice_period",
      question: "What is your notice period?",
      sensitivity: "factual",
      helper: "Kept for 6 months, then re-confirmed.",
      placeholder: "e.g. 4 weeks.",
      staleDays: 180,
      autoAnswerable: true,
    },
  ],
  answeredConcepts: ["work_rights"],
  autoAnswerThreshold: 0.86,
};

beforeEach(() => {
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
});

describe("ScreeningQuestionnaire", () => {
  it("starts every field empty — a placeholder is never a value", async () => {
    render(<ScreeningQuestionnaire defaultOpen />);
    await waitFor(() => expect(screen.getByTestId("seed-input-work_rights")).toBeTruthy());
    for (const question of QUESTIONNAIRE.questions) {
      const input = screen.getByTestId(`seed-input-${question.concept}`) as HTMLInputElement;
      expect(input.value).toBe("");
      expect(input.placeholder).toBe(question.placeholder);
    }
  });

  it("warns before the user types that a judgement answer is not auto-sent", async () => {
    render(<ScreeningQuestionnaire defaultOpen />);
    await waitFor(() => expect(screen.getByTestId("seed-salary_expectation")).toBeTruthy());
    expect(screen.getByTestId("seed-salary_expectation").textContent).toContain(
      "asks you first",
    );
    expect(screen.getByTestId("seed-work_rights").textContent).not.toContain("asks you first");
  });

  it("marks a concept the user has already answered", async () => {
    render(<ScreeningQuestionnaire defaultOpen />);
    await waitFor(() => expect(screen.getByTestId("seed-answered-work_rights")).toBeTruthy());
    expect(screen.queryByTestId("seed-answered-notice_period")).toBeNull();
  });

  it("reports how many are still unanswered, from the server's own answered set", async () => {
    render(<ScreeningQuestionnaire defaultOpen />);
    const remaining = await screen.findByTestId("bank-questionnaire-remaining");
    expect(remaining.textContent).toContain("2 still unanswered");
  });

  it("cannot be saved while every field is blank", async () => {
    render(<ScreeningQuestionnaire defaultOpen />);
    const save = (await screen.findByTestId("bank-questionnaire-save")) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(save);
    expect(submitQuestionnaireMock).not.toHaveBeenCalled();
  });

  it("submits only the questions the user actually answered", async () => {
    const onSaved = vi.fn();
    render(<ScreeningQuestionnaire defaultOpen onSaved={onSaved} />);
    await waitFor(() => expect(screen.getByTestId("seed-input-notice_period")).toBeTruthy());
    fireEvent.change(screen.getByTestId("seed-input-notice_period"), {
      target: { value: "  4 weeks from acceptance  " },
    });
    fireEvent.click(screen.getByTestId("bank-questionnaire-save"));

    await waitFor(() => expect(submitQuestionnaireMock).toHaveBeenCalledTimes(1));
    expect(submitQuestionnaireMock).toHaveBeenCalledWith([
      { question: "What is your notice period?", answer: "4 weeks from acceptance" },
    ]);
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  });

  it("reports the server's own words after saving", async () => {
    render(<ScreeningQuestionnaire defaultOpen />);
    await waitFor(() => expect(screen.getByTestId("seed-input-notice_period")).toBeTruthy());
    fireEvent.change(screen.getByTestId("seed-input-notice_period"), {
      target: { value: "4 weeks" },
    });
    fireEvent.click(screen.getByTestId("bank-questionnaire-save"));
    const result = await screen.findByTestId("bank-questionnaire-result");
    expect(result.textContent).toContain("Saved 1 answer");
  });

  it("surfaces a save failure instead of implying the answer was stored", async () => {
    submitQuestionnaireMock.mockRejectedValue(new Error("POST /answer-bank failed (503)"));
    render(<ScreeningQuestionnaire defaultOpen />);
    await waitFor(() => expect(screen.getByTestId("seed-input-notice_period")).toBeTruthy());
    fireEvent.change(screen.getByTestId("seed-input-notice_period"), {
      target: { value: "4 weeks" },
    });
    fireEvent.click(screen.getByTestId("bank-questionnaire-save"));
    const result = await screen.findByTestId("bank-questionnaire-result");
    expect(result.textContent).toContain("503");
  });

  it("says the questions could not be loaded rather than rendering an empty form", async () => {
    fetchQuestionnaireMock.mockRejectedValue(new Error("GET /answer-bank/questionnaire failed"));
    render(<ScreeningQuestionnaire defaultOpen />);
    expect(await screen.findByTestId("bank-questionnaire-error")).toBeTruthy();
    expect(screen.queryByTestId("bank-questionnaire-save")).toBeNull();
  });

  it("stays collapsed until asked when the host does not request it open", async () => {
    render(<ScreeningQuestionnaire />);
    const toggle = await screen.findByTestId("bank-questionnaire-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByTestId("seed-input-work_rights")).toBeNull();
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByTestId("seed-input-work_rights")).toBeTruthy());
  });
});
