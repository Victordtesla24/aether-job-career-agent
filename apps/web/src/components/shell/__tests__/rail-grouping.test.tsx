// @vitest-environment jsdom
/**
 * S-UI-REBUILD §1.2 — the rail's grouping is PRESENTATIONAL ONLY, and its
 * counts are real or absent.
 *
 * `NAV_ITEMS` is a tested contract (`__tests__/navigation.test.ts` asserts its
 * order and labels; DECISIONS D-0002 owns it). The grouping added by this
 * batch may print a heading between runs of that order; it may never reorder,
 * drop or duplicate an item. The first two tests make that mechanical.
 *
 * The count tests pin the harder rule: *"Counts in the rail are real or
 * absent."* The rail reads the realtime store, which is a reader over the ONE
 * existing connection — so on a page where nothing subscribes there is no
 * observation, and the rail must render NO NUMBER rather than a zero, a
 * placeholder or a stale cache.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard/jobs" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));

const fetchAgentsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));
const fetchSubscriptionMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/billing", () => ({ fetchSubscription: fetchSubscriptionMock }));

// eslint-disable-next-line import/first
import { Rail } from "../Rail";
// eslint-disable-next-line import/first
import { NAV_ITEMS } from "../../../lib/navigation";
// eslint-disable-next-line import/first
import { NAV_GROUPS, groupedNavItems } from "../../../lib/navigation-groups";
// eslint-disable-next-line import/first
import {
  __resetRealtimeStoreForTests,
  setRealtimeTransport,
  subscribeToResources,
} from "../../../lib/realtime/store";
// eslint-disable-next-line import/first
import type {
  RealtimeTransport,
  RealtimeTransportCallbacks,
} from "../../../lib/realtime/transport-types";

beforeEach(() => {
  window.localStorage.clear();
  fetchAgentsMock.mockResolvedValue([]);
  fetchSubscriptionMock.mockResolvedValue(null);
  __resetRealtimeStoreForTests();
});

afterEach(() => {
  cleanup();
  __resetRealtimeStoreForTests();
  vi.clearAllMocks();
});

describe("NAV_GROUPS partition (§1.2)", () => {
  it("covers every NAV_ITEMS href exactly once and invents none", () => {
    const grouped = NAV_GROUPS.flatMap((group) => group.hrefs);
    expect([...grouped].sort()).toEqual([...NAV_ITEMS.map((item) => item.href)].sort());
    expect(new Set(grouped).size).toBe(grouped.length);
  });

  it("reproduces the NAV_ITEMS order exactly — boundaries move, items never do", () => {
    expect(groupedNavItems().map((item) => item.href)).toEqual(NAV_ITEMS.map((item) => item.href));
    expect(groupedNavItems().map((item) => item.label)).toEqual(NAV_ITEMS.map((item) => item.label));
  });

  it("prints an eyebrow only at a group boundary, and each group's eyebrow only once", () => {
    const eyebrows = groupedNavItems()
      .map((item) => item.groupLabel)
      .filter((label): label is string => label !== null);
    expect(eyebrows).toEqual(NAV_GROUPS.map((group) => group.label));
  });
});

describe("Rail rendering (§1.2)", () => {
  it("renders all 13 items in contract order with the active one marked", async () => {
    render(<Rail />);
    const links = Array.from(
      document.querySelectorAll<HTMLElement>("nav[aria-label='Primary'] a[href]"),
    );
    expect(links.map((node) => node.getAttribute("href"))).toEqual(
      NAV_ITEMS.map((item) => item.href),
    );
    const active = links.filter((node) => node.getAttribute("aria-current") === "page");
    expect(active).toHaveLength(1);
    expect(active[0]?.getAttribute("href")).toBe("/dashboard/jobs");
    expect(screen.getByTestId("rail-active-indicator")).toBeTruthy();
  });

  it("renders NO count when the channel has observed nothing — absent, never zero", async () => {
    render(<Rail />);
    await waitFor(() => expect(fetchAgentsMock).toHaveBeenCalled());
    expect(screen.queryByTestId("rail-count-/dashboard/jobs")).toBeNull();
    expect(screen.queryByTestId("rail-count-/dashboard/applications")).toBeNull();
  });

  it("renders the server's own observed count once the existing channel reports one", async () => {
    const opens: RealtimeTransportCallbacks[] = [];
    const transport: RealtimeTransport = (callbacks) => {
      opens.push(callbacks);
      return { close: () => undefined };
    };
    setRealtimeTransport(transport);
    // A SCREEN opens the channel — the rail never does.
    const stop = subscribeToResources(["jobs"], () => undefined);
    render(<Rail />);
    await waitFor(() => expect(opens.length).toBe(1));

    opens[0]!.onEvent("hello", {
      resources: {
        jobs: { count: 8358, watermark: "2026-08-14T03:41:00Z" },
        applications: { count: 540, watermark: "2026-08-14T03:12:00Z" },
      },
    });

    await waitFor(() =>
      expect(screen.getByTestId("rail-count-/dashboard/jobs").textContent).toBe("8,358"),
    );
    expect(screen.getByTestId("rail-count-/dashboard/applications").textContent).toBe("540");
    stop();
  });

  it("persists the collapse preference and keeps every route present when collapsed", async () => {
    window.localStorage.setItem("aether.rail.collapsed", "1");
    render(<Rail />);
    await waitFor(() =>
      expect(screen.getByTestId("app-rail").getAttribute("data-collapsed")).toBe("true"),
    );
    const links = Array.from(
      document.querySelectorAll<HTMLElement>("nav[aria-label='Primary'] a[href]"),
    );
    expect(links.map((node) => node.getAttribute("href"))).toEqual(
      NAV_ITEMS.map((item) => item.href),
    );
    // Collapsed still names every destination for a screen reader.
    expect(screen.getByRole("link", { name: /story bank/i })).toBeTruthy();
  });
});
