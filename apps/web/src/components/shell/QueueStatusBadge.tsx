"use client";

/**
 * D-QDEPTH — honest worker-queue-depth badge for the dashboard header.
 *
 * Polls `GET /queue/status` every 60s via the canonical `usePolling` hook
 * (§11.2) and renders ONLY when there is real, actionable information to
 * show: `queuedJobs >= 1`. An empty queue (`0`) and a Redis outage
 * (`state: "unavailable"`) both render nothing — "honest quiet" rather than
 * a permanent chip that says "0 jobs queued" or surfaces an internal
 * infrastructure error to every user.
 *
 * Deliberately its OWN small component rather than folded into
 * `SystemStatus` (§1.4): that component is documented and tested as a pure
 * reader over the existing realtime SSE store — "it opens no connection,
 * issues no fetch and polls nothing" — and this badge is exactly the
 * opposite of that contract (a 60s poll of a plain REST endpoint).
 */
import { useState } from "react";

import { fetchQueueStatus } from "../../lib/api/queueStatus";
import { usePolling } from "../../hooks/usePolling";

const POLL_INTERVAL_MS = 60_000;

export function QueueStatusBadge({ className = "" }: { className?: string }) {
  const [queuedJobs, setQueuedJobs] = useState<number | null>(null);

  usePolling(async () => {
    try {
      const status = await fetchQueueStatus();
      setQueuedJobs(status.state === "ok" ? status.queuedJobs : null);
    } catch {
      // A transport failure is exactly as "nothing to honestly report" as
      // the server's own `state: "unavailable"` — never surfaced as an error.
      setQueuedJobs(null);
    }
  }, POLL_INTERVAL_MS);

  if (queuedJobs === null || queuedJobs < 1) return null;

  return (
    <span
      data-testid="queue-status-badge"
      className={`type-mono-micro inline-flex shrink-0 items-center gap-1 rounded-full border border-hairline bg-surface-1 px-2 py-0.5 text-aether-muted-dim ${className}`}
    >
      <i className="fa-solid fa-layer-group text-[10px]" aria-hidden="true" />
      {queuedJobs} {queuedJobs === 1 ? "job" : "jobs"} queued
    </span>
  );
}

export default QueueStatusBadge;
