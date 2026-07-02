import { describe, it, expect } from "vitest";
import { NAV_ITEMS, findNavItemByHref } from "../src/lib/navigation";

/**
 * Contract test for the 12-item primary sidebar (Schema A).
 * Order and labels are the single source of truth defined in
 * DECISIONS D-0002; the sidebar component renders straight from this list.
 */
const CANONICAL_LABELS = [
  "Dashboard",
  "Jobs",
  "Resume Studio",
  "Story Bank",
  "Applications",
  "Interview Center",
  "Networking",
  "Email Center",
  "Agents",
  "Analytics",
  "Offers",
  "Settings",
];

describe("dashboard navigation contract (P1-S06)", () => {
  it("has exactly 12 items", () => {
    expect(NAV_ITEMS).toHaveLength(12);
  });

  it("matches the canonical Schema-A order and labels", () => {
    expect(NAV_ITEMS.map((i) => i.label)).toEqual(CANONICAL_LABELS);
  });

  it("uses 'Resume Studio' (no accent) per DECISIONS D-0002", () => {
    expect(NAV_ITEMS.some((i) => i.label === "Résumé Studio")).toBe(false);
    const resume = NAV_ITEMS.find((i) => i.label.includes("Resume"));
    expect(resume?.label).toBe("Resume Studio");
  });

  it("gives every item a unique route and a non-empty icon", () => {
    const hrefs = NAV_ITEMS.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(12);
    for (const item of NAV_ITEMS) {
      expect(item.href.startsWith("/")).toBe(true);
      expect(item.icon.length).toBeGreaterThan(0);
    }
  });

  it("routes Dashboard to /dashboard", () => {
    expect(NAV_ITEMS[0]).toMatchObject({ label: "Dashboard", href: "/dashboard" });
  });
});

/**
 * Resolver used by the dashboard shell to (a) highlight the active sidebar item
 * from the current pathname and (b) title the graceful placeholder shown for
 * dashboard sections whose page has not been built yet (P1-S12). Every nav
 * route must resolve to its item so no navigation click lands on a bare 404.
 */
describe("findNavItemByHref resolver (P1-S12)", () => {
  it("resolves every canonical nav href to its own item", () => {
    for (const item of NAV_ITEMS) {
      expect(findNavItemByHref(item.href)?.label).toBe(item.label);
    }
  });

  it("resolves a nested sub-route to its section (prefix match)", () => {
    expect(findNavItemByHref("/dashboard/jobs/123")?.label).toBe("Jobs");
    expect(findNavItemByHref("/dashboard/resume/v2")?.label).toBe("Resume Studio");
  });

  it("prefers the most specific section over the /dashboard root", () => {
    expect(findNavItemByHref("/dashboard/analytics")?.label).toBe("Analytics");
    expect(findNavItemByHref("/dashboard")?.label).toBe("Dashboard");
  });

  it("returns undefined for an unknown dashboard route", () => {
    expect(findNavItemByHref("/dashboard/does-not-exist")).toBeUndefined();
    expect(findNavItemByHref("/totally/other")).toBeUndefined();
  });
});
