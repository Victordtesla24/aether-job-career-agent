/**
 * Cover Letter Studio — 422 rejection parsing (GAP-E4).
 *
 * The generate/refine agent runs (POST /agents/cover-letter/run,
 * POST /cover-letters/{id}/refine) reject a draft outright — rather than
 * shipping it best-effort — when it still fails the fabrication guard or the
 * §10.2 structural letter contract after every corrective retry
 * (apps/api/app/agents/cover_letter_agent.py FabricationError/StructuralError,
 * apps/api/app/routers/agents.py, apps/api/app/routers/cover_letters.py). Both
 * are surfaced as HTTP 422 with a plain-text `detail` naming the guard and the
 * offending items as a Python list, e.g.:
 *   "Cover letter rejected by fabrication guard: ['Kubernetes', 'Series B']"
 *   "Cover letter rejected — §10.2 format contract not met: ['the closing ...']"
 *   "Revision blocked by fabrication guard: ['Kubernetes']"
 *
 * This module turns that 422 into a typed panel model so the UI can render a
 * dedicated rejection panel instead of the generic error banner. Kept
 * side-effect free (pure functions over the caught error) for unit testing.
 */
import { ApiError } from "../../lib/api/client";

export type CoverLetterRejectionGuard = "fabrication" | "structural";

export interface CoverLetterRejection {
  guard: CoverLetterRejectionGuard;
  title: string;
  itemsLabel: string;
  items: string[];
  remediation: string[];
}

const FABRICATION_REMEDIATION = [
  "Remove or rephrase the flagged claims so every statement traces to your resume or the job description.",
  "Never introduce a skill, employer, tool, or metric that isn't written verbatim in your source documents.",
  "If a flagged term is actually accurate, add it to your resume or Voice DNA evidence first, then regenerate.",
];

const STRUCTURAL_REMEDIATION = [
  "The letter needs exactly 3 paragraphs: an opening naming the role, an evidence paragraph, and a closing call-to-action.",
  "Make sure the opening paragraph names the exact role or company, and the closing invites an interview or conversation.",
  "Regenerate the draft — the corrective retry loop will attempt to fix the format automatically.",
];

/** Extract the FastAPI `{"detail": "..."}` JSON body from an ApiError's message. */
function extractDetail(message: string): string | null {
  const idx = message.indexOf("): ");
  if (idx === -1) return null;
  const rawBody = message.slice(idx + 3);
  try {
    const parsed: unknown = JSON.parse(rawBody);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      return typeof detail === "string" ? detail : null;
    }
  } catch {
    return null;
  }
  return null;
}

/** Parse a Python `str(list[str])` repr, e.g. `['a', 'the "b" c']`, into items. */
function parseListRepr(repr: string): string[] {
  const matches = repr.match(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g) ?? [];
  return matches.map((m) => m.slice(1, -1)).filter((item) => item.length > 0);
}

/**
 * Map a caught agent-run/refine error to a rejection-panel model, or `null`
 * when it isn't a fabrication/structural guard rejection — callers fall back
 * to the generic error alert for every other case (other 4xx/5xx, network
 * errors, non-Error throws).
 */
export function parseCoverLetterRejection(error: unknown): CoverLetterRejection | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  const detail = extractDetail(error.message);
  if (!detail) return null;

  const fabricationMatch = detail.match(/fabrication guard:\s*(\[.*\])/i);
  if (fabricationMatch) {
    const items = parseListRepr(fabricationMatch[1]);
    if (items.length === 0) return null;
    return {
      guard: "fabrication",
      title: "Draft rejected by the fabrication guard",
      itemsLabel: "Flagged claims with no evidence in your resume or the job description",
      items,
      remediation: FABRICATION_REMEDIATION,
    };
  }

  const structuralMatch = detail.match(/format contract not met:\s*(\[.*\])/i);
  if (structuralMatch) {
    const items = parseListRepr(structuralMatch[1]);
    if (items.length === 0) return null;
    return {
      guard: "structural",
      title: "Draft rejected — letter format contract not met",
      itemsLabel: "Missing or malformed elements",
      items,
      remediation: STRUCTURAL_REMEDIATION,
    };
  }

  return null;
}
