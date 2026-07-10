import { describe, it, expect } from "vitest";
import {
  DEFAULT_WEIGHTS,
  DIMENSIONS,
  isEmpty,
  negotiationInsight,
  rankOffers,
  totalComp,
  validateWeights,
  weightedFit,
  type Offer,
  type PriorityWeights,
} from "../src/offers/offers";
import { MARKET_P75_BASE_SYDNEY, SAMPLE_OFFERS } from "../src/offers/fixtures";

const byId = (id: string): Offer => {
  const offer = SAMPLE_OFFERS.find((o) => o.id === id);
  if (!offer) throw new Error(`fixture ${id} missing`);
  return offer;
};

describe("offers · totalComp (SC-OFFER-018)", () => {
  it("sums base+bonus+equity to the wireframe totals", () => {
    expect(totalComp(byId("canva").comp)).toBe(248);
    expect(totalComp(byId("atlassian").comp)).toBe(235);
    expect(totalComp(byId("anz").comp)).toBe(212);
  });
});

describe("offers · validateWeights (SC-OFFER-019)", () => {
  it("accepts the default weights (sum 100)", () => {
    const result = validateWeights(DEFAULT_WEIGHTS);
    expect(result.valid).toBe(true);
    expect(result.sum).toBe(100);
    expect(result.errors).toHaveLength(0);
  });

  it("rejects weights that do not sum to 100", () => {
    const bad: PriorityWeights = { ...DEFAULT_WEIGHTS, compensation: 40 };
    const result = validateWeights(bad);
    expect(result.valid).toBe(false);
    expect(result.sum).toBe(110);
    expect(result.errors.some((e) => e.includes("sum to 100"))).toBe(true);
  });

  it("rejects negative and non-finite weights", () => {
    const negative = validateWeights({ ...DEFAULT_WEIGHTS, growth: -5, culture: 30 });
    expect(negative.valid).toBe(false);
    expect(negative.errors.some((e) => e.includes("non-negative"))).toBe(true);

    const nan = validateWeights({ ...DEFAULT_WEIGHTS, location: Number.NaN });
    expect(nan.valid).toBe(false);
    expect(nan.errors.some((e) => e.includes("finite"))).toBe(true);
  });
});

describe("offers · weightedFit (SC-OFFER-020)", () => {
  it("reproduces the wireframe fit scores under default weights", () => {
    expect(weightedFit(byId("canva").scores)).toBe(91);
    expect(weightedFit(byId("atlassian").scores)).toBe(84);
    expect(weightedFit(byId("anz").scores)).toBe(79);
  });

  it("stays in 0–100 and returns 0 for a zero weight total", () => {
    const perfect = Object.fromEntries(
      DIMENSIONS.map((d) => [d, 100]),
    ) as Offer["scores"];
    expect(weightedFit(perfect)).toBe(100);
    const zeroWeights = Object.fromEntries(
      DIMENSIONS.map((d) => [d, 0]),
    ) as PriorityWeights;
    expect(weightedFit(byId("canva").scores, zeroWeights)).toBe(0);
  });

  it("normalizes weights that do not sum to 100", () => {
    const doubled = Object.fromEntries(
      DIMENSIONS.map((d) => [d, DEFAULT_WEIGHTS[d] * 2]),
    ) as PriorityWeights;
    expect(weightedFit(byId("canva").scores, doubled)).toBe(
      weightedFit(byId("canva").scores, DEFAULT_WEIGHTS),
    );
  });
});

describe("offers · rankOffers (SC-OFFER-021)", () => {
  it("orders by fit desc and flags exactly one top pick (Canva)", () => {
    const ranked = rankOffers(SAMPLE_OFFERS);
    expect(ranked.map((o) => o.id)).toEqual(["canva", "atlassian", "anz"]);
    expect(ranked[0].topPick).toBe(true);
    expect(ranked.filter((o) => o.topPick)).toHaveLength(1);
    expect(ranked.map((o) => o.rank)).toEqual([1, 2, 3]);
  });

  it("does not mutate the input array", () => {
    const snapshot = SAMPLE_OFFERS.map((o) => o.id);
    rankOffers(SAMPLE_OFFERS);
    expect(SAMPLE_OFFERS.map((o) => o.id)).toEqual(snapshot);
  });

  it("breaks fit ties deterministically by total comp then name", () => {
    const scores = byId("canva").scores;
    const a: Offer = { id: "a", company: "Zeta", location: "X", comp: { base: 100, bonus: 0, equity: 0 }, scores };
    const b: Offer = { id: "b", company: "Alpha", location: "X", comp: { base: 200, bonus: 0, equity: 0 }, scores };
    const ranked = rankOffers([a, b]);
    expect(ranked[0].id).toBe("b"); // higher total comp wins the tie
  });
});

describe("offers · negotiationInsight (SC-OFFER-022)", () => {
  it("suggests countering to market P75 with correct leverage for Canva", () => {
    const insight = negotiationInsight(byId("canva"), SAMPLE_OFFERS, MARKET_P75_BASE_SYDNEY);
    expect(insight.belowMarket).toBe(true);
    expect(insight.gapToMarketP75).toBe(10); // $195k P75 − $185k base
    expect(insight.suggestedCounterBase).toBe(195);
    expect(insight.leverageOfferCount).toBe(2);
  });

  it("does not recommend a counter when at/above market", () => {
    const insight = negotiationInsight(byId("canva"), SAMPLE_OFFERS, 185);
    expect(insight.belowMarket).toBe(false);
    expect(insight.gapToMarketP75).toBe(0);
    expect(insight.suggestedCounterBase).toBe(185);
  });
});

describe("offers · isEmpty (SC-OFFER-023)", () => {
  it("is true only when there are no offers", () => {
    expect(isEmpty([])).toBe(true);
    expect(isEmpty(SAMPLE_OFFERS)).toBe(false);
  });
});
