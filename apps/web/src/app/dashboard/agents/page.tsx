"use client";

/**
 * Manage Agents console (wireframe: design/screens/agents.html).
 *
 * Sections, in wireframe order:
 *  1. Header — "Manage Agents" + live counts + Add Provider / Test Run / Run All
 *  2. AI Provider Connections (6 cards, persisted connection state)
 *  3. Agent Configuration grid (full catalog, live status + enable/disable/model)
 *  4. Quick stats (spend / tokens / most-active / success — all from AgentRun)
 *  5. Agent Orchestration (agent-monitor, merged into this screen)
 *  6. Recent runs audit table
 *  7. Test Run modal
 *
 * Every control is wired to a real endpoint — nothing is mock. The full
 * pipeline ("Run All") is a synchronous ~30–120 s call, so the UI streams live
 * progress and a completion/failure notice (see lib/agents-feedback).
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchAgentRuns,
  fetchAgents,
  runAgent,
  runPipeline,
  type AgentRun,
  type AgentSummary,
} from "../../../lib/api/agents";
import { apiRequest } from "../../../lib/api/client";
import Orchestration from "../../../components/agents/Orchestration";
import ProviderConnections from "../../../components/agents/ProviderConnections";
import ModelPicker from "../../../components/agents/ModelPicker";
import ProviderConfigModal from "../../../components/agents/ProviderConfigModal";
import AgentConfigGrid from "../../../components/agents/AgentConfigGrid";
import AgentStatsRow from "../../../components/agents/AgentStats";
import TestRunModal from "../../../components/agents/TestRunModal";
import {
  fetchAgentStats,
  fetchCatalog,
  fetchProviderModels,
  fetchProviders,
  refreshProviderModels,
  updateAgentConfig,
  updateProvider,
  type AgentStats,
  type Catalog,
  type Provider,
  type ProviderModel,
} from "../../../components/agents/api";
import { ApiError } from "../../../lib/api/client";
import {
  agentSuccessNotice,
  missingResumeNotice,
  pipelineCompletionNotice,
  pipelineProgressNotice,
  pipelineStartNotice,
  runErrorNotice,
  type Notice,
} from "../../../lib/agents-feedback";

/** Per-agent discovery params for backend triggers. */
const RUN_PARAMS: Record<string, Record<string, unknown>> = {
  scout: { query: "software engineer", location: "Australia" },
  emailAgent: { mode: "triage" },
};

const AGENT_ROUTE: Record<string, string> = {
  scout: "scout",
  fitScorer: "fit-scorer",
  matcher: "matcher",
  tailor: "tailor",
  coverLetter: "cover-letter",
  storyExtractor: "story-extractor",
  emailAgent: "email-agent",
};

const POLL_MS = 3000;

//: The provider whose LIVE catalog backs the per-agent pickers. OpenRouter is
//: the only provider exposing an open /models catalog (the direct-Anthropic
//: list is static); a per-agent pick of an OpenRouter model routes THAT agent
//: through OpenRouter (billing implication is explicit — resolve_provider on
//: the backend keys off the id, unchanged).
const CATALOG_PROVIDER = "openrouter";

/** Surface the backend's honest `detail` from an ApiError (already lifted by
 *  fetchProviderCatalog), else a safe generic message. */
function catalogErrorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error && e.message.trim()) return e.message;
  return "Couldn't load the model catalog — try again in a moment.";
}

