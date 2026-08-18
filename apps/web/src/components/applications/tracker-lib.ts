/**
 * Application Tracker — pure board logic (wireframe application-tracker.html).
 *
 * Everything here is side-effect free so the stage mapping, fit colouring,
 * relative timestamps and filter/sort behaviour are unit-testable without a
 * DOM (see __tests__/tracker-lib.test.ts).
 */
import type { Job } from "../../lib/api/jobs";
import { hasTransmissionProof } from "./submission-control-lib";
import type { TrackerApplication } from "./tracker-api";

/** Tracker metadata persisted in Application.answers (jsonb). */
export type TrackerMeta = {
  submittedAt?: string;
  appliedUrl?: string | null;
  followUpSentAt?: string;
  autoFollowUpInDays?: number;
  interviewRound?: number;
  interviewDate?: string;
  offerAmount?: string;
  offerDeadline?: string;
};

export type StageKey =
  | "discovered"
  | "evaluating"
  | "tailoring"
  | "ready"
  | "submitted"
  | "in-review"
  | "interview"
  | "offer";

type StageDef = {
  key: StageKey;
  label: string;
  /** Column-header status dot (literal class so Tailwind JIT picks it up). */
  dotClass: string;
  /** Card status icon + tinted circle, per wireframe card icons. */
  icon: string;
  iconClass: string;
};

/**
 * Canonical 8-stage pipeline, wireframe order (col-*-at09..at24). Colours are
 * on-brand DS semantics (UI-BRAND WB4 / RULINGS.md), not the legacy rainbow:
 *
 *   discovered / evaluating / tailoring — the agent-processing stages. All
 *     three are the scout/fit-scorer/tailor working rather than the user, but
 *     they are still three DIFFERENT columns, so each carries its own
 *     identity from CHART_PALETTE order (R6): sapphire-light #8FA8CE, then
 *     chart-sky #439FC8, then chart-rose #C16F7B. The old shared
 *     `aether-indigo` #3E5A8C dot was both indistinguishable across the three
 *     and only 2.8:1 on the board ground; every value here clears 4.5:1.
 *   ready (Ready to Apply) — the one column waiting on the USER: every card
 *     here is blocked on the user's own click-through (assisted channels) or
 *     a re-request after an expired approval. That is an action prompt, not a
 *     state, so it takes the gold action accent; `state-warn` copper is
 *     contractually "stalled / quota pressure" and is reserved for cards that
 *     genuinely are stalled.
 *   submitted / in-review / interview — the three "waiting on someone else"
 *     stages (employer response, then an interview slot) share `state-info`
 *     (#7C93BE): nothing is blocked or failing, Aether is just watching for a
 *     reply.
 *   offer — `state-ok` (#6FAF8D): the one unambiguous success state.
 *
 * (No stage here maps to rejected/failed — those live in the separate
 * "Closed" strip, not a board column.)
 */
export const STAGE_DEFS: readonly StageDef[] = [
  {
    key: "discovered",
    label: "Discovered",
    dotClass: "bg-aether-violet",
    icon: "fa-magnifying-glass",
    iconClass: "text-aether-violet bg-aether-violet/20",
  },
  {
    key: "evaluating",
    label: "Evaluating",
    dotClass: "bg-[#439FC8]",
    icon: "fa-scale-balanced",
    iconClass: "text-[#439FC8] bg-[#439FC8]/20",
  },
  {
    key: "tailoring",
    label: "Tailoring",
    dotClass: "bg-[#C16F7B]",
    icon: "fa-file-pen",
    iconClass: "text-[#C16F7B] bg-[#C16F7B]/20",
  },
  {
    key: "ready",
    label: "Ready to Apply",
    dotClass: "bg-gold",
    icon: "fa-clock",
    iconClass: "text-gold bg-gold/20",
  },
  {
    key: "submitted",
    label: "Submitted",
    dotClass: "bg-state-info",
    icon: "fa-check",
    iconClass: "text-state-info bg-state-info/20",
  },
  {
    key: "in-review",
    label: "In Review",
    dotClass: "bg-state-info",
    icon: "fa-eye",
    iconClass: "text-state-info bg-state-info/20",
  },
  {
    key: "interview",
    label: "Interview",
    dotClass: "bg-state-info",
    icon: "fa-comments",
    iconClass: "text-state-info bg-state-info/20",
  },
  {
    key: "offer",
    label: "Offer",
    dotClass: "bg-state-ok",
    icon: "fa-award",
    iconClass: "text-state-ok bg-state-ok/20",
  },
] as const;

