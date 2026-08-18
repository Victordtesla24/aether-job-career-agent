/**
 * Mount probe for ApplicationTimeline GL gating tests.
 * Lives outside the vi.mock factory so React hooks can be imported normally.
 */
import { useEffect } from "react";

export const glMounts = { count: 0, lastHover: null as string | null };

export function TimelineGlMountProbe(props: {
  hoverId?: string | null;
  hoverAppId?: string | null;
}) {
  useEffect(() => {
    glMounts.count += 1;
  }, []);
  glMounts.lastHover = props.hoverId ?? null;
  return (
    <div
      data-testid="timeline-gl-mock"
      data-hover={props.hoverId ?? ""}
      data-hover-app={props.hoverAppId ?? ""}
    />
  );
}
