// @vitest-environment jsdom
/**
 * ADMIN-FULL — the /admin/users/[id] user-management panel.
 *
 * USER MANDATE (2026-08-14): an admin can change the plan, subscription,
 * username and password of ANY user. These specs pin that the panel:
 *
 *  * sends an ENTITLEMENT OVERRIDE (not a Stripe mutation) for a plan change,
 *    and shows an active override VISIBLY as an override next to the real
 *    billing truth — the billing invariant that an override must never be
 *    mistakable for a payment;
 *  * routes Stripe-linked actions (cancel at period end / refund) to the
 *    backend's existing billing paths;
 *  * sets a password without ever rendering it back, and renders the per-user
 *    audit trail the backend writes.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../../lib/api/client";

const useParamsMock = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => useParamsMock(),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)}>{children}</a>
  ),
}));

const fetchAdminUserMock = vi.fn();
const fetchUserAuditLogMock = vi.fn();
const setEntitlementOverrideMock = vi.fn();
const setUserPasswordMock = vi.fn();
const updateUserIdentityMock = vi.fn();
const cancelUserSubscriptionMock = vi.fn();
const refundUserSubscriptionMock = vi.fn();

vi.mock("../../../../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../../lib/api/admin")>();
  return {
    ...actual,
    fetchAdminUser: (...a: unknown[]) => fetchAdminUserMock(...a),
    fetchUserAuditLog: (...a: unknown[]) => fetchUserAuditLogMock(...a),
    setEntitlementOverride: (...a: unknown[]) => setEntitlementOverrideMock(...a),
    setUserPassword: (...a: unknown[]) => setUserPasswordMock(...a),
    updateUserIdentity: (...a: unknown[]) => updateUserIdentityMock(...a),
    cancelUserSubscription: (...a: unknown[]) => cancelUserSubscriptionMock(...a),
    refundUserSubscription: (...a: unknown[]) => refundUserSubscriptionMock(...a),
    setSpendCap: vi.fn(),
    setSuspended: vi.fn(),
  };
});

// eslint-disable-next-line import/first
import AdminUserDetailPage from "../page";

const USER_ID = "user-abc-123";

function detail(overrides: Record<string, unknown> = {}) {
  return {
    user: {
      id: USER_ID,
      email: "jamie@example.com",
      name: "Jamie Rivera",
      username: null,
      isAdmin: false,
      suspended: false,
      plan: "free",
      subStatus: "active",
      signupAt: "2026-01-01T00:00:00Z",
      lastLoginAt: "2026-07-01T00:00:00Z",
      spendUsd: 4.2,
      runCount: 3,
      currency: "USD",
    },
    subscription: null,
    quota: {
      planId: "free",
      runsUsed: 3,
      runsAllowed: 5,
      spendUsedUsd: 0.4,
      spendCapUsd: 1,
      periodEnd: "2026-08-01T00:00:00Z",
      currency: "USD",
    },
    recentRuns: [],
    spendUsd: 4.2,
    runCount: 3,
    currency: "USD",
    entitlement: {
      unlimited: false,
      entitled: false,
      source: "plan",
      isAdmin: false,
      planId: "free",
      activePaid: false,
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

async function renderPage(d: ReturnType<typeof detail>) {
  useParamsMock.mockReturnValue({ id: USER_ID });
  fetchAdminUserMock.mockResolvedValue(d);
  fetchUserAuditLogMock.mockResolvedValue({ entries: [], total: 0, limit: 25, offset: 0 });
  render(<AdminUserDetailPage />);
  await waitFor(() => expect(fetchAdminUserMock).toHaveBeenCalled());
  await screen.findByTestId("admin-entitlement");
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("entitlement controls", () => {
  it("sends a tier override with the chosen plan and note", async () => {
    await renderPage(detail());
    setEntitlementOverrideMock.mockResolvedValue({ userId: USER_ID, entitlement: {} });

    fireEvent.change(screen.getByLabelText("Entitlement kind"), { target: { value: "tier" } });
    fireEvent.change(screen.getByLabelText("Override plan"), { target: { value: "power" } });
    fireEvent.change(screen.getByLabelText("Override note"), {
      target: { value: "support credit" },
    });
    fireEvent.click(screen.getByTestId("admin-save-entitlement"));

    await waitFor(() => expect(setEntitlementOverrideMock).toHaveBeenCalled());
    expect(setEntitlementOverrideMock.mock.calls[0]?.[1]).toEqual({
      kind: "tier",
      planId: "power",
      note: "support credit",
    });
  });

  it("clears an override with kind=none and sends no planId", async () => {
    await renderPage(
      detail({
        entitlement: {
          unlimited: false,
          entitled: true,
          source: "override",
          isAdmin: false,
          planId: "pro",
          activePaid: false,
          overrideActive: true,
          overrideKind: "comp",
          overridePlanId: "pro",
          overrideNote: "beta tester",
          overrideSetBy: "admin-1",
          overrideSetAt: "2026-08-14T00:00:00Z",
        },
      }),
    );
    setEntitlementOverrideMock.mockResolvedValue({ userId: USER_ID, entitlement: {} });

    fireEvent.change(screen.getByLabelText("Entitlement kind"), { target: { value: "none" } });
    fireEvent.click(screen.getByTestId("admin-save-entitlement"));

    await waitFor(() => expect(setEntitlementOverrideMock).toHaveBeenCalled());
    expect(setEntitlementOverrideMock.mock.calls[0]?.[1]).toMatchObject({ kind: "none" });
    expect(setEntitlementOverrideMock.mock.calls[0]?.[1]).not.toHaveProperty("planId");
  });

  it("shows an active override AS an override, beside the real billing truth", async () => {
    await renderPage(
      detail({
        entitlement: {
          unlimited: false,
          entitled: true,
          source: "override",
          isAdmin: false,
          planId: "pro",
          activePaid: false,
          overrideActive: true,
          overrideKind: "comp",
          overridePlanId: "pro",
          overrideNote: "beta tester",
          overrideSetBy: "admin-1",
          overrideSetAt: "2026-08-14T00:00:00Z",
        },
      }),
    );

    const flag = screen.getByTestId("admin-entitlement-override-flag").textContent ?? "";
    expect(flag).toMatch(/override active/i);
    expect(flag).toMatch(/comp/);
    expect(flag).toMatch(/not a payment/i);
    expect(screen.getByTestId("admin-entitlement-billing").textContent).toContain(
      "no active paid subscription",
    );
  });

  it("reports an unlimited account as enforcing no quota at all", async () => {
    await renderPage(
      detail({
        entitlement: {
          unlimited: true,
          entitled: true,
          source: "admin",
          isAdmin: true,
          planId: null,
          activePaid: false,
          overrideActive: false,
          overrideKind: null,
          overridePlanId: null,
          overrideNote: null,
          overrideSetBy: null,
          overrideSetAt: null,
        },
      }),
    );
    expect(screen.getByTestId("admin-entitlement-state").textContent).toMatch(/unlimited/i);
  });
});

const WITH_SUB = {
  subscription: { planId: "pro", status: "active", cancelAtPeriodEnd: false },
};

describe("Stripe-linked actions route through the billing service", () => {
  it("cancels at period end", async () => {
    await renderPage(detail(WITH_SUB));
    cancelUserSubscriptionMock.mockResolvedValue({
      userId: USER_ID,
      atPeriodEnd: true,
      cancelAtPeriodEnd: true,
      planId: "pro",
    });
    fireEvent.click(screen.getByTestId("admin-cancel-at-period-end"));
    await waitFor(() => expect(cancelUserSubscriptionMock).toHaveBeenCalledWith(USER_ID, true));
  });

  it("refunds the latest charge", async () => {
    await renderPage(detail());
    refundUserSubscriptionMock.mockResolvedValue({
      userId: USER_ID,
      refundId: "re_1",
      status: "succeeded",
      planId: "free",
    });
    fireEvent.click(screen.getByTestId("admin-refund"));
    await waitFor(() => expect(refundUserSubscriptionMock).toHaveBeenCalledWith(USER_ID));
  });

  it("surfaces a 409 as the backend's honest refusal, not a generic failure", async () => {
    // Race case: the subscription lapses between page load and the click. The
    // 409 must read as "Not applicable" with the server's own explanation.
    await renderPage(detail(WITH_SUB));
    cancelUserSubscriptionMock.mockRejectedValue(
      new ApiError("This user has no Stripe subscription to cancel", 409),
    );
    fireEvent.click(screen.getByTestId("admin-cancel-at-period-end"));
    await waitFor(() => {
      const text = screen.getByTestId("admin-user-error").textContent ?? "";
      expect(text).toContain("Not applicable");
      expect(text).toContain("no Stripe subscription");
    });
  });
});

describe("subscription actions are state-aware (owner-reported 409, 2026-08-14)", () => {
  // The owner clicked Cancel on their OWN exempt admin account and got a raw
  // 409 — the buttons must never be offered where the backend can only refuse.
  it("admin accounts show the exemption note and no cancel/refund buttons", async () => {
    await renderPage(
      detail({
        user: { ...detail().user, isAdmin: true },
      }),
    );
    expect(screen.getByTestId("admin-sub-exempt")).toBeTruthy();
    expect(screen.queryByTestId("admin-cancel-at-period-end")).toBeNull();
    expect(screen.queryByTestId("admin-cancel-now")).toBeNull();
    expect(screen.queryByTestId("admin-refund")).toBeNull();
  });

  it("accounts without a Stripe subscription get the entitlement hint, no cancel, refund kept", async () => {
    await renderPage(detail());
    expect(screen.getByTestId("admin-sub-none")).toBeTruthy();
    expect(screen.queryByTestId("admin-cancel-at-period-end")).toBeNull();
    expect(screen.queryByTestId("admin-cancel-now")).toBeNull();
    expect(screen.getByTestId("admin-refund")).toBeTruthy();
  });

  it("accounts with a live subscription keep both cancel actions", async () => {
    await renderPage(detail(WITH_SUB));
    expect(screen.getByTestId("admin-cancel-at-period-end")).toBeTruthy();
    expect(screen.getByTestId("admin-cancel-now")).toBeTruthy();
    expect(screen.getByTestId("admin-refund")).toBeTruthy();
  });
});

describe("credentials", () => {
  it("sets a password and never renders the value back", async () => {
    await renderPage(detail());
    setUserPasswordMock.mockResolvedValue({
      userId: USER_ID,
      passwordChanged: true,
      sessionsInvalidated: true,
    });
    const secret = "N3verShowThis";
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: secret } });
    fireEvent.click(screen.getByTestId("admin-set-password"));

    await waitFor(() => expect(setUserPasswordMock).toHaveBeenCalledWith(USER_ID, secret));
    await waitFor(() =>
      expect((screen.getByLabelText("New password") as HTMLInputElement).value).toBe(""),
    );
    expect(document.body.textContent).not.toContain(secret);
    expect(screen.getByTestId("admin-user-notice").textContent).toMatch(/sessions were invalidated/i);
  });

  it("never claims sessions were invalidated when the API says they were not", async () => {
    // The API computes ``sessionsInvalidated`` from the stamp it actually
    // wrote (it can come back false under server clock skew). The panel must
    // repeat what the API reported, not the optimistic copy — an admin cutting
    // off a compromised session has to know it may still be live.
    await renderPage(detail());
    setUserPasswordMock.mockResolvedValue({
      userId: USER_ID,
      passwordChanged: true,
      sessionsInvalidated: false,
      sessionsInvalidatedBefore: null,
    });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "An0therPassw0rd" } });
    fireEvent.click(screen.getByTestId("admin-set-password"));

    await waitFor(() => expect(screen.getByTestId("admin-user-notice")).toBeTruthy());
    const notice = screen.getByTestId("admin-user-notice").textContent ?? "";
    expect(notice).toMatch(/could not be confirmed/i);
    expect(notice).not.toMatch(/sessions were invalidated/i);
  });

  it("sends only the identity fields that actually changed", async () => {
    await renderPage(detail());
    updateUserIdentityMock.mockResolvedValue({
      userId: USER_ID,
      before: { email: "jamie@example.com", username: null, name: "Jamie Rivera" },
      after: { email: "jamie@example.com", username: "jamie", name: "Jamie Rivera" },
    });
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "jamie" } });
    fireEvent.click(screen.getByTestId("admin-save-identity"));

    await waitFor(() => expect(updateUserIdentityMock).toHaveBeenCalled());
    expect(updateUserIdentityMock.mock.calls[0]?.[1]).toEqual({ username: "jamie" });
  });
});

describe("audit trail", () => {
  it("renders the per-user audit entries the backend wrote", async () => {
    useParamsMock.mockReturnValue({ id: USER_ID });
    fetchAdminUserMock.mockResolvedValue(detail());
    fetchUserAuditLogMock.mockResolvedValue({
      entries: [
        {
          id: "a1",
          actorUserId: "admin-1",
          actorEmail: "owner@example.com",
          actorName: "Owner",
          action: "set_user_password",
          targetType: "user",
          targetId: USER_ID,
          detail: { sessionsInvalidated: true },
          ip: "1.2.3.4",
          createdAt: "2026-08-14T01:00:00Z",
        },
      ],
      total: 1,
      limit: 25,
      offset: 0,
    });
    render(<AdminUserDetailPage />);

    const panel = await screen.findByTestId("admin-user-audit");
    await waitFor(() => expect(panel.textContent).toContain("set_user_password"));
    expect(panel.textContent).toContain("owner@example.com");
  });
});
