import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

export type NoticeTone = "info" | "ok" | "warn" | "danger" | "degraded" | "gold";

/**
 * The one inline message band — a widget that failed to load, a quota warning, a
 * quality-floor disclosure, a "no charge was made" confirmation. `degraded` is
 * reserved for an agent that produced nothing without failing; it is never
 * `danger` and never `ok`.
 *
 * @startingPoint section="Feedback" subtitle="Notice tones and metric disclosure" viewport="700x260"
 */
export interface InlineNoticeProps {
  tone?: NoticeTone;
  title?: ReactNode;
  /** Override the tone's default Font Awesome glyph. */
  icon?: string;
  onDismiss?: MouseEventHandler;
  role?: string;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

export function InlineNotice(props: InlineNoticeProps): JSX.Element;
