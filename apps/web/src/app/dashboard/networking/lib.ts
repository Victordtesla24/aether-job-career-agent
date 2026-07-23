/**
 * Pure view-model helpers for the Networking Kanban board (wireframe:
 * design/screens/networking.html lines ~81-105 — a per-contact card board,
 * not a tab/pill summary).
 *
 * Extracted from page.tsx so the board's column derivation — which contacts
 * land in which stage, how locally-added contacts merge in, and the overall
 * empty-board check — can be unit-tested against a contacts fixture without
 * a DOM renderer.
 */
import type { NetworkingContact, NetworkingSummary } from "../../../lib/api/workspaces";

export const STAGE_ACCENT: Record<string, string> = {
  New: "bg-white/40",
  Warm: "bg-aether-amber",
  Active: "bg-aether-coral",
  Scheduled: "bg-aether-violet",
  Placed: "bg-aether-green",
};

/** Two-letter avatar glyph for a contact card, e.g. "Sarah L." -> "SL". */
export function initials(name: string): string {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

interface PipelineColumnView {
  stage: string;
  count: number;
  contacts: NetworkingContact[];
}

/**
 * Build the board's per-column view model from the API's pipeline plus any
 * contacts added locally in this session (which land in "New" — demo scope).
 *
 * A column with no contacts always renders with an empty `contacts` array —
 * never fabricated cards — so a stage with zero real contacts is an honest
 * empty state rather than a fake placeholder.
 */
export function buildPipelineColumns(
  pipeline: NetworkingSummary["pipeline"],
  added: NetworkingContact[] = [],
): PipelineColumnView[] {
  return pipeline.map((col) => {
    const contacts = col.stage === "New" ? [...added, ...col.contacts] : col.contacts;
    const count = col.stage === "New" ? col.count + added.length : col.count;
    return { stage: col.stage, count, contacts };
  });
}

/** Total contact count across the whole board (stat tile + empty-state check). */
export function totalContacts(stats: NetworkingSummary["stats"], added: NetworkingContact[]): number {
  return stats.contacts + added.length;
}

/**
 * Humanize an OutreachTask.type / NetworkingOutreachEntry.kind enum value
 * ("connection_request", "follow_up", …) into display text ("Connection
 * request", "Follow up"). Used by the Outreach Queue + Communication Log
 * cards (MV-networking-002) instead of a nonexistent `tone` field.
 */
export function formatOutreachKind(kind: string): string {
  const spaced = kind.replace(/_/g, " ").trim();
  if (!spaced) return "";
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Render a nullable ISO-ish timestamp (as psycopg2's `str(datetime)` produces,
 * e.g. "2026-07-18 10:23:45.123456+00:00") as an honest short date, or an
 * em dash when absent — never "undefined" or "Invalid Date".
 */
export function formatWhen(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length >= 10 ? value.slice(0, 10) : value;
}
