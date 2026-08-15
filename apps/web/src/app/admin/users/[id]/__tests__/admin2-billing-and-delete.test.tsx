// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-2 (a)+(b) — the user detail page's billing truth panel, the
 * negotiated-price form, and the delete/restore flow.
 *
 * RED-first: none of these three surfaces exist in this tree yet.
 *
 * WHY THE BILLING PANEL IS TWO COLUMNS AND NOT ONE NUMBER. The owner account
 * is the live proof that the local `Subscription` row and Stripe can disagree:
 * a stale `pro/active` row with nothing cancellable behind it at Stripe.
 * Rendering either side alone — or worse, reconciling them into one figure —
 * hides exactly the discrepancy an admin is here to resolve. So the panel shows
 * both, states the verdict, and treats "Stripe could not be read" as its own
 * third state rather than as "Stripe has nothing" (which looks identical and
 * could talk an admin into clearing a live customer's row).
 *
 * WHY DELETE ASKS FOR THE EMAIL. BE-1 matches `confirmEmail` server-side and
 * 422s a mismatch, so a mis-routed id cannot delete the wrong person. The UI
 * mirrors that gate rather than relying on it alone. The admin/owner refusal is
 * a SERVER guard (409) — the specs below pin that it is surfaced honestly, and
 * do not pretend the button's absence is the protection.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../../lib/api/client";

const useParamsMock = vi.fn();
vi.mock("next/navigation", () => ({ useParams: () => useParamsMock() }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)}>{children}</a>
  ),
}));

const fetchAdminUserMock = vi.fn();
const fetchUserAuditLogMock = vi.fn();
const deleteAdminUserMock = vi.fn();
const restoreAdminUserMock = vi.fn();

vi.mock("../../../../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../../lib/api/admin")>();
  return {
    ...actual,
    fetchAdminUser: (...a: unknown[]) => fetchAdminUserMock(...a),
    fetchUserAuditLog: (...a: unknown[]) => fetchUserAuditLogMock(...a),
    deleteAdminUser: (...a: unknown[]) => deleteAdminUserMock(...a),
    restoreAdminUser: (...a: unknown[]) => restoreAdminUserMock(...a),
    setEntitlementOverride: vi.fn(),
    setUserPassword: vi.fn(),
    updateUserIdentity: vi.fn(),
    cancelUserSubscription: vi.fn(),
    refundUserSubscription: vi.fn(),
    setSpendCap: vi.fn(),
    setSuspended: vi.fn(),
  };
});

const fetchUserBillingMock = vi.fn();
const reconcileLocalBillingMock = vi.fn();
const setCustomPriceMock = vi.fn();

vi.mock("../../../../../lib/api/adminBilling", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../../lib/api/adminBilling")>();
  return {
    ...actual,
    fetchUserBilling: (...a: unknown[]) => fetchUserBillingMock(...a),
    reconcileLocalBilling: (...a: unknown[]) => reconcileLocalBillingMock(...a),
    setCustomPrice: (...a: unknown[]) => setCustomPriceMock(...a),
  };
});

// eslint-disable-next-line import/first
import AdminUserDetailPage from "../page";

const USER_ID = "user-abc-123";
const EMAIL = "jamie@example.com";

function detail(overrides: Record<string, unknown> = {}) {
  return {
    user: {
      id: USER_ID,
      email: EMAIL,
      name: "Jamie Rivera",
      username: null,
      isAdmin: false,
      suspended: false,
      deletedAt: null,
      mustChangePassword: false,
      plan: "pro",
      subStatus: "active",
      signupAt: "2026-01-01T00:00:00Z",
      lastLoginAt: "2026-07-01T00:00:00Z",
      spendUsd: 4.2,
      runCount: 3,
      currency: "USD",
    },
    subscription: {
      planId: "pro",
      status: "active",
      billingInterval: "month",
      currentPeriodEnd: "2026-09-01T00:00:00Z",
      cancelAtPeriodEnd: false,
    },
    quota: null,
    recentRuns: [],
    spendUsd: 4.2,
    runCount: 3,
    currency: "USD",
    entitlement: {
      unlimited: false,
      entitled: true,
      source: "plan",
      isAdmin: false,
      planId: "pro",
      activePaid: true,
      overrideActive: false,
      overrideKind: null,
      overridePlanId: null,
      overrideNote: null,
      overrideSetBy: null,
      overrideSetAt: null,
    },
    ...overrides,
  };
}

