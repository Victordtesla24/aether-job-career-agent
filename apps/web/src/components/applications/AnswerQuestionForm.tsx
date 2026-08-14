"use client";

/**
 * U5d-3 Pillar 4a — the employer's question, answered inside Aether.
 *
 * ADR-SUB-AUTON-1, LAW OF MINIMAL USER ACTIVITY: *"when a submission hits a
 * blocker … the card surfaces ONLY the irreducible human step, in-app."* For
 * an unknown screening question the irreducible human step is typing the
 * answer, so this component renders the employer's OWN question text and a
 * real input of the control type parsed off their form — no link away, no
 * "open the posting and see".
 *
 * THREE HONESTY RULES THIS COMPONENT KEEPS
 *
 * 1. It never invents an answer, a default or a placeholder value. The inputs
 *    start empty and stay empty until the user types.
 * 2. It never claims more than the server did. The result line is the server's
 *    own `detail`, and the "nothing was sent / not resumed" facts come from
 *    the response — this component has no opinion about whether an application
 *    went out, because it cannot know.
 * 3. It says, per question, whether the answer will be reused. A sensitive or
 *    legal question is answered for THIS application only, forever; saying so
 *    next to the input is the difference between banking a consent and
 *    silently automating one.
 */
import { useCallback, useMemo, useState } from "react";

import {
  answerApplicationQuestion as defaultAnswer,
  type AnswerQuestionResult,
} from "../../lib/api/answer-bank";
import type { CardQuestion } from "../../lib/api/applications";

export interface AnswerFormDeps {
  submitAnswers?: (
    applicationId: string,
    answers: Array<{ question: string; answer: string }>,
  ) => Promise<AnswerQuestionResult>;
}

const TONE_BY_SENSITIVITY: Record<string, string> = {
  factual: "text-aether-green",
  judgment: "text-aether-yellow",
  sensitive: "text-aether-coral",
};

function reuseNote(question: CardQuestion): string {
  if (question.sensitivity === "sensitive") {
    return "Sensitive — Aether will never answer this for you automatically; it asks every time.";
  }
  if (question.sensitivity === "judgment") {
    return "Saved, but kept user-gated until you switch it on in your Answer Bank.";
  }
  return "Saved to your Answer Bank — Aether can answer this one for you next time.";
}

const FIELD_CLASS =
  "mt-1 w-full rounded-md border border-white/15 bg-black/30 px-2 py-1.5 text-[11px] text-white " +
  "placeholder:text-aether-muted-dim focus:border-[#818CF8]/60 focus:outline-none";

export default function AnswerQuestionForm({
  applicationId,
  questions,
  onAnswered,
  deps,
}: {
  applicationId: string;
  questions: CardQuestion[];
  /** Called with the server's real result so the board can re-read the row. */
  onAnswered?: (result: AnswerQuestionResult) => void;
  deps?: AnswerFormDeps;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const filled = useMemo(
    () =>
      questions
        .map((question) => ({
          question: question.label,
          answer: (values[question.name] ?? "").trim(),
        }))
        .filter((entry) => entry.answer.length > 0),
    [questions, values],
  );

  const save = useCallback(async () => {
    // A blank answer is never sent. Aether will not put an empty string in
    // front of an employer, and an empty POST would be a no-op that looked
    // like progress.
    if (filled.length === 0) return;
    setSaving(true);
    setFailed(false);
    setResult(null);
    const submit = deps?.submitAnswers ?? defaultAnswer;
    try {
      const answered = await submit(applicationId, filled);
      setResult(answered.detail);
      onAnswered?.(answered);
    } catch (error) {
      setFailed(true);
      setResult(
        error instanceof Error && error.message
          ? error.message
          : "That answer could not be saved — nothing was banked and nothing was sent.",
      );
    } finally {
      setSaving(false);
    }
  }, [applicationId, deps, filled, onAnswered]);

  return (
    <div
      data-testid="answer-question-form"
      onClick={(e) => e.stopPropagation()}
      className="mt-2 space-y-2 rounded-lg border border-aether-coral/30 bg-aether-coral/[0.06] p-2.5"
    >
      {questions.map((question) => (
        <div key={question.name}>
          <label
            htmlFor={`answer-${applicationId}-${question.name}`}
            className="block text-[11px] leading-snug text-white"
          >
            {question.label}
          </label>
          {question.kind === "textarea" ? (
            <textarea
              id={`answer-${applicationId}-${question.name}`}
              data-testid={`answer-input-${question.name}`}
              rows={3}
              value={values[question.name] ?? ""}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [question.name]: e.target.value }))
              }
              className={FIELD_CLASS}
            />
          ) : question.kind === "select" || question.options.length > 0 ? (
            <select
              id={`answer-${applicationId}-${question.name}`}
              data-testid={`answer-input-${question.name}`}
              value={values[question.name] ?? ""}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [question.name]: e.target.value }))
              }
              className={FIELD_CLASS}
            >
              <option value="">Choose an answer…</option>
              {question.options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={`answer-${applicationId}-${question.name}`}
              data-testid={`answer-input-${question.name}`}
              type="text"
              value={values[question.name] ?? ""}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [question.name]: e.target.value }))
              }
              className={FIELD_CLASS}
            />
          )}
          <p
            data-testid={`answer-reuse-${question.name}`}
            className={`mt-1 text-[10px] leading-snug ${
              TONE_BY_SENSITIVITY[question.sensitivity] ?? "text-aether-muted-dim"
            }`}
          >
            {reuseNote(question)}
          </p>
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="answer-submit"
          disabled={saving}
          onClick={(e) => {
            e.stopPropagation();
            void save();
          }}
          className="rounded-md border border-[#818CF8]/50 px-2 py-0.5 text-[10px] text-[#818CF8] transition hover:text-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save answer"}
        </button>
        <span className="text-[10px] text-aether-muted-dim">
          Saving does not submit this application.
        </span>
      </div>

      {result ? (
        <p
          data-testid="answer-result"
          className={`text-[10px] leading-snug ${
            failed ? "text-aether-coral" : "text-aether-muted"
          }`}
        >
          {result}
        </p>
      ) : null}
    </div>
  );
}
