"use client";

/**
 * AI Provider Connections (wireframe: providers-ag07). Six provider cards whose
 * connection status, credential source + active model are real, persisted
 * state. The card action opens the in-app credential configuration modal
 * (REQ-PC-1) — there is no ".env editing" path:
 *  - connected   → "Connected · Manage" (rotate / test / remove the credential)
 *  - warning     → "Re-authenticate"
 *  - unconfigured→ "Configure keys"
 *
 * Renders BOTH provider scopes (F-01 / ADR-F01-PROVIDER-CREDENTIAL-AUTHZ) from
 * the identical row shape, differing only in `title`/`blurb` and which endpoint
 * the parent fetched: the OPERATOR's deployment-wide connections
 * (GET /agents/providers, admin-only) or a CUSTOMER's own keys
 * (GET /agents/user/providers/catalog). This component never fetches — it can
 * only show what the page was allowed to load.
 */
import type { Provider, ProviderModel } from "./api";
import {
  providerAction,
  providerModelDisabledReason,
  providerSourceBadge,
  type ProviderSourceBadge,
} from "./logic";

const DOT: Record<Provider["status"], string> = {
  connected: "bg-aether-green",
  warning: "bg-aether-yellow",
  unconfigured: "bg-aether-muted-dim",
};

const CARD_BORDER: Record<Provider["status"], string> = {
  connected: "border-aether-green/25",
  warning: "border-aether-yellow/30",
  unconfigured: "border-white/10",
};

const ACTION_CLS: Record<Provider["status"], string> = {
  connected: "bg-aether-green/15 text-aether-green border-aether-green/25 hover:bg-aether-green/25",
  warning: "bg-aether-yellow/15 text-aether-yellow border-aether-yellow/25 hover:bg-aether-yellow/25",
  unconfigured: "bg-aether-indigo/15 text-aether-indigo border-aether-indigo/25 hover:bg-aether-indigo/25",
};

const BADGE_CLS: Record<ProviderSourceBadge["tone"], string> = {
  saved: "border-aether-green/25 bg-aether-green/10 text-aether-green",
  env: "border-aether-amber/25 bg-aether-amber/10 text-aether-amber",
  none: "border-white/10 bg-white/5 text-aether-muted-dim",
};

