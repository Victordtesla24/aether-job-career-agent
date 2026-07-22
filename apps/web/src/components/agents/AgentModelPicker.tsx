"use client";

/**
 * Per-agent live-model picker (ML-catalog-001, §3.2). Rendered on EVERY
 * non-planned agent card so a user can choose ANY model from the live catalog
 * for THAT agent independently — the selection persists to the agent's own
 * `AgentConfig.model` (PUT /agents/config/{agentKey}), never the provider-global
 * default. Distinct from the single global `ModelPicker` (which sets the
 * provider default that a per-agent choice overrides).
 *
 * The catalog is hundreds of models, so the list is searchable (no plain
 * <select>) and grouped by budget tier, each row showing the model name, its
 * $/M prompt+completion price and context window. The agent's CURRENT model id
 * is always shown; honest loading / empty / error states only.
 *
 * Contract testids (see __tests__/agents/ml-catalog-fix1.test.tsx):
 *   - container   `agent-model-picker-<agentKey>`
 *   - search box  `agent-model-search-<agentKey>`
 *   - each option `model-option-<id>`  (id is a data attribute; the visible row
 *     shows the NAME + price + context, not the raw id — the current selection
 *     is where the raw id is surfaced)
 */
import { useMemo, useState } from "react";

import type { ModelTier, ProviderModel } from "./api";
import {
  MODEL_TIERS,
  MODEL_TIER_LABEL,
  filterModels,
  formatContextLength,
  formatModelPrice,
  groupModelsByTier,
} from "./logic";

//: Cap the rows rendered per agent when the search is broad — the flat catalog
//: is hundreds of models and this picker is repeated on every agent card, so an
//: uncapped list would be a large DOM. Search narrows to the wanted model; the
//: current selection is always shown separately regardless of the cap.
const DISPLAY_CAP = 50;

