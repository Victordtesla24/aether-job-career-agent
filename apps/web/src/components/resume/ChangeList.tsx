"use client";

/**
 * "What changed — and the evidence for every word."
 *
 * The change cards under the aha hero. Each card is ONE entry of
 * `GET /resumes/{id}/diff`, rendered with the SAME semantics the PDF renderer
 * uses (`components/resume/diff-semantics.ts` mirrors
 * `services/resume_pdf.py`), so the coral wash on screen marks exactly the
 * lines the renderer counts as reworded. The download itself is unmarked; the
 * same wash on the document is the Studio's "Preview highlights" (RFMT-2).
 *
 * Honesty rules encoded here:
 *  - A rewrite shows the baseline wording struck through ABOVE the tailored
 *    wording, so the user can see what was replaced rather than trusting a
 *    summary of it.
 *  - Within the tailored wording, only the words that are genuinely absent
 *    from the baseline sentence are marked. That is a claim provable from the
 *    two strings in hand — nothing stronger.
 *  - The evidence chip renders only when the change carries an `evidenceRef`.
 *    A change without one gets an explicit "no evidence reference recorded"
 *    note, never silence (silence would read as "traced").
 *  - Colour is never the only signal (C-5 / D-3): every changed line carries a
 *    visually-hidden "modified"/"added" prefix and a visible word label.
 */
import type { DiffChange } from "./diff-semantics";
import { segmentRewrite } from "./diff-semantics";
import { chip } from "../ui/recipes";

export interface ChangeListProps {
  changes: readonly DiffChange[];
  /** How many to render before the "show all" affordance. */
  limit?: number;
  onShowAll?: () => void;
  showingAll?: boolean;
}

export default function ChangeList({
  changes,
  limit = 5,
  onShowAll,
  showingAll = false,
}: ChangeListProps) {
  const visible = showingAll ? changes : changes.slice(0, limit);
  const hidden = changes.length - visible.length;

  return (
    <ul className="space-y-2.5" data-testid="change-list">
      {visible.map((change, i) => {
        const after = change.after ?? "";
        const isRewrite = Boolean(change.before) && Boolean(after);
        const segments = isRewrite ? segmentRewrite(change.before, after) : null;
        return (
          <li
            key={`${change.evidenceRef ?? "change"}-${i}`}
            data-testid="change-card"
            className="elev-1 rounded-xl border-hairline p-4"
          >
            <span className="sr-only">{isRewrite ? "modified" : "added"}: </span>
            {change.before ? (
              <p
                data-testid="change-before"
                className="text-[12.5px] leading-[1.6] text-aether-muted-dim line-through decoration-state-danger/45"
              >
                {change.before}
              </p>
            ) : null}
            {after ? (
              <p
                data-testid="change-after"
                className={`text-[13.5px] leading-[1.65] text-aether-text ${
                  change.before ? "mt-2" : ""
                } border-l-2 border-aether-coral/70 pl-3`}
              >
                {segments
                  ? segments.map((seg, s) =>
                      seg.added ? (
                        <mark
                          key={s}
                          data-testid="change-added-words"
                          className="rounded-[3px] bg-aether-coral/[0.18] px-[3px] text-aether-text"
                        >
                          {seg.text}
                        </mark>
                      ) : (
                        <span key={s}>{seg.text}</span>
                      ),
                    )
                  : after}
              </p>
            ) : null}
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <span className={chip({ tone: isRewrite ? "accent" : "ok" })}>
                {isRewrite ? "Rewritten" : "Added"}
              </span>
              {change.evidenceRef ? (
                <span className={chip({ tone: "info", mono: true })} data-testid="change-evidence">
                  <i className="fa-solid fa-link text-[9px]" aria-hidden="true" />
                  {change.evidenceRef}
                </span>
              ) : (
                <span className={chip({ tone: "neutral" })} data-testid="change-evidence-missing">
                  no evidence reference recorded
                </span>
              )}
            </div>
          </li>
        );
      })}
      {hidden > 0 && onShowAll ? (
        <li>
          <button
            type="button"
            data-testid="change-list-show-all"
            onClick={onShowAll}
            className="w-full rounded-xl border border-hairline px-4 py-2 text-xs font-semibold text-aether-muted transition-colors duration-[--dur-fast] hover:border-hairline-strong hover:text-aether-text"
          >
            Show all {changes.length} changes ({hidden} more)
          </button>
        </li>
      ) : null}
    </ul>
  );
}
