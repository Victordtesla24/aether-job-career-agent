/**
 * AGT-OFFER — unit coverage for Offer Comparison helpers (offer-comparison.html):
 * money formatting, weight palette/summing, and Add-Offer draft validation.
 */
import { describe, expect, it } from "vitest";

import {
  emptyDraft,
  money,
  sumWeights,
  tabTrapTarget,
  validateOfferDraft,
  weightColor,
  WEIGHT_COLORS,
  type OfferDraft,
} from "../../components/offers/offers-lib";

describe("money", () => {
  it("formats to compact $NNNk", () => {
    expect(money(248000)).toBe("$248k");
    expect(money(212000)).toBe("$212k");
    expect(money(0)).toBe("$0k");
  });
  it("rounds to the nearest thousand", () => {
    expect(money(185400)).toBe("$185k");
    expect(money(185600)).toBe("$186k");
  });
});

describe("weight palette", () => {
  it("returns the ordered wireframe colors and wraps", () => {
    expect(weightColor(0)).toBe("#FF6B35");
    expect(weightColor(4)).toBe("#FBBF24");
    expect(weightColor(5)).toBe(WEIGHT_COLORS[0]);
  });
  it("sums weights", () => {
    expect(
      sumWeights([{ weight: 30 }, { weight: 25 }, { weight: 20 }, { weight: 15 }, { weight: 10 }]),
    ).toBe(100);
    expect(sumWeights([])).toBe(0);
  });
});

describe("validateOfferDraft", () => {
  const base = (over: Partial<OfferDraft> = {}): OfferDraft => ({
    ...emptyDraft(),
    company: "Figma",
    base: "185000",
    location: "Sydney",
    ...over,
  });

  it("accepts a valid draft and computes total", () => {
    const r = validateOfferDraft(base({ bonus: "20000", equity: "30000" }), "1");
    expect(r.ok).toBe(true);
    expect(r.offer?.total).toBe(235000);
    expect(r.offer?.company).toBe("Figma");
    expect(r.offer?.fitScore).toBeNull();
    expect(r.offer?.topPick).toBe(false);
    expect(r.offer?.isNew).toBe(true);
  });

  it("defaults bonus/equity to 0 when blank", () => {
    const r = validateOfferDraft(base(), "2");
    expect(r.ok).toBe(true);
    expect(r.offer?.total).toBe(185000);
  });

  it("requires a company", () => {
    const r = validateOfferDraft(base({ company: "  " }), "3");
    expect(r.ok).toBe(false);
    expect(r.errors.company).toBeTruthy();
  });

  it("requires a location", () => {
    const r = validateOfferDraft(base({ location: "" }), "4");
    expect(r.ok).toBe(false);
    expect(r.errors.location).toBeTruthy();
  });

  it("rejects non-positive or non-numeric base", () => {
    expect(validateOfferDraft(base({ base: "0" }), "5").ok).toBe(false);
    expect(validateOfferDraft(base({ base: "abc" }), "6").ok).toBe(false);
    expect(validateOfferDraft(base({ base: "-5" }), "7").ok).toBe(false);
  });

  it("rejects negative bonus/equity", () => {
    expect(validateOfferDraft(base({ bonus: "-1" }), "8").errors.bonus).toBeTruthy();
    expect(validateOfferDraft(base({ equity: "-1" }), "9").errors.equity).toBeTruthy();
  });

  it("strips $ and commas from currency inputs", () => {
    const r = validateOfferDraft(base({ base: "$185,000", bonus: "$1,000" }), "10");
    expect(r.ok).toBe(true);
    expect(r.offer?.total).toBe(186000);
  });

  it("caps company length", () => {
    const r = validateOfferDraft(base({ company: "x".repeat(61) }), "11");
    expect(r.ok).toBe(false);
    expect(r.errors.company).toBeTruthy();
  });
});

// GAP-P4-057: the Add-Offer modal must trap Tab focus so it can't escape
// onto the header/empty-state "Add Offer" triggers the overlay visually
// covers (Playwright's "subtree intercepts pointer events" symptom is the
// overlay correctly blocking the mouse; without a trap, keyboard Tab could
// still reach and activate those same covered controls).
describe("tabTrapTarget", () => {
  const fields = ["company", "role", "base", "bonus", "equity", "location", "cancel", "submit"];

  it("wraps Shift+Tab from the first field to the last", () => {
    expect(tabTrapTarget(fields, "company", true)).toBe("submit");
  });

  it("wraps Tab from the last field to the first", () => {
    expect(tabTrapTarget(fields, "submit", false)).toBe("company");
  });

  it("does not interfere with Tab/Shift+Tab away from the boundaries", () => {
    expect(tabTrapTarget(fields, "base", false)).toBeNull();
    expect(tabTrapTarget(fields, "base", true)).toBeNull();
  });

  it("is a no-op when the dialog has no focusable elements", () => {
    expect(tabTrapTarget([], "anything", false)).toBeNull();
  });
});
