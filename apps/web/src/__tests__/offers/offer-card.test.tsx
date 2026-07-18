// @vitest-environment jsdom
/**
 * MV-offer-comparison-006 — OfferCard shows the currency code with the figures.
 * MV-offer-comparison-005 — a manually-added (source="manual") offer exposes a
 * remove control; application-derived offers do not.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OfferCard } from "../../components/offers/OfferCard";
import type { Offer } from "../../lib/api/workspaces";

const manual: Offer = {
  id: "of-manual",
  company: "Acme",
  role: "Staff Engineer",
  total: 250000,
  base: 200000,
  bonus: 20000,
  equity: 30000,
  location: "Sydney · Hybrid",
  currency: "AUD",
  fitScore: null,
  topPick: false,
  deadline: "",
  source: "manual",
};

const derived: Offer = {
  ...manual,
  id: "of-derived",
  company: "Globex",
  currency: "USD",
  fitScore: 88,
  topPick: true,
  source: "application",
};

afterEach(cleanup);

describe("OfferCard currency + delete (MV-006 / MV-005)", () => {
  it("shows the currency code alongside the total", () => {
    render(<OfferCard offer={manual} />);
    expect(screen.getByText(/AUD/)).toBeTruthy();
  });

  it("renders a remove control for manual offers and calls onDelete with the offer id", async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(<OfferCard offer={manual} onDelete={onDelete} />);
    fireEvent.click(screen.getByTestId("offer-delete"));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith("of-manual"));
  });

  it("renders no remove control for application-derived offers", () => {
    render(<OfferCard offer={derived} />);
    expect(screen.queryByTestId("offer-delete")).toBeNull();
  });
});
