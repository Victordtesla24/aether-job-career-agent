"use client";

/**
 * Offers — side-by-side offer comparison, adjustable priority weights and a
 * negotiation coach. Backed by GET /offers (wireframe: offer-comparison.html).
 */
import { useEffect, useMemo, useState } from "react";

import { fetchOffers, type OffersPayload } from "../../../lib/api/workspaces";

const money = (n: number) => `$${Math.round(n / 1000)}k`;

export default function OffersPage() {
  const [data, setData] = useState<OffersPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [counterDraft, setCounterDraft] = useState(false);

  useEffect(() => {
    fetchOffers()
      .then((payload) => {
        setData(payload);
        setWeights(Object.fromEntries(payload.weights.map((w) => [w.key, w.weight])));
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load offers"));
  }, []);

  const totalWeight = useMemo(
    () => Object.values(weights).reduce((a, b) => a + b, 0),
    [weights],
  );

  if (error) {
    return <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>;
  }

  if (data === null) {
    return (
      <div className="grid gap-4 xl:grid-cols-3" aria-busy="true" data-testid="offers-skeleton">
        {[0, 1, 2].map((i) => (
          <div key={i} className="glass h-72 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </div>
    );
  }

  const isEmpty = data.offers.length === 0;

  return (
    <div className="space-y-6" data-testid="offer-comparison">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Offer Comparison</h1>
          <p className="text-sm text-aether-muted">
            Weighted against your priorities — the top pick updates as you tune the sliders.
          </p>
        </div>
        <button
          type="button"
          className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
        >
          + Add Offer
        </button>
      </header>

      {isEmpty ? (
        <div className="glass rounded-2xl border border-white/10 p-12 text-center" data-testid="offers-empty-state">
          <p className="text-lg font-semibold">No offers to compare</p>
          <p className="mt-1 text-sm text-aether-muted">
            When offers land they&apos;ll appear here, scored against your priority weights.
          </p>
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-3">
          {/* Offer cards */}
          <section className="grid gap-4 md:grid-cols-3 xl:col-span-2 xl:grid-cols-3" data-testid="offer-cards">
            {data.offers.map((o) => (
              <article
                key={o.id}
                data-testid="offer-card"
                className={`glass relative rounded-2xl border p-5 ${
                  o.topPick ? "border-aether-green/50" : "border-white/10"
                }`}
              >
                {o.topPick ? (
                  <span className="absolute -top-2.5 left-4 rounded-full bg-aether-green px-2.5 py-0.5 text-[10px] font-bold text-black">
                    TOP PICK
                  </span>
                ) : null}
                <div className="flex items-start justify-between">
                  <div>
                    <h2 className="font-semibold">{o.company}</h2>
                    <p className="text-xs text-aether-muted">{o.role}</p>
                  </div>
                  <span className="mono text-xs font-semibold text-aether-green">fit {o.fitScore}</span>
                </div>
                <p className="mono mt-3 text-2xl font-bold">{money(o.total)}</p>
                <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">total comp / yr</p>
                <dl className="mt-4 space-y-1.5 text-xs">
                  <Row label="Base" value={money(o.base)} />
                  <Row label="Bonus" value={money(o.bonus)} />
                  <Row label="Equity" value={money(o.equity)} />
                  <Row label="Location" value={o.location} />
                  <Row label="Decide by" value={new Date(o.deadline).toLocaleDateString()} />
                </dl>
              </article>
            ))}
          </section>

          {/* Right rail */}
          <div className="space-y-6">
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="priority-weights">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-[15px] font-semibold">Priority Weights</h2>
                <span className={`mono text-xs ${totalWeight === 100 ? "text-aether-green" : "text-aether-amber"}`}>
                  {totalWeight}%
                </span>
              </div>
              <div className="space-y-3">
                {data.weights.map((w) => (
                  <div key={w.key}>
                    <div className="mb-1 flex justify-between text-xs">
                      <span className="text-aether-muted">{w.label}</span>
                      <span className="mono">{weights[w.key] ?? w.weight}%</span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={50}
                      step={5}
                      value={weights[w.key] ?? w.weight}
                      data-testid={`weight-slider-${w.key}`}
                      onChange={(e) =>
                        setWeights((prev) => ({ ...prev, [w.key]: Number(e.target.value) }))
                      }
                      className="w-full accent-[#FF6B35]"
                      aria-label={`${w.label} weight`}
                    />
                  </div>
                ))}
              </div>
              {totalWeight !== 100 ? (
                <p className="mt-2 text-[11px] text-aether-amber">
                  Weights sum to {totalWeight}% — rebalance toward 100% for an accurate ranking.
                </p>
              ) : null}
            </section>

            <section className="glass rounded-2xl border border-aether-violet/30 p-5" data-testid="negotiation-coach">
              <h2 className="mb-3 text-[15px] font-semibold">
                <i className="fa-solid fa-chess-knight mr-2 text-aether-violet" aria-hidden="true" />
                Negotiation Coach
              </h2>
              <p className="text-xs text-aether-muted">{data.negotiation.insight}</p>
              <div className="mt-3 rounded-xl border border-aether-green/30 bg-aether-green/5 p-3">
                <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">Suggested counter (base)</p>
                <p className="mono text-xl font-bold text-aether-green">
                  ${data.negotiation.suggestedCounter.toLocaleString()}
                </p>
              </div>
              <p className="mt-3 text-[11px] uppercase tracking-wide text-aether-muted-dim">Your leverage</p>
              <ul className="mt-1.5 space-y-1.5">
                {data.negotiation.leverage.map((l) => (
                  <li key={l} className="flex items-start gap-2 text-xs text-aether-muted">
                    <i className="fa-solid fa-arrow-trend-up mt-0.5 text-aether-violet" aria-hidden="true" />
                    {l}
                  </li>
                ))}
              </ul>
              <button
                type="button"
                data-testid="draft-counter-btn"
                onClick={() => setCounterDraft((v) => !v)}
                className="mt-4 w-full rounded-lg bg-aether-violet px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                {counterDraft ? "Hide counter email" : "Draft counter email"}
              </button>
              {counterDraft ? (
                <p
                  data-testid="counter-email-draft"
                  className="mt-3 whitespace-pre-line rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-aether-muted"
                >
                  {`Hi Emma,\n\nThank you for the offer — I'm genuinely excited about the role and the team.\n\nBased on my competing offers and the market band for Senior TPMs in Sydney, I'd like to discuss a base of $${data.negotiation.suggestedCounter.toLocaleString()}. I'm confident the AI delivery experience I bring maps directly to the roadmap we discussed.\n\nHappy to jump on a call this week.\n\nBest,\nVikram`}
                </p>
              ) : null}
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-aether-muted-dim">{label}</dt>
      <dd className="mono">{value}</dd>
    </div>
  );
}
