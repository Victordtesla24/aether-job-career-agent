"use client";

/**
 * Manage Agents console (wireframe: design/screens/agents.html; restructured in
 * S-UI-1 §4.1).
 *
 * ── WHY THIS PAGE IS TABBED ────────────────────────────────────────────────
 * The page conflates three jobs — *connect providers*, *configure 22 agents*,
 * *watch the system run* — and used to present all three in one ~6 400px
 * scroll, ordered worst-first: provider config occupied the first ~1 700px and
 * the orchestration content (the product's actual differentiator) sat at
 * ~4 900px, below everything. One route, three linkable tabs (`?tab=`), with
 * ORCHESTRATION as the default, puts the differentiator first and gives each
 * job a whole screen.
 *
 * Tabs, in order:
 *  1. Orchestration (default) — run-health strip, the workflow map(s), the live
 *     run monitor (task queue / performance / error log) and the recent-runs
 *     audit table.
 *  2. Agents — the full catalog grid, filterable, plus the run/spend stats row.
 *  3. Providers — AI provider connections and the provider-default model.
 *
 * ZERO-REGRESSION NOTE (S-UI binding constraint 1): every panel stays MOUNTED
 * and is hidden with the `hidden` attribute rather than unmounted. That keeps
 * the page's request behaviour byte-identical to before (the same fetches on
 * mount, the same polling, the same realtime subscription — a tab switch
 * issues no request at all) and keeps every control keyboard-reachable the
 * instant its tab is shown.
 *
 * Every control is wired to a real endpoint — nothing is mock. The full
 * pipeline ("Run pipeline") is a synchronous ~30–120 s call, so the UI streams live
 * progress and a completion/failure notice (see lib/agents-feedback).
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// S-UI AESTHETICS BAR — the console's page-scoped presentation layer. Every
// selector in it is `ag-`-prefixed and anchored under `.ag-console`, so it
// cannot restyle another route; nothing in it changes what this page says.
import "./agents-console.css";

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
  isInFlight,
  isLiveRun,
  isStalledRun,
  outputGapMessage,
  parseServerTime,
  stalledLabel,
  STALLED_RUN_ADVICE,
} from "../../../lib/agent-run-health";
import SegmentedControl from "../../../components/ui/SegmentedControl";
import { useUrlTab } from "../../../hooks/useUrlTab";
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
import OrchestrationMap from "../../../components/agents/OrchestrationMap";
import ConductorBand from "../../../components/agents/ConductorBand";
import ConductorRail from "../../../components/agents/ConductorRail";
import { useRunEverything } from "../../../components/agents/use-run-everything";
import {
  RUN_PIPELINE_LABEL,
  type SupervisorConfig,
} from "../../../components/agents/conductor";
import RunPolicyInputs from "../../../components/agents/RunPolicyInputs";
import {
  fetchOrchestrationMap,
  type OrchestrationMapData,
} from "../../../lib/api/agentPolicy";
import {
  fetchOrchestrationPlan,
  type OrchestrationPlan,
} from "../../../lib/api/orchestrationPlan";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import ProviderConnections from "../../../components/agents/ProviderConnections";
import ModelPicker from "../../../components/agents/ModelPicker";
import ProviderConfigModal from "../../../components/agents/ProviderConfigModal";
import AgentConfigGrid from "../../../components/agents/AgentConfigGrid";
import AgentStatsRow from "../../../components/agents/AgentStats";
import LowCreditBanner from "../../../components/agents/LowCreditBanner";
import TestRunModal from "../../../components/agents/TestRunModal";
import {
  fetchAgentConfig,
  fetchAgentStats,
  fetchCatalog,
  fetchOpenRouterCredits,
  fetchProviderCatalog,
  fetchProviderModels,
  fetchProviders,
  fetchUserProviderCatalog,
  refreshProviderModels,
  updateAgentConfig,
  updateProvider,
  type AgentStats,
  type Catalog,
  type OpenRouterCredits,
  type Provider,
  type ProviderModel,
} from "../../../components/agents/api";
import { fetchMe } from "../../../lib/api/admin";
import {
  deriveSearchTarget,
  missingTargetLabel,
  type DiscoveryProfile,
} from "../../../lib/discovery/search-target";
import { ApiError, describeApiError } from "../../../lib/api/client";
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

/** S-UI §4.1 — three linkable tabs; Orchestration is the default view. */
const TABS = ["orchestration", "agents", "providers"] as const;
type AgentsTab = (typeof TABS)[number];

