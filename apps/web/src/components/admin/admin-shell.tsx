"use client";

/**
 * Admin panel chrome (GAP-P6-ADMIN-001): a left nav shared by every /admin/*
 * page, styled with the same `aether` dark tokens as the dashboard shell.
 *
 * ML-admin-002: below the `md` breakpoint the sidebar is taken out of normal
 * document flow (`fixed`) and hidden off-canvas by default, so it can never
 * squeeze `main` into a too-narrow column that forces content to overflow
 * the document horizontally at mobile widths. A hamburger button in a
 * mobile-only top bar toggles it open as a slide-in drawer with a backdrop.
 * At `md` and above the sidebar reverts to its original always-visible,
 * in-flow layout — desktop is unchanged.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

export interface AdminNavItem {
  href: string;
  label: string;
  /** The section is part of ADMIN-2.0 but its screen is not in this tree yet. */
  pending?: boolean;
  /** REQUIRED when `pending`. Rendered as the row's title attribute. */
  pendingReason?: string;
  /**
   * One line saying which system this section is, for rows whose label alone
   * cannot separate them from a neighbour. Rendered as the link's title.
   */
  hint?: string;
}

/**
 * ADMIN-2.0 — the admin sections, in the order the brief fixes:
 * Dashboard, Users, Subscriptions, Billing, Sales agents, Promos, Spend,
 * Health, Audit log, Settings. Money and accounts first, operations after.
 *
 * R2.2 adds `/admin/billing`: a catalog editor for the local AUD prices used
 * for future checkout. It is intentionally not a subscriber-management screen:
 * updating a catalog price does not mutate immutable Stripe Prices or reprice
 * existing subscriptions, so the Billing entry is now a real route.
 *
 * FE-2 flipped PROMOS the same way: `app/admin/promos/page.tsx` now exists, so
 * the entry is a real link.
 *
 * TWO DIFFERENT SALES SYSTEMS LIVE IN THIS CONSOLE, and the nav must not blur
 * them. `/admin/sales-agents` (plural) is the ADMIN-2.0 BE-2 RESELLER surface:
 * human resellers, referral codes, attributed signups, commission reports. It
 * moves no money and sends no mail. `/admin/sales-agent` (singular) is the
 * NATIVE SALES AI AGENT console: an in-app autonomous outreach agent with its
 * own tables, a 30-minute systemd timer, an admin "Run now", and real Gmail
 * sends gated by a shadow/LIVE switch. Unrelated systems, unrelated sources of
 * truth — so each keeps its own route, its own name, and a `hint` saying which
 * one it is, because "Sales agents" and "Sales AI agent" are not
 * self-disambiguating on adjacent rows.
 *
 * REFIX ROUND 1 — WHY THAT WORDING CHANGED. Until `origin/main@382f0c2`, the
 * singular route was a placeholder and this file called it "Growth engine", a
 * "read-only window onto the EXTERNAL growth engine ... that has no backend
 * here". `382f0c2` replaced that placeholder with the native agent described
 * above, which made the label and the description false — an admin nav calling
 * a live outbound-email console an inert external window is precisely the kind
 * of fabricated claim this programme forbids. Both are corrected here as part
 * of merging that commit, rather than carried forward.
 *
 * `admin-nav.test.tsx` pins the order, both hrefs, both labels, the presence of
 * both hints, that the singular entry is never again described as external, and
 * that nothing already reachable became unreachable.
 */
export const ADMIN_NAV: readonly AdminNavItem[] = [
  { href: "/admin", label: "Dashboard" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/subscriptions", label: "Subscriptions" },
  { href: "/admin/billing", label: "Billing" },
  {
    href: "/admin/sales-agents",
    label: "Sales agents",
    hint: "Human resellers: referral codes, attributed signups and commission reports. Reporting only — it pays nobody.",
  },
  {
    href: "/admin/sales-agent",
    label: "Sales AI agent",
    hint: "The native in-app outreach agent: campaigns, leads, outreach log and LinkedIn drafts. It sends real email whenever it is not in shadow mode.",
  },
  { href: "/admin/promos", label: "Promos" },
  { href: "/admin/spend", label: "Spend" },
  { href: "/admin/health", label: "Health" },
  { href: "/admin/audit-log", label: "Audit log" },
  { href: "/admin/settings", label: "Settings" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/admin";
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Close the drawer on every route change (including desktop->mobile nav).
  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  return (
    <div className="flex min-h-screen bg-aether-bg text-aether-text">
      {mobileNavOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-50 w-56 shrink-0 -translate-x-full border-r border-white/10 bg-aether-bg-elevated px-3 py-5 transition-transform duration-200 ease-out md:static md:z-auto md:translate-x-0 ${
          mobileNavOpen ? "translate-x-0" : ""
        }`}
      >
        <div className="mb-6 px-2">
          <p className="text-sm font-semibold text-aether-text">Aether Admin</p>
          <p className="text-xs text-aether-muted-dim">Platform control</p>
        </div>
        <nav className="flex flex-col gap-1">
          {ADMIN_NAV.map((item) =>
            item.pending ? (
              <span
                key={item.href}
                data-testid={`admin-nav-pending-${item.href}`}
                aria-disabled="true"
                title={item.pendingReason}
                className="flex cursor-not-allowed items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-aether-muted-dim"
              >
                {item.label}
                {/* The state is a word, not a colour: a greyed row alone would
                    be indistinguishable from a low-contrast theme. */}
                <span className="type-mono-micro rounded border border-white/10 px-1 py-px text-[9px] uppercase tracking-wide">
                  soon
                </span>
              </span>
            ) : (
              <Link
                key={item.href}
                href={item.href}
                title={item.hint}
                onClick={() => setMobileNavOpen(false)}
                className={`rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive(pathname, item.href)
                    ? "bg-aether-indigo/20 text-aether-text"
                    : "text-aether-muted hover:bg-white/5 hover:text-aether-text"
                }`}
              >
                {item.label}
              </Link>
            ),
          )}
        </nav>
        <div className="mt-8 border-t border-white/10 pt-4 px-2">
          <Link href="/dashboard" className="text-xs text-aether-muted-dim hover:text-aether-text">
            ← Back to dashboard
          </Link>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-white/10 bg-aether-bg-elevated px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open admin menu"
            aria-expanded={mobileNavOpen}
            className="rounded-md border border-white/10 p-2 text-aether-text"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
              <path
                d="M4 6h16M4 12h16M4 18h16"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <p className="text-sm font-semibold text-aether-text">Aether Admin</p>
        </header>
        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

/** Consistent page header. */
export function AdminPageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="mb-6">
      <h1 className="text-xl font-semibold text-aether-text">{title}</h1>
      {subtitle ? <p className="mt-1 text-sm text-aether-muted">{subtitle}</p> : null}
    </header>
  );
}
