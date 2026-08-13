// @vitest-environment jsdom
/**
 * MON-018 / U-UI — Notification panel (BELL-OVERLAP-01, BELL-OFFSCREEN-*).
 *
 * Live visual audit (uat/reports/evidence/agents-uplift/u-ui-audit/) found
 * the notification-bell dropdown (data-testid="notification-panel" in
 * components/topbar.tsx):
 *
 *   - BELL-OVERLAP-01 (desktop, HIGH, 8/8 routes): the open panel renders
 *     with NO backdrop and does not dim/block the page content behind it.
 *     Screenshot evidence (dashboard_resume/dashboard_resume__bell-open__full.png)
 *     shows the "TAILORED — LATEST VERSION" resume card and its pill
 *     visibly bleeding through the panel — confirmed absent from the DOM:
 *     there is no backdrop element rendered alongside the panel at all.
 *   - BELL-OFFSCREEN-* (mobile 390x844, HIGH, 5/6 routes tested): the panel
 *     is `absolute right-0` inside a `relative` wrapper around ONLY the
 *     40px bell button, so its `w-80` (320px) box is anchored to that
 *     button's right edge — measured getBoundingClientRect
 *     x=-107.375 (33% of the panel's width off the left edge of a 390px
 *     viewport), making the notification list unreadable on mobile.
 *
 * jsdom does not perform real layout, so pixel geometry (the exact -107px)
 * isn't assertable here (per the audit's own note and the project's existing
 * convention, e.g. src/components/__tests__/topbar.test.tsx
 * MV-mobile-dashboard-001) — these tests instead pin the structural
 * class/behavior contract:
 *   1. The panel must render on a solid/opaque design-token background, not
 *      a translucent `.glass`/`bg-white/N` class (opaque-surface contract).
 *   2. The panel must stack above page content (a z-index utility).
 *   3. A backdrop element (data-testid="notification-backdrop") must render
 *      alongside the panel while it is open, and must not render while closed.
 *   4. The panel must not be positioned with an unclamped `right-0` alone —
 *      it needs a viewport-relative left/inset bound too, so it cannot be
 *      pushed off-screen on a narrow viewport (BELL-OFFSCREEN contract).
 *   5. Outside-click and Escape still close the panel (existing correct
 *      behavior — pinned so the backdrop/positioning fix doesn't regress it).
 *
 * Fixer: rendering a backdrop is the piece that is genuinely missing today;
 * (1)/(2)/(5) already hold against current code and are asserted here purely
 * as a locked-in contract alongside the new backdrop/position requirements.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
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

// eslint-disable-next-line import/first
import { Topbar } from "../topbar";

const PENDING_APPROVAL = {
  id: "appr-1",
  userId: "u1",
  applicationId: "app-1",
  type: "application_submit" as const,
  status: "pending" as const,
  payload: {},
  createdAt: new Date().toISOString(),
  resolvedAt: null,
};

beforeEach(() => {
  fetchSettingsMock.mockResolvedValue({
    profile: { fullName: "Administrator", targetRole: "" },
  });
  fetchAgentsMock.mockResolvedValue([]);
  fetchApprovalsMock.mockResolvedValue([PENDING_APPROVAL]);
});

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchAgentsMock.mockReset();
  fetchApprovalsMock.mockReset();
});

async function openBell() {
  render(<Topbar />);
  const bell = await screen.findByTestId("notification-bell");
  fireEvent.click(bell);
  return screen.findByTestId("notification-panel");
}

describe("Notification panel (BELL-OVERLAP-01)", () => {
  it("renders an opaque surface, stacked above content, with a backdrop element while open", async () => {
    const panel = await openBell();

    // (1) opaque-surface contract: a solid design token, never a translucent
    // glass/opacity utility.
    expect(panel.className).not.toMatch(/\bglass\b/);
    expect(panel.className).not.toMatch(/bg-white\/(?!100\b)\d/);
    expect(panel.className).toMatch(/bg-aether-bg-elevated|bg-\[#[0-9a-fA-F]{3,8}\]/);

    // (2) stacking contract: an explicit z-index utility above page content.
    expect(panel.className).toMatch(/\bz-\d+\b/);

    // (3) BELL-OVERLAP-01: a backdrop must render alongside the panel while
    // it is open — currently absent from the component entirely.
    expect(screen.getByTestId("notification-backdrop")).toBeTruthy();
  });

  it("does not render a backdrop while the panel is closed", async () => {
    render(<Topbar />);
    await screen.findByTestId("notification-bell");
    expect(screen.queryByTestId("notification-backdrop")).toBeNull();
  });

  it("removes the backdrop again once the panel closes", async () => {
    const panel = await openBell();
    expect(screen.getByTestId("notification-backdrop")).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("notification-panel")).toBeNull();
    expect(screen.queryByTestId("notification-backdrop")).toBeNull();
    void panel;
  });
});

describe("Notification panel mobile positioning (BELL-OFFSCREEN-*)", () => {
  it("is not positioned with an unclamped right-anchor alone — it must also carry a viewport-relative left/inset bound so it cannot render off-screen on a narrow viewport", async () => {
    const panel = await openBell();
    // Current class list is `absolute right-0 top-12 z-50 w-80
    // max-w-[calc(100vw-2rem)] ...` — max-w caps the WIDTH but nothing
    // bounds the LEFT edge, so anchoring to the 40px bell button pushes the
    // 320px panel off the left edge of a 390px viewport (measured
    // x=-107.375 in the live audit). A left/inset bound is required in
    // addition to (not instead of) the existing right anchor.
    expect(panel.className).toMatch(/inset-x-\S|(?:^|\s)left-(?:0\b|\[)/);
  });
});

describe("Notification panel close behavior (regression guard)", () => {
  it("closes when clicking outside the panel", async () => {
    await openBell();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByTestId("notification-panel")).toBeNull();
  });

  it("closes on Escape", async () => {
    await openBell();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("notification-panel")).toBeNull();
  });
});
