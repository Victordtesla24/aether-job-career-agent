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
 * The backend is the true enforcement point — every actionable agent call is
 * hard-blocked with a 402 `subscription_required`. So if entitlement can't be
 * fetched (a transient error), this gate FAILS OPEN (renders children) rather
 * than locking out a paying user: the backend 402 still walls every action and
 * the api-client routes that 402 to /pricing.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchEntitlement } from "../lib/api/billing";

type GateState = "loading" | "allowed" | "gated";

const VALUE_POINTS: readonly string[] = [
  "Autonomous job discovery across live sources, scored to your profile",
  "Resume tailoring + ATS optimization, with a fabrication guard",
  "Cover letters, STAR story bank, and an inbox agent — human-approved",
];

export function SubscriptionGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<GateState>("loading");

  useEffect(() => {
    let active = true;
    fetchEntitlement()
      .then((ent) => {
        if (!active) return;
        const gated = ent.requiresSubscription && !ent.active_paid;
        setState(gated ? "gated" : "allowed");
      })
      .catch(() => {
        // Fail open — the backend 402 still blocks every action (see docstring).
        if (active) setState("allowed");
      });
    return () => {
      active = false;
    };
  }, []);

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
          and manage your account.
        </p>
      </div>
    </div>
  );
}
