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
 *    The pre-existing `/admin/sales-agent` (singular) is a DIFFERENT thing, so
 *    it keeps its own route and its own name — nothing reachable becomes
 *    unreachable, as pinned below.
 *
 * REFIX ROUND 1 — WHAT THE SINGULAR PAGE ACTUALLY IS. When FE-2 wrote this
 * file, `/admin/sales-agent` was a placeholder for an EXTERNAL, Google-Sheet
 * driven outreach process with no backend in this repo, and the nav called it
 * "Growth engine". `origin/main@382f0c2` then replaced that page with the
 * NATIVE Sales AI Agent console — in-app tables, a 30-minute timer, and real
 * Gmail sends behind a shadow/LIVE switch. Merging without touching the nav
 * would have shipped a label and a hint asserting something false about a live
 * money-adjacent surface, so the label is now "Sales AI agent" and the last
 * test below is a standing guard against the old "external / Google Sheet /
 * outside this app" description creeping back in.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN_NAV, AdminShell } from "../admin-shell";

// Vitest hoists `vi.mock` above the imports above, so the stubs are in place
// before `../admin-shell` is evaluated even though they are written after it.
// Mutable so the active-row tests can move between routes. Hoisted because
// `vi.mock` factories run before module-scope statements.
const nav = vi.hoisted(() => ({ pathname: "/admin" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
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
      "Sales AI agent",
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
      // The singular sales-agent page FE-1 linked as "Sales agents" — still
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

  it("links Billing now that its catalog editor exists", () => {
    const billing = ADMIN_NAV.find((i) => i.label === "Billing");
    expect(billing?.href).toBe("/admin/billing");
    expect(billing?.pending).toBeFalsy();
  });

  it("points Sales agents at the reseller surface, not the AI-agent page", () => {
    expect(ADMIN_NAV.find((i) => i.label === "Sales agents")?.href).toBe("/admin/sales-agents");
    expect(ADMIN_NAV.find((i) => i.label === "Sales AI agent")?.href).toBe("/admin/sales-agent");
  });

  it("names the singular page for what it is post-382f0c2 — a native in-app agent", () => {
    const native = ADMIN_NAV.find((i) => i.href === "/admin/sales-agent");
    expect(native?.label).toBe("Sales AI agent");
    // Both same-domain entries carry a hint, because two adjacent rows called
    // "Sales agents" and "Sales AI agent" are not self-disambiguating.
    const reseller = ADMIN_NAV.find((i) => i.href === "/admin/sales-agents");
    expect((native?.hint ?? "").length).toBeGreaterThan(0);
    expect((reseller?.hint ?? "").length).toBeGreaterThan(0);
    // Standing guard: the pre-382f0c2 description must never come back.
    const nativeCopy = `${native?.label ?? ""} ${native?.hint ?? ""}`.toLowerCase();
    expect(nativeCopy).not.toMatch(/external|google sheet|google-sheet|outside this app/);
  });
});

describe("<AdminShell>", () => {
  it("renders a real link for every built section", () => {
    render(
      <AdminShell>
        <p>child</p>
      </AdminShell>,
    );
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("/admin");
    expect(screen.getByRole("link", { name: "Sales agents" }).getAttribute("href")).toBe(
      "/admin/sales-agents",
    );
    expect(screen.getByRole("link", { name: "Sales AI agent" }).getAttribute("href")).toBe(
      "/admin/sales-agent",
    );
    // The hint reaches the DOM, or it disambiguates nothing for the operator.
    expect(
      (screen.getByRole("link", { name: "Sales AI agent" }).getAttribute("title") ?? "").length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Promos" }).getAttribute("href")).toBe(
      "/admin/promos",
    );
    expect(screen.getByRole("link", { name: "Billing" }).getAttribute("href")).toBe(
      "/admin/billing",
    );
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

/**
 * REFIX ROUND 1 — CHARACTERIZATION, NOT A FIX. `isActive` is already correct
 * here (`pathname === href || pathname.startsWith(href + "/")`), and these
 * tests passed the moment they were written; they are NOT part of the RED
 * capture for this round and are not claimed as such.
 *
 * They exist because `/admin/sales-agent` is a strict string prefix of
 * `/admin/sales-agents`, so the two routes that `382f0c2` and ADMIN-2.0 put
 * side by side are one refactor away from highlighting each other: the obvious
 * "simplification" of that predicate to `pathname.startsWith(href)` would light
 * up "Sales AI agent" (the live outbound-email console) while the operator is
 * on the reseller page. Cheap to pin now, invisible to catch later.
 */
describe("the two sales routes do not highlight each other", () => {
  const ACTIVE = "bg-aether-coral/20";

  function classesFor(label: string): string {
    return screen.getByRole("link", { name: label }).getAttribute("class") ?? "";
  }

  function renderAt(pathname: string) {
    nav.pathname = pathname;
    render(
      <AdminShell>
        <p>child</p>
      </AdminShell>,
    );
  }

  afterEach(() => {
    nav.pathname = "/admin";
  });

  it("marks only the reseller row active on /admin/sales-agents", () => {
    renderAt("/admin/sales-agents");
    expect(classesFor("Sales agents")).toContain(ACTIVE);
    expect(classesFor("Sales AI agent")).not.toContain(ACTIVE);
  });

  it("marks only the reseller row active on a nested reseller report page", () => {
    renderAt("/admin/sales-agents/agent_123/report");
    expect(classesFor("Sales agents")).toContain(ACTIVE);
    expect(classesFor("Sales AI agent")).not.toContain(ACTIVE);
  });

  it("marks only the AI-agent row active on /admin/sales-agent", () => {
    renderAt("/admin/sales-agent");
    expect(classesFor("Sales AI agent")).toContain(ACTIVE);
    expect(classesFor("Sales agents")).not.toContain(ACTIVE);
  });

  it("does not mark Dashboard active on any deeper admin route", () => {
    renderAt("/admin/sales-agents");
    expect(classesFor("Dashboard")).not.toContain(ACTIVE);
  });
});
