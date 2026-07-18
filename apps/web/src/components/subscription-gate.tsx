"use client";

/**
 * Subscription wall for the /dashboard shell (GAP-P6-PAYWALL).
 *
 * Aether is a subscription-gated product (limited beta): an authenticated user
 * WITHOUT an active paid subscription cannot use the actionable dashboard. This
 * client gate fetches GET /billing/entitlement on mount and, when the gate is
 * enforced server-side (`requiresSubscription`) and the user is not `active_paid`,
 * renders a prominent "Subscribe to unlock Aether" paywall in place of the
 * children, with a clear route to /pricing.
 *
 * Two invariants this gate must honour (Cluster D):
 *
 * 1. FAIL CLOSED (MV-agent-monitor-004, security). If entitlement can't be
 *    verified (fetch error/timeout), the gate must NEVER reveal the gated
 *    dashboard — otherwise a free user forces the entitlement call to error and
 *    bypasses the paywall. On error we render a safe, honest error state (retry
 *    + routes to pricing / account management), never the children.
 *
 * 2. Account management is ALWAYS reachable (MV-pricing-003, MV-settings-003).
 *    A user — free or paid — must always be able to view their own plan/quota
 *    and reach "Manage subscription" to cancel. You cannot lock someone out of
 *    viewing or cancelling their own subscription, so the routes in
 *    GATE_EXEMPT_PREFIXES (settings/billing) bypass the paywall entirely. The
 *    broader "open the whole dashboard to free users" decision is escalated to
 *    the product owner (ADR-MV-02 D1 / H-4) and is deliberately NOT done here —
 *    genuinely gated agent features keep their paywall.
 *
 * The backend remains the true enforcement point — every actionable agent call
 * is hard-blocked with a 402 `subscription_required`, and the api-client routes
 * that 402 to /pricing.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { fetchEntitlement } from "../lib/api/billing";

type GateState = "loading" | "allowed" | "gated" | "error";

/**
 * Routes that must stay reachable for every authenticated user regardless of
 * subscription status — account/billing management, not metered agent features.
 * A user must always be able to see their plan/quota and cancel their sub.
 */
const GATE_EXEMPT_PREFIXES: readonly string[] = ["/dashboard/settings"];

/**
 * Every real dashboard section — one entry per `app/dashboard/<x>/page.tsx`.
 * A pathname that starts with none of these (and isn't the `/dashboard` root
 * itself) belongs to the `[...slug]` catch-all: it cannot be a genuine gated
 * feature, so it must never be masked by the paywall (MV-dashboard-001) — a
 * mistyped/stale-bookmark URL would then be visually indistinguishable from a
 * real paid-feature gate. Keep this list in sync with `app/dashboard/*`.
 */
const KNOWN_DASHBOARD_SECTIONS: readonly string[] = [
  "/dashboard/agents",
  "/dashboard/analytics",
  "/dashboard/applications",
  "/dashboard/approvals",
  "/dashboard/cover-letters",
  "/dashboard/email",
  "/dashboard/interviews",
  "/dashboard/jobs",
  "/dashboard/networking",
  "/dashboard/offers",
  "/dashboard/resume",
  "/dashboard/settings",
  "/dashboard/stories",
];

/** True when `pathname` maps to a real dashboard page (root or a known section). */
function isKnownDashboardRoute(pathname: string): boolean {
  if (pathname === "/dashboard") return true;
  return KNOWN_DASHBOARD_SECTIONS.some(
    (section) => pathname === section || pathname.startsWith(`${section}/`),
  );
}

/** True when `pathname` is an always-reachable account-management route, or an
 * unmapped `/dashboard/*` path that only the `[...slug]` catch-all can serve. */
