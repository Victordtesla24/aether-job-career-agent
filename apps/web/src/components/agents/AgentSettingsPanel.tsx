"use client";

/**
 * Per-agent settings panel (GAP-D3). Expands under an agent card to configure
 * the model's sampling temperature, extended-thinking effort, and which stored
 * credential this agent bills against — then persists everything via
 * PUT /agents/config/{key}. Temperature is disabled for deterministic agents
 * (no LLM sampling); the billing-path indicator reflects the selected
 * credential's authMode (subscription quota vs metered API credits).
 *
 * MODEL-SUB-QUOTA (OWNER DIRECTIVE 2026-08-17): for a CLAUDE agent the only
 * credential that can serve the run is the operator's Anthropic subscription
 * (`authMode: "oauth_token"`), so that is the only kind this drawer offers —
 * and an unpinned Claude agent says so rather than reading as an unspecified
 * default. See the helpers below for the three statements this file used to get
 * wrong.
 */
import { useCallback, useEffect, useState } from "react";

import {
  fetchAgentConfig,
  listUserCredentials,
  updateAgentConfig,
  type CatalogAgent,
  type ThinkingEffort,
  type UserCredential,
} from "./api";
import { providerFromModelId } from "./conductor";

const EFFORTS: ThinkingEffort[] = ["none", "low", "medium", "high"];

/**
 * Which provider serves and bills this agent's model.
 *
 * MODEL-SUB-QUOTA (OWNER DIRECTIVE 2026-08-17). This used to be a private
 * `startsWith("claude")` rule, which called the namespaced spelling
 * `anthropic/claude-*` an OpenRouter model — so the drawer offered OpenRouter
 * credentials for a Claude agent and SAVED `provider: "openrouter"` onto the
 * config row, a persisted claim that a Claude run bills an account it never
 * touches. It now defers to {@link providerFromModelId}, the single FE mirror
 * of the server's `resolve_provider`, so there is ONE rule rather than two that
 * can drift. `null` (a bare id no rule claims, including the `deterministic`
 * sentinel) keeps the historical OpenRouter default, matching the server.
 */
function providerForModel(model: string): string {
  return providerFromModelId(model) ?? "openrouter";
}

/** Whether this agent's model is a Claude model in EITHER spelling. */
function isClaudeModel(model: string): boolean {
  return /^(?:anthropic\/)?claude-/i.test(model.trim());
}

/**
 * Whether a stored credential is the operator's SUBSCRIPTION rather than a
 * metered key.
 *
 * `oauth_token` is the live subscription mode (the API's `CLAUDE_AUTH_MODES`);
 * `subscription_oauth` is its already-unusable legacy form (ADR-P7-01). This
 * drawer previously recognised only the legacy one, so selecting the REAL
 * subscription credential displayed "Metered API credits" — the exact opposite
 * of the truth.
 */
function isSubscriptionMode(authMode: UserCredential["authMode"]): boolean {
  return authMode === "oauth_token" || authMode === "subscription_oauth";
}

