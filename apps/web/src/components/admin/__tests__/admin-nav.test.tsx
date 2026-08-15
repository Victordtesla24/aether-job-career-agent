// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-1 — the admin nav after the dashboard rebuild.
 *
 * The brief fixes the section order (Dashboard, Users, Subscriptions, Billing,
 * Sales agents, Promos, Spend, Health, Audit log, Settings) and requires that
 * nothing already reachable becomes unreachable.
 *
 * FE-2 UPDATE — TWO ENTRIES CHANGED, AND BOTH FOR A STATED REASON.
 *
 * 1. PROMOS IS NOW A REAL LINK. FE-1 left it deliberately disabled because the
 *    screen did not exist; FE-2 built `/admin/promos`, so the flag flips, which
 *    is the exact migration FE-1's own note above described. BILLING stays
 *    pending: FE-2 built the PER-USER billing panel (on the user detail page),
 *    not the platform-wide billing screen behind this entry.
 *
 * 2. "SALES AGENTS" NOW POINTS AT `/admin/sales-agents` (plural), the BE-2
 *    reseller surface — referral codes, attributed counts, commission reports.
 *    The pre-existing `/admin/sales-agent` (singular) is a DIFFERENT thing: a
 *    read-only window onto the external growth engine (a Google-Sheet-driven
 *    outreach process that runs outside this app). Two unrelated features had
 *    collided on one label, so the older page keeps its route — nothing
 *    reachable becomes unreachable, as pinned below — under the name that
 *    actually describes it.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN_NAV, AdminShell } from "../admin-shell";

// Vitest hoists `vi.mock` above the imports above, so the stubs are in place
// before `../admin-shell` is evaluated even though they are written after it.
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin",
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(cleanup);

describe("ADMIN_NAV", () => {
  it("is in the order the brief fixes", () => {
    expect(ADMIN_NAV.map((i) => i.label)).toEqual([
      "Dashboard",
      "Users",
      "Subscriptions",
      "Billing",
      "Sales agents",
      // Adjacent to Sales agents because a reader looking for "the growth
      // stuff" will look here — but named apart, because it is a different
      // system with a different source of truth.
      "Growth engine",
      "Promos",
      "Spend",
      "Health",
      "Audit log",
      "Settings",
    ]);
  });

  it("keeps every route that was already reachable", () => {
    const hrefs = ADMIN_NAV.map((i) => i.href);
    for (const href of [
      "/admin",
      "/admin/users",
      "/admin/subscriptions",
      // The external growth-engine page FE-1 linked as "Sales agents" — still
      // reachable, now under its own name.
      "/admin/sales-agent",
      "/admin/spend",
      "/admin/health",
      "/admin/audit-log",
      "/admin/settings",
    ]) {
      expect(hrefs).toContain(href);
    }
  });

  it("marks the one entry whose screen is still not built, with a reason", () => {
    const billing = ADMIN_NAV.find((i) => i.label === "Billing");
    expect(billing?.pending).toBe(true);
    expect(billing?.pendingReason?.length ?? 0).toBeGreaterThan(0);
    for (const item of ADMIN_NAV.filter((i) => i.label !== "Billing")) {
      expect(item.pending).toBeFalsy();
    }
  });

  it("points Sales agents at the reseller surface, not the growth-engine page", () => {
    expect(ADMIN_NAV.find((i) => i.label === "Sales agents")?.href).toBe("/admin/sales-agents");
    expect(ADMIN_NAV.find((i) => i.label === "Growth engine")?.href).toBe("/admin/sales-agent");
  });
});

describe("<AdminShell>", () => {
  it("renders a real link for every built section and NO link for a pending one", () => {
    render(
      <AdminShell>
        <p>child</p>
      </AdminShell>,
    );
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("/admin");
    expect(screen.getByRole("link", { name: "Sales agents" }).getAttribute("href")).toBe(
      "/admin/sales-agents",
    );
    expect(screen.getByRole("link", { name: "Growth engine" }).getAttribute("href")).toBe(
      "/admin/sales-agent",
    );
    expect(screen.getByRole("link", { name: "Promos" }).getAttribute("href")).toBe(
      "/admin/promos",
    );
    expect(screen.queryByRole("link", { name: "Billing" })).toBeNull();
    const billing = screen.getByTestId("admin-nav-pending-/admin/billing");
    expect(billing.getAttribute("aria-disabled")).toBe("true");
    expect(billing.getAttribute("title")?.length ?? 0).toBeGreaterThan(0);
  });

  it("still renders its children", () => {
    render(
      <AdminShell>
        <p>child</p>
      </AdminShell>,
    );
    expect(screen.getByText("child")).toBeTruthy();
  });
});
