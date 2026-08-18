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
 *  - Anthropic: the credential that SERVES Claude runs is the Claude
 *    subscription token (sk-ant-oat…), which draws the Claude Pro/Max
 *    subscription quota. An API key (sk-ant-api…) is still storable and
 *    verifiable but does NOT serve Claude runs — MODEL-SUB-QUOTA (OWNER
 *    DIRECTIVE 2026-08-17) makes every Claude model subscription-only, so the
 *    copy says so instead of promising metered billing that never happens.
 *  - OpenRouter: an API key; every non-Anthropic model bills to OpenRouter
 *    credits. Credentials never cross providers.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteProviderCredential,
  deleteUserProviderCredential,
  exchangeAnthropicOAuth,
  exchangeUserAnthropicOAuth,
  exchangeUserProviderOAuth,
  listUserCredentials,
  putProviderCredential,
  putUserProviderCredential,
  refreshAnthropicOAuth,
  startAnthropicOAuth,
  startUserAnthropicOAuth,
  startUserProviderOAuth,
  supportsUserOAuthConnect,
  verifyProvider,
  verifyUserProvider,
  type Provider,
  type ProviderAuthMode,
} from "./api";
import AnthropicOAuthPanel from "./AnthropicOAuthPanel";
import { normalizeCredentialSecret, providerSourceBadge, type ProviderSourceBadge } from "./logic";
import {
  extractApiJsonDetail,
  providerCredentialErrorNotice,
  type Notice,
} from "../../lib/agents-feedback";

interface AuthModeOption {
  value: ProviderAuthMode;
  label: string;
  hint: string;
  placeholder: string;
}

/** The credential shape a given provider accepts. Every provider — Anthropic
 * included — takes an API key. Anthropic also accepts a Claude Code OAuth
 * token (sk-ant-oat01-…): customers mint one in-app via Click here for
 * subscription token (UPO-1); operators use the deployment Connect flow.
 * Manual paste remains an honest fallback. Only the OAuth token serves
 * Claude runs (MODEL-SUB-QUOTA). */
