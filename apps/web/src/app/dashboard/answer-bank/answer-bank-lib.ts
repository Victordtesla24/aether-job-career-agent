/**
 * U5d-3 — the Answer Bank page's pure logic, kept out of the component so the
 * honesty-bearing parts are unit-testable without a DOM.
 *
 * NOTHING here decides whether an answer will be auto-sent. That is
 * `item.autoAnswers`, computed on the server from the sensitivity class, the
 * opt-in switch and the expiry — re-deriving it on the client is how a UI ends
 * up promising an automation the backend refuses to perform.
 */
import type { AnswerBankItem } from "../../../lib/api/answer-bank";

export interface BankSummary {
  /** Every answer the user has banked, expired ones included. */
  total: number;
  /** How many Aether will actually send without asking. */
  automatic: number;
  /** Banked, but user-gated on every application (judgement or sensitive). */
  gated: number;
  /** Past their staleness policy — Aether asks again rather than send them. */
  expired: number;
  /** Total recorded auto-answers across the whole bank. */
  timesUsed: number;
}

export function summarise(items: AnswerBankItem[]): BankSummary {
  return {
    total: items.length,
    automatic: items.filter((item) => item.autoAnswers).length,
    gated: items.filter((item) => !item.autoAnswers && !item.expired).length,
    expired: items.filter((item) => item.expired).length,
    timesUsed: items.reduce((sum, item) => sum + item.timesUsed, 0),
  };
}

export type BankFilter = "all" | "automatic" | "gated" | "expired";

export const BANK_FILTERS: Array<{ key: BankFilter; label: string }> = [
  { key: "all", label: "All answers" },
  { key: "automatic", label: "Sent automatically" },
  { key: "gated", label: "Asks you first" },
  { key: "expired", label: "Needs refreshing" },
];

export function applyFilter(items: AnswerBankItem[], filter: BankFilter): AnswerBankItem[] {
  if (filter === "automatic") return items.filter((item) => item.autoAnswers);
  if (filter === "gated") return items.filter((item) => !item.autoAnswers && !item.expired);
  if (filter === "expired") return items.filter((item) => item.expired);
  return items;
}

/**
 * The one-line status a row shows, in the user's terms.
 *
 * Order matters and mirrors the server's own precedence: an EXPIRED answer is
 * not sent whatever its class, so that fact is stated first rather than being
 * hidden behind a class label.
 */
export function statusLabel(item: AnswerBankItem): string {
  if (item.expired) return "Needs refreshing";
  if (item.autoAnswers) return "Sent automatically";
  return "Asks you first";
}

export function statusTone(item: AnswerBankItem): string {
  if (item.expired) return "text-aether-yellow";
  if (item.autoAnswers) return "text-aether-green";
  return "text-aether-muted";
}

/** How many DISTINCT applications a banked answer has been used on. */
export function distinctApplications(item: AnswerBankItem): number {
  return new Set(
    item.usedOn.map((use) => use.applicationId).filter((id): id is string => Boolean(id)),
  ).size;
}

/**
 * Human phrasing for where an answer was used — recorded fact only.
 *
 * An answer with no recorded use says exactly that. "Banked but never needed
 * yet" is a true and useful state, and inventing a count for it would corrupt
 * the only audit trail the user has over their own automated answers.
 */
export function usageSummary(item: AnswerBankItem): string {
  if (item.timesUsed === 0) return "Not used yet";
  const applications = distinctApplications(item);
  const uses = `${item.timesUsed} time${item.timesUsed === 1 ? "" : "s"}`;
  if (applications === 0) return `Used ${uses}`;
  return `Used ${uses} across ${applications} application${applications === 1 ? "" : "s"}`;
}

/** Confidence as a whole-number percentage, for the audit list. */
export function confidencePercent(confidence: number): number {
  return Math.round(confidence * 100);
}

/**
 * Which seed questions still have no banked answer.
 *
 * Drives the questionnaire's "N left" copy. It compares CONCEPTS, not question
 * strings, because an employer's wording of the same question banks under the
 * same concept — a user who answered "notice period" on a real application has
 * genuinely answered the seed question too.
 */
export function unansweredConcepts(
  questions: Array<{ concept: string }>,
  answeredConcepts: string[],
): string[] {
  const answered = new Set(answeredConcepts);
  return questions.map((q) => q.concept).filter((concept) => !answered.has(concept));
}
