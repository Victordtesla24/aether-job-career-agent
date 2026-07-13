/**
 * Pure helpers for the Settings → Career Data panel (GAP-P4-047 · ADR D-0031).
 *
 * The panel lets a user configure the three career-data sources that feed
 * resume tailoring + cover-letter context, then triggers a real ingestion via
 * `POST /workspaces/career-data/refresh`. These helpers derive the editable
 * input state from the persisted server rows and build the refresh payload —
 * kept side-effect-free so they can be unit-tested without a DOM.
 */
import type {
  CareerData,
  CareerDataRefreshInput,
  CareerDataSource,
  CareerSourceName,
} from "../../lib/api/workspaces";

/** Editable input state for the Career Data panel. */
export interface CareerDataInputs {
  githubUsername: string;
  portfolioUrl: string;
  linkedinSummary: string;
}

/** Human-readable label for each persisted source status. */
export const CAREER_STATUS_LABEL: Record<string, string> = {
  ok: "Synced",
  pending: "Pending",
  empty: "Not provided",
  error: "Error",
  not_configured: "Not configured",
};

/** Tailwind chip styling per status, mirroring the settings STATUS_STYLE map. */
export const CAREER_STATUS_STYLE: Record<string, string> = {
  ok: "bg-aether-green/15 text-aether-green border-aether-green/25",
  pending: "bg-aether-amber/15 text-aether-amber border-aether-amber/25",
  empty: "bg-white/5 text-aether-muted-dim border-white/10",
  not_configured: "bg-white/5 text-aether-muted-dim border-white/10",
  error: "bg-red-500/10 text-red-300 border-red-500/25",
};

export function careerStatusLabel(status: string): string {
  return CAREER_STATUS_LABEL[status] ?? status;
}

export function careerStatusStyle(status: string): string {
  return CAREER_STATUS_STYLE[status] ?? CAREER_STATUS_STYLE.not_configured!;
}

/** Look up one source's persisted state (or undefined if absent). */
export function bySource(
  data: CareerData | null,
  source: CareerSourceName,
): CareerDataSource | undefined {
  return data?.sources.find((s) => s.source === source);
}

/**
 * Extract the GitHub username from a stored profile URL
 * (`https://github.com/<username>` → `<username>`), so the input can be
 * prefilled with what's already configured. Returns `""` when not parseable.
 */
export function parseGithubUsername(url: string | null | undefined): string {
  if (!url) return "";
  const match = /github\.com\/([^/?#]+)/i.exec(url);
  return match?.[1] ?? "";
}

/**
 * Derive editable input values from the server state. GitHub/portfolio prefill
 * from their persisted URLs; LinkedIn is intentionally left blank because the
 * API returns the formatted summary, not the raw paste — the user re-pastes to
 * change it (an untouched blank textarea reuses the stored value, see
 * {@link buildRefreshPayload}).
 */
export function deriveInputs(data: CareerData | null): CareerDataInputs {
  return {
    githubUsername: parseGithubUsername(bySource(data, "github")?.url),
    portfolioUrl: bySource(data, "portfolio")?.url ?? "",
    linkedinSummary: "",
  };
}

/**
 * Build the refresh request body from the current inputs.
 *
 * GitHub username and portfolio URL are sent (trimmed) once the initial
 * career-data GET has resolved (`loaded`) — at that point clearing an input
 * intentionally clears that source. Before the GET resolves, `inputs` is
 * still the component's un-populated default state (`""`), which is NOT a
 * user's intentional clear: sending it verbatim would silently wipe a
 * GitHub username / portfolio URL the server already has configured the
 * instant "Sync now" is pressed too early. So while `loaded` is false, both
 * fields are omitted entirely — the same "omit means keep" guard LinkedIn
 * already relies on (GAP-P4-047 Wave-1 regression).
 *
 * LinkedIn is only sent when the user has actually edited the textarea
 * (`linkedinDirty`); otherwise it is omitted so a bare "Sync now" preserves a
 * previously pasted LinkedIn summary instead of silently wiping it.
 */
export function buildRefreshPayload(
  inputs: CareerDataInputs,
  linkedinDirty: boolean,
  loaded: boolean = true,
): CareerDataRefreshInput {
  const payload: CareerDataRefreshInput = {};
  if (loaded) {
    payload.githubUsername = inputs.githubUsername.trim();
    payload.portfolioUrl = inputs.portfolioUrl.trim();
  }
  if (linkedinDirty) {
    payload.linkedinSummary = inputs.linkedinSummary;
  }
  return payload;
}