/** Local row and Stripe AGREE — the ordinary, healthy case. */
function billingInAgreement(overrides: Record<string, unknown> = {}) {
  return {
    userId: USER_ID,
    currency: "AUD",
    local: {
      planId: "pro",
      status: "active",
      billingInterval: "month",
      stripeCustomerId: "cus_live_1",
      stripeSubscriptionId: "sub_live_1",
      currentPeriodStart: "2026-08-01T00:00:00Z",
      currentPeriodEnd: "2026-09-01T00:00:00Z",
      cancelAtPeriodEnd: false,
      customPrice: null,
      updatedAt: "2026-08-01T00:00:00Z",
    },
    stripe: {
      available: true,
      reason: null,
      customer: {
        id: "cus_live_1",
        email: EMAIL,
        name: "Jamie Rivera",
        delinquent: false,
        created: "2026-01-01T00:00:00Z",
      },
      subscription: {
        id: "sub_live_1",
        status: "active",
        cancelAtPeriodEnd: false,
        currentPeriodEnd: "2026-09-01T00:00:00Z",
        amountAud: 39,
        interval: "month",
        priceId: "price_1",
      },
      subscriptions: [{ id: "sub_live_1", status: "active" }],
      invoices: [
        { id: "in_1", amountPaidAud: 39, status: "paid", created: "2026-08-01T00:00:00Z" },
      ],
      paymentMethod: { brand: "visa", last4: "4242", expMonth: 12, expYear: 2029 },
    },
    mismatch: { evaluated: true, hasMismatch: false, reasons: [] },
    ...overrides,
  };
}

/** The owner's real state: a stale local paid row, nothing live at Stripe. */
function billingStaleLocalRow() {
  return {
    userId: USER_ID,
    currency: "AUD",
    local: {
      planId: "pro",
      status: "active",
      billingInterval: "month",
      stripeCustomerId: null,
      stripeSubscriptionId: null,
      currentPeriodStart: null,
      currentPeriodEnd: null,
      cancelAtPeriodEnd: false,
      customPrice: null,
      updatedAt: "2026-02-01T00:00:00Z",
    },
    stripe: {
      available: true,
      reason: null,
      customer: null,
      subscription: null,
      subscriptions: [],
      invoices: [],
      paymentMethod: null,
      note: "No Stripe customer id is recorded locally for this account.",
    },
    mismatch: {
      evaluated: true,
      hasMismatch: true,
      reasons: [
        "The local row shows a paid, billable plan but Stripe has no live subscription for this customer.",
      ],
    },
  };
}

