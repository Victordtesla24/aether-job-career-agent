import { describe, it, expect } from "vitest";
import { NAV_ITEMS } from "../src/lib/navigation";

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
