/**
 * Pure helpers for the Offer Comparison screen (wireframe: offer-comparison.html).
 * Kept framework-free so they can be unit-tested in isolation.
 */
import type { Offer } from "../../lib/api/workspaces";

/** A user-added offer has no agent-scored fit yet, so fitScore may be null. */
export type UiOffer = Omit<Offer, "fitScore"> & {
  fitScore: number | null;
  /** True for offers added in-session via the Add-Offer modal. */
  isNew?: boolean;
};

/** Format a dollar amount as the wireframe's compact `$NNNk`. */
export const money = (n: number): string => `$${Math.round(n / 1000)}k`;

/**
 * Ordered accent palette for the priority-weight bars, matching the wireframe
 * (`weights-of11`): compensation→coral, growth→indigo, culture→violet,
 * work-life→green, location→yellow. Falls back to coral for extra rows.
 */
export const WEIGHT_COLORS = [
  "#FF6B35", // coral
  "#818CF8", // indigo-400
  "#A78BFA", // violet-400
  "#34D399", // green
  "#FBBF24", // yellow
] as const;

export const weightColor = (index: number): string =>
  WEIGHT_COLORS[index % WEIGHT_COLORS.length];

/** Sum of the priority weights (should be 100 at defaults). */
export const sumWeights = (weights: Array<{ weight: number }>): number =>
  weights.reduce((total, w) => total + w.weight, 0);

/* --------------------------- Add-Offer validation -------------------------- */

export interface OfferDraft {
  company: string;
  role: string;
  base: string;
  bonus: string;
  equity: string;
  location: string;
}

export const emptyDraft = (): OfferDraft => ({
  company: "",
  role: "",
  base: "",
  bonus: "",
  equity: "",
  location: "",
});

export type DraftErrors = Partial<Record<keyof OfferDraft, string>>;

/** Parse a currency-ish string into a non-negative integer of dollars. */
const parseMoney = (raw: string): number | null => {
  const cleaned = raw.replace(/[$,\s]/g, "");
  if (cleaned === "") return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n) || n < 0) return null;
  return Math.round(n);
};

export interface ValidationResult {
  ok: boolean;
  errors: DraftErrors;
  offer?: UiOffer;
}

/**
 * Validate an Add-Offer draft. Company + base + location are required; base must
 * be > 0; bonus/equity default to 0 and must be ≥ 0 when present. On success
 * returns a UiOffer (fitScore null = pending agent analysis, never top pick).
 */
export function validateOfferDraft(draft: OfferDraft, idSuffix: string): ValidationResult {
  const errors: DraftErrors = {};

  const company = draft.company.trim();
  if (!company) errors.company = "Company is required.";
  else if (company.length > 60) errors.company = "Keep the company name under 60 characters.";

  const location = draft.location.trim();
  if (!location) errors.location = "Location is required.";

  const base = parseMoney(draft.base);
  if (base === null) errors.base = "Enter a base salary (numbers only).";
  else if (base <= 0) errors.base = "Base salary must be greater than 0.";

  const bonusRaw = draft.bonus.trim();
  const bonus = bonusRaw === "" ? 0 : parseMoney(draft.bonus);
  if (bonus === null) errors.bonus = "Bonus must be a non-negative number.";

  const equityRaw = draft.equity.trim();
  const equity = equityRaw === "" ? 0 : parseMoney(draft.equity);
  if (equity === null) errors.equity = "Equity must be a non-negative number.";

  if (Object.keys(errors).length > 0 || base === null || bonus === null || equity === null) {
    return { ok: false, errors };
  }

  return {
    ok: true,
    errors: {},
    offer: {
      id: `of-new-${idSuffix}`,
      company,
      role: draft.role.trim() || "—",
      base,
      bonus,
      equity,
      total: base + bonus + equity,
      location,
      fitScore: null,
      topPick: false,
      deadline: "",
      isNew: true,
    },
  };
}
