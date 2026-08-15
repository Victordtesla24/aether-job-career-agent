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
}

/**
 * ADMIN-2.0 FE-1 — the admin sections, in the order the brief fixes:
 * Dashboard, Users, Subscriptions, Billing, Sales agents, Promos, Spend,
 * Health, Audit log, Settings. Money and accounts first, operations after.
 *
 * WHY TWO ENTRIES ARE MARKED `pending` INSTEAD OF LINKED. BE-1 has already
 * landed the API for both (`GET /admin/billing/summary`, and the
 * `GET/POST/DELETE /admin/promos` trio), but their SCREENS belong to a later
 * frontend slice and do not exist in this tree — there is no
 * `app/admin/billing/page.tsx` and no `app/admin/promos/page.tsx` on any
 * branch. Linking to them anyway would hand the owner two 404s dressed as
 * working sections, which is exactly the kind of fake-completeness this
 * programme forbids. So they hold their place in the stated order, render as
 * visibly disabled with the reason on hover, and become links by deleting one
 * flag when the screens land. `admin-nav.test.tsx` pins both halves of that:
 * the order, and the absence of a live link to a route that does not exist.
 */
export const ADMIN_NAV: readonly AdminNavItem[] = [
  { href: "/admin", label: "Dashboard" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/subscriptions", label: "Subscriptions" },
  {
    href: "/admin/billing",
    label: "Billing",
    pending: true,
    pendingReason:
      "The billing screen is not built yet. Its API (GET /admin/billing/summary) is live; the screen ships in a later ADMIN-2.0 slice.",
  },
  { href: "/admin/sales-agent", label: "Sales agents" },
  {
    href: "/admin/promos",
    label: "Promos",
    pending: true,
    pendingReason:
      "The promotions screen is not built yet. Its API (GET/POST/DELETE /admin/promos) is live; the screen ships in a later ADMIN-2.0 slice.",
  },
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
