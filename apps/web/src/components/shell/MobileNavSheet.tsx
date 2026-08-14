"use client";

/**
 * S-UI-REBUILD §1.5 — the fix for **U-NAV-MOBILE-01 (HIGH)**.
 *
 * THE DEFECT
 * ----------
 * `Sidebar` is `hidden lg:flex` and `MobileTabBar` exposes 5 of the 13
 * `NAV_ITEMS`. There was no drawer, no "More", no hamburger anywhere in the
 * dashboard shell, so below 1024px **eight paid features were unreachable
 * except by typing the URL**: Resume Studio, Cover Letter Studio, Story
 * Bank, Interview Center, Networking, Email Center, Analytics and Offers. On
 * a subscription product that is a paid-feature blackout on phones.
 *
 * THE FIX
 * -------
 * An affordance over routes that already exist. This sheet adds NO API call,
 * NO new route and NO behaviour: it renders the same `NAV_ITEMS` contract the
 * rail renders, in the same order, with the same additive grouping, and the
 * plan/quota block reads the subscription the shell ALREADY fetched (see
 * `shell-context.tsx` — one request per page, exactly as on `main`).
 *
 * A11y: `role="dialog"` + `aria-modal="true"`, focus moves in on open and is
 * trapped by a wrap-around Tab handler, `Escape` closes, and focus returns to
 * the trigger the shell owns. The scrim cross-fades separately from the panel
 * (pattern M4).
 */

import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef } from "react";

import { DURATION, EASE, SPRING } from "../../lib/motion";
import { groupedNavItems } from "../../lib/navigation-groups";
import { useShellSubscription } from "./shell-context";
import { SystemStatus } from "./SystemStatus";

const FOCUSABLE =
  'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

function isActive(currentHref: string, href: string): boolean {
  return href === "/dashboard"
    ? currentHref === "/dashboard"
    : currentHref === href || currentHref.startsWith(`${href}/`);
}

export function MobileNavSheet({
  open,
  onClose,
  currentHref,
  supportEmail = null,
}: {
  open: boolean;
  onClose: () => void;
  currentHref: string;
  supportEmail?: string | null;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const items = groupedNavItems();
  const shared = useShellSubscription();
  const subscription = shared ? shared.value : undefined;

  useEffect(() => {
    if (!open) return undefined;
    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>(FOCUSABLE)?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!nodes || nodes.length === 0) return;
      const first = nodes[0]!;
      const last = nodes[nodes.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open ? (
        <div className="lg:hidden" data-testid="mobile-nav-sheet-root">
          <motion.div
            aria-hidden="true"
            data-testid="mobile-nav-scrim"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DURATION.base, ease: EASE }}
            className="fixed inset-0 z-40 bg-black/50"
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            data-testid="mobile-nav-sheet"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={SPRING.smooth}
            className="chrome-blur fixed inset-y-0 left-0 z-50 flex w-[19rem] max-w-[85vw] flex-col overflow-y-auto border-r border-hairline px-4 py-5"
          >
            <div className="mb-5 flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-aether-coral to-aether-amber">
                <i className="fa-solid fa-bolt text-[13px] text-white" aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] font-semibold leading-none">Aether</div>
                <div className="type-meta mt-1 truncate">Career Agent</div>
              </div>
              <button
                type="button"
                data-testid="mobile-nav-close"
                onClick={onClose}
                aria-label="Close navigation"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-aether-muted transition-colors duration-[--dur-fast] hover:bg-surface-2 hover:text-aether-text focus:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/60"
              >
                <i className="fa-solid fa-xmark text-sm" aria-hidden="true" />
              </button>
            </div>

            <nav aria-label="All sections" className="flex flex-col">
              {items.map((item) => {
                const active = isActive(currentHref, item.href);
                return (
                  <div key={item.href}>
                    {item.groupLabel ? (
                      <p className="type-section mb-1.5 mt-4 px-3 first:mt-0">{item.groupLabel}</p>
                    ) : null}
                    <Link
                      href={item.href}
                      prefetch={false}
                      onClick={onClose}
                      aria-current={active ? "page" : undefined}
                      data-testid={`mobile-nav-link-${item.href}`}
                      className={`relative flex min-h-[44px] items-center gap-3 rounded-lg px-3 py-2 text-[14px] ${
                        active
                          ? "bg-surface-2 font-medium text-aether-coral"
                          : "text-aether-muted hover:bg-surface-2 hover:text-aether-text"
                      }`}
                    >
                      {active ? (
                        <span
                          aria-hidden="true"
                          className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-aether-coral"
                        />
                      ) : null}
                      <i className={`${item.icon} w-4 shrink-0 text-center`} aria-hidden="true" />
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    </Link>
                  </div>
                );
              })}
            </nav>

            <div className="mt-auto flex flex-col gap-2 pt-5">
              {/* Same honest plan/quota readout as the rail, from the SAME
                  single GET /billing/subscription the shell already made. */}
              <div className="elev-2 rounded-xl p-3" data-testid="mobile-nav-plan-quota">
                {subscription === undefined ? (
                  <div aria-hidden="true" className="space-y-2">
                    <span className="block h-3 w-24 animate-pulse rounded bg-white/10" />
                    <span className="block h-2.5 w-32 animate-pulse rounded bg-white/10" />
                  </div>
                ) : subscription === null ? (
                  <p className="type-meta">Plan unavailable</p>
                ) : subscription.entitlement?.unlimited === true ? (
                  /* ADMIN-FULL / OWNER EXPERIENCE: same honest owner state as
                     the rail — an owner has no plan and no quota, so no number
                     is shown and no upgrade is offered. */
                  <>
                    <p className="text-xs font-medium" data-testid="mobile-nav-plan-name">
                      Owner — unlimited
                    </p>
                    <p
                      className="type-mono-micro mt-1 text-aether-muted-dim"
                      data-testid="mobile-nav-plan-unlimited"
                    >
                      No plan, quota or spend cap
                    </p>
                  </>
                ) : (
                  <>
                    <p className="text-xs font-medium">{subscription.plan?.name ?? "Free plan"}</p>
                    {subscription.quota ? (
                      <p className="type-mono-micro mt-1 text-aether-muted-dim">
                        {subscription.quota.runsUsed}/{subscription.quota.runsAllowed} runs this
                        period
                      </p>
                    ) : (
                      <p className="type-meta mt-1">No usage quota on record</p>
                    )}
                  </>
                )}
              </div>

              <SystemStatus />

              <div className="flex flex-wrap gap-x-3 gap-y-1 px-1 text-[11px] text-aether-muted-dim">
                <Link href="/privacy-policy" prefetch={false} onClick={onClose}>
                  Privacy Policy
                </Link>
                <span>·</span>
                <Link href="/terms" prefetch={false} onClick={onClose}>
                  Terms
                </Link>
                {supportEmail ? (
                  <>
                    <span>·</span>
                    <a href={`mailto:${supportEmail}`}>Contact support</a>
                  </>
                ) : null}
              </div>
            </div>
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );
}

export default MobileNavSheet;
