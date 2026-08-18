"use client";

/**
 * SUB-010 — the SMART SHORTLIST answer pack, on one screen.
 *
 * LEDGER: *"read-only GET /applications/{id}/answer-pack fusing profile +
 * answer bank + resume + cover for every manual job, + a 'needs your click'
 * filter. Buildable from existing parts. Honesty contract: never claims
 * applied."*
 *
 * WHAT THIS IS. When Aether cannot finish an application itself — the platform
 * prohibits automation, the site wants a login, or the form asks something
 * Aether refuses to invent an answer to — the last step is the user's own
 * click. Until now that meant re-assembling by hand, from four screens, the
 * material Aether already held for that one job. This panel is that material
 * in one place, in copy-ready blocks.
 *
 * THE HONESTY CONTRACT, in copy (clause 3). Every string on this panel is
 * about a row with NO transmission proof, so none of them says applied,
 * submitted or sent; the server's own honesty statement leads the panel, and
 * the test scans the rendered text for those words. Values are shown exactly
 * as the server returned them, and a missing piece renders the server's
 * absence sentence — never an empty box, never a placeholder, never a guess.
 *
 * NOTHING HERE WRITES. Opening the panel issues one GET. There is no submit
 * control on it, and no path from it to an employer.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { downloadResume } from "../../lib/api/resumes";
import {
  fetchAnswerPack,
  type AnswerPack,
  type AnswerPackEntry,
  type AnswerPackField,
} from "./tracker-api";

/** A stable testid/DOM id for one question, derived from its own wording. */
export function entrySlug(question: string): string {
  return question
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

/** Where a question came from, in the user's language. */
function questionSourceLabel(source: string): string {
  return source === "employer_form"
    ? "This employer asked it"
    : "Most application forms ask it";
}

/** Where an answer came from. Never anywhere else — there is no generator. */
function answerSourceLabel(source: string | null): string {
  if (source === "this_application") return "your answer for this role";
  if (source === "answer_bank") return "your Answer Bank";
  return "";
}

/**
 * Copy one value to the clipboard.
 *
 * The whole point of the pack is that the user pastes their own material into
 * the employer's form themselves, so this is the only interaction on the
 * panel. It is best-effort: a browser without clipboard permission simply
 * leaves the text on screen to select by hand, and nothing claims otherwise.
 */
function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <button
      type="button"
      aria-label={`Copy ${label}`}
      onClick={() => {
        void navigator?.clipboard
          ?.writeText(value)
          .then(() => setCopied(true))
          .catch(() => setCopied(false));
      }}
      className="shrink-0 rounded-md border border-hairline px-2 py-0.5 text-[10px] text-aether-muted transition hover:border-hairline-strong hover:text-aether-text"
    >
      <i className="fa-regular fa-copy text-[9px]" aria-hidden="true" />{" "}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** A missing piece, stated in the server's own words. */
function Absence({ text }: { text: string }) {
  return (
    <p className="mt-1 text-[11px] leading-relaxed text-state-neutral">
      <i className="fa-regular fa-circle-question mr-1 text-[9px]" aria-hidden="true" />
      {text}
    </p>
  );
}

function ProfileField({ field }: { field: AnswerPackField }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface-2 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.1em] text-aether-muted-dim">
            {field.label}
          </p>
          {field.present && field.value ? (
            <p className="mono mt-1 break-words text-[12px] text-aether-text">{field.value}</p>
          ) : null}
        </div>
        {field.present && field.value ? (
          <CopyButton value={field.value} label={field.label} />
        ) : null}
      </div>
      {field.present && field.source ? (
        <p className="mt-1 text-[10px] text-aether-muted-dim">from {field.source}</p>
      ) : null}
      {!field.present && field.absence ? <Absence text={field.absence} /> : null}
    </div>
  );
}

