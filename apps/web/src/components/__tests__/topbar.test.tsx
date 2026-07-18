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
import { cleanup, render, screen } from "@testing-library/react";
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
import { Topbar } from "../topbar";

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

describe("Topbar account-identity chip at mobile width (MV-mobile-dashboard-004)", () => {
  it("hides the redundant name/role text below the lg breakpoint", () => {
    render(<Topbar />);
    // Initial synchronous chip state renders chipName "Welcome" before the
    // fetchSettings promise resolves.
    const nameNode = screen.getByText("Welcome", { selector: "span" });
    const textWrapper = nameNode.parentElement as HTMLElement;
    expect(textWrapper.className).toMatch(/\bmax-lg:hidden\b/);
  });
});
