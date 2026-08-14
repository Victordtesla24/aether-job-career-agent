"use client";

/**
 * S-UI-REBUILD §1 — the dashboard frame, assembled.
 *
 * Rail (desktop) + command bar + mobile nav sheet + mobile tab bar around the
 * routed page. It exists because three of those four surfaces need to agree
 * on two things a server component cannot hold:
 *
 *  1. the hamburger's open/closed state (U-NAV-MOBILE-01), and
 *  2. ONE `GET /billing/subscription` shared by the rail and the sheet — see
 *     `shell-context.tsx`. Fetching it twice would add a request that does
 *     not exist on `main`, and behavioural parity is checked by diffing the
 *     request list.
 *
 * `MotionConfig reducedMotion="user"` sits here, at the shell root, so it
 * covers the chrome AND every routed page beneath it (§2.5 layer 2). Framer
 * then drops transform/position animation and keeps opacity automatically for
 * every `motion` element in the tree. Layers 1 (the global CSS block) and 3
 * (components that read `useReducedMotion()` and render a static equivalent
 * IN WORDS) are unchanged by this batch.
 */

import { usePathname } from "next/navigation";
import { MotionConfig } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { fetchSubscription, type SubscriptionState } from "../../lib/api/billing";
import { MobileTabBar } from "../mobile-tab-bar";
import { CommandBar } from "./CommandBar";
import { MobileNavSheet } from "./MobileNavSheet";
import { Rail } from "./Rail";
import { ShellSubscriptionContext } from "./shell-context";

export function AppShell({
  children,
  supportEmail = null,
}: {
  children: ReactNode;
  supportEmail?: string | null;
}) {
  const pathname = usePathname();
  const currentHref = pathname ?? "/dashboard";
  const [navOpen, setNavOpen] = useState(false);
  // undefined = loading, null = fetch failed (honest fallback), otherwise the
  // real GET /billing/subscription state. Exactly one request per page, the
  // same one the sidebar has always made.
  const [subscription, setSubscription] = useState<SubscriptionState | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    fetchSubscription()
      .then((s) => {
        if (!cancelled) setSubscription(s);
      })
      .catch(() => {
        if (!cancelled) setSubscription(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // §1.5: the sheet closes on route change.
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  // Body scroll lock while the sheet owns the viewport.
  useEffect(() => {
    if (!navOpen) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [navOpen]);

  const shellSubscription = useMemo(() => ({ value: subscription }), [subscription]);

  return (
    <MotionConfig reducedMotion="user">
      <ShellSubscriptionContext.Provider value={shellSubscription}>
        <div className="flex min-h-screen">
          <Rail supportEmail={supportEmail} />
          <div className="flex min-w-0 flex-1 flex-col">
            <CommandBar onOpenNav={() => setNavOpen(true)} />
            {/* X-13: clearance for the fixed mobile tab bar, including the
                device's own safe-area inset. */}
            <main className="flex-1 px-4 py-5 pb-[calc(72px+env(safe-area-inset-bottom))] sm:px-6 lg:px-8 lg:py-7 lg:pb-7">
              {children}
            </main>
            <MobileTabBar />
          </div>
        </div>
        <MobileNavSheet
          open={navOpen}
          onClose={() => setNavOpen(false)}
          currentHref={currentHref}
          supportEmail={supportEmail}
        />
      </ShellSubscriptionContext.Provider>
    </MotionConfig>
  );
}

export default AppShell;
