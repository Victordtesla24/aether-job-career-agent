"use client";

/**
 * ADMIN-2.0 FE-1 — the executive dashboard's HEADLINE BAND.
 *
 * Five slots, always all five, always in the same order. The tile language is
 * the one already certified on the Analytics executive band
 * (`components/analytics/ExecutiveSummary.tsx`): label on its own line, a
 * 28px mono numeral with the delta chip riding alongside it, a spark that
 * carries the same declared window as the visible basis line, and at most one
 * deterministic sentence underneath.
 *
 * A tile that cannot be measured does NOT disappear. It holds its slot with
 * the chart kit's em dash and the reason — because a five-tile board that
 * silently becomes a three-tile board tells the reader nothing is wrong.
 */
import { Spark, useChartMotion } from "../../charts";
import { DecisionGuidance } from "../../ui/decision-guidance";
import type { AdminKpiTile } from "../../../lib/admin/executive";

/** Certified tone language — see `lib/admin/executive.ts` › `delta` for why a
 *  fall is amber (warn) rather than red (broken). Colour is never the only
 *  signal: the chip carries a glyph and a signed number as well (C-5). */
const TONE_CLASS: Record<string, string> = {
  up: "border-aether-green/30 bg-aether-green/10 text-aether-green",
  down: "border-aether-amber/40 bg-aether-amber/10 text-aether-amber",
  neutral: "border-white/15 bg-white/[0.04] text-aether-muted",
};

const TONE_GLYPH: Record<string, string> = { up: "▲", down: "▼", neutral: "" };

function KpiTile({ tile, index }: { tile: AdminKpiTile; index: number }) {
  const motion = useChartMotion();
  const delay = motion.stagger(index, 55, 5);

  return (
    <div
      data-testid={`admin-kpi-${tile.id}`}
      data-measured={tile.measured ? "true" : "false"}
      className="elev-1 flex min-w-0 flex-col overflow-hidden rounded-2xl p-4 transition-colors duration-[--dur] hover:border-white/[0.14]"
      style={{
        opacity: motion.atOrigin ? 0 : undefined,
        transform: motion.atOrigin ? "translateY(6px)" : undefined,
        ...motion.transitionParts("opacity, transform", delay),
      }}
    >
      <p className="type-section truncate" title={tile.label}>
        {tile.label}
      </p>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <div
          data-testid={`admin-kpi-${tile.id}-value`}
          className="mono flex items-baseline gap-0.5 text-[28px] font-semibold leading-none tracking-[-0.02em] tabular-nums"
          style={tile.measured ? undefined : { color: "#8B8BA3" }}
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
            data-testid={`admin-kpi-${tile.id}-delta`}
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
          windowLabel={tile.spark.windowLabel}
          kind={tile.spark.kind}
          data={tile.spark.data}
          nullMeaning={tile.spark.nullMeaning}
          target={tile.spark.target}
          axisMax={tile.spark.axisMax}
          height={tile.spark.kind === "bullet" ? 26 : 30}
        />
      </div>

      {/* An unmeasured tile leads with WHY. A measured one leads with the
          denominator or the caveat. Neither is ever silent. */}
      {tile.measured ? null : (
        <p
          data-testid={`admin-kpi-${tile.id}-reason`}
          className="mt-2.5 text-[11px] leading-[1.45] text-aether-muted"
        >
          {tile.reason}
        </p>
      )}
      {tile.detail ? (
        <p
          data-testid={`admin-kpi-${tile.id}-detail`}
          className="mt-1.5 text-[11px] leading-[1.45] text-aether-muted"
        >
          {tile.detail}
        </p>
      ) : null}
      <p className="mt-1 text-[11px] leading-[1.4] text-aether-muted-dim">{tile.basis}</p>
    </div>
  );
}

export function KpiBand({ tiles }: { tiles: readonly AdminKpiTile[] }) {
  return (
    <section data-testid="admin-kpi-band" aria-labelledby="admin-kpi-heading">
      <h2 id="admin-kpi-heading" className="sr-only">
        Headline metrics
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {tiles.map((tile, index) => (
          <KpiTile key={tile.id} tile={tile} index={index} />
        ))}
      </div>
      {/* R1.2 — one band-level guidance line: the five tiles share a reading. */}
      <DecisionGuidance
        tellsYou="the platform's five headline figures for the declared window — every value is measured from the database, and an unmeasured tile says so instead of showing zero."
        next="read the amber deltas first: a falling headline figure is a prompt to open the matching panel below, not an alarm on its own."
      />
    </section>
  );
}
