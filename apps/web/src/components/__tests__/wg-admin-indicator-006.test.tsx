// @vitest-environment jsdom
/**
 * GOLD-MASTER-V2 §9.2.3 (W-G) — no persistent "Admin" indicator for a
 * logged-in admin OUTSIDE /admin/*.
 *
 * VERIFIED TWICE on production: a logged-in admin browsing anywhere in the
 * regular app shell (e.g. /dashboard) sees exactly the same chrome as a
 * standard user — nothing in the persistent Topbar/UserMenu signals
 * "you are an admin" or offers a way back into /admin without typing the
 * URL by hand. (Everything ELSE about admin access — the 7 /admin/* routes,
 * the AdminGuard client-side redirect, the backend AdminUser 403 gate — is
 * already built and independently verified; this test is only about the
 * MISSING persistent indicator outside /admin/*.)
 *
 * RCA against current code:
 *   - apps/web/src/components/topbar.tsx renders greeting/subtitle, search,
 *     notification bell, and <UserMenu>. It has no isAdmin awareness at all
 *     (no import of `fetchMe` / anything from `lib/api/admin`).
 *   - apps/web/src/components/user-menu.tsx renders only avatar-initials +
 *     name/role + a "Sign out" menu item. No admin badge, no link to /admin.
 *   - The one place isAdmin IS already fetched client-side is
 *     apps/web/src/components/admin/admin-guard.tsx, via
 *     `fetchMe()` from `../../lib/api/admin` — the obvious, already-existing
 *     mechanism a minimal fix would reuse rather than inventing a new one
 *     (duplicating an isAdmin fetch would violate §13.1).
 *
 * This test mocks that same `fetchMe` and renders the real <Topbar/>,
 * asserting BOTH halves of the contract: an admin session shows a
 * persistent "Admin" indicator; a standard session shows none (guards
 * against an over-broad fix that labels every user "Admin").
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const fetchSettingsMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/workspaces", () => ({ fetchSettings: fetchSettingsMock }));

const fetchAgentsMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));

const fetchApprovalsMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/approvals", () => ({ fetchApprovals: fetchApprovalsMock }));

// The already-existing isAdmin source (used today only by admin-guard.tsx).
const fetchMeMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/admin", () => ({ fetchMe: fetchMeMock }));

// eslint-disable-next-line import/first
import { Topbar } from "../topbar";

beforeEach(() => {
  fetchSettingsMock.mockResolvedValue({
    profile: { fullName: "Jordan Rivera", targetRole: "Engineer" },
  });
  fetchAgentsMock.mockResolvedValue([]);
  fetchApprovalsMock.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchAgentsMock.mockReset();
  fetchApprovalsMock.mockReset();
  fetchMeMock.mockReset();
});

describe("W-G §9.2.3: persistent Admin indicator outside /admin/*", () => {
  it("shows a persistent Admin indicator in the shell for a logged-in admin", async () => {
    fetchMeMock.mockResolvedValue({
      id: "u-admin-1",
      email: "admin-fixture@example.com",
      isAdmin: true,
    });

    render(<Topbar />);

    // Give any admin-status fetch a chance to resolve before asserting
    // absence/presence (mirrors the async-settling pattern the rest of this
    // suite already uses for fetchSettings-driven chip state).
    await waitFor(() => expect(fetchSettingsMock).toHaveBeenCalled());

    const adminMarker = await screen.findByText(/admin/i, {}, { timeout: 500 }).catch(() => null);
    expect(
      adminMarker,
      "logged-in admin: expected a persistent 'Admin' indicator somewhere in the " +
        "Topbar/UserMenu shell (outside /admin/*); none was rendered",
    ).not.toBeNull();
  });

  it("shows NOTHING admin-related for a standard (non-admin) user", async () => {
    fetchMeMock.mockResolvedValue({
      id: "u-standard-1",
      email: "standard-fixture@example.com",
      isAdmin: false,
    });

    render(<Topbar />);
    await waitFor(() => expect(fetchSettingsMock).toHaveBeenCalled());

    const adminMarker = screen.queryByText(/admin/i);
    expect(
      adminMarker,
      "standard user: no admin-related text should appear anywhere in the shell",
    ).toBeNull();
  });
});
