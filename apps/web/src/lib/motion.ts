/**
 * S-UI-REBUILD §2 — the app's motion language, in one place.
 *
 * WHY THIS FILE IS FRAMER-FREE
 * ----------------------------
 * §2.1 forbids importing `framer-motion` from `lib/` or from any server
 * component. These are plain data objects, so a server component may compute
 * with them and only the client components that actually animate pull the
 * library in. The values are typed with `as const` so framer's `Transition`
 * accepts `type: "spring"` as the literal it wants rather than `string`.
 *
 * WHAT THE NUMBERS MEAN (doctrine D-η: "motion has a physics")
 * -----------------------------------------------------------
 * Everything in the product animates with either one of the three DURATION
 * tiers or one of the three SPRINGs. An ad-hoc `transition-all duration-300`
 * is a review failure. Two exceptions are named in the spec (§3.4 telemetry
 * pulses and the orchestration edge dot) and are owned by other batches.
 */

/**
 * Springs — for anything that moves POSITION (§2.3).
 *
 * These are the only place the stiffness/damping/mass numbers exist.
 */
export const SPRING = {
  /** Active nav bar, badge pop, command palette. */
  snappy: { type: "spring", stiffness: 520, damping: 34, mass: 0.7 },
  /** Sheet, rail collapse, layout shifts. */
  smooth: { type: "spring", stiffness: 260, damping: 30, mass: 0.9 },
  /** Number counters, bar growth. */
  gentle: { type: "spring", stiffness: 140, damping: 22, mass: 1.0 },
} as const;

/**
 * Duration tiers in SECONDS (§2.2). The CSS custom properties `--dur-fast` /
 * `--dur` / `--dur-slow` in `globals.css` carry the same values in ms; these
 * are their framer-side twins so a JS animation and its CSS neighbour cannot
 * drift apart.
 *
 * | tier | ms  | owns                                                    |
 * |------|-----|---------------------------------------------------------|
 * | fast | 120 | hover, press, focus ring, chip toggle, tooltip open      |
 * | base | 180 | card enter, popover, tab content swap, badge change      |
 * | slow | 260 | route transition, drawer/sheet, modal, rail collapse     |
 */
export const DURATION = {
  fast: 0.12,
  base: 0.18,
  slow: 0.26,
} as const;

/**
 * The single easing curve, mirroring `--ease` in `globals.css`.
 * Declared as a mutable 4-tuple because framer's `Easing` type rejects a
 * `readonly` array.
 */
export const EASE: [number, number, number, number] = [0.2, 0, 0, 1];

/**
 * M1 entrance stagger (§2.4). Capped at 8 children: a 22-card stagger at
 * 35ms is a 770ms wait before the last card exists, which reads as jank, not
 * polish. The 9th child onward appears instantly.
 */
export const STAGGER = {
  step: 0.035,
  /** Children after this index get no delay at all. */
  cap: 8,
} as const;

/** Per-child delay for an M1 stagger, honouring {@link STAGGER.cap}. */
export function staggerDelay(index: number): number {
  return Math.min(index, STAGGER.cap) * STAGGER.step;
}

/**
 * Pattern M1 as used by `app/dashboard/template.tsx` for the route
 * transition: an 8px rise + fade, no exit animation.
 *
 * §1.7's illustrative snippet writes `duration: 0.22`; §2.2's tier table —
 * which is the normative one, and the one doctrine D-η is scored against —
 * assigns the route transition to `--dur-slow`. The tier wins, so the value
 * here is {@link DURATION.slow}. Under `MotionConfig reducedMotion="user"`
 * framer drops the `y` and leaves the opacity swap, which is the whole
 * reduced-motion contract for this pattern.
 */
export const PAGE_TRANSITION = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: DURATION.slow, ease: EASE },
} as const;
