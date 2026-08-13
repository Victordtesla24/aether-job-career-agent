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
import {
  agentOutputGaps,
  isStalledRun,
  outputGapMessage,
  parseServerTime,
  stalledLabel,
  STALLED_RUN_ADVICE,
} from "../../../lib/agent-run-health";
import { useNow } from "../../../hooks/useNow";
import { apiRequest } from "../../../lib/api/client";
import { humanizeActivityMessage } from "../../../lib/humanize";
import {
  jobAlertHeadline,
  jobAlertTone,
  runJobAlertIntake,
} from "../../../lib/api/jobAlerts";
import { coverLetterDegraded } from "../../../components/dashboard/feed";
import Orchestration from "../../../components/agents/Orchestration";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import ProviderConnections from "../../../components/agents/ProviderConnections";
import ModelPicker from "../../../components/agents/ModelPicker";
import ProviderConfigModal from "../../../components/agents/ProviderConfigModal";
import AgentConfigGrid from "../../../components/agents/AgentConfigGrid";
import AgentStatsRow from "../../../components/agents/AgentStats";
import TestRunModal from "../../../components/agents/TestRunModal";
import {
  fetchAgentStats,
  fetchCatalog,
  fetchProviderCatalog,
  fetchProviderModels,
  fetchProviders,
  fetchUserProviderCatalog,
  refreshProviderModels,
  updateAgentConfig,
  updateProvider,
  type AgentStats,
  type Catalog,
  type Provider,
  type ProviderModel,
} from "../../../components/agents/api";
import { fetchMe } from "../../../lib/api/admin";
import {
  deriveSearchTarget,
  missingTargetLabel,
  type DiscoveryProfile,
} from "../../../lib/discovery/search-target";
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

/**
 * Per-agent params for backend triggers.
 *
 * F-02: `scout` deliberately has NO entry. It used to carry a hardcoded
 * `{query: "software engineer", location: "Australia"}` sent for every
 * customer who pressed Run on the Scout card — the same defect as Job
 * Discovery's "Sync Now" hardcode, with a different literal. Scout's params
 * are now resolved per-run from the signed-in user's own profile in
 * `resolveScoutParams()` below, which refuses rather than invents one.
 */
