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
  /**
   * The real backend explanation, never fabricated: the humanized adapter
   * error when the last run FAILED, or the honest quota-pause copy when the
   * source is paused on a shared API quota (S-FIX-A/S-2). Null otherwise —
   * including RT-008's structural block, whose reason stays suppressed by
   * design because nothing the user does changes it.
   */
  errorText: string | null;
}

/** Bound on how much of a raw, unrecognised error reaches the UI (NEW-I4-FE-05). */
const MAX_RAW_CAUSE_LENGTH = 200;

/**
 * Query-string material can carry credentials (e.g. Adzuna's app_id/app_key
 * — see adzuna_adapter.py:83-84) — strip it from any embedded URL before the
 * cause reaches the UI. The URL itself is not secret; only redact from the
 * "?" onward.
 */
function stripUrlQueryStrings(text: string): string {
  return text.replace(/(https?:\/\/[^\s'"?]+)\?[^\s'")]*/gi, "$1");
}

/**
 * A stack-trace-shaped dump is reduced to its single most informative
 * line rather than shown whole: the LAST line for a Python traceback (that's
 * where the actual exception message lives), the FIRST line for any other
 * multi-line blob (e.g. httpx's "<message>\nFor more information check:
 * <url>" tail, which adds nothing).
 */
function collapseToOneLine(text: string): string {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length <= 1) return text.trim();
  return /Traceback \(most recent call last\)/.test(text) ? lines[lines.length - 1] : lines[0];
}

/**
 * Bound how much of a raw, unrecognised error reaches the UI while never
 * fabricating its content — truncates with an explicit ellipsis rather than
 * replacing the cause outright.
 */
function boundedRawCause(text: string): string {
  const cause = stripUrlQueryStrings(collapseToOneLine(text));
  if (cause.length <= MAX_RAW_CAUSE_LENGTH) return cause;
  return `${cause.slice(0, MAX_RAW_CAUSE_LENGTH).trimEnd()}…`;
}

/**
 * QA H-08 / M4 (NEW-I4-FE-05): translate a raw adapter exception string
 * (e.g. "AdapterFetchError: Wellfound public listings unavailable: HTTP
 * Error 404: Not Found") into calm, user-readable prose. The mapping never
 * fabricates a cause and never claims a failure is temporary or retryable
 * unless the raw text itself says so: it strips the exception-class prefix
 * and normalises the HTTP-error tail. For an oversized, URL-bearing, or
 * stack-trace-shaped payload — which would otherwise leak internals or wrap
 * hideously in the pill — it additionally redacts any URL query string
 * (which may carry credentials), collapses a multi-line dump to its single
 * most informative line, and truncates to a bounded display length; the
 * real cause is always preserved, truncated rather than replaced. Nothing
 * this function does not recognise is swapped for invented copy.
 */
export function humanizeSourceError(raw: string, source?: string): string {
  let text = raw.trim();
  // Strip a leading Python/JS exception class prefix ("AdapterFetchError: ").
  text = text.replace(/^[A-Za-z_]*(Error|Exception)\s*:\s*/, "");
  // "HTTP Error 404: Not Found" → "the source returned HTTP 404".
  text = text.replace(
    /HTTP Error (\d{3})(?::\s*[A-Za-z ]+)?/,
    (_m, code) => `the source returned HTTP ${code}`,
  );
  if (!text) return "Sync failed";

  // M4: some adapters bubble up genuinely raw payloads — a URL, a multi-line
  // stack trace, or an enormous blob — that would leak internals or wrap
  // hideously in the pill. The curated "... the source returned HTTP 403
  // ..." style messages (short, no URL, no newline) fall through untouched
  // below so their copy is preserved unchanged.
  const looksRaw =
    /https?:\/\//i.test(text) || // embedded URL
    /\n|Traceback|\bFile "|\s+at\s+\S+\(/.test(text) || // stack trace
    text.length > 160; // oversized blob
  if (looksRaw) {
    const label = source
      ? `${source.charAt(0).toUpperCase()}${source.slice(1)}`
      : "This source";
    const cause = boundedRawCause(text);
    return cause
      ? `${label}: ${cause}`
      : `${label}: sync failed — the source returned an unreadable error; see server logs.`;
  }

  return `${text.charAt(0).toUpperCase()}${text.slice(1)} — Aether will retry on the next sync.`;
}

/**
 * The scout writes `f"{type(exc).__name__}: {exc}"` onto the source row, so a
 * quota pause arrives as `SourceQuotaError: <curated message>` (S-FIX-A/S-2).
 */
const QUOTA_PREFIX = /^SourceQuotaError\s*:\s*/;

/**
 * The user-facing copy for a quota pause, or `null` when the row is not one.
 *
 * The message is written by our own adapter (a short, curated sentence naming
 * the reset time), so it is shown VERBATIM rather than being re-worded — the
 * only edit is dropping the exception-class marker, which is plumbing. The
 * guard mirrors `humanizeSourceError`'s: if a future caller ever puts a raw
 * dump (URL, stack trace, oversized blob) behind that prefix, it degrades to
 * the same calm humanized line instead of leaking internals into the pill.
 */
function quotaCopy(lastError: string | null | undefined, source?: string): string | null {
  if (!lastError || !QUOTA_PREFIX.test(lastError.trim())) return null;
  const text = lastError.trim().replace(QUOTA_PREFIX, "").trim();
  const looksRaw =
    text.length === 0 ||
    text.length > 220 ||
    /https?:\/\//i.test(text) ||
    /\n|Traceback|\bFile "/.test(text);
  return looksRaw ? humanizeSourceError(lastError, source) : text;
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
    // S-FIX-A/S-2: a QUOTA pause is the opposite of RT-008's structural block —
    // temporary, self-healing, and the backend's message says exactly when
    // market data resumes ("… resets at 00:00 UTC"). Suppressing that message
    // under the generic "blocked by source" pill told a paying subscriber the
    // board was refusing us. The adapter asserts the distinction by TYPE
    // (SourceQuotaError extends SourceBlockedError) and the scout stringifies
    // the class name onto the row, so this reads a class marker the backend
    // owns — never a guess about what an arbitrary error string means.
    const quotaMessage = isBlocked ? quotaCopy(row.lastError, row.source) : null;
    const badge: SourceBadge = isError ? "error" : isOk ? "ok" : "neutral";
    const badgeLabel = isError
      ? "error"
      : isOk
        ? `ok, ${count} new`
        : quotaMessage
          ? "market data paused (API quota)"
          : isBlocked
            ? "unavailable (blocked by source)"
            : row.status;
    const errorText = isError
      ? row.lastError && row.lastError.trim().length > 0
        ? humanizeSourceError(row.lastError, row.source)
        : "Sync failed"
      : quotaMessage;
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
