"use client";

/**
 * ADMIN-2.0 FE-2 — the small set of controls the management surfaces share.
 *
 * These exist so the four screens FE-2 adds (add-user, the billing panel, sales
 * agents, promos) speak ONE language rather than four dialects of it, and so the
 * honesty rules below are implemented once instead of being re-argued per page:
 *
 * * `StatusPill` encodes state in FORM as well as colour — the label is a word,
 *   so the state survives a monochrome screenshot, a colour-blind reader and a
 *   low-contrast display. Semantic tones (good / warn / critical) are kept
 *   distinct from the brand accent, so "this is the primary action" and "this is
 *   healthy" never collide.
 *
 * * `CopyButton` reports what actually happened. A clipboard write can be denied
 *   (permissions, insecure context, an embedded frame), and the app's older copy
 *   affordance says "Copied" regardless — harmless for a story snippet, not
 *   harmless for a one-time password an admin then closes the dialog on. So a
 *   failure says so and points at the value, which stays selectable on screen.
 *
 * * `ConfirmPanel` is an in-page confirmation rather than `window.confirm`: it
 *   can state consequences in full ("this makes no Stripe call", "the redemption
 *   history survives"), it is styled with the rest of the product, and it is
 *   reachable by the same tests that exercise the action behind it.
 */
import { useCallback, useState, type ReactNode } from "react";

// The card surface is FE-1's, not a second one: re-exported here so the
// management screens import their whole vocabulary from one place.
export { Panel } from "./executive/panels";

// --------------------------------------------------------------------------- //
// Control surfaces (matching the certified S-UI B1/B2/B3 language)
// --------------------------------------------------------------------------- //

export const FIELD =
  "w-full rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text placeholder:text-aether-muted-dim focus:border-aether-indigo/50 focus:outline-none";
export const PRIMARY_BTN =
  "rounded-md bg-aether-indigo px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-aether-indigo/90 disabled:cursor-not-allowed disabled:opacity-50";
export const QUIET_BTN =
  "rounded-md border border-white/15 px-4 py-2 text-sm font-medium text-aether-muted transition-colors hover:border-white/30 hover:text-white disabled:cursor-not-allowed disabled:opacity-50";
export const DANGER_BTN =
  "rounded-md bg-red-500/20 px-4 py-2 text-sm font-medium text-red-300 transition-colors hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50";

export type StatusTone = "good" | "warn" | "critical" | "neutral" | "accent";

const PILL_TONE: Record<StatusTone, string> = {
  good: "border-aether-green/30 bg-aether-green/10 text-aether-green",
  warn: "border-aether-amber/40 bg-aether-amber/10 text-aether-amber",
  critical: "border-red-500/40 bg-red-500/10 text-red-300",
  neutral: "border-white/15 bg-white/[0.04] text-aether-muted",
  accent: "border-aether-indigo/40 bg-aether-indigo/10 text-aether-indigo",
};

export function StatusPill({
  tone = "neutral",
  children,
  testId,
  title,
  state,
}: {
  tone?: StatusTone;
  children: ReactNode;
  testId?: string;
  title?: string;
  /** Mirrored to `data-state` so a reviewer can assert the verdict from the DOM. */
  state?: string;
}) {
  return (
    <span
      data-testid={testId}
      data-state={state}
      data-tone={tone}
      title={title}
      className={`type-mono-micro inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 font-semibold uppercase tracking-wide ${PILL_TONE[tone]}`}
    >
      {children}
    </span>
  );
}

/** A label/value pair for the scannable summary rows. Figures are tabular. */
export function StatTile({
  label,
  value,
  hint,
  testId,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  testId?: string;
  tone?: StatusTone;
}) {
  return (
    <div data-testid={testId} className="elev-1 min-w-0 rounded-2xl p-4">
      <p className="type-section truncate" title={label}>
        {label}
      </p>
      <p
        className={`mono mt-2 text-[24px] font-semibold leading-none tracking-[-0.02em] tabular-nums ${
          tone === "warn"
            ? "text-aether-amber"
            : tone === "critical"
              ? "text-red-300"
              : "text-aether-text"
        }`}
      >
        {value}
      </p>
      {hint ? <p className="type-meta mt-2">{hint}</p> : null}
    </div>
  );
}

/**
 * Copy `value` to the clipboard and say honestly whether that worked.
 *
 * The three states are distinct on purpose: idle, a confirmed copy, and a
 * REFUSED copy that tells the reader to select the value by hand. Nothing here
 * claims a copy it did not make.
 */
export function CopyButton({
  value,
  label = "Copy",
  testId,
  ariaLabel,
  className,
}: {
  value: string;
  label?: string;
  testId?: string;
  ariaLabel?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
      return;
    }
    window.setTimeout(() => setState("idle"), 1800);
  }, [value]);

  return (
    <button
      type="button"
      data-testid={testId}
      aria-label={ariaLabel ?? `${label} ${value}`}
      onClick={() => void copy()}
      className={
        className ??
        "type-mono-micro rounded-md border border-white/15 px-2 py-1 text-aether-muted transition-colors hover:border-white/30 hover:text-white"
      }
    >
      {state === "copied"
        ? "Copied"
        : state === "failed"
          ? "Couldn't copy — select it manually"
          : label}
    </button>
  );
}

/**
 * An in-page confirmation. `body` carries the consequences in full — that is
 * the whole reason this is not `window.confirm`.
 */
export function ConfirmPanel({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  busy,
  testId,
  confirmTestId,
  cancelTestId,
  tone = "warn",
  confirmDisabled,
  children,
}: {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
  testId?: string;
  confirmTestId?: string;
  cancelTestId?: string;
  tone?: "warn" | "critical";
  confirmDisabled?: boolean;
  /** Extra controls the confirmation itself requires (e.g. a typed email). */
  children?: ReactNode;
}) {
  return (
    <div
      data-testid={testId}
      role="group"
      aria-label={title}
      className={`mt-3 rounded-xl border p-3 ${
        tone === "critical"
          ? "border-red-500/40 bg-red-500/[0.06]"
          : "border-aether-amber/40 bg-aether-amber/[0.06]"
      }`}
    >
      <p className="text-[13px] font-medium text-aether-text">{title}</p>
      <div className="type-meta mt-1.5 max-w-prose">{body}</div>
      {children}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          data-testid={confirmTestId}
          onClick={onConfirm}
          disabled={busy || confirmDisabled}
          className={tone === "critical" ? DANGER_BTN : PRIMARY_BTN}
        >
          {confirmLabel}
        </button>
        <button
          type="button"
          data-testid={cancelTestId}
          onClick={onCancel}
          disabled={busy}
          className={QUIET_BTN}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/**
 * Money, to the cent, marked A$.
 *
 * The currency marker is not decoration: this admin surface shows AUD revenue
 * beside USD LLM spend, and a bare "$" in either column is genuinely ambiguous.
 * `narrowSymbol` renders AUD as a plain "$" in en-AU, so the prefix is restored
 * here — including on a negative, where the sign precedes the symbol and a naive
 * anchor would silently leave "-$" unmarked.
 *
 * An absent figure is an em dash, never 0: this function is fed nullable API
 * fields, and a fabricated zero in a money column is a lie about the account.
 */
export function formatAudExact(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) return "—";
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
    .format(amount)
    .replace(/^(-?)\$/, (_match, sign: string) => `${sign}A$`);
}