const RUN_PARAMS: Record<string, Record<string, unknown>> = {
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
  const [stoppingAll, setStoppingAll] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [configProvider, setConfigProvider] = useState<Provider | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  // Job-alert intake (email agent `mode: "job_alerts"`) — its own busy/notice
  // pair so it never borrows the pipeline's wording or its spinner.
  const [alertsBusy, setAlertsBusy] = useState(false);
  const [alertsNotice, setAlertsNotice] = useState<{
    tone: "success" | "neutral" | "warning";
    headline: string;
    detail: string;
  } | null>(null);
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
    } catch (e) {
      setNotice(runErrorNotice(e, "Loading agents"));
      setCatalog((prev) => prev ?? { agents: [], counts: { total: 0, active: 0, paused: 0, error: 0 } });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // F-01 (ADR-F01-PROVIDER-CREDENTIAL-AUTHZ). GET /agents/providers exposes the
  // OPERATOR's deployment-wide credential state (source, last-4 secretHint,
  // verify timestamps) and is admin-only on the server. Resolve isAdmin FIRST —
  // from the same /auth/me source the AdminGuard and topbar already use — and
  // only then decide which endpoint to call, so a customer's browser never even
  // REQUESTS the operator's rows (a 403-after-click would still be too late:
  // the panel would have rendered "Manage" controls that can only fail).
  // `null` = not yet resolved; a failed lookup degrades to non-admin, the safe
  // direction, and the server gate is authoritative regardless.
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const me = await fetchMe();
        if (!cancelled) setIsAdmin(me.isAdmin);
      } catch {
        if (!cancelled) setIsAdmin(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // The provider panel, scoped to who is looking: the operator's shared
  // connections, or the customer's own keys. Deliberately NOT part of `load()`
  // above — it must not run until isAdmin is known, and a provider-panel
  // failure must not blank the agent catalog.
  const loadProviders = useCallback(async () => {
    if (isAdmin === null) return;
    try {
      setProviders(isAdmin ? await fetchProviders() : await fetchUserProviderCatalog());
    } catch (e) {
      setNotice(runErrorNotice(e, "Loading providers"));
      setProviders((prev) => prev ?? []);
    }
  }, [isAdmin]);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  // W-RT — the shared realtime channel. The in-flight poll below only runs
  // while THIS tab started a run; a run started by the scheduler, the worker or
  // another tab left these cards frozen. `agentRuns` watches the AgentRun row's
  // own createdAt/startedAt/completedAt, so every genuine transition lands here.
  useRealtimeResources(["agentRuns"], () => {
    void load();
  });

  // Load the live model catalog once for the per-agent pickers, WITH its
  // freshness envelope (ML-catalog-008/N1): the GET .../models response already
  // carries lastRefreshedAt/stale on every call, so surface the REAL backend
  // timestamp on initial load instead of a "not yet refreshed" placeholder.
  // fetchProviderCatalog returns that full envelope; if it yields no usable
  // payload we degrade to the narrower fetchProviderModels (models only, no
  // freshness) so the picker still populates. Never blocks the page: its own
  // loading/error state is local.
  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true);
    setCatalogError(null);
    try {
      const cat = await fetchProviderCatalog(CATALOG_PROVIDER);
      if (cat && Array.isArray(cat.models)) {
        setCatalogModels(cat.models);
        setCatalogRefreshedAt(cat.lastRefreshedAt);
        setCatalogStale(cat.stale);
      } else {
        setCatalogModels(await fetchProviderModels(CATALOG_PROVIDER));
      }
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

  /**
   * F-02 — Scout runs the SIGNED-IN user's own search, or it does not run.
   *
   * Returns the params, or `null` after posting an honest refusal notice. The
   * profile is re-read per run (rather than reused from the mount-time
   * `isAdmin` lookup) so a target role just saved in Settings takes effect
   * immediately. Nothing here manufactures a query: a user who has told us
   * nothing gets a message pointing at Settings, never someone else's search.
   */
  const resolveScoutParams = async (): Promise<Record<string, unknown> | null> => {
    let profile: DiscoveryProfile | null = null;
    try {
      const me = await fetchMe();
      profile = { targetRole: me.targetRole, location: me.location };
    } catch {
      setNotice({
        kind: "error",
        text: "Scout could not read your profile, so it has no target role to search for. Reload and try again — it will not run a guessed search.",
      });
      return null;
    }
    const target = deriveSearchTarget(profile);
    if (target.status !== "ready") {
      setNotice({
        kind: "error",
        text: `Scout has nothing to search for — your profile has no ${missingTargetLabel(target.missing)} set. Add it in Settings and Scout will search for exactly that.`,
        href: "/dashboard/settings",
        hrefLabel: "open Settings →",
      });
      return null;
    }
    return { query: target.query, location: target.location };
  };

  const trigger = async (backend: string) => {
    // Resolved BEFORE the "started" notice so a refusal never follows a claim
    // that the run began.
    let scoutParams: Record<string, unknown> | null = null;
    if (backend === "scout") {
      scoutParams = await resolveScoutParams();
      if (scoutParams === null) return;
    }
    setBusy(backend);
    setNotice({ kind: "info", text: `${backend} started — running now…` });
    startPolling("agent");
    try {
      const params = scoutParams ?? (await resolveParams(backend));
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

  /**
   * Run the Email Agent's job-alert intake from the console.
   *
   * Deliberately NOT routed through `trigger()`: that path sends
   * `RUN_PARAMS[backend]` (triage for emailAgent) and renders
   * `agentSuccessNotice`, which knows nothing about intake counts and would
   * report a scan in triage's words. This uses the shared intake client, so the
   * headline is derived from the run's OWN counts by the same rules as the
   * Email Center — including the honest degrade when no mailbox is connected.
   */
  const scanJobAlerts = async () => {
    setAlertsBusy(true);
    setAlertsNotice(null);
    try {
      const summary = await runJobAlertIntake();
      setAlertsNotice({
        tone: jobAlertTone(summary),
        headline: jobAlertHeadline(summary),
        detail: summary.message,
      });
    } catch (e) {
      setAlertsNotice({
        tone: "warning",
        headline: "The job-alert scan did not complete",
        detail: e instanceof Error ? e.message : "Unknown error.",
      });
    } finally {
      setAlertsBusy(false);
      // The intake records a real AgentRun row — refresh the audit table/stats
      // so the console reflects it without a reload.
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

  // H-06: a single kill-switch that pauses every currently-enabled agent.
  // There is no server-side "stop all" endpoint (each agent's enabled flag is
  // its own AgentConfig row), so this honestly pauses them one by one via the
  // same PATCH the per-agent toggle uses, then refreshes from the server so
  // the counts reflect the true post-stop state. Disabling an agent stops it
  // being scheduled/triggered; it does not force-kill an already-running run
  // (no cancel endpoint exists) — the notice says so.
  const onStopAll = async () => {
    const enabled = (catalog?.agents ?? []).filter((a) => a.enabled);
    if (enabled.length === 0) {
      setNotice({ kind: "info", text: "No agents are currently enabled." });
      return;
    }
    if (
      typeof window !== "undefined" &&
      !window.confirm(
        `Pause all ${enabled.length} enabled agent${enabled.length === 1 ? "" : "s"}? ` +
          "They will stop being scheduled. Runs already in progress finish on their own.",
      )
    ) {
      return;
    }
    setStoppingAll(true);
    let failed = 0;
    for (const agent of enabled) {
      try {
        await updateAgentConfig(agent.key, { enabled: false });
      } catch {
        failed += 1;
      }
    }
    try {
      const [cat, st] = await Promise.all([fetchCatalog(), fetchAgentStats()]);
      setCatalog(cat);
      setStats(st);
    } catch {
      // Leave the last-known catalog in place if the refresh itself fails.
    }
    setStoppingAll(false);
    if (failed === 0) {
      setNotice({
        kind: "success",
        text: `Paused ${enabled.length} agent${enabled.length === 1 ? "" : "s"}. New runs are on hold.`,
      });
    } else {
      setNotice({
        kind: "error",
        text: `Paused ${enabled.length - failed} of ${enabled.length} agents; ${failed} could not be paused. Try again.`,
      });
    }
  };

  // The provider card action opens the in-app credential configuration modal
  // (REQ-PC-1). There is no ".env editing" path and no doomed status-flip PUT:
  // credentials are entered, tested and removed entirely in the modal, which
  // then refreshes the honest DB-first provider list.
  const openConfig = (provider: Provider) => setConfigProvider(provider);

  const refreshProviders = useCallback(async () => {
    setProviderBusy(null);
    await loadProviders();
  }, [loadProviders]);

  const onProviderModel = async (id: string, model: string) => {
    setProviderBusy(id);
    try {
      await updateProvider(id, { model });
      await loadProviders();
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

  // CRITICAL-2. A run goes stale by the passage of time, not by any server
  // event, so this screen re-renders on a clock in addition to the realtime
  // refetch above; otherwise a run that dies while the console is open keeps
  // its "in progress" label until someone reloads.
  const now = useNow();
  const stalledRuns = runs.filter((r) => isStalledRun(r, now));
  // "This agent has produced nothing since <date>" — derived from the runs the
  // server actually returned. No agent name is hardcoded and nothing is
  // asserted about an agent absent from the window.
  const outputGaps = agentOutputGaps(runs, now);

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
          {/* The Email Agent's job-alert intake. The per-agent "Run" button
              below triggers TRIAGE (RUN_PARAMS.emailAgent) — before this
              control existed, `mode: "job_alerts"` was reachable from no user
              action anywhere, so a fully built backend sat dead. Deterministic
              on the server (regex/HTML parser, no model), so it is never
              metered and never invents a posting. */}
          <button
            type="button"
            data-testid="agents-scan-job-alerts"
            onClick={() => void scanJobAlerts()}
            disabled={alertsBusy}
            title="Read your own job-alert emails from the last 7 days and add the postings to your Jobs board"
            className="flex items-center gap-2 rounded-lg border border-aether-green/40 bg-aether-green/10 px-3.5 py-2 text-xs font-semibold text-aether-green transition hover:bg-aether-green/20 disabled:opacity-50"
          >
            {alertsBusy ? (
              <>
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-aether-green/40 border-t-aether-green" />
                Scanning job alerts…
              </>
            ) : (
              <>
                <i className="fa-solid fa-inbox text-[10px]" aria-hidden="true" />
                Scan Job Alerts
              </>
            )}
          </button>
          <button
            type="button"
            data-testid="stop-all-agents-btn"
            onClick={() => void onStopAll()}
            disabled={stoppingAll || busy !== null}
            title="Pause every enabled agent so no new runs are scheduled"
            className="flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3.5 py-2 text-xs font-semibold text-red-300 transition hover:bg-red-500/20 disabled:opacity-50"
          >
            {stoppingAll ? (
              <>
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-red-300/40 border-t-red-300" />
                Stopping…
              </>
            ) : (
              <>
                <i className="fa-solid fa-stop text-[10px]" aria-hidden="true" />
                Stop All Agents
              </>
            )}
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

      {stalledRuns.length > 0 ? (
        // CRITICAL-2. In production one tailor run sat at status='running' for
        // 192.6 hours with no process attached, and every surface rendered it
        // as active work — so the product concealed a week of total inactivity
        // behind a spinner. A run in flight for longer than the backend's own
        // staleness window (agents.py `_job_stale_thresholds`) has no worker
        // behind it; say so, say how long, and say what can be done. There is
        // no cancel endpoint for an AgentRun, so no clear/cancel action is
        // offered — only the one that genuinely exists, starting a new run.
        <div
          data-testid="agents-stalled-banner"
          role="alert"
          className="rounded-xl border border-aether-amber/40 bg-aether-amber/10 p-3 text-sm text-aether-amber"
        >
          <p className="font-semibold">
            {stalledRuns.length === 1
              ? "1 agent run is stalled — it is not making progress"
              : `${stalledRuns.length} agent runs are stalled — they are not making progress`}
          </p>
          <ul className="mt-1.5 space-y-1">
            {stalledRuns.slice(0, 5).map((r) => (
              <li key={r.id} className="font-mono text-xs">
                {r.agentName} · {stalledLabel(r, now)} · started{" "}
                {parseServerTime(r.startedAt ?? r.createdAt) !== null
                  ? new Date(
                      parseServerTime(r.startedAt ?? r.createdAt) as number,
                    ).toLocaleString("en-AU")
                  : "unknown"}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-aether-amber/90">{STALLED_RUN_ADVICE}</p>
        </div>
      ) : null}

      {outputGaps.length > 0 ? (
        // CRITICAL-2 item 3: an agent can look healthy while producing nothing
        // for days. Report the drought from the real run history rather than
        // letting an idle-looking green card imply work is happening.
        <div
          data-testid="agents-no-output"
          role="status"
          className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm text-aether-muted"
        >
          <p className="font-semibold text-aether-muted">Agents with no recent output</p>
          <ul className="mt-1.5 space-y-1 text-xs">
            {outputGaps.map((gap) => (
              <li key={gap.agent}>{outputGapMessage(gap, now)}</li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11px] text-aether-muted-dim">
            Measured over the {runs.length.toLocaleString()} most recent run
            {runs.length === 1 ? "" : "s"} this console loaded.
          </p>
        </div>
      ) : null}

      {alertsNotice ? (
        <p
          data-testid="agents-job-alerts-notice"
          data-tone={alertsNotice.tone}
          role={alertsNotice.tone === "warning" ? "alert" : "status"}
          className={`rounded-xl border p-3 text-sm ${
            alertsNotice.tone === "success"
              ? "border-aether-green/30 bg-aether-green/10 text-aether-green"
              : alertsNotice.tone === "warning"
                ? "border-amber-400/40 bg-amber-400/10 text-amber-200"
                : "border-white/10 bg-white/5 text-aether-muted"
          }`}
        >
          <span className="font-semibold">{alertsNotice.headline}</span>
          {alertsNotice.detail ? <span className="ml-2">{alertsNotice.detail}</span> : null}
          {alertsNotice.tone === "success" ? (
            <>
              {" "}
              <Link href="/dashboard/jobs" className="font-semibold underline underline-offset-2">
                Open your Jobs board
              </Link>
            </>
          ) : null}
        </p>
      ) : null}

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
        loading={providers === null || isAdmin === null}
        busyId={providerBusy}
        onConfigure={openConfig}
        onModel={(id, model) => void onProviderModel(id, model)}
        title={
          isAdmin === null
            ? "AI Providers"
            : isAdmin
              ? "AI Provider Connections"
              : "Your AI Provider Keys"
        }
        blurb={
          isAdmin === false
            ? "Keys you add here are yours alone, stored encrypted. Runs on a provider you have supplied a key for bill to your own account."
            : undefined
        }
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
                      {coverLetterDegraded(run) ? (
                        // QA3-F-03: a letterless coverLetter degrade is
                        // recorded status='completed' (GAP-P4-002 — the
                        // guard working is not a failure), but rendering it
                        // as a plain green "completed" is indistinguishable
                        // from a real letter — match the honest, neutral
                        // "Unavailable" treatment the dashboard feed already
                        // uses for this exact run shape.
                        <span className="text-aether-muted">Unavailable</span>
                      ) : isStalledRun(run, now) ? (
                        // CRITICAL-2: never print the raw "running" for a row
                        // whose worker is gone — that word is what convinced
                        // the owner an agent had been grinding for hours.
                        <span className="text-aether-amber" title={STALLED_RUN_ADVICE}>
                          {stalledLabel(run, now)}
                        </span>
                      ) : (
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
                      )}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-aether-muted">
                      {/* parseServerTime, not `new Date`: the API's naive UTC
                          stamps carry no timezone designator, so a bare parse
                          renders them in the viewer's offset — ten hours out
                          for this product's en-AU owner. */}
                      {parseServerTime(run.startedAt) !== null
                        ? new Date(parseServerTime(run.startedAt) as number).toLocaleString("en-AU")
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-aether-muted-dim">
                      {humanizeActivityMessage(run.error) || "—"}
                    </td>
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
        // Explicitly `=== true`: while isAdmin is still unresolved the safe
        // default is the per-user store, never the operator's.
        scope={isAdmin === true ? "deployment" : "user"}
      />
    </div>
  );
}
