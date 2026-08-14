// @vitest-environment jsdom
/**
 * U-NAV-MOBILE-01 (HIGH) — every paid section must be reachable on a phone.
 *
 * THE DEFECT THIS PINS
 * --------------------
 * `Sidebar` was `hidden lg:flex` and `MobileTabBar` exposes 5 of the 13
 * `NAV_ITEMS`. `grep -rn "fa-bars" src/` hit only `admin/admin-shell.tsx`:
 * there was no drawer, no "More" and no hamburger anywhere in the dashboard
 * shell, so below 1024px EIGHT sections were unreachable except by typing the
 * URL — Resume Studio, Cover Letter Studio, Story Bank, Interview Center,
 * Networking, Email Center, Analytics and Offers. On a subscription product
 * that is a paid-feature blackout on phones.
 *
 * WHY IT IS ASSERTED THIS WAY
 * ---------------------------
 * jsdom does not do layout, so a 390px viewport cannot be simulated by
 * measuring. This suite follows the project's established convention for
 * CSS-driven behaviour (see `components/__tests__/topbar.test.tsx`
 * MV-mobile-dashboard-001): the responsive VISIBILITY classes are asserted
 * structurally — the rail is `hidden` until `lg`, the hamburger is present
 * until `lg` — and reachability itself is asserted by opening the sheet and
 * checking a link exists for every href in the `NAV_ITEMS` contract.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));

const fetchSettingsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/workspaces", () => ({ fetchSettings: fetchSettingsMock }));
const fetchAgentsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));
const fetchApprovalsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/approvals", () => ({ fetchApprovals: fetchApprovalsMock }));
const fetchSubscriptionMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/billing", () => ({ fetchSubscription: fetchSubscriptionMock }));
const fetchMeMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/admin", () => ({ fetchMe: fetchMeMock }));

// eslint-disable-next-line import/first
import { AppShell } from "../AppShell";
// eslint-disable-next-line import/first
import { MobileTabBar } from "../../mobile-tab-bar";
// eslint-disable-next-line import/first
import { NAV_ITEMS } from "../../../lib/navigation";

beforeEach(() => {
  fetchSettingsMock.mockResolvedValue({ profile: { fullName: "Vikram Sarkar", targetRole: "" } });
  fetchAgentsMock.mockResolvedValue([]);
  fetchApprovalsMock.mockResolvedValue([]);
  fetchSubscriptionMock.mockResolvedValue(null);
  fetchMeMock.mockResolvedValue({ id: "u1", email: "u@example.com", isAdmin: false });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function hrefsIn(root: HTMLElement): Set<string> {
  return new Set(
    Array.from(root.querySelectorAll("a[href]")).map((a) => a.getAttribute("href") ?? ""),
  );
}

describe("U-NAV-MOBILE-01 — mobile reachability of every NAV_ITEMS route", () => {
  it("the bottom tab bar alone reaches only 5 of the 13 sections (the defect it cannot fix)", () => {
    const { container } = render(<MobileTabBar />);
    const reachable = hrefsIn(container);
    const missing = NAV_ITEMS.filter((item) => !reachable.has(item.href));
    // This is the measurement that made U-NAV-MOBILE-01 a HIGH: the tab bar
    // is a 5-tab wireframe contract and must not grow a 6th tab, so the eight
    // it cannot reach need a different affordance.
    expect(missing).toHaveLength(8);
  });

  it("hides the desktop rail below lg, and offers a hamburger there instead", async () => {
    render(
      <AppShell supportEmail={null}>
        <p>page</p>
      </AppShell>,
    );

    const rail = await screen.findByTestId("app-rail");
    const railClasses = rail.className.split(/\s+/);
    expect(railClasses).toContain("hidden");
    expect(railClasses).toContain("lg:flex");

    const trigger = screen.getByTestId("mobile-nav-trigger");
    expect(trigger.className.split(/\s+/)).toContain("lg:hidden");
  });

  it("opens a nav sheet that reaches EVERY route in the NAV_ITEMS contract", async () => {
    render(
      <AppShell supportEmail={null}>
        <p>page</p>
      </AppShell>,
    );

    fireEvent.click(screen.getByTestId("mobile-nav-trigger"));
    const sheet = await screen.findByTestId("mobile-nav-sheet");

    const reachable = hrefsIn(sheet);
    const missing = NAV_ITEMS.filter((item) => !reachable.has(item.href));
    expect(
      missing.map((item) => item.label),
      "every NAV_ITEMS route must be reachable from the mobile nav sheet",
    ).toEqual([]);

    // The sheet's own container is mobile-only — it must never double the
    // rail on desktop.
    expect(
      screen.getByTestId("mobile-nav-sheet-root").className.split(/\s+/),
    ).toContain("lg:hidden");
  });

  it("renders the sheet's sections in the NAV_ITEMS order — grouping is presentational only", async () => {
    render(
      <AppShell supportEmail={null}>
        <p>page</p>
      </AppShell>,
    );
    fireEvent.click(screen.getByTestId("mobile-nav-trigger"));
    const sheet = await screen.findByTestId("mobile-nav-sheet");

    const rendered = Array.from(
      sheet.querySelectorAll<HTMLElement>("[data-testid^='mobile-nav-link-']"),
    ).map((node) => node.getAttribute("href"));
    expect(rendered).toEqual(NAV_ITEMS.map((item) => item.href));
  });

  it("is a real dialog: modal, Escape-closable, and it closes on a nav selection", async () => {
    render(
      <AppShell supportEmail={null}>
        <p>page</p>
      </AppShell>,
    );

    fireEvent.click(screen.getByTestId("mobile-nav-trigger"));
    const sheet = await screen.findByTestId("mobile-nav-sheet");
    expect(sheet.getAttribute("role")).toBe("dialog");
    expect(sheet.getAttribute("aria-modal")).toBe("true");
    await waitFor(() => expect(sheet.contains(document.activeElement)).toBe(true));

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("mobile-nav-sheet")).toBeNull());

    fireEvent.click(screen.getByTestId("mobile-nav-trigger"));
    const reopened = await screen.findByTestId("mobile-nav-sheet");
    fireEvent.click(within(reopened).getByTestId("mobile-nav-link-/dashboard/offers"));
    await waitFor(() => expect(screen.queryByTestId("mobile-nav-sheet")).toBeNull());
  });

  it("adds NO API call — the sheet reuses the shell's single subscription fetch", async () => {
    render(
      <AppShell supportEmail={null}>
        <p>page</p>
      </AppShell>,
    );
    await waitFor(() => expect(fetchSubscriptionMock).toHaveBeenCalled());
    const before = fetchSubscriptionMock.mock.calls.length;

    fireEvent.click(screen.getByTestId("mobile-nav-trigger"));
    await screen.findByTestId("mobile-nav-sheet");

    // The rail and the sheet share one GET /billing/subscription — opening the
    // sheet must not add a request that does not exist on `main`.
    expect(fetchSubscriptionMock.mock.calls.length).toBe(before);
    expect(before).toBe(1);
  });
});