/** Application.status → stage key (post-application half of the pipeline). */
export const APP_STAGE: Partial<Record<TrackerApplication["status"], StageKey>> = {
  draft: "ready",
  submitted: "submitted",
  screening: "in-review",
  interview: "interview",
  offer: "offer",
};

/** Job.status → stage key (agent pipeline half, pre-application). */
const JOB_STAGE: Record<string, StageKey> = {
  discovered: "discovered",
  screening: "evaluating",
  matched: "evaluating",
  tailoring: "tailoring",
};

// ---- FEAT-B2: stage moves ---------------------------------------------------

/** Stage key → Application.status write target (inverse of APP_STAGE). */
export const STAGE_TO_APP_STATUS: Partial<Record<StageKey, TrackerApplication["status"]>> = {
  ready: "draft",
  submitted: "submitted",
  "in-review": "screening",
  interview: "interview",
  offer: "offer",
};

/** Stage key → Job.status write target ("evaluating" canonically writes
 *  'screening'; the column also renders 'matched' jobs). */
export const STAGE_TO_JOB_STATUS: Partial<Record<StageKey, Job["status"]>> = {
  discovered: "discovered",
  evaluating: "screening",
  tailoring: "tailoring",
};

/** The 5 application-fed stage keys, board order. */
export const APP_STAGE_KEYS: readonly StageKey[] = [
  "ready",
  "submitted",
  "in-review",
  "interview",
  "offer",
];

/** The 3 job-fed stage keys, board order. */
export const JOB_STAGE_KEYS: readonly StageKey[] = ["discovered", "evaluating", "tailoring"];

/**
 * Legal move targets for a card (FEAT-B2): application cards move between the
 * 5 application-fed stages, pipeline job cards between the 3 job-fed stages —
 * the server enforces the same split with 422s. Excludes ``currentStage``.
 */
export function moveTargetsFor(card: StageCard, currentStage: StageKey): StageKey[] {
  const keys = card.app ? APP_STAGE_KEYS : JOB_STAGE_KEYS;
  return keys.filter((k) => k !== currentStage);
}

/** One card on the board — a live application or an agent-pipeline job. */
export type StageCard = {
  id: string;
  title: string;
  company: string;
  updatedAt: string;
  fit?: number;
  /** ATS score (distinct from `fit`/match score) — GOLD-MASTER-V2 §12.4. */
  atsScore?: number;
  app?: TrackerApplication;
  meta: TrackerMeta;
};

type Stage = StageDef & { cards: StageCard[] };

