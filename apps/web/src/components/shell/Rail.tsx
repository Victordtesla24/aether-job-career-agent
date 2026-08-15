"use client";

/**
 * S-UI-REBUILD §1.2 — the sidebar becomes the RAIL.
 *
 * WHAT CHANGED AND WHAT DID NOT
 * -----------------------------
 * Thirteen equal-weight links are now grouped, collapsible, and carry live
 * counts. Nothing about the WIRING moved: the same `fetchAgents` poll on the
 * same 30s interval feeding the same `agentPulse()` staleness verdict
 * (CRITICAL-2), the same one-shot `fetchSubscription()`, the same
 * `NAV_ITEMS` in the same order, the same `supportEmail` conditional, the
 * same testids and the same copy. `NAV_ITEMS` itself is NOT edited — it is a
 * tested contract (`__tests__/navigation.test.ts`); grouping is applied by
 * the additive `lib/navigation-groups.ts` partition, which prints an eyebrow
 * when a group boundary is crossed and reorders nothing.
 *
 * COUNTS ARE REAL OR ABSENT (§1.2)
 * --------------------------------
 * Jobs / Applications counts come from `useRealtimeSnapshot()` — a READER
 * over the one existing SSE store. It opens no connection and issues no
 * fetch: on a page whose screens subscribe to nothing, the store is idle,
 * there is no observation, and the rail renders NO NUMBER rather than a
 * placeholder or a stale cache. The Agents `N` running count is
 * `agentPulse().running`, exactly as the old sidebar computed it.
 *
 * COLOUR-FLAT (reference-pack rule 2)
 * -----------------------------------
 * The rail shares the page ground: no `.glass`, no blur, no card boundary —
 * only a hairline right edge. Linear and Perplexity both do this, and it is
 * what stops a sidebar reading as a bolted-on panel. Blur in this app is
 * reserved for the command bar, the mobile sheet/tab bar and `elev-3`
 * overlays (§1.1).
 *
 * VIEWPORT-PINNED (doctrine D-ε — "the chrome does not scroll away")
 * -----------------------------------------------------------------
 * `sticky top-0 h-screen` is load-bearing, not cosmetic. Without the explicit
 * height the rail is a plain flex item: `align-items` stretches it to the
 * whole row, whose height is the ROUTED PAGE's height (measured 2007.5px on a
 * 1000px viewport), and the `mt-auto` footer group below then parks the
 * plan/quota block, "Agents Active" and the §1.4 SystemStatus trigger at the
 * bottom of THAT box — 908px below the fold — while every nav link scrolls
 * off the top after an ordinary 900px wheel scroll (there is no `lg`
 * hamburger fallback; the sheet trigger is `lg:hidden`). The rail's own
 * content is only ~941px tall, so it was never too big for the screen; it was
 * simply never given a box of its own.
 *
 * The explicit `h-screen` overrides flex stretch (a definite cross size beats
 * `align-self: stretch`), which is what finally gives the pre-existing
 * `overflow-y-auto` something to clip against: on viewports shorter than the
 * rail's content the NAV scrolls inside the rail instead of taking the page
 * with it. `overscroll-contain` stops that inner scroll from chaining out to
 * the document once it bottoms out. `AppShell`'s `flex min-h-screen` wrapper
 * is deliberately left alone — it is the sticky containing block and it keeps
 * the ground full-height on short pages.
 *
 * Same shape as `MobileNavSheet`'s `fixed inset-y-0 left-0 … overflow-y-auto`,
 * chosen as `sticky` here so the content column keeps its normal flow width
 * and needs no compensating offset.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutGroup, motion } from "framer-motion";
import { useEffect, useState } from "react";

import { useRealtimeSnapshot } from "../../hooks/useRealtime";
import { agentPulse, type AgentPulse } from "../../lib/agent-run-health";
import { fetchAgents } from "../../lib/api/agents";
import { fetchSubscription, type SubscriptionState } from "../../lib/api/billing";
import { groupedNavItems } from "../../lib/navigation-groups";
import { SPRING } from "../../lib/motion";
import { useShellSubscription } from "./shell-context";
import { SystemStatus } from "./SystemStatus";

/** Persisted collapse preference. */
const COLLAPSE_KEY = "aether.rail.collapsed";

/** Nav hrefs whose count the realtime snapshot can honestly supply. */
const COUNTED_RESOURCE: Record<string, "jobs" | "applications"> = {
  "/dashboard/jobs": "jobs",
  "/dashboard/applications": "applications",
};

function isActive(currentHref: string, href: string): boolean {
  return href === "/dashboard"
    ? currentHref === "/dashboard"
    : currentHref === href || currentHref.startsWith(`${href}/`);
}

