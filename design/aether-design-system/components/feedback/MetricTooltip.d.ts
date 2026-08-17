import type { CSSProperties, ReactNode } from "react";

/**
 * Wraps a number with the disclosure that states what it counts. This is where
 * Aether's honesty copy lives — every KPI, score and price uses it rather than
 * shrinking the caveat to 10px. The value keeps a dotted gold underline so the
 * affordance is visible without a hover.
 */
export interface MetricTooltipProps {
  value: ReactNode;
  tooltip: ReactNode;
  className?: string;
  style?: CSSProperties;
}

export function MetricTooltip(props: MetricTooltipProps): JSX.Element;
