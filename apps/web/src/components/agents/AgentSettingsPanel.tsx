"use client";

/**
 * Per-agent settings panel (GAP-D3). Expands under an agent card to configure
 * the model's sampling temperature, extended-thinking effort, and which stored
 * credential this agent bills against — then persists everything via
 * PUT /agents/config/{key}. Temperature is disabled for deterministic agents
 * (no LLM sampling); the billing-path indicator reflects the selected
 * credential's authMode (subscription quota vs metered API credits).
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

const EFFORTS: ThinkingEffort[] = ["none", "low", "medium", "high"];

/** claude-* models bill to Anthropic; everything else to OpenRouter. */
function providerForModel(model: string): "anthropic" | "openrouter" {
  return model.trim().toLowerCase().startsWith("claude") ? "anthropic" : "openrouter";
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

  const providerCreds = creds.filter((c) => c.provider === provider);
  const selectedCred = providerCreds.find((c) => c.id === credentialRef) ?? null;
  const billingPath = selectedCred
    ? selectedCred.authMode === "subscription_oauth"
      ? "Subscription quota"
      : "Metered API credits"
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
          className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-white outline-none focus:border-aether-indigo/50"
        >
          {EFFORTS.map((eff) => (
            <option key={eff} value={eff} className="bg-[#1C1C29]">
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
          className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-white outline-none focus:border-aether-indigo/50"
        >
          <option value="" className="bg-[#1C1C29]">
            Deployment default
          </option>
          {providerCreds.map((c) => (
            <option key={c.id} value={c.id} className="bg-[#1C1C29]">
              {c.authMode === "subscription_oauth" ? "Subscription" : "API key"}
              {c.secretHint ? ` (${c.secretHint})` : ""}
            </option>
          ))}
        </select>
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
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-aether-indigo px-3 py-1.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
      >
        <i className="fa-solid fa-floppy-disk text-[10px]" aria-hidden="true" />
        {saving ? "Saving…" : "Save settings"}
      </button>
    </div>
  );
}