/** Company initials chip (wireframe card avatar). */
export function initials(company: string): string {
  const parts = company.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/** Fit score colour: green at/above the 85% auto-apply bar, amber below. */
export function fitClass(fit: number): string {
  return fit >= 85 ? "text-aether-green" : "text-aether-yellow";
}

/** Wireframe-style relative timestamp ("2 min ago", "3 h ago", "4 d ago"). */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const mins = Math.floor((now - then) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} d ago`;
  return new Date(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

/** Short "Jul 3" date for badges (interview round, offer deadline). */
export function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

// ---- U5 — honest submission-state labels -----------------------------------
//
// U-PLAN "U5 MANDATE SHARPENED": every approved application reaches either
// TRANSMITTED (email or web-form, evidence + timestamp/channel) or an HONEST
// ACTIONABLE manual-step state — never a silent "prepared only". These pure
// helpers turn the machine channel/reason codes the backend records
// (apps/api/app/services/apply_channel_resolver.py,
// apps/api/app/services/apply_executor.py `record_manual_step`) into the
// human copy the card/detail-panel UI renders, so that copy lives in one
// tested place instead of being duplicated inline in JSX.

/** Machine channel code → human label. Keys cover BOTH the
 *  `transmissionChannel` values `application_submission.py` stamps on a real
 *  send (`gmail`, the only value today) AND the `applyChannel` codes
 *  `apply_channel_resolver.py` `CHANNELS` resolves from a posting (`email`,
 *  `ashby`, ... `seek-manual`, `unknown`) — two different columns, so
 *  `gmail`/`email` are BOTH mapped here rather than assuming only one is ever
 *  seen (MED-9: a future writer stamping `transmissionChannel = "email"`
 *  must not fall through to the unrecognised-code branch). */
const CHANNEL_LABELS: Readonly<Record<string, string>> = {
  gmail: "email",
  email: "email",
  ashby: "Ashby application form",
  greenhouse: "Greenhouse application form",
  lever: "Lever application form",
  smartrecruiters: "SmartRecruiters application form",
  generic: "the employer's application form",
  "seek-manual": "Seek (not automated)",
  unknown: "an unresolved channel",
};

/** Human label for a transmission/apply channel code. Never fabricates a
 *  specific channel for a missing/unknown code — falls back to a neutral
 *  phrase (absent) or the raw code itself (unrecognised, so a future channel
 *  this UI hasn't been taught about is still legible, not silently hidden). */
export function channelLabel(channel: string | null | undefined): string {
  if (!channel) return "the employer";
  return CHANNEL_LABELS[channel] ?? channel;
}

/** Machine manual-step reason code → human headline
 *  (apps/api/app/services/apply_executor.py callers of `record_manual_step`). */
const MANUAL_STEP_LABELS: Readonly<Record<string, string>> = {
  unknown_required_question: "A required question needs your answer",
  captcha: "A CAPTCHA blocked automatic submission",
  login_wall: "This posting requires logging in to apply",
  no_automatable_channel: "No automatic submission path exists for this posting yet",
  submit_control_not_found: "Aether filled the form but could not find its submit button",
  no_confirmation: "Aether submitted the form but the site did not confirm it",
  // SUB-007: the two honest halves the single `no_confirmation` code used to
  // hide. They lead the user to different actions, so they get different
  // words — and neither of them ever reads as "applied".
  submitted_unconfirmed: "Submitted — but the site never confirmed it received it",
  form_rejected: "The site rejected the form — nothing was submitted",
  // SUB-007 round 2: a submit button that is present but GREYED OUT is not a
  // missing button. Saying "could not find its submit button" about a control
  // the user can see on the page reads as a bug in Aether rather than as the
  // form still holding something back — and sends them looking for the wrong
  // thing.
  submit_control_disabled: "The form's submit button was greyed out — nothing was submitted",
  submit_click_failed: "Aether found the submit button but the click did not land",
  // ORCHESTRATOR RULING U5-F3: an ASSISTED channel is not a failure — the
  // artifacts are done and only the click is the user's.
  assisted_manual_submit: "Ready to submit — this platform needs your click",
  // Stale-approval guard: the approval aged out, so the submission was NOT
  // driven. One click re-confirms it.
  approval_expired: "Approval expired — reconfirm to submit",
};

/** Human headline for a manual-step reason code. Unknown codes de-slugify
 *  rather than fall back to a vague generic label, so a reason this UI has
 *  not been taught about is still legible instead of hidden. */
export function manualStepLabel(reason: string | null | undefined): string {
  if (!reason) return "Manual step needed";
  return (
    MANUAL_STEP_LABELS[reason] ??
    reason.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}

/** Single-sourced manual-step tooltip title (MED-8: previously assembled
 *  inline, identically, at both the board badge and the "ready" card badge —
 *  free to drift). Quotes the employer's own verbatim detail when Aether
 *  recorded one; never invents one when it did not. */
export function manualStepTooltip(
  reason: string | null | undefined,
  detail?: string | null,
): string {
  const label = manualStepLabel(reason);
  return detail ? `${label}: "${detail}"` : label;
}

/** The facts `describeTransmission` needs — a structural subset of
 *  `TrackerApplication` so it stays usable from a bare `{app}`-shaped object
 *  in tests without importing the full schema type. */
export type TransmissionFacts = {
  transmittedTo?: string | null;
  transmittedAt?: string | null;
  transmissionChannel?: string | null;
  transmissionRef?: string | null;
};

export type TransmissionSummary = {
  /** One-line honest statement of what happened and when. */
  headline: string;
  /** Set ONLY when `transmissionRef` is an http(s) URL — a real clickable
   *  link. The site-apply path stores a server-side screenshot FILE PATH in
   *  the same column (apps/api/app/services/apply_executor.py
   *  `_record_site_transmission`), which is never rendered as a link: an
   *  unopenable `file://` or bare path would be a broken promise, not evidence. */
  evidenceUrl: string | null;
  /** Non-link evidence note for the cases `evidenceUrl` can't cover. */
  evidenceNote: string | null;
};

