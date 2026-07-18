/**
 * EmptyState — shown when there are no offers to compare (wireframe:
 * empty-state-of15). Icon tile, heading, copy, Add-Offer CTA, and a tip.
 */
export function EmptyState({ onAddOffer }: { onAddOffer: () => void }) {
  return (
    <div data-testid="offers-empty-state">
      <div className="glass flex flex-col items-center rounded-2xl border border-dashed border-white/15 px-8 py-16 text-center">
        <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-aether-coral/25 bg-aether-coral/10">
          <i className="fa-solid fa-scale-balanced text-2xl text-aether-coral" aria-hidden="true" />
        </div>
        <h2 className="mb-1.5 text-lg font-bold">No offers to compare</h2>
        <p className="mb-6 max-w-md text-sm text-aether-muted">
          When you receive an offer, add it here to compare total compensation side by side
          — and get negotiation coaching anchored on your strongest offer.
        </p>
        <button
          type="button"
          data-testid="empty-add-offer"
          onClick={onAddOffer}
          className="flex min-h-[44px] items-center gap-2 rounded-xl bg-aether-coral px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90"
        >
          <i className="fa-solid fa-plus" aria-hidden="true" />
          Add Offer
        </button>
        <div className="mt-6 flex items-center gap-2 text-[11px] text-aether-muted-dim">
          <i className="fa-solid fa-lightbulb text-aether-yellow" aria-hidden="true" />
          Tip: Add at least two offers to compare them side by side and get counter-offer suggestions.
        </div>
      </div>
    </div>
  );
}
