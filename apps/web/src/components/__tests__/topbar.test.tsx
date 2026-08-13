// @vitest-environment jsdom
/**
 * Topbar — mobile header clip regression guard (MV-mobile-dashboard-001).
 *
 * Live 390x844 DOM measurement found the greeting `<h1>` rendering with
 * `top:-15` (15px clipped above the fixed-height header box) and the
 * subtitle `<p>` overflowing 14px below the header's own bottom edge — both
 * caused by the text wrapping to 2-3 lines inside a header locked to a fixed
 * `h-16` (64px) height at narrow viewports. This is reproduced/verified via
 * jsdom class assertions (this suite does not do real layout), following the
 * project's existing convention for CSS-driven fixes (see
 * apps/web/src/__tests__/metric-tooltip.test.tsx GAP-P6-UI-001) rather than
 * asserting computed pixel geometry jsdom cannot produce.
 *
 * Fix: the greeting/subtitle must truncate to a single line (never wrap) so
 * they can never exceed the header's box, and the header's height must be a
 * `min-h` (allowed to grow) rather than a hard-clamped `h-16`.
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

// eslint-disable-next-line import/first
import { Topbar, computeBellPanelPosition } from "../topbar";

beforeEach(() => {
  fetchSettingsMock.mockResolvedValue({
    profile: { fullName: "Administrator", targetRole: "" },
  });
  fetchAgentsMock.mockResolvedValue([]);
  fetchApprovalsMock.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchAgentsMock.mockReset();
  fetchApprovalsMock.mockReset();
});

describe("Topbar mobile header clip (MV-mobile-dashboard-001)", () => {
  it("truncates the greeting to a single line instead of letting it wrap and clip", () => {
    render(<Topbar />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.className.split(/\s+/)).toContain("truncate");
  });

  it("truncates the subtitle to a single line instead of letting it wrap and overflow", () => {
    render(<Topbar />);
    const heading = screen.getByRole("heading", { level: 1 });
    const subtitle = heading.parentElement?.querySelector("p");
    expect(subtitle).toBeTruthy();
    expect((subtitle as HTMLElement).className.split(/\s+/)).toContain("truncate");
  });

  it("uses a flexible min-height for the header instead of a hard-clamped fixed height", () => {
    render(<Topbar />);
    const header = screen.getByRole("banner");
    const classes = header.className.split(/\s+/);
    expect(classes).not.toContain("h-16");
    expect(classes).toContain("min-h-16");
  });
});

describe("computeBellPanelPosition (U-UI BELL-OVERLAP-01 / BELL-OFFSCREEN-*)", () => {
  it("keeps the panel fully on-screen on a narrow (390px) mobile viewport", () => {
    // Live audit geometry: bell button near the right edge of a 390px
    // viewport (BELL-OFFSCREEN-dashboard measured the OLD panel at
    // x=-107.375, i.e. 107px off-screen left).
    const buttonRect = { right: 374, bottom: 52 };
    const pos = computeBellPanelPosition(buttonRect, 390);
    expect(pos.left).toBeGreaterThanOrEqual(0);
    expect(pos.left + pos.width).toBeLessThanOrEqual(390);
  });

  it("anchors flush to the button's right edge when there is room (desktop)", () => {
    const buttonRect = { right: 1104.625, bottom: 59.5 };
    const pos = computeBellPanelPosition(buttonRect, 1440);
    expect(pos.left + pos.width).toBe(1104.625);
    expect(pos.width).toBe(320);
  });

  it("clamps the panel so it never starts left of the margin even for a button pinned at x=0", () => {
    const pos = computeBellPanelPosition({ right: 10, bottom: 40 }, 390);
    expect(pos.left).toBeGreaterThanOrEqual(16);
  });

  it("shrinks the panel width (never overflows) on a viewport narrower than the default 320px panel", () => {
    const pos = computeBellPanelPosition({ right: 300, bottom: 40 }, 320);
    expect(pos.width).toBeLessThanOrEqual(320 - 16 * 2);
    expect(pos.left + pos.width).toBeLessThanOrEqual(320);
    expect(pos.left).toBeGreaterThanOrEqual(0);
  });
});

describe("Topbar notification panel (U-UI BELL-OVERLAP-01/KANBAN-HEADER-OVERLAP-01)", () => {
  it("renders the open panel outside the blurred header's DOM subtree (portaled), with a solid surface and a high z-index", async () => {
    render(<Topbar />);
    fireEvent.click(screen.getByTestId("notification-bell"));

    const panel = await screen.findByTestId("notification-panel");
    const header = screen.getByRole("banner");
    // U-UI BELL-OVERLAP-01: previously nested inside the `.glass`
    // (backdrop-filter) header — the ancestor whose filter context produced
    // the transparency bleed-through. A portaled panel is never contained by
    // it, regardless of any future header markup changes.
    expect(header.contains(panel)).toBe(false);
    expect(panel.className).toMatch(/\bbg-aether-bg-elevated\b/);
    expect(panel.className).toMatch(/z-\[100\]/);
  });

  it("renders a click-to-close backdrop alongside the panel", async () => {
    render(<Topbar />);
    fireEvent.click(screen.getByTestId("notification-bell"));

    const panel = await screen.findByTestId("notification-panel");
    expect(panel.className).toMatch(/z-\[100\]/);
    // The backdrop is the panel's previous sibling in the portal root.
    const backdrop = panel.previousElementSibling as HTMLElement;
    expect(backdrop).not.toBeNull();
    expect(backdrop.className).toMatch(/fixed inset-0/);

    fireEvent.click(backdrop);
    expect(screen.getByTestId("notification-bell").getAttribute("aria-expanded")).toBe("false");
  });

  it("closes the panel on Escape", async () => {
    render(<Topbar />);
    fireEvent.click(screen.getByTestId("notification-bell"));
    await screen.findByTestId("notification-panel");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByTestId("notification-bell").getAttribute("aria-expanded")).toBe("false");
  });
});

describe("Topbar account-identity chip at mobile width (MV-mobile-dashboard-004)", () => {
  it("hides the redundant name/role text below the lg breakpoint", async () => {
    render(<Topbar />);
    // M6: the chip renders a skeleton until fetchSettings resolves (no
    // "Welcome"/"AE" flicker), then shows the real name. Wait for the loaded
    // name before asserting its wrapper carries the responsive hide class.
    const nameNode = await screen.findByText("Administrator", { selector: "span" });
    const textWrapper = nameNode.parentElement as HTMLElement;
    expect(textWrapper.className).toMatch(/\bmax-lg:hidden\b/);
  });
});
