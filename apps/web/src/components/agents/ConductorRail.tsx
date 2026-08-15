"use client";

/**
 * P1-B — the CONDUCTOR RAIL: the drawn "manages" edges from the Conductor band
 * into each workflow map's header.
 *
 * ADR-AGI-3 Decision 2 asks for "a supervisor band/node rendered ABOVE the
 * three workflow maps, with structural manages-edges into each map's header,
 * drawn in the U-STORY-3a linkage language". This is that layer, and it obeys
 * the same four rules that layer established, for the same reasons:
 *
 *   · STRUCTURAL, NOT CAUSAL. A fine dotted white stroke — never coral, which
 *     on this page means "a run is live". These edges say how the system is
 *     wired (one scheduler plans every map), not that anything is flowing.
 *   · MOTIONLESS. `data-motion="none"`, no SMIL, no CSS animation anywhere in
 *     the subtree: a moving wire would read as a run in progress.
 *   · MEASURED OR ABSENT. Every line is drawn between two boxes read out of
 *     the live DOM. An unmeasured end (server render, jsdom, a collapsed
 *     panel, a hidden tab) draws NOTHING rather than a guessed coordinate.
 *   · DECORATIVE TO ASSISTIVE TECH. `aria-hidden`, `pointer-events: none`; the
 *     same claim is stated in words inside the band
 *     (`conductorRailStatement`), so nothing is lost when nothing is drawn.
 *
 * It is deliberately a SIBLING overlay over a wrapper that contains both the
 * band and the maps — the band cannot draw into a map from inside its own
 * panel, and giving the map component knowledge of the band would couple two
 * components that have no other reason to know about each other.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import type { OrchestrationMapData } from "../../lib/api/agentPolicy";
import { LINKAGE_DASH, LINKAGE_STROKE_DIM } from "./workflow-linkage";

interface RailLine {
  key: string;
  path: string;
  /** The workflow this edge lands on — used only for a stable test hook. */
  mapKey: string;
}

interface RailGeometry {
  width: number;
  height: number;
  lines: RailLine[];
}

const EMPTY: RailGeometry = { width: 0, height: 0, lines: [] };

function sameGeometry(a: RailGeometry, b: RailGeometry): boolean {
  if (a.width !== b.width || a.height !== b.height) return false;
  if (a.lines.length !== b.lines.length) return false;
  return a.lines.every((line, i) => line.key === b.lines[i].key && line.path === b.lines[i].path);
}

/** A vertical S-curve: the band is above the map, so the bend is on Y. */
function railPath(x1: number, y1: number, x2: number, y2: number): string {
  const dy = Math.max(18, (y2 - y1) * 0.45);
  return `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
}

export default function ConductorRail({
  wrapperRef,
  maps,
}: {
  /** The element that contains BOTH the band and the workflow maps. */
  wrapperRef: React.RefObject<HTMLElement | null>;
  maps: OrchestrationMapData | null;
}) {
  const [geom, setGeom] = useState<RailGeometry>(EMPTY);
  const raf = useRef(0);

  const measure = useCallback(() => {
    const host = wrapperRef.current;
    if (!host) {
      setGeom((prev) => (prev === EMPTY ? prev : EMPTY));
      return;
    }
    const hostRect = host.getBoundingClientRect();
    if (hostRect.width === 0 || hostRect.height === 0) {
      setGeom((prev) => (prev === EMPTY ? prev : EMPTY));
      return;
    }
    const lines: RailLine[] = [];
    (maps?.maps ?? []).forEach((map) => {
      // `CSS.escape` where the environment has it; a plain quoted attribute
      // value otherwise (jsdom, older engines). A key carrying a quote would
      // simply match nothing — a wire not drawn, never a wire drawn wrong.
      const key =
        typeof CSS !== "undefined" && typeof CSS.escape === "function"
          ? CSS.escape(map.key)
          : map.key.replace(/["\\]/g, "\\$&");
      const anchor = host.querySelector<HTMLElement>(`[data-conductor-anchor="${key}"]`);
      const target = host.querySelector<HTMLElement>(
        `[data-testid="orchestration-map-${key}"]`,
      );
      if (!anchor || !target) return;
      const a = anchor.getBoundingClientRect();
      const t = target.getBoundingClientRect();
      if (a.width === 0 || a.height === 0 || t.width === 0 || t.height === 0) return;
      const x1 = a.left - hostRect.left + a.width / 2;
      const y1 = a.bottom - hostRect.top;
      const x2 = t.left - hostRect.left + Math.min(64, t.width / 2);
      const y2 = t.top - hostRect.top;
      // A map ABOVE its own anchor would mean the band is not above the maps —
      // the claim this rail makes visually. Draw nothing rather than a wire
      // that runs the wrong way.
      if (y2 <= y1) return;
      lines.push({ key: `rail-${map.key}`, mapKey: map.key, path: railPath(x1, y1, x2, y2) });
    });
    const next: RailGeometry = {
      width: Math.round(hostRect.width),
      height: Math.round(hostRect.height),
      lines,
    };
    setGeom((prev) => (sameGeometry(prev, next) ? prev : next));
  }, [maps, wrapperRef]);

  useLayoutEffect(() => {
    measure();
  }, [measure]);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onChange = () => {
      if (typeof requestAnimationFrame === "undefined") {
        measure();
        return;
      }
      if (raf.current) return;
      raf.current = requestAnimationFrame(() => {
        raf.current = 0;
        measure();
      });
    };
    window.addEventListener("resize", onChange, { passive: true });
    window.addEventListener("scroll", onChange, { passive: true, capture: true });
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined" && wrapperRef.current) {
      observer = new ResizeObserver(onChange);
      observer.observe(wrapperRef.current);
    }
    return () => {
      window.removeEventListener("resize", onChange);
      window.removeEventListener("scroll", onChange, true);
      observer?.disconnect();
      if (raf.current && typeof cancelAnimationFrame !== "undefined") {
        cancelAnimationFrame(raf.current);
        raf.current = 0;
      }
    };
  }, [measure, wrapperRef]);

  if (geom.lines.length === 0) return null;

  return (
    <svg
      data-testid="conductor-rail"
      aria-hidden="true"
      focusable="false"
      width={geom.width}
      height={geom.height}
      viewBox={`0 0 ${geom.width} ${geom.height}`}
      className="pointer-events-none absolute left-0 top-0 z-[1]"
    >
      {geom.lines.map((line) => (
        <path
          key={line.key}
          data-testid={`conductor-rail-${line.mapKey}`}
          data-motion="none"
          d={line.path}
          fill="none"
          stroke={LINKAGE_STROKE_DIM}
          strokeWidth={1}
          strokeDasharray={LINKAGE_DASH}
          strokeLinecap="round"
        />
      ))}
    </svg>
  );
}
