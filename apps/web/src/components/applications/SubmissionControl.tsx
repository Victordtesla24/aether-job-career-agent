"use client";

/**
 * U5d-2 — the per-card submit control on `/dashboard/applications`.
 *
 * ONE control per application card, and what it offers is decided by the
 * posting's real apply channel plus the row's real state (see
 * `apps/api/app/services/submission_control.py`, whose `submissionControl`
 * block this renders). It never invents a state, and it reaches "Submitted ✓"
 * only on a re-read `transmittedAt` — see `submission-control-lib.ts`.
 *
 * The eight card states, and what each one looks like here:
 *
 *   draft                    — the gate artifacts are missing; the control says
 *                              WHICH one and links to where it is fixed.
 *   ready                    — "Submit application" (Ashby/Greenhouse) or
 *                              "Send application email" (a published address).
 *                              Pressing it IS the approval for this application.
 *   submitting               — this browser's own in-flight request. Live, from
 *                              the real request's lifetime, never a timer.
 *   submitted                — proof-bound. `transmittedAt` is set.
 *   needs_your_click         — ASSISTED platform / Seek: everything is prepared,
 *                              and the direct posting URL is handed over.
 *   manual_step              — a real obstacle the engine refuses to guess past
 *                              (CAPTCHA, login wall, an unanswerable question).
 *   expired_reconfirm        — the approval aged out; one click re-arms it.
 *   failed                   — an honest reason, from the real error.
 */
import Link from "next/link";
import { useCallback, useState } from "react";

import type { Application, SubmissionControl } from "../../lib/api/applications";
import {
  cardStateFor,
  isPressable,
  runCardSubmission,
  type CardSubmissionDeps,
  type CardSubmissionOutcome,
  type LocalSubmissionState,
} from "./submission-control-lib";

const TONE: Record<string, string> = {
  submitted: "border-aether-green/40 text-aether-green",
  ready: "border-[#818CF8]/50 text-[#818CF8]",
  submitting: "border-[#818CF8]/50 text-[#818CF8]",
  needs_your_click: "border-aether-yellow/40 text-aether-yellow",
  manual_step: "border-aether-coral/40 text-aether-coral",
  expired_reconfirm: "border-aether-coral/40 text-aether-coral",
  failed: "border-aether-coral/40 text-aether-coral",
  draft: "border-white/15 text-aether-muted",
  recorded_not_transmitted: "border-white/15 text-aether-muted",
};

export default function SubmissionControl({
  application,
  onReconfirm,
  onSettled,
  deps,
}: {
  application: Pick<
    Application,
    "id" | "submissionControl" | "transmittedAt" | "transmissionRef"
  >;
  /** Existing U5 one-click path for an aged-out approval. */
  onReconfirm?: () => void;
  /** Called with the real outcome so the board can refresh from the server. */
  onSettled?: (outcome: CardSubmissionOutcome) => void;
  /** Injected transport (tests). Production uses the real API clients. */
  deps?: CardSubmissionDeps;
}) {
  const control: SubmissionControl | null = application.submissionControl ?? null;
  const [local, setLocal] = useState<LocalSubmissionState>("idle");
  const [liveDetail, setLiveDetail] = useState<string | null>(null);

  const submit = useCallback(async () => {
    setLocal("submitting");
    setLiveDetail(null);
    const outcome = await runCardSubmission(application.id, deps);
    if (outcome.kind === "transmitted") {
      // Deliberately NOT set to a local "submitted": the card's submitted
      // state comes from the refreshed row's own `submissionControl`, so the
      // only thing that can paint success is the server reading back proof.
      setLocal("idle");
    } else if (outcome.kind === "manual_step") {
      setLocal("idle");
      setLiveDetail(outcome.detail);
    } else {
      setLocal("failed");
      setLiveDetail(outcome.detail);
    }
    onSettled?.(outcome);
  }, [application.id, deps, onSettled]);

  if (!control) return null;
  const state = cardStateFor(control, local);
  const tone = TONE[state] ?? TONE.draft;
  const detail = liveDetail ?? control.detail;

  if (state === "submitting") {
    return (
      <div
        data-testid="submission-control"
        data-state="submitting"
        className={`mt-2 flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] ${tone}`}
      >
        <i className="fa-solid fa-circle-notch fa-spin text-[9px]" aria-hidden="true" />
        <span>Submitting — nothing is claimed until the employer’s form confirms.</span>
      </div>
    );
  }

  if (state === "failed") {
    return (
      <div
        data-testid="submission-control"
        data-state="failed"
        className={`mt-2 rounded-md border px-2 py-1 text-[10px] ${tone}`}
      >
        <p data-testid="submission-control-detail">{detail}</p>
        <button
          type="button"
          data-testid="submission-control-retry"
          onClick={(e) => {
            e.stopPropagation();
            void submit();
          }}
          className="mt-1 rounded border border-white/15 px-2 py-0.5 text-[10px] text-aether-muted transition hover:border-white/30 hover:text-white"
        >
          Try again
        </button>
      </div>
    );
  }

  if (state === "submitted") {
    return (
      <div
        data-testid="submission-control"
        data-state="submitted"
        title={detail}
        className={`mt-2 inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[10px] ${tone}`}
      >
        <i className="fa-solid fa-circle-check text-[9px]" aria-hidden="true" />
        <span data-testid="submission-control-label">{control.label}</span>
      </div>
    );
  }

  const body = (() => {
    switch (control.action) {
      case "submit":
      case "send_email":
        return (
          <button
            type="button"
            data-testid="submission-control-button"
            onClick={(e) => {
              e.stopPropagation();
              void submit();
            }}
            className={`rounded-md border px-2 py-0.5 text-[10px] transition hover:text-white ${tone}`}
          >
            {control.label}
          </button>
        );
      case "open_posting":
        return control.applyUrl ? (
          <a
            data-testid="submission-control-link"
            href={control.applyUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] transition hover:text-white ${tone}`}
          >
            {control.label}
            <i className="fa-solid fa-arrow-up-right-from-square text-[8px]" aria-hidden="true" />
          </a>
        ) : (
          <span data-testid="submission-control-label" className="text-[10px] text-aether-muted">
            {control.label}
          </span>
        );
      case "reconfirm":
        return (
          <button
            type="button"
            data-testid="submission-control-reconfirm"
            onClick={(e) => {
              e.stopPropagation();
              onReconfirm?.();
            }}
            className={`rounded-md border px-2 py-0.5 text-[10px] transition hover:text-white ${tone}`}
          >
            {control.label}
          </button>
        );
      case "fix_artifacts":
        return control.href ? (
          <Link
            data-testid="submission-control-fix"
            href={control.href}
            onClick={(e) => e.stopPropagation()}
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] transition hover:text-white ${tone}`}
          >
            {control.label}
            <i className="fa-solid fa-arrow-right text-[8px]" aria-hidden="true" />
          </Link>
        ) : (
          <span data-testid="submission-control-label" className="text-[10px] text-aether-muted">
            {control.label}
          </span>
        );
      default:
        return (
          <span
            data-testid="submission-control-label"
            className={`inline-block rounded-md border px-2 py-0.5 text-[10px] ${tone}`}
          >
            {control.label}
          </span>
        );
    }
  })();

  return (
    <div
      data-testid="submission-control"
      data-state={state}
      data-action={control.action}
      data-channel={control.channel}
      title={detail}
      className="mt-2 flex flex-wrap items-center gap-1.5"
    >
      {body}
      {isPressable(control) ? null : (
        <span className="sr-only" data-testid="submission-control-detail">
          {detail}
        </span>
      )}
    </div>
  );
}
