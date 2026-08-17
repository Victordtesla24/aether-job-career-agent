import type { CSSProperties } from "react";

/**
 * The brand's ornamental rule, inherited from the AB Entertainment baseline:
 * a hairline, a 45°-rotated open diamond, a hairline. Use it under a section
 * heading on ceremonial surfaces (public site, empty states, offer screens) —
 * not inside dense data views, where a luminance step separates bands instead.
 */
export interface OrnamentDividerProps {
  /** Pixel width, or "full" to fill the container. */
  width?: number | "full";
  align?: "left" | "center" | "right";
  tone?: "gold" | "neutral";
  className?: string;
  style?: CSSProperties;
}

export function OrnamentDivider(props: OrnamentDividerProps): JSX.Element;
