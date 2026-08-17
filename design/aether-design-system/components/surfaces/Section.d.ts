import type { CSSProperties, ReactNode } from "react";

/**
 * The one content section wrapper on every workspace screen. The `footnote` slot
 * is load-bearing: sample-window and "not measured" disclosures live there at
 * readable size instead of being squeezed into a heading.
 *
 * @startingPoint section="Surfaces" subtitle="Section, selectable row and stat tile" viewport="700x340"
 */
export interface SectionProps {
  /** Gold uppercase overline. */
  eyebrow?: ReactNode;
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  /** Disclosure line rendered under the body with an info glyph. */
  footnote?: ReactNode;
  /** 1px gold gradient inset at the top — for a section that owns a status. */
  accent?: boolean;
  as?: "section" | "div" | "article";
  className?: string;
  style?: CSSProperties;
  bodyStyle?: CSSProperties;
  children?: ReactNode;
}

export function Section(props: SectionProps): JSX.Element;
