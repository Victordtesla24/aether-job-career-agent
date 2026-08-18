"use client";

/**
 * The "Connect with Anthropic" panel inside the provider-configuration dialog.
 *
 * One panel serves BOTH credential scopes, which differ only in copy, test-id
 * prefix and what the caller's handlers do with the result:
 *
 *  - `deployment` (ML-agents-cred-002, admin-only): the operator authorises,
 *    and the server stores the token deployment-wide. The operator never sees
 *    the token. Owns the needs-reauth / "Renew now" block, passed as children.
 *
 *  - `user` (UPO-1): the customer authorises with their own Claude Pro/Max
 *    account and the minted token is written into the dialog's OAuth-token
 *    field for them to Save. Before this existed a customer had to leave the
 *    app, run `claude setup-token`, and paste the result back by hand.
 *
 * The two sets of test ids are deliberately distinct (`anthropic-oauth-*` vs
 * `anthropic-oauth-user-*`) so the F-01 guard — a customer must never be shown
 * the deployment-wide control, which could only 403 for them — stays
 * structurally enforceable rather than resting on reading the handlers.
 */
import type { ReactNode } from "react";

export type AnthropicOAuthScope = "deployment" | "user";

/** Copy and ids that differ between the two scopes; everything else is shared. */
const VARIANT: Record<
  AnthropicOAuthScope,
  {
    idPrefix: string;
    connect: string;
    connecting: string;
    complete: string;
    completing: string;
    description: string;
    fallback: string;
  }
> = {
  deployment: {
    idPrefix: "anthropic-oauth",
    connect: "Connect with Anthropic (subscription)",
    connecting: "Opening Anthropic…",
    complete: "Finish connecting",
    completing: "Connecting…",
    description:
      "Opens Anthropic's sign-in page in a new tab. Approve access to your Claude Pro/Max account, then paste the one-time code Anthropic shows you. Your token is created on the server — you never copy the token yourself.",
    fallback: "or paste a token manually below (honest fallback)",
  },
  user: {
    idPrefix: "anthropic-oauth-user",
    connect: "Click here for subscription token",
    connecting: "Opening Anthropic…",
    complete: "Get my token",
    completing: "Retrieving…",
    description:
      "Opens Anthropic's sign-in page in a new tab. Approve access with your own Claude Pro/Max account, then paste the one-time code Anthropic shows you. Your subscription token is filled in below automatically — then press Save to store it.",
    fallback: "or paste a token you already have below",
  },
};

export default function AnthropicOAuthPanel({
  scope,
  step,
  code,
  onCodeChange,
  onConnect,
  onComplete,
  busy,
  connecting,
  children,
}: {
  scope: AnthropicOAuthScope;
  /** `await_code` once Anthropic's tab is open and a code can be pasted back. */
  step: "idle" | "await_code";
  code: string;
  onCodeChange: (value: string) => void;
  onConnect: () => void;
  onComplete: () => void;
  /** Any dialog operation is in flight — every control here is disabled. */
  busy: boolean;
  /** This flow specifically is in flight — drives the progress labels. */
  connecting: boolean;
  /** Scope-specific extras rendered above the button (the needs-reauth block). */
  children?: ReactNode;
}) {
  const v = VARIANT[scope];
  return (
    <div className="mb-4 rounded-lg border border-aether-indigo/25 bg-aether-indigo/5 p-3">
      {children}
      <button
        type="button"
        data-testid={`${v.idPrefix}-connect`}
        onClick={onConnect}
        disabled={busy}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-aether-indigo px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-aether-indigo/25 transition hover:opacity-90 disabled:opacity-50"
      >
        <i className="fa-solid fa-arrow-up-right-from-square text-[10px]" aria-hidden="true" />
        {connecting && step === "idle" ? v.connecting : v.connect}
      </button>
      <p className="mt-2 text-[11px] leading-relaxed text-aether-muted">{v.description}</p>
      {/* ML-agents-003 (ADR-ML-5): the authorize URL is the correct
          subscription flow — Anthropic may interpose a brief security check on
          the sign-in page. Set the expectation so it is not read as a broken
          or wrong link. */}
      <p
        data-testid={`${v.idPrefix}-security-hint`}
        className="mt-1.5 flex items-start gap-1.5 text-[10px] leading-relaxed text-aether-muted-dim"
      >
        <i className="fa-solid fa-shield-halved mt-0.5 shrink-0 text-[10px]" aria-hidden="true" />
        <span>
          You may see a brief Anthropic security check — that&apos;s expected;
          complete it to continue.
        </span>
      </p>
      {step === "await_code" ? (
        <div className="mt-3">
          <label
            htmlFor={`${v.idPrefix}-code`}
            className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim"
          >
            Paste the code from Anthropic
          </label>
          <div className="flex items-center gap-2">
            <input
              id={`${v.idPrefix}-code`}
              data-testid={`${v.idPrefix}-code-input`}
              type="text"
              value={code}
              onChange={(e) => onCodeChange(e.target.value)}
              placeholder="code#state"
              autoComplete="off"
              spellCheck={false}
              className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-xs text-white outline-none focus:border-aether-indigo/50"
            />
            <button
              type="button"
              data-testid={`${v.idPrefix}-complete`}
              onClick={onComplete}
              disabled={busy || code.trim() === ""}
              className="shrink-0 rounded-lg bg-aether-indigo px-3 py-2.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
            >
              {connecting ? v.completing : v.complete}
            </button>
          </div>
        </div>
      ) : null}
      <p className="mt-2 text-[10px] text-aether-muted-dim">{v.fallback}</p>
    </div>
  );
}
