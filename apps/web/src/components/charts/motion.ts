"use client";

/**
 * Chart motion — deliberately the smallest possible animation surface.
 *
 * Doctrine D-β ("nothing moves unless something moved") plus S-UI-REBUILD-SPEC
 * §5.2 ("charts do NOT animate on refetch — a chart that re-grows every 30s is
 * noise, and worse, it implies change that may not have happened") give the
 * kit exactly one animation: a one-time reveal on first mount.
 *
 * Phases:
 *   off       reduced motion — final values, no transition styles at all
 *   initial   client-only pre-paint frame holding the origin values
 *   animating transition attached, values at their final positions
 *   settled   transition removed — a later data update changes values with no
 *             animation, which is what makes "no re-grow on refetch" true
 *             rather than merely intended
 *
 * The server and the very first client render both produce the FINAL values
 * (phase "off"), so a chart is never invisible when JavaScript is slow, blocked
 * or absent.
 */
import { useEffect, useLayoutEffect, useState } from "react";

import { DUR_REVEAL, EASE } from "./tokens";

export type MotionPhase = "off" | "initial" | "animating" | "settled";

/** SSR-safe layout effect (React logs a warning for useLayoutEffect on the
 *  server; charts are client components but may be pre-rendered). */
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export interface ChartMotion {
  phase: MotionPhase;
  /** True once the reveal is allowed to run at all. */
  enabled: boolean;
  /** True while marks should sit at their origin (pre-reveal) position. */
  atOrigin: boolean;
  /** Transition style for a reveal, or `undefined` when motion is off/settled
   *  — `undefined` leaves the DOM property empty rather than writing "none". */
  transition: (property: string, delayMs?: number) => string | undefined;
  /** Per-item stagger delay, capped so a long list cannot animate forever. */
  stagger: (index: number, stepMs?: number, cap?: number) => number | undefined;
  /** Longhand form of `transition`, for elements that also need their own
   *  delay: mixing the `transition` shorthand with `transitionDelay` makes
   *  React warn, and the shorthand would silently reset the delay. */
  transitionParts: (property: string, delayMs?: number) => CSSTransitionParts;
}

export interface CSSTransitionParts {
  transitionProperty?: string;
  transitionDuration?: string;
  transitionTimingFunction?: string;
  transitionDelay?: string;
}

export function useChartMotion(durationMs: number = DUR_REVEAL): ChartMotion {
  const [phase, setPhase] = useState<MotionPhase>("off");

  useIsomorphicLayoutEffect(() => {
    if (prefersReducedMotion()) {
      setPhase("off");
      return;
    }
    setPhase("initial");
  }, []);

  useEffect(() => {
    if (phase !== "initial") return undefined;
    const frame = requestAnimationFrame(() => setPhase("animating"));
    return () => cancelAnimationFrame(frame);
  }, [phase]);

  useEffect(() => {
    if (phase !== "animating") return undefined;
    const timer = setTimeout(() => setPhase("settled"), durationMs + 400);
    return () => clearTimeout(timer);
  }, [phase, durationMs]);

  const enabled = phase !== "off";
  return {
    phase,
    enabled,
    atOrigin: phase === "initial",
    transition: (property, delayMs) =>
      phase === "initial" || phase === "animating"
        ? `${property} ${durationMs}ms ${EASE}${delayMs ? ` ${delayMs}ms` : ""}`
        : undefined,
    stagger: (index, stepMs = 35, cap = 8) =>
      enabled && phase !== "settled" ? Math.min(index, cap) * stepMs : undefined,
    transitionParts: (property, delayMs) =>
      phase === "initial" || phase === "animating"
        ? {
            transitionProperty: property,
            transitionDuration: `${durationMs}ms`,
            transitionTimingFunction: EASE,
            transitionDelay: delayMs ? `${delayMs}ms` : undefined,
          }
        : {},
  };
}