export default function ProviderConnections({
  providers,
  loading,
  busyId,
  onConfigure,
  onModel,
  title = "AI Provider Connections",
  blurb,
  anthropicModels = null,
  anthropicModelsError = null,
}: {
  providers: Provider[];
  loading: boolean;
  busyId: string | null;
  onConfigure: (provider: Provider) => void;
  onModel: (id: string, model: string) => void;
  /** Heading for this scope. Defaults to the operator wording. */
  title?: string;
  /** Optional one-line explanation of whose keys these are. */
  blurb?: string;
  /**
   * Anthropic's LIVE curated catalog (GET /agents/providers/anthropic/models,
   * `fetchProviderModels("anthropic")`) — ML-U1X-b. Fetched independently of
   * `providers[].models` so a genuinely connected+verified credential renders
   * real, priced options even when that seed array is still empty/stale
   * (the RCA: a working 3-model catalog existed but nothing ever fetched it
   * for this card). `null` while loading; falls back to `providers[].models`
   * (bare ids, no pricing) so the select never regresses to "no models" while
   * the live fetch is in flight or has failed.
   *
   * F-3 re-fix: this live catalog is CREDENTIAL-INDEPENDENT (the endpoint
   * answers 200 unconditionally, ADR-ML-4), so it may only back THIS card's
   * select while `p.status === "connected"` in the scope this panel is
   * showing — otherwise the backend's own honest-empty-list gating for
   * unconfigured/needs-reauth providers (D-0020) would be dead for this one
   * card. See the `anthropicOptions` computation below.
   */
  anthropicModels?: ProviderModel[] | null;
  /** F-4: the live anthropic-catalog fetch's error, if it failed — surfaced
   *  on the card so an empty anthropic select names the REAL cause (the fetch
   *  failed) instead of the generic "configure below" copy, which is false
   *  once a credential is actually connected. */
  anthropicModelsError?: string | null;
}) {
  return (
    <section data-testid="provider-connections">
      <div className="mb-1 flex items-center gap-2">
        <i className="fa-solid fa-plug text-sm text-aether-indigo" aria-hidden="true" />
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      {blurb ? (
        <p
          data-testid="provider-connections-blurb"
          className="mb-4 text-[11px] leading-relaxed text-aether-muted"
        >
          {blurb}
        </p>
      ) : (
        <div className="mb-4" />
      )}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="glass h-44 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {providers.map((p) => {
            const action = providerAction(p.status);
            const busy = busyId === p.id;
            const badge = providerSourceBadge(p);
            // F-3 re-fix: the live-fetched catalog is credential-independent,
            // so it may only stand in for the seed once THIS scope's card is
            // actually `connected` — otherwise an unconfigured/needs-reauth
            // card would show a real, selectable catalog for a credential
            // nobody can call (D-0020 — the backend's own gating on `p.models`
            // becomes dead for this card if the live fetch is preferred
            // unconditionally). When connected, prefer the live fetch (it
            // carries real pricing) and fall back to the seed's bare id list
            // only while that fetch hasn't resolved yet or failed — the seed
            // is ALSO real for a connected provider (backend static-catalog
            // wiring), so this never regresses to a blanket "no models".
            // Labels stay bare ids here (pricing is the Orchestrator role
            // picker's job, AgentModelPicker below) so this card matches
            // every other provider's plain-id select.
            const anthropicOptions =
              p.id === "anthropic" && p.status === "connected"
                ? anthropicModels && anthropicModels.length > 0
                  ? anthropicModels.map((m) => ({ id: m.id, label: m.id }))
                  : p.models.map((id) => ({ id, label: id }))
                : [];
            // F-4: key the lock reason on the count of options THIS card is
            // actually about to render (never the raw seed length for
            // anthropic), so the tooltip and the `disabled` attribute below
            // — both driven by `anthropicOptions.length` — can never diverge.
            // R-2: also thread the anthropic card's REAL fetch-error text so
            // a connected-but-catalog-fetch-failed card gets the true cause
            // in its `title`, never the false "configure its credentials".
            const modelLockReason =
              p.id === "anthropic"
                ? providerModelDisabledReason(p, anthropicOptions.length, anthropicModelsError)
                : providerModelDisabledReason(p);
            return (
              <div
                key={p.id}
                data-testid={`provider-${p.id}`}
                className={`glass rounded-2xl border p-5 ${CARD_BORDER[p.status]}`}
              >
                <div className="mb-3 flex items-start justify-between">
                  <div className="flex min-w-0 items-center gap-3">
                    <div
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
                      style={{ backgroundColor: p.color }}
                    >
                      <i
                        className={`fa-solid ${p.icon} text-sm text-white`}
                        aria-hidden="true"
                      />
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{p.name}</p>
                      <p className="text-[11px] text-aether-muted-dim">{p.auth}</p>
                    </div>
                  </div>
                  <span
                    className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${DOT[p.status]}`}
                    aria-label={`${p.name} ${p.status}`}
                    role="img"
                  />
                </div>

                <p
                  className={`mb-2 text-[11px] ${p.status === "warning" ? "text-aether-yellow" : "text-aether-muted"}`}
                  data-testid={`provider-detail-${p.id}`}
                >
                  {p.detail}
                </p>

                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span
                    data-testid={`provider-source-${p.id}`}
                    className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${BADGE_CLS[badge.tone]}`}
                  >
                    {badge.label}
                  </span>
                  {p.secretHint ? (
                    <span
                      data-testid={`provider-hint-${p.id}`}
                      className="font-mono text-[10px] text-aether-muted-dim"
                    >
                      Ends {p.secretHint}
                    </span>
                  ) : null}
                </div>

                {p.id === "openrouter" ? (
                  // OpenRouter's models are the LIVE catalog (330+), chosen in the
                  // model picker below — NOT a fixed dropdown. Surface a clear
                  // affordance on the card so users find them where they look
                  // (GAP-P7-MODEL-CHOICE-002).
                  <a
                    href="#openrouter-model-picker"
                    data-testid="provider-model-openrouter"
                    className="mb-3 flex w-full items-center justify-between gap-2 rounded-lg border border-aether-coral/30 bg-aether-coral/10 px-3 py-2 text-[11px] font-medium text-aether-coral transition hover:bg-aether-coral/20"
                  >
                    <span className="truncate">
                      <i className="fa-solid fa-list-ul mr-1.5" aria-hidden="true" />
                      {p.model
                        ? `Model: ${p.model} — change`
                        : "Choose from all models"}
                    </span>
                    <i
                      className="fa-solid fa-arrow-down text-[10px] opacity-70"
                      aria-hidden="true"
                    />
                  </a>
                ) : p.id === "anthropic" ? (
                  // Anthropic has no open catalog to browse live (ADR-ML-4 —
                  // static curated list), but IS a real fetched catalog
                  // (`fetchProviderModels("anthropic")`), not a hardcoded
                  // seed array — so it gets a real (non-openrouter-style)
                  // select with actual per-model pricing, rather than the
                  // generic branch below whose options are just the bare
                  // `providers[].models` seed.
                  <label className="mb-3 block">
                    <span className="sr-only">{p.name} model</span>
                    <select
                      data-testid={`provider-model-${p.id}`}
                      aria-label={`${p.name} model`}
                      aria-disabled={modelLockReason !== null || undefined}
                      title={modelLockReason ?? undefined}
                      value={p.model}
                      disabled={anthropicOptions.length === 0 || busy}
                      onChange={(e) => onModel(p.id, e.target.value)}
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[11px] text-aether-muted outline-none focus:border-aether-coral/50 disabled:cursor-not-allowed disabled:opacity-60 disabled:grayscale [&>option]:bg-aether-bg"
                    >
                      {anthropicOptions.length === 0 ? (
                        <option value="">
                          {p.status === "connected" && anthropicModelsError
                            ? `Catalog unavailable — ${anthropicModelsError}`
                            : "No preset models — configure below"}
                        </option>
                      ) : (
                        anthropicOptions.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.label}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                ) : (
                  <label className="mb-3 block">
                    <span className="sr-only">{p.name} model</span>
                    <select
                      data-testid={`provider-model-${p.id}`}
                      aria-label={`${p.name} model`}
                      aria-disabled={modelLockReason !== null || undefined}
                      title={modelLockReason ?? undefined}
                      value={p.model}
                      disabled={p.models.length === 0 || busy}
                      onChange={(e) => onModel(p.id, e.target.value)}
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[11px] text-aether-muted outline-none focus:border-aether-coral/50 disabled:cursor-not-allowed disabled:opacity-60 disabled:grayscale [&>option]:bg-aether-bg"
                    >
                      {p.models.length === 0 ? (
                        <option value="">No preset models — configure below</option>
                      ) : (
                        p.models.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                )}

                <button
                  type="button"
                  data-testid={`provider-action-${p.id}`}
                  onClick={() => onConfigure(p)}
                  disabled={busy}
                  className={`w-full rounded-lg border py-2 text-xs font-medium transition disabled:opacity-60 ${ACTION_CLS[p.status]}`}
                >
                  <i className={`fa-solid ${action.icon} mr-1.5`} aria-hidden="true" />
                  {busy ? "Saving…" : action.label}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
