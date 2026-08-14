/**
 * S-UI B2 — the work-surface recipes.
 *
 * WHY THIS FILE EXISTS. B0 gave the app a token set and B1 gave it a chart kit,
 * but the three work surfaces (Jobs, Applications, Approvals) still composed
 * every card, chip and button from a bespoke ternary written at the call site.
 * The result is what the audit called "one card style everywhere, and none of
 * them the same" — the shells looked alike but their padding, radius, border
 * and hover state all drifted a few pixels apart, which is exactly the thing a
 * neutral eye reads as "unfinished" (reference-pack rule 15: the shell stays
 * uniform, density and colour carry the hierarchy).
 *
 * These are `tailwind-variants` recipes (MIT, one runtime dep, `tailwind-merge`
 * is an OPTIONAL peer and is deliberately NOT installed — v3 ships its own
 * conflict resolution, so the adoption costs exactly one package). They REPLACE
 * hand-written class ternaries; every recipe below has at least two call sites
 * across the B2 pages, which is the bar for putting it here rather than inline.
 *
 * Honesty note: nothing in this file decides a *tone*. `state-neutral` vs
 * `state-ok` remains a decision made at the call site from real data — a recipe
 * that guessed a tone would be a colour lying about a measurement (Rule D-1).
 */
import { tv } from "tailwind-variants";

/**
 * The one row/card shell for a selectable list item.
 *
 * `selected` is the certified selection language: `elev-2` fill + a coral left
 * rail (drawn by the caller with `layoutId` where motion is wanted), never a
 * saturated background wash.
 */
export const listCard = tv({
  base:
    "relative w-full overflow-hidden rounded-xl border p-3.5 text-left transition-colors duration-[--dur-fast] " +
    "focus-within:border-hairline-strong",
  variants: {
    selected: {
      true: "elev-2 border-aether-coral/45",
      false: "elev-1 border-hairline hover:border-hairline-strong hover:bg-surface-3/40",
    },
    interactive: {
      true: "cursor-pointer",
      false: "",
    },
  },
  defaultVariants: { selected: false, interactive: true },
});

/**
 * A metadata chip: source badge, freshness stamp, stage marker.
 *
 * `tone` maps 1:1 onto the state palette. `neutral` is the default because an
 * unqualified chip must never borrow a semantic colour it did not earn.
 */
export const chip = tv({
  base:
    "inline-flex min-w-0 shrink-0 items-center gap-1.5 rounded-md border px-1.5 py-0.5 " +
    "text-[10px] font-medium leading-[1.4]",
  variants: {
    tone: {
      neutral: "border-hairline bg-white/[0.04] text-aether-muted",
      ok: "border-state-ok/25 bg-state-ok/[0.10] text-state-ok",
      warn: "border-state-warn/25 bg-state-warn/[0.10] text-state-warn",
      danger: "border-state-danger/25 bg-state-danger/[0.10] text-state-danger",
      info: "border-state-info/25 bg-state-info/[0.10] text-state-info",
      accent: "border-aether-coral/30 bg-aether-coral/[0.12] text-aether-coral",
      /** Rule D-1: "not measured" is its own colour, never ok and never error. */
      degraded: "border-state-degraded/25 bg-state-degraded/[0.10] text-state-degraded",
    },
    mono: { true: "mono", false: "" },
  },
  defaultVariants: { tone: "neutral", mono: false },
});

/**
 * Buttons. `primary` is the ONE coral fill a surface is allowed; `equal` exists
 * because §5.5 requires Approve and Reject to carry the SAME visual weight —
 * approval must not be the cheaper click.
 */
export const button = tv({
  base:
    "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-semibold " +
    "outline-none transition-colors duration-[--dur-fast] " +
    "focus-visible:ring-2 focus-visible:ring-aether-coral/70 " +
    "disabled:cursor-not-allowed disabled:opacity-45",
  variants: {
    tone: {
      primary: "bg-aether-coral hover:opacity-90 active:translate-y-px",
      neutral:
        "elev-1 border-hairline text-aether-text hover:border-hairline-strong hover:bg-surface-3",
      quiet: "text-aether-muted hover:bg-white/[0.06] hover:text-aether-text",
      ok: "border border-state-ok/40 bg-state-ok/[0.12] text-state-ok hover:bg-state-ok/20",
      danger:
        "border border-state-danger/40 bg-state-danger/[0.10] text-state-danger hover:bg-state-danger/20",
      warn: "border border-state-warn/40 bg-state-warn/[0.10] text-state-warn hover:bg-state-warn/20",
      info: "border border-state-info/40 bg-state-info/[0.10] text-state-info hover:bg-state-info/20",
    },
    size: {
      xs: "px-2.5 py-1 text-[11px]",
      sm: "px-3 py-1.5 text-xs",
      md: "px-4 py-2 text-sm",
    },
  },
  defaultVariants: { tone: "neutral", size: "sm" },
});

/**
 * A scroll-contained column body (D-ε: "the page ends" — everything else
 * scrolls inside a container). `overscroll-contain` stops a column's scroll
 * from chaining into the page once it bottoms out, which is what made the
 * kanban feel like quicksand at 390px.
 */
export const scrollBody = tv({
  base: "min-h-0 overflow-y-auto overscroll-contain pr-1",
});
