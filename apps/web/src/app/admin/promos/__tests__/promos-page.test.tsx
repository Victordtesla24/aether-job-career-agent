// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-2 (d) — /admin/promos.
 *
 * RED-first: the page does not exist in this tree yet (FE-1 left the nav entry
 * deliberately disabled rather than linking to a 404).
 *
 * MONEY SAFETY, RESTATED IN THE UI. Creating a discount charges nobody: BE-1
 * creates a Stripe Coupon plus its customer-facing PromotionCode, and money
 * only ever moves when a customer redeems the code at their own checkout. The
 * removal action is a DEACTIVATION (`active=false`), not a coupon delete —
 * deliberately reversible, and it preserves the redemption history of everyone
 * who already used the code. A "Delete" label here would misdescribe both.
 *
 * Stripe is the source of truth for this screen; there is no local mirror to
 * drift, so the list is whatever `GET /admin/promos` returns and a 503 (billing
 * not configured on this deployment) is stated as such rather than rendered as
 * "no promotions".
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../lib/api/client";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)}>{children}</a>
  ),
}));

const fetchPromosMock = vi.fn();
const createPromoMock = vi.fn();
const deactivatePromoMock = vi.fn();

vi.mock("../../../../lib/api/adminPromos", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/adminPromos")>();
  return {
    ...actual,
    fetchPromos: (...a: unknown[]) => fetchPromosMock(...a),
    createPromo: (...a: unknown[]) => createPromoMock(...a),
    deactivatePromo: (...a: unknown[]) => deactivatePromoMock(...a),
  };
});

// eslint-disable-next-line import/first
import AdminPromosPage from "../page";

function promo(overrides: Record<string, unknown> = {}) {
  return {
    id: "promo_1",
    code: "LAUNCH20",
    active: true,
    couponId: "coup_1",
    percentOff: 20,
    amountOffAud: null,
    duration: "once",
    timesRedeemed: 3,
    maxRedemptions: 100,
    expiresAt: null,
    ...overrides,
  };
}

async function renderPage(promos: unknown[] = [promo()]) {
  fetchPromosMock.mockResolvedValue({ promos, total: promos.length });
  render(<AdminPromosPage />);
  await waitFor(() => expect(fetchPromosMock).toHaveBeenCalled());
}

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the promotion list", () => {
  it("shows the code, its discount, redemptions and status", async () => {
    await renderPage();
    const row = await screen.findByTestId("admin-promo-row-promo_1");
    expect(row.textContent).toContain("LAUNCH20");
    expect(row.textContent).toContain("20");
    expect(row.textContent).toContain("3");
    expect(within(row).getByTestId("admin-promo-status-promo_1").textContent).toMatch(/active/i);
  });

  it("renders an amount-off promotion in AUD, not as a percentage", async () => {
    await renderPage([
      promo({ id: "promo_2", code: "TENOFF", percentOff: null, amountOffAud: 10 }),
    ]);
    const row = await screen.findByTestId("admin-promo-row-promo_2");
    expect(row.textContent).toMatch(/\$?10/);
    expect(row.textContent).not.toMatch(/10\s*%/);
  });

  it("copies a code for pasting to a customer", async () => {
    await renderPage();
    fireEvent.click(await screen.findByTestId("admin-promo-copy-promo_1"));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("LAUNCH20"));
  });

  it("states an empty Stripe account as empty, honestly", async () => {
    await renderPage([]);
    expect((await screen.findByTestId("admin-promos-empty")).textContent).toMatch(
      /no promotion/i,
    );
  });

  it("distinguishes 'billing not configured' from 'no promotions'", async () => {
    fetchPromosMock.mockRejectedValue(
      new ApiError("Billing is not configured on this deployment yet", 503),
    );
    render(<AdminPromosPage />);
    await waitFor(() => expect(screen.getByTestId("admin-promos-error")).toBeTruthy());
    expect(screen.getByTestId("admin-promos-error").textContent).toContain(
      "not configured",
    );
    expect(screen.queryByTestId("admin-promos-empty")).toBeNull();
  });
});

