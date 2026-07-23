/**
 * Pure helpers for the approval queue + modal (wireframe approval-modal.html).
 *
 * Approval payloads are written by different agents (tailoring, email,
 * negotiation) with overlapping-but-not-identical shapes, so all payload
 * access is centralized here and every field degrades to a sensible default.
 */
import type { Approval } from "../../lib/api/approvals";

/** Server-side expiry window (see apps/api approval_service.EXPIRY_HOURS). */
export const EXPIRY_HOURS = 48;

interface ReasoningItem {
  kind: "check" | "warning";
  text: string;
}

interface ApprovalDetails {
  /** Agent asking for approval, e.g. "Tailoring Agent". */
  agent: string;
  /** Verb phrase for the header subtitle, e.g. "submit an application". */
  action: string;
  jobTitle: string | null;
  company: string | null;
  location: string | null;
  /** Where the job was found, e.g. "LinkedIn". */
  source: string | null;
  /** Confidence in [0, 100], or null when the agent did not report one. */
  confidence: number | null;
  /** Why the approval gate fired. */
  why: string | null;
  reasoning: ReasoningItem[];
  /** Generated cover letter / message body preview. */
  preview: string | null;
  /** Two-letter tile glyph for the action summary row. */
  initials: string;
}

const ACTION_BY_TYPE: Record<Approval["type"], { agent: string; action: string }> = {
  application_submit: { agent: "Application Agent", action: "submit an application" },
  email_send: { agent: "Email Agent", action: "send an email" },
  offer_response: { agent: "Negotiation Agent", action: "respond to an offer" },
};

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function parseConfidence(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  // Values above 1 are ambiguous (fraction vs. already-a-percentage) unless
  // they're a whole number: the only real producer of an already-scaled
  // percentage (cover_letter_agent's grounding_confidence) always emits an
  // integer 0-100. A non-integer above 1 (e.g. 1.5) is neither a valid
  // [0,1] fraction nor a genuine percentage — reject it instead of silently
  // rendering a nonsensical value (MV-approval-modal-004).
  if (value > 1 && !Number.isInteger(value)) return null;
  const pct = value <= 1 ? value * 100 : value;
  return pct > 100 ? null : Math.round(pct);
}

function parseReasoning(value: unknown): ReasoningItem[] {
  if (!Array.isArray(value)) return [];
  const items: ReasoningItem[] = [];
  for (const entry of value) {
    if (typeof entry === "string" && entry.trim() !== "") {
      items.push({ kind: "check", text: entry });
    } else if (entry && typeof entry === "object") {
      const { kind, text } = entry as { kind?: unknown; text?: unknown };
      const body = asString(text);
      if (body) items.push({ kind: kind === "warning" ? "warning" : "check", text: body });
    }
  }
  return items;
}

export function companyInitials(company: string | null): string {
  if (!company) return "CV";
  const words = company.trim().split(/\s+/).filter(Boolean);
  const glyph =
    words.length >= 2 ? `${words[0][0]}${words[1][0]}` : company.trim().slice(0, 2);
  return glyph.toUpperCase();
}

export function parseApprovalPayload(approval: Approval): ApprovalDetails {
  const payload = approval.payload as Record<string, unknown>;
  const defaults = ACTION_BY_TYPE[approval.type];
  const company = asString(payload.company);
  return {
    agent: asString(payload.agent) ?? defaults.agent,
    action: asString(payload.action) ?? defaults.action,
    jobTitle: asString(payload.job_title),
    company,
    location: asString(payload.location),
    source: asString(payload.source),
    confidence: parseConfidence(payload.confidence),
    why: asString(payload.why),
    reasoning: parseReasoning(payload.reasoning),
    preview: asString(payload.preview),
    initials: asString(payload.initials)?.slice(0, 2).toUpperCase() ?? companyInitials(company),
  };
}

/** Pending approvals older than 48h are void — the API answers 409 (D8). */
export function isExpired(approval: Approval, now: number = Date.now()): boolean {
  return (
    approval.status === "pending" &&
    now - new Date(approval.createdAt).getTime() > EXPIRY_HOURS * 3600 * 1000
  );
}

