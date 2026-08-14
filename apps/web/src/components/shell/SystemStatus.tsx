"use client";

/**
 * S-UI-REBUILD §1.4 — the live-status chip becomes a system-status element.
 *
 * WHAT THIS IS NOT
 * ----------------
 * It is not a new telemetry source. It opens no connection, issues no fetch
 * and polls nothing: `useRealtimeSnapshot()` is a READER over the ONE
 * existing SSE store (`lib/realtime/store.ts`), registered as a listener and
 * nothing more. On a page where no screen subscribes, the store is `idle`,
 * this element renders nothing, and the stream budget (3/user, 8 global) is
 * untouched. That is spec §3's standing law and risk R-6's mitigation.
 *
 * WHAT IT MAY CLAIM
 * -----------------
 * Only what the wire carries (§3.1a): per-resource row COUNTS and
 * WATERMARKS the server observed, plus the client clock at which each frame
 * arrived. The channel carries no record contents and names no business
 * event, so neither does this popover — the footnote says so out loud.
 *
 * The §3.2 mapping law is enforced in {@link describeDelta}:
 *   - `count > previousCount`      → "↑N" + "new"      (the delta is exact)
 *   - `count < previousCount`      → "↓N" + "removed"  (never "new", never green)
 *   - counts equal (watermark_advanced / reconnect_gap) → "·" + "updated",
 *     never a number
 *   - no previous count at all (connect-time `hello`) → "·" and NO word: a
 *     first observation is not a change, and back-filling one would invent a
 *     history we never observed.
 *
 * MOTION (§1.4, §3.5): a non-live state NEVER animates. `live` pulses,
 * `reconnecting` breathes (it is actively retrying — that is real work), and
 * `connecting` / `offline` / `idle` are static and say what is wrong in
 * words. `RealtimeStatusBadge` stays the compact renderer so every state
 * string, the `asOf()` phrasing, the 30s `OFFLINE_GRACE_MS` grace and the
 * server's verbatim `detail` survive verbatim — this is a container upgrade,
 * not a copy rewrite.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useNow } from "../../hooks/useNow";
import { useRealtimeSnapshot, useRealtimeStatus } from "../../hooks/useRealtime";
import type { RealtimeResourceObservation } from "../../hooks/useRealtime";
import { RealtimeStatusBadge } from "../realtime/RealtimeStatusBadge";

/** Human labels for the 12 wire resource keys. Presentation only — the key
 * itself is shown alongside so nothing is renamed away. */
const RESOURCE_LABEL: Record<string, string> = {
  jobs: "Jobs",
  applications: "Applications",
  coverLetters: "Cover letters",
  resumes: "Resumes",
  stories: "Stories",
  emails: "Emails",
  contacts: "Contacts",
  outreach: "Outreach",
  interviews: "Interviews",
  offers: "Offers",
  approvals: "Approvals",
  agentRuns: "Agent runs",
};

export interface DeltaDescription {
  /** "↑12" / "↓3" / "·" */
  glyph: string;
  /** "new" / "removed" / "updated" / "" — never "new" without a real rise. */
  word: string;
  tone: "ok" | "warn" | "neutral";
}

/** §3.2, expressed once. Exported so a test can pin the law directly. */
export function describeDelta(entry: RealtimeResourceObservation): DeltaDescription {
  if (entry.previousCount === null) {
    // Connect-time observation. There is no delta to state.
    return { glyph: "·", word: "", tone: "neutral" };
  }
  const delta = entry.count - entry.previousCount;
  if (delta > 0) return { glyph: `↑${delta}`, word: "new", tone: "ok" };
  if (delta < 0) return { glyph: `↓${Math.abs(delta)}`, word: "removed", tone: "warn" };
  return { glyph: "·", word: "updated", tone: "neutral" };
}

