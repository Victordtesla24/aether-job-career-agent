"use client";

/**
 * S-UI-REBUILD §1.7 — the route transition.
 *
 * App Router re-mounts a `template` on every navigation, which is exactly
 * the hook a page-enter animation needs. The whole transition is an 8px rise
 * + fade over one duration tier, and NO exit animation: the App Router does
 * not hold the outgoing tree without extra machinery, and fighting that buys
 * nothing while costing a whole class of stale-DOM bugs (§1.7).
 *
 * Reduced motion is handled one level up by `MotionConfig reducedMotion="user"`
 * in `components/shell/AppShell.tsx`: framer drops the `y` and leaves an
 * instant opacity swap, so the page still arrives, just without the travel.
 *
 * This element is a `div`, not a `main` — `AppShell` already owns the page's
 * single `<main>` landmark, and nesting a second one would be an a11y defect.
 */

import { motion } from "framer-motion";
import type { ReactNode } from "react";

import { PAGE_TRANSITION } from "../../lib/motion";

export default function DashboardTemplate({ children }: { children: ReactNode }) {
  return (
    <motion.div
      data-testid="page-transition"
      initial={PAGE_TRANSITION.initial}
      animate={PAGE_TRANSITION.animate}
      transition={PAGE_TRANSITION.transition}
    >
      {children}
    </motion.div>
  );
}
