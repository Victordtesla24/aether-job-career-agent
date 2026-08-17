"use client";

/**
 * Agent Configuration grid (wireframe: agent-grid-ag14; redesigned in S-UI-1
 * §4.1 Tab 2). The full agent catalog as cards: category glyph,
 * keyboard-accessible recommendation tooltip, live status badge, assigned
 * model, and an enable/disable toggle. Runnable agents (real backend) also
 * expose Run.
 *
 * Status + config are real: derived from GET /agents/catalog and mutated via
 * PUT /agents/config/{key} (see components/agents/api.ts).
 *
 * ── S-UI-1 CHANGES (presentation + information architecture only) ──────────
 * X-2 "card-height discipline": NO component may render an expanding list
 * inside a grid cell. Two offenders lived here and both are gone:
 *   1. `AgentModelPicker`'s model list — now a portalled popover opened from a
 *      compact trigger (see that file's header for the root-cause note).
 *   2. `AgentSettingsPanel` — now a full-width drawer BELOW the grid rather
 *      than an accordion inside one cell, which used to shove that card to
 *      ~600px and break every row's alignment.
 * With no variable-height children left, every card renders the same height by
 * construction (a `min-h` floor plus grid row-stretch keeps it exact), so this
 * is a grid instead of a broken masonry.
 *
 * A filter strip (status segments + text filter) is added because 22 identical
 * cards is a wall, not a grid. It is pure client-side filtering over the same
 * `agents` prop — no new request, no changed request.
 *
 * Preserved verbatim: the stale-catalog banner and its exact `refreshedLabel()`
 * copy, the model-picker lock and its reason text, planned cards' disabled
 * treatment and absent picker, and every existing testid.
 */
import { useCallback, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import SegmentedControl from "../ui/SegmentedControl";
import StatusBadge, { type StatusTone } from "../ui/StatusBadge";
import AgentModelPicker from "./AgentModelPicker";
import AgentSettingsPanel from "./AgentSettingsPanel";
import type { CatalogAgent, ProviderModel } from "./api";
import { type CatalogCounts, catalogScaleLabel } from "./catalog-counts";
import { agentRunDisabledReason } from "./logic";

/** Human "catalog last refreshed …" text (ML-catalog-002). Honest when the
 *  backend timestamp is not yet known (shown until the first refresh/envelope
 *  load) and calls out a stale (last-good) copy explicitly. */
function refreshedLabel(iso: string | null, stale: boolean): string {
  if (!iso) return "Catalog not yet refreshed — showing the latest loaded list.";
  const when = new Date(iso);
  const ts = Number.isNaN(when.getTime()) ? iso : when.toLocaleString("en-AU");
  return stale
    ? `Catalog last refreshed ${ts} · stale — showing cached data`
    : `Catalog last refreshed ${ts}`;
}

const ACCENT_BG: Record<string, string> = {
  indigo: "bg-aether-indigo/15 text-aether-indigo",
  coral: "bg-aether-coral/15 text-aether-coral",
  amber: "bg-aether-amber/15 text-aether-amber",
  green: "bg-aether-green/15 text-aether-green",
};

const STATUS_TONE: Record<CatalogAgent["status"], StatusTone> = {
  active: "ok",
  paused: "warn",
  error: "danger",
  planned: "neutral",
};

const STATUS_LABEL: Record<CatalogAgent["status"], string> = {
  active: "Active",
  paused: "Paused",
  error: "Error",
  planned: "Planned",
};

/**
 * S-UI aesthetics slice: `.ag-node` (agents-console.css) is the console's ONE
 * card shell — 1px hairline, top-edge highlight, soft top-light wash — so the
 * 22 configuration cards, the orchestration map's nodes and the live-run
 * monitor's nodes all read as the same material (reference-pack rule 15).
 * The status semantics are unchanged: error keeps its danger tint, planned
 * keeps its dashed, un-lit, 75%-opacity treatment.
 */
const CARD_BORDER: Record<CatalogAgent["status"], string> = {
  active: "ag-node",
  paused: "ag-node",
  error: "border border-state-danger/30 bg-state-danger/[0.05] hover:border-state-danger/50",
  planned: "ag-node ag-node-planned opacity-75",
};

type StatusFilter = "all" | CatalogAgent["status"];

const FILTERS: ReadonlyArray<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "error", label: "Error" },
  { value: "planned", label: "Planned" },
];

