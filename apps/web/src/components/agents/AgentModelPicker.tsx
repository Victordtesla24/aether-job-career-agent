"use client";

/**
 * Per-agent live-model picker (ML-catalog-001, §3.2). Rendered for EVERY
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
 * ── S-UI-1 STRUCTURAL FIX (X-2 / §4.1 Tab 2) ───────────────────────────────
 * ROOT CAUSE of the Agents page's broken masonry: this picker used to render
 * its full model list INSIDE the grid cell, so agent cards varied from 180px
 * to 600px tall and no row of the grid ever aligned. No amount of styling
 * fixes that — an expanding list simply cannot live inside a grid cell.
 *
 * The whole picker surface now renders through a PORTAL to `document.body`
 * (the pattern proven by `AgentTip`/`MetricTooltip` for
 * AGENTS-PHANTOM-OVERFLOW-01) and is positioned under a compact trigger button
 * that stays in the card. Because the panel is never a DOM descendant of the
 * card it contributes ZERO to the card's layout height OR to its scrollable
 * overflow region, so cards are uniform and the grid is a grid.
 *
 * The panel is always MOUNTED and toggled with `display:none` rather than
 * conditionally rendered — the same choice `AgentTip` made. Two consequences,
 * both deliberate: (a) a closed panel is not laid out at all, so this is
 * strictly cheaper than the previous always-inline list; (b) the picker's
 * pinned test contract (below) keeps holding, since `agent-model-picker-*`
 * remains one element containing the search box, the rows and the current
 * selection.
 *
 * Contract testids (see __tests__/agents/ml-catalog-fix1.test.tsx):
 *   - container   `agent-model-picker-<agentKey>`   (now portalled)
 *   - trigger     `agent-model-trigger-<agentKey>`  (stays in the card)
 *   - search box  `agent-model-search-<agentKey>`
 *   - each option `model-option-<id>`  (id is a data attribute; the visible row
 *     shows the NAME + price + context, not the raw id — the current selection
 *     is where the raw id is surfaced)
 */
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

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

const PANEL_W = 320;