/**
 * A card is removable when it is no longer actionable: an EXPIRED pending
 * request or a resolved (approved/rejected) one (FEAT-B1). A live pending
 * request must be approved or rejected, never silently removed — the server
 * enforces the same rule with a 409.
 */
export function canRemove(approval: Approval, now: number = Date.now()): boolean {
  return approval.status !== "pending" || isExpired(approval, now);
}

/** The artifact family a payload describes, discriminated by ``kind`` for the
 *  approvals that share the ``application_submit`` type (MV-resume-studio-001). */
function payloadKind(approval: Approval): string | undefined {
  return (approval.payload as { kind?: string }).kind;
}

/** One-line description for a queue card, e.g. "Application for Senior ML Engineer @ Canva". */
export function summarize(approval: Approval): string {
  const details = parseApprovalPayload(approval);
  const kind =
    approval.type === "email_send"
      ? "Email"
      : approval.type === "offer_response"
        ? "Offer response"
        : payloadKind(approval) === "cover_letter"
          ? "Cover letter"
          : payloadKind(approval) === "resume_tailor"
            ? "Tailored résumé"
            : "Application";
  const target = details.jobTitle
    ? ` for ${details.jobTitle}${details.company ? ` @ ${details.company}` : ""}`
    : "";
  return `${kind}${target}`;
}

/** Label for the generated-artifact preview block in the approval modal. Reflects
 *  the artifact family so a tailored-résumé approval never mislabels its preview
 *  as a "cover letter" (MV-resume-studio-001). */
export function previewLabel(approval: Approval): string {
  if (payloadKind(approval) === "resume_tailor") return "Tailored résumé changes";
  if (approval.type === "email_send") return "Email to send";
  if (approval.type === "offer_response") return "Offer response";
  return "Generated cover letter";
}

/** "Company · Location · via Source" meta line under the job title. */
export function metaLine(details: ApprovalDetails): string {
  const parts = [details.company, details.location].filter(Boolean) as string[];
  if (details.source) parts.push(`via ${details.source}`);
  return parts.join(" · ");
}

/** Matches a salutation opener, e.g. "Dear Hiring Team at Acme," (ML-approvals-001). */
const SALUTATION_RE = /^dear\b/i;

/**
 * True for a business-letter "letterhead" line — a date, blank spacer,
 * "Re: <subject>" line, or a short address-block line (recipient / company
 * name) with no terminal sentence punctuation. Real body paragraphs are
 * longer and end in `.`/`!`/`?` (ML-approvals-001).
 */
function isLetterheadLine(line: string): boolean {
  const trimmed = line.trim();
  if (trimmed === "") return true;
  // "22 July 2026" / "July 22, 2026" / "2026-07-22"
  if (/^\d{1,2}\s+[A-Za-z]+\s+\d{4}$/.test(trimmed)) return true;
  if (/^[A-Za-z]+\s+\d{1,2},?\s+\d{4}$/.test(trimmed)) return true;
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return true;
  if (/^re:/i.test(trimmed)) return true;
  // Short address-block lines (company/recipient name, "Hiring Team") — no
  // sentence-ending punctuation and few enough words that it reads as a
  // label, not a sentence.
  if (trimmed.length <= 40 && !/[.!?]$/.test(trimmed) && trimmed.split(/\s+/).length <= 6) return true;
  return false;
}

/**
 * Skip past a generated letter's letterhead (date / addressee block / "Re:"
 * line / salutation) and return the substantive body that follows, so a
 * `line-clamp-3` card preview surfaces real content instead of being
 * exhausted by letterhead alone (ML-approvals-001). Falls back to the
 * original text untouched when nothing looks like letterhead, or when the
 * whole text turns out to be letterhead (never returns emptiness).
 */
export function substantiveExcerpt(preview: string): string {
  const lines = preview.split("\n");
  let start = 0;
  const salutationIndex = lines.findIndex((line) => SALUTATION_RE.test(line.trim()));
  if (salutationIndex !== -1) {
    start = salutationIndex + 1;
  } else {
    while (start < lines.length && isLetterheadLine(lines[start])) start++;
  }
  while (start < lines.length && lines[start].trim() === "") start++;
  const excerpt = lines.slice(start).join("\n").trim();
  return excerpt || preview.trim();
}