/**
 * Honest one-line summary of a TRANSMITTED application, channel-aware.
 *
 * `transmissionChannel`/`transmissionRef` are shared columns written by BOTH
 * transmission paths (apps/api/app/services/application_submission.py W-SUB
 * email send, and U5b's `_record_site_transmission` for a filled ATS form) —
 * `gmail` (or an absent channel, matching every pre-U5 row) means the email
 * path; anything else means a web-form submission on that channel.
 */
export function describeTransmission(app: TransmissionFacts): TransmissionSummary {
  const when = app.transmittedAt ? ` on ${shortDate(app.transmittedAt)}` : "";
  // MED-9: recognise BOTH `gmail` (the literal value
  // `application_submission.py` `CHANNEL_GMAIL` stamps today) and `email`
  // (the resolver's own code for the same channel) as the email path, so a
  // future writer using either value still renders truthfully instead of
  // falling into the web-form branch below and claiming a screenshot that
  // was never taken.
  const isEmail =
    !app.transmissionChannel ||
    app.transmissionChannel === "gmail" ||
    app.transmissionChannel === "email";
  const ref = app.transmissionRef ?? null;
  const looksLikeUrl = ref !== null && /^https?:\/\//i.test(ref);
  if (isEmail) {
    return {
      headline: `Sent by Aether to ${app.transmittedTo ?? "the employer"}${when}`,
      evidenceUrl: null,
      evidenceNote: ref ? `message ${ref} (in your Gmail Sent folder)` : null,
    };
  }
  return {
    headline: `Submitted by Aether via ${channelLabel(app.transmissionChannel)}${when}`,
    evidenceUrl: looksLikeUrl ? ref : null,
    // HIGH-5: the web-form path stores a SERVER-LOCAL file path in this
    // column (apps/api/app/services/apply_executor.py `_record_site_
    // transmission`, :1203/:1220) — there is no authenticated endpoint that
    // serves it to the browser yet, so saying only "saved by Aether" implied
    // evidence the user could open. State plainly that it exists but is not
    // viewable here, rather than imply a dead link.
    evidenceNote:
      !looksLikeUrl && ref
        ? "confirmation screenshot saved by Aether (not yet viewable in this app)"
        : null,
  };
}

