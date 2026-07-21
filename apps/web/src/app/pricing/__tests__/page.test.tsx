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
const fetchSubscriptionMock = vi.fn();
vi.mock("../../../lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/billing")>();
  return {
    ...actual,
    fetchPlans: (...args: unknown[]) => fetchPlansMock(...args),
    startCheckout: (...args: unknown[]) => startCheckoutMock(...args),
    fetchSubscription: (...args: unknown[]) => fetchSubscriptionMock(...args),
  };
});

/** No subscription on record — the default for an unauthenticated/free visitor. */
const NO_SUBSCRIPTION = {
  plan: null,
  status: null,
  interval: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  quota: null,
};

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

// Some tests below replace `window.location` with a plain href-capturing stub
// (to observe a redirect) via Object.defineProperty — jsdom's `window`
// persists across `it()`s within this file, so without restoring the real
// descriptor afterward, EVERY later test would inherit a `window.location`
// with no working `search`/`pathname` (breaking the ?checkout=cancel and
// current-plan tests below, which read the real URL).
const originalLocationDescriptor = Object.getOwnPropertyDescriptor(window, "location");

beforeEach(() => {
  window.localStorage.clear();
  fetchSubscriptionMock.mockResolvedValue(NO_SUBSCRIPTION);
});

afterEach(() => {
  cleanup();
  fetchPlansMock.mockReset();
  startCheckoutMock.mockReset();
  fetchSubscriptionMock.mockReset();
  window.localStorage.clear();
  if (originalLocationDescriptor) {
    Object.defineProperty(window, "location", originalLocationDescriptor);
  }
  window.history.replaceState(null, "", "/pricing");
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

  it("MV-privacy-policy-001/MV-terms-001: shows a footer linking to /privacy-policy and /terms", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("pricing-tier-free"));
    const privacyLink = screen.getByRole("link", { name: /privacy policy/i });
    const termsLink = screen.getByRole("link", { name: /^terms$/i });
    expect(privacyLink.getAttribute("href")).toBe("/privacy-policy");
    expect(termsLink.getAttribute("href")).toBe("/terms");
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

describe("PricingPage — checkout=cancel notice (PAY-R3-05)", () => {
  it("shows a dismissible 'no charge was made' notice when the URL carries ?checkout=cancel, and strips the param", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    window.history.replaceState(null, "", "/pricing?checkout=cancel");

    render(<PricingPage />);

    await waitFor(() => screen.getByTestId("checkout-cancel-notice"));
    expect(screen.getByTestId("checkout-cancel-notice").textContent ?? "").toMatch(
      /canceled.*not been charged/i,
    );
    expect(window.location.search).toBe("");

    fireEvent.click(screen.getByTestId("checkout-cancel-notice-dismiss"));
    expect(screen.queryByTestId("checkout-cancel-notice")).toBeNull();
  });

  it("shows no cancel notice on a plain visit (no ?checkout param)", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("pricing-tier-free"));
    expect(screen.queryByTestId("checkout-cancel-notice")).toBeNull();
  });
});

