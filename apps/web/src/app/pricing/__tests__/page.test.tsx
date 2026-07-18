// @vitest-environment jsdom
/**
 * /pricing page (GAP-P6-PRICING-001).
 *
 * Renders the real component so the defects a backend-only test cannot see —
 * a tier not rendered, a missing GST line, a Subscribe CTA that doesn't reach
 * checkout — are caught at the layer where they would ship. Plain DOM/vitest
 * matchers only (no jest-dom), matching the MarketPulse/signup test precedent.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../lib/api/client";

const fetchPlansMock = vi.fn();
const startCheckoutMock = vi.fn();
vi.mock("../../../lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/billing")>();
  return {
    ...actual,
    fetchPlans: (...args: unknown[]) => fetchPlansMock(...args),
    startCheckout: (...args: unknown[]) => startCheckoutMock(...args),
  };
});

// eslint-disable-next-line import/first
import PricingPage from "../page";

const PLANS = {
  currency: "AUD",
  gstIncluded: true,
  plans: [
    {
      id: "free", name: "Free", modelTier: "light", runsPerMonth: 5,
      monthly: { total: 0, gst: 0, net: 0 }, annual: null,
      features: ["5 tailored agent runs / month", "Light model tier"], purchasable: false,
    },
    {
      id: "starter", name: "Starter", modelTier: "standard", runsPerMonth: 30,
      monthly: { total: 19, gst: 1.73, net: 17.27 },
      annual: { total: 179, gst: 16.27, net: 162.73 },
      features: ["30 tailored agent runs / month", "Standard model tier"], purchasable: true,
    },
    {
      id: "pro", name: "Pro", modelTier: "advanced", runsPerMonth: 100,
      monthly: { total: 39, gst: 3.55, net: 35.45 },
      annual: { total: 359, gst: 32.64, net: 326.36 },
      features: ["100 tailored agent runs / month", "Advanced model tier"], purchasable: true,
    },
    {
      id: "power", name: "Power", modelTier: "premium", runsPerMonth: 300,
      monthly: { total: 69, gst: 6.27, net: 62.73 },
      annual: { total: 649, gst: 59.0, net: 590.0 },
      features: ["300 tailored agent runs / month", "Full model access"], purchasable: true,
    },
  ],
};

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  fetchPlansMock.mockReset();
  startCheckoutMock.mockReset();
  window.localStorage.clear();
});

describe("PricingPage", () => {
  it("renders all four ratified tiers with GST-inclusive prices and a GST line", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    render(<PricingPage />);

    await waitFor(() => {
      expect(screen.getByTestId("pricing-tier-free")).not.toBeNull();
    });
    for (const id of ["free", "starter", "pro", "power"]) {
      expect(screen.getByTestId(`pricing-tier-${id}`)).not.toBeNull();
    }
    // GST-inclusive monthly price + a GST breakdown line for a paid tier.
    expect(screen.getByTestId("price-starter").textContent).toContain("19");
    expect(screen.getByTestId("gst-starter").textContent).toContain("GST");
  });

  it("Subscribe CTA starts checkout and redirects to the Stripe session URL", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    startCheckoutMock.mockResolvedValue({
      checkoutUrl: "https://checkout.stripe.com/c/pay/cs_test_abc",
      sessionId: "cs_test_abc",
    });
    // window.location.href is assigned by the handler — make it observable.
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { set href(v: string) { hrefSetter(v); }, get href() { return ""; } },
    });

    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("subscribe-pro"));
    fireEvent.click(screen.getByTestId("subscribe-pro"));

    await waitFor(() => {
      expect(startCheckoutMock).toHaveBeenCalledWith("pro", "month");
    });
    await waitFor(() => {
      expect(hrefSetter).toHaveBeenCalledWith("https://checkout.stripe.com/c/pay/cs_test_abc");
    });
  });

  it("Annual toggle switches paid tiers to their annual price", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("interval-year"));
    fireEvent.click(screen.getByTestId("interval-year"));
    await waitFor(() => {
      expect(screen.getByTestId("price-pro").textContent).toContain("359");
    });
  });

  it("MV-pricing-002: never claims a per-plan model-tier/model-access differentiation that doesn't exist", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("pricing-tier-power"));

    const bodyText = document.body.textContent ?? "";
    // None of the fixture's model-tier feature bullets ("Light model tier",
    // "Advanced model tier", "Full model access", ...) may render anywhere.
    expect(bodyText).not.toMatch(/model tier/i);
    expect(bodyText).not.toMatch(/model access/i);
    // The honest differentiator (run quota, not model quality) is stated.
    expect(bodyText).toMatch(/same ai models/i);
  });

  it("MV-pricing-004: shows a distinct honest message for a 400 (no Stripe price configured)", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    startCheckoutMock.mockRejectedValue(
      new ApiError("POST /billing/checkout failed (400): no Stripe price configured", 400),
    );
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("subscribe-starter"));
    fireEvent.click(screen.getByTestId("subscribe-starter"));

    await waitFor(() => screen.getByTestId("checkout-error"));
    const msg = screen.getByTestId("checkout-error").textContent ?? "";
    expect(msg).not.toMatch(/could not start checkout\. please try again\.$/i);
    expect(msg.toLowerCase()).toMatch(/not available for purchase|not yet configured/);
  });

  it("MV-pricing-004: a 429 shows a distinct message honoring Retry-After, not the generic message", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    startCheckoutMock.mockRejectedValue(
      new ApiError("POST /billing/checkout failed (429): rate limited", 429, 90),
    );
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("subscribe-starter"));
    fireEvent.click(screen.getByTestId("subscribe-starter"));

    await waitFor(() => screen.getByTestId("checkout-error"));
    const msg = screen.getByTestId("checkout-error").textContent ?? "";
    expect(msg.toLowerCase()).toMatch(/too many checkout attempts/);
    expect(msg).toMatch(/2 minutes/);
  });

  it("MV-pricing-005: the Free CTA is session-aware — routes an authenticated visitor to /dashboard, not /signup", async () => {
    window.localStorage.setItem("aether_token", "fake.jwt.token");
    fetchPlansMock.mockResolvedValue(PLANS);
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("subscribe-free"));

    await waitFor(() => {
      expect(screen.getByTestId("subscribe-free").getAttribute("href")).toBe("/dashboard");
    });
    expect(screen.getByTestId("subscribe-free").textContent).toMatch(/dashboard/i);
  });

  it("MV-pricing-005: an unauthenticated visitor's Free CTA still links to /signup", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("subscribe-free"));

    expect(screen.getByTestId("subscribe-free").getAttribute("href")).toBe("/signup");
  });
});
