"use client";

/**
 * A ticking clock for state that becomes untrue with the passage of time.
 *
 * The realtime channel (`hooks/useRealtime`) covers everything that changes
 * because the SERVER changed something. A run going stale is different: no row
 * moves, no event is emitted — the run simply stops being plausible as the
 * seconds pass. Without a tick, a screen opened while a run was still inside
 * its staleness window would keep showing "in progress" forever, which is the
 * exact failure this whole change exists to remove.
 *
 * So this is not a poll: it fires no requests and fetches nothing. It only
 * re-renders so that `Date.now()`-derived labels are recomputed.
 */
import { useEffect, useState } from "react";

/** Default cadence — fine-grained enough that a stalled run is surfaced within
 *  half a minute of crossing the window, cheap enough to be invisible. */
export const DEFAULT_TICK_MS = 30_000;

export function useNow(intervalMs: number = DEFAULT_TICK_MS): number {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    if (!Number.isFinite(intervalMs) || intervalMs <= 0) return undefined;
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