async function renderPage(
  d: ReturnType<typeof detail> = detail(),
  billing: unknown = billingInAgreement(),
) {
  useParamsMock.mockReturnValue({ id: USER_ID });
  fetchAdminUserMock.mockResolvedValue(d);
  fetchUserAuditLogMock.mockResolvedValue({ entries: [], total: 0, limit: 25, offset: 0 });
  if (billing instanceof Error) fetchUserBillingMock.mockRejectedValue(billing);
  else fetchUserBillingMock.mockResolvedValue(billing);
  render(<AdminUserDetailPage />);
  await screen.findByTestId("admin-entitlement");
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

describe("billing panel — local row and Stripe, side by side", () => {
  it("renders both sides from the API, never one merged figure", async () => {
    await renderPage();
    const local = await screen.findByTestId("admin-billing-local");
    const stripe = screen.getByTestId("admin-billing-stripe");
    expect(local.textContent).toContain("pro");
    expect(local.textContent).toContain("sub_live_1");
    expect(stripe.textContent).toContain("active");
    // The masked payment method — brand + last four, the only fields Stripe gives.
    expect(stripe.textContent).toContain("4242");
  });

  it("shows an agreeing comparison as a match", async () => {
    await renderPage();
    const badge = await screen.findByTestId("admin-billing-mismatch");
    expect(badge.getAttribute("data-state")).toBe("match");
  });

  it("shows the owner's stale-row case as a mismatch, with the API's reasons", async () => {
    await renderPage(detail(), billingStaleLocalRow());
    const badge = await screen.findByTestId("admin-billing-mismatch");
    expect(badge.getAttribute("data-state")).toBe("mismatch");
    expect(badge.textContent).toMatch(/mismatch/i);
    expect(screen.getByTestId("admin-billing-mismatch-reasons").textContent).toContain(
      "Stripe has no live subscription",
    );
  });

  it("never claims a comparison it did not make (evaluated:false)", async () => {
    await renderPage(
      detail(),
      billingInAgreement({
        stripe: {
          available: false,
          reason: "Stripe read failed (APIConnectionError).",
          customer: null,
          subscription: null,
          subscriptions: [],
          invoices: [],
          paymentMethod: null,
        },
        mismatch: { evaluated: false, hasMismatch: false, reasons: [] },
      }),
    );
    const badge = await screen.findByTestId("admin-billing-mismatch");
    expect(badge.getAttribute("data-state")).toBe("not-evaluated");
    expect(badge.textContent).not.toMatch(/^match/i);
    // The API's own reason is repeated verbatim rather than paraphrased away.
    expect(screen.getByTestId("admin-billing-stripe-unavailable").textContent).toContain(
      "Stripe read failed (APIConnectionError).",
    );
  });

  it("keeps the rest of the page alive when the billing read itself fails", async () => {
    await renderPage(detail(), new ApiError("Billing surface unavailable", 500));
    expect(await screen.findByTestId("admin-billing-error")).toBeTruthy();
    // The panel failing must not blank the account it belongs to.
    expect(screen.getByTestId("admin-entitlement")).toBeTruthy();
  });
});

describe("reconcile-local (no Stripe mutation, ever)", () => {
  it("is offered only where there is a stale local row to clear", async () => {
    await renderPage(
      detail(),
      billingInAgreement({
        local: {
          planId: "free",
          status: "canceled",
          billingInterval: null,
          stripeCustomerId: null,
          stripeSubscriptionId: null,
          currentPeriodStart: null,
          currentPeriodEnd: null,
          cancelAtPeriodEnd: false,
          customPrice: null,
          updatedAt: "2026-08-01T00:00:00Z",
        },
      }),
    );
    await screen.findByTestId("admin-billing-local");
    expect(screen.queryByTestId("admin-billing-reconcile")).toBeNull();
    expect(screen.getByTestId("admin-billing-reconcile-na")).toBeTruthy();
  });

  it("requires a confirmation before it clears anything", async () => {
    await renderPage(detail(), billingStaleLocalRow());
    fireEvent.click(await screen.findByTestId("admin-billing-reconcile"));
    // Opening the confirmation must not have called the API yet.
    expect(reconcileLocalBillingMock).not.toHaveBeenCalled();
    const confirm = await screen.findByTestId("admin-billing-reconcile-confirm-panel");
    expect(confirm.textContent).toMatch(/no Stripe|local/i);

    reconcileLocalBillingMock.mockResolvedValue({
      userId: USER_ID,
      reconciled: true,
      before: { planId: "pro", status: "active" },
      after: { planId: "free", status: "canceled" },
      stripeChecked: "no_customer_on_file",
      stripeMutated: false,
    });
    fireEvent.click(within(confirm).getByTestId("admin-billing-reconcile-confirm"));
    await waitFor(() => expect(reconcileLocalBillingMock).toHaveBeenCalledWith(USER_ID));
  });

  it("cancelling the confirmation calls nothing", async () => {
    await renderPage(detail(), billingStaleLocalRow());
    fireEvent.click(await screen.findByTestId("admin-billing-reconcile"));
    fireEvent.click(await screen.findByTestId("admin-billing-reconcile-cancel"));
    await waitFor(() =>
      expect(screen.queryByTestId("admin-billing-reconcile-confirm-panel")).toBeNull(),
    );
    expect(reconcileLocalBillingMock).not.toHaveBeenCalled();
  });

  it("surfaces the 'Stripe shows a live subscription' 409 as a refusal", async () => {
    await renderPage(detail(), billingStaleLocalRow());
    fireEvent.click(await screen.findByTestId("admin-billing-reconcile"));
    reconcileLocalBillingMock.mockRejectedValue(
      new ApiError(
        "Stripe shows a live subscription for this customer (sub_9, status 'active') — the local row is not stale. Cancel or refund it instead.",
        409,
      ),
    );
    fireEvent.click(await screen.findByTestId("admin-billing-reconcile-confirm"));
    await waitFor(() => {
      const text = screen.getByTestId("admin-user-error").textContent ?? "";
      expect(text).toContain("Not applicable");
      expect(text).toContain("the local row is not stale");
    });
  });
});

describe("negotiated custom price", () => {
  it("sends the amount and interval, and says the change is not immediate", async () => {
    await renderPage();
    setCustomPriceMock.mockResolvedValue({
      userId: USER_ID,
      amountAud: 24.5,
      interval: "month",
      currency: "AUD",
      planId: "pro",
      stripePriceId: "price_new",
      stripeSubscriptionId: "sub_live_1",
      prorationBehavior: "none",
      effectiveFrom: "next_renewal",
      note: "The existing subscription was repriced in place with no proration.",
    });
    fireEvent.change(await screen.findByLabelText("Custom amount (AUD)"), {
      target: { value: "24.50" },
    });
    fireEvent.change(screen.getByLabelText("Billing interval"), { target: { value: "year" } });
    fireEvent.click(screen.getByTestId("admin-custom-price-save"));

    await waitFor(() => expect(setCustomPriceMock).toHaveBeenCalled());
    expect(setCustomPriceMock.mock.calls[0]?.[1]).toEqual({ amountAud: 24.5, interval: "year" });
    await waitFor(() => {
      const notice = screen.getByTestId("admin-user-notice").textContent ?? "";
      expect(notice).toMatch(/next renewal/i);
      expect(notice).toMatch(/no.*(charge|proration)/i);
    });
  });

  it("rejects a non-positive amount client-side without calling the API", async () => {
    await renderPage();
    fireEvent.change(await screen.findByLabelText("Custom amount (AUD)"), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByTestId("admin-custom-price-save"));
    await waitFor(() => expect(screen.getByTestId("admin-user-error")).toBeTruthy());
    expect(setCustomPriceMock).not.toHaveBeenCalled();
  });

  it("surfaces the no-live-subscription 409 through the 'Not applicable:' pattern", async () => {
    await renderPage();
    setCustomPriceMock.mockRejectedValue(
      new ApiError(
        "This user has no live Stripe subscription to reprice — use an entitlement override instead.",
        409,
      ),
    );
    fireEvent.change(await screen.findByLabelText("Custom amount (AUD)"), {
      target: { value: "19" },
    });
    fireEvent.click(screen.getByTestId("admin-custom-price-save"));
    await waitFor(() => {
      const text = screen.getByTestId("admin-user-error").textContent ?? "";
      expect(text).toContain("Not applicable");
      expect(text).toContain("entitlement override");
    });
  });

  it("shows an already-negotiated price as the current one", async () => {
    await renderPage(
      detail(),
      billingInAgreement({
        local: {
          ...billingInAgreement().local,
          customPrice: {
            amountAud: 15,
            interval: "month",
            stripePriceId: "price_custom",
            setAt: "2026-08-10T00:00:00Z",
            setBy: "admin-1",
          },
        },
      }),
    );
    const panel = await screen.findByTestId("admin-custom-price-current");
    expect(panel.textContent).toContain("15");
    expect(panel.textContent).toMatch(/month/i);
  });
});

describe("delete user (soft, typed confirmation, server-guarded)", () => {
  it("keeps the confirm button disabled until the exact email is typed", async () => {
    await renderPage();
    fireEvent.click(await screen.findByTestId("admin-delete-user"));
    const confirmBtn = (await screen.findByTestId(
      "admin-delete-user-confirm",
    )) as HTMLButtonElement;
    expect(confirmBtn.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Type the email address to confirm deletion"), {
      target: { value: "wrong@example.com" },
    });
    expect((screen.getByTestId("admin-delete-user-confirm") as HTMLButtonElement).disabled).toBe(
      true,
    );

    fireEvent.change(screen.getByLabelText("Type the email address to confirm deletion"), {
      target: { value: EMAIL.toUpperCase() },
    });
    expect((screen.getByTestId("admin-delete-user-confirm") as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("sends the typed confirmation to the API and reports the soft-delete honestly", async () => {
    await renderPage();
    deleteAdminUserMock.mockResolvedValue({
      userId: USER_ID,
      deleted: true,
      mode: "soft",
      deletedAt: "2026-08-15T01:00:00Z",
      suspended: true,
      note: "Soft delete: the account is suspended and hidden from normal use.",
    });
    fireEvent.click(await screen.findByTestId("admin-delete-user"));
    fireEvent.change(screen.getByLabelText("Type the email address to confirm deletion"), {
      target: { value: EMAIL },
    });
    fireEvent.click(screen.getByTestId("admin-delete-user-confirm"));

    await waitFor(() => expect(deleteAdminUserMock).toHaveBeenCalledWith(USER_ID, EMAIL));
    await waitFor(() => {
      const notice = screen.getByTestId("admin-user-notice").textContent ?? "";
      // "Deleted" here means soft — the page must not imply the data is gone.
      expect(notice).toMatch(/soft|reversible|restore/i);
    });
  });

  it("surfaces the admin/owner 409 refusal as the server's own words", async () => {
    await renderPage();
    deleteAdminUserMock.mockRejectedValue(
      new ApiError("This account is an administrator and cannot be deleted.", 409),
    );
    fireEvent.click(await screen.findByTestId("admin-delete-user"));
    fireEvent.change(screen.getByLabelText("Type the email address to confirm deletion"), {
      target: { value: EMAIL },
    });
    fireEvent.click(screen.getByTestId("admin-delete-user-confirm"));

    await waitFor(() => {
      const text = screen.getByTestId("admin-user-error").textContent ?? "";
      expect(text).toContain("Not applicable");
      expect(text).toContain("administrator");
    });
  });

  it("shows an already-deleted account as deleted, and offers restore instead", async () => {
    await renderPage(
      detail({
        user: { ...detail().user, deletedAt: "2026-08-14T00:00:00Z", suspended: true },
      }),
    );
    expect(await screen.findByTestId("admin-user-deleted-banner")).toBeTruthy();
    expect(screen.queryByTestId("admin-delete-user")).toBeNull();

    restoreAdminUserMock.mockResolvedValue({
      userId: USER_ID,
      deleted: false,
      deletedAt: null,
      suspended: true,
      note: "Restored. The account is still suspended — lift it deliberately.",
    });
    fireEvent.click(screen.getByTestId("admin-restore-user"));
    await waitFor(() => expect(restoreAdminUserMock).toHaveBeenCalledWith(USER_ID));
    // Restore does NOT lift suspension; the notice must not imply it did.
    await waitFor(() =>
      expect(screen.getByTestId("admin-user-notice").textContent).toMatch(/still suspended/i),
    );
  });
});

describe("REGRESSION — the state-aware subscription actions from 29ea6bc survive", () => {
  it("an admin account still shows the exemption note and no cancel/refund", async () => {
    await renderPage(detail({ user: { ...detail().user, isAdmin: true } }));
    expect(screen.getByTestId("admin-sub-exempt")).toBeTruthy();
    expect(screen.queryByTestId("admin-cancel-at-period-end")).toBeNull();
    expect(screen.queryByTestId("admin-refund")).toBeNull();
  });

  it("an account with no Stripe subscription still gets the entitlement hint", async () => {
    await renderPage(detail({ subscription: null }));
    expect(screen.getByTestId("admin-sub-none")).toBeTruthy();
    expect(screen.queryByTestId("admin-cancel-at-period-end")).toBeNull();
    expect(screen.getByTestId("admin-refund")).toBeTruthy();
  });

  it("an account with a live subscription still keeps both cancel actions", async () => {
    await renderPage();
    expect(screen.getByTestId("admin-cancel-at-period-end")).toBeTruthy();
    expect(screen.getByTestId("admin-cancel-now")).toBeTruthy();
  });
});
