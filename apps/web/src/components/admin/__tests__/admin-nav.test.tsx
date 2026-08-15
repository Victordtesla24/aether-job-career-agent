// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-1 — the admin nav after the dashboard rebuild.
 *
 * RED-first: the reordered nav does not exist yet.
 *
 * The brief fixes the section order (Dashboard, Users, Subscriptions, Billing,
 * Sales agents, Promos, Spend, Health, Audit log, Settings) and requires that
 * nothing already reachable becomes unreachable.
 *
 * BILLING AND PROMOS DO NOT HAVE PAGES IN THIS TREE YET (BE-1 shipped
 * `/admin/billing/summary` and `/admin/promos` on the API; the screens are a
 * later FE slice). A nav that links to them anyway would hand the owner two
 * 404s, so the two entries render as declared-but-not-yet-built rows: present
 * in the stated order, visibly disabled, and carrying the reason. When the
 * screens land, the entry flips one flag. What is NOT acceptable — and is
 * pinned below — is a live-looking link to a route that does not exist.
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
      "/admin/sales-agent",
      "/admin/spend",
      "/admin/health",
      "/admin/audit-log",
      "/admin/settings",
    ]) {
      expect(hrefs).toContain(href);
    }
  });

  it("marks the two entries whose screens are not built yet, with a reason", () => {
    for (const label of ["Billing", "Promos"]) {
      const item = ADMIN_NAV.find((i) => i.label === label);
      expect(item?.pending).toBe(true);
      expect(item?.pendingReason?.length ?? 0).toBeGreaterThan(0);
    }
    for (const item of ADMIN_NAV.filter((i) => !["Billing", "Promos"].includes(i.label))) {
      expect(item.pending).toBeFalsy();
    }
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
      "/admin/sales-agent",
    );
    expect(screen.queryByRole("link", { name: "Billing" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Promos" })).toBeNull();
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
