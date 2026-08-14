/**
 * U2c — the one below-quality-floor notice, shared by every Studio surface.
 *
 * The Resume Studio and the Cover Letter Studio both have to tell the user the
 * same thing about the same kind of verdict, so they render the same component
 * rather than two paraphrases that can drift apart. The approval modal keeps
 * its own layout (it also carries the acknowledgment control), but quotes the
 * SAME parsed verdict and the same per-dimension wording via
 * `lib/quality-gate.describeDimension`.
 *
 * Three honesty rules, all visible in the markup:
 *  - every failing dimension is named with its REAL score, straight from the
 *    stored verdict — never re-derived, never rounded up;
 *  - a dimension that could not be MEASURED says exactly that, instead of
 *    being shown as a 0% deficiency it never had;
 *  - the artifact is not withheld, and the copy says so. Below the floor is a
 *    labelled state, not a hidden failure and not a silent pass.
 */
import { type QualityGate, describeDimension } from "../../lib/quality-gate";

export function QualityFloorNotice({
  gate,
  testId = "quality-floor-notice",
}: {
  gate: QualityGate | null | undefined;
  testId?: string;
}) {
  if (!gate || gate.passed) return null;
  return (
    <div
      data-testid={testId}
      className="mt-3 rounded-xl border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100"
    >
      <p className="font-semibold">
        Below Aether&apos;s {gate.floor.toFixed(0)}% quality floor
      </p>
      <ul className="mt-2 space-y-1">
        {gate.failing.map((dimension) => (
          <li key={dimension.key}>{describeDimension(dimension)}</li>
        ))}
      </ul>
      <p className="mt-2 text-amber-200/80">
        These are the measured scores of the version that was actually stored.
        Nothing was inflated to reach the floor, and no claim your evidence does not
        support was added — a rewrite that tried was refused.
      </p>
    </div>
  );
}
