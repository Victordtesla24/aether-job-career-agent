/**
 * Application Tracker — pure board logic (wireframe application-tracker.html).
 *
 * Everything here is side-effect free so the stage mapping, fit colouring,
 * relative timestamps and filter/sort behaviour are unit-testable without a
 * DOM (see __tests__/tracker-lib.test.ts).
 */
import type { Job } from "../../lib/api/jobs";
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

/** Canonical 8-stage pipeline, wireframe order and colours (col-*-at09..at24). */
export const STAGE_DEFS: readonly StageDef[] = [
  {
    key: "discovered",
    label: "Discovered",
    dotClass: "bg-[#4F46E5]",
    icon: "fa-magnifying-glass",
    iconClass: "text-[#818CF8] bg-[#4F46E5]/20",
  },
  {
    key: "evaluating",
    label: "Evaluating",
    dotClass: "bg-[#818CF8]",
    icon: "fa-scale-balanced",
    iconClass: "text-[#818CF8] bg-[#818CF8]/20",
  },
  {
    key: "tailoring",
    label: "Tailoring",
    dotClass: "bg-[#FF6B35]",
    icon: "fa-file-pen",
    iconClass: "text-[#FF6B35] bg-[#FF6B35]/20",
  },
  {
    key: "ready",
    label: "Ready to Apply",
    dotClass: "bg-[#F59E0B]",
    icon: "fa-clock",
    iconClass: "text-[#F59E0B] bg-[#F59E0B]/20",
  },
  {
    key: "submitted",
    label: "Submitted",
    dotClass: "bg-[#60A5FA]",
    icon: "fa-check",
    iconClass: "text-[#60A5FA] bg-[#60A5FA]/20",
  },
  {
    key: "in-review",
    label: "In Review",
    dotClass: "bg-[#A78BFA]",
    icon: "fa-eye",
    iconClass: "text-[#A78BFA] bg-[#A78BFA]/20",
  },
  {
    key: "interview",
    label: "Interview",
    dotClass: "bg-[#F59E0B]",
    icon: "fa-comments",
    iconClass: "text-[#F59E0B] bg-[#F59E0B]/20",
  },
  {
    key: "offer",
    label: "Offer",
    dotClass: "bg-[#34D399]",
    icon: "fa-award",
    iconClass: "text-[#34D399] bg-[#34D399]/20",
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
 * (`apps/api/app/workers/apply_sweep.py` `sweep_enabled()`) and
 * `AETHER_APPLY_SWEEP_ENABLED` is unset in this deployment's `.env` today, so
 * approving a non-email application does not, by itself, cause anything to
 * happen. Seek postings and unresolved channels are excluded from automation
 * even once the sweep runs (ADR-SEEK-V3 / `AUTOMATABLE_CHANNELS`).
 */
export function notTransmittedReason(app: {
  autoSubmittable?: boolean | null;
  applyChannel?: string | null;
}): string {
  if (app.autoSubmittable) {
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
    // that is never coming for this platform. State the true position: the
    // work is done, the click is the user's.
    return (
      "Your tailored résumé and cover letter are ready to submit — " +
      `${platformLabel(app.applyChannel)} needs your click. Open the posting ` +
      "and submit them there."
    );
  }
  if (app.applyChannel && FE_AUTOMATABLE_CHANNELS.has(app.applyChannel)) {
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

/** Generic (non-per-application) version of {@link notTransmittedReason} for
 *  confirm dialogs that decide over a batch and have no single application's
 *  channel to hand (approvals bulk-approve). Kept as ONE string so it cannot
 *  say something the per-application copy above contradicts. */
export const AUTOMATIC_SUBMISSION_DISCLAIMER =
  "Approving does not send anything automatically: emails must be sent " +
  "individually from each application's card, and automatic employer-form " +
  "submission is not enabled on this deployment yet.";

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

export type FilterKey = "all" | "high-fit" | "below-fit" | "needs-approval";
export type SortKey = "recent" | "fit" | "company";

export const FILTER_OPTIONS: ReadonlyArray<{ key: FilterKey; label: string }> = [
  { key: "all", label: "All applications" },
  { key: "high-fit", label: "Match ≥ 85" },
  { key: "below-fit", label: "Match < 85" },
  { key: "needs-approval", label: "Needs approval" },
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
