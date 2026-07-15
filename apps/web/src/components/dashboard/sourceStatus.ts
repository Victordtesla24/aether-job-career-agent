/**
 * Pure helpers for the Jobs page per-source Sync Status panel (GAP-SRC-003).
 * Maps GET /agents/scout/sources rows to a badge-ready view model. Honest
 * states only: a source that errored never renders as "ok", and a source
 * with zero new jobs still shows its real "ok" status (never blank/hidden).
 */
import type { ScoutSourceStatus } from "../../lib/api/jobs";
import { relTime } from "./feed";

export type SourceBadge = "ok" | "error" | "neutral";

export interface SourceStatusView {
  source: string;
  /** Jobs persisted from this source in its most recent sync run. */
  count: number;
  badge: SourceBadge;
  /** Short pill text, e.g. "ok, 3 new", "error", or a raw status like "skipped". */
  badgeLabel: string;
  /** Relative last-sync time, or "never synced" when no run has recorded one. */
  lastSyncLabel: string;
  /** Populated iff the source's last run failed — the real backend error, never fabricated. */
  errorText: string | null;
}

/** Map raw per-source status rows to the view model the Sync Status panel renders. */
export function sourceStatusView(
  rows: ScoutSourceStatus[],
  now: Date = new Date(),
): SourceStatusView[] {
  return rows.map((row) => {
    const count = row.lastPersisted;
    const isError = row.status === "error";
    const isOk = row.status === "ok";
    const badge: SourceBadge = isError ? "error" : isOk ? "ok" : "neutral";
    const badgeLabel = isError ? "error" : isOk ? `ok, ${count} new` : row.status;
    const errorText = isError
      ? row.lastError && row.lastError.trim().length > 0
        ? row.lastError
        : "Sync failed"
      : null;
    return {
      source: row.source,
      count,
      badge,
      badgeLabel,
      lastSyncLabel: row.lastSyncAt ? relTime(row.lastSyncAt, now) : "never synced",
      errorText,
    };
  });
}
