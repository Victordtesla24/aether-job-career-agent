"use client";

/**
 * Before/after honesty for one tailored resume version — U-AX build spec
 * item 3 ("BEFORE/AFTER HONESTY"). Renders the overall ATS score before vs
 * after AND all 10 fit-radar dimensions (the EXISTING set —
 * `apps/api/app/routers/jobs.py::_build_insights` /
 * `dashboard/jobs/page.tsx` `Dimension[]`), with the >80% threshold marked
 * and every delta shown honestly — including negative or zero, never
 * clamped, never hidden.
 *
 * Pure presentational component: the caller supplies both score sets
 * (typically the baseline resume's insights vs the tailored version's
 * re-score against the same job) — this component computes and displays
 * deltas only, it never re-derives or fabricates a number of its own.
 */
export interface TailoringDimension {
  label: string;
  score: number;
  /** F-UAX-02: true when this measurement is a neutral placeholder (the
   *  semantic engine was untrusted for this run), not a genuine score. A
   *  degraded dimension renders as "—" (not measured) — never as a number,
   *  which would let a placeholder silently satisfy or trip the >80% floor. */
  degraded?: boolean;
}

export interface TailoringImpactProps {
  /** R-01: `null` means the half was NOT measured — the API withholds the
   *  number rather than flagging it (`GET /resumes/{id}/tailoring-impact`
   *  returns `ats: null` whenever `atsMeasured` is false), so this component
   *  cannot render a placeholder-contaminated score as a bold headline even by
   *  accident. `overall` is 0.4*keyword + 0.4*semantic + 0.2*experience, i.e.
   *  40% neutral placeholder when the semantic path is untrusted — the exact
   *  number that used to print as "Before 58 → After 61.4 (+3.4 ATS)" directly
   *  above a "Role Alignment — → — n/a" row derived from the same value. */
  beforeAts: number | null;
  afterAts: number | null;
  beforeDimensions: TailoringDimension[];
  afterDimensions: TailoringDimension[];
  /** Why an absent ATS number is absent. A bare "—" tells a paying subscriber
   *  nothing; this turns it into a statement. */
  atsUnmeasuredReason?: string | null;
}

const DIMENSION_THRESHOLD = 80;

/** `+1.2` / `-9` / `±0` — the sign is always explicit, a zero delta is never
 *  silently rendered as blank (that would read as "not measured"). */
function formatDelta(delta: number): string {
  const rounded = Math.round(delta * 10) / 10;
  if (rounded === 0) return "±0";
  return rounded > 0 ? `+${rounded}` : `${rounded}`;
}

function deltaTone(delta: number): string {
  if (delta > 0) return "text-aether-green";
  if (delta < 0) return "text-red-300";
  return "text-aether-muted-dim";
}

export default function TailoringImpact({
  beforeAts,
  afterAts,
  beforeDimensions,
  afterDimensions,
  atsUnmeasuredReason,
}: TailoringImpactProps) {
  // Same rule the dimension rows below already follow: a delta is only
  // meaningful when BOTH sides are measurements. One missing half yields
  // "n/a", never a subtraction against a placeholder.
  const atsDelta = beforeAts !== null && afterAts !== null ? afterAts - beforeAts : null;

  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="tailoring-impact"
    >
      <h3 className="text-sm font-semibold uppercase tracking-wide text-aether-muted-dim">
        Tailoring Impact — Before vs After
      </h3>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">Before (baseline)</p>
          <p
            className={`mono text-2xl font-bold ${beforeAts === null ? "text-aether-muted-dim" : ""}`}
            data-testid="ats-before"
          >
            {beforeAts === null ? "—" : beforeAts}
          </p>
        </div>
        <span className="text-aether-muted-dim">→</span>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">After (tailored)</p>
          <p
            className={`mono text-2xl font-bold ${
              afterAts === null ? "text-aether-muted-dim" : "text-aether-green"
            }`}
            data-testid="ats-after"
          >
            {afterAts === null ? "—" : afterAts}
          </p>
        </div>
        <span
          className={`mono ml-1 text-sm font-semibold ${
            atsDelta === null ? "text-aether-muted-dim" : deltaTone(atsDelta)
          }`}
          data-testid="ats-delta"
        >
          {atsDelta === null ? "n/a" : `${formatDelta(atsDelta)} ATS`}
        </span>
      </div>

      {beforeAts === null || afterAts === null ? (
        <p
          className="mt-2 text-xs text-aether-muted-dim"
          data-testid="ats-unmeasured-caveat"
        >
          Not measured
          {atsUnmeasuredReason ? ` — ${atsUnmeasuredReason}` : "."} We show a dash
          rather than a score that was never taken.
        </p>
      ) : null}

      <div className="mt-4" data-testid="dimension-threshold-line">
        <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">
          10-dimension fit score · baseline vs tailored · threshold {DIMENSION_THRESHOLD}%
        </p>
      </div>

      <div className="mt-2 space-y-1.5">
        {beforeDimensions.map((dim) => {
          // F-UAX-05: pair by LABEL, never by array index — an index pairing
          // silently mismatches two dimensions the moment either list is
          // reordered, filtered or grows, and previously fell back to
          // `dim.score` (a fabricated "±0, no change" the moment the arrays
          // ever misaligned). A genuinely missing counterpart now reads as
          // "not available", never as a manufactured zero delta.
          const after = afterDimensions.find((d) => d.label === dim.label);
          const beforeUnknown = dim.degraded === true;
          const afterUnknown = after == null || after.degraded === true;
          const known = !beforeUnknown && !afterUnknown;
          const delta = known ? after!.score - dim.score : null;
          return (
            <div
              key={dim.label}
              data-testid="dimension-row"
              className="grid grid-cols-[1fr,auto,auto,auto,auto] items-center gap-2 rounded-lg border border-white/10 p-2 text-xs"
            >
              <span className="truncate font-medium text-aether-muted">{dim.label}</span>
              <span className="mono text-aether-muted-dim" data-testid="dimension-before">
                {beforeUnknown ? "—" : dim.score}
              </span>
              <span className="text-aether-muted-dim">→</span>
              <span
                className={`mono font-semibold ${
                  afterUnknown
                    ? "text-aether-muted-dim"
                    : after!.score > DIMENSION_THRESHOLD
                      ? "text-aether-green"
                      : "text-aether-amber"
                }`}
                data-testid="dimension-after"
              >
                {afterUnknown ? "—" : after!.score}
              </span>
              <span
                className={`mono ${delta === null ? "text-aether-muted-dim" : deltaTone(delta)}`}
                data-testid="dimension-delta"
              >
                {delta === null ? "n/a" : formatDelta(delta)}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