export default function AgentModelPicker({
  agentKey,
  currentModel,
  models,
  loading,
  error,
  saving,
  overridable = true,
  catalogProvider = "openrouter",
  onSelect,
}: {
  agentKey: string;
  currentModel: string;
  models: ProviderModel[] | null;
  loading: boolean;
  error: string | null;
  saving: boolean;
  // ML-agents-001: whether a user-picked model is actually HONOURED at run
  // time for this agent. When false the picker renders an honest locked
  // indicator instead of a functional search+select surface that no-ops.
  overridable?: boolean;
  // ML-U1X-b: which live catalog `models` was fetched from — drives the
  // billing disclosure copy below. Every card but the Orchestrator ROLE
  // (`orchestration`/`supervisor`) is fed the shared OpenRouter catalog; the
  // Orchestrator's default/downshift options are Anthropic's own static
  // catalog, so the old hardcoded "these come from OpenRouter" text would be
  // dishonestly wrong for that one card (ADR-ML-3 — never mislead about which
  // credential a choice bills against).
  catalogProvider?: "openrouter" | "anthropic";
  onSelect: (model: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState<ModelTier | "all">("all");
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  const filtered = useMemo(
    () => (models ? filterModels(models, query, tier) : []),
    [models, query, tier],
  );
  const capped = filtered.slice(0, DISPLAY_CAP);
  const hidden = filtered.length - capped.length;
  const groups = useMemo(() => groupModelsByTier(capped), [capped]);

  useLayoutEffect(() => setMounted(true), []);

  // REV-U-UI-01: the grid has no inner scroll container — the whole dashboard
  // page scrolls with the window, so a `position: fixed` panel's viewport
  // coordinates are only valid for the scroll offset they were captured at.
  // Re-measure on open and keep tracking while open.
  const measure = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = typeof window === "undefined" ? PANEL_W + 16 : window.innerWidth;
    const left = Math.min(Math.max(8, rect.left), Math.max(8, vw - PANEL_W - 8));
    setPos({ top: rect.bottom + 6, left });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    measure();
    window.addEventListener("scroll", measure, { passive: true, capture: true });
    window.addEventListener("resize", measure, { passive: true });
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open, measure]);

  // Dismissal: click outside, or Escape from anywhere in the panel/trigger.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent | TouchEvent) => {
      const t = e.target as Node | null;
      if (!t) return;
      if (panelRef.current?.contains(t) || triggerRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const displayModel = currentModel || "—";

  // ML-agents-001 / ML-catalog-008/N2: a picked model is honoured at run time
  // ONLY for user-overridable LLM tiers. When it is not — a deterministic
  // (no-LLM) backend OR a fixed LLM tier (STRUCTURED, e.g. storyExtraction) —
  // a functional search+select surface would silently no-op, so the panel
  // renders an HONEST locked indicator instead (no search box, no model rows).
  const isDeterministic = !currentModel || currentModel === "deterministic";

  const panel = (
    <div
      style={{ top: pos.top, left: pos.left, width: PANEL_W }}
      className={`fixed z-50 max-w-[calc(100vw-1rem)] ${open ? "block" : "hidden"}`}
    >
      <div
        ref={panelRef}
        id={panelId}
        role="dialog"
        aria-label={`Model for ${agentKey}`}
        data-testid={`agent-model-picker-${agentKey}`}
        className="elev-3 rounded-lg p-3"
      >
        <p className="mb-2 break-all text-[11px] text-aether-muted-dim">
          Model for this agent:{" "}
          <span className="break-all font-mono text-aether-indigo">{displayModel}</span>
          {saving ? <span className="ml-1 break-normal text-state-warn">· saving…</span> : null}
        </p>

        {!overridable ? (
          <p className="flex items-start gap-1.5 text-[11px] leading-[1.5] text-aether-muted">
            <i
              className="fa-solid fa-lock mt-0.5 shrink-0 text-[10px] text-state-neutral"
              aria-hidden="true"
            />
            <span className="min-w-0">
              {isDeterministic ? (
                <>
                  Fixed model — not user-selectable. This agent runs
                  deterministically (no LLM), so there is no model to choose.
                </>
              ) : (
                <>
                  Fixed model — not user-selectable. This agent runs on a tuned
                  model for reliable structured output:{" "}
                  <span className="break-all font-mono text-aether-indigo">{currentModel}</span>.
                </>
              )}
            </span>
          </p>
        ) : (
          <>
            {/* ML-catalog-007 (§3.1.3) / ML-U1X-b: the billing/provider
                implication must be USER-VISIBLE, not just a code comment — and
                must name the catalog `models` ACTUALLY came from for this card. */}
            <p className="mb-2 flex items-start gap-1.5 rounded-md border border-aether-indigo/20 bg-aether-indigo/5 px-2 py-1.5 text-[10px] leading-[1.5] text-aether-muted-dim">
              <i
                className="fa-solid fa-scale-balanced mt-0.5 shrink-0 text-[10px] text-aether-indigo"
                aria-hidden="true"
              />
              {catalogProvider === "anthropic" ? (
                <span>
                  These are Anthropic&apos;s own curated models for the Orchestrator
                  role. Today&apos;s sequencing is deterministic, so assigning one
                  costs nothing until a real planning call runs on it — and when it
                  does, it runs only against a connected, verified Anthropic
                  credential: never through OpenRouter, never against a different
                  account.
                </span>
              ) : (
                <span>
                  These models come from the OpenRouter catalog — choosing one routes
                  this agent&apos;s runs through OpenRouter and bills to your OpenRouter
                  account. Anthropic models never route through OpenRouter.
                </span>
              )}
            </p>

            {loading && models === null ? (
              <div
                data-testid={`agent-model-loading-${agentKey}`}
                role="status"
                aria-live="polite"
                className="flex items-center gap-2 px-1 py-2 text-[11px] text-aether-muted"
              >
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-aether-indigo/40 border-t-aether-indigo" />
                Loading the live catalog…
              </div>
            ) : error !== null ? (
              <p
                data-testid={`agent-model-error-${agentKey}`}
                role="status"
                className="rounded-md border border-state-warn/30 bg-state-warn/10 px-2 py-1.5 text-[11px] leading-[1.5] text-state-warn"
              >
                {error}
              </p>
            ) : (
              <>
                <div className="mb-2 flex gap-1.5">
                  <input
                    data-testid={`agent-model-search-${agentKey}`}
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    aria-label={`Search models for ${agentKey}`}
                    placeholder="Search models…"
                    className="min-w-0 flex-1 rounded-md border border-hairline bg-surface-1 px-2 py-1 text-[12px] text-white outline-none placeholder:text-aether-muted-dim focus-visible:ring-2 focus-visible:ring-aether-coral/70"
                  />
                  <select
                    data-testid={`agent-model-tier-${agentKey}`}
                    value={tier}
                    onChange={(e) => setTier(e.target.value as ModelTier | "all")}
                    aria-label={`Filter models by tier for ${agentKey}`}
                    className="rounded-md border border-hairline bg-surface-1 px-1.5 py-1 text-[11px] text-aether-muted outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/70 [&>option]:bg-aether-bg"
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
                    className="px-1 py-2 text-center text-[11px] text-aether-muted"
                  >
                    {models && models.length === 0
                      ? "No models available yet."
                      : "No models match your search."}
                  </p>
                ) : (
                  <div className="max-h-[42vh] space-y-2 overflow-y-auto pr-0.5">
                    {groups.map((g) => (
                      <div key={g.tier}>
                        <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-aether-muted-dim">
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
                                  className={`w-full rounded-md border px-2 py-1 text-left outline-none transition-colors duration-[var(--dur-fast)] focus-visible:ring-2 focus-visible:ring-aether-coral/70 disabled:opacity-60 ${
                                    selected
                                      ? "border-aether-coral/50 bg-aether-coral/10"
                                      : "border-hairline bg-surface-1 hover:border-hairline-strong hover:bg-surface-3"
                                  }`}
                                >
                                  <div className="flex min-w-0 items-center justify-between gap-1.5">
                                    <span className="min-w-0 truncate text-[12px] font-medium text-white">
                                      {m.name}
                                    </span>
                                    {selected ? (
                                      <i
                                        className="fa-solid fa-circle-check shrink-0 text-[10px] text-aether-coral"
                                        aria-label="current model"
                                      />
                                    ) : null}
                                  </div>
                                  <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] tabular-nums text-aether-muted">
                                    <span className="break-words">
                                      {formatModelPrice(m.promptPerM, m.completionPerM)}
                                    </span>
                                    {ctx ? <span className="break-words">{ctx}</span> : null}
                                  </div>
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ))}
                    {hidden > 0 ? (
                      <p className="px-1 pt-0.5 text-center text-[10px] text-aether-muted-dim">
                        …and {hidden} more — refine your search.
                      </p>
                    ) : null}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        data-testid={`agent-model-trigger-${agentKey}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={panelId}
        // Disabled-not-hidden: a locked picker still opens, because the reason
        // it is locked is information the user is entitled to read.
        title={overridable ? "Choose this agent's model" : "Fixed model — not user-selectable"}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full min-w-0 items-center gap-1.5 rounded-md border border-hairline bg-surface-1 px-2 py-1 text-left outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70"
      >
        {!overridable ? (
          <i className="fa-solid fa-lock shrink-0 text-[9px] text-state-neutral" aria-hidden="true" />
        ) : null}
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-aether-indigo">
          {displayModel}
        </span>
        {saving ? (
          <span className="shrink-0 font-mono text-[10px] text-state-warn">saving…</span>
        ) : (
          <i className="fa-solid fa-chevron-down shrink-0 text-[9px] text-aether-muted-dim" aria-hidden="true" />
        )}
      </button>
      {mounted ? createPortal(panel, document.body) : null}
    </>
  );
}
