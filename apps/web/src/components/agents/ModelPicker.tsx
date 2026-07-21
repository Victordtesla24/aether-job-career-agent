"use client";

/**
 * Live model & budget picker (GAP-P7-MODEL-CHOICE-001). For a catalog provider
 * (OpenRouter) it fetches the LIVE model catalog
 * (GET /agents/providers/{id}/models — 300+ models) and lets the user set the
 * provider DEFAULT model either by:
 *  - browsing the catalog grouped by budget tier (Free / Budget / Standard /
 *    Premium), searchable by name/id and filterable by tier, each row showing
 *    its $/M prompt+completion price and context window; or
 *  - one-click BUDGET PRESETS (Economy / Balanced / Premium) whose target id is
 *    derived from the fetched catalog at click-time — never a hardcoded id.
 *
 * Selecting a model or a preset persists via PUT /agents/providers/{id}
 * (updateProvider), which the backend now reads at run time — a per-agent
 * override still wins where set. Honest states only: a loading spinner while
 * fetching, and the backend's own 400 detail (no key / catalog unreachable)
 * rendered verbatim — never a fabricated list.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchProviderModels,
  updateProvider,
  type ModelTier,
  type Provider,
  type ProviderModel,
} from "./api";
import {
  MODEL_TIERS,
  MODEL_TIER_LABEL,
  deriveBudgetPresetModel,
  filterModels,
  formatContextLength,
  formatModelPrice,
  groupModelsByTier,
  type BudgetPreset,
} from "./logic";
import { ApiError } from "../../lib/api/client";
import type { Notice } from "../../lib/agents-feedback";

const PRESETS: Array<{ id: BudgetPreset; label: string; icon: string; hint: string }> = [
  { id: "economy", label: "Economy", icon: "fa-leaf", hint: "Cheapest capable model" },
  { id: "balanced", label: "Balanced", icon: "fa-scale-balanced", hint: "Clear override → app default" },
  { id: "premium", label: "Premium", icon: "fa-gem", hint: "Top-tier frontier model" },
];

/** Surface the honest backend `detail`. `fetchProviderModels` already cleans an
 *  ApiError's message to the detail; `updateProvider` doesn't, so lift it here. */
function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error && e.message.trim()) {
    const match = e.message.match(/\{[\s\S]*\}$/);
    if (match) {
      try {
        const parsed = JSON.parse(match[0]) as { detail?: unknown };
        if (typeof parsed.detail === "string" && parsed.detail.trim()) return parsed.detail;
      } catch {
        /* not JSON — fall through */
      }
    }
    return e.message;
  }
  return "Something went wrong — try again in a moment.";
}