/** Every channel the site-apply automation is allowed to drive a browser
 *  against (mirrors `apps/api/app/services/apply_channel_resolver.py`
 *  `AUTOMATABLE_CHANNELS` — kept as a literal copy, not an import, because
 *  this is a `next/server`-free pure FE module). The copy is PINNED against
 *  the backend set by `apps/api/tests/test_u5_invariant_sweep.py`
 *  (`test_the_frontend_mirror_of_the_allowlist_matches_the_backend`), which
 *  reads this file — so drift fails a test rather than silently changing what
 *  the UI promises. */
const FE_AUTOMATABLE_CHANNELS: ReadonlySet<string> = new Set(["ashby", "greenhouse"]);

/** Channels whose destination Aether resolved exactly and deliberately does
 *  NOT click through (ORCHESTRATOR RULING U5-F3): no dedicated form parser
 *  exists for them, and auto-submitting a real application on a best-effort
 *  schema is the worst failure this product can have. Aether still prepares
 *  the tailored résumé + cover letter; the user submits them. Pinned against
 *  the backend `ASSISTED_CHANNELS` by the same test. */
const FE_ASSISTED_CHANNELS: ReadonlySet<string> = new Set([
  "lever",
  "smartrecruiters",
  "generic",
]);

/** The PLATFORM's own name, for copy that addresses the user about where they
 *  must click — distinct from {@link channelLabel}, which names the artifact
 *  ("Lever application form"). Never invents a name for an unknown code. */
const PLATFORM_LABELS: Readonly<Record<string, string>> = {
  ashby: "Ashby",
  greenhouse: "Greenhouse",
  lever: "Lever",
  smartrecruiters: "SmartRecruiters",
  generic: "this employer's own form",
};

export function platformLabel(channel: string | null | undefined): string {
  if (!channel) return "this employer's own form";
  return PLATFORM_LABELS[channel] ?? channel;
}

/**
 * Single-sourced, honest reason an application has NOT been transmitted
 * (BLOCKER-2/BLOCKER-3/MED-8): reused verbatim by the board badge and the
 * detail-panel line so the two copies cannot drift, and differentiated by
 * `applyChannel` so the promise is never broader than what the code can
 * actually do.
 *
 * Never claims automatic submission "with no further action" — the ARQ sweep
 * that would drive a non-email channel is OFF by code default
 * (`apps/api/app/workers/apply_sweep.py` `sweep_enabled()`), so approving a
 * non-email application does not, by itself, cause anything to happen unless
 * an operator turned that sweep on; `sweepEnabled` below carries the live
 * answer rather than this comment asserting a deployment's `.env` state,
 * which would rot the moment it changed. Seek postings and unresolved
 * channels are excluded from automation even once the sweep runs
 * (ADR-SEEK-V3 / `AUTOMATABLE_CHANNELS`).
 */