describe("creating a promotion", () => {
  it("creates a percent-off code", async () => {
    await renderPage([]);
    createPromoMock.mockResolvedValue({
      promotionCodeId: "promo_new",
      code: "SPRING25",
      couponId: "coup_2",
      percentOff: 25,
      amountOffAud: null,
      duration: "once",
      durationInMonths: null,
      maxRedemptions: null,
      expiresAt: null,
      active: true,
      currency: "AUD",
    });
    fireEvent.change(screen.getByLabelText("Discount value"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("Promotion code (optional)"), {
      target: { value: "spring25" },
    });
    fireEvent.click(screen.getByTestId("admin-promo-create"));

    await waitFor(() => expect(createPromoMock).toHaveBeenCalled());
    expect(createPromoMock.mock.calls[0]?.[0]).toMatchObject({
      percentOff: 25,
      duration: "once",
      // Stripe stores codes uppercase; send the canonical form.
      code: "SPRING25",
    });
    expect(createPromoMock.mock.calls[0]?.[0]).not.toHaveProperty("amountOffAud");
  });

  it("creates an amount-off code in AUD when the discount type is switched", async () => {
    await renderPage([]);
    createPromoMock.mockResolvedValue({
      promotionCodeId: "promo_new",
      code: "TEN",
      couponId: "coup_3",
      percentOff: null,
      amountOffAud: 10,
      duration: "once",
      durationInMonths: null,
      maxRedemptions: null,
      expiresAt: null,
      active: true,
      currency: "AUD",
    });
    fireEvent.change(screen.getByLabelText("Discount type"), { target: { value: "amount" } });
    fireEvent.change(screen.getByLabelText("Discount value"), { target: { value: "10" } });
    fireEvent.click(screen.getByTestId("admin-promo-create"));

    await waitFor(() => expect(createPromoMock).toHaveBeenCalled());
    expect(createPromoMock.mock.calls[0]?.[0]).toMatchObject({ amountOffAud: 10 });
    expect(createPromoMock.mock.calls[0]?.[0]).not.toHaveProperty("percentOff");
  });

  it("requires a month count when the duration is 'repeating', before calling the API", async () => {
    await renderPage([]);
    fireEvent.change(screen.getByLabelText("Discount value"), { target: { value: "15" } });
    fireEvent.change(screen.getByLabelText("Duration"), { target: { value: "repeating" } });
    fireEvent.click(screen.getByTestId("admin-promo-create"));

    await waitFor(() => expect(screen.getByTestId("admin-promos-error")).toBeTruthy());
    expect(createPromoMock).not.toHaveBeenCalled();

    createPromoMock.mockResolvedValue({
      promotionCodeId: "p3",
      code: "THREE",
      couponId: "c3",
      percentOff: 15,
      amountOffAud: null,
      duration: "repeating",
      durationInMonths: 3,
      maxRedemptions: null,
      expiresAt: null,
      active: true,
      currency: "AUD",
    });
    fireEvent.change(screen.getByLabelText("Repeats for (months)"), { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("admin-promo-create"));
    await waitFor(() => expect(createPromoMock).toHaveBeenCalled());
    expect(createPromoMock.mock.calls[0]?.[0]).toMatchObject({
      duration: "repeating",
      durationInMonths: 3,
    });
  });

  it("rejects a percentage over 100 without calling the API", async () => {
    await renderPage([]);
    fireEvent.change(screen.getByLabelText("Discount value"), { target: { value: "120" } });
    fireEvent.click(screen.getByTestId("admin-promo-create"));
    await waitFor(() => expect(screen.getByTestId("admin-promos-error")).toBeTruthy());
    expect(createPromoMock).not.toHaveBeenCalled();
  });

  it("shows the created code for copying, and reloads the list", async () => {
    await renderPage([]);
    createPromoMock.mockResolvedValue({
      promotionCodeId: "promo_new",
      code: "SPRING25",
      couponId: "coup_2",
      percentOff: 25,
      amountOffAud: null,
      duration: "once",
      durationInMonths: null,
      maxRedemptions: null,
      expiresAt: null,
      active: true,
      currency: "AUD",
    });
    fireEvent.change(screen.getByLabelText("Discount value"), { target: { value: "25" } });
    fireEvent.click(screen.getByTestId("admin-promo-create"));

    const created = await screen.findByTestId("admin-promo-created");
    expect(created.textContent).toContain("SPRING25");
    await waitFor(() => expect(fetchPromosMock.mock.calls.length).toBeGreaterThan(1));
  });

  it("says creating a discount charges nobody", async () => {
    await renderPage([]);
    expect(screen.getByTestId("admin-promos-money-note").textContent).toMatch(
      /charges nobody|no (money|one is charged)|only.*redeem/i,
    );
  });
});

describe("deactivation is not deletion", () => {
  it("deactivates through the API and never calls it a delete", async () => {
    await renderPage();
    deactivatePromoMock.mockResolvedValue({ promotionCodeId: "promo_1", active: false });
    const button = await screen.findByTestId("admin-promo-deactivate-promo_1");
    expect(button.textContent).toMatch(/deactivate/i);
    expect(button.textContent).not.toMatch(/delete/i);

    fireEvent.click(button);
    // Turning off a live discount is a deliberate act — confirm first.
    fireEvent.click(await screen.findByTestId("admin-promo-deactivate-confirm"));
    await waitFor(() => expect(deactivatePromoMock).toHaveBeenCalledWith("promo_1"));
  });

  it("offers no deactivate button on an already-inactive code", async () => {
    await renderPage([promo({ active: false })]);
    await screen.findByTestId("admin-promo-row-promo_1");
    expect(screen.queryByTestId("admin-promo-deactivate-promo_1")).toBeNull();
  });

  it("says the redemption history survives a deactivation", async () => {
    await renderPage();
    fireEvent.click(await screen.findByTestId("admin-promo-deactivate-promo_1"));
    const confirm = await screen.findByTestId("admin-promo-deactivate-panel");
    expect(confirm.textContent).toMatch(/history|already used|redeem/i);
  });
});
