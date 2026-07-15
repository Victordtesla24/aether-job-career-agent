"use client";

/**
 * Provider credential configuration modal (wireframe: provider-config-ag21).
 *
 * Replaces the old "edit the server .env" UX (REQ-PC-1): the user enters a
 * provider credential entirely in-app. It writes to the real backend
 * (PUT/DELETE /agents/providers/{id}/credential), tests it end-to-end
 * (POST .../verify), and renders the honest DB-first state returned by the
 * server — source badge + last-4 hint — never a fabricated "connected".
 *
 * Billing separation (REQ-PC-2/3/4) is legible in the copy:
 *  - Anthropic: two auth modes — a Claude subscription token (sk-ant-oat…,
 *    billed to the Anthropic subscription quota) or an API key (sk-ant-api…,
 *    billed to Anthropic API credits).
 *  - OpenRouter: an API key; every non-Anthropic model bills to OpenRouter
 *    credits. Credentials never cross providers.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteProviderCredential,
  putProviderCredential,
  startAnthropicOAuth,
  verifyProvider,
  type Provider,
  type ProviderAuthMode,
} from "./api";
import { providerSourceBadge, type ProviderSourceBadge } from "./logic";
import { providerCredentialErrorNotice, type Notice } from "../../lib/agents-feedback";

interface AuthModeOption {
  value: ProviderAuthMode;
  label: string;
  hint: string;
  placeholder: string;
}

/** The credential shapes a given provider accepts. Anthropic is the only
 * provider with a subscription-vs-key choice; everything else is an API key. */
function authModeOptions(providerId: string): AuthModeOption[] {
  if (providerId === "anthropic") {
    return [
      {
        value: "subscription_oauth",
        label: "Claude subscription (Max/Pro)",
        hint: "Paste a Claude subscription token (starts sk-ant-oat…). Runs on Anthropic models draw from your Claude subscription quota.",
        placeholder: "sk-ant-oat…",
      },
      {
        value: "api_key",
        label: "API key",
        hint: "Paste an Anthropic API key (starts sk-ant-api…). Runs on Anthropic models bill to your Anthropic API credits.",
        placeholder: "sk-ant-api…",
      },
    ];
  }
  return [
    {
      value: "api_key",
      label: "API key",
      hint: "Paste this provider's API key. It is stored encrypted and never shown again — only the last 4 characters.",
      placeholder: "Paste API key",
    },
  ];
}

/** Short, accurate billing implication — the whole point of the feature. */
function billingNote(providerId: string): string {
  if (providerId === "anthropic") {
    return "Anthropic models bill to your Anthropic account (subscription quota or API credits, per the mode above). Every non-Anthropic model bills to OpenRouter — credentials never cross providers.";
  }
  if (providerId === "openrouter") {
    return "Every non-Anthropic model across Aether bills to your OpenRouter credits. Anthropic models never route through OpenRouter.";
  }
  return "Stored encrypted and used only for this provider's models. Anthropic-billed and OpenRouter-billed traffic never cross.";
}

const BADGE_CLS: Record<ProviderSourceBadge["tone"], string> = {
  saved: "border-aether-green/25 bg-aether-green/10 text-aether-green",
  env: "border-aether-amber/25 bg-aether-amber/10 text-aether-amber",
  none: "border-white/10 bg-white/5 text-aether-muted-dim",
};