export function isGateExempt(pathname: string | null): boolean {
  if (!pathname) return false;
  if (
    GATE_EXEMPT_PREFIXES.some(
      (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
    )
  ) {
    return true;
  }
  return pathname.startsWith("/dashboard/") && !isKnownDashboardRoute(pathname);
}

const VALUE_POINTS: readonly string[] = [
  "Autonomous job discovery across live sources, scored to your profile",
  "Resume tailoring + ATS optimization, with a fabrication guard",
  "Cover letters, STAR story bank, and an inbox agent — human-approved",
];

export function SubscriptionGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const exempt = isGateExempt(pathname);
  const [state, setState] = useState<GateState>("loading");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    // Account-management routes are always reachable — never gate them, and
    // don't bother fetching entitlement for them.
    if (exempt) return;
    let active = true;
    setState("loading");
    fetchEntitlement()
      .then((ent) => {
        if (!active) return;
        const gated = ent.requiresSubscription && !ent.active_paid;
        setState(gated ? "gated" : "allowed");
      })
      .catch(() => {
        // FAIL CLOSED: entitlement could not be verified — do NOT reveal the
        // gated dashboard. Show a safe, recoverable error state instead.
        if (active) setState("error");
      });
    return () => {
      active = false;
    };
  }, [exempt, reloadKey]);

  // Always-reachable account management (settings/billing): render as-is, even
  // for free/unsubscribed users and even when entitlement can't be fetched.
  if (exempt) {
    return <>{children}</>;
  }

  if (state === "loading") {
    return (
      <div
        data-testid="subscription-gate-loading"
        className="flex min-h-[60vh] items-center justify-center text-sm text-aether-muted"
      >
        Checking your subscription…
      </div>
    );
  }

  if (state === "gated") {
    return <Paywall />;
  }

  if (state === "error") {
    return <EntitlementError onRetry={() => setReloadKey((k) => k + 1)} />;
  }

  return <>{children}</>;
}

function Paywall() {
  return (
    <div
      data-testid="subscription-paywall"
      role="region"
      aria-label="Subscription required"
      className="flex min-h-[70vh] items-center justify-center px-4 py-10"
    >
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-aether-bg-elevated p-8 text-center shadow-2xl">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-aether-coral text-2xl font-bold">
          ✦
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-aether-text">
          Subscribe to unlock Aether
        </h1>
        <p className="mx-auto mt-3 max-w-md text-sm text-aether-muted">
          Aether is in limited beta. An active subscription is required to run
          the AI agents that power your job search — discovery, tailoring, cover
          letters, and the inbox agent.
        </p>

        <ul className="mx-auto mt-6 space-y-2 text-left text-sm text-aether-muted">
          {VALUE_POINTS.map((point) => (
            <li key={point} className="flex items-start gap-2">
              <span aria-hidden className="mt-0.5 text-aether-coral">
                ✓
              </span>
              <span>{point}</span>
            </li>
          ))}
        </ul>

        <Link
          href="/pricing"
          className="mt-8 inline-flex w-full items-center justify-center rounded-xl bg-aether-coral px-6 py-3 text-sm font-semibold transition hover:opacity-90"
        >
          View plans &amp; subscribe
        </Link>
        <p className="mt-4 text-xs text-aether-muted-dim">
          You can still browse{" "}
          <Link href="/pricing" className="text-aether-coral hover:underline">
            pricing
          </Link>{" "}
          and{" "}
          <Link
            href="/dashboard/settings"
            className="text-aether-coral hover:underline"
          >
            manage your account
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

/**
 * Safe fail-closed fallback (MV-agent-monitor-004): shown when entitlement can't
 * be verified. It does NOT reveal the gated dashboard, and — unlike the paywall
 * — it does not assert the user is unsubscribed (the failure may be a transient
 * blip for a paying user), so it offers a retry plus honest routes to pricing
 * and to always-reachable account management.
 */
function EntitlementError({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      data-testid="subscription-gate-error"
      role="alert"
      aria-label="Subscription check failed"
      className="flex min-h-[70vh] items-center justify-center px-4 py-10"
    >
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-aether-bg-elevated p-8 text-center shadow-2xl">
        <h1 className="text-xl font-bold tracking-tight text-aether-text">
          We could not verify your subscription
        </h1>
        <p className="mx-auto mt-3 max-w-md text-sm text-aether-muted">
          Something went wrong checking your plan, so we cannot load your
          dashboard right now. This is usually temporary — please try again.
        </p>
        <button
          type="button"
          data-testid="subscription-gate-retry"
          onClick={onRetry}
          className="mt-6 inline-flex w-full items-center justify-center rounded-xl bg-aether-coral px-6 py-3 text-sm font-semibold transition hover:opacity-90"
        >
          Try again
        </button>
        <p className="mt-4 text-xs text-aether-muted-dim">
          Still stuck? You can{" "}
          <Link href="/pricing" className="text-aether-coral hover:underline">
            view plans
          </Link>{" "}
          or{" "}
          <Link
            href="/dashboard/settings"
            className="text-aether-coral hover:underline"
          >
            manage your account
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
