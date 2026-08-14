/**
 * THE FIVE HONEST-RENDERING LAWS (S-UI-REBUILD-SPEC §4.2), enforced
 * mechanically rather than by review.
 *
 *   C-1  Zero is not a colour          → `geometry.ts` (markKind / barLength)
 *   C-2  Unmeasured is not zero        → assertNullMeaning (dev-throw)
 *   C-3  The window is part of the chart → assertWindowLabel (dev-throw)
 *   C-4  Scale is declared             → assertScaleDeclared (dev-throw)
 *   C-5  Colour is redundant           → assertColourRedundancy (dev-throw)
 *
 * Enforcement is loud in every environment. In development and in tests a
 * violation THROWS, so it cannot be merged. In production it is reported via
 * `console.error` instead: a chart that mislabels itself is a serious bug, but
 * white-screening a paying user's dashboard over it would be a worse one — and
 * a silent skip would be worse still.
 */
import type { ChartDatum, ScaleDeclaration } from "./types";

export type ChartLaw = "C-1" | "C-2" | "C-3" | "C-4" | "C-5";

export class ChartLawError extends Error {
  readonly law: ChartLaw;

  constructor(law: ChartLaw, message: string) {
    super(`[chart ${law}] ${message}`);
    this.name = "ChartLawError";
    this.law = law;
  }
}

function isProduction(): boolean {
  return process.env.NODE_ENV === "production";
}

/** Throw in dev/test, report in production. Never silent. */
export function reportLawViolation(law: ChartLaw, message: string): void {
  const error = new ChartLawError(law, message);
  if (isProduction()) {
    console.error(error.message, { law });
    return;
  }
  throw error;
}

/** C-3 — every chart states its sample window. */
export function assertWindowLabel(windowLabel: string | undefined): void {
  if (typeof windowLabel !== "string" || windowLabel.trim() === "") {
    reportLawViolation(
      "C-3",
      "a chart must state its sample window (windowLabel), e.g. \"last 50 runs\" or " +
        '"all time — not affected by the period selector"',
    );
  }
}

/** C-4 — log scales and truncated axes announce themselves. */
export function assertScaleDeclared(scale: ScaleDeclaration | undefined): void {
  if (!scale || typeof scale.kind !== "string") {
    reportLawViolation("C-4", "a chart must declare its scale: linear | log | share-of-previous");
    return;
  }
  if (scale.kind !== "linear" && scale.kind !== "log" && scale.kind !== "share-of-previous") {
    reportLawViolation("C-4", `unknown scale kind "${String(scale.kind)}"`);
    return;
  }
  const baseline = scale.baseline ?? 0;
  if (baseline !== 0 && scale.truncated !== true) {
    reportLawViolation(
      "C-4",
      `the value axis starts at ${baseline}, not 0 — set truncated: true so the break is drawn`,
    );
  }
}

/** C-2 — a series that mixes real zeroes with unmeasured values must say what
 *  the unmeasured ones mean, so the two can never read as the same thing. */
export function assertNullMeaning(
  data: readonly ChartDatum[],
  nullMeaning: string | undefined,
): void {
  const hasZero = data.some((d) => d.value === 0);
  const hasNull = data.some((d) => d.value === null || d.value === undefined);
  if (!hasZero || !hasNull) return;
  // The PROP is what the law requires, not a per-datum note: `nullMeaning` is
  // what appears on the chart's face ("— = …"), where a reader meets the two
  // marks side by side. A note buried in the data table explains one row after
  // the fact; it cannot stop 0 and — from reading as the same thing on sight.
  const explained = typeof nullMeaning === "string" && nullMeaning.trim() !== "";
  if (!explained) {
    reportLawViolation(
      "C-2",
      "this series contains both 0 and null. Pass nullMeaning (or a per-datum note) " +
        "so a reader can tell a measured zero from a value that was never measured",
    );
  }
}

/** C-5 — every tone pairs with a word. A datum with no label is a colour with
 *  no meaning. */
export function assertColourRedundancy(data: readonly ChartDatum[]): void {
  const blank = data.find((d) => typeof d.label !== "string" || d.label.trim() === "");
  if (blank) {
    reportLawViolation(
      "C-5",
      "every datum needs a label — colour alone may never carry a meaning (colour-blind + a11y)",
    );
  }
}

export interface ChartLawInput {
  windowLabel: string;
  scale: ScaleDeclaration;
  data: readonly ChartDatum[];
  nullMeaning?: string;
}

/** All four render-time laws in the order a reader meets them. C-1 is
 *  structural and lives in `geometry.ts`. */
export function assertChartLaws({
  windowLabel,
  scale,
  data,
  nullMeaning,
}: ChartLawInput): void {
  assertWindowLabel(windowLabel);
  assertScaleDeclared(scale);
  assertColourRedundancy(data);
  assertNullMeaning(data, nullMeaning);
}
