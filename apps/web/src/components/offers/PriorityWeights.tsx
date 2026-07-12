/**
 * PriorityWeights — read-only visualisation of the user's weighted decision
 * priorities (wireframe: weights-of11). Static colored proportional bars, one
 * per dimension, plus a running total badge.
 */
import { sumWeights, weightColor } from "./offers-lib";

export interface WeightRow {
  key: string;
  label: string;
  weight: number;
}

export function PriorityWeights({ weights }: { weights: WeightRow[] }) {
  const total = sumWeights(weights);
  const balanced = total === 100;
  return (
    <section className="glass rounded-2xl border border-white/10 p-5" data-testid="priority-weights">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <i className="fa-solid fa-sliders text-aether-coral" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Priority Weights</h2>
        </div>
        <span
          data-testid="weights-total"
          className={`mono text-xs ${balanced ? "text-[#34D399]" : "text-aether-amber"}`}
        >
          {total}%
        </span>
      </div>
      <div className="space-y-4 text-[13px]">
        {weights.map((w, i) => {
          const color = weightColor(i);
          const pct = Math.max(0, Math.min(100, w.weight));
          return (
            <div key={w.key} data-testid={`weight-row-${w.key}`}>
              <div className="mb-1 flex justify-between">
                <span className="text-aether-muted">{w.label}</span>
                <span className="mono" style={{ color }}>
                  {w.weight}%
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-white/10">
                <div
                  className="h-1.5 rounded-full"
                  style={{ width: `${pct}%`, backgroundColor: color }}
                  role="progressbar"
                  aria-label={`${w.label} priority weight`}
                  aria-valuenow={w.weight}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
            </div>
          );
        })}
      </div>
      {!balanced ? (
        <p className="mt-3 text-[11px] text-aether-amber">
          Weights sum to {total}% — rebalance toward 100% for an accurate ranking.
        </p>
      ) : null}
    </section>
  );
}
