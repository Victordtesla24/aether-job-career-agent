// @vitest-environment jsdom
/**
 * MV-offer-comparison-004 — the page no longer claims "weighted decision
 * analysis" and no longer renders the decorative Priority Weights panel (no
 * scoring ever consumed the weights).
 * MV-offer-comparison-001/006 — a persisted offer renders from the GET payload,
 * with its currency code and a remove control (manual source).
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Offer, OffersPayload } from "../../lib/api/workspaces";

const fetchOffersMock = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api/workspaces", async () => {
  const actual =
    await vi.importActual<typeof import("../../lib/api/workspaces")>("../../lib/api/workspaces");
  return { ...actual, fetchOffers: fetchOffersMock };
});

import OffersPage from "../../app/dashboard/offers/page";

afterEach(() => {
  cleanup();
  fetchOffersMock.mockReset();
});

const payload = (offers: Offer[]): OffersPayload => ({
  offers,
  weights: [],
  negotiation: { insight: "x", suggestedCounter: null, leverage: [] },
});

const manualOffer: Offer = {
  id: "o1",
  company: "Acme",
  role: "TPM",
  total: 250000,
  base: 200000,
  bonus: 20000,
  equity: 30000,
  location: "Sydney",
  currency: "AUD",
  fitScore: null,
  topPick: false,
  deadline: "",
  source: "manual",
};

describe("Offers page honest framing (MV-offer-comparison-004)", () => {
  it("does not claim 'weighted decision analysis' in the subtitle", async () => {
    fetchOffersMock.mockResolvedValue(payload([]));
    render(<OffersPage />);
    await waitFor(() => expect(screen.getByTestId("offer-comparison")).toBeTruthy());
    expect(screen.queryByText(/weighted decision analysis/i)).toBeNull();
    expect(screen.getByText(/compare your live offers/i)).toBeTruthy();
  });

  it("renders a persisted offer with its currency + remove control, and no Priority Weights panel", async () => {
    fetchOffersMock.mockResolvedValue(payload([manualOffer]));
    render(<OffersPage />);
    await waitFor(() => expect(screen.getByTestId("offer-cards")).toBeTruthy());
    expect(screen.getByTestId("offer-delete")).toBeTruthy();
    expect(screen.getByText(/AUD/)).toBeTruthy();
    // the decorative weights panel is gone
    expect(screen.queryByTestId("priority-weights")).toBeNull();
  });
});
