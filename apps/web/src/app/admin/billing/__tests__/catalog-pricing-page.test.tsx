// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchAdminPlansMock = vi.fn();
const updatePlanPricingMock = vi.fn();

vi.mock("../../../../lib/api/adminPlans", () => ({
  fetchAdminPlans: (...args: unknown[]) => fetchAdminPlansMock(...args),
  updatePlanPricing: (...args: unknown[]) => updatePlanPricingMock(...args),
}));

// eslint-disable-next-line import/first
import AdminBillingPage from "../page";

const starter = {
  id: "starter",
  name: "Starter",
  priceAudMonthly: 19,
  priceAudAnnual: 179,
  stripeProductId: "prod_starter",
  stripePriceIdMonthly: "price_monthly",
  stripePriceIdAnnual: "price_annual",
  active: true,
};

beforeEach(() => {
  fetchAdminPlansMock.mockResolvedValue({ plans: [starter] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("catalog pricing editor", () => {
  it("loads every plan and saves an explicit future-checkout price after confirmation", async () => {
    render(<AdminBillingPage />);
    const row = await screen.findByTestId("admin-plan-row-starter");
    expect(row.textContent).toContain("A$19.00");
    expect(row.textContent).toContain("A$179.00");
    expect(row.textContent).toMatch(/future checkout/i);

    fireEvent.change(within(row).getByLabelText("Starter monthly price (AUD)"), {
      target: { value: "21.50" },
    });
    fireEvent.click(within(row).getByTestId("admin-plan-save-starter"));
    expect(updatePlanPricingMock).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByTestId("admin-plan-save-confirm-starter"));
    await waitFor(() =>
      expect(updatePlanPricingMock).toHaveBeenCalledWith("starter", { priceAudMonthly: 21.5 }),
    );
  });

  it("does not call the API for an invalid price", async () => {
    render(<AdminBillingPage />);
    const row = await screen.findByTestId("admin-plan-row-starter");
    fireEvent.change(within(row).getByLabelText("Starter annual price (AUD)"), {
      target: { value: "-1" },
    });
    fireEvent.click(within(row).getByTestId("admin-plan-save-starter"));
    expect(screen.getByTestId("admin-plan-error-starter").textContent).toMatch(/zero or more/i);
    expect(updatePlanPricingMock).not.toHaveBeenCalled();
  });
});