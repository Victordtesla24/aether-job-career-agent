/**
 * U2c — the 80%-across-all-dimensions quality verdict, as the browser reads it.
 *
 * ONE definition, shared by every surface that shows it: the approval modal,
 * the Resume Studio and the Cover Letter Studio. The verdict itself is computed
 * server-side (`apps/api/app/services/quality_gate.py`) and stamped onto the
 * artifact, the approval and the run; nothing here recomputes it. The browser's
 * only job is to render the numbers the run actually produced — a second
 * computation in the client would be a second opinion, and the whole point of
 * the gate is that there is one.
 *
 * `null` is a first-class answer. Artifacts produced before this gate existed
 * carry no verdict, and a surface must then say nothing rather than claim
 * either a pass or a failure that was never measured.
 */

/** One dimension of an artifact's verdict, exactly as the API stamped it. */
export interface QualityDimension {
  key: string;
  label: string;
  /** The REAL score, or null when the dimension could not be measured. */
  score: number | null;
  floor: number;
  measured: boolean;
  passed: boolean;
  unmeasuredReason: string | null;
}

export interface QualityGate {
  floor: number;
  passed: boolean;
  failing: QualityDimension[];
  failingLabels: string[];
  summary: string;
  acknowledgementLabel: string;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The default floor if a payload somehow omits it — matches the server's. */
const DEFAULT_FLOOR = 80;

/**
 * Parse a raw `qualityGate` object off any API payload, or `null` when there
 * is none (or it is not a verdict at all). Never invents a verdict.
 */
export function qualityGateFrom(raw: unknown): QualityGate | null {
  if (raw === null || typeof raw !== "object") return null;
  const gate = raw as Record<string, unknown>;
  if (typeof gate.passed !== "boolean") return null;
  const floor = asNumber(gate.floor) ?? DEFAULT_FLOOR;
  const failing = Array.isArray(gate.failing)
    ? (gate.failing as Record<string, unknown>[]).map((d) => ({
        key: String(d.key ?? ""),
        label: String(d.label ?? d.key ?? ""),
        score: asNumber(d.score),
        floor: asNumber(d.floor) ?? floor,
        measured: d.measured === true,
        passed: d.passed === true,
        unmeasuredReason:
          typeof d.unmeasuredReason === "string" ? d.unmeasuredReason : null,
      }))
    : [];
  return {
    floor,
    passed: gate.passed,
    failing,
    failingLabels: Array.isArray(gate.failingLabels)
      ? (gate.failingLabels as unknown[]).map(String)
      : failing.map((d) => d.label),
    summary: typeof gate.summary === "string" ? gate.summary : "",
    acknowledgementLabel:
      typeof gate.acknowledgementLabel === "string"
        ? gate.acknowledgementLabel
        : acknowledgementLabelFor(failing.length),
  };
}

/** The exact words the approve control carries for a below-floor artifact —
 *  kept identical to the server's `quality_gate.acknowledgement_label_for`. */
export function acknowledgementLabelFor(failingCount: number): string {
  const noun = failingCount === 1 ? "dimension" : "dimensions";
  return `Approve anyway — ${failingCount} ${noun} below floor`;
}

/**
 * One dimension rendered for a human: its REAL number, or an explicit
 * "not measured" — never a placeholder value dressed up as a measurement.
 */
export function describeDimension(dimension: QualityDimension): string {
  if (!dimension.measured || dimension.score === null) {
    const reason = dimension.unmeasuredReason ? ` — ${dimension.unmeasuredReason}` : "";
    return `${dimension.label}: not measured${reason}`;
  }
  return `${dimension.label}: ${dimension.score.toFixed(1)}% (floor ${dimension.floor.toFixed(0)}%)`;
}
