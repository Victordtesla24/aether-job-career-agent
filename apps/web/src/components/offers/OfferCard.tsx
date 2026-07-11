/**
 * OfferCard — a single offer in the comparison grid (wireframe: offer-card-of07).
 * Company + badge row, big total comp, comp breakdown rows, fit-score footer.
 */
import { money, type UiOffer } from "./offers-lib";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-aether-muted">{label}</dt>
      <dd className="mono text-[#C7C7D6]">{value}</dd>
    </div>
  );
}

export function OfferCard({ offer }: { offer: UiOffer }) {
  const isTop = offer.topPick;
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
        {isTop ? (
          <span className="shrink-0 rounded bg-[#34D399]/15 px-2 py-0.5 text-[10px] font-semibold text-[#34D399]">
            Top pick
          </span>
        ) : offer.isNew ? (
          <span className="shrink-0 rounded bg-[#818CF8]/15 px-2 py-0.5 text-[10px] font-semibold text-[#818CF8]">
            New
          </span>
        ) : null}
      </div>

      <div className="mono mb-1 text-2xl font-bold">{money(offer.total)}</div>
      <div className="mb-4 text-[11px] text-aether-muted">Total comp / yr</div>

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