export function notTransmittedReason(app: {
  autoSubmittable?: boolean | null;
  applyChannel?: string | null;
  /** SHOULD-FIX 6 (round-3 re-review): live read of the operator's
   *  ``AETHER_APPLY_SWEEP_ENABLED`` kill-switch (``GET
   *  /applications/apply-sweep-status``, backed by
   *  ``app.workers.apply_sweep.sweep_enabled()``). Defaults to `false` —
   *  the code default, and the honest choice while the caller's fetch of
   *  the live signal is still in flight — so a slow/failed status fetch can
   *  only ever under-promise, never claim automation that is not actually
   *  configured. */
  sweepEnabled?: boolean;
}): string {
  if (app.autoSubmittable) {
    // TRUE as written, and behaviourally pinned: approving this application's
    // request in Approvals fires POST /approvals/{id}/execute for it from all
    // three decision surfaces (card, modal, bulk) — see
    // `components/approvals/lib.ts` `sendsOnApprove`, asserted by
    // `app/dashboard/approvals/__tests__/u5-email-submission-send-and-retry.test.tsx`
    // — and the backend really transmits it (`_execute_application_submit`).
    // Round-4 MUST-FIX 1: before that wiring the UI executed `email_send`
    // approvals ONLY, so this sentence promised a send nothing performed.
    return "Approve it in Approvals to email it to the employer.";
  }
  if (app.applyChannel === "seek-manual") {
    return (
      "This is a Seek posting — Aether does not automate Seek applications " +
      "(policy). Apply on Seek yourself."
    );
  }
  if (app.applyChannel && FE_ASSISTED_CHANNELS.has(app.applyChannel)) {
    // ORCHESTRATOR RULING U5-F3: this posting's destination IS resolved, so
    // saying "Aether has not resolved where to submit it" would be false, and
    // saying "automatic submission … not enabled yet" would promise something
    // that is never coming for this platform (regardless of the sweep
    // kill-switch — assisted channels have no dedicated parser to drive).
    // State the true position: the work is done, the click is the user's.
    return (
      "Your tailored résumé and cover letter are ready to submit — " +
      `${platformLabel(app.applyChannel)} needs your click. Open the posting ` +
      "and submit them there."
    );
  }
  if (app.applyChannel && FE_AUTOMATABLE_CHANNELS.has(app.applyChannel)) {
    if (app.sweepEnabled) {
      return (
        "This posting publishes no application email address, but automatic " +
        `submission through ${channelLabel(app.applyChannel)} is enabled on ` +
        "this deployment — approve it in Approvals and Aether will submit it " +
        "for you on its next sweep."
      );
    }
    return (
      "This posting publishes no application email address. Automatic " +
      `submission through ${channelLabel(app.applyChannel)} is not enabled ` +
      "on this deployment yet — apply on the employer's site yourself."
    );
  }
  return (
    "This posting publishes no application email address, and Aether has not " +
    "resolved where to submit it. Apply on the employer's site yourself."
  );
}

/**
 * Generic (non-per-application) version of {@link notTransmittedReason} for
 * confirm dialogs that decide over a batch and have no single application's
 * channel to hand (approvals bulk-approve).
 *
 * MUST-FIX 3/5 (round-3 re-review): the previous copy told the user to "send
 * each email individually from each application's card" — there is NO send
 * affordance on an application's card; `executeApproval` is the only send in
 * the product, and it now fires for every bulk-approved item Aether can send
 * by email (C2 fixed `bulkDecide` to call it, matching a single-card approve
 * exactly). This describes THAT real behaviour instead of a UI surface that
 * does not exist, and reads the SAME live `sweepEnabled` signal
 * {@link notTransmittedReason} does for the employer-form half, so the two
 * copies can never again assert opposite things about the same deployment.
 *
 * Round-4 MUST-FIX 1/2: "email" here is the resolved apply CHANNEL, not the
 * approval type — an application whose posting publishes an application
 * address is sent by this same click (`components/approvals/lib.ts`
 * `sendsOnApprove`), which is what makes {@link notTransmittedReason}'s
 * "Approve it in Approvals to email it to the employer" true. The retry named
 * below is the real `Retry send` button the Approvals queue renders for an
 * approved-but-unsent request (`needsSendRetry`), not an imagined surface.
 */
export function automaticSubmissionDisclaimer(sweepEnabled: boolean): string {
  return (
    "Approving a request Aether can send by email — an outreach email, or an " +
    "application whose posting publishes an application address — sends it " +
    "immediately (each is sent individually, right after its own approval " +
    "goes through; a failed send is reported honestly and its request stays " +
    "in this queue with a Retry send button, never hidden). Automatic " +
    "employer-form submission " +
    (sweepEnabled
      ? "is enabled on this deployment and runs on Aether's own schedule " +
        "once approved."
      : "is not enabled on this deployment yet — apply on the employer's " +
        "site yourself for those.")
  );
}

// ---- SUB-006 — prepared is not submitted -----------------------------------

