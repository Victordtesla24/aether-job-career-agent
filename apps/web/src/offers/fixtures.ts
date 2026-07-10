/**
 * Canonical Offer Comparison sample data, mirroring the three offers in
 * design/screens/offer-comparison.html. Compensation figures are expressed in
 * thousands of dollars to match the wireframe's `$185k` style labels.
 *
 * Per-dimension scores are chosen so that `weightedFit(..., DEFAULT_WEIGHTS)`
 * reproduces the wireframe's displayed fit scores exactly (Canva 91, Atlassian
 * 84, ANZ 79) — the engine is the source of truth, the mock just shows it.
 */
import type { Offer } from "./offers";

/** Market P75 base for Senior TPM in Sydney, per the Negotiation Coach note. */
export const MARKET_P75_BASE_SYDNEY = 195;

export const SAMPLE_OFFERS: readonly Offer[] = [
  {
    id: "canva",
    company: "Canva",
    location: "Sydney",
    comp: { base: 185, bonus: 28, equity: 35 },
    scores: {
      compensation: 88,
      growth: 95,
      culture: 92,
      workLife: 90,
      location: 92,
    },
  },
  {
    id: "atlassian",
    company: "Atlassian",
    location: "Sydney",
    comp: { base: 175, bonus: 25, equity: 35 },
    scores: {
      compensation: 85,
      growth: 86,
      culture: 84,
      workLife: 80,
      location: 84,
    },
  },
  {
    id: "anz",
    company: "ANZ",
    location: "Melbourne",
    comp: { base: 180, bonus: 22, equity: 10 },
    scores: {
      compensation: 82,
      growth: 74,
      culture: 78,
      workLife: 80,
      location: 80,
    },
  },
] as const;
