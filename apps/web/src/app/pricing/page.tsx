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
 *
 * MV-pricing-002 (HIGH): the API still returns a per-plan `modelTier` field
 * and feature bullets like "Advanced model tier" / "Full model access" — but
 * no backend code path routes a subscriber's plan to a different LLM; every
 * agent call resolves its model from a fixed task-type tier, identical for
 * every plan. This page does not render the `modelTier` label or any
 * feature bullet that claims per-plan model differentiation, and states the
 * real differentiator (monthly run quota) plainly instead.
 *
 * PAY-R3-01/PAY-R3-03 fix — plan switching: an authenticated visitor who
 * already holds an active PAID subscription sees a "Current plan" badge on
 * their plan and "Switch to this plan" (not "Subscribe") on every other paid
 * tier. POST /billing/checkout now returns EITHER the usual
 * `{checkoutUrl}` (redirect to Stripe Checkout — a brand-new subscriber) OR
 * `{switched: true, planId, message}` when the backend switched the caller's
 * EXISTING Stripe subscription to the new plan server-side instead of
 * starting a second, independently-billing one. On `switched` we show
 * `message` in place of a redirect and re-fetch subscription state so the
 * badges/labels reflect the new plan immediately — no reload required.
 *
 * PAY-R3-05 — a Checkout Session that the shopper backed out of returns here
 * via `cancel_url=/pricing?checkout=cancel` (see stripe_gateway.py); we show
 * a dismissible "no charge was made" notice and strip the query param so a
 * refresh doesn't re-show it (same convention as the Gmail-connect callback
 * on /dashboard/email — read `window.location.search` directly, no
 * `useSearchParams`, so no Suspense boundary is required).
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import MetricTooltip from "../../components/MetricTooltip";
import PublicFooter from "../../components/PublicFooter";
import { ApiError, formatRetryAfter } from "../../lib/api/client";
import { formatAud } from "../../lib/format";
import {
  fetchPlans,
  fetchSubscription,
  isCheckoutSwitchedResult,
  startCheckout,
  type Plan,
  type SubscriptionState,
} from "../../lib/api/billing";

type Interval = "month" | "year";

const TOKEN_STORAGE_KEY = "aether_token";

// Matches feature copy that implies a plan-differentiated model/LLM quality
// (there is none — MV-pricing-002). Filtered from display; the honest
// differentiator (run quota) is stated separately in the page header.
const MODEL_TIER_CLAIM_RE = /model tier|model access/i;

// Subscription statuses the backend treats as "entitled paid" (mirrors
// SubscriptionRepository.has_active_paid_subscription in
// apps/api/app/repositories/billing.py) — the Free tier's own row is ALSO
// `status: "active"`, so status alone never implies a paid plan; `planId`
// must additionally be non-free.
const ENTITLED_STATUSES = new Set(["active", "trialing", "past_due"]);