/**
 * The honest word for "the artifacts are ready, nothing was transmitted, the
 * click is still yours".
 *
 * GROUND TRUTH (production, 2026-08-16): all 5 `Application` rows carry
 * `status = 'submitted'` and ZERO carry a `transmittedAt`. Every one of those
 * cards sat under the word "Submitted" — five claims that a real job
 * application had been sent, with nothing in the database able to support a
 * single one of them.
 */
export const PREPARED_NOT_SENT_LABEL = "Prepared — needs your click";

/** The facts the prepared-vs-submitted derivation reads — a structural subset
 *  of `TrackerApplication`, so a bare row shape works without the full type. */
export type PreparedFacts = {
  status?: string | null;
  transmittedAt?: string | null;
};

/**
 * `true` when the row SAYS submitted but nothing proves a transmission.
 *
 * Two deliberate boundaries:
 *
 *  - Proof is `hasTransmissionProof`, IMPORTED rather than re-derived, so this
 *    label and the per-card submit control can never disagree about what
 *    counts as a send (the test pins the two against each other).
 *  - Only `submitted` is reinterpreted. `screening`/`interview`/`offer` are the
 *    USER telling us an application is already live somewhere — an employer
 *    replied — so calling those "prepared" would be its own false claim, in
 *    the opposite direction.
 *
 * The stored status is the user's own tracker history and is never rewritten;
 * what this changes is only the CLAIM the UI makes about it.
 */
export function isPreparedNotTransmitted(app: PreparedFacts | null | undefined): boolean {
  if (!app || app.status !== "submitted") return false;
  return !hasTransmissionProof({ transmittedAt: app.transmittedAt ?? null });
}

/**
 * The stage word a CARD is allowed to use, which is not always its column's.
 *
 * A column is a lane shared by many rows, so its header keeps the stage name;
 * an individual card in the Submitted lane with no transmission proof says the
 * true thing instead. Every other stage's word is returned untouched — this is
 * a correction of one specific over-claim, not a relabelling pass.
 */
export function stageLabelForCard(
  stage: StageKey,
  app?: PreparedFacts | null,
): string {
  const label = STAGE_DEFS.find((d) => d.key === stage)?.label ?? stage;
  if (stage === "submitted" && isPreparedNotTransmitted(app)) {
    return PREPARED_NOT_SENT_LABEL;
  }
  return label;
}

function metaOf(app: TrackerApplication): TrackerMeta {
  return (app.answers ?? {}) as TrackerMeta;
}

/** Assemble the 8 stage columns from live applications + pipeline jobs. */
export function buildStages(apps: TrackerApplication[], jobs: Job[]): Stage[] {
  const jobFit = new Map(
    jobs.filter((j) => j.fitScore != null).map((j) => [j.id, Math.round(Number(j.fitScore))]),
  );
  const jobAts = new Map(
    jobs.filter((j) => j.atsScore != null).map((j) => [j.id, Math.round(Number(j.atsScore))]),
  );
  const appJobIds = new Set(apps.map((a) => a.jobId));
  const stages: Stage[] = STAGE_DEFS.map((d) => ({ ...d, cards: [] }));
  const byKey = new Map(stages.map((s) => [s.key, s]));

  for (const j of jobs) {
    const key = JOB_STAGE[j.status];
    if (key && !appJobIds.has(j.id)) {
      byKey.get(key)!.cards.push({
        id: `job-${j.id}`,
        title: j.title,
        company: j.company,
        updatedAt: j.updatedAt ?? j.createdAt ?? "",
        fit: j.fitScore != null ? Math.round(Number(j.fitScore)) : undefined,
        atsScore: j.atsScore != null ? Math.round(Number(j.atsScore)) : undefined,
        meta: {},
      });
    }
  }
  for (const a of apps) {
    const key = APP_STAGE[a.status];
    if (key) {
      byKey.get(key)!.cards.push({
        id: a.id,
        title: a.jobTitle,
        company: a.company,
        updatedAt: a.updatedAt,
        fit: a.fitScore != null ? Math.round(Number(a.fitScore)) : jobFit.get(a.jobId),
        atsScore:
          a.atsScore != null ? Math.round(Number(a.atsScore)) : jobAts.get(a.jobId),
        app: a,
        meta: metaOf(a),
      });
    }
  }
  return stages;
}