export default function AgentModelPicker({
  agentKey,
  currentModel,
  models,
  loading,
  error,
  saving,
  deterministic = false,
  onSelect,
}: {
  agentKey: string;
  currentModel: string;
  models: ProviderModel[] | null;
  loading: boolean;
  error: string | null;
  saving: boolean;
  deterministic?: boolean;
  onSelect: (model: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState<ModelTier | "all">("all");

  const filtered = useMemo(
    () => (models ? filterModels(models, query, tier) : []),
    [models, query, tier],
  );
  const capped = filtered.slice(0, DISPLAY_CAP);
  const hidden = filtered.length - capped.length;
  const groups = useMemo(() => groupModelsByTier(capped), [capped]);

  // ML-catalog-008/N2: deterministic backends (scout/fitScorer/matcher/
  // supervisor) never read a stored model at run time, so a functional
  // search+select surface here would silently no-op. Render an HONEST
  // "not user-selectable" indicator instead — no search box, no model rows.
  // (Placed after the hooks above so hook order stays stable — rules-of-hooks.)
  if (deterministic) {
    return (
      <div
        data-testid={`agent-model-picker-${agentKey}`}
        className="mt-3 rounded-lg border border-white/10 bg-white/5 p-2.5"
      >
        <p className="flex items-start gap-1.5 text-[10px] leading-relaxed text-aether-muted">
          <i
            className="fa-solid fa-lock mt-0.5 shrink-0 text-[10px] text-aether-muted-dim"
            aria-hidden="true"
          />
          <span>
            Fixed model — not user-selectable. This agent runs deterministically
            (no LLM), so there is no model to choose.
          </span>
        </p>
      </div>
    );
  }

  return (
    <div
      data-testid={`agent-model-picker-${agentKey}`}
      className="mt-3 rounded-lg border border-white/10 bg-white/5 p-2.5"
    >
      <p className="mb-1.5 text-[10px] text-aether-muted-dim">
        Model for this agent:{" "}
        <span className="font-mono text-aether-indigo">{currentModel || "—"}</span>
        {saving ? <span className="ml-1 text-aether-amber">· saving…</span> : null}
      </p>

      {/* ML-catalog-007 (§3.1.3): the billing/provider implication must be
          USER-VISIBLE, not just a code comment. Every model offered here comes
          from the OpenRouter catalog, so choosing one routes THIS agent through
          OpenRouter (resolve_provider keys off the id; credentials never cross
          providers). */}
      <p className="mb-1.5 flex items-start gap-1.5 rounded-md border border-aether-indigo/20 bg-aether-indigo/5 px-1.5 py-1 text-[9px] leading-relaxed text-aether-muted-dim">
        <i
          className="fa-solid fa-scale-balanced mt-0.5 shrink-0 text-[9px] text-aether-indigo"
          aria-hidden="true"
        />
        <span>
          These models come from the OpenRouter catalog — choosing one routes
          this agent&apos;s runs through OpenRouter and bills to your OpenRouter
          account. Anthropic models never route through OpenRouter.
        </span>
      </p>

      {loading && models === null ? (
        <div
          data-testid={`agent-model-loading-${agentKey}`}
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 px-1 py-2 text-[10px] text-aether-muted"
        >
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-aether-indigo/40 border-t-aether-indigo" />
          Loading the live catalog…
        </div>
      ) : error !== null ? (
        <p
          data-testid={`agent-model-error-${agentKey}`}
          role="status"
          className="rounded-md border border-aether-amber/30 bg-aether-amber/10 px-2 py-1.5 text-[10px] leading-relaxed text-aether-amber"
        >
          {error}
        </p>
      ) : (
        <>
          <div className="mb-1.5 flex gap-1.5">
            <input
              data-testid={`agent-model-search-${agentKey}`}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label={`Search models for ${agentKey}`}
              placeholder="Search models…"
              className="min-w-0 flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white outline-none placeholder:text-aether-muted-dim focus:border-aether-indigo/50"
            />
            <select
              data-testid={`agent-model-tier-${agentKey}`}
              value={tier}
              onChange={(e) => setTier(e.target.value as ModelTier | "all")}
              aria-label={`Filter models by tier for ${agentKey}`}
              className="rounded-md border border-white/10 bg-white/5 px-1.5 py-1 text-[10px] text-aether-muted outline-none focus:border-aether-indigo/50 [&>option]:bg-aether-bg"
            >
              <option value="all">All</option>
              {MODEL_TIERS.map((t) => (
                <option key={t} value={t}>
                  {MODEL_TIER_LABEL[t]}
                </option>
              ))}
            </select>
          </div>

          {groups.length === 0 ? (
            <p
              data-testid={`agent-model-empty-${agentKey}`}
              className="px-1 py-2 text-center text-[10px] text-aether-muted"
            >
              {models && models.length === 0
                ? "No models available yet."
                : "No models match your search."}
            </p>
          ) : (
            <div className="max-h-56 space-y-2 overflow-y-auto pr-0.5">
              {groups.map((g) => (
                <div key={g.tier}>
                  <p className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-aether-muted-dim">
                    {g.label}
                  </p>
                  <ul className="space-y-1">
                    {g.models.map((m) => {
                      const selected = m.id === currentModel;
                      const ctx = formatContextLength(m.contextLength);
                      return (
                        <li key={m.id}>
                          <button
                            type="button"
                            data-testid={`model-option-${m.id}`}
                            data-selected={selected || undefined}
                            aria-pressed={selected}
                            disabled={saving}
                            onClick={() => onSelect(m.id)}
                            className={`w-full rounded-md border px-2 py-1 text-left transition disabled:opacity-60 ${
                              selected
                                ? "border-aether-coral/50 bg-aether-coral/10"
                                : "border-white/10 bg-white/5 hover:bg-white/10"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-1.5">
                              <span className="truncate text-[11px] font-medium text-white">
                                {m.name}
                              </span>
                              {selected ? (
                                <i
                                  className="fa-solid fa-circle-check shrink-0 text-[10px] text-aether-coral"
                                  aria-label="current model"
                                />
                              ) : null}
                            </div>
                            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[9px] text-aether-muted">
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
              {hidden > 0 ? (
                <p className="px-1 pt-0.5 text-center text-[9px] text-aether-muted-dim">
                  …and {hidden} more — refine your search.
                </p>
              ) : null}
            </div>
          )}
        </>
      )}
    </div>
  );
}
