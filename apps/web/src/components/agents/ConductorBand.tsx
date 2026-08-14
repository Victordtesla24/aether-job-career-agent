"use client";

/**
 * P1-B CONDUCTOR BAND — the Supervisor, rendered ABOVE the three workflow maps
 * (ADR-AGI-3 Decision 2 + the owner's 2026-08-14 addendum: "the
 * orchestration/supervisor agent manages all the 3 workflows — fix that and
 * ensure UI too reflects that", and "the users must be able to run individual,
 * multiple agents or the whole workflow from the UI").
 *
 * WHAT THIS BAND IS ALLOWED TO SAY
 * ---------------------------------------------------------------------------
 * Every figure on it is read from a server response, and every claim it makes
 * about a run comes from a PERSISTED transition:
 *
 *   · counts, concurrency, spacing, dedup and the $0.00 preview cost →
 *     GET /agents/orchestration/plan (which dispatches nothing — that is why
 *     the cost is a literal zero rather than a projection);
 *   · the model chip → the orchestration agent's own AgentConfig / catalog row.
 *     The ADR's example model id is never substituted for a config the console
 *     has not read;
 *   · the fallback chain → the ADR constant, presented as a CHAIN. A "served by
 *     fallback" chip appears only when a run RECORDED a substitution;
 *   · the three workflow names, and which cards sit on which → the live
 *     orchestration-map payload;
 *   · a run's state → the recorded RunPlan row. `partial` and `halted` keep
 *     their own words, because the server keeps them apart for the reason that
 *     "completed | failed" would force a lie.
 *
 * WHY THE CONFIRMATION SHOWS THE PLAN FIRST. "Run everything" is 19 dispatches
 * against the user's own quota. The plan endpoint costs nothing, so the honest
 * ordering is: read the plan, show the user exactly what would run and what it
 * would bill, and only then offer the button that spends. The first press of
 * "Run everything" therefore runs NOTHING.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AgentRun } from "../../lib/api/agents";
import type { OrchestrationMapData } from "../../lib/api/agentPolicy";
import type { OrchestrationPlan, RunPlanRecord } from "../../lib/api/orchestrationPlan";
import {
  BINDING_UNREAD_TEXT,
  CONDUCTOR_HEADING,
  CONDUCTOR_MANDATE,
  FALLBACK_DISCLOSURE,
  PLAN_PREVIEW_COST_NOTE,
  SUPERVISOR_FALLBACK_CHAIN,
  conductorRailStatement,
  fallbackEngagement,
  formatPlanCost,
  groupPlanByWorkflow,
  planLinkages,
  planRunView,
  runEverythingLabel,
  supervisorBinding,
  type PlanCard,
  type SupervisorCatalogAgent,
  type SupervisorConfig,
  type WorkflowPlanGroup,
} from "./conductor";
import type { RunEverythingState } from "./use-run-everything";

/** The backend the orchestration card dispatches on (catalog: supervisor). */
const SUPERVISOR_BACKEND = "supervisor";

export interface ConductorBandProps {
  /** GET /agents/orchestration/plan, or null when it has not been read. */
  plan: OrchestrationPlan | null;
  /** Epoch ms of the console's last successful plan read; null if never. */
  planFetchedAt: number | null;
  /** The plan read's own failure message, verbatim; null when it succeeded. */
  planError: string | null;
  /** GET /agents/orchestration-map — the workflows being conducted. */
  maps: OrchestrationMapData | null;
  /** The orchestration agent's live config (provider + auth mode). */
  supervisorConfig: SupervisorConfig | null;
  /** The orchestration agent's catalog row (name + the model it runs on). */
  supervisorAgent: SupervisorCatalogAgent | null;
  /** Recent runs — the only source of a RECORDED fallback engagement. */
  runs: AgentRun[];
  run: RunEverythingState;
  onRunEverything: () => void;
  onDismissRun: () => void;
  /** The console-wide in-flight backend, so one run at a time still holds. */
  busyBackend: string | null;
}

