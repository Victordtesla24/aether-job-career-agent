"use client";

/**
 * S-UI-REBUILD §3.4 T-A — the Live Activity ticker.
 *
 * THE HONESTY THIS COMPONENT EXISTS TO PROTECT (§3.1(a), §3.2):
 * `/events/stream` reports **that rows changed, not what they contain**. So a
 * row here never names a record. It says "12 new jobs" — the exact delta the
 * server reported — and the owning screen refetches through the ordinary API
 * to show what those jobs actually are. All copy comes from
 * `describeResourceChange`, which is pinned row-by-row against §3.2's table in
 * `lib/telemetry/__tests__/activity-feed.test.ts`.
 *
 * A CALM TICKER IS AN HONEST TICKER. The empty state is the frequent, correct
 * one — a fresh connection's `hello` deliberately produces no rows, because
 * back-filling events we never observed is forbidden. So emptiness is drawn as
 * a designed, quiet state (D-θ), never as a spinner implying work in progress.
 *
 * NO RETRY BUTTON, DELIBERATELY. §3.5 sketches one for the `offline` row, but
 * `lib/realtime/store.ts` exports no reconnect entry point — it schedules its
 * own retry internally (`scheduleRetry(retryDelay())`). Adding a button would
 * mean adding a new public path into the store, i.e. changing wiring, which
 * Binding Constraint 1 forbids in an S-UI slice. The honest substitute is to
 * state the real reason verbatim and the instant the data was last known
 * current, which is what a user needs in order to decide whether to trust the
 * screen.
 */
import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";

import { DURATION, EASE } from "../../lib/motion";
import { useActivityFeed, type ActivityRow } from "../../hooks/useActivityFeed";
import { useRealtimeStatus } from "../../hooks/useRealtime";

/** Rows drawn at desktop. The rest stay in memory and drop off the bottom. */
const VISIBLE_ROWS = 12;

