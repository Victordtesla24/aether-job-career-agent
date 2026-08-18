"use client";

/**
 * SETUP-1 — the screening set-up questionnaire, in ONE place.
 *
 * These are the questions an application form asks that a résumé cannot answer:
 * work rights, notice period, salary expectation, relocation. The Submission
 * Agent needs them to send an application without stopping, and it will never
 * invent one — so the only way an application goes out unattended is if the user
 * has said the words first.
 *
 * This component is mounted by BOTH surfaces that ask for them:
 *
 *   * `/dashboard/settings` → Screening Answers, beside the résumé upload and
 *     the portfolio / GitHub / LinkedIn fields, so a new subscriber supplies
 *     everything the agent needs in one sitting;
 *   * `/dashboard/answer-bank`, alongside the full list of stored answers.
 *
 * It is deliberately ONE component rather than a copy per surface: the wording
 * here makes promises about what Aether will and will not send automatically,
 * and two drifting copies of that wording is how a promise becomes untrue on
 * one screen only.
 *
 * NOTHING HERE SUGGESTS AN ANSWER. Every field starts empty and stays empty
 * until the user types; `placeholder` is an illustrative shape, never a value
 * that can be submitted. A blank field banks nothing and is not an error —
 * "I would rather answer that one per application" is a legitimate choice.
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";

import {
  fetchQuestionnaire,
  submitQuestionnaire,
  type Questionnaire,
  type QuestionnaireResult,
} from "../../lib/api/answer-bank";

export interface ScreeningQuestionnaireProps {
  /** Render expanded on mount. Hosts open it when there is nothing banked. */
  defaultOpen?: boolean;
  onSaved?: (result: QuestionnaireResult) => void;
  eyebrow?: string;
  heading?: string;
}

export type ScreeningQuestionnaireHandle = {
  /** Persist typed drafts. True when there was nothing to save, or save succeeded. */
  saveDrafts: () => Promise<boolean>;
};

const ScreeningQuestionnaire = forwardRef<
  ScreeningQuestionnaireHandle,
  ScreeningQuestionnaireProps
>(function ScreeningQuestionnaire(
  {
    defaultOpen = false,
    onSaved,
    eyebrow = "Set-up",
    heading = "The questions employers ask most",
  },
  ref,
) {
  const [questionnaire, setQuestionnaire] = useState<Questionnaire | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(defaultOpen);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setQuestionnaire(await fetchQuestionnaire());
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "The set-up questions could not be loaded.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // `defaultOpen` is resolved by the host from data it loads asynchronously, so
  // it can flip from false to true after mount. Honour that without clobbering
  // a user who has since collapsed the panel: only opening is propagated.
  useEffect(() => {
    if (defaultOpen) setOpen(true);
  }, [defaultOpen]);

  const remaining = useMemo(() => {
    if (!questionnaire) return 0;
    return questionnaire.questions.filter(
      (question) => !questionnaire.answeredConcepts.includes(question.concept),
    ).length;
  }, [questionnaire]);

  const save = useCallback(async (): Promise<boolean> => {
    const answers = Object.entries(drafts)
      .map(([question, answer]) => ({ question, answer: answer.trim() }))
      .filter((entry) => entry.answer.length > 0);
    if (answers.length === 0) return true;
    setSaving(true);
    setResult(null);
    try {
      const saved = await submitQuestionnaire(answers);
      setResult(saved.detail);
      setDrafts({});
      await load();
      onSaved?.(saved);
      return true;
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Those answers did not save.");
      return false;
    } finally {
      setSaving(false);
    }
  }, [drafts, load, onSaved]);

  useImperativeHandle(ref, () => ({ saveDrafts: save }), [save]);

  if (loadError) {
    return (
      <p data-testid="bank-questionnaire-error" className="text-[12px] text-red-300">
        {loadError}
      </p>
    );
  }
  if (!questionnaire) return null;

  const pending = Object.values(drafts).filter((value) => value.trim().length > 0).length;

  return (
    <div data-testid="bank-questionnaire">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p className="mono text-[10px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">
            {eyebrow}
          </p>
          <h3 className="text-[15px] font-semibold">{heading}</h3>
          <p className="mt-0.5 text-[13px] leading-[1.5] text-aether-muted">
            Answer these once and applications stop waiting on you for them.{" "}
            <span data-testid="bank-questionnaire-remaining">
              {remaining > 0
                ? `${remaining} still unanswered.`
                : "All answered — nothing left here."}
            </span>
          </p>
        </div>
        <button
          type="button"
          data-testid="bank-questionnaire-toggle"
          aria-expanded={open}
          onClick={() => setOpen((prev) => !prev)}
          className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-aether-muted transition hover:bg-white/10 hover:text-white"
        >
          {open ? "Hide" : "Answer them"}
        </button>
      </header>

      {open ? (
        <>
          <ul className="space-y-3">
            {questionnaire.questions.map((question) => {
              const answered = questionnaire.answeredConcepts.includes(question.concept);
              return (
                <li key={question.concept} data-testid={`seed-${question.concept}`}>
                  <label
                    htmlFor={`seed-input-${question.concept}`}
                    className="flex flex-wrap items-center gap-2 text-[13px] text-white"
                  >
                    {question.question}
                    {answered ? (
                      <span
                        data-testid={`seed-answered-${question.concept}`}
                        className="text-[10px] text-aether-green"
                      >
                        Answered
                      </span>
                    ) : null}
                    {!question.autoAnswerable ? (
                      <span className="rounded border border-state-warn/40 px-1.5 py-0.5 text-[10px] text-state-warn">
                        asks you first
                      </span>
                    ) : null}
                  </label>
                  <input
                    id={`seed-input-${question.concept}`}
                    data-testid={`seed-input-${question.concept}`}
                    type="text"
                    value={drafts[question.question] ?? ""}
                    placeholder={question.placeholder}
                    onChange={(e) =>
                      setDrafts((prev) => ({ ...prev, [question.question]: e.target.value }))
                    }
                    className="mt-1 w-full rounded-md border border-white/15 bg-black/30 px-2.5 py-1.5 text-[12px] text-white placeholder:text-aether-muted-dim focus:border-aether-coral/50 focus:outline-none"
                  />
                  <p className="mt-1 text-[11px] leading-snug text-aether-muted-dim">
                    {question.helper}
                  </p>
                </li>
              );
            })}
          </ul>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              data-testid="bank-questionnaire-save"
              disabled={saving || pending === 0}
              onClick={() => void save()}
              className="rounded-lg bg-aether-coral px-3 py-1.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save my answers"}
            </button>
            <span className="text-[11px] text-aether-muted-dim">
              Leave anything blank to keep answering it per application.
            </span>
          </div>
        </>
      ) : null}
      {result ? (
        <p data-testid="bank-questionnaire-result" className="mt-2 text-[11px] text-aether-muted">
          {result}
        </p>
      ) : null}
    </div>
  );
});

ScreeningQuestionnaire.displayName = "ScreeningQuestionnaire";

export default ScreeningQuestionnaire;
