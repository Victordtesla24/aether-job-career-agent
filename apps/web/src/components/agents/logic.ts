/**
 * Pure, unit-testable helpers for the Agents screen (no React/DOM). Kept
 * separate from the components so the display + interaction logic can be
 * verified in the node vitest environment.
 */
import type { CatalogAgent, Provider } from "./api";

/** Compact token formatting for the stat cards (3.42M / 4.2K / 120). */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${n}`;
}

export interface ProviderAction {
  label: string;
  icon: string;
  next: Provider["status"];
}

/** The action a provider card offers, and the state a click transitions to. */
export function providerAction(status: Provider["status"]): ProviderAction {
  if (status === "connected")
    return { label: "Connected · Manage", icon: "fa-circle-check", next: "unconfigured" };
  if (status === "warning")
    return { label: "Re-authenticate", icon: "fa-google", next: "connected" };
  return { label: "Configure keys", icon: "fa-key", next: "connected" };
}

/** Where a provider's active credential really lives, derived from the
 * backend `source` field. Honest by construction (REQ-PC-6): "Saved in app"
 * is returned ONLY when the credential is persisted in the database — the UI
 * never fabricates it. Legacy rows that predate the enriched contract (no
 * `source`) fall back to the plain connected/not-configured status signal. */
export interface ProviderSourceBadge {
  label: string;
  tone: "saved" | "env" | "none";
}

export function providerSourceBadge(
  provider: Pick<Provider, "source" | "status">,
): ProviderSourceBadge {
  switch (provider.source) {
    case "database":
      return { label: "Saved in app", tone: "saved" };
    case "environment":
      return { label: "From environment", tone: "env" };
    case "none":
      return { label: "Not configured", tone: "none" };
    default:
      // Backend not yet enriched — never claim "Saved in app" without proof.
      return provider.status === "connected"
        ? { label: "Configured", tone: "env" }
        : { label: "Not configured", tone: "none" };
  }
}

/** Human-readable status label for an agent card. */
export function agentStatusLabel(
  status: "active" | "paused" | "error" | "planned",
): string {
  return { active: "Active", paused: "Paused", error: "Error", planned: "Planned" }[status];
}

/**
 * Why a provider's model select is intentionally locked (no models to choose
 * from), or null when it isn't. Per D-0020, a provider with no keys/models
 * configured legitimately disables its select — but a disabled control still
 * needs to explain itself, so this backs a `title` tooltip rather than
 * leaving the lock silent.
 */
export function providerModelDisabledReason(provider: Provider): string | null {
  if (provider.models.length === 0) {
    return `${provider.name} has no selectable models yet — configure its credentials to enable model selection.`;
  }
  return null;
}

/**
 * Why an agent's Run button is intentionally locked, or null when it isn't.
 * Excludes the transient "busy" (request in flight) state, which callers
 * already surface separately (e.g. a "Running…" label).
 */
export function agentRunDisabledReason(
  agent: Pick<CatalogAgent, "name" | "enabled">,
): string | null {
  if (!agent.enabled) {
    return `${agent.name} is disabled — enable it above to run it.`;
  }
  return null;
}