function authModeOptions(providerId: string): AuthModeOption[] {
  if (providerId === "anthropic") {
    return [
      {
        value: "api_key",
        label: "API key",
        hint: "Paste an Anthropic API key (starts sk-ant-api…). Note: Claude models are served by the Claude subscription token below, so an API key alone will not run them.",
        placeholder: "sk-ant-api…",
      },
      {
        value: "oauth_token",
        label: "Claude Code OAuth Token",
        hint: "Use Click here for subscription token above, or paste a token from `claude setup-token` (starts sk-ant-oat01-…). Runs on Anthropic models bill against your Claude Pro/Max subscription quota.",
        placeholder: "sk-ant-oat01-…",
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

/**
 * Human-readable text for the modal's own inline error slot (P3-2,
 * RUN-20260818T0223Z third-party adversarial review). Never the raw
 * `METHOD /path failed (status): {json}` string `apiRequest` embeds in
 * `Error.message` — that is an internal route path and JSON error shape, not
 * something a customer should read, and it duplicated (less honestly than)
 * the friendly banner `providerCredentialErrorNotice` already renders one
 * line above it.
 *
 * Review finding #1 (`14-p3-review.md`, RUN-20260818T0223Z): the first
 * version of this helper used `extractApiDetail`, whose documented raw-
 * message fallback still returned the whole raw string — including the real
 * internal route path — for any error body that wasn't precisely
 * `{"detail": "<string>"}` JSON. Reproduced live for two realistic shapes:
 * an unhandled 500 (Starlette's plain-text default body — `apps/api/app/
 * main.py` registers no generic exception handler) and a Pydantic
 * `RequestValidationError` 422 (`detail` is an array, not a string). This
 * helper now uses the STRICT `extractApiJsonDetail`, which returns a real
 * backend detail or `null` — never a raw echo — so every other case falls
 * through to the caller's own bounded, generic `fallback` string (e.g.
 * "Save failed") instead of any internal implementation detail.
 */
function inlineErrorMessage(e: unknown, fallback: string): string {
  return (extractApiJsonDetail(e) ?? fallback).slice(0, 160);
}

/** Short, accurate billing implication — the whole point of the feature. */
function billingNote(providerId: string): string {
  if (providerId === "anthropic") {
    return "Claude models run on your Claude Pro/Max subscription quota (Claude Code OAuth token) — never on Anthropic API credits and never through OpenRouter, in either spelling of the model id. Every non-Claude model bills to OpenRouter; credentials never cross providers.";
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

/**
 * Fold a per-user credential row into the provider card's view model.
 *
 * The two stores answer with different shapes: the deployment endpoints return
 * a full provider row (mergeable as-is), while the per-user endpoints return a
 * `UserCredential` whose `id` is the CREDENTIAL row's id — spreading it whole
 * would silently overwrite the provider's own `id` and point every subsequent
 * call at a nonexistent provider. So copy only the credential-derived fields.
 * `detail` is deliberately not synthesised here: the parent's `onSaved()`
 * refetch supplies the server's own honest wording.
 */
function withUserCredential(
  view: Provider,
  cred: { authMode?: string | null; secretHint?: string | null; lastVerifiedAt?: string | null; lastVerifyStatus?: "ok" | "failed" | null },
): Provider {
  const stored = Boolean(cred.secretHint);
  return {
    ...view,
    source: stored ? "database" : "none",
    status: stored ? (cred.lastVerifyStatus === "failed" ? "warning" : "connected") : "unconfigured",
    authMode: (cred.authMode as Provider["authMode"]) ?? null,
    secretHint: cred.secretHint ?? null,
    lastVerifiedAt: cred.lastVerifiedAt ?? null,
    lastVerifyStatus: cred.lastVerifyStatus ?? null,
    needsReauth: false,
  };
}

/**
 * Which credential store this dialog writes (F-01 /
 * ADR-F01-PROVIDER-CREDENTIAL-AUTHZ):
 *  - `"deployment"` — the operator's shared store (`/agents/providers/...`),
 *    admin-only on the server. The historical default.
 *  - `"user"` — the signed-in customer's OWN store
 *    (`/agents/user/providers/...`), which bills that customer's own account.
 */
export type ProviderConfigScope = "deployment" | "user";

export default function ProviderConfigModal({
  provider,
  onClose,
  onSaved,
  onNotice,
  scope = "deployment",
}: {
  provider: Provider | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
  onNotice: (notice: Notice) => void;
  scope?: ProviderConfigScope;
}) {
  const open = provider !== null;
  const userScope = scope === "user";

  const [view, setView] = useState<Provider | null>(provider);
  const [mode, setMode] = useState<ProviderAuthMode>("api_key");
  const [secret, setSecret] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState<
    "saving" | "removing" | "verifying" | "connecting" | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  // Connect-with-Anthropic (ML-agents-cred-002 deployment scope; UPO-1 mint
  // in user scope): "idle" until Connect is clicked, then "await_code" while
  // the code#state Anthropic showed is pasted back. Only the short-lived
  // code lives in component state — never a token.
  const [oauthStep, setOauthStep] = useState<"idle" | "await_code">("idle");
  const [oauthCode, setOauthCode] = useState("");
  // GAP-PROVIDER-OAUTH-1's generic per-user Connect gets its OWN step/code
  // state, deliberately separate from the mint flow's above (RUN-20260818T0223Z
  // merge decision — see docs/delivery/evidence/RUN-20260818T0223Z/
  // FEAT-PROVIDER/09-deploy-merge-resolution.md): both controls can be shown
  // together for Anthropic in user scope (UPO-1's mint-then-Save vs.
  // GAP-PROVIDER-OAUTH-1's single-click auto-persisted connect), and sharing
  // one `oauthStep` would flip BOTH panels into their paste-back UI whichever
  // one the customer actually clicked — a real, user-visible bug, not just a
  // cosmetic one.
  const [userOauthStep, setUserOauthStep] = useState<"idle" | "await_code">("idle");
  const [userOauthCode, setUserOauthCode] = useState("");

  // Re-seed local state whenever a (different) provider is opened. The parent
  // only ever swaps in a new `provider` object reference when the user opens
  // a genuinely different provider (or closes the dialog, passing null) — it
  // never mutates the object in place — so depending on the object itself
  // (rather than just its id) reruns this exactly when intended, with no
  // extra renders and no risk of looping.
  useEffect(() => {
    if (!provider) return;
    setView(provider);
    const opts = authModeOptions(provider.id);
    setMode(provider.authMode ?? opts[0].value);
    setSecret("");
    setReveal(false);
    setError(null);
    setBusy(null);
    setOauthStep("idle");
    setOauthCode("");
    setUserOauthStep("idle");
    setUserOauthCode("");
  }, [provider]);

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

  // GAP-PROVIDER-OAUTH-1 (app_callback auto-return): the popup window opened
  // by connectUserProviderOAuth lands on our own server's oauth/callback
  // page, which posts {source:"aether-oauth", provider, connected} back to
  // window.opener and closes itself — NEVER a token, only the honest
  // connected/not-connected status. Origin-checked so no other tab/site can
  // spoof a "connected" result into this modal.
  useEffect(() => {
    if (!open || !userScope) return undefined;
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as
        | { source?: string; provider?: string; connected?: boolean }
        | null
        | undefined;
      if (!data || data.source !== "aether-oauth") return;
      if (!view || data.provider !== view.id) return;
      setUserOauthStep("idle");
      setBusy(null);
      if (data.connected) {
        onNotice({ kind: "success", text: `${view.name} connected.` });
        void (async () => {
          try {
            const creds = await listUserCredentials();
            const mine = creds.find((c) => c.provider === view.id);
            if (mine) setView((v) => (v ? withUserCredential(v, mine) : v));
          } catch {
            /* best-effort refresh — onSaved() below still runs */
          }
          await onSaved();
        })();
      } else {
        onNotice({
          kind: "error",
          text: `${view.name} connection did not complete. Try again.`,
        });
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [open, userScope, view, onNotice, onSaved]);

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
  // ML-agents-cred-002 (ADR-ML-2a DECISION-1b): the Anthropic subscription OAuth
  // session was marked needs_reauth (auto-refresh failed / token revoked) — show
  // the Reconnect / Renew affordance. The server demotes status to "warning", so
  // treat an oauth_token credential in "warning" as needs_reauth too.
  const anthropicNeedsReauth =
    view.id === "anthropic" &&
    (view.needsReauth === true ||
      (view.status === "warning" && view.authMode === "oauth_token"));
  const canVerify =
    view.source === "database" || view.source === "environment" || view.status === "connected";

  const save = async () => {
    const trimmed = normalizeCredentialSecret(secret);
    if (!trimmed || busy) return;
    setBusy("saving");
    setError(null);
    onNotice({ kind: "info", text: `Saving ${view.name} credential…` });
    try {
      const updated = userScope
        ? withUserCredential(
            view,
            await putUserProviderCredential(view.id, { authMode: mode, secret: trimmed }),
          )
        : await putProviderCredential(view.id, { authMode: mode, secret: trimmed });
      setView((v) => (v ? { ...v, ...updated } : updated));
      setSecret("");
      onNotice({
        kind: "success",
        text: `${view.name} credential saved${updated.secretHint ? ` (${updated.secretHint})` : ""}. Test the connection to confirm it works.`,
      });
      await onSaved();
    } catch (e) {
      onNotice(providerCredentialErrorNotice(e, `Saving ${view.name} credential`));
      setError(inlineErrorMessage(e, "Save failed"));
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (busy) return;
    setBusy("removing");
    setError(null);
    try {
      const updated = userScope
        ? withUserCredential(view, await deleteUserProviderCredential(view.id))
        : await deleteProviderCredential(view.id);
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
      setError(inlineErrorMessage(e, "Remove failed"));
    } finally {
      setBusy(null);
    }
  };

  // Connect-with-Anthropic step 1: mint the authorize URL server-side and open
  // Anthropic's OWN sign-in page in a new tab, then reveal the paste-back field.
  // Shared catch/finally for the two Connect-with-Anthropic steps (DEDUP-026):
  // identical error notice/context and busy reset, distinct happy paths.
  const runConnect = async (fn: () => Promise<void>) => {
    try {
      await fn();
    } catch (e) {
      onNotice(providerCredentialErrorNotice(e, `Connecting ${view.name}`));
      setError(inlineErrorMessage(e, "Connect failed"));
    } finally {
      setBusy(null);
    }
  };

  const connectAnthropic = async () => {
    if (busy) return;
    setBusy("connecting");
    setError(null);
    onNotice({ kind: "info", text: "Opening Anthropic sign-in in a new tab…" });
    await runConnect(async () => {
      const { authorizeUrl } = userScope
        ? await startUserAnthropicOAuth()
        : await startAnthropicOAuth();
      window.open(authorizeUrl, "_blank", "noopener");
      if (userScope) setMode("oauth_token");
      setOauthStep("await_code");
    });
  };

  // Connect-with-Anthropic step 2. The raw code is cleared once submitted.
  // Deployment: the server stores the token and we refresh the masked view.
  // User (UPO-1): the server stored nothing and handed the token back, so we
  // put it in the secret field. Save remains the only write path.
  const completeAnthropic = async () => {
    const code = oauthCode.trim();
    if (!code || busy) return;
    setBusy("connecting");
    setError(null);
    onNotice({ kind: "info", text: `Retrieving your ${view.name} subscription token…` });
    await runConnect(async () => {
      if (userScope) {
        const minted = await exchangeUserAnthropicOAuth(code);
        setMode("oauth_token");
        setSecret(minted.token);
        setOauthCode("");
        setOauthStep("idle");
        onNotice({
          kind: "success",
          text: `${view.name} subscription token retrieved${
            minted.secretHint ? ` (${minted.secretHint})` : ""
          }. Press Save to store it.`,
        });
        return;
      }
      const updated = await exchangeAnthropicOAuth(code);
      setView((v) => (v ? { ...v, ...updated } : updated));
      setOauthCode("");
      setOauthStep("idle");
      onNotice({
        kind: "success",
        text: `${view.name} connected${updated.secretHint ? ` (${updated.secretHint})` : ""}.`,
      });
      await onSaved();
    });
  };

  // Connect-with-Anthropic renew: rotate the stored subscription session via the
  // /oauth/refresh endpoint (ADR-ML-2a DECISION-1b — needs_reauth recovery). An
  // honest failure surfaces the server's message; it never fakes a green badge.
  const renewAnthropic = async () => {
    if (busy) return;
    setBusy("connecting");
    setError(null);
    onNotice({ kind: "info", text: `Renewing ${view.name} session…` });
    try {
      const updated = await refreshAnthropicOAuth();
      setView((v) => (v ? { ...v, ...updated } : updated));
      onNotice({ kind: "success", text: `${view.name} subscription session renewed.` });
      await onSaved();
    } catch (e) {
      onNotice(providerCredentialErrorNotice(e, `Renewing ${view.name} session`));
      setError(inlineErrorMessage(e, "Renew failed"));
    } finally {
      setBusy(null);
    }
  };

  // GAP-PROVIDER-OAUTH-1: begin THIS user's own OAuth connect. Opens a BLANK
  // popup synchronously (same tick as the click, before any await) so the
  // browser's popup blocker treats it as a direct result of the user's
  // gesture, then navigates that same window once the real authorize URL
  // comes back from the server — never opens a second, separately-blockable
  // window after the async round-trip. code_relay providers use it only to
  // avoid a jarring "nothing happened" click; app_callback providers keep it
  // open and reuse it as the auto-return target.
  const connectUserProviderOAuth = async () => {
    if (busy) return;
    setBusy("connecting");
    setError(null);
    const popup = window.open("", "aether-oauth-connect", "width=520,height=680");
    onNotice({ kind: "info", text: `Opening ${view.name} sign-in…` });
    await runConnect(async () => {
      const { authorizeUrl, flow } = await startUserProviderOAuth(view.id);
      if (flow === "code_relay") {
        popup?.close();
        window.open(authorizeUrl, "_blank", "noopener");
        setUserOauthStep("await_code");
        return;
      }
      if (popup) {
        popup.location.href = authorizeUrl;
      } else {
        // Popup blocked despite the synchronous open (e.g. a strict
        // extension) — fall back to a plain new tab.
        window.open(authorizeUrl, "_blank", "noopener");
      }
      setUserOauthStep("idle");
    });
  };

  // GAP-PROVIDER-OAUTH-1 code_relay fallback: exchange the pasted `code#state`
  // for THIS user's own credential (never the deployment-wide store).
  const completeUserProviderOAuth = async () => {
    const code = userOauthCode.trim();
    if (!code || busy) return;
    setBusy("connecting");
    setError(null);
    onNotice({ kind: "info", text: `Connecting ${view.name}…` });
    await runConnect(async () => {
      const updated = await exchangeUserProviderOAuth(view.id, code);
      setView((v) => (v ? withUserCredential(v, updated) : v));
      setUserOauthCode("");
      setUserOauthStep("idle");
      onNotice({
        kind: "success",
        text: `${view.name} connected${updated.secretHint ? ` (${updated.secretHint})` : ""}.`,
      });
      await onSaved();
    });
  };

  const verify = async () => {
    if (busy) return;
    setBusy("verifying");
    setError(null);
    onNotice({ kind: "info", text: `Testing ${view.name} connection…` });
    try {
      const res = userScope
        ? await verifyUserProvider(view.id)
        : await verifyProvider(view.id);
      onNotice({
        kind: res.ok ? "success" : "error",
        text: `${view.name} connection ${res.ok ? "ok" : "failed"} — ${res.detail}`,
      });
      await onSaved();
    } catch (e) {
      onNotice(providerCredentialErrorNotice(e, `Testing ${view.name} connection`));
      setError(inlineErrorMessage(e, "Verify failed"));
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
              <p className="text-[11px] text-aether-muted-dim" data-testid="provider-config-scope-note">
                {userScope ? (
                  <>
                    Your own key, stored encrypted on the server. Runs on this
                    provider bill to your account.
                  </>
                ) : (
                  <>
                    Credentials are stored encrypted on the server — enter them here, no{" "}
                    <code className="font-mono">.env</code> editing.
                  </>
                )}
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
                ? ` · ${new Date(view.lastVerifiedAt).toLocaleString("en-AU")}`
                : ""}
            </span>
          ) : null}
        </div>

        {/* Both scopes authorise on Anthropic's own pages; they differ in what
            happens to the resulting token. The DEPLOYMENT flow writes the
            shared ProviderCredential('anthropic') row server-side and its
            routes are admin-only (F-01), so a customer must never be offered
            it — the per-user flow mints a token into the field below instead,
            and Save stores it against the customer's own row. */}
        {view.id === "anthropic" ? (
          <AnthropicOAuthPanel
            scope={userScope ? "user" : "deployment"}
            step={oauthStep}
            code={oauthCode}
            onCodeChange={setOauthCode}
            onConnect={() => void connectAnthropic()}
            onComplete={() => void completeAnthropic()}
            busy={busy !== null}
            connecting={busy === "connecting"}
          >
            {!userScope && anthropicNeedsReauth ? (
              <div
                data-testid="anthropic-oauth-needs-reauth"
                role="alert"
                className="mb-3 rounded-lg border border-aether-amber/30 bg-aether-amber/10 p-2.5"
              >
                <p className="text-[11px] leading-relaxed text-aether-amber">
                  <i className="fa-solid fa-triangle-exclamation mr-1.5" aria-hidden="true" />
                  Your Anthropic subscription session expired. Renew it now, or click
                  Connect with Anthropic to sign in again.
                </p>
                <button
                  type="button"
                  data-testid="anthropic-oauth-reconnect"
                  onClick={() => void renewAnthropic()}
                  disabled={busy !== null}
                  className="mt-2 rounded-lg border border-aether-amber/30 bg-aether-amber/15 px-3 py-1.5 text-[11px] font-semibold text-aether-amber transition hover:bg-aether-amber/25 disabled:opacity-50"
                >
                  {busy === "connecting" ? "Renewing…" : "Renew now"}
                </button>
              </div>
            ) : null}
          </AnthropicOAuthPanel>
        ) : null}

        {/* GAP-PROVIDER-OAUTH-1: the per-user, provider-agnostic "Connect"
            affordance — writes ONLY this user's own UserProviderCredential
            row, never the deployment-wide store the block above owns. Shown
            for every provider whose descriptor supports it (today:
            anthropic, openrouter — see OAUTH_CONNECT_PROVIDERS in ./api). */}
        {userScope && supportsUserOAuthConnect(view.id) ? (
          <div className="mb-4 rounded-lg border border-aether-indigo/25 bg-aether-indigo/5 p-3">
            <button
              type="button"
              data-testid="user-oauth-connect"
              onClick={() => void connectUserProviderOAuth()}
              disabled={busy !== null}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-aether-indigo px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-aether-indigo/25 transition hover:opacity-90 disabled:opacity-50"
            >
              <i className="fa-solid fa-arrow-up-right-from-square text-[10px]" aria-hidden="true" />
              {busy === "connecting" && userOauthStep === "idle"
                ? `Opening ${view.name}…`
                : `Connect with ${view.name}`}
            </button>
            <p className="mt-2 text-[11px] leading-relaxed text-aether-muted">
              {view.id === "anthropic" ? (
                <>
                  Connects <strong>your own</strong> Claude Pro/Max subscription — runs bill
                  your subscription quota, never Aether&apos;s. Revoke access anytime at
                  claude.ai.
                </>
              ) : (
                <>
                  Connects <strong>your own</strong> OpenRouter account — runs bill your
                  OpenRouter balance, never Aether&apos;s. Revoke access anytime at
                  openrouter.ai.
                </>
              )}
            </p>
            {userOauthStep === "await_code" ? (
              <div className="mt-3">
                <label
                  htmlFor="user-oauth-code"
                  className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim"
                >
                  Paste the code {view.name} showed you
                </label>
                <div className="flex items-center gap-2">
                  <input
                    id="user-oauth-code"
                    data-testid="user-oauth-code-input"
                    type="text"
                    value={userOauthCode}
                    onChange={(e) => setUserOauthCode(e.target.value)}
                    placeholder="code#state"
                    autoComplete="off"
                    spellCheck={false}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-xs text-white outline-none focus:border-aether-indigo/50"
                  />
                  <button
                    type="button"
                    data-testid="user-oauth-complete"
                    onClick={() => void completeUserProviderOAuth()}
                    disabled={busy !== null || userOauthCode.trim() === ""}
                    className="shrink-0 rounded-lg bg-aether-indigo px-3 py-2.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                  >
                    {busy === "connecting" ? "Connecting…" : "Finish connecting"}
                  </button>
                </div>
              </div>
            ) : null}
            <p className="mt-2 text-[10px] text-aether-muted-dim">
              or paste a key manually below
            </p>
          </div>
        ) : null}

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
              {busy === "saving" ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
