"use client";

/**
 * ANALYTICS-VIZ — the EXECUTIVE SUMMARY BAND.
 *
 * The user's mandate: "at the top show an executive summary useful to users to
 * know what's what in ONE GLANCE". A glance is not a paragraph, so this band is
 * a row of measured tiles: a numeral, a shape, a delta against a stated target
 * or a prior measurement, and at most one deterministic line each.
 *
 * WHERE THE NUMBERS COME FROM. `lib/analytics/executive-summary.ts`, purely,
 * over the five payloads this page ALREADY fetches. No request was added, none
 * was moved, and every string on a tile is a computation over a real number —
 * there is no model anywhere in this path and nothing here is written by hand
 * at render time (S-UI binding constraint 1; the orchestrator's "NEVER
 * LLM-generated, NEVER invented" ruling).
 *
 * WHY THE TILES NEVER DISAPPEAR. The band always renders its five slots in the
 * same order. An endpoint that failed leaves its tile in place, showing the
 * kit's em dash and the reason on the tile — the alternative (dropping the
 * tile) reflows the band under the reader AND hides the failure, which is the
 * exact defect class the page's "—, never 0" rules exist to prevent.
 *
 * MOTION. Entrance only, through the chart kit's own `useChartMotion`, so
 * `prefers-reduced-motion` is honoured in one place for the tiles and their
 * sparks alike. Nothing in this band pulses: the telemetry law reserves pulse
 * for genuinely live elements, and a derived summary is not one.
 */
import { Spark } from "../charts";
import type { ExecTileModel } from "../../lib/analytics/executive-summary";
import { useChartMotion } from "../charts";

const TONE_CLASS: Record<string, string> = {
  up: "border-aether-green/30 bg-aether-green/10 text-aether-green",
  down: "border-aether-amber/40 bg-aether-amber/10 text-aether-amber",
  neutral: "border-white/15 bg-white/[0.04] text-aether-muted",
};

/** C-5 — the chip's direction is carried by a glyph AND its words, never by
 *  colour alone. `neutral` gets no glyph because it asserts no direction. */
const TONE_GLYPH: Record<string, string> = {
  up: "▲",
  down: "▼",
  neutral: "",
};

function ExecTile({ tile, index }: { tile: ExecTileModel; index: number }) {
  const motion = useChartMotion();
  const delay = motion.stagger(index, 55, 5);

  return (
    <div
      data-testid={`exec-tile-${tile.id}`}
      data-measured={tile.measured ? "true" : "false"}
      className="elev-1 group relative flex flex-col overflow-hidden rounded-2xl p-4 transition-colors duration-[--dur] hover:border-white/[0.14]"
      style={{
        opacity: motion.atOrigin ? 0 : undefined,
        transform: motion.atOrigin ? "translateY(6px)" : undefined,
        ...motion.transitionParts("opacity, transform", delay),
      }}
    >
      {/* The label owns its own full-width line. The delta chip rides with the
          VALUE, not with the label: at five tiles across 1600px a chip like
          "▼ 20 pts to target" is wider than the label beside it, and putting
          the two in one row truncated "Interview conversion" to "INTERVIE…" —
          a metric nobody can name is not a summary. */}
      <p className="type-section truncate" title={tile.label}>
        {tile.label}
      </p>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <div
          data-testid={`exec-tile-${tile.id}-value`}
          className="mono flex items-baseline gap-0.5 text-[28px] font-semibold leading-none tracking-[-0.02em] tabular-nums"
        >
          {tile.value}
          {tile.unit ? (
            <span className="translate-y-[-0.5em] text-[13px] font-medium text-aether-muted">
              {tile.unit}
            </span>
          ) : null}
        </div>
        {tile.delta ? (
          <span
            data-testid={`exec-tile-${tile.id}-delta`}
            data-tone={tile.delta.tone}
            title={tile.delta.title}
            className={`type-mono-micro shrink-0 whitespace-nowrap rounded-full border px-1.5 py-0.5 font-semibold ${
              TONE_CLASS[tile.delta.tone] ?? TONE_CLASS.neutral
            }`}
          >
            {TONE_GLYPH[tile.delta.tone] ? `${TONE_GLYPH[tile.delta.tone]} ` : ""}
            {tile.delta.text}
          </span>
        ) : null}
      </div>

      <div className="mt-3">
        <Spark
          title={tile.label}
          windowLabel={tile.basis}
          kind={tile.spark.kind}
          data={tile.spark.data}
          nullMeaning={tile.spark.nullMeaning}
          target={tile.spark.target}
          height={tile.spark.kind === "bullet" ? 26 : 30}
        />
      </div>

      {/* THE one measured line. `insight` is the deterministic reading of the
          numbers above it; `basis` is the window they were measured in and is
          the SAME string the spark asserted against (C-3), so the reader and
          the chart kit can never be looking at different claims. */}
      <p
        data-prose="insight"
        data-testid={`exec-tile-${tile.id}-insight`}
        className="mt-2.5 text-[11px] leading-[1.45] text-aether-muted"
      >
        {tile.insight}
      </p>
      <p
        data-prose="caption"
        data-testid={`exec-tile-${tile.id}-basis`}
        className="mt-1 text-[11px] leading-[1.4] text-aether-muted-dim"
      >
        {tile.basis}
      </p>
    </div>
  );
}

export default function ExecutiveSummary({ tiles }: { tiles: readonly ExecTileModel[] }) {
  return (
    <section data-testid="executive-summary" aria-labelledby="executive-summary-heading">
      <h2 id="executive-summary-heading" className="sr-only">
        Executive summary
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {tiles.map((tile, index) => (
          <ExecTile key={tile.id} tile={tile} index={index} />
        ))}
      </div>
    </section>
  );
}