// ---- Filter / Sort (btn-filter-at06 / btn-sort-at07) -----------------------

export type FilterKey =
  | "all"
  | "high-fit"
  | "below-fit"
  | "needs-approval"
  | "needs-your-click";
export type SortKey = "recent" | "fit" | "company";

/**
 * SUB-010 — the filter label for the population whose last step is the user's
 * own click: everything is prepared, nothing was transmitted.
 *
 * The wording is the SUB-006 wording minus the state half ("Prepared — needs
 * your click"), because a filter names an action to take rather than a state
 * to read. It says nothing about applying, submitting or sending, which is the
 * whole point: these are exactly the rows where none of those happened.
 */
export const NEEDS_YOUR_CLICK_LABEL = "Needs your click";

export const FILTER_OPTIONS: ReadonlyArray<{ key: FilterKey; label: string }> = [
  { key: "all", label: "All applications" },
  { key: "high-fit", label: "Match ≥ 85" },
  { key: "below-fit", label: "Match < 85" },
  { key: "needs-approval", label: "Needs approval" },
  { key: "needs-your-click", label: NEEDS_YOUR_CLICK_LABEL },
] as const;

export const SORT_OPTIONS: ReadonlyArray<{ key: SortKey; label: string }> = [
  { key: "recent", label: "Latest activity" },
  { key: "fit", label: "Match score" },
  { key: "company", label: "Company A–Z" },
] as const;

/**
 * Application ids with a live, pending ApprovalRequest — the same set the
 * pending-approvals banner counts (GET /approvals?status=pending). Passed
 * into the "needs-approval" filter so both signals on this screen always
 * describe the SAME underlying set (MV-application-tracker-002): a
 * status==='draft' heuristic could disagree with the banner whenever a
 * draft Application had no linked approval request (or vice versa).
 */
type PendingApprovalIds = ReadonlySet<string>;

export function cardMatchesFilter(
  card: StageCard,
  filter: FilterKey,
  pendingApprovalIds: PendingApprovalIds = new Set(),
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "high-fit":
      return card.fit != null && card.fit >= 85;
    case "below-fit":
      return card.fit != null && card.fit < 85;
    case "needs-approval":
      return card.app != null && pendingApprovalIds.has(card.app.id);
    case "needs-your-click":
      // SUB-010 clause 2. `isPreparedNotTransmitted` is the SUB-006 predicate
      // ITSELF, not a copy of its rule: the filter and the card badge must
      // never be able to disagree about which rows are still waiting on the
      // user. A card with no application behind it (a discovered job) has
      // nothing prepared, so it is never in this set.
      return card.app != null && isPreparedNotTransmitted(card.app);
    default:
      return true;
  }
}

export function sortCards(cards: StageCard[], sort: SortKey): StageCard[] {
  const copy = [...cards];
  switch (sort) {
    case "fit":
      copy.sort((a, b) => (b.fit ?? -1) - (a.fit ?? -1));
      break;
    case "company":
      copy.sort((a, b) => a.company.localeCompare(b.company));
      break;
    case "recent":
    default:
      copy.sort(
        (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
      );
      break;
  }
  return copy;
}

/** Apply the active filter + sort to every stage (pure). */
export function viewStages(
  stages: Stage[],
  filter: FilterKey,
  sort: SortKey,
  pendingApprovalIds: PendingApprovalIds = new Set(),
): Stage[] {
  return stages.map((s) => ({
    ...s,
    cards: sortCards(
      s.cards.filter((c) => cardMatchesFilter(c, filter, pendingApprovalIds)),
      sort,
    ),
  }));
}
