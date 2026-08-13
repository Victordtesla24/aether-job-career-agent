/**
 * Pure helpers for the Jobs page per-source Sync Status panel (GAP-SRC-003).
 * Maps GET /agents/scout/sources rows to a badge-ready view model. Honest
 * states only: a source that errored never renders as "ok", and a source
 * with zero new jobs still shows its real "ok" status (never blank/hidden).
 */
import type { ScoutSourceStatus } from "../../lib/api/jobs";
import { relTime } from "./feed";

type SourceBadge = "ok" | "error" | "neutral";

interface SourceStatusView {
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

/**
 * QA H-08: translate a raw adapter exception string (e.g.
 * "AdapterFetchError: Wellfound public listings unavailable: HTTP Error 404:
 * Not Found") into calm, user-readable prose. The mapping never fabricates a
 * cause: it strips the exception-class prefix and normalises the HTTP-error
 * tail; anything it does not recognise passes through verbatim.
 */
export function humanizeSourceError(raw: string): string {
  let text = raw.trim();
  // Strip a leading Python/JS exception class prefix ("AdapterFetchError: ").
  text = text.replace(/^[A-Za-z_]*(Error|Exception)\s*:\s*/, "");
  // "HTTP Error 404: Not Found" → "the source returned HTTP 404".
  text = text.replace(
    /HTTP Error (\d{3})(?::\s*[A-Za-z ]+)?/,
    (_m, code) => `the source returned HTTP ${code}`,
  );
  if (!text) return "Sync failed";
  return `${text.charAt(0).toUpperCase()}${text.slice(1)} — Aether will retry on the next sync.`;
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
    // RT-008: "blocked" = the source denies automated access from this server
    // (e.g. wellfound 403). Permanent + not user-actionable, so it renders as
    // a calm neutral "unavailable" pill, never a red error re-alarming on
    // every sync. The real reason stays in the row's lastError via the API.
    const isBlocked = row.status === "blocked";
    const badge: SourceBadge = isError ? "error" : isOk ? "ok" : "neutral";
    const badgeLabel = isError
      ? "error"
      : isOk
        ? `ok, ${count} new`
        : isBlocked
          ? "unavailable (blocked by source)"
          : row.status;
    const errorText = isError
      ? row.lastError && row.lastError.trim().length > 0
        ? humanizeSourceError(row.lastError)
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
