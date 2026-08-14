"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutGroup, motion } from "framer-motion";

import { SPRING } from "../lib/motion";

/**
 * Mobile bottom tab bar (design/screens/mobile-dashboard.html, m-tabbar-md08).
 * Shown below the lg breakpoint where the desktop rail collapses (DEF-020).
 * Five canonical tabs per the mobile wireframe: Home / Jobs / Apps / Agents / Profile.
 *
 * S-UI-REBUILD §1.5: this bar keeps its five canonical tabs and gains NO
 * sixth tab — the wireframe contract `m-tabbar-md08` fixes both the set and
 * the order. The eight sections it cannot reach are reached through the nav
 * sheet the command bar's hamburger opens (U-NAV-MOBILE-01), which is the
 * overflow affordance this bar deliberately does not become.
 *
 * Restyle only: chrome blur (one of the four permitted blurred surfaces,
 * §1.1), and a 2px coral top bar that SLIDES between tabs via a shared
 * `layoutId` (pattern M5). Touch targets stay >= 56px (DEF-052 / the 44px
 * rule).
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
    <LayoutGroup id="mobile-tabbar">
      <nav
        aria-label="Mobile"
        data-design-id="m-tabbar-md08"
        className="chrome-blur lg:hidden fixed bottom-0 inset-x-0 z-40 border-t border-hairline flex items-stretch justify-around px-1 pb-[env(safe-area-inset-bottom)]"
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
              prefetch={false}
              aria-current={active ? "page" : undefined}
              className={`relative flex flex-col items-center justify-center gap-1 min-w-[56px] min-h-[56px] py-2 text-[10px] font-medium ${
                active ? "text-aether-coral" : "text-aether-muted"
              }`}
            >
              {active ? (
                <motion.span
                  layoutId="tab-active"
                  aria-hidden="true"
                  transition={SPRING.snappy}
                  className="absolute inset-x-2 top-0 h-[2px] rounded-b bg-aether-coral"
                />
              ) : null}
              <i className={`${t.icon} text-base`} aria-hidden="true" />
              {t.label}
            </Link>
          );
        })}
      </nav>
    </LayoutGroup>
  );
}
