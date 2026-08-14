/**
 * S-UI-REBUILD §1.2 — presentational grouping for the rail. ADDITIVE ONLY.
 *
 * `NAV_ITEMS` in `./navigation.ts` is a tested contract: `__tests__/
 * navigation.test.ts` asserts its exact order and labels, and DECISIONS
 * D-0002 owns it. This module does not import-and-reshuffle it; it only
 * declares which *runs* of that existing order carry a group eyebrow. The
 * rail still renders `NAV_ITEMS` in `NAV_ITEMS` order and merely prints a
 * heading when the group changes.
 *
 * WHY THE GROUPS ARE NOT THE ONES THE SPEC SKETCHED
 * ------------------------------------------------
 * The §1.2 sketch put Applications in WORK and Offers in PIPELINE. Both sit
 * elsewhere in the shipped order (Applications is 6th, after Story Bank;
 * Offers is 12th, after Analytics), so honouring that sketch would require
 * reordering a tested contract. §1.2's own rule settles it: *"If the
 * partition cannot reproduce the exact existing order, the group boundaries
 * move — never the items."* The boundaries below are therefore the closest
 * contiguous cover of the real order, and the one visible consequence is
 * disclosed rather than hidden: **Offers is grouped under SYSTEM**, because
 * it sits between Analytics and Settings in the contract.
 *
 * An href that appears in no group renders with no eyebrow — it is never
 * dropped from the rail.
 */
import { NAV_ITEMS } from "./navigation";

export interface NavGroup {
  /** Eyebrow text, rendered uppercase at 10px. */
  label: string;
  /** Hrefs belonging to this group, as they appear in `NAV_ITEMS`. */
  hrefs: string[];
}

export const NAV_GROUPS: NavGroup[] = [
  { label: "Work", hrefs: ["/dashboard", "/dashboard/jobs"] },
  {
    label: "Studio",
    hrefs: ["/dashboard/resume", "/dashboard/cover-letters", "/dashboard/stories"],
  },
  {
    label: "Pipeline",
    hrefs: [
      "/dashboard/applications",
      "/dashboard/interviews",
      "/dashboard/networking",
      "/dashboard/email",
    ],
  },
  {
    label: "System",
    hrefs: ["/dashboard/agents", "/dashboard/analytics", "/dashboard/offers"],
  },
  { label: "Account", hrefs: ["/dashboard/settings"] },
];

export interface GroupedNavItem {
  label: string;
  href: string;
  icon: string;
  /**
   * The eyebrow to print ABOVE this item, or `null` when the previous item
   * already belongs to the same group (or this item belongs to none).
   */
  groupLabel: string | null;
}

const GROUP_OF_HREF: ReadonlyMap<string, string> = new Map(
  NAV_GROUPS.flatMap((group) => group.hrefs.map((href) => [href, group.label] as const)),
);

/**
 * `NAV_ITEMS`, in `NAV_ITEMS` order, annotated with the eyebrow each item
 * should be preceded by. Pure; safe in a server component or a test.
 */
export function groupedNavItems(): GroupedNavItem[] {
  let previousGroup: string | null = null;
  return NAV_ITEMS.map((item) => {
    const group = GROUP_OF_HREF.get(item.href) ?? null;
    const groupLabel = group !== null && group !== previousGroup ? group : null;
    previousGroup = group;
    return { ...item, groupLabel };
  });
}