export default function AgentSettingsPanel({
  agent,
  onSaved,
}: {
  agent: CatalogAgent;
  onSaved?: () => void;
}) {
  const deterministic =
    agent.recommended === "deterministic" || agent.model === "deterministic";
  const provider = providerForModel(agent.model);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [temperature, setTemperature] = useState(0.7);
  const [thinking, setThinking] = useState<ThinkingEffort>("medium");
  const [credentialRef, setCredentialRef] = useState<string>("");
  const [creds, setCreds] = useState<UserCredential[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, userCreds] = await Promise.all([
        fetchAgentConfig(agent.key),
        listUserCredentials().catch(() => [] as UserCredential[]),
      ]);
      setTemperature(cfg.temperature);
      setThinking(cfg.thinkingEffort);
      setCredentialRef(cfg.credentialRef ?? "");
      setCreds(userCreds);
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 160) : "Could not load settings");
    } finally {
      setLoading(false);
    }
  }, [agent.key]);

  useEffect(() => {
    void load();
  }, [load]);

  const claude = isClaudeModel(agent.model);
  // MODEL-SUB-QUOTA clause 3: the API serves a Claude run on the operator's
  // SUBSCRIPTION credential or on nothing at all — an Anthropic api_key is
  // skipped at resolution and refused at the seam. Offering one here would
  // invite a pin that can never fund the run, so a Claude agent lists only
  // subscription-mode credentials.
  const providerCreds = creds.filter(
    (c) => c.provider === provider && (!claude || isSubscriptionMode(c.authMode)),
  );
  // Anthropic keys the user does own but that a Claude run may not spend —
  // counted so the drawer can say WHY they are absent instead of hiding them.
  const ineligibleClaudeKeys = claude
    ? creds.filter((c) => c.provider === provider && !isSubscriptionMode(c.authMode)).length
    : 0;
  const selectedCred = providerCreds.find((c) => c.id === credentialRef) ?? null;
  const billingPath = selectedCred
    ? isSubscriptionMode(selectedCred.authMode)
      ? "Subscription quota"
      : "Metered API credits"
    : claude
      // No per-agent pin: a Claude run falls to the operator's Anthropic
      // subscription token, never to a metered key and never to OpenRouter.
      ? "Your Anthropic subscription quota — Claude models are never billed to an API key"
      : "Deployment default credential";

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      await updateAgentConfig(agent.key, {
        temperature: deterministic ? undefined : temperature,
        thinkingEffort: thinking,
        credentialRef: credentialRef || "",
        provider,
      });
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 160) : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div
        data-testid={`agent-settings-loading-${agent.key}`}
        className="mt-3 h-24 animate-pulse rounded-lg border border-white/10 bg-white/5"
      />
    );
  }

  return (
    <div
      data-testid={`agent-settings-${agent.key}`}
      className="mt-3 space-y-3 rounded-lg border border-white/10 bg-white/5 p-3"
    >
      <div>
        <div className="mb-1 flex items-center justify-between">
          <label
            htmlFor={`temp-${agent.key}`}
            className="text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim"
          >
            Temperature
          </label>
          <span className="font-mono text-[11px] text-aether-indigo">
            {deterministic ? "—" : temperature.toFixed(1)}
          </span>
        </div>
        <input
          id={`temp-${agent.key}`}
          data-testid={`agent-temp-${agent.key}`}
          type="range"
          min={0}
          max={2}
          step={0.1}
          value={temperature}
          disabled={deterministic}
          onChange={(e) => setTemperature(Number(e.target.value))}
          className="w-full accent-aether-coral disabled:opacity-40"
        />
        {deterministic ? (
          <p className="mt-1 text-[10px] text-aether-muted-dim">
            Deterministic agent — no LLM sampling, temperature does not apply.
          </p>
        ) : null}
      </div>

      <div>
        <label
          htmlFor={`think-${agent.key}`}
          className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim"
        >
          Thinking effort
        </label>
        <select
          id={`think-${agent.key}`}
          data-testid={`agent-thinking-${agent.key}`}
          value={thinking}
          onChange={(e) => setThinking(e.target.value as ThinkingEffort)}
          className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-aether-text outline-none focus:border-aether-indigo/50 [&>option]:bg-surface-2"
        >
          {EFFORTS.map((eff) => (
            <option key={eff} value={eff}>
              {eff.charAt(0).toUpperCase() + eff.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label
          htmlFor={`cred-${agent.key}`}
          className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-aether-muted-dim"
        >
          Billing credential ({provider})
        </label>
        <select
          id={`cred-${agent.key}`}
          data-testid={`agent-credential-${agent.key}`}
          value={credentialRef}
          onChange={(e) => setCredentialRef(e.target.value)}
          className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-aether-text outline-none focus:border-aether-indigo/50 [&>option]:bg-surface-2"
        >
          <option value="">
            Deployment default
          </option>
          {providerCreds.map((c) => (
            <option key={c.id} value={c.id}>
              {isSubscriptionMode(c.authMode) ? "Subscription" : "API key"}
              {c.secretHint ? ` (${c.secretHint})` : ""}
            </option>
          ))}
        </select>
        {ineligibleClaudeKeys > 0 ? (
          <p
            data-testid={`agent-ineligible-creds-${agent.key}`}
            className="mt-1.5 text-[10px] text-aether-muted-dim"
          >
            {ineligibleClaudeKeys === 1
              ? "1 Anthropic API key you have stored is not listed"
              : `${ineligibleClaudeKeys} Anthropic API keys you have stored are not listed`}
            : Claude models run on your subscription token, so an API key cannot
            fund them.
          </p>
        ) : null}
        <p
          data-testid={`agent-billing-path-${agent.key}`}
          className="mt-1.5 rounded-md border border-aether-indigo/20 bg-aether-indigo/5 px-2 py-1 text-[10px] text-aether-muted"
        >
          <i className="fa-solid fa-scale-balanced mr-1 text-aether-indigo" aria-hidden="true" />
          Bills to: {billingPath}
        </p>
      </div>

      {error ? (
        <p
          role="alert"
          data-testid={`agent-settings-error-${agent.key}`}
          className="rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-[10px] text-red-300"
        >
          {error}
        </p>
      ) : null}

      <button
        type="button"
        onClick={() => void save()}
        disabled={saving}
        data-testid={`agent-settings-save-${agent.key}`}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-aether-indigo px-3 py-1.5 text-xs font-semibold text-aether-text transition hover:opacity-90 disabled:opacity-50"
      >
        <i className="fa-solid fa-floppy-disk text-[10px]" aria-hidden="true" />
        {saving ? "Saving…" : "Save settings"}
      </button>
    </div>
  );
}
