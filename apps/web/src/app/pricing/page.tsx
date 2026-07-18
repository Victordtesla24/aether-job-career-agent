"use client";

/**
 * /pricing — PUBLIC pricing page (GAP-P6-PRICING-001, H-025).
 *
 * Reads GET /api/billing/plans (public) and renders the four ratified tiers
 * (ADR-P6-PRICING) with GST-INCLUSIVE AUD prices. Every price carries a GST-line
 * breakdown via the shared MetricTooltip (net + embedded 10% GST) so the tax
 * treatment is honest and auditable; the frontend never computes tax itself —
 * the server pre-computes `round(total/11, 2)`. Subscribe posts to
 * /api/billing/checkout and redirects to the returned Stripe Checkout URL
 * (logged-out visitors are sent to /login by the shared client first).
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import MetricTooltip from "../../components/MetricTooltip";
import PublicFooter from "../../components/PublicFooter";
import { ApiError } from "../../lib/api/client";
import { fetchPlans, startCheckout, type Plan } from "../../lib/api/billing";

type Interval = "month" | "year";

function formatAud(amount: number): string {
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
  }).format(amount);
}

export default function PricingPage() {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [interval, setInterval] = useState<Interval>("month");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPlans()
      .then((res) => {
        if (!cancelled) setPlans(res.plans);
      })
      .catch(() => {
        if (!cancelled) setLoadError("Could not load pricing. Please try again shortly.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubscribe = useCallback(
    async (plan: Plan) => {
      setCheckoutError(null);
      setSubmitting(plan.id);
      try {
        const result = await startCheckout(plan.id, interval);
        window.location.href = result.checkoutUrl;
      } catch (err) {
        // A 401 already redirected the visitor to /login via the shared client.
        if (err instanceof ApiError && err.status === 401) return;
        if (err instanceof ApiError && err.status === 503) {
          setCheckoutError("Checkout isn't available yet — billing is still being set up.");
        } else {
          setCheckoutError("Could not start checkout. Please try again.");
        }
        setSubmitting(null);
      }
    },
    [interval],
  );

  return (
    <main className="min-h-screen bg-aether-bg px-4 py-16" data-testid="pricing-page">
      <div className="mx-auto max-w-6xl">
        <header className="mb-10 text-center">
          <div className="mb-4 flex items-center justify-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-aether-indigo to-aether-violet text-lg font-bold">
              A
            </div>
            <span className="text-xl font-semibold tracking-tight">Aether</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight">Simple, honest pricing</h1>
          <p className="mx-auto mt-3 max-w-xl text-sm text-aether-muted">
            All prices are in Australian dollars and GST-inclusive. Pick a plan and let
            Aether do the applying — cancel anytime.
          </p>

          <div
            className="mt-6 inline-flex items-center gap-1 rounded-xl border border-white/10 bg-white/5 p-1 text-sm"
            role="group"
            aria-label="Billing interval"
          >
            {(["month", "year"] as Interval[]).map((opt) => (
              <button
                key={opt}
                type="button"
                data-testid={`interval-${opt}`}
                aria-pressed={interval === opt}
                onClick={() => setInterval(opt)}
                className={`rounded-lg px-4 py-1.5 font-medium transition ${
                  interval === opt
                    ? "bg-gradient-to-r from-aether-indigo to-aether-violet text-white"
                    : "text-aether-muted hover:text-white"
                }`}
              >
                {opt === "month" ? "Monthly" : "Annual"}
                {opt === "year" ? (
                  <span className="ml-1.5 text-[11px] text-aether-green">save more</span>
                ) : null}
              </button>
            ))}
          </div>
        </header>

        {loadError ? (
          <p role="alert" data-testid="pricing-error" className="text-center text-sm text-aether-coral">
            {loadError}
          </p>
        ) : null}

        {checkoutError ? (
          <p role="alert" data-testid="checkout-error" className="mb-6 text-center text-sm text-aether-coral">
            {checkoutError}
          </p>
        ) : null}

        {plans === null && !loadError ? (
          <p data-testid="pricing-loading" className="text-center text-sm text-aether-muted">
            Loading plans…
          </p>
        ) : null}

        {plans ? (
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {plans.map((plan) => {
              const breakdown =
                interval === "year" && plan.annual ? plan.annual : plan.monthly;
              const perLabel =
                interval === "year" && plan.annual ? "/ year" : "/ month";
              const isFree = !plan.purchasable;
              return (
                <div
                  key={plan.id}
                  data-testid={`pricing-tier-${plan.id}`}
                  className="glass flex flex-col rounded-2xl border border-white/10 p-6"
                >
                  <h2 className="text-lg font-semibold">{plan.name}</h2>
                  <p className="mt-1 text-[11px] uppercase tracking-wide text-aether-muted-dim">
                    {plan.modelTier} model tier
                  </p>

                  <div className="mt-4 flex items-baseline gap-1">
                    <span
                      data-testid={`price-${plan.id}`}
                      className="text-3xl font-bold"
                    >
                      {formatAud(breakdown.total)}
                    </span>
                    {!isFree ? (
                      <span className="text-sm text-aether-muted">{perLabel}</span>
                    ) : null}
                  </div>

                  <div className="mt-2 text-[12px] text-aether-muted" data-testid={`gst-${plan.id}`}>
                    {breakdown.total > 0 ? (
                      <MetricTooltip
                        value={`Incl. ${formatAud(breakdown.gst)} GST`}
                        tooltip={`GST-inclusive price. Net ${formatAud(
                          breakdown.net,
                        )} + ${formatAud(
                          breakdown.gst,
                        )} GST (10%, computed as round(total ÷ 11, 2)).`}
                      />
                    ) : (
                      <span>No card required</span>
                    )}
                  </div>

                  <p className="mt-4 text-sm font-medium">
                    {plan.runsPerMonth} agent runs / month
                  </p>

                  <ul className="mt-3 flex flex-1 flex-col gap-2 text-[13px] text-aether-muted">
                    {plan.features.map((feature) => (
                      <li key={feature} className="flex items-start gap-2">
                        <i className="fa-solid fa-check mt-0.5 text-aether-green" aria-hidden="true" />
                        <span>{feature}</span>
                      </li>
                    ))}
                  </ul>

                  {isFree ? (
                    <Link
                      href="/signup"
                      data-testid={`subscribe-${plan.id}`}
                      className="mt-6 rounded-xl border border-white/15 py-2.5 text-center text-sm font-semibold transition hover:bg-white/5"
                    >
                      Get started free
                    </Link>
                  ) : (
                    <button
                      type="button"
                      data-testid={`subscribe-${plan.id}`}
                      onClick={() => handleSubscribe(plan)}
                      disabled={submitting === plan.id}
                      className="mt-6 rounded-xl bg-gradient-to-r from-aether-indigo to-aether-violet py-2.5 text-sm font-semibold transition hover:opacity-90 disabled:opacity-50"
                    >
                      {submitting === plan.id ? "Starting checkout…" : `Subscribe to ${plan.name}`}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ) : null}

        <p className="mt-10 text-center text-xs text-aether-muted-dim">
          Already have an account?{" "}
          <Link href="/login" className="text-aether-indigo hover:underline">
            Sign in
          </Link>
        </p>

        <PublicFooter />
      </div>
    </main>
  );
}
