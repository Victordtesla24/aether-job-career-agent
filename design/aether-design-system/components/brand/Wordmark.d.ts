import type { CSSProperties } from "react";

/**
 * The brand lockup — the product's own gold compass mark beside the name in the
 * display face. Use it in the rail header, on auth screens and in public-site
 * chrome. Never redraw or recolour the mark; pass `src` as the relative path to
 * `assets/aether-mark.png` from the consuming page.
 *
 * @startingPoint section="Brand" subtitle="Lockup and ornamental rule" viewport="700x180"
 */
export interface WordmarkProps {
  size?: "sm" | "md" | "lg";
  /** "full" = mark + name + tagline; "mark" = the mark alone. */
  variant?: "full" | "mark";
  /** Set to null/"" to drop the tagline line. */
  tagline?: string | null;
  src?: string;
  className?: string;
  style?: CSSProperties;
}

export function Wordmark(props: WordmarkProps): JSX.Element;
