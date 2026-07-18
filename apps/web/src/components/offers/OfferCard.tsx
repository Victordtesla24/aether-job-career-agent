/**
 * OfferCard — a single offer in the comparison grid (wireframe: offer-card-of07).
 * Company + badge row, big total comp, comp breakdown rows, fit-score footer.
 *
 * MV-offer-comparison-006: the currency code (offer.currency) is shown alongside
 * the total so the figures are never ambiguous "$" amounts.
 * MV-offer-comparison-005: manually-added offers (onDelete provided) expose a
 * remove control so a mistyped, now-persisted offer can be corrected.
 */
import { useState } from "react";

import { money } from "./offers-lib";
import type { Offer } from "../../lib/api/workspaces";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-aether-muted">{label}</dt>
      <dd className="mono text-[#C7C7D6]">{value}</dd>
    </div>
  );
}

export function OfferCard({
  offer,
  onDelete,
}: {
  offer: Offer;
  onDelete?: (offerId: string) => void | Promise<void>;
}) {
  const isTop = offer.topPick;
  const [busy, setBusy] = useState(false);

  const handleDelete = async () => {
    if (!onDelete || busy) return;
    setBusy(true);
    try {
      await onDelete(offer.id);
    } catch {
      // Delete failed — keep the card and let the user retry.
      setBusy(false);
    }
  };

  return (
    <article
      data-testid="offer-card"
      data-company={offer.company}
      className={`glass-raised min-w-0 rounded-2xl border-t-2 p-5 ${
        isTop ? "border-t-[#34D399]" : "border-t-white/10"
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold">{offer.company}</span>
        <div className="flex shrink-0 items-center gap-2">
          {isTop ? (
            <span className="rounded bg-[#34D399]/15 px-2 py-0.5 text-[10px] font-semibold text-[#34D399]">
              Top pick
            </span>
          ) : null}
          {onDelete ? (
            <button
              type="button"
              data-testid="offer-delete"
              aria-label={`Remove ${offer.company} offer`}
              onClick={handleDelete}
              disabled={busy}
              className="flex h-6 w-6 items-center justify-center rounded text-aether-muted-dim transition hover:text-red-400 disabled:opacity-50"
            >
              <i className="fa-solid fa-trash-can text-xs" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </div>

      <div className="mono mb-1 text-2xl font-bold">{money(offer.total)}</div>
      <div className="mb-4 text-[11px] text-aether-muted">Total comp / yr · {offer.currency}</div>

      <dl className="space-y-2 text-[12px]">
        <Row label="Base" value={money(offer.base)} />
        <Row label="Bonus" value={money(offer.bonus)} />
        <Row label="Equity" value={money(offer.equity)} />
        <div className="flex justify-between">
          <dt className="text-aether-muted">Location</dt>
          <dd className="truncate pl-2 text-right text-[#C7C7D6]">{offer.location}</dd>
        </div>
      </dl>

      <div className="mt-4 flex items-center justify-between border-t border-white/10 pt-3">
        <span className="text-[11px] text-aether-muted">Fit score</span>
        {offer.fitScore === null ? (
          <span className="text-[11px] text-aether-muted-dim" title="Pending agent analysis">
            Pending
          </span>
        ) : (
          <span
            className={`mono text-lg font-bold ${isTop ? "text-[#34D399]" : "text-white"}`}
          >
            {offer.fitScore}
          </span>
        )}
      </div>
    </article>
  );
}
