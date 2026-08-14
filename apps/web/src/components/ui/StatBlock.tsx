"use client";

/**
 * S-UI-REBUILD §3.4 T-B + reference-pack rule 4 — the one stat tile.
 *
 * TYPOGRAPHY. Reference rule 4 ("numerals get their own typographic
 * treatment") is why the unit is a separate, smaller, raised element rather
 * than part of the value string: Mercury's dashboard renders "$12,505" large
 * with ".87" small and superscript-baselined, and that single move is what
 * makes a number look typeset instead of concatenated. Every numeral is
 * `tabular-nums` (Rule D-γ) so columns of them align.
 *
 * LIVE DELTAS. The chip is a READER over the realtime store's existing
 * observation set (`useRealtimeResourceObservation` — registers a listener,
 * opens nothing). It renders ONLY for a `count_changed` observation with a
 * real prior count, and it DECAYS after {@link DELTA_TTL_MS}: a delta is a
 * *live* signal, and leaving it up forever would make a stale tab look busy.
 *
 * The honesty rule that costs the most to get right (§3.2 row 3):
 * `watermark_advanced` means rows MOVED, not that rows were ADDED. It gets no
 * chip and no number — only the underline sweep. A number there would be a
 * claim the server never made.
 */
import { useEffect, useState, type ReactNode } from "react";

import { useRealtimeResourceObservation } from "../../hooks/useRealtime";
import type { RealtimeResource } from "../../lib/realtime/transport-types";

/** How long a delta chip stays on screen after the observation. §3.4 T-B. */
export const DELTA_TTL_MS = 30_000;

export interface StatBlockProps {
  label: string;
  /** The measured value, already formatted, or `null` for NOT MEASURED. */
  value: ReactNode;
  /** Rendered small and raised, Mercury-style: "%", "USD", ".87". */
  unit?: string;
  /** The support line under the value — denominator, basis, or the reason a
   *  value is unmeasured. Never decorative. */
  note?: ReactNode;
  /** Drives the T-B delta chip. Omit for a stat no stream resource backs. */
  resource?: RealtimeResource;
  /** Optional inline visual (sparkline). Must render real data or nothing. */
  visual?: ReactNode;
  /** Wraps the value — used for the existing `<MetricTooltip>` affordance. */
  children?: ReactNode;
  testId?: string;
  className?: string;
}

/**
 * The live delta for one resource, or `null`.
 *
 * Returns a value only while the observation is fresh AND the server's own
 * `reason` was a count change with a prior count to subtract from.
 */
function useLiveDelta(resource: RealtimeResource | undefined): number | null {
  const observation = useRealtimeResourceObservation(resource ?? "jobs");
  const [, setTick] = useState(0);

  const relevant = resource ? observation : undefined;
  const observedAt = relevant?.observedAt ?? null;

  // Re-render once when the chip's lifetime expires, so it disappears on its
  // own rather than waiting for unrelated state to move.
  useEffect(() => {
    if (observedAt === null) return undefined;
    const remaining = observedAt + DELTA_TTL_MS - Date.now();
    if (remaining <= 0) return undefined;
    const timer = setTimeout(() => setTick((n) => n + 1), remaining);
    return () => clearTimeout(timer);
  }, [observedAt]);

  if (!relevant || relevant.reason !== "count_changed") return null;
  if (relevant.previousCount === null) return null;
  if (Date.now() - relevant.observedAt > DELTA_TTL_MS) return null;

  const delta = relevant.count - relevant.previousCount;
  return delta === 0 ? null : delta;
}

export default function StatBlock({
  label,
  value,
  unit,
  note,
  resource,
  visual,
  children,
  testId,
  className = "",
}: StatBlockProps) {
  const delta = useLiveDelta(resource);

  return (
    <div
      data-testid={testId}
      className={`elev-1 group relative overflow-hidden rounded-2xl p-5 transition-colors duration-[--dur] hover:border-white/[0.14] ${className}`}
    >
      {/*
        The label is a DIRECT child of the root, and the delta chip is
        positioned rather than wrapped in a flex row. That is deliberate: the
        Analytics summary test locates a tile's tooltip via
        `label.closest("div")`, so an intermediate wrapper between the label and
        the value would put the two in different subtrees.
      */}
      <p className="type-section pr-12">{label}</p>
      {delta !== null ? (
        <span
          data-testid={testId ? `${testId}-delta` : undefined}
          // C-5: the sign is a word-equivalent glyph, not colour alone.
          className={`type-mono-micro absolute right-5 top-5 rounded-full border px-1.5 py-0.5 font-semibold ${
            delta > 0
              ? "border-aether-green/30 bg-aether-green/10 text-aether-green"
              : "border-aether-coral/30 bg-aether-coral/10 text-aether-coral"
          }`}
        >
          {delta > 0 ? `+${delta}` : delta}
        </span>
      ) : null}

      {/* Mercury numeral treatment: the magnitude carries the weight, the unit
          rides small and raised beside it. */}
      <div className="mono mt-2.5 flex items-baseline gap-0.5 text-[34px] font-semibold leading-none tracking-[-0.02em] tabular-nums">
        {children ?? value}
        {unit ? (
          <span className="translate-y-[-0.55em] text-[15px] font-medium text-aether-muted">
            {unit}
          </span>
        ) : null}
      </div>

      {note ? <p className="type-meta mt-2">{note}</p> : null}
      {visual ? <div className="mt-3">{visual}</div> : null}
    </div>
  );
}
