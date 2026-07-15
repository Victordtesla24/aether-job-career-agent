/**
 * Dedicated cover-letter rejection panel (GAP-E4): replaces the generic
 * top-of-page alert when a generate/regenerate/refine call is rejected by the
 * fabrication guard or the §10.2 structural letter contract (HTTP 422 — see
 * ../../components/cover-letters/rejection.ts for the detail-parsing logic).
 */
import type { CoverLetterRejection } from "./rejection";

const GUARD_LABEL: Record<CoverLetterRejection["guard"], string> = {
  fabrication: "Fabrication guard",
  structural: "Letter format contract",
};

const GUARD_ICON: Record<CoverLetterRejection["guard"], string> = {
  fabrication: "fa-solid fa-shield-halved",
  structural: "fa-solid fa-ruler-combined",
};

export function RejectionPanel({
  rejection,
  onRegenerate,
  regenerating,
}: {
  rejection: CoverLetterRejection;
  onRegenerate: () => void;
  regenerating: boolean;
}) {
  return (
    <section
      role="alert"
      aria-live="assertive"
      data-testid="cover-letter-rejection-panel"
      data-guard={rejection.guard}
      className="glass rounded-2xl border border-aether-amber/30 bg-aether-amber/10 p-5"
    >
      <div className="flex items-center gap-2">
        <i className={`${GUARD_ICON[rejection.guard]} text-aether-amber`} aria-hidden="true" />
        <span
          data-testid="cover-letter-rejection-guard"
          className="rounded-md border border-aether-amber/30 bg-aether-amber/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-aether-amber"
        >
          {GUARD_LABEL[rejection.guard]}
        </span>
      </div>
      <h3 className="mt-2 text-sm font-semibold text-aether-text">{rejection.title}</h3>

      <p className="mt-2 text-xs font-medium text-aether-muted">{rejection.itemsLabel}</p>
      <ul
        className="mt-1.5 list-disc space-y-1 pl-5 text-xs text-aether-muted"
        data-testid="cover-letter-rejection-items"
      >
        {rejection.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>

      <p className="mt-3 text-xs font-medium text-aether-muted">How to fix it</p>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-xs text-aether-muted">
        {rejection.remediation.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ul>

      <button
        type="button"
        data-testid="cover-letter-rejection-regenerate-btn"
        onClick={onRegenerate}
        disabled={regenerating}
        className="mt-4 min-h-[44px] rounded-xl bg-aether-amber/20 px-4 py-2 text-sm font-semibold text-aether-amber transition hover:bg-aether-amber/30 disabled:opacity-50"
      >
        {regenerating ? "Regenerating…" : "Regenerate"}
      </button>
    </section>
  );
}
