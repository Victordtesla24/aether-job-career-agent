// @vitest-environment jsdom
/**
 * S-UI-REBUILD doctrine D-ε — the shell's chrome does not scroll away.
 *
 * WHY A CLASS ASSERTION AND NOT A LAYOUT ASSERTION
 * ------------------------------------------------
 * jsdom has no layout engine: `getBoundingClientRect()` returns zeroes and
 * Tailwind's stylesheet is never applied, so no unit test in this project can
 * observe that the rail is pinned. The MEASURED proof lives in the batch's
 * evidence directory — a real Chromium, the real production build, logged in
 * as a real user:
 *
 *   uat/reports/evidence/market-perf/s-ui/b0/refix/
 *     before-measurements.json    railPosition "static", railHeight 2007.5px,
 *                                 system-status trigger at y=1908 on a 1000px
 *                                 viewport, 0 of 13 nav links left on screen
 *                                 after a 900px wheel scroll
 *     after-measurements.json     railPosition "sticky", rail height clamped
 *                                 to the viewport, 13 of 13 nav links still on
 *                                 screen after the same scroll
 *     after-short-viewports.json  1440x900 / 1366x768 / 1280x720 / 1280x600 —
 *                                 the rail clips its OWN content and the
 *                                 plan/quota + SystemStatus footer is reached
 *                                 by scrolling the rail, not the page
 *
 * What this file does is stop that fix from being deleted by accident. The
 * four utilities below are the whole mechanism, and each one is load-bearing:
 * drop `h-screen` and flex stretch silently reinstates the 2007.5px column;
 * drop `sticky`/`top-0` and it scrolls away again; drop `overflow-y-auto` and
 * a short viewport clips the nav with no way to reach it. A reviewer reading a
 * future diff that removes any of them gets a red test instead of a regression
 * that only shows up in a screenshot.
 */
import type { ReactNode } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rail } from "../Rail";

const fetchAgentsMock = vi.hoisted(() => vi.fn());
const fetchSubscriptionMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("../../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));
vi.mock("../../../lib/api/billing", () => ({ fetchSubscription: fetchSubscriptionMock }));

function railClasses(): string[] {
  return screen.getByTestId("app-rail").className.split(/\s+/).filter(Boolean);
}

beforeEach(() => {
  window.localStorage.clear();
  fetchAgentsMock.mockResolvedValue([]);
  fetchSubscriptionMock.mockResolvedValue(null);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Rail is viewport-pinned (D-ε)", () => {
  it("clamps its own height to the viewport and pins itself there", () => {
    render(<Rail />);
    const classes = railClasses();
    // Pinned to the top of the viewport rather than flowing with the page.
    expect(classes).toContain("sticky");
    expect(classes).toContain("top-0");
    // The definite height is what beats flex `align-self: stretch`; without it
    // the rail inherits the routed page's height and the footer block
    // (plan/quota, Agents Active, SystemStatus) lands below the fold.
    expect(classes).toContain("h-screen");
  });

  it("keeps its own scroll region so the nav never takes the page with it", () => {
    render(<Rail />);
    const classes = railClasses();
    expect(classes).toContain("overflow-y-auto");
    // Stops the rail's inner scroll from chaining out to the document once it
    // bottoms out.
    expect(classes).toContain("overscroll-contain");
  });

  it("stays pinned when collapsed — the 64px rail is chrome too", () => {
    window.localStorage.setItem("aether.rail.collapsed", "1");
    render(<Rail />);
    expect(railClasses()).toEqual(
      expect.arrayContaining(["sticky", "top-0", "h-screen", "overflow-y-auto"]),
    );
  });
});