export default function ModelPicker({
  provider,
  onSaved,
  onNotice,
}: {
  provider: Provider | null | undefined;
  onSaved?: () => void | Promise<void>;
  onNotice?: (notice: Notice) => void;
}) {
  const [models, setModels] = useState<ProviderModel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState<ModelTier | "all">("all");
  const [busy, setBusy] = useState(false);

  const providerId = provider?.id ?? null;
  const providerName = provider?.name ?? "";
  const current = provider?.model ?? "";

  const load = useCallback(async () => {
    if (!providerId) return;
    setLoading(true);
    setError(null);
    try {
      setModels(await fetchProviderModels(providerId));
    } catch (e) {
      setModels(null);
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [providerId]);

  useEffect(() => {
    void load();
  }, [load]);

  const setModel = useCallback(
    async (model: string, label: string) => {
      if (!providerId || busy) return;
      setBusy(true);
      try {
        await updateProvider(providerId, { model });
        onNotice?.({
          kind: "success",
          text: model
            ? `Default model for ${providerName} set to ${label}.`
            : `Cleared the ${providerName} override — agents will run the app default model.`,
        });
        await onSaved?.();
      } catch (e) {
        onNotice?.({ kind: "error", text: `Couldn't update the model — ${errorText(e)}` });
      } finally {
        setBusy(false);
      }
    },
    [providerId, providerName, busy, onNotice, onSaved],
  );

  const applyPreset = (preset: BudgetPreset) => {
    if (!models) return;
    const id = deriveBudgetPresetModel(models, preset);
    if (id === null) {
      onNotice?.({ kind: "error", text: "No models are available to apply that preset yet." });
      return;
    }
    const label = id === "" ? "the app default" : models.find((m) => m.id === id)?.name ?? id;
    void setModel(id, label);
  };

  const filtered = useMemo(
    () => (models ? filterModels(models, query, tier) : []),
    [models, query, tier],
  );
  const groups = useMemo(() => groupModelsByTier(filtered), [filtered]);

  if (!provider) return null;

  return (
    <section
      data-testid="model-picker"
      aria-label={`Model and budget for ${providerName}`}
      className="glass rounded-2xl border border-white/10 p-5"
    >
      <div className="mb-1 flex items-center gap-2">
        <i className="fa-solid fa-sliders text-sm text-aether-indigo" aria-hidden="true" />
        <h2 className="text-sm font-semibold">Model &amp; budget · {providerName}</h2>
      </div>
      <p className="mb-4 text-[11px] leading-relaxed text-aether-muted">
        Pick ANY model from the live {providerName} catalog, or choose by budget. This sets the
        default model every agent uses; a per-agent override still wins where set. Cheaper models
        cost less to run but may lower quality.
      </p>

      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Budget presets">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            data-testid={`model-preset-${p.id}`}
            onClick={() => applyPreset(p.id)}
            disabled={busy || loading || models === null}
            title={p.hint}
            className="flex items-center gap-1.5 rounded-lg border border-aether-indigo/25 bg-aether-indigo/10 px-3 py-2 text-xs font-medium text-aether-indigo transition hover:bg-aether-indigo/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <i className={`fa-solid ${p.icon} text-[10px]`} aria-hidden="true" />
            {p.label}
          </button>
        ))}
      </div>

      {loading && models === null ? (
        <div
          data-testid="model-picker-loading"
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-4 text-xs text-aether-muted"
        >
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-aether-indigo/40 border-t-aether-indigo" />
          Loading the live model catalog…
        </div>
      ) : error !== null ? (
        <div
          data-testid="model-picker-error"
          role="status"
          className="rounded-lg border border-aether-amber/30 bg-aether-amber/10 p-3 text-[11px] leading-relaxed text-aether-amber"
        >
          <p>{error}</p>
          <button
            type="button"
            data-testid="model-picker-retry"
            onClick={() => void load()}
            className="mt-2 rounded-md border border-aether-amber/30 bg-aether-amber/10 px-2.5 py-1 text-[10px] font-medium transition hover:bg-aether-amber/20"
          >
            <i className="fa-solid fa-rotate-right mr-1" aria-hidden="true" />
            Retry
          </button>
        </div>
      ) : (
        <>
          <div className="mb-3 flex flex-col gap-2 sm:flex-row">
            <label className="flex-1">
              <span className="sr-only">Search models by name or id</span>
              <input
                data-testid="model-search"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search 300+ models by name or id…"
                className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white outline-none placeholder:text-aether-muted-dim focus:border-aether-indigo/50"
              />
            </label>
            <label className="sm:w-40">
              <span className="sr-only">Filter by budget tier</span>
              <select
                data-testid="model-tier-filter"
                value={tier}
                onChange={(e) => setTier(e.target.value as ModelTier | "all")}
                className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-aether-muted outline-none focus:border-aether-indigo/50 [&>option]:bg-aether-bg"
              >
                <option value="all">All tiers</option>
                {MODEL_TIERS.map((t) => (
                  <option key={t} value={t}>
                    {MODEL_TIER_LABEL[t]}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <p data-testid="model-current" className="mb-2 text-[11px] text-aether-muted-dim">
            {current ? (
              <>
                Current default: <span className="font-mono text-aether-muted">{current}</span>
              </>
            ) : (
              "Current default: app default (no override)"
            )}
          </p>

          {groups.length === 0 ? (
            <p
              data-testid="model-empty"
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-4 text-center text-xs text-aether-muted"
            >
              No models match your search or tier filter.
            </p>
          ) : (
            <div
              data-testid="model-list"
              className="max-h-96 space-y-4 overflow-y-auto pr-1"
            >
              {groups.map((g) => (
                <div key={g.tier} data-testid={`model-group-${g.tier}`}>
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-aether-muted-dim">
                    {g.label} · {g.models.length}
                  </p>
                  <ul className="space-y-1.5">
                    {g.models.map((m) => {
                      const selected = m.id === current;
                      const ctx = formatContextLength(m.contextLength);
                      return (
                        <li key={m.id}>
                          <button
                            type="button"
                            data-testid={`model-option-${m.id}`}
                            data-selected={selected || undefined}
                            aria-pressed={selected}
                            disabled={busy}
                            onClick={() => void setModel(m.id, m.name)}
                            className={`w-full rounded-lg border px-3 py-2 text-left transition disabled:opacity-60 ${
                              selected
                                ? "border-aether-coral/50 bg-aether-coral/10"
                                : "border-white/10 bg-white/5 hover:bg-white/10"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate text-xs font-medium text-white">
                                {m.name}
                              </span>
                              <span className="flex shrink-0 items-center gap-1.5">
                                {m.reasoning ? (
                                  <span className="rounded border border-aether-indigo/25 bg-aether-indigo/10 px-1.5 py-0.5 text-[9px] font-medium text-aether-indigo">
                                    Reasoning
                                  </span>
                                ) : null}
                                {selected ? (
                                  <i
                                    className="fa-solid fa-circle-check text-[11px] text-aether-coral"
                                    aria-label="selected default"
                                  />
                                ) : null}
                              </span>
                            </div>
                            <span className="block truncate font-mono text-[10px] text-aether-muted-dim">
                              {m.id}
                            </span>
                            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-aether-muted">
                              <span>{formatModelPrice(m.promptPerM, m.completionPerM)}</span>
                              {ctx ? <span>{ctx}</span> : null}
                            </div>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