export default function PricingPage() {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [interval, setInterval] = useState<Interval>("month");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<string | null>(null);
  // Session-aware Free CTA (MV-pricing-005): read the stored token directly —
  // never `getToken()`, which force-redirects an unauthenticated visitor to
  // /login and would break this public page.
  const [isAuthed, setIsAuthed] = useState(false);
  // PAY-R3-01/03: the caller's OWN subscription (undefined = not fetched yet,
  // null = fetch failed/inapplicable) — drives the "Current plan" badge and
  // the Subscribe -> "Switch to this plan" relabel for an existing paid
  // subscriber. Best-effort only: this page must still work for a logged-out
  // visitor or if this fetch fails, so a failure never blocks the page.
  const [mySubscription, setMySubscription] = useState<SubscriptionState | null | undefined>(
    undefined,
  );
  // PAY-R3-01: confirmation shown after POST /billing/checkout switches an
  // existing subscription in place instead of redirecting to Stripe.
  const [switchNotice, setSwitchNotice] = useState<string | null>(null);
  // PAY-R3-05: dismissible notice for a shopper who backed out of Checkout
  // (cancel_url=/pricing?checkout=cancel).
  const [cancelNotice, setCancelNotice] = useState(false);

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

  useEffect(() => {
    const authed = Boolean(window.localStorage.getItem(TOKEN_STORAGE_KEY));
    setIsAuthed(authed);
    if (!authed) {
      setMySubscription(null);
      return;
    }
    fetchSubscription()
      .then((s) => setMySubscription(s))
      .catch((err: unknown) => {
        // A 401 already redirected the visitor to /login via the shared
        // client. Any other failure (network hiccup) just means we cannot
        // show current-plan badges — the page still renders and Subscribe
        // still works, so degrade silently rather than blocking the page.
        if (err instanceof ApiError && err.status === 401) return;
        setMySubscription(null);
      });
  }, []);

  // PAY-R3-05: read ?checkout=cancel directly off the query string (no
  // useSearchParams -> no Suspense boundary needed), then strip it so a
  // refresh doesn't re-show the notice.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "cancel") {
      setCancelNotice(true);
      window.history.replaceState(null, "", "/pricing");
    }
  }, []);

  // The plan id of the caller's own PAID subscription, or null if they have
  // none (logged out, Free, or no subscription on record). Mirrors the
  // backend's own definition of "entitled paid" (SubscriptionRepository
  // .has_active_paid_subscription): status in (active, trialing, past_due)
  // AND planId != 'free' — the Free tier's own row is also `status: "active"`,
  // so `status === "active"` alone is NOT enough to mean "has a paid plan".
  const currentPaidPlanId =
    mySubscription?.plan &&
    mySubscription.plan.id !== "free" &&
    mySubscription.status !== null &&
    ENTITLED_STATUSES.has(mySubscription.status)
      ? mySubscription.plan.id
      : null;

  const handleSubscribe = useCallback(
    async (plan: Plan) => {
      setCheckoutError(null);
      setSwitchNotice(null);
      setSubmitting(plan.id);
      try {
        const result = await startCheckout(plan.id, interval);
        if (isCheckoutSwitchedResult(result)) {
          // PAY-R3-01: the backend switched the existing subscription's
          // price in place — no Stripe redirect. Refresh subscription state
          // so the "Current plan" badge moves to the new plan immediately.
          setSwitchNotice(result.message);
          setSubmitting(null);
          try {
            setMySubscription(await fetchSubscription());
          } catch {
            // Best-effort refresh only — the switch itself already
            // succeeded server-side; a stale badge until next load is not
            // worth surfacing as an error here.
          }
          return;
        }
        window.location.href = result.checkoutUrl;
      } catch (err) {
        // A 401 already redirected the visitor to /login via the shared client.
        if (err instanceof ApiError && err.status === 401) return;
        if (err instanceof ApiError && err.status === 503) {
          setCheckoutError("Checkout isn't available yet — billing is still being set up.");
        } else if (err instanceof ApiError && err.status === 400) {
          // MV-pricing-004: honest, distinct message — this plan has no Stripe
          // price configured yet, not a generic failure.
          setCheckoutError(
            "This plan isn't available for purchase yet (not yet configured for checkout). Please try a different plan or check back soon.",
          );
        } else if (err instanceof ApiError && err.status === 429) {
          // MV-pricing-004: respect Retry-After instead of a generic message.
          setCheckoutError(
            err.retryAfterSeconds !== undefined
              ? `Too many checkout attempts — please try again in about ${formatRetryAfter(err.retryAfterSeconds)}.`
              : "Too many checkout attempts — please wait a bit and try again.",
          );
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
          <p
            data-testid="pricing-model-honesty-note"
            className="mx-auto mt-2 max-w-xl text-xs text-aether-muted-dim"
          >
            Every plan uses the same AI models — plans differ by monthly agent-run
            quota and feature access, not model quality.
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

        {cancelNotice ? (
          <div
            role="status"
            data-testid="checkout-cancel-notice"
            className="mb-6 flex items-center justify-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-center text-sm text-aether-muted"
          >
            <span>Checkout canceled — you have not been charged.</span>
            <button
              type="button"
              aria-label="Dismiss"
              data-testid="checkout-cancel-notice-dismiss"
              onClick={() => setCancelNotice(false)}
              className="text-aether-muted-dim hover:text-white"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true" />
            </button>
          </div>
        ) : null}

        {switchNotice ? (
          <div
            role="status"
            data-testid="plan-switch-notice"
            className="mb-6 flex items-center justify-center gap-3 rounded-xl border border-aether-green/25 bg-aether-green/10 px-4 py-2.5 text-center text-sm text-aether-green"
          >
            <span>{switchNotice}</span>
            <button
              type="button"
              aria-label="Dismiss"
              data-testid="plan-switch-notice-dismiss"
              onClick={() => setSwitchNotice(null)}
              className="text-aether-green/70 hover:text-aether-green"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true" />
            </button>
          </div>
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
              // PAY-R3-01/03: this tile is the subscriber's own paid plan AT
              // THEIR CURRENT BILLING INTERVAL, or (for the Free tile) their
              // subscription record is on Free. Matching on plan id alone
              // would also disable a legitimate action — the backend's
              // switch-in-place path (POST /billing/checkout) supports
              // switching JUST the interval on the same plan (e.g. monthly
              // Pro -> annual Pro), so that combination must still show an
              // enabled "Switch to this plan", not a disabled "Current plan".
              const isCurrentPlan =
                (currentPaidPlanId === plan.id && mySubscription?.interval === interval) ||
                (isFree && currentPaidPlanId === null && mySubscription?.plan?.id === "free");
              return (
                <div
                  key={plan.id}
                  data-testid={`pricing-tier-${plan.id}`}
                  className={`glass flex flex-col rounded-2xl border p-6 ${
                    isCurrentPlan ? "border-aether-green/40" : "border-white/10"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="text-lg font-semibold">{plan.name}</h2>
                    {isCurrentPlan ? (
                      <span
                        data-testid={`current-plan-badge-${plan.id}`}
                        className="rounded-md border border-aether-green/25 bg-aether-green/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-aether-green"
                      >
                        Current plan
                      </span>
                    ) : null}
                  </div>

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
                    {plan.features
                      .filter((feature) => !MODEL_TIER_CLAIM_RE.test(feature))
                      .map((feature) => (
                        <li key={feature} className="flex items-start gap-2">
                          <i className="fa-solid fa-check mt-0.5 text-aether-green" aria-hidden="true" />
                          <span>{feature}</span>
                        </li>
                      ))}
                  </ul>

                  {isFree ? (
                    <Link
                      href={isAuthed ? "/dashboard" : "/signup"}
                      data-testid={`subscribe-${plan.id}`}
                      className="mt-6 rounded-xl border border-white/15 py-2.5 text-center text-sm font-semibold transition hover:bg-white/5"
                    >
                      {isAuthed ? "Go to dashboard" : "Get started free"}
                    </Link>
                  ) : isCurrentPlan ? (
                    <button
                      type="button"
                      data-testid={`subscribe-${plan.id}`}
                      disabled
                      className="mt-6 cursor-default rounded-xl border border-aether-green/25 bg-aether-green/10 py-2.5 text-sm font-semibold text-aether-green opacity-100"
                    >
                      Current plan
                    </button>
                  ) : (
                    <button
                      type="button"
                      data-testid={`subscribe-${plan.id}`}
                      onClick={() => handleSubscribe(plan)}
                      disabled={submitting === plan.id}
                      className="mt-6 rounded-xl bg-gradient-to-r from-aether-indigo to-aether-violet py-2.5 text-sm font-semibold transition hover:opacity-90 disabled:opacity-50"
                    >
                      {submitting === plan.id
                        ? "Starting checkout…"
                        : currentPaidPlanId !== null
                          ? "Switch to this plan"
                          : `Subscribe to ${plan.name}`}
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
