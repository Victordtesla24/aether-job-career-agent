"use client";

import { useEffect, useRef } from "react";

export interface UsePollingOptions {
  /** When false, polling (and the initial fetch) is disabled entirely. */
  enabled?: boolean;
  /**
   * Changing this value tears down and restarts the poll cycle — the
   * fetcher is invoked immediately with its fresh closure instead of
   * waiting for the next tick. Use it when the fetcher's inputs change
   * (e.g. an active filter) and the screen should refresh right away
   * rather than sit on stale data until the next interval fires.
   */
  restartKey?: unknown;
}

/**
 * Canonical shared polling hook (GOLD-MASTER-V2 §11.2).
 *
 * Before this hook existed, every screen that wanted a "live" refresh
 * hand-rolled its own `setInterval`/`window.setInterval` — five independent
 * copies (sidebar 30s, topbar 60s, agents job-run poll, applications 20s,
 * jobs 20s), each with slightly different (or missing) unmount/visibility
 * handling. `usePolling` centralises the contract every one of those call
 * sites needs:
 *
 *   1. invoke `fetcher` once immediately on mount (the initial load),
 *   2. re-invoke it every `intervalMs` after that,
 *   3. stop invoking it after unmount (no state-update-after-unmount leak),
 *   4. pause while `document.visibilityState !== "visible"`, resuming (with
 *      an immediate catch-up fetch) on the next `visibilitychange` — a
 *      backgrounded tab should not keep burning API calls/tokens.
 *
 * This file does not migrate the five existing ad-hoc call sites (that is a
 * separate, larger diff tracked outside this fix — see the W-I fix report
 * for exactly which screens this run adopted the hook on). It is the
 * canonical implementation new adopters use going forward, starting with
 * Story Bank (`app/dashboard/stories/page.tsx`).
 */
export function usePolling(
  fetcher: () => Promise<unknown> | unknown,
  intervalMs: number,
  options: UsePollingOptions = {},
): void {
  const { enabled = true, restartKey } = options;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!enabled) return undefined;

    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer != null) return;
      timer = setInterval(() => {
        if (document.visibilityState === "visible") {
          void fetcherRef.current();
        }
      }, intervalMs);
    };
    const stop = () => {
      if (timer != null) {
        clearInterval(timer);
        timer = null;
      }
    };

    // Initial load — always fires on mount/restart regardless of tab
    // visibility; this is the explicit first load, not a background poll.
    void fetcherRef.current();
    start();

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        // Catch up immediately on return instead of waiting out whatever is
        // left of the current interval.
        void fetcherRef.current();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
    // restartKey is intentionally part of the dependency array — see
    // UsePollingOptions.restartKey doc above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled, restartKey]);
}
