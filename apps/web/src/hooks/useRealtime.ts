"use client";

/**
 * How a screen joins the one shared realtime channel (W-RT).
 *
 * A screen says which resources it renders and what to do when they change:
 *
 * ```tsx
 * useRealtimeResources(["jobs", "applications"], () => void load());
 * ```
 *
 * The callback should REFETCH through the ordinary API client. The channel
 * never carries domain data (see `lib/realtime/store.ts`), so nothing on screen
 * is ever built from a stream payload — what renders is always what the API
 * returned.
 *
 * The subscription is registered once per mount and is deliberately NOT
 * re-registered when the callback identity changes: screens close over filter
 * state, so their callbacks change on nearly every render, and resubscribing
 * each time would churn the single shared connection every screen depends on.
 * The latest callback is used via a ref instead.
 */

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

import {
  getRealtimeState,
  subscribeToRealtimeState,
  subscribeToResources,
} from "../lib/realtime/store";
import type { RealtimeState } from "../lib/realtime/store";
import type { RealtimeResource, ResourceChange } from "../lib/realtime/transport-types";

export type { RealtimeResource, ResourceChange } from "../lib/realtime/transport-types";
export type { RealtimeState, RealtimeConnectionStatus } from "../lib/realtime/store";

export interface UseRealtimeResourcesOptions {
  /**
   * When false the screen does not join the channel at all. Use it while a
   * screen has nothing loaded (or is behind a gate), so it does not hold the
   * shared connection open for updates it cannot render.
   */
  enabled?: boolean;
}

export function useRealtimeResources(
  resources: readonly RealtimeResource[],
  onChange: (change: ResourceChange) => void,
  options: UseRealtimeResourcesOptions = {},
): void {
  const { enabled = true } = options;
  const handlerRef = useRef(onChange);
  handlerRef.current = onChange;

  // Resource lists are written inline at call sites (`["jobs"]`), so their
  // identity changes every render. Key the effect on the CONTENT instead, or
  // the subscription would be torn down and rebuilt on every render.
  const key = [...resources].sort().join(",");

  useEffect(() => {
    if (!enabled || key === "") return undefined;
    const list = key.split(",") as RealtimeResource[];
    // One server poll can report several resources moving at once (a pipeline
    // run writes Job, Application and AgentRun rows together), and the store
    // delivers each as its own change — deliberately, so nothing is hidden from
    // a consumer that cares which resource moved. A SCREEN, though, refetches
    // the same views regardless of which of its resources triggered it, so
    // running that reload once per frame in the same tick is pure duplicate
    // work (Analytics is four API calls a reload). The first change of a burst
    // is delivered synchronously; the rest of that tick is suppressed, and the
    // single refetch that does run necessarily sees ALL of the writes.
    //
    // A handler that branches on `change.resource` should therefore subscribe
    // once per resource (as `app/dashboard/page.tsx` does) rather than branch
    // inside one multi-resource subscription.
    let bursting = false;
    return subscribeToResources(list, (change) => {
      if (bursting) return;
      bursting = true;
      queueMicrotask(() => {
        bursting = false;
      });
      handlerRef.current(change);
    });
  }, [key, enabled]);
}

/**
 * The channel's honest connection state, re-rendering on every transition.
 *
 * Consumers must not treat "not live" as cosmetic: it means the screen may be
 * showing data that is no longer current, and the UI has to say so.
 */
export function useRealtimeStatus(): RealtimeState {
  const subscribe = useCallback(
    (notify: () => void) => subscribeToRealtimeState(() => notify()),
    [],
  );
  return useSyncExternalStore(subscribe, getRealtimeState, getRealtimeState);
}