/**
 * U-UI AGENTS-PHANTOM-OVERFLOW-01 / AGENTS-CARD-OVERLAP-01: the recommendation
 * tooltip used to be a `.group`/`group-hover` CSS-only popover living inline
 * next to its trigger. Even while closed (`opacity-0`) it stayed in normal
 * flow, so all 22 cards' hidden description boxes contributed to their card's
 * `scrollHeight` (70 flagged elements, 71px phantom overflow on the whole
 * grid) and could geometrically overlap the next row's card.
 *
 * The description renders through a portal to document.body — never a DOM
 * descendant of its `agent-card-<key>` container — with visibility toggled by
 * CSS, and is re-measured on open (REV-U-UI-01) so a below-the-fold card's
 * popover is never pinned to a stale page-load position.
 */
function AgentTip({ agentKey, name, tip }: { agentKey: string; name: string; tip: string }) {
  const tipId = useId();
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [pos, setPos] = useState({ top: 0, right: 0 });
  const triggerRef = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => setMounted(true), []);

  const measure = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    setPos({ top: rect.bottom + 8, right: Math.max(8, window.innerWidth - rect.right) });
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

  const close = () => setOpen(false);

  return (
    <span className="relative inline-flex">
      <button
        ref={triggerRef}
        type="button"
        data-testid={`agent-tip-${agentKey}`}
        aria-label={`Model recommendation for ${name}`}
        aria-describedby={tipId}
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={close}
        onFocus={() => setOpen(true)}
        onBlur={close}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            close();
            triggerRef.current?.focus();
          }
        }}
        className="flex h-5 w-5 items-center justify-center rounded text-aether-muted-dim outline-none hover:text-white focus-visible:ring-2 focus-visible:ring-aether-coral/70"
      >
        <i className="fa-solid fa-circle-info text-xs" aria-hidden="true" />
      </button>
      {mounted
        ? createPortal(
            <span
              data-testid={`agent-tip-desc-${agentKey}`}
              style={{ top: pos.top, right: pos.right }}
              className="pointer-events-none fixed z-50"
            >
              <span
                id={tipId}
                role="tooltip"
                data-testid={`agent-tip-popover-${agentKey}`}
                className={`elev-3 w-[280px] max-w-[calc(100vw-2rem)] rounded-lg p-3 text-[12px] leading-[1.45] text-aether-muted transition-opacity duration-[var(--dur-fast)] ${
                  open ? "block opacity-100" : "hidden opacity-0"
                }`}
              >
                {tip}
              </span>
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}

/** ML-U1X-b: the ONE catalog key whose model is a user-assignable ROLE
 *  (`_ROLE_MODEL_BACKENDS`, backend "supervisor") rather than a metered
 *  per-call tier — its default/downshift options are Anthropic's own static
 *  catalog, never the shared OpenRouter list every other card uses. */
const ORCHESTRATOR_ROLE_KEY = "orchestration";

function AgentCard({
  agent,
  busy,
  onToggle,
  onRun,
  catalogModels,
  catalogLoading,
  catalogError,
  orchestratorModels,
  orchestratorModelsLoading,
  orchestratorModelsError,
  savingModel,
  onSelectModel,
  settingsOpen,
  onToggleSettings,
}: {
  agent: CatalogAgent;
  busy: boolean;
  onToggle: (key: string, enabled: boolean) => void;
  onRun: (key: string) => void;
  catalogModels: ProviderModel[] | null;
  catalogLoading: boolean;
  catalogError: string | null;
  // ML-U1X-b: Anthropic's live catalog, fed ONLY to the Orchestrator role
  // card (see `ORCHESTRATOR_ROLE_KEY`) — a distinct fetch from `catalogModels`
  // (OpenRouter) with its own loading/error state.
  orchestratorModels: ProviderModel[] | null;
  orchestratorModelsLoading: boolean;
  orchestratorModelsError: string | null;
  savingModel: boolean;
  onSelectModel: (key: string, model: string) => void;
  settingsOpen: boolean;
  onToggleSettings: (key: string) => void;
}) {
  const isOrchestratorRole = agent.key === ORCHESTRATOR_ROLE_KEY;
  const pickerModels = isOrchestratorRole ? orchestratorModels : catalogModels;
  const pickerLoading = isOrchestratorRole ? orchestratorModelsLoading : catalogLoading;
  const pickerError = isOrchestratorRole ? orchestratorModelsError : catalogError;
  const runLockReason = agentRunDisabledReason(agent);

  return (
    <div
      data-testid={`agent-card-${agent.key}`}
      className={`relative flex min-h-[168px] flex-col justify-between gap-3 p-4 sm:min-h-[150px] ${CARD_BORDER[agent.status]}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${ACCENT_BG[agent.accent] ?? ACCENT_BG.indigo}`}
        >
          <i className={`fa-solid ${agent.icon} text-xs`} aria-hidden="true" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col items-end gap-1">
          <div className="flex w-full min-w-0 items-center justify-end gap-1.5">
            <p
              title={agent.name}
              className="min-w-0 flex-1 truncate text-right text-[13px] font-semibold tracking-[-0.01em]"
            >
              {agent.name}
            </p>
            <AgentTip agentKey={agent.key} name={agent.name} tip={agent.tip} />
          </div>
        </div>
      </div>

      {/* The model is a BUTTON that opens the picker popover — never an
          inline, card-height-inflating list (X-2). Planned agents have no
          backend and therefore nothing to configure, so they get no picker,
          exactly as before. */}
      {agent.status !== "planned" ? (
        <AgentModelPicker
          agentKey={agent.key}
          currentModel={agent.model}
          models={pickerModels}
          loading={pickerLoading}
          error={pickerError}
          saving={savingModel}
          // ML-agents-001: lock the picker whenever a picked model is NOT
          // honoured at run time — the authoritative server-computed
          // `modelOverridable` flag covers BOTH deterministic (no-LLM) backends
          // AND fixed-tier LLM agents (STRUCTURED, e.g. storyExtraction), whose
          // `recommended` is a real model id so the old
          // `recommended === "deterministic"` sentinel (ML-catalog-008/N2)
          // missed them. Fall back to that sentinel for a response predating
          // the flag so deterministic agents still lock.
          overridable={agent.modelOverridable ?? agent.recommended !== "deterministic"}
          catalogProvider={isOrchestratorRole ? "anthropic" : "openrouter"}
          onSelect={(model) => onSelectModel(agent.key, model)}
        />
      ) : (
        <p className="truncate rounded-md border border-dashed border-hairline px-2 py-1 font-mono text-[11px] text-state-neutral">
          {agent.model}
        </p>
      )}

      {/* ML-agents-005: the 44px min tap targets (gear/run/toggle) plus the
          status label exceed a narrow card's width at 390px. Wrap the row so
          the action cluster drops to its own line on a narrow card while the
          accessible 44px tap targets are preserved. */}
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <StatusBadge
          tone={STATUS_TONE[agent.status]}
          dot={agent.status === "active"}
          testId={`agent-status-${agent.key}`}
        >
          {STATUS_LABEL[agent.status]}
        </StatusBadge>
        {agent.status === "planned" ? null : (
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid={`agent-settings-toggle-${agent.key}`}
              aria-expanded={settingsOpen}
              aria-label={`${settingsOpen ? "Hide" : "Show"} settings for ${agent.name}`}
              onClick={() => onToggleSettings(agent.key)}
              className={`flex h-6 w-6 items-center justify-center rounded-md border outline-none transition-colors duration-[var(--dur-fast)] focus-visible:ring-2 focus-visible:ring-aether-coral/70 ${
                settingsOpen
                  ? "border-aether-coral/50 bg-aether-coral/10 text-aether-coral"
                  : "border-hairline-strong text-aether-muted-dim hover:border-white/30 hover:text-white"
              }`}
            >
              <i className="fa-solid fa-sliders text-[10px]" aria-hidden="true" />
            </button>
            {agent.runnable ? (
              <button
                type="button"
                data-testid={`agent-run-${agent.key}`}
                onClick={() => onRun(agent.key)}
                disabled={busy || !agent.enabled}
                aria-disabled={runLockReason !== null || undefined}
                title={busy ? "Running…" : (runLockReason ?? undefined)}
                className="rounded-md border border-hairline-strong px-2 py-0.5 text-[11px] font-semibold text-aether-muted outline-none hover:border-white/30 hover:text-white focus-visible:ring-2 focus-visible:ring-aether-coral/70 disabled:cursor-not-allowed disabled:opacity-40 disabled:grayscale"
              >
                Run
              </button>
            ) : null}
            <button
              type="button"
              role="switch"
              aria-checked={agent.enabled}
              aria-label={`${agent.enabled ? "Disable" : "Enable"} ${agent.name}`}
              data-testid={`agent-toggle-${agent.key}`}
              onClick={() => onToggle(agent.key, !agent.enabled)}
              disabled={busy}
              title={busy ? "Updating…" : undefined}
              className="inline-flex min-h-[44px] min-w-[44px] items-center justify-end outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/70 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-0 sm:min-w-0"
            >
              <span
                className={`relative block h-4 w-8 rounded-full transition-colors duration-[var(--dur)] ${agent.enabled ? "bg-aether-coral" : "bg-white/12"}`}
              >
                <span
                  className={`absolute top-0.5 h-3 w-3 rounded-full transition-all duration-[var(--dur)] ${agent.enabled ? "right-0.5 bg-white" : "left-0.5 bg-aether-muted-dim"}`}
                />
              </span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function AgentConfigGrid({
  agents,
  counts,
  loading,
  busyKey,
  onToggle,
  onRun,
  catalogModels,
  catalogLoading,
  catalogError,
  orchestratorModels,
  orchestratorModelsLoading,
  orchestratorModelsError,
  catalogRefreshedAt,
  catalogStale,
  catalogRefreshing,
  onRefreshCatalog,
  savingModelKey,
  onSelectModel,
}: {
  agents: CatalogAgent[];
  counts: CatalogCounts | null;
  loading: boolean;
  busyKey: string | null;
  onToggle: (key: string, enabled: boolean) => void;
  onRun: (key: string) => void;
  catalogModels: ProviderModel[] | null;
  catalogLoading: boolean;
  catalogError: string | null;
  // ML-U1X-b: Anthropic's live catalog for the Orchestrator role card only —
  // see `ORCHESTRATOR_ROLE_KEY` / `AgentCard` above. Required (not optional
  // with a silent-empty default): a caller that forgets to wire the
  // Anthropic fetch must fail to compile, not ship a card whose model
  // picker silently renders zero options with no error (REV-U-UI-04) on the
  // one agent whose model choice carries the Anthropic-vs-OpenRouter
  // billing distinction (ML-U1X-b / ADR-ML-3). Callers with no Orchestrator
  // card in their agent list still pass explicit null/false/null.
  orchestratorModels: ProviderModel[] | null;
  orchestratorModelsLoading: boolean;
  orchestratorModelsError: string | null;
  catalogRefreshedAt: string | null;
  catalogStale: boolean;
  catalogRefreshing: boolean;
  onRefreshCatalog: () => void;
  savingModelKey: string | null;
  onSelectModel: (key: string, model: string) => void;
}) {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [text, setText] = useState("");
  const [settingsKey, setSettingsKey] = useState<string | null>(null);

  const visible = useMemo(() => {
    const q = text.trim().toLowerCase();
    return agents.filter((a) => {
      if (statusFilter !== "all" && a.status !== statusFilter) return false;
      if (!q) return true;
      return (
        a.name.toLowerCase().includes(q) ||
        a.key.toLowerCase().includes(q) ||
        a.model.toLowerCase().includes(q)
      );
    });
  }, [agents, statusFilter, text]);

  const settingsAgent = settingsKey ? (agents.find((a) => a.key === settingsKey) ?? null) : null;

  return (
    <section data-testid="agent-configuration" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <i className="fa-solid fa-robot text-sm text-aether-coral" aria-hidden="true" />
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Agent Configuration</h2>
          {/* AUD-AGENT-4: this said "N agents" over the CARD total, counting
              the one fitScorer engine three times. Both server-computed
              numbers are stated instead, and nothing is stated when the
              server sent no honest basis. */}
          <span
            data-testid="catalog-scale"
            className="font-mono text-[11px] tabular-nums text-aether-muted-dim"
          >
            {catalogScaleLabel(counts) ?? "…"}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-aether-muted-dim">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-state-ok" />
            <span className="font-mono tabular-nums">{counts ? counts.active : "—"}</span> Active
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-state-warn" />
            <span className="font-mono tabular-nums">{counts ? counts.paused : "—"}</span> Paused
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-state-danger" />
            <span className="font-mono tabular-nums">{counts ? counts.error : "—"}</span> Error
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-state-neutral" />
            <span className="font-mono tabular-nums">{counts ? (counts.planned ?? 0) : "—"}</span>{" "}
            Planned
          </span>
        </div>
      </div>

      <div className="elev-2 flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2">
        <p
          data-testid="catalog-last-refreshed"
          className={`text-[11px] ${catalogStale ? "text-state-warn" : "text-aether-muted-dim"}`}
        >
          <i
            className={`fa-solid ${catalogStale ? "fa-triangle-exclamation" : "fa-clock-rotate-left"} mr-1.5 text-[10px]`}
            aria-hidden="true"
          />
          {refreshedLabel(catalogRefreshedAt, catalogStale)}
        </p>
        <button
          type="button"
          data-testid="catalog-refresh-btn"
          onClick={onRefreshCatalog}
          disabled={catalogRefreshing}
          className="flex items-center gap-1.5 rounded-md border border-hairline-strong bg-surface-1 px-2.5 py-1 text-[11px] font-medium outline-none transition-colors duration-[var(--dur-fast)] hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <i
            className={`fa-solid fa-rotate-right text-[10px] ${catalogRefreshing ? "animate-spin" : ""}`}
            aria-hidden="true"
          />
          {catalogRefreshing ? "Refreshing…" : "Refresh catalog"}
        </button>
      </div>

      {/* Filter strip — with 22 cards this is the difference between a grid
          and a wall. Pure client-side narrowing of the same data. */}
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl
          items={FILTERS}
          value={statusFilter}
          onChange={setStatusFilter}
          ariaLabel="Filter agents by status"
          idPrefix="agent-filter"
          size="sm"
          testId="agent-filter-strip"
        />
        <label className="relative min-w-[180px] flex-1">
          <span className="sr-only">Filter agents by name or model</span>
          <i
            className="fa-solid fa-magnifying-glass pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-aether-muted-dim"
            aria-hidden="true"
          />
          <input
            type="search"
            data-testid="agent-text-filter"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Filter by name or model…"
            className="w-full rounded-md border border-hairline bg-surface-1 py-1.5 pl-7 pr-2 text-[12px] text-white outline-none placeholder:text-aether-muted-dim focus-visible:ring-2 focus-visible:ring-aether-coral/70"
          />
        </label>
      </div>

      {loading ? (
        // Skeleton at the EXACT final geometry so nothing reflows on arrival.
        <div
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
          aria-busy="true"
        >
          {Array.from({ length: 8 }).map((_, i) => (
            <div
              key={i}
              className="ag-node min-h-[168px] animate-pulse sm:min-h-[150px]"
            />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="ag-panel p-8 text-center">
          <i
            className="fa-solid fa-filter-circle-xmark mb-2 text-[32px] text-aether-muted-dim/40"
            aria-hidden="true"
          />
          <p className="text-[13px] text-aether-muted">
            No agents match this filter.
          </p>
          <button
            type="button"
            onClick={() => {
              setStatusFilter("all");
              setText("");
            }}
            className="mt-3 rounded-md bg-aether-coral px-3 py-1.5 text-[12px] font-semibold outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/70"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {visible.map((a) => (
            <AgentCard
              key={a.key}
              agent={a}
              busy={busyKey === a.key}
              onToggle={onToggle}
              onRun={onRun}
              catalogModels={catalogModels}
              catalogLoading={catalogLoading}
              catalogError={catalogError}
              orchestratorModels={orchestratorModels}
              orchestratorModelsLoading={orchestratorModelsLoading}
              orchestratorModelsError={orchestratorModelsError}
              savingModel={savingModelKey === a.key}
              onSelectModel={onSelectModel}
              settingsOpen={settingsKey === a.key}
              onToggleSettings={(key) => setSettingsKey((k) => (k === key ? null : key))}
            />
          ))}
        </div>
      )}

      {/* X-2: the settings drawer opens BELOW the grid at full width — it used
          to expand inside one grid cell and shove that column's cards out of
          alignment with every other column. Same component, same endpoints. */}
      {settingsAgent ? (
        <div
          data-testid="agent-settings-drawer"
          className="ag-panel p-4"
          role="region"
          aria-label={`Settings for ${settingsAgent.name}`}
        >
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-[13px] font-semibold">
              Settings ·{" "}
              <span className="font-mono tabular-nums text-aether-muted">{settingsAgent.name}</span>
            </h3>
            <button
              type="button"
              data-testid="agent-settings-drawer-close"
              onClick={() => setSettingsKey(null)}
              aria-label={`Close settings for ${settingsAgent.name}`}
              className="rounded-md border border-hairline-strong px-2 py-1 text-[11px] text-aether-muted-dim outline-none hover:text-white focus-visible:ring-2 focus-visible:ring-aether-coral/70"
            >
              Close
            </button>
          </div>
          <AgentSettingsPanel agent={settingsAgent} />
        </div>
      ) : null}
    </section>
  );
}
