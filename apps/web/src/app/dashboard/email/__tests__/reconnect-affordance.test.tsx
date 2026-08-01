// @vitest-environment jsdom
/**
 * §22 STEP 2 (GOLD-MASTER-V4) — GMV4-email-001 (HIGH), failing-test evidence.
 *
 * On production BOTH linked Gmail accounts are in `needs_reauth` state. The
 * backend already computes and returns this honestly
 * (apps/api/app/routers/workspaces.py:634-649 — `status: "needs_reauth"`,
 * `actionRequired: true`, a `note` explaining "reconnect your account").
 *
 * But `EmailCenterPage` (apps/web/src/app/dashboard/email/page.tsx:534-536)
 * renders inbox-account chips ONLY for accounts whose status is
 * `"connected"`:
 *
 *     {inbox.accounts
 *       .filter((a) => a.status === "connected")
 *       .map((a) => ( ... data-testid="inbox-account" ... ))}
 *
 * so when every account is `needs_reauth`, ZERO chips render. The CTA button
 * (page.tsx:587-600) picks its label purely off
 * `inbox.accounts.some((a) => a.status === "connected")`, which is also
 * `false` for an all-broken inbox — so it falls back to the same bare
 * "Connect Gmail" label used when there are NO accounts at all. The word
 * "reauth"/"reconnect" appears nowhere in page.tsx (grepped). Every
 * email-dependent agent is silently degraded with no user-visible cause.
 *
 * These tests are RED against current code (HEAD 4ac8740) — see
 * uat/reports/evidence/models-live/ for the verbatim run output.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EmailInbox } from "../../../../lib/api/workspaces";

const fetchEmailInboxMock = vi.fn();
const fetchEmailThreadBodyMock = vi.fn();

vi.mock("../../../../lib/api/workspaces", async () => {
  const actual =
    await vi.importActual<typeof import("../../../../lib/api/workspaces")>(
      "../../../../lib/api/workspaces",
    );
  return {
    ...actual,
    fetchEmailInbox: (...args: unknown[]) => fetchEmailInboxMock(...args),
    fetchEmailThreadBody: (...args: unknown[]) => fetchEmailThreadBodyMock(...args),
  };
});

// eslint-disable-next-line import/first
import EmailCenterPage from "../page";

function inboxFixture(accounts: EmailInbox["accounts"]): EmailInbox {
  return {
    accounts,
    stats: {
      received: 0,
      recruiterEmails: 0,
      autoDrafted: 0,
      sentApproved: 0,
      followUpsSent: 0,
      avgResponseHrs: 0,
    },
    followUps: [],
    messages: [],
    recruiterProfile: null,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("GMV4-email-001: needs_reauth accounts must stay visible with a reconnect affordance", () => {
  it("renders a connected chip when the account status is connected", async () => {
    fetchEmailInboxMock.mockResolvedValue(
      inboxFixture([
        { id: "acc-1", email: "primary@gmail.com", provider: "Gmail", status: "connected", isPrimary: true, unread: 3 },
      ]),
    );

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    const chips = screen.getAllByTestId("inbox-account");
    expect(chips).toHaveLength(1);
    expect(chips[0].textContent).toContain("primary@gmail.com");
  });

  it("renders a reconnect affordance when an account status is needs_reauth", async () => {
    fetchEmailInboxMock.mockResolvedValue(
      inboxFixture([
        { id: "acc-1", email: "broken@gmail.com", provider: "Gmail", status: "needs_reauth", isPrimary: true, unread: 0 },
      ]),
    );

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    // The broken account must still be visible somewhere on the page...
    expect(screen.queryByText("broken@gmail.com")).not.toBeNull();

    // ...AND the page must offer a reconnect action — not just a generic
    // "Connect Gmail" that's indistinguishable from "no account linked".
    const reconnectAffordance =
      screen.queryByRole("button", { name: /reconnect|re-authenticate|re-auth/i }) ??
      screen.queryByText(/reconnect|needs? re-?auth|re-?authenticate/i);
    expect(reconnectAffordance).not.toBeNull();
  });

  it("does not silently render zero chips when every account needs reauth", async () => {
    fetchEmailInboxMock.mockResolvedValue(
      inboxFixture([
        { id: "acc-1", email: "one@gmail.com", provider: "Gmail", status: "needs_reauth", isPrimary: true, unread: 0 },
        { id: "acc-2", email: "two@gmail.com", provider: "Gmail", status: "needs_reauth", isPrimary: false, unread: 0 },
      ]),
    );

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    // This is the exact production state: 2 linked accounts, both broken.
    // The inbox chips row must communicate SOMETHING — not render as if zero
    // accounts were ever linked.
    const chips = screen.queryAllByTestId("inbox-account");
    expect(chips.length).toBeGreaterThan(0);
  });

  it('distinguishes "no accounts linked" from "accounts linked but broken"', async () => {
    // Reading 1: truly no accounts linked.
    fetchEmailInboxMock.mockResolvedValueOnce(inboxFixture([]));
    const { unmount } = render(<EmailCenterPage />);
    await screen.findByTestId("email-center");
    const noAccountsCta = screen.getByTestId("connect-gmail-btn").textContent;
    unmount();

    // Reading 2: 2 accounts ARE linked, but both are broken (needs_reauth) —
    // production's actual state.
    fetchEmailInboxMock.mockResolvedValueOnce(
      inboxFixture([
        { id: "acc-1", email: "one@gmail.com", provider: "Gmail", status: "needs_reauth", isPrimary: true, unread: 0 },
        { id: "acc-2", email: "two@gmail.com", provider: "Gmail", status: "needs_reauth", isPrimary: false, unread: 0 },
      ]),
    );
    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");
    const brokenAccountsCta = screen.getByTestId("connect-gmail-btn").textContent;

    // These are two fundamentally different user situations — the UI must
    // not present them identically.
    expect(brokenAccountsCta).not.toBe(noAccountsCta);
  });
});