const TAB_ITEMS: ReadonlyArray<{ value: AgentsTab; label: string; icon: string }> = [
  { value: "orchestration", label: "Orchestration", icon: "fa-diagram-project" },
  { value: "agents", label: "Agents", icon: "fa-robot" },
  { value: "providers", label: "Providers", icon: "fa-plug" },
];

//: The provider whose LIVE catalog backs the per-agent pickers. OpenRouter is
//: the only provider exposing an open /models catalog (the direct-Anthropic
//: list is static); a per-agent pick of an OpenRouter model routes THAT agent
//: through OpenRouter (billing implication is explicit — resolve_provider on
//: the backend keys off the id, unchanged).
const CATALOG_PROVIDER = "openrouter";

//: ML-U1X-b — the provider whose static curated catalog backs both (a) the
//: Anthropic provider card's own model select and (b) the Orchestrator role's
//: default/downshift options. Credential-independent (GET .../models answers
//: unconditionally), so this is fetched unconditionally on mount, same as
//: `CATALOG_PROVIDER` above.
const ANTHROPIC_PROVIDER = "anthropic";

//: P1-B — the catalog key of the supervisor card (backend `supervisor`). Its
//: AgentConfig is what the Conductor band reads its model binding from, so the
//: key lives in one place rather than in a string literal per call site.
const ORCHESTRATION_AGENT_KEY = "orchestration";

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
  // ML-U1X-b: Anthropic's live curated catalog — feeds the anthropic provider
  // card's model select AND the Orchestrator role's picker (both need real
  // ids + pricing, neither the shared OpenRouter `catalogModels` above).
  const [anthropicModels, setAnthropicModels] = useState<ProviderModel[] | null>(null);
  const [anthropicModelsLoading, setAnthropicModelsLoading] = useState(true);
  const [anthropicModelsError, setAnthropicModelsError] = useState<string | null>(null);
  // ML-U1X-b: the deployment's real remaining OpenRouter credit (operator-only
  // proxy) — `null` before the first read resolves, so the banner stays
  // hidden rather than flashing "unavailable" during initial load.
  const [credits, setCredits] = useState<OpenRouterCredits | null>(null);
  // U-AX item 5: all 22 catalog agents in their defined workflow map(s),
  // honest real-vs-planned status. Loaded independently so its own failure
  // never blanks the rest of the console.
  const [orchestrationMap, setOrchestrationMap] = useState<OrchestrationMapData | null>(null);
  // P1-B CONDUCTOR: the Supervisor's plan, read BEFORE anything runs (it costs
  // $0 — the endpoint dispatches nothing). Its own state triple, because the
  // band must be able to say "not read yet" and "the read failed, here is the
  // server's sentence" as two different things.
  const [orchestrationPlan, setOrchestrationPlan] = useState<OrchestrationPlan | null>(null);
  const [planFetchedAt, setPlanFetchedAt] = useState<number | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  // The orchestration agent's own AgentConfig — the ONLY honest source for
  // "which credential does the supervisor consume", which the catalog row
  // (model only) cannot answer.
  const [supervisorConfig, setSupervisorConfig] = useState<SupervisorConfig | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const runStartedAt = useRef<number>(0);
  // Wraps the Conductor band AND the workflow maps, so the rail can be measured
  // between them (a band cannot draw into a map from inside its own panel).
  const conductorStackRef = useRef<HTMLDivElement | null>(null);

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

  // U-AX item 5: independent load (its own failure must not blank the agent
  // catalog above) — not part of `load()`/polling since the map itself only
  // changes on a new run, not every 3s tick.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const map = await fetchOrchestrationMap();
        if (!cancelled) setOrchestrationMap(map);
      } catch {
        if (!cancelled) setOrchestrationMap(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // P1-B: the Supervisor's plan. Independent of `load()` for the same reason
  // the map is — its failure must not blank the console — and re-read on demand
  // (`loadPlan`) so the band's counts follow the server rather than a snapshot
  // taken once at mount.
  const loadPlan = useCallback(async () => {
    try {
      const plan = await fetchOrchestrationPlan();
      setOrchestrationPlan(plan);
      setPlanFetchedAt(Date.now());
      setPlanError(null);
    } catch (e) {
      // The plan is not shown at all rather than shown stale: a count that no
      // longer matches the server is the one thing this band may not print.
      setOrchestrationPlan(null);
      setPlanFetchedAt(null);
      setPlanError(describeApiError(e, "The plan endpoint did not answer."));
    }
  }, []);

  useEffect(() => {
    void loadPlan();
  }, [loadPlan]);

  // The orchestration agent's live config (provider + auth mode). A failure
  // leaves it null, and the band then says the binding has not been read —
  // never a placeholder model.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const cfg = await fetchAgentConfig(ORCHESTRATION_AGENT_KEY);
        if (!cancelled) {
          setSupervisorConfig({
            key: cfg.key,
            model: cfg.model,
            provider: cfg.provider ?? null,
            authMode: cfg.authMode ?? null,
          });
        }
      } catch {
        if (!cancelled) setSupervisorConfig(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

  // ML-U1X-b: Anthropic's static curated catalog (RCA: a working 3-model
  // catalog already existed at GET /agents/providers/anthropic/models, but
  // nothing in the FE ever called it — only OpenRouter's live catalog above
  // was fetched). Credential-independent, so this is unconditional on mount,
  // mirroring `loadCatalog`. Feeds the anthropic provider card AND the
  // Orchestrator role picker (see AgentConfigGrid `orchestratorModels`).
  const loadAnthropicModels = useCallback(async () => {
    setAnthropicModelsLoading(true);
    setAnthropicModelsError(null);
    try {
      setAnthropicModels(await fetchProviderModels(ANTHROPIC_PROVIDER));
    } catch (e) {
      setAnthropicModelsError(catalogErrorText(e));
    } finally {
      setAnthropicModelsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAnthropicModels();
  }, [loadAnthropicModels]);

  // ML-U1X-b (retired-U1 spec (d)): the deployment's real remaining OpenRouter
  // credit — operator-only (the proxy endpoint is admin-gated, same as
  // `fetchProviders`), so this never even attempts the call for a non-admin
  // customer. A failed read still resolves to an honest `{available:false}`
  // reading rather than leaving `credits` at `null` forever (which the banner
  // would otherwise render identically to "still loading").
  useEffect(() => {
    if (isAdmin !== true) return;
    let cancelled = false;
    void (async () => {
      try {
        const c = await fetchOpenRouterCredits();
        if (!cancelled) setCredits(c);
      } catch {
        if (!cancelled) setCredits({ available: false, remaining: null, total: null, asOf: null });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

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

  // The supervisor's catalog row — its NAME and the model the server says it
  // actually runs on. Null until the catalog loads, so the band says "not read
  // yet" rather than printing a model nobody has confirmed.
  const supervisorAgent = useMemo(() => {
    const row = catalog?.agents.find((a) => a.key === ORCHESTRATION_AGENT_KEY);
    return row ? { key: row.key, name: row.name, model: row.model } : null;
  }, [catalog]);

  // P1-B — "Run everything": ONE server-recorded plan over all three workflows.
  // Deliberately NOT folded into `busy`/`pipeline` above: that pair models a
  // SYNCHRONOUS call this tab is holding open, while a plan runs on the queue
  // and outlives this tab. The hook watches the recorded plan row instead, and
  // the console's one-run-at-a-time rule is still enforced where it is real —
  // on the server (the plan admission claim and the silo index).
  const runEverything = useRunEverything();
  const planPhase = runEverything.state.phase;

  // A settled plan changed the run history and every card's last-run state, so
  // re-read both — the same refresh a finished single run performs.
  useEffect(() => {
    if (planPhase !== "settled") return;
    void load();
    void loadPlan();
  }, [planPhase, load, loadPlan]);

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
   * Returns the params, or the honest REFUSAL notice explaining why there are
   * none. The profile is re-read per run (rather than reused from the mount-time
   * `isAdmin` lookup) so a target role just saved in Settings takes effect
   * immediately. Nothing here manufactures a query: a user who has told us
   * nothing gets a message pointing at Settings, never someone else's search.
   *
   * ORCH-RUN: the refusal is RETURNED rather than only posted to the banner, so
   * `trigger` can hand it back to whichever surface asked for the run — the
   * workflow map quotes it on the node it refused, verbatim, instead of showing
   * a node that silently did nothing.
   */
  const resolveScoutParams = async (): Promise<
    { params: Record<string, unknown> } | { refusal: Notice }
  > => {
    let profile: DiscoveryProfile | null = null;
    try {
      const me = await fetchMe();
      profile = { targetRole: me.targetRole, location: me.location };
    } catch {
      return {
        refusal: {
          kind: "error",
          text: "Scout could not read your profile, so it has no target role to search for. Reload and try again — it will not run a guessed search.",
        },
      };
    }
    const target = deriveSearchTarget(profile);
    if (target.status !== "ready") {
      return {
        refusal: {
          kind: "error",
          text: `Scout has nothing to search for — your profile has no ${missingTargetLabel(target.missing)} set. Add it in Settings and Scout will search for exactly that.`,
          href: "/dashboard/settings",
          hrefLabel: "open Settings →",
        },
      };
    }
    return { params: { query: target.query, location: target.location } };
  };

  /**
   * Dispatch ONE agent, and return the truthful notice that describes how it
   * ended — the same object that goes into the banner.
   *
   * The return value is what makes the orchestration map's per-node / selection
   * / whole-map run controls possible without a second run path: they await
   * this, quote its text on the node, and (for a batch) stop on the first
   * `kind: "error"` exactly as `_pipeline_core` stops on the first exception.
   */
  const trigger = async (backend: string): Promise<Notice> => {
    // Resolved BEFORE the "started" notice so a refusal never follows a claim
    // that the run began.
    let scoutParams: Record<string, unknown> | null = null;
    if (backend === "scout") {
      const resolved = await resolveScoutParams();
      if ("refusal" in resolved) {
        setNotice(resolved.refusal);
        return resolved.refusal;
      }
      scoutParams = resolved.params;
    }
    setBusy(backend);
    setNotice({ kind: "info", text: `${backend} started — running now…` });
    startPolling("agent");
    let outcome: Notice;
    try {
      const params = scoutParams ?? (await resolveParams(backend));
      // MON-020: a scout pass really takes minutes (production discovery-cron
      // measurement: 255-473s typical, 968s worst case) while Cloudflare aborts
      // the request at ~100s. Run it through the endpoint's background mode —
      // `runAgent` still awaits the real terminal result via `resolveRun`, so
      // the success/failure notice below means exactly what it did before.
      const output = await runAgent(
        AGENT_ROUTE[backend] ?? backend,
        params,
        {},
        { background: backend === "scout" },
      );
      outcome = missingResumeNotice(output) ?? agentSuccessNotice(backend, output);
      setNotice(outcome);
    } catch (e) {
      outcome = runErrorNotice(e, backend);
      setNotice(outcome);
    } finally {
      // Unchanged ordering: the outcome notice is posted BEFORE the refresh, so
      // a refresh that itself fails still gets to replace it with its own
      // honest "Loading agents failed" message rather than being overwritten.
      stopPolling();
      setBusy(null);
      await load();
    }
    return outcome;
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

  // S-UI §4.1 RUN HEALTH strip. Every number is derived from data already on
  // screen — agents online from GET /agents, live/stalled from the SAME
  // `isInFlight && isLiveRun` predicates the run monitor obeys (CRITICAL-2).
  // There is no uptime signal in this product, so no uptime % is shown.
  const agentsOnline = agents.filter((a) => a.status !== "offline").length;
  const liveRunCount = runs.filter((r) => isInFlight(r) && isLiveRun(r, now)).length;

  const [tab, setTab] = useUrlTab<AgentsTab>(TABS, "orchestration");
  const [overflowOpen, setOverflowOpen] = useState(false);
  const overflowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!overflowOpen) return;
    const onDown = (e: MouseEvent) => {
      if (overflowRef.current && !overflowRef.current.contains(e.target as Node)) {
        setOverflowOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOverflowOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [overflowOpen]);

  const tabItems = useMemo(
    () =>
      TAB_ITEMS.map((t) =>
        t.value === "agents"
          ? { ...t, count: catalog ? catalog.counts.total : null }
          : t.value === "providers"
            ? { ...t, count: providers ? providers.length : null }
            : t,
      ),
    [catalog, providers],
  );

  /** Inactive panels stay mounted (see the file header) but are removed from
   *  the a11y tree and from layout by the `hidden` attribute. */
  const panelProps = (value: AgentsTab) => ({
    id: `agents-panel-${value}`,
    role: "tabpanel" as const,
    "aria-labelledby": `agents-tabs-${value}`,
    hidden: tab !== value,
    "data-testid": `agents-panel-${value}`,
  });

  return (
    <div className="ag-console space-y-7">
      {/* `ag-hero` carries the fold's atmosphere: a wide, very low-opacity
          coral wash behind the title and a cooler counter-light opposite it,
          both inert (`pointer-events:none`, laid out inside the content
          column) so neither can be clicked or scrolled into. */}
      <header className="ag-hero flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {/* Rule 3 — the ONE saturated gesture on this fold. */}
          <h1 className="ag-title">Manage Agents</h1>
          <p className="ag-subline mt-1.5 font-mono text-aether-muted-dim">
            {agentCount} agents · {providerCount} AI providers · configure models &amp; connections
          </p>
        </div>
        {/* S-UI §4.1: ONE primary action (coral). Everything else is a ghost of
            equal weight, and the destructive bulk action moves into an overflow
            menu — it used to sit in the header at full red weight, competing
            with "Run pipeline" for the eye. The menu is always mounted (hidden, not
            unmounted) so every control stays keyboard-reachable and no
            automation has to guess whether it exists. */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="test-run-open"
            onClick={() => setTestOpen(true)}
            className="flex items-center gap-2 rounded-md border border-hairline bg-surface-1 px-3 py-2 text-[12px] font-medium outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70 active:translate-y-px"
          >
            <i className="fa-solid fa-vial text-[10px] text-aether-indigo" aria-hidden="true" />
            Test Run
          </button>
          {/* The Email Agent's job-alert intake. The per-agent "Run" button
              triggers TRIAGE (RUN_PARAMS.emailAgent) — before this control
              existed, `mode: "job_alerts"` was reachable from no user action
              anywhere, so a fully built backend sat dead. Deterministic on the
              server (regex/HTML parser, no model), so it is never metered and
              never invents a posting. */}
          <button
            type="button"
            data-testid="agents-scan-job-alerts"
            onClick={() => void scanJobAlerts()}
            disabled={alertsBusy}
            title="Read your own job-alert emails from the last 7 days and add the postings to your Jobs board"
            className="flex items-center gap-2 rounded-md border border-hairline bg-surface-1 px-3 py-2 text-[12px] font-medium outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
          >
            {alertsBusy ? (
              <>
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-aether-green/40 border-t-aether-green" />
                Scanning job alerts…
              </>
            ) : (
              <>
                <i className="fa-solid fa-inbox text-[10px] text-aether-green" aria-hidden="true" />
                Scan Job Alerts
              </>
            )}
          </button>
          <button
            type="button"
            data-testid="run-pipeline-btn"
            onClick={() => void pipeline()}
            disabled={busy !== null}
            className="flex items-center gap-2 rounded-md bg-aether-coral px-4 py-2 text-[12px] font-semibold outline-none transition-opacity duration-[var(--dur-fast)] hover:opacity-90 focus-visible:ring-2 focus-visible:ring-aether-coral/70 focus-visible:ring-offset-2 focus-visible:ring-offset-aether-bg active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "pipeline" ? (
              <>
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-black/30 border-t-black/70" />
                Running…
              </>
            ) : (
              <>
                <i className="fa-solid fa-play text-[10px]" aria-hidden="true" />
                {/* ADR-AGI-3 Decision 2 — was "Run All", which named a set it
                    does not run: this control runs the SEQUENTIAL pipeline
                    (`_PIPELINE_PLAN`, 5 steps), while the Conductor band's
                    "Run everything" runs all 19 dispatches. Two controls named
                    alike over different sets is the named failure mode. */}
                {RUN_PIPELINE_LABEL}
              </>
            )}
          </button>
          <div className="relative" ref={overflowRef}>
            <button
              type="button"
              data-testid="agents-overflow-btn"
              aria-haspopup="menu"
              aria-expanded={overflowOpen}
              aria-label="More agent actions"
              onClick={() => setOverflowOpen((v) => !v)}
              className="flex h-9 w-9 items-center justify-center rounded-md border border-hairline bg-surface-1 outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70"
            >
              <i className="fa-solid fa-ellipsis text-[12px]" aria-hidden="true" />
            </button>
            <div
              role="menu"
              aria-label="More agent actions"
              hidden={!overflowOpen}
              className="elev-3 absolute right-0 top-full z-40 mt-1 w-[240px] rounded-lg p-1"
            >
              <button
                type="button"
                role="menuitem"
                data-testid="add-provider-btn"
                onClick={() => {
                  setOverflowOpen(false);
                  void onAddProvider();
                }}
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[12px] font-medium outline-none hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70"
              >
                <i className="fa-solid fa-plus w-4 text-[10px]" aria-hidden="true" />
                Add Provider
              </button>
              <button
                type="button"
                role="menuitem"
                data-testid="stop-all-agents-btn"
                onClick={() => {
                  setOverflowOpen(false);
                  void onStopAll();
                }}
                disabled={stoppingAll || busy !== null}
                title="Pause every enabled agent so no new runs are scheduled"
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[12px] font-semibold text-state-danger outline-none hover:bg-state-danger/10 focus-visible:ring-2 focus-visible:ring-aether-coral/70 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {stoppingAll ? (
                  <>
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-state-danger/40 border-t-state-danger" />
                    Stopping…
                  </>
                ) : (
                  <>
                    <i className="fa-solid fa-stop w-4 text-[10px]" aria-hidden="true" />
                    Stop All Agents
                  </>
                )}
              </button>
            </div>
          </div>
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

      <LowCreditBanner credits={credits} />

      <SegmentedControl
        items={tabItems}
        value={tab}
        onChange={setTab}
        ariaLabel="Agents console sections"
        idPrefix="agents-tabs"
        panelIdPrefix="agents-panel"
        testId="agents-tabs"
      />

      {/* ══ TAB 1 — ORCHESTRATION (default) ═══════════════════════════════ */}
      <div {...panelProps("orchestration")} className="space-y-6">
        {/* RUN HEALTH. `aria-live="polite"` so a run starting or dying is
            announced without stealing focus. No fabricated uptime %: this
            product has no uptime signal, so the strip reports only what is
            genuinely measured — agents online, live runs, stalled runs. */}
        {/* Rule 4 (numerals get their own typographic treatment): the three
            counts are now the Mercury/Amplitude figure-over-label pair — a big
            tabular figure with a small grey caption — instead of three 13px
            runs of body copy. The dots, the words and the sample-window
            disclosure are unchanged. */}
        <div
          data-testid="agents-run-health"
          role="status"
          aria-live="polite"
          className="ag-rail flex flex-wrap items-center gap-x-7 gap-y-4 px-5 py-4"
        >
          <span className="ag-stat">
            <span className="ag-stat-figure">
              <span className="mr-2.5 inline-block h-1.5 w-1.5 rounded-full bg-state-ok align-middle" aria-hidden="true" />
              {agentsOnline}
            </span>
            <span className="ag-stat-label">online</span>
          </span>
          <span className="ag-rail-sep" aria-hidden="true" />
          <span className="ag-stat">
            <span className="ag-stat-figure">
              {liveRunCount > 0 ? (
                <span
                  className="live-dot mr-2.5 inline-block h-1.5 w-1.5 rounded-full bg-aether-coral align-middle"
                  aria-hidden="true"
                />
              ) : (
                <span
                  className="mr-2.5 inline-block h-1.5 w-1.5 rounded-full bg-state-neutral align-middle"
                  aria-hidden="true"
                />
              )}
              {liveRunCount}
            </span>
            <span className="ag-stat-label">running</span>
          </span>
          <span className="ag-rail-sep" aria-hidden="true" />
          <span className={`ag-stat ${stalledRuns.length > 0 ? "text-state-warn" : ""}`}>
            <span className={`ag-stat-figure ${stalledRuns.length > 0 ? "text-state-warn" : ""}`}>
              <span
                className={`mr-2.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${stalledRuns.length > 0 ? "bg-state-warn" : "bg-state-neutral"}`}
                aria-hidden="true"
              />
              {stalledRuns.length}
            </span>
            <span className={`ag-stat-label ${stalledRuns.length > 0 ? "text-state-warn" : ""}`}>
              stalled
            </span>
          </span>
          <span className="ml-auto max-w-[280px] text-right text-[11px] leading-[1.5] text-aether-muted-dim">
            Counted from the {runs.length.toLocaleString()} most recent run
            {runs.length === 1 ? "" : "s"} this console loaded.
          </span>
        </div>

        {/* ── P1-B CONDUCTOR STACK ─────────────────────────────────────────
            The Conductor band and the maps it conducts share one positioned
            wrapper so the rail can be MEASURED between them (ADR-AGI-3
            Decision 2: structural manages-edges from the band into each map's
            header, drawn in the U-STORY-3a linkage language). The rail is
            decorative; the same claim is stated in words inside the band. */}
        <div ref={conductorStackRef} className="relative space-y-6">
          <ConductorRail wrapperRef={conductorStackRef} maps={orchestrationMap} />
          <ConductorBand
            plan={orchestrationPlan}
            planFetchedAt={planFetchedAt}
            planError={planError}
            maps={orchestrationMap}
            supervisorConfig={supervisorConfig}
            supervisorAgent={supervisorAgent}
            runs={runs}
            run={runEverything.state}
            onRunEverything={() => void runEverything.run()}
            onDismissRun={runEverything.dismiss}
            busyBackend={busy}
          />

        {/* U-AX item 5 / S-UI §4.1: the defined end-to-end workflow map(s) —
            every catalog agent, honest real-vs-planned status, stage role,
            metrics consumed, threshold responsibilities, last-run tier +
            trend. DISTINCT from the live run monitor below. `runs` is passed
            so an edge can pulse ONLY where a run is genuinely in flight. */}
        {orchestrationMap ? (
          <section className="space-y-3.5">
            <div>
              <h2 className="ag-eyebrow">
                <span>Agent Orchestration — Workflow Maps</span>
              </h2>
              <p className="mt-2 max-w-[86ch] text-[13px] leading-[1.6] text-aether-muted">
                Every agent in the catalog, placed in the workflow it actually plays a part in —
                real agents show what they consume and improve on; planned agents are labelled
                roadmap stages, never shown as running. Run one agent, select several, or run a
                whole map in its stage order; results appear on each node and in the banner above.
              </p>
            </div>
            {/* ORCH-RUN: the map's run controls dispatch through THIS page's
                existing `trigger(backend)` — the same call the per-agent Run
                button on the Agents tab makes, with the same quota checks, the
                same polling and the same truthful banner. `busy` is handed over
                so the map refuses a second run while the console is already
                running something (Run pipeline included), exactly as Run
                pipeline does. */}
            <OrchestrationMap
              data={orchestrationMap}
              runs={runs}
              onRunAgent={trigger}
              busyBackend={busy}
            />
          </section>
        ) : null}
        </div>

        <Orchestration agents={agents} runs={runs} />

        <section className="space-y-3.5">
          <h2 className="ag-eyebrow">
            <span>Recent runs</span>
          </h2>
          {runs.length === 0 ? (
            <div className="ag-panel p-6 text-center text-[13px] text-aether-muted">
              No agent runs recorded yet.
            </div>
          ) : (
            <div className="ag-panel-sunken overflow-x-auto">
              {/* Rule 6/13: hairline row separators only, and row heights back
                  inside the 28–48px band every real dashboard in the reference
                  set uses. The measured before-state was 359px per row —
                  twenty paragraph-height slabs — caused entirely by the policy
                  column below. */}
              <table className="ag-table text-left text-[13px]" data-testid="agent-runs-table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Error</th>
                  {/* U-AX item 2(b)/5: per-run "policy inputs consumed" — the
                      metric snapshot the agent sourced and the resulting
                      rigor level, honest "not recorded" for pre-instrumentation
                      runs. */}
                  <th>Policy</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 20).map((run) => (
                  <tr key={run.id}>
                    <td className="whitespace-nowrap font-medium">{run.agentName}</td>
                    <td className="whitespace-nowrap">
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
                    <td className="whitespace-nowrap font-mono text-[11px] tabular-nums text-aether-muted">
                      {/* parseServerTime, not `new Date`: the API's naive UTC
                          stamps carry no timezone designator, so a bare parse
                          renders them in the viewer's offset — ten hours out
                          for this product's en-AU owner. */}
                      {parseServerTime(run.startedAt) !== null
                        ? new Date(parseServerTime(run.startedAt) as number).toLocaleString("en-AU")
                        : "—"}
                    </td>
                    {/* S-UI §3.4: a raw error string used to run the full width
                        of the viewport. Clamped with the full text in `title` —
                        clamped, never truncated away. */}
                    <td className="max-w-[280px] text-[11px] leading-[1.45] text-aether-muted-dim">
                      <span
                        title={humanizeActivityMessage(run.error) || undefined}
                        className="line-clamp-1 block"
                      >
                        {humanizeActivityMessage(run.error) || "—"}
                      </span>
                    </td>
                    <td className="max-w-[340px]">
                      {/* SUI1-P1 density fix: the policy paragraph is CLAMPED to
                          one line and given a real disclosure — every word stays
                          in the DOM, in `title`, and one click away. */}
                      <RunPolicyInputs run={run} variant="row" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          )}
        </section>
      </div>

      {/* ══ TAB 2 — AGENTS ════════════════════════════════════════════════ */}
      <div {...panelProps("agents")} className="space-y-6">
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
          orchestratorModels={anthropicModels}
          orchestratorModelsLoading={anthropicModelsLoading}
          orchestratorModelsError={anthropicModelsError}
          catalogRefreshedAt={catalogRefreshedAt}
          catalogStale={catalogStale}
          catalogRefreshing={catalogRefreshing}
          onRefreshCatalog={() => void onRefreshCatalog()}
          savingModelKey={savingModelKey}
          onSelectModel={(key, model) => void onSelectModel(key, model)}
        />

        <AgentStatsRow stats={stats} loading={stats === null} />
      </div>

      {/* ══ TAB 3 — PROVIDERS ═════════════════════════════════════════════ */}
      <div {...panelProps("providers")} className="space-y-6">
        <ProviderConnections
          providers={providers ?? []}
          loading={providers === null || isAdmin === null}
          busyId={providerBusy}
          onConfigure={openConfig}
          onModel={(id, model) => void onProviderModel(id, model)}
          anthropicModels={anthropicModels}
          anthropicModelsError={anthropicModelsError}
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

        {/* The per-agent pickers on the Agents tab browse this same live
            catalog, so the browsing surface no longer needs a second home on
            this tab — but this control does something the per-agent pickers
            cannot: it sets the PROVIDER-GLOBAL default (PUT
            /agents/providers/{id}), which is the model every agent without its
            own override runs on. It is deliberately retained (S-UI §4.1 Tab 3
            proposed removing it; removing it would delete the only UI for that
            endpoint, which the zero-regression constraint forbids) and given an
            explicit heading so the two scopes can no longer be confused. */}
        {openrouterProvider ? (
          <section className="space-y-2" data-testid="provider-default-model">
            <div>
              <h2 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">
                Provider default model
              </h2>
              <p className="mt-0.5 text-[11px] leading-[1.5] text-aether-muted-dim">
                The fallback every agent uses when it has no model of its own. To give ONE agent a
                different model, open that agent&apos;s model picker on the Agents tab —
                {catalogModels && catalogModels.length > 0 ? (
                  <>
                    {" "}
                    <span className="font-mono tabular-nums">{catalogModels.length}</span> models are
                    available there.
                  </>
                ) : (
                  " the full live catalog is available there."
                )}
              </p>
            </div>
            <ModelPicker
              provider={openrouterProvider}
              onSaved={refreshProviders}
              onNotice={setNotice}
            />
          </section>
        ) : null}
      </div>

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
