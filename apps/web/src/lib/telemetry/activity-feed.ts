/**
 * S-UI-REBUILD §3.2 — the event→visual MAPPING LAW, as pure functions.
 *
 * `GET /events/stream` carries **no record contents and never names a business
 * event** (§3.1(a); `apps/api/app/services/workspace_event_stream.py`'s module
 * docstring says so explicitly, citing ADR-GMV4-003). What it proves is narrow:
 * *the rows behind a screen moved, and — sometimes — by how many.*
 *
 * Law T-1: nothing in the telemetry layer may render a fact that is not in
 * §3.2's left column. Everything richer ("Cover letter drafted for Nearmap")
 * requires the backend to persist and emit it, which is a different
 * workstream — never a guess here.
 *
 * This module is deliberately pure and clock-free: the caller supplies
 * `observedAt`, so a row's timestamp is always the instant the store recorded
 * the observation, never the instant a component happened to re-render.
 */
import type { RealtimeResource, ResourceChange } from "../realtime/transport-types";

/** How a row reads. `gap` is NOT a variant of neutral: it means we were not
 *  watching when it happened, and §3.2 forbids presenting it as live. */
export type ActivityTone = "increase" | "decrease" | "neutral" | "gap";

export interface ActivityRow {
  /** Stable within a session; the store may report the same resource twice. */
  id: string;
  resource: RealtimeResource;
  /** Verbatim copy. Exactly what the wire proves — no more. */
  text: string;
  /** The EXACT signed count delta, or `null` when the wire proves no count
   *  change (or gives no prior observation to subtract from). Never inferred. */
  delta: number | null;
  tone: ActivityTone;
  /** Epoch ms, supplied by the caller from the store's own observation. */
  observedAt: number;
  /** The screen that can show what actually changed, after it refetches. */
  href: string;
}

/**
 * Per-resource copy.
 *
 * `one`/`many` name the THING COUNTED — which is not always the thing the key
 * is named after. `updated` is the numberless form used whenever the evidence
 * is a watermark move rather than a count change.
 */
interface ResourceCopy {
  one: string;
  many: string;
  updated: string;
  /** Gap copy uses a lowercase plural inside a sentence. */
  gapNoun: string;
  href: string;
}

const COPY: Record<RealtimeResource, ResourceCopy> = {
  jobs: { one: "job", many: "jobs", updated: "Jobs updated", gapNoun: "jobs", href: "/dashboard/jobs" },
  applications: {
    one: "application",
    many: "applications",
    updated: "Applications updated",
    gapNoun: "applications",
    href: "/dashboard/applications",
  },
  /**
   * SUPERSET WARNING (§3.1(a)). `coverLetters` watches **Application rows that
   * HAVE a cover letter**, so an unrelated stage move fires it. A count
   * increase therefore proves "one more application now has a cover letter" —
   * it does NOT prove a cover letter was just written, and the spec forbids
   * saying so. The noun is the application, deliberately.
   */
  coverLetters: {
    one: "application has a cover letter",
    many: "applications have a cover letter",
    updated: "Cover letters updated",
    gapNoun: "cover letters",
    href: "/dashboard/cover-letters",
  },
  resumes: {
    one: "résumé",
    many: "résumés",
    updated: "Résumés updated",
    gapNoun: "résumés",
    href: "/dashboard/resume",
  },
  stories: {
    one: "story",
    many: "stories",
    updated: "Stories updated",
    gapNoun: "stories",
    href: "/dashboard/stories",
  },
  emails: { one: "email", many: "emails", updated: "Emails updated", gapNoun: "emails", href: "/dashboard/email" },
  contacts: {
    one: "contact",
    many: "contacts",
    updated: "Contacts updated",
    gapNoun: "contacts",
    href: "/dashboard/networking",
  },
  outreach: {
    one: "outreach message",
    many: "outreach messages",
    updated: "Outreach updated",
    gapNoun: "outreach",
    href: "/dashboard/networking",
  },
  interviews: {
    one: "interview",
    many: "interviews",
    updated: "Interviews updated",
    gapNoun: "interviews",
    href: "/dashboard/interviews",
  },
  offers: { one: "offer", many: "offers", updated: "Offers updated", gapNoun: "offers", href: "/dashboard/offers" },
  approvals: {
    one: "approval request",
    many: "approval requests",
    updated: "Approval queue updated",
    gapNoun: "approval requests",
    href: "/dashboard/approvals",
  },
  agentRuns: {
    one: "agent run",
    many: "agent runs",
    updated: "Agent runs updated",
    gapNoun: "agent runs",
    href: "/dashboard/agents",
  },
};

/** The screen that owns a resource — where a click can show the real records. */
export function resourceHref(resource: RealtimeResource): string {
  return COPY[resource].href;
}

/**
 * §3.2, row by row. The `coverLetters` phrasing above is why the increase and
 * decrease branches build their sentence from `one`/`many` rather than
 * hard-coding "new" + noun: for that key the noun already contains its verb.
 */
export function describeResourceChange(change: ResourceChange, observedAt: number): ActivityRow {
  const copy = COPY[change.resource];
  const base = {
    id: `${change.resource}-${observedAt}-${change.count}`,
    resource: change.resource,
    observedAt,
    href: copy.href,
  };

  // Row 4 — the store diffed two server snapshots across a disconnect. Both
  // sides are real observations, but we did not watch it happen, so it may
  // carry no delta and no timestamp implying we did.
  if (change.reason === "reconnect_gap") {
    return { ...base, text: `While reconnecting: ${copy.gapNoun} changed`, delta: null, tone: "gap" };
  }

  // Row 3 — a watermark move proves a row CHANGED, not that one was ADDED.
  // Any number here would be a claim the server did not make.
  const delta =
    change.reason === "count_changed" && change.previousCount !== null
      ? change.count - change.previousCount
      : 0;

  if (delta === 0) {
    return { ...base, text: copy.updated, delta: null, tone: "neutral" };
  }

  // Rows 1 and 2 — the delta is exact, and its direction is stated in words as
  // well as tone (C-5: colour is never the only signal).
  const magnitude = Math.abs(delta);
  const noun = magnitude === 1 ? copy.one : copy.many;

  if (delta > 0) {
    const text =
      change.resource === "coverLetters"
        ? `${magnitude} more ${noun}`
        : `${magnitude} new ${noun}`;
    return { ...base, text, delta, tone: "increase" };
  }

  const text =
    change.resource === "coverLetters"
      ? `${magnitude} fewer ${noun}`
      : `${magnitude} ${noun} removed`;
  return { ...base, text, delta, tone: "decrease" };
}

/** Rows kept in memory by `useActivityFeed` (§3.4 T-A). Nothing is persisted. */
export const ACTIVITY_FEED_CAPACITY = 30;
