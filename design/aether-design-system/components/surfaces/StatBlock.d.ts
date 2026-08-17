import type { CSSProperties, ReactNode } from "react";

/**
 * The one KPI tile. Values render in the tabular data face; an unmeasured value
 * renders an em dash in `--state-neutral`, never a zero. `delta` is a live
 * signal only — omit it for ratios and means, where a row-count delta would
 * describe a different quantity than the one displayed.
 */
export interface StatBlockProps {
  label: string;
  /** Already-formatted value, or null for NOT MEASURED. */
  value?: ReactNode;
  /** Small raised unit: "%", "AUD", ".87". */
  unit?: string;
  /** Support line — denominator, basis, or the reason a value is unmeasured. */
  note?: ReactNode;
  /** Signed live delta chip. Null or 0 renders nothing. */
  delta?: number | null;
  /** Inline sparkline or meter. Must render real data or nothing. */
  visual?: ReactNode;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

export function StatBlock(props: StatBlockProps): JSX.Element;