function clockTime(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function clockTimeWithSeconds(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function SystemStatus({
  className = "",
  compact = false,
}: {
  className?: string;
  /** Command-bar mirror: badge label only, no "as of" suffix. */
  compact?: boolean;
}) {
  const state = useRealtimeStatus();
  const snapshot = useRealtimeSnapshot();
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  // Only ticks while the popover is open — "last frame Ns" is the one label
  // here that goes stale on its own, and nothing else needs a clock.
  const now = useNow(open ? 1_000 : 0);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return undefined;
    function onDown(event: MouseEvent) {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (popoverRef.current?.contains(target)) return;
      setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Same focus contract the notification panel already proved (REV-U-UI-05):
  // move focus into the portaled surface on open, hand it back to the trigger
  // on close unless something else has already claimed it.
  useEffect(() => {
    if (!open) return undefined;
    const popover = popoverRef.current;
    if (!popover) return undefined;
    const trigger = triggerRef.current;
    popover.focus();
    return () => {
      if (document.activeElement === document.body) trigger?.focus();
    };
  }, [open]);

  // §3.5 / `hideWhenIdle` parity: nothing on this page subscribes, so there is
  // genuinely nothing to report. A permanent "idle" affordance would be noise.
  if (state.status === "idle") return null;

  const lastFrameSeconds =
    state.lastMessageAt === null ? null : Math.max(0, Math.round((now - state.lastMessageAt) / 1000));

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        data-testid="system-status-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label="System status — live update channel details"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex max-w-full items-center gap-1.5 rounded-lg px-1 py-0.5 text-left transition-colors duration-[--dur-fast] hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/60 ${className}`}
      >
        <RealtimeStatusBadge compact={compact} hideWhenIdle className="shrink min-w-0" />
        <i className="fa-solid fa-circle-info shrink-0 text-[10px] text-aether-muted-dim" aria-hidden="true" />
      </button>

      {mounted && open
        ? createPortal(
            <>
              <div
                aria-hidden="true"
                data-testid="system-status-backdrop"
                onClick={() => setOpen(false)}
                className="fixed inset-0 z-40"
              />
              <div
                ref={popoverRef}
                role="dialog"
                aria-modal="false"
                aria-label="System status"
                tabIndex={-1}
                data-testid="system-status-popover"
                data-status={state.status}
                className="elev-3 fixed inset-x-4 bottom-4 z-50 max-h-[70vh] overflow-y-auto rounded-xl p-4 sm:inset-x-auto sm:left-4 sm:w-[22rem] lg:left-[calc(var(--aether-rail-w,248px)+1rem)]"
              >
                <p className="type-section">Connection</p>
                {/* One dot, owned by the badge (which also owns every state
                    string and the `data-motion` rule). Duplicating it here
                    would risk the two drifting apart. */}
                <div className="mt-2 flex items-center gap-2">
                  <RealtimeStatusBadge />
                </div>

                <p className="type-mono-micro mt-2 text-aether-muted-dim" data-testid="system-status-connection">
                  {state.connectedAt === null
                    ? "Never connected on this page."
                    : `Connected ${clockTimeWithSeconds(state.connectedAt)}${
                        lastFrameSeconds === null ? "" : ` · last frame ${lastFrameSeconds}s ago`
                      }`}
                </p>
                {snapshot.resources.length > 0 ? (
                  <p className="type-mono-micro mt-0.5 text-aether-muted-dim">
                    Streaming {snapshot.resources.length} resource
                    {snapshot.resources.length === 1 ? "" : "s"} on 1 channel
                  </p>
                ) : null}
                {state.detail ? (
                  // The server's own words, never paraphrased.
                  <p
                    data-testid="system-status-detail"
                    className={`type-meta mt-2 ${
                      state.status === "offline" ? "text-state-danger" : "text-state-warn"
                    }`}
                  >
                    {state.detail}
                  </p>
                ) : null}

                <p className="type-section mt-4">Resources</p>
                {snapshot.resources.length === 0 ? (
                  <p className="type-meta mt-2" data-testid="system-status-empty">
                    The server has not reported any resource counts on this connection yet.
                  </p>
                ) : (
                  <table className="mt-2 w-full" data-testid="system-status-resources">
                    <caption className="sr-only">
                      Server-observed row counts per resource, with any change since the
                      previous observation.
                    </caption>
                    <thead>
                      <tr className="type-section">
                        <th scope="col" className="pb-1 text-left font-semibold">
                          Resource
                        </th>
                        <th scope="col" className="pb-1 text-right font-semibold">
                          Count
                        </th>
                        <th scope="col" className="pb-1 text-right font-semibold">
                          Change
                        </th>
                        <th scope="col" className="pb-1 text-right font-semibold">
                          Seen
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshot.resources.map((entry) => {
                        const delta = describeDelta(entry);
                        return (
                          <tr
                            key={entry.resource}
                            data-testid={`system-status-row-${entry.resource}`}
                            data-delta={delta.glyph}
                            className="border-t border-hairline"
                          >
                            <th
                              scope="row"
                              className="py-1 text-left text-[11px] font-normal text-aether-muted"
                            >
                              {RESOURCE_LABEL[entry.resource] ?? entry.resource}
                            </th>
                            <td className="type-mono-micro py-1 text-right">{entry.count}</td>
                            <td
                              className={`type-mono-micro py-1 text-right ${
                                delta.tone === "ok"
                                  ? "text-state-ok"
                                  : delta.tone === "warn"
                                    ? "text-state-warn"
                                    : "text-state-neutral"
                              }`}
                            >
                              {delta.glyph}
                              {delta.word ? (
                                <span className="ml-1 text-[10px] text-aether-muted-dim">
                                  {delta.word}
                                </span>
                              ) : null}
                            </td>
                            <td className="type-mono-micro py-1 text-right text-aether-muted-dim">
                              {clockTime(entry.observedAt)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}

                <p className="type-meta mt-3 border-t border-hairline pt-2">
                  Counts are the server&rsquo;s own row observations. The channel carries no
                  record contents — screens refetch through the ordinary API to show what
                  changed.
                </p>
              </div>
            </>,
            document.body,
          )
        : null}
    </>
  );
}

export default SystemStatus;
