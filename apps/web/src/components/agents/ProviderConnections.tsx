"use client";

/**
 * AI Provider Connections (wireframe: providers-ag07). Six provider cards whose
 * connection status + active model are real, persisted state (GET/PUT
 * /agents/providers). Buttons perform genuine state changes:
 *  - connected   → "Connected · Manage" (click disconnects)
 *  - warning     → "Re-authenticate"    (click reconnects)
 *  - unconfigured→ "Configure keys"     (click connects)
 */
import type { Provider } from "./api";
import { providerAction, providerModelDisabledReason } from "./logic";

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

export default function ProviderConnections({
  providers,
  loading,
  busyId,
  onToggle,
  onModel,
}: {
  providers: Provider[];
  loading: boolean;
  busyId: string | null;
  onToggle: (id: string, next: Provider["status"]) => void;
  onModel: (id: string, model: string) => void;
}) {
  return (
    <section data-testid="provider-connections">
      <div className="mb-4 flex items-center gap-2">
        <i className="fa-solid fa-plug text-sm text-aether-indigo" aria-hidden="true" />
        <h2 className="text-sm font-semibold">AI Provider Connections</h2>
      </div>

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
            const modelLockReason = providerModelDisabledReason(p);
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
                  className={`mb-3 text-[11px] ${p.status === "warning" ? "text-aether-yellow" : "text-aether-muted"}`}
                  data-testid={`provider-detail-${p.id}`}
                >
                  {p.detail}
                </p>

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
                      <option value="">Select region — ap-southeast-2</option>
                    ) : (
                      p.models.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))
                    )}
                  </select>
                </label>

                <button
                  type="button"
                  data-testid={`provider-action-${p.id}`}
                  onClick={() => onToggle(p.id, action.next)}
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
