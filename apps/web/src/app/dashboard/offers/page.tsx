"use client";

/**
 * Offer Comparison — side-by-side offer cards and a negotiation coach (wireframe:
 * design/screens/offer-comparison.html). Backed by the live authenticated API:
 * GET /workspaces/offers via fetchOffers(); Add/Remove persist via
 * createOffer()/deleteOffer() so offers survive reloads (MV-offer-comparison-001).
 */
import { useCallback, useEffect, useState } from "react";

import { AddOfferModal } from "../../../components/offers/AddOfferModal";
import { EmptyState } from "../../../components/offers/EmptyState";
import { NegotiationCoach } from "../../../components/offers/NegotiationCoach";
import { OfferCard } from "../../../components/offers/OfferCard";
import {
  createOffer,
  deleteOffer,
  fetchOffers,
  type OfferCreateInput,
  type OffersPayload,
} from "../../../lib/api/workspaces";

export default function OffersPage() {
  const [data, setData] = useState<OffersPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const load = useCallback(async () => {
    const payload = await fetchOffers();
    setData(payload);
    return payload;
  }, []);

  useEffect(() => {
    load().catch((e: unknown) =>
      setError(e instanceof Error ? e.message : "Failed to load offers"),
    );
  }, [load]);

  // Persist the offer, then refetch so the grid AND the recomputed negotiation
  // coach reflect the real backend state. Errors propagate to the modal, which
  // keeps the draft and shows an inline message (no fake success).
  const handleAdd = useCallback(
    async (input: OfferCreateInput) => {
      await createOffer(input);
      await load();
    },
    [load],
  );

  const handleDelete = useCallback(
    async (offerId: string) => {
      await deleteOffer(offerId);
      await load();
    },
    [load],
  );

  if (error) {
    return (
      <p
        role="alert"
        data-testid="offers-error"
        className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
      >
        {error}
      </p>
    );
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

  const offers = data.offers;
  const isEmpty = offers.length === 0;

  return (
    <div className="space-y-6" data-testid="offer-comparison">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-[13px] text-aether-muted">
            <i className="fa-solid fa-scale-balanced text-aether-coral" aria-hidden="true" />
            Offers
          </div>
          <h1 className="text-2xl font-bold">Offer Comparison</h1>
          <p className="mt-1 text-sm text-aether-muted">
            Compare your live offers side by side.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="add-offer"
            onClick={() => setModalOpen(true)}
            className="flex min-h-[44px] items-center gap-2 rounded-xl bg-aether-coral px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90"
          >
            <i className="fa-solid fa-plus" aria-hidden="true" />
            Add Offer
          </button>
        </div>
      </header>

      {isEmpty ? (
        <EmptyState
          onAddOffer={() => {
            setModalOpen(true);
          }}
        />
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-3">
          <section
            data-testid="offer-cards"
            className="grid min-w-0 gap-4 sm:grid-cols-2 xl:col-span-2 xl:grid-cols-3"
          >
            {offers.map((o) => (
              <OfferCard
                key={o.id}
                offer={o}
                onDelete={o.source === "manual" ? handleDelete : undefined}
              />
            ))}
          </section>

          <div className="min-w-0 space-y-5">
            <NegotiationCoach negotiation={data.negotiation} />
          </div>
        </div>
      )}

      <AddOfferModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onAdd={handleAdd}
      />
    </div>
  );
}
