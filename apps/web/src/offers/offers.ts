/**
 * Offer Comparison domain logic (screen: /dashboard/offers).
 *
 * Pure, framework-free functions that back the Offer Comparison wireframe
 * (design/screens/offer-comparison.html): weighted decision analysis across
 * live offers, top-pick ranking, negotiation coaching, and the empty-state
 * contract. Kept dependency-free so it runs under the existing vitest harness
 * and can be consumed by any UI layer.
 */

/** The five priority dimensions scored on every offer (see Priority Weights panel). */
export type Dimension =
  | "compensation"
  | "growth"
  | "culture"
  | "workLife"
  | "location";

export const DIMENSIONS: readonly Dimension[] = [
  "compensation",
  "growth",
  "culture",
  "workLife",
  "location",
] as const;

/** Priority weights as whole-number percentages that must sum to 100. */
export type PriorityWeights = Record<Dimension, number>;

/** Per-dimension fit scores for a single offer, each on a 0–100 scale. */
export type DimensionScores = Record<Dimension, number>;

export interface CompBreakdown {
  /** Annual base salary. */
  base: number;
  /** Annual cash bonus (target). */
  bonus: number;
  /** Annualized equity value. */
  equity: number;
}

export interface Offer {
  id: string;
  company: string;
  location: string;
  comp: CompBreakdown;
  scores: DimensionScores;
}

export interface RankedOffer extends Offer {
  /** base + bonus + equity. */
  totalComp: number;
  /** 0–100 weighted fit score, rounded to the nearest integer. */
  fit: number;
  /** 1-based rank by weighted fit (1 = best). */
  rank: number;
  /** True for the single highest-ranked offer. */
  topPick: boolean;
}

/** Default priority weights matching the wireframe's Priority Weights panel. */
export const DEFAULT_WEIGHTS: PriorityWeights = {
  compensation: 30,
  growth: 25,
  culture: 20,
  workLife: 15,
  location: 10,
};

const TOLERANCE = 0.01;

function isFiniteNumber(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/** Sum of base + bonus + equity for an offer. */
export function totalComp(comp: CompBreakdown): number {
  return comp.base + comp.bonus + comp.equity;
}

/**
 * Validate that weights are non-negative, cover every dimension, and sum to 100
 * (within a small rounding tolerance). Returns a typed result rather than
 * throwing so callers can surface field-level UI errors.
 */
export function validateWeights(weights: PriorityWeights): {
  valid: boolean;
  sum: number;
  errors: string[];
} {
  const errors: string[] = [];
  let sum = 0;
  for (const dim of DIMENSIONS) {
    const value = weights[dim];
    if (!isFiniteNumber(value)) {
      errors.push(`${dim}: weight must be a finite number`);
      continue;
    }
    if (value < 0) {
      errors.push(`${dim}: weight must be non-negative`);
    }
    sum += value;
  }
  if (errors.length === 0 && Math.abs(sum - 100) > TOLERANCE) {
    errors.push(`weights must sum to 100 (got ${sum})`);
  }
  return { valid: errors.length === 0, sum, errors };
}

/**
 * Weighted fit score (0–100) for one offer: the dot product of per-dimension
 * scores with weights normalized to fractions of the weight total. Normalizing
 * keeps the output in range even if callers pass weights that do not sum to 100.
 */
export function weightedFit(
  scores: DimensionScores,
  weights: PriorityWeights = DEFAULT_WEIGHTS,
): number {
  const weightTotal = DIMENSIONS.reduce((acc, dim) => acc + weights[dim], 0);
  if (weightTotal <= 0) return 0;
  const raw = DIMENSIONS.reduce(
    (acc, dim) => acc + scores[dim] * (weights[dim] / weightTotal),
    0,
  );
  return Math.round(raw);
}

/**
 * Rank offers by weighted fit (desc), attaching totalComp, fit, rank and a
 * single topPick flag. Ties break by total comp (desc) then company name so the
 * ordering is deterministic. Input is not mutated.
 */
export function rankOffers(
  offers: readonly Offer[],
  weights: PriorityWeights = DEFAULT_WEIGHTS,
): RankedOffer[] {
  const scored = offers.map((offer) => ({
    offer,
    totalComp: totalComp(offer.comp),
    fit: weightedFit(offer.scores, weights),
  }));

  scored.sort((a, b) => {
    if (b.fit !== a.fit) return b.fit - a.fit;
    if (b.totalComp !== a.totalComp) return b.totalComp - a.totalComp;
    return a.offer.company.localeCompare(b.offer.company);
  });

  return scored.map((entry, index) => ({
    ...entry.offer,
    totalComp: entry.totalComp,
    fit: entry.fit,
    rank: index + 1,
    topPick: index === 0,
  }));
}

/** True when there are no offers to compare (drives the empty state). */
export function isEmpty(offers: readonly Offer[]): boolean {
  return offers.length === 0;
}

export interface NegotiationInsight {
  /** Offer the coaching targets. */
  offerId: string;
  /** True when base sits below the market P75 benchmark. */
  belowMarket: boolean;
  /** Gap between market P75 and current base (0 when at/above market). */
  gapToMarketP75: number;
  /** Suggested counter base; equals market P75 when below, else current base. */
  suggestedCounterBase: number;
  /** Number of *other* live offers acting as leverage. */
  leverageOfferCount: number;
}

/**
 * Negotiation coaching for a target offer. When the offer's base is below the
 * provided market P75 benchmark, recommend countering up to P75; leverage is the
 * number of competing offers the candidate can cite.
 */
export function negotiationInsight(
  target: Offer,
  allOffers: readonly Offer[],
  marketP75Base: number,
): NegotiationInsight {
  const base = target.comp.base;
  const belowMarket = base < marketP75Base;
  const gapToMarketP75 = belowMarket ? marketP75Base - base : 0;
  const leverageOfferCount = allOffers.filter((o) => o.id !== target.id).length;
  return {
    offerId: target.id,
    belowMarket,
    gapToMarketP75,
    suggestedCounterBase: belowMarket ? marketP75Base : base,
    leverageOfferCount,
  };
}