function AnswerEntry({ entry }: { entry: AnswerPackEntry }) {
  return (
    <li
      data-testid={`answer-pack-entry-${entrySlug(entry.question)}`}
      className="rounded-lg border border-hairline bg-surface-2 p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-[12px] font-medium leading-snug text-aether-text">
          {entry.question}
        </p>
        {entry.answered && entry.answer ? (
          <CopyButton value={entry.answer} label="this answer" />
        ) : null}
      </div>
      <p className="mt-0.5 text-[10px] text-aether-muted-dim">
        {questionSourceLabel(entry.questionSource)}
      </p>
      {entry.answered && entry.answer ? (
        <>
          <p className="mt-2 whitespace-pre-wrap text-[12px] leading-relaxed text-aether-muted">
            {entry.answer}
          </p>
          <p className="mt-1 text-[10px] text-aether-muted-dim">
            In your own words, from {answerSourceLabel(entry.answerSource)}
            {entry.bankedQuestion && entry.answerSource === "answer_bank"
              ? ` — banked as “${entry.bankedQuestion}”`
              : ""}
            {entry.matchConfidence != null && entry.answerSource === "answer_bank"
              ? ` (match ${Math.round(entry.matchConfidence * 100)}%)`
              : ""}
          </p>
        </>
      ) : entry.absence ? (
        <Absence text={entry.absence} />
      ) : null}
      {/* The Answer Bank's transmission gate, reported and never widened: this
          panel shows the user their own answer to copy, which has never been
          gated — what the gate decides is whether Aether may ever put it into
          a form unattended. */}
      {!entry.wouldAutoSend ? (
        <p className="mt-2 flex items-start gap-1.5 text-[10px] leading-relaxed text-state-info">
          <i className="fa-solid fa-hand text-[9px] leading-4" aria-hidden="true" />
          <span>{entry.gateReason}</span>
        </p>
      ) : null}
    </li>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-4">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-aether-muted">
          {title}
        </h4>
        {count ? <span className="mono text-[10px] text-aether-muted-dim">{count}</span> : null}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}

export default function AnswerPackPanel({
  applicationId,
  onClose,
}: {
  applicationId: string;
  onClose: () => void;
}) {
  const [pack, setPack] = useState<AnswerPack | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => onClose(), [onClose]);

  useEffect(() => {
    let cancelled = false;
    setPack(null);
    setError(null);
    fetchAnswerPack(applicationId)
      .then((data) => {
        if (!cancelled) setPack(data);
      })
      .catch((e) => {
        // An honest failure, in the product's plain register — never an empty
        // pack, which would read as "there is nothing for this role".
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Couldn't load this pack.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={close}
    >
      <div
        data-testid="answer-pack-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="answerPackTitle"
        onClick={(e) => e.stopPropagation()}
        className="elev-3 relative my-6 w-[720px] max-w-[94vw] rounded-[14px] border border-hairline bg-surface-1 p-6"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3
              id="answerPackTitle"
              className="text-base font-semibold leading-snug text-aether-text"
            >
              Answer pack
            </h3>
            {pack ? (
              <p className="mt-0.5 truncate text-[12px] text-aether-muted">
                {pack.jobTitle} · {pack.company}
              </p>
            ) : null}
          </div>
          <button
            ref={closeRef}
            type="button"
            data-testid="answer-pack-close"
            aria-label="Close the answer pack"
            onClick={close}
            className="shrink-0 rounded-md border border-hairline px-2 py-1 text-[11px] text-aether-muted transition hover:border-hairline-strong hover:text-aether-text"
          >
            <i className="fa-solid fa-xmark text-[10px]" aria-hidden="true" />
          </button>
        </div>

        {error ? (
          <p
            data-testid="answer-pack-error"
            className="mt-4 rounded-lg border border-state-danger/40 bg-state-danger/10 p-3 text-[12px] text-aether-text"
          >
            Couldn&apos;t load this pack — {error}. Nothing changed, and nothing left
            Aether.
          </p>
        ) : null}

        {!pack && !error ? (
          <p className="mt-4 text-[12px] text-aether-muted">Reading what Aether holds…</p>
        ) : null}

        {pack ? (
          <>
            {/* The server's own honesty block leads the panel: what this row
                is, in one sentence, before any material is shown. */}
            <p
              data-testid="answer-pack-honesty"
              className="mt-4 rounded-lg border border-sapphire/40 bg-sapphire/10 p-3 text-[12px] leading-relaxed text-aether-text"
            >
              <i
                className="fa-solid fa-hand-pointer mr-1.5 text-[10px] text-sapphire-light"
                aria-hidden="true"
              />
              {pack.honesty.statement} {pack.honesty.note}
            </p>

            {pack.applyUrl ? (
              <a
                href={pack.applyUrl}
                target="_blank"
                rel="noreferrer noopener"
                data-testid="answer-pack-apply-link"
                className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-surface-2 px-3 py-1.5 text-[11px] text-aether-muted transition hover:border-hairline-strong hover:text-aether-text"
              >
                <i className="fa-solid fa-arrow-up-right-from-square text-[9px]" aria-hidden="true" />
                Open the employer&apos;s form
              </a>
            ) : null}

            <Section
              title="Your details"
              count={`${pack.profile.presentCount} on file · ${pack.profile.missingCount} missing`}
            >
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {pack.profile.fields.map((field) => (
                  <ProfileField key={field.key} field={field} />
                ))}
              </div>
              {pack.profile.otherResumeContactLines.length > 0 ? (
                <p className="mt-2 text-[10px] text-aether-muted-dim">
                  Also on your résumé:{" "}
                  {pack.profile.otherResumeContactLines.join(" · ")}
                </p>
              ) : null}
            </Section>

            <Section
              title="Questions and your answers"
              count={`${pack.answers.answeredCount} answered · ${pack.answers.unansweredCount} open`}
            >
              <p className="text-[11px] leading-relaxed text-aether-muted-dim">
                {pack.answers.note}
              </p>
              <ul className="mt-2 space-y-2">
                {pack.answers.entries.map((entry) => (
                  <AnswerEntry key={entry.question} entry={entry} />
                ))}
              </ul>
            </Section>

            <Section title="Your résumé for this role">
              {pack.resume.present && pack.resume.resumeId && pack.resume.downloadPath ? (
                <>
                  {/* An artifact REFERENCE, fetched through the authenticated
                      résumé client — the same `GET /resumes/{id}/download` the
                      Studio's own button and the email attachment path use, so
                      the file the employer receives is the file named here.
                      A bare <a href> could not carry the bearer token, and a
                      link that 401s is a promise the panel cannot keep. */}
                  <button
                    type="button"
                    data-testid="answer-pack-resume-link"
                    data-resume-id={pack.resume.resumeId}
                    data-download-path={pack.resume.downloadPath}
                    onClick={() => {
                      setResumeError(null);
                      void downloadResume(pack.resume.resumeId!).catch((e) =>
                        setResumeError(
                          e instanceof Error ? e.message : "the download failed",
                        ),
                      );
                    }}
                    className="inline-flex items-center gap-2 rounded-lg border border-hairline bg-surface-2 px-3 py-2 text-[12px] text-aether-text transition hover:border-hairline-strong"
                  >
                    <i className="fa-regular fa-file-lines text-[11px]" aria-hidden="true" />
                    {pack.resume.label ?? "Tailored résumé"}
                    {pack.resume.version != null ? (
                      <span className="mono text-[10px] text-aether-muted-dim">
                        v{pack.resume.version}
                      </span>
                    ) : null}
                  </button>
                  {resumeError ? (
                    <p
                      data-testid="answer-pack-resume-error"
                      className="mt-2 text-[11px] text-state-danger"
                    >
                      Couldn&apos;t open your résumé — {resumeError}.
                    </p>
                  ) : null}
                </>
              ) : pack.resume.absence ? (
                <Absence text={pack.resume.absence} />
              ) : null}
            </Section>

            <Section title="Your cover letter">
              {pack.coverLetter.present && pack.coverLetter.text ? (
                <div className="rounded-lg border border-hairline bg-surface-2 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="mono text-[10px] text-aether-muted-dim">
                      {pack.coverLetter.characterCount} characters
                    </span>
                    <CopyButton value={pack.coverLetter.text} label="the cover letter" />
                  </div>
                  <p className="mt-2 whitespace-pre-wrap text-[12px] leading-relaxed text-aether-muted">
                    {pack.coverLetter.text}
                  </p>
                </div>
              ) : pack.coverLetter.absence ? (
                <Absence text={pack.coverLetter.absence} />
              ) : null}
            </Section>
          </>
        ) : null}
      </div>
    </div>
  );
}