export function Rail({
  activeHref,
  supportEmail = null,
}: {
  activeHref?: string;
  supportEmail?: string | null;
}) {
  const pathname = usePathname();
  const currentHref = activeHref ?? pathname ?? "/dashboard";
  // undefined = loading, null = unavailable, otherwise live counts
  const [pulse, setPulse] = useState<AgentPulse | null | undefined>(undefined);
  // MV-dashboard-006: no plan/quota indicator existed anywhere on the
  // dashboard hub despite a real, populated quota system server-side.
  // undefined = loading, null = fetch failed (honest fallback), otherwise
  // the real GET /billing/subscription state.
  const [selfSubscription, setSubscription] = useState<SubscriptionState | null | undefined>(
    undefined,
  );
  const [collapsed, setCollapsed] = useState(false);
  const snapshot = useRealtimeSnapshot();
  // When the shell provides it, the rail must NOT fetch: exactly one
  // GET /billing/subscription per page, shared with the mobile nav sheet.
  const sharedSubscription = useShellSubscription();
  const hasSharedSubscription = sharedSubscription !== null;

  // Read the persisted preference AFTER mount so SSR and the first client
  // render agree (no hydration mismatch), then adopt it.
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      // Private-mode / blocked storage: stay expanded. Not worth surfacing.
    }
  }, []);

  // Publish the rail's current width so PORTALED overlays (the SystemStatus
  // popover lives on `document.body`, out of this subtree, to escape the
  // rail's own `overflow` clipping) can sit beside the rail instead of on
  // top of it. A CSS variable rather than a measured pixel value: nothing to
  // go stale on resize, and no layout read per frame.
  useEffect(() => {
    document.documentElement.style.setProperty("--aether-rail-w", collapsed ? "64px" : "248px");
  }, [collapsed]);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchAgents()
        .then((agents) => {
          if (cancelled) return;
          // CRITICAL-2: an agent whose latest run merely SAYS "running" is not
          // necessarily working. `agentPulse` applies the same staleness window
          // the rest of the UI uses, so a run abandoned days ago can no longer
          // light up "Agents Active" — that badge is exactly what made a week
          // of total inactivity look like a busy system.
          setPulse(agentPulse(agents));
        })
        .catch(() => {
          if (!cancelled) setPulse(null);
        });
    load();
    const timer = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (hasSharedSubscription) return undefined;
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
  }, [hasSharedSubscription]);

  function toggleCollapsed(): void {
    setCollapsed((previous) => {
      const next = !previous;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        // Preference simply is not persisted; the session still honours it.
      }
      return next;
    });
  }

  const running = pulse?.running ?? 0;
  const stalled = pulse?.stalled ?? 0;
  const agentsActive = running > 0;
  const items = groupedNavItems();
  const subscription = sharedSubscription ? sharedSubscription.value : selfSubscription;

  /** A count the channel has actually observed, or null. Never a guess. */
  function countFor(href: string): number | null {
    const resource = COUNTED_RESOURCE[href];
    if (!resource) {
      // The Agents row shows RUNNING agents, from the poll the rail already
      // makes — not a row count.
      if (href === "/dashboard/agents") return agentsActive ? running : null;
      return null;
    }
    const entry = snapshot.resources.find((row) => row.resource === resource);
    return entry ? entry.count : null;
  }

  const quota = subscription ? subscription.quota : null;
  const quotaPercent =
    quota && quota.runsAllowed > 0
      ? Math.min(100, Math.round((quota.runsUsed / quota.runsAllowed) * 100))
      : null;

  return (
    <motion.aside
      data-testid="app-rail"
      data-collapsed={collapsed ? "true" : "false"}
      aria-label="Primary navigation rail"
      // Reference rule 2: colour-flat against the page — a hairline edge, no
      // surface of its own, no blur.
      // `sticky top-0 h-screen`: D-ε — the chrome stays on screen and the nav
      // scrolls INSIDE the rail. See the module docstring for the measurement.
      className="sticky top-0 hidden h-screen shrink-0 flex-col overflow-y-auto overflow-x-hidden overscroll-contain border-r border-hairline px-3 py-5 lg:flex"
      initial={false}
      animate={{ width: collapsed ? 64 : 248 }}
      transition={SPRING.smooth}
    >
      <div
        className={`mb-6 flex gap-2.5 ${
          collapsed ? "flex-col items-center" : "items-center px-2"
        }`}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-gold to-gold-dark">
          <i className="fa-solid fa-bolt text-[13px] text-[#0a0a0a]" aria-hidden="true" />
        </div>
        {collapsed ? null : (
          <div className="min-w-0 flex-1">
            <div className="truncate font-display text-[15px] font-semibold uppercase leading-none tracking-[0.08em]">
              Aether
            </div>
            <div className="type-meta mt-1 truncate">Career Agent</div>
          </div>
        )}
        <button
          type="button"
          data-testid="rail-collapse-toggle"
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand navigation rail" : "Collapse navigation rail"}
          aria-pressed={collapsed}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-aether-muted-dim transition-colors duration-[--dur-fast] hover:bg-surface-2 hover:text-aether-text focus:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/60"
        >
          <i
            className={`fa-solid ${collapsed ? "fa-angles-right" : "fa-angles-left"} text-[11px]`}
            aria-hidden="true"
          />
        </button>
      </div>

      <LayoutGroup id="rail">
        <nav aria-label="Primary" className="flex flex-col">
          {items.map((item) => {
            const active = isActive(currentHref, item.href);
            const count = countFor(item.href);
            return (
              <div key={item.href}>
                {item.groupLabel && !collapsed ? (
                  <p className="type-section mb-1.5 mt-5 px-3 first:mt-0">{item.groupLabel}</p>
                ) : null}
                {item.groupLabel && collapsed ? (
                  <hr className="mx-2 my-2 border-t border-hairline first:mt-0" aria-hidden="true" />
                ) : null}
                <Link
                  href={item.href}
                  prefetch={false}
                  aria-current={active ? "page" : undefined}
                  /*
                   * §1.2 asks for an `elev-3` tooltip on the collapsed label.
                   * The rail is a scroll container (`overflow-x-hidden`), so a
                   * DOM tooltip positioned to its right would be CLIPPED, and
                   * portaling one per item would mean 13 measured overlays for
                   * a label the accessible name already carries. The native
                   * `title` is the honest trade: it appears on hover, it is
                   * not clipped by any ancestor, and the `sr-only` label below
                   * keeps the destination announced either way.
                   */
                  title={collapsed ? item.label : undefined}
                  className={`group relative flex items-center gap-3 rounded-lg py-2 text-[13px] transition-colors duration-[--dur-fast] focus:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/60 ${
                    collapsed ? "justify-center px-0" : "px-3"
                  } ${
                    active
                      ? "bg-surface-2 font-medium text-aether-coral"
                      : "text-aether-muted hover:bg-surface-2 hover:text-aether-text"
                  }`}
                >
                  {/*
                    §1.2 / M5 — the one premium micro-interaction: a shared
                    `layoutId` makes the 3px coral bar SLIDE between items
                    instead of teleporting. Reference rule 8 (minimal active
                    states) is why the indicator is a bar and the fill is
                    `surface-2` — a near-invisible step above the ground —
                    rather than a saturated pill.
                  */}
                  {active ? (
                    <motion.span
                      layoutId="rail-active"
                      data-testid="rail-active-indicator"
                      aria-hidden="true"
                      transition={SPRING.snappy}
                      className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-aether-coral"
                    />
                  ) : null}
                  <i
                    className={`${item.icon} w-4 shrink-0 text-center text-[13px]`}
                    aria-hidden="true"
                  />
                  {collapsed ? (
                    <span className="sr-only">{item.label}</span>
                  ) : (
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  )}
                  {count !== null ? (
                    <span
                      data-testid={`rail-count-${item.href}`}
                      className={`type-mono-micro shrink-0 ${
                        collapsed
                          ? "absolute right-1 top-1 rounded bg-surface-3 px-1 text-[9px]"
                          : ""
                      } ${
                        item.href === "/dashboard/agents"
                          ? "text-state-ok"
                          : "text-aether-muted-dim"
                      }`}
                    >
                      {count.toLocaleString()}
                    </span>
                  ) : null}
                </Link>
              </div>
            );
          })}
        </nav>
      </LayoutGroup>

      <div className="mt-auto flex flex-col gap-2 pt-5">
        {/*
          MV-dashboard-006: no plan-tier or quota/usage indicator existed
          anywhere on the dashboard hub (topbar chip only showed name +
          target role) despite a real, populated quota system server-side
          (GET /billing/subscription) already surfaced honestly on the
          Settings page. This reads the same live endpoint — no fabricated
          numbers, no Math.random(); an unresolved/errored fetch shows an
          honest fallback, never an invented figure.
        */}
        <div
          className={`elev-2 rounded-xl p-3 ${collapsed ? "hidden" : ""}`}
          data-testid="sidebar-plan-quota"
        >
          {subscription === undefined ? (
            // M6: render calm skeleton bars while the plan loads instead of the
            // "Checking plan…" text, so the panel doesn't visibly flip copy.
            <div aria-hidden="true" data-testid="sidebar-plan-skeleton" className="space-y-2">
              <span className="block h-3 w-24 rounded bg-white/10 animate-pulse" />
              <span className="block h-2.5 w-32 rounded bg-white/10 animate-pulse" />
            </div>
          ) : subscription === null ? (
            <p className="type-meta">Plan unavailable</p>
          ) : subscription.entitlement?.unlimited === true ? (
            /*
              ADMIN-FULL / OWNER EXPERIENCE: an owner holds no plan and no
              quota — the server enforces neither — so rendering "Pro 98/100"
              here would be a number nothing can ever enforce. Say what is
              actually true instead, and offer no upgrade path.
            */
            <>
              <p className="text-xs font-medium" data-testid="sidebar-plan-name">
                Owner — unlimited
              </p>
              <p
                className="type-mono-micro mt-1 text-aether-muted-dim"
                data-testid="sidebar-plan-unlimited"
              >
                No plan, quota or spend cap
              </p>
            </>
          ) : (
            <>
              <p className="text-xs font-medium" data-testid="sidebar-plan-name">
                {subscription.plan?.name ?? "Free plan"}
              </p>
              {subscription.quota ? (
                <>
                  <p
                    className="type-mono-micro mt-1 text-aether-muted-dim"
                    data-testid="sidebar-plan-quota-runs"
                  >
                    {subscription.quota.runsUsed}/{subscription.quota.runsAllowed} runs this period
                  </p>
                  {quotaPercent !== null ? (
                    <div
                      className="mt-1.5 h-[2px] w-full overflow-hidden rounded-full bg-white/10"
                      role="img"
                      aria-label={`${quotaPercent}% of this period's runs used`}
                    >
                      <span
                        className="block h-full rounded-full bg-aether-coral"
                        style={{ width: `${quotaPercent}%` }}
                      />
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="type-meta mt-1">No usage quota on record</p>
              )}
            </>
          )}
        </div>

        <div className={`elev-1 rounded-xl p-3 ${collapsed ? "hidden" : ""}`}>
          <div className="mb-1.5 flex items-center gap-2">
            <span
              className={
                agentsActive
                  ? "h-1.5 w-1.5 rounded-full bg-state-ok pulse-ok"
                  : "h-1.5 w-1.5 rounded-full bg-state-neutral"
              }
              aria-hidden="true"
            />
            <span
              className={
                agentsActive
                  ? "text-[11px] font-medium text-state-ok"
                  : "text-[11px] font-medium text-aether-muted"
              }
            >
              {agentsActive ? "Agents Active" : stalled > 0 ? "Agents Stalled" : "Agents Idle"}
            </span>
          </div>
          <p className="type-meta">
            {pulse === undefined
              ? "Checking agent status…"
              : pulse === null
                ? "Agent status unavailable"
                : agentsActive
                  ? `${running} of ${pulse.total} agents running${
                      stalled > 0 ? ` · ${stalled} stalled` : ""
                    }`
                  : stalled > 0
                    ? // Honest: the run says "running" but has not moved for
                      // longer than any real run takes, so nothing is working.
                      `${stalled} stalled run${stalled === 1 ? "" : "s"} · none running`
                    : `${pulse.total} agents ready · none running`}
          </p>
          <Link
            href="/dashboard/agents"
            prefetch={false}
            className="mt-2.5 block w-full rounded-lg border border-hairline py-1.5 text-center text-[11px] font-medium transition-colors duration-[--dur-fast] hover:bg-surface-2"
          >
            Manage Agents
          </Link>
        </div>

        {/* §1.4 — the rail footer's system-status affordance. A reader over
            the one existing store; renders nothing when nothing subscribes. */}
        <div className={collapsed ? "hidden" : "px-1"}>
          <SystemStatus />
        </div>
      </div>

      <div
        className={`mt-3 flex flex-wrap gap-x-3 gap-y-1 px-2 text-[11px] text-aether-muted-dim ${
          collapsed ? "hidden" : ""
        }`}
      >
        <Link href="/privacy-policy" prefetch={false} className="transition hover:text-white">
          Privacy Policy
        </Link>
        <span>·</span>
        <Link href="/terms" prefetch={false} className="transition hover:text-white">
          Terms
        </Link>
        {supportEmail ? (
          <>
            <span>·</span>
            <a href={`mailto:${supportEmail}`} className="transition hover:text-white">
              Contact support
            </a>
          </>
        ) : null}
        <span>·</span>
        <span>© 2026 Aether</span>
      </div>
    </motion.aside>
  );
}

export default Rail;
