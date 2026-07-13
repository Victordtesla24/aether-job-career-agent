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

export interface PipelineColumnView {
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
