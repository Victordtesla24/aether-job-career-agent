"use client";

/**
 * The honest status of the shared realtime channel (W-RT, requirement 4).
 *
 * The point of this badge is the UNHAPPY path. A dashboard that silently keeps
 * rendering data from twenty minutes ago because its stream died is worse than
 * one with no stream at all: the user has no way to tell. So:
 *
 *  - "Live" is claimed ONLY when the server's own `hello` arrived on the
 *    current connection and the server has been heard from within the
 *    heartbeat window. The store enforces both.
 *  - Every other state names what is wrong AND when the data was last known
 *    current, and the `title` carries the server's verbatim reason.
 *  - Nothing here invents a reason. If the store has no detail, the badge says
 *    only what it knows.
 */

import { useEffect, useState } from "react";

import { useRealtimeStatus } from "../../hooks/useRealtime";

/** L4: how long after mount we hold back a transient degraded banner. Freshly
 * loaded data cannot meaningfully be "stale" yet, so a network hiccup during
 * the opening handshake shows as a calm "Connecting…" rather than an alarming
 * amber/red "may be stale" banner. A genuine server *refusal* (a real reason
 * like a stream cap or expired session) is exempt and always surfaces. */
const OFFLINE_GRACE_MS = 30_000;

function asOf(connectedAt: number | null): string {
  if (connectedAt === null) return "not yet loaded live";
  const when = new Date(connectedAt);
  return `as of ${when.toLocaleTimeString("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

export interface RealtimeStatusBadgeProps {
  className?: string;
  /** Drop the "(as of HH:MM)" suffix from the visible label — the `title` still
   * carries it in full. For tight surfaces like the top bar. */
  compact?: boolean;
  /** Render nothing when no screen on this page subscribes. There is genuinely
   * nothing to report in that case, and a permanent "idle" chip would just be
   * noise. */
  hideWhenIdle?: boolean;
}

export function RealtimeStatusBadge({
  className = "",
  compact = false,
  hideWhenIdle = false,
}: RealtimeStatusBadgeProps) {
  const state = useRealtimeStatus();

  // L4: within the first 30s after mount, hold back the transient degraded
  // banner so a slow/ flaky opening handshake does not greet the user with an
  // alarming "may be stale" message on freshly loaded data.
  const [graceElapsed, setGraceElapsed] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setGraceElapsed(true), OFFLINE_GRACE_MS);
    return () => clearTimeout(t);
  }, []);

  if (hideWhenIdle && state.status === "idle") return null;

  // Treat a degraded state as "still connecting" during the grace window when
  // we have never connected. A server *refusal* carries a real reason
  // (state.detail) and is exempt — it surfaces immediately, as ever.
  const isTransientDegraded =
    state.connectedAt === null &&
    (state.status === "reconnecting" || (state.status === "offline" && !state.detail));
  const effectiveStatus =
    !graceElapsed && isTransientDegraded ? "connecting" : state.status;

  let label: string;
  let tone: string;
  let title: string;
  const suffix = compact ? "" : ` (${asOf(state.connectedAt)})`;

  switch (effectiveStatus) {
    case "live":
      label = "Live";
      tone = "text-emerald-300/90 border-emerald-400/30 bg-emerald-400/10";
      title = "Live updates connected — this screen refreshes itself when your agents change something.";
      break;
    case "connecting":
      label = "Connecting…";
      tone = "text-aether-muted border-white/10 bg-white/5";
      title = "Opening the live update stream. Until it connects, this screen shows what it loaded.";
      break;
    case "reconnecting":
      label = `Reconnecting — may be stale${suffix}`;
      tone = "text-amber-300/90 border-amber-400/30 bg-amber-400/10";
      title = state.detail
        ? `Live updates dropped: ${state.detail} Retrying. What you see is ${asOf(state.connectedAt)} and may already be out of date.`
        : `Live updates dropped and are being retried. What you see is ${asOf(state.connectedAt)} and may already be out of date.`;
      break;
    case "offline":
      label = `Live updates offline — may be stale${suffix}`;
      tone = "text-red-300/90 border-red-400/30 bg-red-400/10";
      title = state.detail
        ? `${state.detail} What you see is ${asOf(state.connectedAt)} and may already be out of date — reload to refresh.`
        : `Live updates are not connected. What you see is ${asOf(state.connectedAt)} and may already be out of date — reload to refresh.`;
      break;
    default:
      label = "Live updates idle";
      tone = "text-aether-muted-dim border-white/10 bg-white/5";
      title = "No screen on this page subscribes to live updates.";
      break;
  }

  return (
    <span
      data-testid="realtime-status"
      data-status={state.status}
      title={title}
      aria-live="polite"
      className={`inline-flex max-w-full items-center gap-1.5 truncate rounded-full border px-2.5 py-1 text-[11px] font-medium ${tone} ${className}`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          state.status === "live" ? "bg-emerald-400" : "bg-current opacity-70"
        }`}
      />
      <span className="truncate">{label}</span>
    </span>
  );
}
