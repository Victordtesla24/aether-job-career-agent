/**
 * Primary navigation contract for the Aether dashboard (Schema A).
 *
 * This module is intentionally free of React / Next imports so it can be
 * consumed by server components, client components, and unit tests running
 * under a plain Node environment alike. The order and labels defined here are
 * the single source of truth referenced by DECISIONS D-0002 and are asserted
 * by `__tests__/navigation.test.ts`.
 *
 * `icon` holds a Font Awesome 6 class name (rendered as `<i className={icon} />`).
 */
export interface NavItem {
  /** Human-readable label shown in the sidebar. */
  label: string;
  /** App Router route the item links to. */
  href: string;
  /** Font Awesome 6 icon class, e.g. "fa-solid fa-gauge-high". */
  icon: string;
}

/**
 * The canonical 13-item primary sidebar, in display order.
 * "Resume Studio" is intentionally written without accents (D-0002).
 * "Cover Letter Studio" sits between Resume Studio and Story Bank (D-0002
 * amendment, 2026-07-12): the screen is now a real workspace at
 * /dashboard/cover-letters, so it is no longer the "phantom" entry Schema B
 * was rejected for.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: "fa-solid fa-gauge-high" },
  { label: "Jobs", href: "/dashboard/jobs", icon: "fa-solid fa-magnifying-glass" },
  { label: "Resume Studio", href: "/dashboard/resume", icon: "fa-solid fa-file-lines" },
  { label: "Cover Letter Studio", href: "/dashboard/cover-letters", icon: "fa-solid fa-envelope-open-text" },
  { label: "Story Bank", href: "/dashboard/stories", icon: "fa-solid fa-book-bookmark" },
  { label: "Applications", href: "/dashboard/applications", icon: "fa-solid fa-paper-plane" },
  { label: "Interview Center", href: "/dashboard/interviews", icon: "fa-solid fa-microphone-lines" },
  { label: "Networking", href: "/dashboard/networking", icon: "fa-solid fa-handshake" },
  { label: "Email Center", href: "/dashboard/email", icon: "fa-solid fa-envelope" },
  { label: "Agents", href: "/dashboard/agents", icon: "fa-solid fa-robot" },
  { label: "Analytics", href: "/dashboard/analytics", icon: "fa-solid fa-chart-line" },
  { label: "Offers", href: "/dashboard/offers", icon: "fa-solid fa-scale-balanced" },
  { label: "Settings", href: "/dashboard/settings", icon: "fa-solid fa-gear" },
];

/**
 * Resolve a pathname to the nav item that "owns" it.
 *
 * Used by the sidebar to highlight the active section from the current
 * pathname, and by the graceful placeholder shown for dashboard sections whose
 * page has not been built yet (P1-S12). Matching is prefix-based so nested
 * routes (e.g. `/dashboard/jobs/123`) resolve to their section, and the most
 * specific match wins so `/dashboard/analytics` never collapses to Dashboard.
 * Returns `undefined` for a path that maps to no known section.
 */
export function findNavItemByHref(href: string): NavItem | undefined {
  const specific = NAV_ITEMS.filter((item) => item.href !== "/dashboard")
    .filter((item) => href === item.href || href.startsWith(`${item.href}/`))
    .sort((a, b) => b.href.length - a.href.length);

  if (specific.length > 0) {
    return specific[0];
  }

  if (href === "/dashboard") {
    return NAV_ITEMS[0];
  }

  return undefined;
}
