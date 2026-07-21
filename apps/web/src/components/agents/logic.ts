/**
 * Pure, unit-testable helpers for the Agents screen (no React/DOM). Kept
 * separate from the components so the display + interaction logic can be
 * verified in the node vitest environment.
 */
import type { CatalogAgent, ModelTier, Provider, ProviderModel } from "./api";

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

// ---------------------------------------------------------------------------
// Live model picker (GAP-P7-MODEL-CHOICE-001) — pure display + selection logic.
// ---------------------------------------------------------------------------

/** Budget tiers in cheapest-first display order (matches the backend ranking). */
export const MODEL_TIERS: readonly ModelTier[] = ["free", "budget", "standard", "premium"];

export const MODEL_TIER_LABEL: Record<ModelTier, string> = {
  free: "Free",
  budget: "Budget",
  standard: "Standard",
  premium: "Premium",
};

/** `$3.00/M in · $15.00/M out`, or "Free" when a model has no metered price. */
export function formatModelPrice(promptPerM: number, completionPerM: number): string {
  if (promptPerM <= 0 && completionPerM <= 0) return "Free";
  return `$${promptPerM.toFixed(2)}/M in · $${completionPerM.toFixed(2)}/M out`;
}

/** Compact context-window label (200K / 1M ctx), or null when unknown. */
export function formatContextLength(n: number | null): string | null {
  if (n === null || n <= 0) return null;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M ctx`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K ctx`;
  return `${n} ctx`;
}

/**
 * Case-insensitive filter by model name/id, plus an optional tier. Preserves
 * the backend's cheapest-first ordering; the picker searches 300+ models so
 * this narrows the list before it is grouped/rendered.
 */
export function filterModels(
  models: ProviderModel[],
  query: string,
  tier: ModelTier | "all",
): ProviderModel[] {
  const q = query.trim().toLowerCase();
  return models.filter((m) => {
    if (tier !== "all" && m.tier !== tier) return false;
    if (!q) return true;
    return m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q);
  });
}

export interface ModelTierGroup {
  tier: ModelTier;
  label: string;
  models: ProviderModel[];
}

/** Group models into the fixed tier order, dropping empty groups and keeping
 *  the backend's cheapest-first ordering within each tier. */
export function groupModelsByTier(models: ProviderModel[]): ModelTierGroup[] {
  return MODEL_TIERS.map((tier) => ({
    tier,
    label: MODEL_TIER_LABEL[tier],
    models: models.filter((m) => m.tier === tier),
  })).filter((g) => g.models.length > 0);
}

export type BudgetPreset = "economy" | "balanced" | "premium";

/** id families that denote a premium frontier model — used ONLY to pick one
 *  that actually exists in the fetched catalog, never to fabricate an id. */
const PREMIUM_ID_HINT = /(claude.*opus|gpt-5|gpt-4|\bo1\b|\bo3\b|gemini.*pro|grok)/i;

/**
 * The model id a budget preset should set, derived FROM the fetched catalog at
 * click-time (never a hardcoded id that might not exist):
 *  - economy  → cheapest reasoning-capable model, else the cheapest overall
 *  - balanced → "" (clear the override so agents run the app default)
 *  - premium  → a recognised frontier model if the catalog has one, else the
 *               priciest premium-tier model, else the priciest overall
 * Returns null when there is nothing to derive from (economy/premium on an
 * empty catalog). The catalog arrives cheapest-first within tier (free first),
 * so `models[0]` is the cheapest and the first reasoning match is the cheapest
 * reasoning-capable model.
 */
export function deriveBudgetPresetModel(
  models: ProviderModel[],
  preset: BudgetPreset,
): string | null {
  if (preset === "balanced") return "";
  if (models.length === 0) return null;
  if (preset === "economy") {
    const reasoning = models.filter((m) => m.reasoning);
    return (reasoning[0] ?? models[0]).id;
  }
  const premiumTier = models.filter((m) => m.tier === "premium");
  const pool = premiumTier.length > 0 ? premiumTier : models;
  const known = pool.find((m) => PREMIUM_ID_HINT.test(m.id));
  if (known) return known.id;
  return pool.reduce((a, b) => (b.promptPerM > a.promptPerM ? b : a)).id;
}
