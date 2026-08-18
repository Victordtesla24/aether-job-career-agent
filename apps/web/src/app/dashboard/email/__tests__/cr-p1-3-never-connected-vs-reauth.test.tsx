// @vitest-environment jsdom
/**
 * CR-P1-3 (RUN-20260818T0223Z, commercial-readiness audit
 * `docs/delivery/evidence/RUN-20260818T0223Z/COMMERCIAL-READINESS/email-networking-agents/audit.md`)
 *
 * Email Center falsely told a subscriber who has NEVER connected Gmail that
 * their inbox "needs reconnect" / re-authorization. The backend genuinely
 * distinguishes three states (`apps/api/app/routers/workspaces.py:927-975`):
 *   - "connected"      — a real, live grant
 *   - "needs_reauth"    — a real grant that expired/was revoked
 *   - "not_connected"   — the placeholder row sent when NOTHING has ever
 *                          been linked (`id: null`, the user's own login
 *                          email standing in for an inbox address)
 *
 * The frontend collapsed all non-"connected" statuses into one
 * `linkedButBroken`/`allAccountsBroken` bucket (`status !== "connected"`),
 * so a brand-new subscriber with the `not_connected` placeholder saw the
 * exact same "Reconnect Gmail" / "needs re-authorization" copy as someone
 * whose real grant expired. This file proves the two cases must render
 * differently: NEVER-CONNECTED gets a first-time "Connect" affordance;
 * NEEDS-REAUTH keeps the honest reconnect affordance.
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

/** The exact shape the backend sends for a subscriber who never linked
 *  Gmail — `apps/api/app/routers/workspaces.py:963-975`. */
const NEVER_CONNECTED_PLACEHOLDER: EmailInbox["accounts"][number] = {
  id: null,
  email: "subscriber@example.com",
  provider: "Gmail",
  status: "not_connected",
  isPrimary: false,
  unread: 0,
  lastSyncedAt: null,
  note: "Connect your Gmail account to see your inbox here.",
};

const EXPIRED_GRANT: EmailInbox["accounts"][number] = {
  id: "acc-1",
  email: "real@gmail.com",
  provider: "Gmail",
  status: "needs_reauth",
  isPrimary: true,
  unread: 0,
  actionRequired: true,
  note: "Gmail authorization expired or was revoked — reconnect your account to resume syncing.",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CR-P1-3 — never-connected Gmail must say Connect, not Reconnect", () => {
  it('renders "Connect Gmail" (not "Reconnect Gmail") for a subscriber who has never linked Gmail', async () => {
    fetchEmailInboxMock.mockResolvedValue(inboxFixture([NEVER_CONNECTED_PLACEHOLDER]));

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    expect(screen.getByTestId("connect-gmail-btn").textContent).toContain("Connect Gmail");
    expect(screen.getByTestId("connect-gmail-btn").textContent).not.toMatch(/reconnect/i);
  });

  it("does not render a reconnect badge on the never-connected placeholder chip", async () => {
    fetchEmailInboxMock.mockResolvedValue(inboxFixture([NEVER_CONNECTED_PLACEHOLDER]));

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    expect(screen.queryByTestId("inbox-needs-reconnect")).toBeNull();
  });

  it('does not tell a never-connected subscriber their inbox "needs re-authorization"', async () => {
    fetchEmailInboxMock.mockResolvedValue(inboxFixture([NEVER_CONNECTED_PLACEHOLDER]));

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    const banner = screen.queryByTestId("job-alerts-unavailable");
    expect(banner).not.toBeNull();
    expect(banner!.textContent).not.toMatch(/reconnect|re-authorization|re-auth/i);
    expect(banner!.textContent).toMatch(/connect gmail/i);
  });

  it('still renders "Reconnect Gmail" and the reconnect badge for a genuinely expired grant', async () => {
    fetchEmailInboxMock.mockResolvedValue(inboxFixture([EXPIRED_GRANT]));

    render(<EmailCenterPage />);
    await screen.findByTestId("email-center");

    expect(screen.getByTestId("connect-gmail-btn").textContent).toMatch(/reconnect gmail/i);
    expect(screen.getByTestId("inbox-needs-reconnect")).toBeTruthy();

    const banner = screen.queryByTestId("job-alerts-unavailable");
    expect(banner).not.toBeNull();
    expect(banner!.textContent).toMatch(/reconnect|re-authorization/i);
  });
});
