import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

export type ButtonTone = "primary" | "outline" | "neutral" | "quiet" | "ok" | "danger" | "warn" | "info";
export type ButtonSize = "xs" | "sm" | "md" | "lg";

/**
 * The Aether call-to-action. Labels are ALL CAPS with wide tracking; the gold
 * gradient fill (`primary`) is the single loudest control allowed on a surface.
 * Approve/Reject pairs use `ok` + `danger` at the SAME size — approval is never
 * the cheaper click.
 *
 * @startingPoint section="Core" subtitle="Gold-fill, outline, quiet and state buttons" viewport="700x150"
 */
export interface ButtonProps {
  tone?: ButtonTone;
  size?: ButtonSize;
  /** Font Awesome 6 class, e.g. "fa-solid fa-bolt". */
  icon?: string;
  iconAfter?: string;
  block?: boolean;
  disabled?: boolean;
  /** Renders an anchor instead of a button. */
  href?: string;
  onClick?: MouseEventHandler;
  type?: "button" | "submit" | "reset";
  title?: string;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

export function Button(props: ButtonProps): JSX.Element;
