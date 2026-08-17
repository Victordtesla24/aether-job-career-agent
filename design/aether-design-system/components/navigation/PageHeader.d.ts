import type { CSSProperties, ReactNode } from "react";

/**
 * Every workspace screen opens with this header — no page hand-rolls an `h1`.
 * The title is the display face in caps; `ornament` adds the house
 * line–diamond–line rule beneath it for ceremonial screens.
 *
 * @startingPoint section="Navigation" subtitle="Page header with tabs and ornament" viewport="700x260"
 */
export interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  /** Row below the title — usually a SegmentedControl. */
  controls?: ReactNode;
  footnote?: ReactNode;
  ornament?: boolean;
  className?: string;
  style?: CSSProperties;
}

export function PageHeader(props: PageHeaderProps): JSX.Element;
