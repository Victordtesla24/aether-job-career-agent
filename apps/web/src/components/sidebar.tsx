"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchAgents } from "../lib/api/agents";
import { fetchSubscription, type SubscriptionState } from "../lib/api/billing";
import { NAV_ITEMS } from "../lib/navigation";

type AgentPulse = { running: number; total: number };

/**
 * Primary application sidebar. It renders straight from the NAV_ITEMS contract
 * (see src/lib/navigation.ts) so the ordering asserted by the navigation
 * contract test is exactly what ships. The active section is resolved from the
 * live pathname (prefix-based for nested routes); `activeHref` can override it
 * for tests/stories.
 */
export function Sidebar({ activeHref }: { activeHref?: string }) {
  const pathname = usePathname();
  const currentHref = activeHref ?? pathname ?? "/dashboard";
  // undefined = loading, null = unavailable, otherwise live counts
  const [pulse, setPulse] = useState<AgentPulse | null | undefined>(undefined);
  // MV-dashboard-006: no plan/quota indicator existed anywhere on the
  // dashboard hub despite a real, populated quota system server-side.
  // undefined = loading, null = fetch failed (honest fallback), otherwise
  // the real GET /billing/subscription state.
  const [subscription, setSubscription] = useState<SubscriptionState | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchAgents()
        .then((agents) => {
          if (cancelled) return;
          setPulse({
            running: agents.filter((a) => a.status === "running").length,
            total: agents.length,
          });
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

  const running = pulse?.running ?? 0;
  const agentsActive = running > 0;
  return (
    <aside className="w-[248px] shrink-0 border-r border-white/10 glass hidden lg:flex flex-col px-4 py-6">
      <div className="flex items-center gap-3 px-2 mb-8">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-aether-coral to-aether-amber flex items-center justify-center shadow-lg shadow-aether-coral/30">
          <i className="fa-solid fa-bolt text-white text-sm" />
        </div>
        <div>
          <div className="font-bold text-[15px] leading-none">Aether</div>
          <div className="text-[11px] text-aether-muted-dim mt-1">Career Agent</div>
        </div>
      </div>

      <nav aria-label="Primary" className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/dashboard"
              ? currentHref === "/dashboard"
              : currentHref === item.href || currentHref.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              prefetch={false}
              aria-current={isActive ? "page" : undefined}
              className={
                isActive
                  ? "flex items-center gap-3 px-3 py-2.5 rounded-xl bg-aether-coral/12 text-aether-coral border border-aether-coral/20 text-sm font-medium"
                  : "flex items-center gap-3 px-3 py-2.5 rounded-xl text-aether-muted hover:bg-white/5 hover:text-white transition text-sm"
              }
            >
              <i
                className={`${item.icon} w-4${isActive ? " text-aether-coral" : ""}`}
                aria-hidden="true"
              />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col gap-3">
        {/*
          MV-dashboard-006: no plan-tier or quota/usage indicator existed
          anywhere on the dashboard hub (topbar chip only showed name +
          target role) despite a real, populated quota system server-side
          (GET /billing/subscription) already surfaced honestly on the
          Settings page. This reads the same live endpoint — no fabricated
          numbers, no Math.random(); an unresolved/errored fetch shows an
          honest fallback, never an invented figure.
        */}
        <div className="glass-raised rounded-2xl border border-white/10 p-3" data-testid="sidebar-plan-quota">
          {subscription === undefined ? (
            <p className="text-[11px] text-aether-muted-dim">Checking plan…</p>
          ) : subscription === null ? (
            <p className="text-[11px] text-aether-muted-dim">Plan unavailable</p>
          ) : (
            <>
              <p className="text-xs font-medium" data-testid="sidebar-plan-name">
                {subscription.plan?.name ?? "Free plan"}
              </p>
              {subscription.quota ? (
                <p className="mono mt-1 text-[11px] text-aether-muted-dim" data-testid="sidebar-plan-quota-runs">
                  {subscription.quota.runsUsed}/{subscription.quota.runsAllowed} runs this period
                </p>
              ) : (
                <p className="mt-1 text-[11px] text-aether-muted-dim">No usage quota on record</p>
              )}
            </>
          )}
        </div>

        <div className="glass-raised rounded-2xl p-4 border border-white/10">
          <div className="flex items-center gap-2 mb-2">
            <span
              className={
                agentsActive
                  ? "w-2 h-2 rounded-full bg-aether-green live-dot"
                  : "w-2 h-2 rounded-full bg-aether-muted-dim"
              }
            />
            <span
              className={
                agentsActive
                  ? "text-xs font-medium text-aether-green"
                  : "text-xs font-medium text-aether-muted"
              }
            >
              {agentsActive ? "Agents Active" : "Agents Idle"}
            </span>
          </div>
          <p className="text-[11px] text-aether-muted-dim leading-relaxed">
            {pulse === undefined
              ? "Checking agent status…"
              : pulse === null
                ? "Agent status unavailable"
                : agentsActive
                  ? `${running} of ${pulse.total} agents running`
                  : `${pulse.total} agents ready · none running`}
          </p>
          <Link
            href="/dashboard/agents"
            prefetch={false}
            className="mt-3 block w-full text-center text-xs font-medium py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition"
          >
            Manage Agents
          </Link>
        </div>
      </div>

      <div className="mt-4 px-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-aether-muted-dim">
        <Link
          href="/privacy-policy"
          prefetch={false}
          className="hover:text-white transition"
        >
          Privacy Policy
        </Link>
        <span>·</span>
        <Link
          href="/terms"
          prefetch={false}
          className="hover:text-white transition"
        >
          Terms
        </Link>
        <span>·</span>
        <span>© 2026 Aether</span>
      </div>
    </aside>
  );
}
