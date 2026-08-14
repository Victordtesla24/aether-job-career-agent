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
}

export interface TailoringImpactProps {
  beforeAts: number;
  afterAts: number;
  beforeDimensions: TailoringDimension[];
  afterDimensions: TailoringDimension[];
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
}: TailoringImpactProps) {
  const atsDelta = afterAts - beforeAts;

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
          <p className="mono text-2xl font-bold" data-testid="ats-before">
            {beforeAts}
          </p>
        </div>
        <span className="text-aether-muted-dim">→</span>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">After (tailored)</p>
          <p className="mono text-2xl font-bold text-aether-green" data-testid="ats-after">
            {afterAts}
          </p>
        </div>
        <span className={`mono ml-1 text-sm font-semibold ${deltaTone(atsDelta)}`}>
          {formatDelta(atsDelta)} ATS
        </span>
      </div>

      <div className="mt-4" data-testid="dimension-threshold-line">
        <p className="text-[10px] uppercase tracking-wide text-aether-muted-dim">
          10-dimension fit score · baseline vs tailored · threshold {DIMENSION_THRESHOLD}%
        </p>
      </div>

      <div className="mt-2 space-y-1.5">
        {beforeDimensions.map((dim, i) => {
          const after = afterDimensions[i];
          const afterScore = after?.score ?? dim.score;
          const delta = afterScore - dim.score;
          return (
            <div
              key={dim.label}
              data-testid="dimension-row"
              className="grid grid-cols-[1fr,auto,auto,auto,auto] items-center gap-2 rounded-lg border border-white/10 p-2 text-xs"
            >
              <span className="truncate font-medium text-aether-muted">{dim.label}</span>
              <span className="mono text-aether-muted-dim">{dim.score}</span>
              <span className="text-aether-muted-dim">→</span>
              <span
                className={`mono font-semibold ${
                  afterScore > DIMENSION_THRESHOLD ? "text-aether-green" : "text-aether-amber"
                }`}
              >
                {afterScore}
              </span>
              <span className={`mono ${deltaTone(delta)}`}>{formatDelta(delta)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
