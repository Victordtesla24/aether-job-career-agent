import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

/**
 * The one row shell for a selectable list item — job results, applications,
 * approvals, contacts. Selected rows step up one elevation and gain a gold left
 * rail; they are never filled with a saturated wash.
 */
export interface ListCardProps {
  selected?: boolean;
  interactive?: boolean;
  onClick?: MouseEventHandler;
  as?: "div" | "li" | "article";
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

export function ListCard(props: ListCardProps): JSX.Element;