function clockTime(epochMs: number | null): string | null {
  if (epochMs === null) return null;
  return new Date(epochMs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function rowTime(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** C-5 — every tone is paired with a word or a shape, never colour alone. */
const TONE: Record<ActivityRow["tone"], { dot: string; delta: string }> = {
  increase: { dot: "bg-aether-green", delta: "text-aether-green" },
  decrease: { dot: "bg-aether-coral", delta: "text-aether-coral" },
  neutral: { dot: "bg-white/25", delta: "text-aether-muted-dim" },
  gap: { dot: "bg-aether-amber", delta: "text-aether-amber" },
};

export default function ActivityTicker({
  maxRows = VISIBLE_ROWS,
  className = "",
}: {
  maxRows?: number;
  className?: string;
}) {
  const rows = useActivityFeed();
  const state = useRealtimeStatus();
  const since = clockTime(state.connectedAt);

  // §3.5 — the degraded state is DESIGNED, not discovered. Each arm carries the
  // store's verbatim `detail`; none of them keeps animating as if live.
  const degraded =
    state.status === "reconnecting"
      ? {
          tone: "warn" as const,
          headline: since
            ? `Live updates interrupted — showing data as of ${since}`
            : "Live updates interrupted",
        }
      : state.status === "offline"
        ? {
            tone: "danger" as const,
            headline: since
              ? `Live updates stopped — showing data as of ${since}`
              : "Live updates stopped",
          }
        : state.status === "connecting"
          ? { tone: "info" as const, headline: "Connecting…" }
          : null;

  /*
   * `idle` means nothing on this page subscribes, so there is nothing to report.
   * §3.5 says "ticker not rendered" — but this component sits inside a
   * `<Section>` shell, and returning `null` would leave that shell on screen as
   * an empty bordered card: precisely the X-10 ghost-card defect this batch
   * exists to close. So the idle state is DRAWN and NAMED instead of blanked
   * (doctrine D-θ). It is close to unreachable on the Dashboard in any case —
   * this component's own `useActivityFeed` subscribes on mount, which moves the
   * store out of `idle`.
   */
  const isIdle = state.status === "idle";
  const isLive = state.status === "live";
  const visible = rows.slice(0, maxRows);

  return (
    <div className={`flex min-h-0 flex-col ${className}`} data-testid="activity-ticker">
      <div className="mb-2.5 flex items-center gap-2">
        <span
          aria-hidden="true"
          // Motion and glow are reserved for genuinely-live: a non-live state
          // never animates (§1.4's rule, and D-β).
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            isLive
              ? "glow-live bg-aether-green pulse-ok"
              : isIdle
                ? "bg-white/25"
                : degraded?.tone === "danger"
                  ? "bg-red-400"
                  : "bg-aether-amber"
          }`}
        />
        <h3 className="type-section">Live activity</h3>
        {isLive && since ? (
          <span className="type-mono-micro text-aether-muted-dim">since {since}</span>
        ) : null}
      </div>

      {degraded ? (
        <p
          data-testid="activity-ticker-degraded"
          className={`mb-2.5 rounded-lg border px-2.5 py-2 text-[11px] leading-[1.5] ${
            degraded.tone === "danger"
              ? "border-red-500/30 bg-red-500/10 text-red-300"
              : degraded.tone === "warn"
                ? "border-aether-amber/30 bg-aether-amber/10 text-aether-amber"
                : "border-white/10 bg-white/[0.03] text-aether-muted"
          }`}
        >
          {degraded.headline}
          {/* The server's own words, verbatim — never a generic paraphrase. */}
          {state.detail ? (
            <span className="mt-0.5 block opacity-90" data-testid="activity-ticker-detail">
              {state.detail}
            </span>
          ) : null}
        </p>
      ) : null}

      {isIdle ? (
        <p className="type-meta" data-testid="activity-ticker-idle">
          Live updates aren&apos;t running on this screen.
        </p>
      ) : visible.length === 0 ? (
        <p className="type-meta" data-testid="activity-ticker-empty">
          {since ? `Nothing has changed since ${since}.` : "Nothing has changed yet."}
        </p>
      ) : (
        <ul
          // Rows are dimmed while the channel cannot vouch for them being
          // current (§3.5) — the data is kept, its confidence is not.
          className={`-mx-1 min-h-0 flex-1 overflow-y-auto ${degraded ? "opacity-60" : ""}`}
        >
          <AnimatePresence initial={false}>
            {visible.map((row) => {
              const tone = TONE[row.tone];
              return (
                <motion.li
                  key={row.id}
                  layout
                  initial={{ opacity: 0, y: -6, height: 0 }}
                  animate={{ opacity: 1, y: 0, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: DURATION.base, ease: EASE }}
                >
                  <Link
                    href={row.href}
                    className="group flex items-baseline gap-2 rounded-md px-1 py-1 transition hover:bg-white/[0.04] max-sm:min-h-11"
                  >
                    <span
                      aria-hidden="true"
                      className={`h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full ${tone.dot}`}
                    />
                    <span className="type-mono-micro min-w-0 flex-1 truncate text-aether-muted group-hover:text-aether-text">
                      {row.text}
                    </span>
                    {/* The delta chip only exists when the wire proved a count
                        change; a watermark move renders no number at all. */}
                    {row.delta !== null ? (
                      <span className={`type-mono-micro shrink-0 font-semibold ${tone.delta}`}>
                        {row.delta > 0 ? `+${row.delta}` : row.delta}
                      </span>
                    ) : null}
                    <time
                      dateTime={new Date(row.observedAt).toISOString()}
                      className="type-mono-micro shrink-0 text-aether-muted-dim"
                    >
                      {rowTime(row.observedAt)}
                    </time>
                  </Link>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>
      )}

      <p className="type-meta mt-2.5 border-t border-white/[0.06] pt-2">
        This channel reports that rows changed, not what they contain. Screens refetch to show the
        truth.
      </p>
    </div>
  );
}
