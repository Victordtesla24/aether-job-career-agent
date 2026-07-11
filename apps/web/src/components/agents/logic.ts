/**
 * Pure, unit-testable helpers for the Agents screen (no React/DOM). Kept
 * separate from the components so the display + interaction logic can be
 * verified in the node vitest environment.
 */
import type { Provider } from "./api";

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

/** Human-readable status label for an agent card. */
export function agentStatusLabel(status: "active" | "paused" | "error"): string {
  return { active: "Active", paused: "Paused", error: "Error" }[status];
}
