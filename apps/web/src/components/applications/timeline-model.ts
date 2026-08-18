/**
 * Application Timeline — pure model (SESSION TL-VIZ).
 *
 * Layout + honesty live here so the DOM and optional WebGL overlay share one
 * source of truth. The GL layer must never invent a fact this module does not
 * already expose.
 */
import type { TrackerApplication } from "./tracker-api";
import {
  cardMatchesFilter,
  sortCards,
  type FilterKey,
  type SortKey,
  type StageCard,
} from "./tracker-lib";

/** Provenance marker from apps/api/.../application_status_event.py */
export const BACKFILL_SOURCE = "backfill:current-status";

/** Visible copy on genesis (backfill) nodes — never invent prior stages. */
export const GENESIS_NOTE = "Earlier transitions were not observed.";

/**
 * Status → node colour. Gilt is the ready/draft ACTION accent only — never a
 * success/warn/danger state. Coral/indigo are forbidden.
 */
export const STATUS_NODE_COLOR = {
  draft: "#C9A84C",
  submitted: "#7C93BE",
  screening: "#7C93BE",
  interview: "#7C93BE",
  offer: "#6FAF8D",
  rejected: "#B9544B",
  withdrawn: "#8C8A82",
} as const;

export type ApplicationStatusKey = keyof typeof STATUS_NODE_COLOR;

export type TimelineEvent = {
  id: string;
  applicationId: string;
  fromStatus: string | null;
  toStatus: string;
  at: string;
  source: string;
};

export type TimelineItem = {
  application: TrackerApplication;
  events: TimelineEvent[];
};

export type TimelinePayload = {
  items: TimelineItem[];
  range: { start: string | null; end: string | null };
};

export type TimelineNode = {
  id: string;
  applicationId: string;
  fromStatus: string | null;
  toStatus: string;
  at: string;
  source: string;
  /** 0..1 along the observed time range. */
  x: number;
  color: string;
  genesis: boolean;
  note: string | null;
  label: string;
};

export type TimelineLane = {
  applicationId: string;
  jobTitle: string;
  company: string;
  status: TrackerApplication["status"];
  application: TrackerApplication;
  nodes: TimelineNode[];
};

export type TimelineModel = {
  lanes: TimelineLane[];
  range: { start: string | null; end: string | null };
  empty: boolean;
  axisTicks: Array<{ x: number; label: string; at: string }>;
};

function statusColor(status: string): string {
  if (status in STATUS_NODE_COLOR) {
    return STATUS_NODE_COLOR[status as ApplicationStatusKey];
  }
  return "#8C8A82";
}

function statusLabel(status: string): string {
  switch (status) {
    case "draft":
      return "Ready to apply";
    case "submitted":
      return "Submitted";
    case "screening":
      return "In review";
    case "interview":
      return "Interview";
    case "offer":
      return "Offer";
    case "rejected":
      return "Rejected";
    case "withdrawn":
      return "Withdrawn";
    default:
      return status;
  }
}

function toMs(iso: string): number {
  const t = new Date(iso).getTime();
  return Number.isFinite(t) ? t : 0;
}

function formatTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

function asCard(application: TrackerApplication): StageCard {
  return {
    id: application.id,
    title: application.jobTitle,
    company: application.company,
    updatedAt: application.updatedAt,
    fit: application.fitScore ?? undefined,
    atsScore: application.atsScore ?? undefined,
    app: application,
    meta: {},
  };
}

export type TimelineViewOptions = {
  filter?: FilterKey;
  sort?: SortKey;
  pendingApprovalIds?: ReadonlySet<string>;
};

/**
 * Build the timeline model from a verified API payload.
 *
 * Empty range stays null — callers must not paint a fake "today" axis.
 */
export function buildTimelineModel(
  payload: TimelinePayload,
  options: TimelineViewOptions = {},
): TimelineModel {
  const filter = options.filter ?? "all";
  const sort = options.sort ?? "recent";
  const pending = options.pendingApprovalIds ?? new Set<string>();

  const cards = payload.items.map((item) => asCard(item.application));
  const visibleIds = new Set(
    sortCards(
      cards.filter((c) => cardMatchesFilter(c, filter, pending)),
      sort,
    ).map((c) => c.id),
  );

  const startMs =
    payload.range.start != null ? toMs(payload.range.start) : null;
  const endMs = payload.range.end != null ? toMs(payload.range.end) : null;
  const span =
    startMs != null && endMs != null && endMs > startMs ? endMs - startMs : 0;

  const lanes: TimelineLane[] = [];
  for (const item of payload.items) {
    if (!visibleIds.has(item.application.id)) continue;
    const nodes: TimelineNode[] = item.events.map((ev) => {
      const t = toMs(ev.at);
      const x =
        startMs == null || span <= 0
          ? 0.5
          : Math.min(1, Math.max(0, (t - startMs) / span));
      const genesis =
        ev.fromStatus == null && ev.source === BACKFILL_SOURCE;
      return {
        id: ev.id,
        applicationId: ev.applicationId,
        fromStatus: ev.fromStatus,
        toStatus: ev.toStatus,
        at: ev.at,
        source: ev.source,
        x,
        color: statusColor(ev.toStatus),
        genesis,
        note: genesis ? GENESIS_NOTE : null,
        label: statusLabel(ev.toStatus),
      };
    });
    lanes.push({
      applicationId: item.application.id,
      jobTitle: item.application.jobTitle,
      company: item.application.company,
      status: item.application.status,
      application: item.application,
      nodes,
    });
  }

  // Preserve sort order from sortCards.
  const order = [...visibleIds];
  lanes.sort(
    (a, b) => order.indexOf(a.applicationId) - order.indexOf(b.applicationId),
  );

  const axisTicks: TimelineModel["axisTicks"] = [];
  if (payload.range.start && payload.range.end && span > 0) {
    const mid = new Date(startMs! + span / 2).toISOString();
    axisTicks.push(
      { x: 0, label: formatTick(payload.range.start), at: payload.range.start },
      { x: 0.5, label: formatTick(mid), at: mid },
      { x: 1, label: formatTick(payload.range.end), at: payload.range.end },
    );
  }

  return {
    lanes,
    range: {
      start: payload.range.start,
      end: payload.range.end,
    },
    empty: lanes.length === 0,
    axisTicks,
  };
}
