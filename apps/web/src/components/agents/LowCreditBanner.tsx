"use client";

/**
 * Low-OpenRouter-credit banner (ML-U1X-b, retired-U1 spec item (d): "surface
 * credits honestly"). Fed by `fetchOpenRouterCredits()` (GET
 * /agents/providers/openrouter/credits — operator-only, F-01), which itself
 * reads OpenRouter's own `GET /credits` and never fabricates a balance.
 *
 * Three honest states, no others:
 *  - hidden       — no reading yet, or a real reading that is NOT low.
 *  - low          — a real reading under the threshold: warn with the real
 *                    numbers.
 *  - unavailable  — the reading failed (no credential, upstream unreachable,
 *                    or this proxy call itself errored). Rendered explicitly
 *                    rather than silently hidden, because hidden would look
 *                    identical to "credit is healthy" — a claim this cannot
 *                    honestly make when the read failed.
 */
import { creditsBannerState, type CreditsReading } from "./logic";

export default function LowCreditBanner({
  credits,
}: {
  credits: CreditsReading | null;
}) {
  const state = creditsBannerState(credits);

  if (state.kind === "hidden") return null;

  if (state.kind === "unavailable") {
    return (
      <p
        data-testid="low-credit-banner"
        data-state="unavailable"
        role="status"
        className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm text-aether-muted-dim"
      >
        <i className="fa-solid fa-circle-question mr-1.5 text-[11px]" aria-hidden="true" />
        OpenRouter credit balance is currently unavailable — a run will still
        surface an honest error if it actually fails on insufficient credit.
      </p>
    );
  }

  return (
    <p
      data-testid="low-credit-banner"
      data-state="low"
      role="alert"
      className="rounded-xl border border-aether-amber/40 bg-aether-amber/10 p-3 text-sm text-aether-amber"
    >
      <i className="fa-solid fa-triangle-exclamation mr-1.5 text-[11px]" aria-hidden="true" />
      <span className="font-semibold">Low OpenRouter credit</span> — $
      {state.remaining.toFixed(2)}
      {state.total !== null ? ` of $${state.total.toFixed(2)}` : ""} remaining
      for the deployment. Add credit on OpenRouter, or bring your own key from
      one of the provider cards below.
    </p>
  );
}
