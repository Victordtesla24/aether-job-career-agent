"use client";

/**
 * S-UI-REBUILD §3.4 T-A — the Live Activity ticker's data source.
 *
 * A **reader** over the ONE existing realtime channel: it subscribes to all 12
 * resource keys and keeps the last {@link ACTIVITY_FEED_CAPACITY} changes in
 * memory. **No new connection, no new endpoint, no persistence.**
 *
 * That is true rather than merely intended because `GET /events/stream` is not
 * parameterised by resource (`lib/realtime/transport.ts` — `STREAM_PATH` takes
 * no query), so the resource list here is a client-side fan-out filter and
 * costs no additional request. The Dashboard already holds the connection open
 * for its seven widget subscriptions; this adds rows to what that same socket
 * already delivers.
 *
 * A first connection's `hello` produces NO rows: the store only delivers a
 * change when it has a PREVIOUS server snapshot to diff against
 * (`lib/realtime/store.ts` — `diffSnapshots` runs only when `previous` exists).
 * §3.2 requires exactly that: back-filling a history of events we never
 * observed is forbidden, so an empty ticker on a fresh page is correct.
 */
import { useEffect, useRef, useState } from "react";

import { subscribeToResources } from "../lib/realtime/store";
import { REALTIME_RESOURCES } from "../lib/realtime/transport-types";
import {
  ACTIVITY_FEED_CAPACITY,
  describeResourceChange,
  type ActivityRow,
} from "../lib/telemetry/activity-feed";

export type { ActivityRow } from "../lib/telemetry/activity-feed";

export function useActivityFeed(): ActivityRow[] {
  const [rows, setRows] = useState<ActivityRow[]>([]);
  // Two changes can land in the same millisecond (one poll reports several
  // resources moving together), which would collide the `observedAt`-derived
  // key. A monotonic suffix keeps React keys stable without putting a
  // render-time clock anywhere near the row's displayed timestamp.
  const seq = useRef(0);

  useEffect(() => {
    return subscribeToResources(REALTIME_RESOURCES, (change) => {
      seq.current += 1;
      const row = describeResourceChange(change, Date.now());
      setRows((previous) =>
        [{ ...row, id: `${row.id}-${seq.current}` }, ...previous].slice(0, ACTIVITY_FEED_CAPACITY),
      );
    });
  }, []);

  return rows;
}
