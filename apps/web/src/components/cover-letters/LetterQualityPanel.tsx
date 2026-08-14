/**
 * Letter Quality panel (W-TAILOR-CONVERGE item 4/5).
 *
 * Renders the PERSISTED, deterministic quality score of the selected letter —
 * `Application.coverLetterQuality`, produced by
 * `apps/api/app/services/cover_letter_quality.py` and served on
 * `GET /cover-letters/{id}/insights`. Every number here is API-derived; nothing
 * is computed or estimated in the browser.
 *
 * Honesty rules this component must keep:
 *  - A letter with no stored score shows "not measured", NEVER a placeholder
 *    number. Letters generated before scoring existed are exactly that case.
 *  - `reachedTarget` comes from the API's strict `overall >= targetScore`; the
 *    UI never re-derives or rounds it.
 *  - Job-description keywords the candidate's evidence cannot support are
 *    labelled as such — they are not presented as a shortfall the user could
 *    fix by rewriting, because closing them would mean fabricating.
 */
import type { LetterInsights } from "./api";

type Quality = NonNullable<LetterInsights["quality"]>;

function Bar({ label, value }: { label: string; value: number }) {
  return (
    <div className="mt-2">
      <div className="flex items-center justify-between text-xs text-aether-muted">
        <span>{label}</span>
        <span className="mono text-white">{value}%</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-white/[0.07]">
        <div
          className="h-1.5 rounded-full bg-state-info"
          style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        />
      </div>
    </div>
  );
}

export function LetterQualityPanel({
  quality,
  loading,
}: {
  quality: Quality | null | undefined;
  loading: boolean;
}) {
  return (
    <section
      className="elev-1 rounded-2xl p-5"
      data-testid="letter-quality-panel"
    >
      <div className="mb-3 flex items-center gap-2">
        <i className="fa-solid fa-gauge-high text-sm text-state-info" aria-hidden="true" />
        <h2 className="text-[13px] font-semibold tracking-[-0.01em]">Letter Quality</h2>
      </div>

      {loading ? (
        <p className="text-xs text-aether-muted">Loading…</p>
      ) : !quality ? (
        <p className="text-xs text-aether-muted-dim" data-testid="letter-quality-not-measured">
          Not measured — this letter was generated before quality scoring existed, so no
          score was ever recorded for it. Regenerate the letter to get one.
        </p>
      ) : (
        <>
          <p className="text-sm text-aether-muted" data-testid="letter-quality-before-after">
            First draft:{" "}
            <span className="mono font-semibold text-white">{quality.initialScore}%</span> →
            Shipped:{" "}
            <span className="mono font-semibold text-state-ok">{quality.finalScore}%</span>
            <span className="ml-2 text-xs text-aether-muted-dim">
              ({quality.delta >= 0 ? "+" : ""}
              {quality.delta} pts)
            </span>
          </p>
          <p className="mt-1 text-xs" data-testid="letter-quality-target">
            {quality.reachedTarget ? (
              <span className="text-state-ok">
                Reached the {quality.targetScore}% quality target.
              </span>
            ) : (
              <span className="text-aether-amber">
                Below the {quality.targetScore}% target — this is the honest score of the
                letter that was actually stored, not a rounded one.
              </span>
            )}
          </p>

          <Bar
            label={
              quality.jdAlignmentMeasured
                ? "Job-description alignment"
                : "Job-description alignment (not measurable)"
            }
            value={quality.jdAlignmentMeasured ? quality.jdAlignment : 0}
          />
          <Bar label="Evidence grounding" value={quality.grounding} />
          <Bar label="Letter format" value={quality.structure} />

          {quality.missingKeywords.length > 0 ? (
            <div className="mt-3" data-testid="letter-quality-missing">
              <p className="text-xs text-aether-muted">
                Still missing (your evidence supports these — a rewrite can add them):
              </p>
              <p className="mt-1 text-xs text-white">{quality.missingKeywords.join(", ")}</p>
            </div>
          ) : null}

          {quality.unreachableKeywords.length > 0 ? (
            <div className="mt-3" data-testid="letter-quality-unreachable">
              <p className="text-xs text-aether-muted-dim">
                Excluded from the score — the posting asks for these and your résumé, story
                bank and career data prove none of them, so no truthful letter can claim
                them: {quality.unreachableKeywords.slice(0, 12).join(", ")}
                {quality.unreachableKeywords.length > 12
                  ? ` (+${quality.unreachableKeywords.length - 12} more)`
                  : ""}
                .
              </p>
            </div>
          ) : null}

          <p className="mt-3 text-[11px] leading-relaxed text-aether-muted-dim">
            {quality.methodology}
          </p>
        </>
      )}
    </section>
  );
}
