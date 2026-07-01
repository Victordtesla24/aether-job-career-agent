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
 * The canonical 12-item primary sidebar, in display order.
 * "Resume Studio" is intentionally written without accents (D-0002).
 */
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: "fa-solid fa-gauge-high" },
  { label: "Jobs", href: "/dashboard/jobs", icon: "fa-solid fa-magnifying-glass" },
  { label: "Resume Studio", href: "/dashboard/resume", icon: "fa-solid fa-file-lines" },
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
