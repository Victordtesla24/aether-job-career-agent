// @vitest-environment jsdom
/**
 * U5d-3 Pillar 4a — the native in-card question (RED first).
 *
 * ADR-SUB-AUTON-1: *"UNKNOWN QUESTION → rendered NATIVELY in the card
 * (question text + typed input extracted from the form); user answers inside
 * Aether … and BANKS the answer. No site visit."*
 *
 * All transport is MOCKED. The ONLY endpoint this component may call is
 * `POST /applications/{id}/answer-question`, which transmits nothing — a
 * component that reached a submit path would fail these tests.
 *
 * The honesty contract pinned here: the card never claims the paused attempt
 * resumed, never claims anything was sent, and never pretends a sensitive
 * answer will be reused — the server says which of those are true and the UI
 * repeats it rather than deciding for itself.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SubmissionControl from "../SubmissionControl";
import type {
  Application,
  SubmissionControl as ControlBlock,
} from "../../../lib/api/applications";

function questionControl(overrides: Partial<ControlBlock> = {}): ControlBlock {
  return {
    state: "manual_step",
    action: "answer_question",
    label: "Answer it here — 1 question",
    detail:
      "This employer asks something Aether has no answer for and will not invent.",
    channel: "ashby",
    applyUrl: "https://jobs.ashbyhq.com/example-co/abc",
    href: null,
    missing: [],
    questions: [
      {
        name: "custom_q1",
        label: "How many years of Kubernetes experience do you have?",
        kind: "text",
        options: [],
        required: true,
        sensitivity: "factual",
        reusable: true,
      },
    ],
    ...overrides,
  } as ControlBlock;
}

function application(control: ControlBlock): Pick<
  Application,
  "id" | "submissionControl" | "transmittedAt" | "transmissionRef"
> {
  return {
    id: "app_1",
    submissionControl: control,
    transmittedAt: null,
    transmissionRef: null,
  };
}

describe("U5d-3 native in-card question", () => {
  it("renders the employer's question verbatim with a real input", () => {
    render(<SubmissionControl application={application(questionControl())} />);

    expect(screen.getByTestId("submission-control").getAttribute("data-state")).toBe(
      "manual_step",
    );
    expect(
      screen.getByText("How many years of Kubernetes experience do you have?"),
    ).toBeTruthy();
    expect(screen.getByTestId("answer-input-custom_q1")).toBeTruthy();
  });

  it("renders a textarea for a long-form question and a select for a choice", () => {
    const control = questionControl({
      questions: [
        {
          name: "q_long",
          label: "Why do you want to work here?",
          kind: "textarea",
          options: [],
          required: true,
          sensitivity: "judgment",
          reusable: false,
        },
        {
          name: "q_choice",
          label: "Preferred working arrangement",
          kind: "select",
          options: ["Remote", "Hybrid", "Onsite"],
          required: true,
          sensitivity: "factual",
          reusable: true,
        },
      ],
    } as Partial<ControlBlock>);
    render(<SubmissionControl application={application(control)} />);

    expect(screen.getByTestId("answer-input-q_long").tagName).toBe("TEXTAREA");
    const choice = screen.getByTestId("answer-input-q_choice");
    expect(choice.tagName).toBe("SELECT");
    expect(choice.querySelectorAll("option").length).toBe(4); // 3 + the empty prompt
  });

  it("says honestly, per question, whether the answer will be reused", () => {
    const control = questionControl({
      questions: [
        {
          name: "q_sensitive",
          label: "Do you consent to a criminal background check?",
          kind: "text",
          options: [],
          required: true,
          sensitivity: "sensitive",
          reusable: false,
        },
      ],
    } as Partial<ControlBlock>);
    render(<SubmissionControl application={application(control)} />);

    const note = screen.getByTestId("answer-reuse-q_sensitive").textContent ?? "";
    expect(note.toLowerCase()).toContain("never");
  });

  it("posts the answer to the answer-question endpoint and nothing else", async () => {
    const submitAnswers = vi.fn().mockResolvedValue({
      applicationId: "app_1",
      banked: [],
      remainingQuestions: [],
      resumed: false,
      transmitted: false,
      detail: "Saved to your Answer Bank. Nothing has been sent.",
    });
    const requestSubmission = vi.fn();
    const executeApproval = vi.fn();

    render(
      <SubmissionControl
        application={application(questionControl())}
        deps={{ submitAnswers, requestSubmission, executeApproval }}
      />,
    );

    fireEvent.change(screen.getByTestId("answer-input-custom_q1"), {
      target: { value: "6 years" },
    });
    fireEvent.click(screen.getByTestId("answer-submit"));

    await waitFor(() => expect(submitAnswers).toHaveBeenCalledTimes(1));
    expect(submitAnswers).toHaveBeenCalledWith("app_1", [
      { question: "How many years of Kubernetes experience do you have?", answer: "6 years" },
    ]);
    expect(requestSubmission).not.toHaveBeenCalled();
    expect(executeApproval).not.toHaveBeenCalled();
  });

  it("repeats the server's honest 'nothing was sent' result", async () => {
    const submitAnswers = vi.fn().mockResolvedValue({
      applicationId: "app_1",
      banked: [],
      remainingQuestions: [],
      resumed: false,
      transmitted: false,
      detail: "Saved to your Answer Bank. Nothing has been sent — next attempt.",
    });
    render(
      <SubmissionControl
        application={application(questionControl())}
        deps={{ submitAnswers }}
      />,
    );
    fireEvent.change(screen.getByTestId("answer-input-custom_q1"), {
      target: { value: "6 years" },
    });
    fireEvent.click(screen.getByTestId("answer-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("answer-result").textContent).toContain(
        "Nothing has been sent",
      ),
    );
  });

  it("refuses to send a blank answer at all", () => {
    const submitAnswers = vi.fn();
    render(
      <SubmissionControl
        application={application(questionControl())}
        deps={{ submitAnswers }}
      />,
    );
    fireEvent.click(screen.getByTestId("answer-submit"));
    expect(submitAnswers).not.toHaveBeenCalled();
  });

  it("surfaces a save failure honestly instead of pretending it saved", async () => {
    const submitAnswers = vi.fn().mockRejectedValue(new Error("Network is down"));
    render(
      <SubmissionControl
        application={application(questionControl())}
        deps={{ submitAnswers }}
      />,
    );
    fireEvent.change(screen.getByTestId("answer-input-custom_q1"), {
      target: { value: "6 years" },
    });
    fireEvent.click(screen.getByTestId("answer-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("answer-result").textContent).toContain("Network is down"),
    );
  });

  it("falls back to the posting link when the server captured no questions", () => {
    const control = questionControl({
      action: "open_posting",
      label: "Needs a manual step",
      questions: [],
    } as Partial<ControlBlock>);
    render(<SubmissionControl application={application(control)} />);

    expect(screen.getByTestId("submission-control-link")).toBeTruthy();
    expect(screen.queryByTestId("answer-submit")).toBeNull();
  });
});