export default function ConductorBand({
  plan,
  planFetchedAt,
  planError,
  maps,
  supervisorConfig,
  supervisorAgent,
  runs,
  run,
  onRunEverything,
  onDismissRun,
  busyBackend,
}: ConductorBandProps) {
  const [planOpen, setPlanOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const confirmRef = useRef<HTMLDivElement | null>(null);
  const startRef = useRef<HTMLButtonElement | null>(null);

  const binding = useMemo(
    () => supervisorBinding(supervisorConfig, supervisorAgent),
    [supervisorConfig, supervisorAgent],
  );
  const engaged = useMemo(() => fallbackEngagement(runs, SUPERVISOR_BACKEND), [runs]);
  const grouped = useMemo(() => groupPlanByWorkflow(plan, maps), [plan, maps]);
  const linkages = useMemo(() => planLinkages(plan, maps), [plan, maps]);
  const railStatement = useMemo(() => conductorRailStatement(maps), [maps]);
  const runView = useMemo(() => planRunView(run.record), [run.record]);
  const workflows = maps?.maps ?? [];

  const planLive = run.phase === "starting" || run.phase === "running";
  const blockedReason = !plan
    ? "The plan has not been read yet, so there is nothing to run."
    : plan.refusal
      ? plan.refusal
      : planLive
        ? "A run plan is already in flight — one plan at a time."
        : busyBackend
          ? `${busyBackend === "pipeline" ? "Run pipeline" : busyBackend} is running — one run at a time.`
          : null;
  const canRun = blockedReason === null;

  // Escape closes the confirmation wherever focus sits; the initial focus goes
  // to the action itself so a keyboard user is never dropped into a long plan.
  useEffect(() => {
    if (!confirmOpen) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setConfirmOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const t = setTimeout(() => startRef.current?.focus(), 0);
    return () => {
      document.removeEventListener("keydown", onKey);
      clearTimeout(t);
    };
  }, [confirmOpen]);

  const trapFocus = useCallback((e: React.KeyboardEvent) => {
    if (e.key !== "Tab" || !confirmRef.current) return;
    const focusable = confirmRef.current.querySelectorAll<HTMLElement>(
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
  }, []);

  const confirmAndRun = () => {
    setConfirmOpen(false);
    onRunEverything();
  };

  return (
    <section className="ag-panel relative overflow-hidden p-5" data-testid="conductor-band">
      <div className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <h2 className="ag-eyebrow">
              <span>{CONDUCTOR_HEADING}</span>
            </h2>
            <p className="mt-2 max-w-[86ch] text-[13px] leading-[1.6] text-aether-muted">
              {CONDUCTOR_MANDATE}
            </p>
            {/* The drawn rail is decorative to a screen reader; this is the same
                claim in words, so nothing is lost when it is not drawn. */}
            <p className="sr-only" data-testid="conductor-manages-text">
              {railStatement}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <button
              type="button"
              data-testid="conductor-plan-toggle"
              aria-expanded={planOpen}
              onClick={() => setPlanOpen((v) => !v)}
              title={PLAN_PREVIEW_COST_NOTE}
              className="flex items-center gap-2 rounded-md border border-hairline bg-surface-1 px-3 py-2 text-[12px] font-medium outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70 active:translate-y-px"
            >
              <i className="fa-solid fa-list-check text-[10px] text-aether-indigo" aria-hidden="true" />
              {planOpen ? "Hide plan" : "View plan"}
            </button>
            <button
              type="button"
              data-testid="conductor-run-everything"
              onClick={() => setConfirmOpen(true)}
              disabled={!canRun}
              title={blockedReason ?? "Review the plan, then start it"}
              className="flex items-center gap-2 rounded-md bg-aether-coral px-4 py-2 text-[12px] font-semibold text-black outline-none transition-opacity duration-[var(--dur-fast)] hover:opacity-90 focus-visible:ring-2 focus-visible:ring-aether-coral/70 focus-visible:ring-offset-2 focus-visible:ring-offset-aether-bg active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
            >
              <i className="fa-solid fa-play text-[10px]" aria-hidden="true" />
              {runEverythingLabel(plan)}
            </button>
          </div>
        </div>

        {/* ---- the binding, and the chain behind it ---- */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span
            data-testid="conductor-model-chip"
            title={
              binding
                ? "The model and credential this supervisor actually runs on, from its own configuration"
                : "This console has not read the orchestration agent's configuration yet"
            }
            className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-md border border-hairline-strong bg-surface-1 px-2.5 py-1.5 text-[11.5px]"
          >
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-state-ok" aria-hidden="true" />
            <span className="truncate text-aether-muted">
              {supervisorAgent?.name ?? "Orchestration Agent"}
            </span>
            <span className="truncate font-mono font-semibold">
              {binding ? binding.chip : BINDING_UNREAD_TEXT}
            </span>
          </span>
          <div
            data-testid="conductor-fallback-chain"
            className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] text-aether-muted-dim"
          >
            {SUPERVISOR_FALLBACK_CHAIN.map((link, i) => (
              <span key={link.id} className="flex items-center gap-1.5">
                {i > 0 ? <span aria-hidden="true">→</span> : null}
                <span
                  data-fallback-link={link.id}
                  title={link.note}
                  className={`rounded border px-1.5 py-0.5 ${
                    link.role === "primary"
                      ? "border-hairline-strong text-aether-muted"
                      : "border-hairline"
                  }`}
                >
                  {link.label}
                </span>
              </span>
            ))}
            <span className="min-w-0 max-w-[70ch] leading-[1.5]">{FALLBACK_DISCLOSURE}</span>
          </div>
        </div>

        {engaged ? (
          <p
            data-testid="conductor-fallback-engaged"
            className="rounded-md border border-state-warn/40 bg-state-warn/10 px-3 py-2 text-[11.5px] leading-[1.5] text-state-warn"
          >
            A recorded run was served by a fallback: asked for{" "}
            <span className="font-mono">{engaged.requestedModel}</span>, served by{" "}
            <span className="font-mono">{engaged.servedModel}</span>
            {engaged.reason ? ` — ${engaged.reason}` : ""}.
          </p>
        ) : null}

        {/* ---- what the plan endpoint says right now ---- */}
        <div
          data-testid="conductor-status-strip"
          role="status"
          aria-live="polite"
          className="ag-rail flex flex-wrap items-center gap-x-7 gap-y-3 px-4 py-3"
        >
          {plan ? (
            <>
              <span className="ag-stat">
                <span className="ag-stat-figure">{plan.agentCount}</span>
                <span className="ag-stat-label">dispatches</span>
              </span>
              <span className="ag-rail-sep" aria-hidden="true" />
              <span className="ag-stat">
                <span className="ag-stat-figure">{plan.cardCount}</span>
                <span className="ag-stat-label">cards covered</span>
              </span>
              <span className="ag-rail-sep" aria-hidden="true" />
              <span className="ag-stat">
                <span className="ag-stat-figure">{plan.concurrency}</span>
                <span className="ag-stat-label">at a time</span>
              </span>
              <span className="ag-rail-sep" aria-hidden="true" />
              <span className="ag-stat">
                <span className="ag-stat-figure">{formatPlanCost(plan)}</span>
                <span className="ag-stat-label">to preview</span>
              </span>
              <span
                data-testid="conductor-plan-read-at"
                className="ml-auto max-w-[320px] text-right text-[11px] leading-[1.5] text-aether-muted-dim"
              >
                Plan read{" "}
                {planFetchedAt !== null
                  ? new Date(planFetchedAt).toLocaleTimeString("en-AU")
                  : "—"}{" "}
                · {plan.concurrencyBasis}
              </span>
            </>
          ) : (
            <span className="text-[12px] leading-[1.5] text-aether-muted">
              {planError
                ? `The plan could not be read: ${planError}`
                : "Plan not read yet — no counts are shown until the plan endpoint answers."}
            </span>
          )}
          {plan?.refusal ? (
            <span className="w-full text-[12px] leading-[1.5] text-state-warn">
              {plan.refusal}
            </span>
          ) : null}
        </div>

        {/* ---- the run itself, in the server's words ---- */}
        {run.phase !== "idle" ? (
          <div
            data-testid="conductor-run-status"
            role="status"
            aria-live="polite"
            className={`flex flex-wrap items-start justify-between gap-x-4 gap-y-2 rounded-md border px-3 py-2.5 text-[12px] leading-[1.55] ${
              runView?.tone === "ok"
                ? "border-state-ok/40 bg-state-ok/10"
                : runView?.tone === "warn"
                  ? "border-state-warn/40 bg-state-warn/10"
                  : runView?.tone === "error" || run.phase === "error"
                    ? "border-state-err/40 bg-state-err/10"
                    : "border-hairline bg-surface-1"
            }`}
          >
            <div className="min-w-0">
              <p className="font-medium">
                {run.phase === "error"
                  ? "The plan did not start."
                  : runView
                    ? runView.headline
                    : run.phase === "starting"
                      ? "Asking the server to admit this plan…"
                      : "Plan admitted — waiting for the first recorded step."}
              </p>
              {runView?.detail ? (
                <p className="mt-1 text-aether-muted">{runView.detail}</p>
              ) : null}
              {run.error ? <p className="mt-1 text-aether-muted">{run.error}</p> : null}
              {run.planId ? (
                <p className="mt-1 font-mono text-[10.5px] text-aether-muted-dim">
                  plan {run.planId}
                </p>
              ) : null}
            </div>
            {run.phase === "settled" || run.phase === "error" ? (
              <button
                type="button"
                data-testid="conductor-run-dismiss"
                onClick={onDismissRun}
                className="shrink-0 rounded-md border border-hairline px-2.5 py-1 text-[11px] font-medium text-aether-muted outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:text-aether-text focus-visible:ring-2 focus-visible:ring-aether-coral/70"
              >
                Dismiss
              </button>
            ) : null}
          </div>
        ) : null}

        {/* ---- the rail's anchors: one per workflow this band conducts ---- */}
        {workflows.length > 0 ? (
          <div
            data-testid="conductor-manages"
            className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3"
          >
            {workflows.map((map) => {
              const group = grouped.groups.find((g) => g.key === map.key);
              return (
                <div
                  key={map.key}
                  data-testid={`conductor-anchor-${map.key}`}
                  data-conductor-anchor={map.key}
                  className="ag-panel-sunken flex min-w-0 items-center justify-between gap-3 px-3 py-2"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[12px] font-medium">{map.name}</span>
                    <span className="block text-[10.5px] text-aether-muted-dim">
                      conducted from here
                    </span>
                  </span>
                  <span className="shrink-0 text-right font-mono text-[10.5px] tabular-nums text-aether-muted-dim">
                    {group ? `${group.cards.length} cards` : "—"}
                    <br />
                    {group ? `${group.dispatchCount} runs` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        ) : null}

        {planOpen && !confirmOpen ? (
          <PlanView
            plan={plan}
            planError={planError}
            groups={grouped.groups}
            unplaced={grouped.unplaced}
            linkages={linkages}
            record={run.record}
          />
        ) : null}
      </div>

      {confirmOpen ? (
        <div
          className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto px-3 py-8"
          data-testid="conductor-confirm-shell"
          onKeyDown={trapFocus}
        >
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            aria-hidden="true"
            data-testid="conductor-confirm-backdrop"
            onClick={() => setConfirmOpen(false)}
          />
          <div
            ref={confirmRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="conductor-confirm-title"
            data-testid="conductor-confirm"
            className="elev-3 relative w-full max-w-[820px] rounded-2xl border border-hairline-strong bg-surface-1 p-5"
          >
            <h3 id="conductor-confirm-title" className="text-[15px] font-semibold">
              This is what &ldquo;{runEverythingLabel(plan)}&rdquo; will run
            </h3>
            <p className="mt-1.5 max-w-[80ch] text-[12px] leading-[1.55] text-aether-muted">
              Nothing has run yet. {PLAN_PREVIEW_COST_NOTE} Starting it dispatches every
              step below through the same paywall, quota reservation and audit row as
              pressing Run on one card.
            </p>
            <div className="mt-4 max-h-[52vh] overflow-y-auto pr-1">
              <PlanView
                plan={plan}
                planError={planError}
                groups={grouped.groups}
                unplaced={grouped.unplaced}
                linkages={linkages}
                record={null}
              />
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                data-testid="conductor-confirm-cancel"
                onClick={() => setConfirmOpen(false)}
                className="rounded-md border border-hairline bg-surface-1 px-3 py-2 text-[12px] font-medium outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70"
              >
                Cancel
              </button>
              <button
                type="button"
                ref={startRef}
                data-testid="conductor-confirm-start"
                onClick={confirmAndRun}
                disabled={!canRun}
                className="rounded-md bg-aether-coral px-4 py-2 text-[12px] font-semibold text-black outline-none transition-opacity duration-[var(--dur-fast)] hover:opacity-90 focus-visible:ring-2 focus-visible:ring-aether-coral/70 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Start the plan
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// The plan view — the same component behind "View plan" and the confirmation
// ---------------------------------------------------------------------------

function PlanView({
  plan,
  planError,
  groups,
  unplaced,
  linkages,
  record,
}: {
  plan: OrchestrationPlan | null;
  planError: string | null;
  groups: WorkflowPlanGroup[];
  unplaced: PlanCard[];
  linkages: ReturnType<typeof planLinkages>;
  /** A recorded plan, when one is live — its persisted step states are shown. */
  record: RunPlanRecord | null;
}) {
  const stepStates = useMemo(() => {
    const states = new Map<string, string>();
    (record?.steps ?? []).forEach((step) => {
      if (typeof step.state === "string") states.set(step.key, step.state);
    });
    return states;
  }, [record]);

  if (!plan) {
    return (
      <div data-testid="conductor-plan-view" className="ag-panel-sunken p-4 text-[12px] text-aether-muted">
        {planError
          ? `The plan could not be read: ${planError}`
          : "The plan has not been read yet, so there is nothing to show."}
      </div>
    );
  }

  return (
    <div data-testid="conductor-plan-view" className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11.5px] text-aether-muted">
        <span>
          <span className="font-mono font-semibold tabular-nums text-aether-text">
            {plan.agentCount}
          </span>{" "}
          dispatches
        </span>
        <span>
          <span className="font-mono font-semibold tabular-nums text-aether-text">
            {plan.cardCount}
          </span>{" "}
          cards covered
        </span>
        <span>
          <span className="font-mono font-semibold tabular-nums text-aether-text">
            {plan.duplicateCardsCollapsed}
          </span>{" "}
          duplicate cards collapsed
        </span>
        <span>
          <span className="font-mono font-semibold tabular-nums text-aether-text">
            {plan.meteredStepCount}
          </span>{" "}
          metered steps
        </span>
        <span>
          <span className="font-mono font-semibold tabular-nums text-aether-text">
            {formatPlanCost(plan)}
          </span>{" "}
          to preview
        </span>
        <span>
          {plan.concurrency} at a time · {plan.spacingSeconds}s apart
        </span>
      </div>

      {groups.map((group) => (
        <div
          key={group.key}
          data-testid={`conductor-plan-group-${group.key}`}
          className="ag-panel-sunken p-3"
        >
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h4 className="text-[12.5px] font-semibold">{group.name}</h4>
            <p className="font-mono text-[10.5px] tabular-nums text-aether-muted-dim">
              {group.cards.length} card{group.cards.length === 1 ? "" : "s"} ·{" "}
              {group.dispatchCount} dispatch{group.dispatchCount === 1 ? "" : "es"} ·{" "}
              {group.meteredCount} metered
            </p>
          </div>
          <ul className="space-y-1">
            {group.cards.map((card) => {
              const state = stepStates.get(card.stepKey) ?? null;
              return (
                <li
                  key={`${card.stepKey}:${card.cardKey}`}
                  data-testid={`conductor-plan-card-${card.cardKey}`}
                  className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 text-[11.5px]"
                >
                  <span className="min-w-0 font-medium">{card.cardName}</span>
                  <span className="font-mono text-[10.5px] text-aether-muted-dim">
                    {card.backend}
                  </span>
                  {card.execClass ? (
                    <span className="text-[10.5px] text-aether-muted-dim">{card.execClass}</span>
                  ) : null}
                  <span className="text-[10.5px] text-aether-muted-dim">
                    {card.metered ? "reserves a paid run" : "no model call"}
                  </span>
                  {state ? (
                    <span
                      data-testid={`conductor-plan-state-${card.cardKey}`}
                      className={`text-[10.5px] font-medium ${
                        state === "completed"
                          ? "text-aether-green"
                          : state === "failed" || state === "refused"
                            ? "text-red-300"
                            : "text-aether-amber"
                      }`}
                    >
                      {state}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      {unplaced.length > 0 ? (
        <div data-testid="conductor-plan-unplaced" className="ag-panel-sunken p-3 text-[11.5px]">
          <p className="mb-1 font-semibold">Covered by the plan, not on a loaded workflow map</p>
          <p className="text-aether-muted-dim">
            {unplaced.map((c) => c.cardName).join(", ")} — listed here rather than placed on a
            map the payload does not put them on.
          </p>
        </div>
      ) : null}

      {linkages.length > 0 ? (
        <div data-testid="conductor-plan-linkages" className="ag-panel-sunken p-3">
          <p className="mb-1.5 text-[12.5px] font-semibold">
            What this plan hands between workflows
          </p>
          <ul className="space-y-1 text-[11.5px]">
            {linkages.map((link) => (
              <li key={link.id} data-testid={`conductor-plan-linkage-${link.id}`}>
                <span className="font-medium">{link.fromName}</span>
                <span className="text-aether-muted-dim"> ({link.fromWorkflow})</span>
                <span aria-hidden="true"> → </span>
                <span className="font-medium">{link.toName}</span>
                <span className="text-aether-muted-dim"> ({link.toWorkflow})</span>
                <span className="text-aether-muted"> — {link.meaning}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {plan.notes.length > 0 ? (
        <ul className="space-y-1 text-[11px] leading-[1.5] text-aether-muted-dim">
          {plan.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