export default function AgentsPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [providerBusy, setProviderBusy] = useState<string | null>(null);
  const [toggleBusy, setToggleBusy] = useState<string | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const [configProvider, setConfigProvider] = useState<Provider | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  // Per-agent live model catalog (ML-catalog-001/002/003): one shared fetch of
  // the OpenRouter catalog + its freshness, fed to every per-agent picker.
  const [catalogModels, setCatalogModels] = useState<ProviderModel[] | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogRefreshedAt, setCatalogRefreshedAt] = useState<string | null>(null);
  const [catalogStale, setCatalogStale] = useState(false);
  const [catalogRefreshing, setCatalogRefreshing] = useState(false);
  const [savingModelKey, setSavingModelKey] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const runStartedAt = useRef<number>(0);

  const load = useCallback(async () => {
    try {
      const [cat, prov, st, agentList, runList] = await Promise.all([
        fetchCatalog(),
        fetchProviders(),
        fetchAgentStats(),
        fetchAgents(),
        fetchAgentRuns(),
      ]);
      setCatalog(cat);
      setProviders(prov);
      setStats(st);
      setAgents(agentList);
      setRuns(runList);
    } catch (e) {
      setNotice(runErrorNotice(e, "Loading agents"));
      setCatalog((prev) => prev ?? { agents: [], counts: { total: 0, active: 0, paused: 0, error: 0 } });
      setProviders((prev) => prev ?? []);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Load the live model catalog once for the per-agent pickers. Freshness
  // (lastRefreshedAt / stale) is surfaced through the manual Refresh control
  // (refreshProviderModels) — until then the note honestly reads "not yet
  // refreshed". Never blocks the page: its own loading/error state is local.
  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true);
    setCatalogError(null);
    try {
      setCatalogModels(await fetchProviderModels(CATALOG_PROVIDER));
    } catch (e) {
      setCatalogError(catalogErrorText(e));
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  // Force a fresh upstream refresh of the catalog (ML-catalog-003). Never blocks
  // the UI: the button shows its own spinner; the cache keeps serving meanwhile.
  const onRefreshCatalog = useCallback(async () => {
    setCatalogRefreshing(true);
    try {
      const cat = await refreshProviderModels(CATALOG_PROVIDER);
      if (cat) {
        setCatalogModels(cat.models);
        setCatalogRefreshedAt(cat.lastRefreshedAt);
        setCatalogStale(cat.stale);
        setCatalogError(null);
        setNotice({ kind: "success", text: "Model catalog refreshed from OpenRouter." });
      }
    } catch (e) {
      setNotice(runErrorNotice(e, "Refreshing the model catalog"));
    } finally {
      setCatalogRefreshing(false);
    }
  }, []);

  // Persist a per-agent model choice to THAT agent's config (ML-catalog-001):
  // PUT /agents/config/{key} → AgentConfig.model, never the provider-global row.
  const onSelectModel = useCallback(
    async (agentKey: string, model: string) => {
      setSavingModelKey(agentKey);
      try {
        await updateAgentConfig(agentKey, { model });
        setNotice({ kind: "success", text: `Model updated for ${agentKey} → ${model}.` });
        setCatalog(await fetchCatalog());
      } catch (e) {
        setNotice(runErrorNotice(e, "Updating the agent model"));
      } finally {
        setSavingModelKey(null);
      }
    },
    [],
  );

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  /** Poll while a run/pipeline is in flight so cards + stats update live. */
  const startPolling = useCallback(
    (mode: "pipeline" | "agent") => {
      runStartedAt.current = Date.now();
      stopPolling();
      pollTimer.current = setInterval(() => {
        void (async () => {
          try {
            const [cat, st, agentList, runList] = await Promise.all([
              fetchCatalog(),
              fetchAgentStats(),
              fetchAgents(),
              fetchAgentRuns(),
            ]);
            setCatalog(cat);
            setStats(st);
            setAgents(agentList);
            setRuns(runList);
            if (mode === "pipeline") {
              const completedSinceStart = runList
                .filter(
                  (r) =>
                    r.status === "completed" &&
                    r.createdAt &&
                    new Date(r.createdAt).getTime() >= runStartedAt.current,
                )
                .map((r) => r.agentName);
              setNotice(pipelineProgressNotice(completedSinceStart));
            }
          } catch {
            /* transient poll failure — keep the last notice */
          }
        })();
      }, POLL_MS);
    },
    [stopPolling],
  );

  const pipeline = async () => {
    setBusy("pipeline");
    setNotice(pipelineStartNotice());
    startPolling("pipeline");
    try {
      const result = await runPipeline();
      setNotice(missingResumeNotice(result) ?? pipelineCompletionNotice(result));
    } catch (e) {
      setNotice(runErrorNotice(e, "Pipeline"));
    } finally {
      stopPolling();
      setBusy(null);
      await load();
    }
  };

  const resolveParams = async (name: string): Promise<Record<string, unknown>> => {
    if (name === "tailor" || name === "coverLetter") {
      const jobs = await apiRequest<Array<{ id: string }>>("/jobs?sort=fitScore");
      if (jobs.length === 0) {
        throw Object.assign(new Error("No jobs discovered yet"), { status: 422 });
      }
      return { job_id: jobs[0].id };
    }
    return RUN_PARAMS[name] ?? {};
  };

  const trigger = async (backend: string) => {
    setBusy(backend);
    setNotice({ kind: "info", text: `${backend} started — running now…` });
    startPolling("agent");
    try {
      const params = await resolveParams(backend);
      const output = await runAgent(AGENT_ROUTE[backend] ?? backend, params);
      setNotice(missingResumeNotice(output) ?? agentSuccessNotice(backend, output));
    } catch (e) {
      setNotice(runErrorNotice(e, backend));
    } finally {
      stopPolling();
      setBusy(null);
      await load();
    }
  };

  const onRunAgent = (key: string) => {
    const agent = catalog?.agents.find((a) => a.key === key);
    if (agent?.backend) void trigger(agent.backend);
  };

  const onToggleAgent = async (key: string, enabled: boolean) => {
    setToggleBusy(key);
    try {
      await updateAgentConfig(key, { enabled });
      const [cat, st] = await Promise.all([fetchCatalog(), fetchAgentStats()]);
      setCatalog(cat);
      setStats(st);
    } catch (e) {
      setNotice(runErrorNotice(e, "Updating agent"));
    } finally {
      setToggleBusy(null);
    }
  };

  // The provider card action opens the in-app credential configuration modal
  // (REQ-PC-1). There is no ".env editing" path and no doomed status-flip PUT:
  // credentials are entered, tested and removed entirely in the modal, which
  // then refreshes the honest DB-first provider list.
  const openConfig = (provider: Provider) => setConfigProvider(provider);

  const refreshProviders = useCallback(async () => {
    setProviderBusy(null);
    try {
      setProviders(await fetchProviders());
    } catch (e) {
      setNotice(runErrorNotice(e, "Refreshing providers"));
    }
  }, []);

  const onProviderModel = async (id: string, model: string) => {
    setProviderBusy(id);
    try {
      await updateProvider(id, { model });
      setProviders(await fetchProviders());
    } catch (e) {
      setNotice(runErrorNotice(e, "Updating provider"));
    } finally {
      setProviderBusy(null);
    }
  };

  // "Add Provider" jumps straight into the config modal — the first provider
  // still awaiting a credential, or (all configured) the first one to manage.
  const onAddProvider = () => {
    const list = providers ?? [];
    if (list.length === 0) {
      setNotice({ kind: "info", text: "Providers are still loading — try again in a moment." });
      return;
    }
    const target = list.find((p) => p.status === "unconfigured") ?? list[0];
    setConfigProvider(target);
  };

  const agentCount = catalog?.counts.total ?? 0;
  const providerCount = providers?.length ?? 0;
  // OpenRouter carries the live 300+ model catalog the picker browses; other
  // providers expose only a small static list via the card select above.
  const openrouterProvider = (providers ?? []).find((p) => p.id === "openrouter") ?? null;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Manage Agents</h1>
          <p className="mt-0.5 font-mono text-xs text-aether-muted-dim">
            {agentCount} agents · {providerCount} AI providers · configure models &amp; connections
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            data-testid="add-provider-btn"
            onClick={() => void onAddProvider()}
            className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-medium transition hover:bg-white/10"
          >
            <i className="fa-solid fa-plus text-[10px]" aria-hidden="true" />
            Add Provider
          </button>
          <button
            type="button"
            data-testid="test-run-open"
            onClick={() => setTestOpen(true)}
            className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-medium transition hover:bg-white/10"
          >
            <i className="fa-solid fa-vial text-[10px] text-aether-indigo" aria-hidden="true" />
            Test Run
          </button>
          <button
            type="button"
            data-testid="run-pipeline-btn"
            onClick={() => void pipeline()}
            disabled={busy !== null}
            className="flex items-center gap-2 rounded-lg bg-aether-coral px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-aether-coral/25 transition hover:opacity-90 disabled:opacity-50"
          >
            {busy === "pipeline" ? (
              <>
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                Running…
              </>
            ) : (
              <>
                <i className="fa-solid fa-play text-[10px]" aria-hidden="true" />
                Run All
              </>
            )}
          </button>
        </div>
      </header>

      {notice ? (
        <p
          data-testid="agents-notice"
          role="status"
          className={`rounded-xl border p-3 text-sm ${
            notice.kind === "error"
              ? "border-red-500/30 bg-red-500/10 text-red-300"
              : notice.kind === "success"
                ? "border-aether-green/30 bg-aether-green/10 text-aether-green"
                : "border-aether-amber/30 bg-aether-amber/10 text-aether-amber"
          }`}
        >
          {notice.kind === "info" && busy !== null ? (
            <span className="mr-2 inline-block h-3 w-3 animate-spin rounded-full border-2 border-current/40 border-t-current align-middle" />
          ) : null}
          {notice.text}
          {notice.href ? (
            <>
              {" "}
              <Link href={notice.href} className="font-semibold underline underline-offset-2">
                {notice.hrefLabel ?? notice.href}
              </Link>
            </>
          ) : null}
        </p>
      ) : null}

      <ProviderConnections
        providers={providers ?? []}
        loading={providers === null}
        busyId={providerBusy}
        onConfigure={openConfig}
        onModel={(id, model) => void onProviderModel(id, model)}
      />

      {openrouterProvider ? (
        <ModelPicker
          provider={openrouterProvider}
          onSaved={refreshProviders}
          onNotice={setNotice}
        />
      ) : null}

      <AgentConfigGrid
        agents={catalog?.agents ?? []}
        counts={catalog?.counts ?? null}
        loading={catalog === null}
        busyKey={toggleBusy ?? busy}
        onToggle={(key, enabled) => void onToggleAgent(key, enabled)}
        onRun={onRunAgent}
        catalogModels={catalogModels}
        catalogLoading={catalogLoading}
        catalogError={catalogError}
        catalogRefreshedAt={catalogRefreshedAt}
        catalogStale={catalogStale}
        catalogRefreshing={catalogRefreshing}
        onRefreshCatalog={() => void onRefreshCatalog()}
        savingModelKey={savingModelKey}
        onSelectModel={(key, model) => void onSelectModel(key, model)}
      />

      <AgentStatsRow stats={stats} loading={stats === null} />

      <Orchestration agents={agents} runs={runs} />

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted-dim">
          Recent runs
        </h2>
        {runs.length === 0 ? (
          <div className="glass rounded-2xl border border-white/10 p-6 text-center text-sm text-aether-muted">
            No agent runs recorded yet.
          </div>
        ) : (
          <div className="glass overflow-x-auto rounded-2xl border border-white/10">
            <table className="w-full text-left text-sm" data-testid="agent-runs-table">
              <thead className="text-xs uppercase tracking-wide text-aether-muted-dim">
                <tr className="border-b border-white/10">
                  <th className="px-4 py-3">Agent</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Error</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 20).map((run) => (
                  <tr key={run.id} className="border-b border-white/5 last:border-0">
                    <td className="px-4 py-2.5 font-medium">{run.agentName}</td>
                    <td className="px-4 py-2.5">
                      <span
                        className={
                          run.status === "completed"
                            ? "text-aether-green"
                            : run.status === "failed"
                              ? "text-red-300"
                              : "text-aether-amber"
                        }
                      >
                        {run.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-aether-muted">
                      {run.startedAt ? new Date(run.startedAt).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-aether-muted-dim">{run.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <TestRunModal
        open={testOpen}
        agents={catalog?.agents ?? []}
        onClose={() => setTestOpen(false)}
      />

      <ProviderConfigModal
        provider={configProvider}
        onClose={() => setConfigProvider(null)}
        onSaved={refreshProviders}
        onNotice={setNotice}
      />
    </div>
  );
}