export default function ProviderConfigModal({
  provider,
  onClose,
  onSaved,
  onNotice,
}: {
  provider: Provider | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
  onNotice: (notice: Notice) => void;
}) {
  const open = provider !== null;
  const providerId = provider?.id ?? null;

  const [view, setView] = useState<Provider | null>(provider);
  const [mode, setMode] = useState<ProviderAuthMode>("api_key");
  const [secret, setSecret] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState<"saving" | "removing" | "verifying" | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Re-seed local state whenever a (different) provider is opened.
  useEffect(() => {
    if (!provider) return;
    setView(provider);
    const opts = authModeOptions(provider.id);
    setMode(provider.authMode ?? opts[0].value);
    setSecret("");
    setReveal(false);
    setError(null);
    setBusy(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerId]);

  // Move focus into the dialog on open and restore it to the trigger on close.
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<Element | null>(null);
  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement;
      const t = setTimeout(() => inputRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
    if (triggerRef.current instanceof HTMLElement) triggerRef.current.focus();
    return undefined;
  }, [open]);

  // Document-level Escape so the dialog closes regardless of focus position.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], select, input, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [onClose],
  );

  if (!open || !view) return null;

  const options = authModeOptions(view.id);
  const active = options.find((o) => o.value === mode) ?? options[0];
  const badge = providerSourceBadge(view);
  const hasStoredCredential = view.source === "database";
  const canVerify =
    view.source === "database" || view.source === "environment" || view.status === "connected";

  const save = async () => {
    const trimmed = secret.trim();
    if (!trimmed || busy) return;
    setBusy("saving");
    setError(null);
    onNotice({ kind: "info", text: `Saving ${view.name} credential…` });
    try {
      const updated = await putProviderCredential(view.id, { authMode: mode, secret: trimmed });
      setView((v) => (v ? { ...v, ...updated } : updated));
      setSecret("");
      onNotice({
        kind: "success",
        text: `${view.name} credential saved${updated.secretHint ? ` (${updated.secretHint})` : ""}. Test the connection to confirm it works.`,
      });
      await onSaved();
    } catch (e) {
      onNotice(providerCredentialErrorNotice(e, `Saving ${view.name} credential`));
      setError(e instanceof Error ? e.message.slice(0, 160) : "Save failed");
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (busy) return;
    setBusy("removing");
    setError(null);
    try {
      const updated = await deleteProviderCredential(view.id);
      setView((v) => (v ? { ...v, ...updated } : updated));
      setSecret("");
      onNotice({
        kind: "info",
        text: `${view.name} credential removed${
          updated.source === "environment"
            ? " — falling back to the server environment credential."
            : "."
        }`,
      });
      await onSaved();
    } catch (e) {
      onNotice(providerCredentialErrorNotice(e, `Removing ${view.name} credential`));
      setError(e instanceof Error ? e.message.slice(0, 160) : "Remove failed");
    } finally {
      setBusy(null);
    }
  };

  // GAP-D1: one-click Anthropic subscription connect (OAuth PKCE). Redirects to
  // the claude.ai consent screen; the callback stores the token server-side.
  const connectOAuth = async () => {
    if (busy) return;
    setBusy("saving");
    setError(null);
    onNotice({
      kind: "info",
      text: "Redirecting to Anthropic to connect your Claude subscription…",
    });
    try {
      const { authorizeUrl } = await startAnthropicOAuth();
      window.location.href = authorizeUrl;
    } catch (e) {
      onNotice(providerCredentialErrorNotice(e, "Starting Anthropic OAuth"));
      setError(
        e instanceof Error
          ? e.message.slice(0, 160)
          : "Anthropic OAuth is not available.",
      );
      setBusy(null);
    }
  };

  const verify = async () => {
    if (busy) return;
    setBusy("verifying");
    setError(null);
    onNotice({ kind: "info", text: `Testing ${view.name} connection…` });
    try {
      const res = await verifyProvider(view.id);
      onNotice({
        kind: res.ok ? "success" : "error",
        text: `${view.name} connection ${res.ok ? "ok" : "failed"} — ${res.detail}`,
      });
      await onSaved();
    } catch (e) {
      onNotice(providerCredentialErrorNotice(e, `Testing ${view.name} connection`));
      setError(e instanceof Error ? e.message.slice(0, 160) : "Verify failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      data-testid="provider-config-modal"
      onKeyDown={handleKey}
    >
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        data-testid="provider-config-backdrop"
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="provider-config-title"
        className="glass-raised relative w-full max-w-lg rounded-2xl border border-aether-indigo/40 p-6 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
              style={{ backgroundColor: view.color }}
            >
              <i className={`fa-solid ${view.icon} text-sm text-white`} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h3 id="provider-config-title" className="truncate text-sm font-semibold">
                Configure {view.name}
              </h3>
              <p className="text-[11px] text-aether-muted-dim">
                Credentials are stored encrypted on the server — enter them here, no{" "}
                <code className="font-mono">.env</code> editing.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            data-testid="provider-config-close"
            aria-label="Close provider configuration dialog"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 transition hover:bg-white/10"
          >
            <i className="fa-solid fa-xmark text-xs text-aether-muted" aria-hidden="true" />
          </button>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span
            data-testid="provider-config-source"
            className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${BADGE_CLS[badge.tone]}`}
          >
            {badge.label}
          </span>
          {view.secretHint ? (
            <span
              data-testid="provider-config-hint"
              className="font-mono text-[10px] text-aether-muted"
            >
              Ends {view.secretHint}
            </span>
          ) : null}
          {view.lastVerifyStatus ? (
            <span
              className={`text-[10px] ${
                view.lastVerifyStatus === "ok" ? "text-aether-green" : "text-red-300"
              }`}
            >
              Last test: {view.lastVerifyStatus === "ok" ? "passed" : "failed"}
              {view.lastVerifiedAt
                ? ` · ${new Date(view.lastVerifiedAt).toLocaleString()}`
                : ""}
            </span>
          ) : null}
        </div>

        {options.length > 1 ? (
          <fieldset className="mb-4">
            <legend className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim">
              Authentication mode
            </legend>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {options.map((opt) => (
                <label
                  key={opt.value}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2.5 text-xs transition ${
                    mode === opt.value
                      ? "border-aether-indigo/40 bg-aether-indigo/10 text-white"
                      : "border-white/10 bg-white/5 text-aether-muted hover:bg-white/10"
                  }`}
                >
                  <input
                    type="radio"
                    name="provider-authmode"
                    value={opt.value}
                    checked={mode === opt.value}
                    onChange={() => setMode(opt.value)}
                    data-testid={`authmode-${opt.value}`}
                    className="accent-aether-indigo"
                  />
                  <span className="font-medium">{opt.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}

        {view.id === "anthropic" && mode === "subscription_oauth" ? (
          <div
            data-testid="anthropic-oauth-connect-block"
            className="mb-4 rounded-lg border border-aether-coral/25 bg-aether-coral/5 p-3"
          >
            <button
              type="button"
              onClick={() => void connectOAuth()}
              disabled={busy !== null}
              data-testid="anthropic-oauth-connect"
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-aether-coral px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-aether-coral/25 transition hover:opacity-90 disabled:opacity-50"
            >
              <i className="fa-solid fa-link text-[10px]" aria-hidden="true" />
              {busy === "saving" ? "Connecting…" : "Connect with Anthropic"}
            </button>
            <p className="mt-2 text-[11px] leading-relaxed text-aether-muted">
              One-click connect with your Claude subscription — no token to copy.
              Or paste a subscription token below if you already have one.
            </p>
          </div>
        ) : null}

        <label
          htmlFor="provider-secret"
          className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim"
        >
          {active.label}
        </label>
        <div className="relative mb-1.5">
          <input
            id="provider-secret"
            ref={inputRef}
            data-testid="provider-secret-input"
            type={reveal ? "text" : "password"}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder={active.placeholder}
            autoComplete="off"
            spellCheck={false}
            className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 pr-16 text-xs text-white outline-none focus:border-aether-indigo/50"
          />
          <button
            type="button"
            onClick={() => setReveal((r) => !r)}
            data-testid="provider-secret-reveal"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[10px] font-medium text-aether-muted transition hover:bg-white/10"
          >
            {reveal ? "Hide" : "Show"}
          </button>
        </div>
        <p className="mb-3 text-[11px] leading-relaxed text-aether-muted">{active.hint}</p>

        <p
          data-testid="provider-config-billing"
          className="mb-4 rounded-lg border border-aether-indigo/20 bg-aether-indigo/5 p-2.5 text-[11px] leading-relaxed text-aether-muted"
        >
          <i className="fa-solid fa-scale-balanced mr-1.5 text-aether-indigo" aria-hidden="true" />
          {billingNote(view.id)}
        </p>

        {error ? (
          <p
            role="alert"
            data-testid="provider-config-error"
            className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-[11px] text-red-300"
          >
            {error}
          </p>
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <div className="flex shrink-0 items-center gap-2">
            {hasStoredCredential ? (
              <button
                type="button"
                onClick={() => void remove()}
                disabled={busy !== null}
                data-testid="provider-config-remove"
                className="rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-xs font-medium text-red-300 transition hover:bg-red-500/20 disabled:opacity-50"
              >
                {busy === "removing" ? "Removing…" : "Remove"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => void verify()}
              disabled={busy !== null || !canVerify}
              data-testid="provider-config-verify"
              title={canVerify ? undefined : "Save a credential first, then test it."}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium transition hover:bg-white/10 disabled:opacity-50"
            >
              {busy === "verifying" ? "Testing…" : "Test connection"}
            </button>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              data-testid="provider-config-cancel"
              className="rounded-lg border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-medium transition hover:bg-white/10"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy !== null || secret.trim() === ""}
              data-testid="provider-config-save"
              className="flex items-center gap-2 rounded-lg bg-aether-indigo px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-aether-indigo/25 transition hover:opacity-90 disabled:opacity-50"
            >
              <i className="fa-solid fa-floppy-disk text-[10px]" aria-hidden="true" />
              {busy === "saving" ? "Saving…" : "Save credential"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
