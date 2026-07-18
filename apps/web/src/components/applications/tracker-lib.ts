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

export type StageDef = {
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
export const JOB_STAGE: Record<string, StageKey> = {
  discovered: "discovered",
  screening: "evaluating",
  matched: "evaluating",
  tailoring: "tailoring",
};

/** One card on the board — a live application or an agent-pipeline job. */
export type StageCard = {
  id: string;
  title: string;
  company: string;
  updatedAt: string;
  fit?: number;
  app?: TrackerApplication;
  meta: TrackerMeta;
};

export type Stage = StageDef & { cards: StageCard[] };

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
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function metaOf(app: TrackerApplication): TrackerMeta {
  return (app.answers ?? {}) as TrackerMeta;
}

/** Assemble the 8 stage columns from live applications + pipeline jobs. */
export function buildStages(apps: TrackerApplication[], jobs: Job[]): Stage[] {
  const jobFit = new Map(
    jobs.filter((j) => j.fitScore != null).map((j) => [j.id, Math.round(Number(j.fitScore))]),
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
export type PendingApprovalIds = ReadonlySet<string>;

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
