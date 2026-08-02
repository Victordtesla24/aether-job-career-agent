/**
 * GMV4-ats-002 / ADR-GMV4-001 — STRUCTURAL guard against the degraded-ATS
 * defect class (ESC-002 mandate (b)).
 *
 * THE DEFECT CLASS. `ATSScore.semantic_similarity` — 40% of every ATS number
 * this product shows — is replaced by a neutral placeholder when neither the
 * local embedding model nor the HF Inference API is available
 * (`apps/api/app/services/ats_engine.py`, `_DEGRADED_SEMANTIC_SCORE`). The
 * API therefore ships the NUMBER and its PROVENANCE as sibling fields. Three
 * consecutive review rounds each found a consumer that read the number and
 * not the sibling, silently presenting a placeholder as a measurement.
 *
 * WHY A TYPE AND NOT A CONVENTION. Sibling fields (`score` + `degraded?`)
 * make the unguarded read the path of least resistance: it compiles, it
 * renders, nothing fails. The types below invert that. Each is a
 * DISCRIMINATED UNION whose untrustworthy arm simply DOES NOT HAVE the
 * numeric member, so `impact.tailoredATSScore` is a COMPILE ERROR until the
 * caller has narrowed on `.provenance` / `.measured`. `tsc --noEmit` is
 * already a required gate, so round 3's leak (`jobs/page.tsx:570`,
 * `out.conversionMetrics.tailoredATSScore` with no check) would have been a
 * build failure instead of a review finding.
 *
 * FAIL CLOSED AT THE BOUNDARY. The `Raw*` types are the honest shape of the
 * JSON. The only way to obtain a union value is a `*From()` normaliser here,
 * and each treats an unrecognised/absent flag as untrustworthy wherever the
 * wire is guaranteed to carry it.
 */

// ---------------------------------------------------------------------------
// ATS conversion impact — before / after / estimated lift from a tailor run
// ---------------------------------------------------------------------------

/**
 * Wire shape of `TailorRunResult.conversionMetrics`
 * (`apps/api/app/agents/tailor_agent.py::_compute_conversion_metrics`).
 * Never render these members directly — the type of every consumer-facing
 * field is deliberately `?`, so the only ergonomic path is
 * {@link conversionImpactFrom}.
 */
export interface RawConversionMetrics {
  baselineATSScore?: number;
  tailoredATSScore?: number;
  estimatedConversionLift?: string;
  methodology?: string;
  confidence?: string;
  requires_review?: boolean;
  baselineDegraded?: boolean;
  tailoredDegraded?: boolean;
  scoringDegraded?: boolean;
}

/**
 * How much we know about where the numbers came from.
 *
 * - `"measured"`   — every provenance flag was present and false: a genuine
 *                    embedding-backed measurement.
 * - `"degraded"`   — at least one flag was true: the number is 40% neutral
 *                    placeholder and MUST NOT be presented as a measurement.
 *
 * COLLAPSED TO TWO STATES (W-TAILOR-CONVERGE, 2026-08-02). A third
 * `"unattested"` arm used to exist for payloads carrying NO provenance fields
 * at all, and it CARRIED THE NUMBERS THROUGH — so a `conversionMetrics` blob
 * with no flags rendered "Before 60% → After 88%" as if measured, which is the
 * exact leak this module exists to prevent. It was kept only while five vitest
 * fixtures predated the provenance fields; those fixtures now all state their
 * provenance, so the arm is gone and an unattested payload FAILS CLOSED to
 * `"degraded"`, like every other unrecognised shape.
 */
export type ConversionProvenance = "measured" | "degraded";

/** Context that is equally true whether or not scoring was measured. */
interface ConversionContext {
  readonly methodology: string;
  readonly confidence: string;
  readonly requiresReview: boolean;
}

/**
 * Before/after/lift together with their provenance. The `"degraded"` arm has
 * NO numeric members, so a consumer cannot read one without first ruling that
 * arm out.
 */
export type ConversionImpact =
  | (ConversionContext & {
      readonly provenance: "measured";
      readonly baselineATSScore: number;
      readonly tailoredATSScore: number;
      readonly estimatedConversionLift: string;
    })
  | (ConversionContext & { readonly provenance: "degraded" });

export function conversionImpactFrom(
  raw: RawConversionMetrics | null | undefined,
): ConversionImpact | null {
  if (!raw) return null;
  const flags = [raw.scoringDegraded, raw.baselineDegraded, raw.tailoredDegraded];
  const attested = flags.some((f) => typeof f === "boolean");
  const allExplicitlyFalse = flags.every((f) => f === false);
  const { baselineATSScore, tailoredATSScore, estimatedConversionLift } = raw;
  // WHITELIST: "measured" needs every flag PRESENT and false. A partial flag
  // set, any true flag, an unrecognised shape, or a missing number all fall
  // through to "degraded" — never to "measured".
  const numbersPresent =
    typeof baselineATSScore === "number" &&
    typeof tailoredATSScore === "number" &&
    typeof estimatedConversionLift === "string";
  // "measured" requires every flag PRESENT and explicitly false. Everything
  // else — a partial flag set, any true flag, NO flags at all, a missing
  // number — is "degraded".
  const provenance: ConversionProvenance =
    numbersPresent && attested && allExplicitlyFalse ? "measured" : "degraded";
  const context: ConversionContext = {
    methodology: raw.methodology ?? "",
    confidence: raw.confidence ?? "",
    // ADR-GMV4-001: a degraded run can never be "reviewed enough".
    requiresReview: raw.requires_review === true || provenance === "degraded",
  };
  if (
    provenance === "degraded" ||
    typeof baselineATSScore !== "number" ||
    typeof tailoredATSScore !== "number" ||
    typeof estimatedConversionLift !== "string"
  ) {
    return { ...context, provenance: "degraded" };
  }
  return { ...context, provenance, baselineATSScore, tailoredATSScore, estimatedConversionLift };
}

// ---------------------------------------------------------------------------
// 10-dimensional fit — one radar/grid axis of GET /jobs/{id}/insights
// ---------------------------------------------------------------------------

/**
 * Wire shape of one `dimensions[]` entry. `degraded` is MANDATORY server-side
 * (`apps/api/app/routers/jobs.py::_dimension` takes it as a keyword-only
 * argument, so a new dimension cannot be added without stating its
 * provenance), which is what makes the fail-closed read below correct rather
 * than merely conservative.
 */
export interface RawFitDimension {
  label?: string;
  score?: number;
  degraded?: boolean;
}

/** One fit dimension. The untrustworthy arm carries no `score`. */
export type FitDimension =
  | { readonly label: string; readonly measured: true; readonly score: number }
  | { readonly label: string; readonly measured: false };

export function fitDimensionsFrom(
  raw: readonly RawFitDimension[] | null | undefined,
): FitDimension[] {
  if (!raw) return [];
  return raw.map((d) => {
    const label = typeof d.label === "string" ? d.label : "";
    // FAIL CLOSED: only an explicit `degraded: false` alongside a real number
    // counts as measured. Absent, `true`, or a non-number score all read as
    // not measured.
    if (d.degraded === false && typeof d.score === "number") {
      return { label, measured: true, score: d.score } as const;
    }
    return { label, measured: false } as const;
  });
}
