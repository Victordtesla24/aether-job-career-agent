"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Mobile bottom tab bar (design/screens/mobile-dashboard.html, m-tabbar-md08).
 * Shown below the lg breakpoint where the desktop sidebar collapses (DEF-020).
 * Five canonical tabs per the mobile wireframe: Home / Jobs / Apps / Agents / Profile.
 */
const TABS = [
  { label: "Home", href: "/dashboard", icon: "fa-solid fa-house" },
  { label: "Jobs", href: "/dashboard/jobs", icon: "fa-solid fa-briefcase" },
  { label: "Apps", href: "/dashboard/applications", icon: "fa-solid fa-table-columns" },
  { label: "Agents", href: "/dashboard/agents", icon: "fa-solid fa-robot" },
  { label: "Profile", href: "/dashboard/settings", icon: "fa-solid fa-user" },
];

export function MobileTabBar() {
  const pathname = usePathname() ?? "/dashboard";
  return (
    <nav
      aria-label="Mobile"
      data-design-id="m-tabbar-md08"
      className="lg:hidden fixed bottom-0 inset-x-0 z-40 glass-raised border-t border-white/10 flex items-stretch justify-around px-1 pb-[env(safe-area-inset-bottom)]"
    >
      {TABS.map((t) => {
        const active =
          t.href === "/dashboard"
            ? pathname === "/dashboard"
            : pathname === t.href || pathname.startsWith(`${t.href}/`);
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={`flex flex-col items-center justify-center gap-1 min-w-[56px] min-h-[56px] py-2 text-[11px] font-medium ${
              active ? "text-aether-coral" : "text-aether-muted"
            }`}
          >
            <i className={`${t.icon} text-base`} aria-hidden="true" />
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