describe("PricingPage — plan-switch UI for an existing paid subscriber (PAY-R3-01/03)", () => {
  const PRO_SUBSCRIPTION = {
    plan: { id: "pro", name: "Pro", modelTier: "advanced" },
    status: "active",
    interval: "month",
    currentPeriodEnd: "2026-08-01T00:00:00Z",
    cancelAtPeriodEnd: false,
    quota: { runsUsed: 10, runsAllowed: 100, spendUsedUsd: 1, spendCapUsd: 15, periodEnd: null },
  };

  it("shows a 'Current plan' badge on the subscriber's own plan and 'Switch to this plan' on the others", async () => {
    window.localStorage.setItem("aether_token", "fake.jwt.token");
    fetchPlansMock.mockResolvedValue(PLANS);
    fetchSubscriptionMock.mockResolvedValue(PRO_SUBSCRIPTION);

    render(<PricingPage />);

    await waitFor(() => screen.getByTestId("current-plan-badge-pro"));
    // The subscriber's own plan: badge + a disabled "Current plan" CTA, not Subscribe.
    expect(screen.getByTestId("subscribe-pro").textContent).toMatch(/current plan/i);
    expect((screen.getByTestId("subscribe-pro") as HTMLButtonElement).disabled).toBe(true);

    // Every other PAID tier relabels to "Switch to this plan" instead of "Subscribe to X".
    expect(screen.getByTestId("subscribe-starter").textContent).toMatch(/switch to this plan/i);
    expect(screen.getByTestId("subscribe-power").textContent).toMatch(/switch to this plan/i);
    expect(screen.queryByTestId("current-plan-badge-starter")).toBeNull();
    expect(screen.queryByTestId("current-plan-badge-power")).toBeNull();
  });

  it("a logged-out visitor sees plain 'Subscribe to X' CTAs with no current-plan badges", async () => {
    fetchPlansMock.mockResolvedValue(PLANS);
    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("subscribe-starter"));

    expect(screen.getByTestId("subscribe-starter").textContent).toMatch(/subscribe to starter/i);
    expect(screen.queryByTestId("current-plan-badge-starter")).toBeNull();
    expect(screen.queryByTestId("current-plan-badge-free")).toBeNull();
  });

  it("interval-only switch: toggling to Annual on the subscriber's OWN plan shows 'Switch to this plan' (enabled), not a disabled 'Current plan'", async () => {
    // The backend's switch-in-place path also supports switching JUST the
    // billing interval on the same plan (monthly Pro -> annual Pro) — this
    // must stay a clickable action, not get disabled by plan-id matching alone.
    window.localStorage.setItem("aether_token", "fake.jwt.token");
    fetchPlansMock.mockResolvedValue(PLANS);
    fetchSubscriptionMock.mockResolvedValue(PRO_SUBSCRIPTION); // interval: "month"

    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("current-plan-badge-pro"));

    fireEvent.click(screen.getByTestId("interval-year"));

    await waitFor(() => {
      expect(screen.getByTestId("subscribe-pro").textContent).toMatch(/switch to this plan/i);
    });
    expect((screen.getByTestId("subscribe-pro") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("current-plan-badge-pro")).toBeNull();
  });

  it("an authed FREE-plan user sees plain 'Subscribe to X' CTAs (not 'Switch'), since they hold no paid plan", async () => {
    window.localStorage.setItem("aether_token", "fake.jwt.token");
    fetchPlansMock.mockResolvedValue(PLANS);
    fetchSubscriptionMock.mockResolvedValue({
      plan: { id: "free", name: "Free", modelTier: "basic" },
      status: "active",
      interval: null,
      currentPeriodEnd: null,
      cancelAtPeriodEnd: false,
      quota: { runsUsed: 1, runsAllowed: 5, spendUsedUsd: 0, spendCapUsd: 1, periodEnd: null },
    });

    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("current-plan-badge-free"));

    expect(screen.getByTestId("subscribe-starter").textContent).toMatch(/subscribe to starter/i);
  });

  it("handles a {switched:true} checkout result: shows the message, refreshes state, and never redirects", async () => {
    window.localStorage.setItem("aether_token", "fake.jwt.token");
    fetchPlansMock.mockResolvedValue(PLANS);
    fetchSubscriptionMock
      .mockResolvedValueOnce(PRO_SUBSCRIPTION) // initial load
      .mockResolvedValueOnce({
        ...PRO_SUBSCRIPTION,
        plan: { id: "power", name: "Power", modelTier: "premium" },
      }); // post-switch refresh
    startCheckoutMock.mockResolvedValue({
      switched: true,
      planId: "power",
      message: "Switched to Power — no second charge, your existing subscription was updated.",
    });
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { set href(v: string) { hrefSetter(v); }, get href() { return ""; } },
    });

    render(<PricingPage />);
    await waitFor(() => screen.getByTestId("current-plan-badge-pro"));

    fireEvent.click(screen.getByTestId("subscribe-power"));

    await waitFor(() => screen.getByTestId("plan-switch-notice"));
    expect(screen.getByTestId("plan-switch-notice").textContent ?? "").toMatch(
      /switched to power/i,
    );
    // Never redirected — the switch happened server-side, no Stripe Checkout involved.
    expect(hrefSetter).not.toHaveBeenCalled();

    // Badge moves to the new plan once subscription state is refreshed.
    await waitFor(() => screen.getByTestId("current-plan-badge-power"));
    expect(screen.queryByTestId("current-plan-badge-pro")).toBeNull();

    fireEvent.click(screen.getByTestId("plan-switch-notice-dismiss"));
    expect(screen.queryByTestId("plan-switch-notice")).toBeNull();
  });
});
