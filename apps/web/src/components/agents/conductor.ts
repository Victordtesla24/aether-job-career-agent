/**
 * P1-B CONDUCTOR — the pure logic behind the Conductor band.
 *
 * ADR-AGI-3 Decision 2, with the owner's 2026-08-14 addendum: the Supervisor
 * is the CONDUCTOR of the operating loop, and the UI has to show that.
 *
 * THE HONESTY RULES THIS MODULE ENCODES (they are why it exists):
 *
 *  1. NO COUNT IS EVER INVENTED. "Run everything (19 agents / 21 cards)" reads
 *     `agentCount`/`cardCount` off GET /agents/orchestration/plan; with no plan
 *     read, the control carries NO number at all rather than a plausible one.
 *  2. THE ACTIVE MODEL BINDING IS THE LIVE ONE. The chip is built from the
 *     orchestration agent's own AgentConfig / catalog row. The ADR's example
 *     ("claude-opus-4-8") is an example — it may never be substituted for a
 *     config the console has not read. Unread ⇒ say unread.
 *  3. THE FALLBACK CHAIN IS A CHAIN, NOT A STATE. Its ORDER is the ADR
 *     constant (Anthropic subscription → OpenRouter → Abacus.ai → Google); the
 *     chips say what would happen on quota exhaustion, and only a run that
 *     RECORDED a substitution (`servedModel` ≠ `requestedModel`) can put a
 *     "served by fallback" chip on screen.
 *  4. CREDENTIALS NEVER CROSS PROVIDERS. When a config carries no provider,
 *     the label is resolved by the SAME rule the server bills on
 *     (llm_client.resolve_provider): a `/` in the id is an OpenRouter id, a
 *     bare `claude-*` is direct Anthropic. Nothing here re-decides billing; it
 *     only names what the server would do.
 *  5. WORKFLOW NAMES COME FROM THE PAYLOAD. Maps are named by
 *     GET /agents/orchestration-map, so a backend that renames or re-groups a
 *     workflow moves this UI with it, and a card the maps do not place is
 *     DISCLOSED rather than dropped into whichever group looked closest.
 *  6. A PLAN'S OUTCOME IS WHAT THE SERVER RECORDED. `partial` and `halted`
 *     exist precisely because "completed | failed" would force a lie; neither
 *     is ever rendered as a success.
 */
import type { AgentRun } from "../../lib/api/agents";
import type { OrchestrationMapData } from "../../lib/api/agentPolicy";
import type { OrchestrationPlan, RunPlanRecord } from "../../lib/api/orchestrationPlan";
import { WORKFLOW_LINKAGES, drawableLinkages } from "./workflow-linkage";

// ---------------------------------------------------------------------------
// Copy that names the mandate
// ---------------------------------------------------------------------------

export const CONDUCTOR_HEADING = "Conductor";

/**
 * The band's standing sentence. It states the SCHEDULING mandate only —
 * execution classes, dedup and budgets — because that is what P1-A actually
 * made true. The ADR-AGI-2 improvement loop is deliberately NOT claimed here:
 * it ships in P2, and the fabricated-topology law applies to copy as much as to
 * edges.
 */
export const CONDUCTOR_MANDATE =
  "One supervisor schedules every run on the operating loop below — in " +
  "dependency order, deduping cards that share a backend, holding exclusive " +
  "slots where the database demands one, and reserving budget per step rather " +
  "than for the whole plan.";

/** Stated wherever the plan preview is offered. It is a fact, not an estimate. */
export const PLAN_PREVIEW_COST_NOTE =
  "Previewing the plan costs $0.00: the plan endpoint dispatches nothing, " +
  "records no run and calls no model.";

// ---------------------------------------------------------------------------
// The rename (ADR-AGI-3 Decision 2)
// ---------------------------------------------------------------------------

/**
 * How many steps the SEQUENTIAL pipeline runs — `_PIPELINE_PLAN` in the API.
 *
 * Mirrored rather than fetched because no endpoint exposes it, and pinned by
 * `conductor-logic.test.ts`, which opens the server file and re-reads the list
 * on every run (the same discipline `workflow-linkage-provenance.test.ts` uses
 * for citations). Add a sixth pipeline step and that test goes red — the button
 * cannot silently start lying about what it runs.
 */
export const PIPELINE_STEP_COUNT = 5;

/** Where {@link PIPELINE_STEP_COUNT} is verified against, on every test run. */
export const PIPELINE_PLAN_PROVENANCE = "apps/api/app/routers/agents.py::_PIPELINE_PLAN";

/**
 * The header control's name. It used to be "Run All", which was the ADR's named
 * failure mode: two controls named alike over DIFFERENT sets — the header ran
 * 5 sequential agents while the map's control ran a whole workflow, and the new
 * global control runs 19. Each now says what it runs.
 */
export const RUN_PIPELINE_LABEL = `Run pipeline (${PIPELINE_STEP_COUNT} steps)`;

/** The same control, named in prose (tooltips, "X is in progress" messages). */
export const RUN_PIPELINE_SHORT = "Run pipeline";

/** The global control, before any plan has been read. */
export const RUN_EVERYTHING_BASE = "Run everything";

/** "Run everything (19 agents / 21 cards)" — counts from the plan, or none. */
export function runEverythingLabel(plan: OrchestrationPlan | null): string {
  if (!plan) return RUN_EVERYTHING_BASE;
  const agents = `${plan.agentCount} agent${plan.agentCount === 1 ? "" : "s"}`;
  const cards = `${plan.cardCount} card${plan.cardCount === 1 ? "" : "s"}`;
  return `${RUN_EVERYTHING_BASE} (${agents} / ${cards})`;
}

/** The plan's own cost figure, formatted; never a guess when unread. */
export function formatPlanCost(plan: OrchestrationPlan | null): string {
  if (!plan) return "—";
  return `$${plan.estimatedCostUsd.toFixed(2)}`;
}

// ---------------------------------------------------------------------------
// Model binding + fallback chain
// ---------------------------------------------------------------------------

export interface SupervisorConfig {
  key: string;
  model: string;
  provider?: string | null;
  authMode?: string | null;
}

export interface SupervisorCatalogAgent {
  key: string;
  name: string;
  model: string;
}

export interface SupervisorBinding {
  /** The model id the server says this agent runs on. */
  model: string;
  /** Provider id as configured, or resolved from the model id; null if neither. */
  provider: string | null;
  authMode: string | null;
  /** Human label for the credential the run would consume. */
  providerText: string;
  /** "claude-opus-4-8 · Anthropic subscription". */
  chip: string;
}

/** Placeholders the catalog uses for "no model applies" — never a binding. */
const NON_MODELS = new Set(["—", "-", "deterministic", ""]);

function usableModel(model: string | null | undefined): string | null {
  const trimmed = (model ?? "").trim();
  return NON_MODELS.has(trimmed) ? null : trimmed;
}

/**
 * The credential a run on this binding would consume, in words.
 *
 * `authMode` is what separates "Anthropic subscription" from "Anthropic API
 * key" — and when the server has told us neither, this says "Anthropic" and
 * stops, because claiming a subscription the config does not record would be
 * the same fabrication as claiming a model.
 */
export function providerLabel(
  provider: string | null | undefined,
  authMode: string | null | undefined,
  model?: string | null,
): string {
  const resolved = (provider ?? providerFromModelId(model) ?? "").toLowerCase();
  if (resolved === "anthropic") {
    if (authMode === "oauth_token" || authMode === "subscription_oauth") {
      return "Anthropic subscription";
    }
    if (authMode === "api_key") return "Anthropic API key";
    return "Anthropic";
  }
  if (resolved === "openrouter") return "OpenRouter";
  if (resolved === "abacus" || resolved === "abacusai") return "Abacus.ai";
  if (resolved === "google" || resolved === "gemini") return "Google";
  if (resolved) return provider ?? resolved;
  return "provider resolved at run time";
}

/**
 * Which provider an id bills to, by the server's rule (`resolve_provider`).
 *
 * MODEL-SUB-QUOTA (OWNER DIRECTIVE 2026-08-17): ANY Claude id — bare
 * `claude-*` OR namespaced `anthropic/claude-*` — is served by the operator's
 * Anthropic subscription. Both spellings name one model, so both label as
 * Anthropic; labelling the namespaced form "OpenRouter" would tell the user
 * their Claude run billed to an account it never touched.
 *
 * Every OTHER `vendor/model` id is an OpenRouter id, unchanged. Anything else
 * is unknown here — the server decides, and this returns null rather than
 * guessing on the user's bill. Kept in lockstep with the API rule by
 * `__tests__/agents/conductor-logic.test.ts`.
 */
export function providerFromModelId(model: string | null | undefined): string | null {
  const id = (model ?? "").trim();
  if (!id) return null;
  if (/^(?:anthropic\/)?claude-/i.test(id)) return "anthropic";
  if (id.includes("/")) return "openrouter";
  return null;
}

/**
 * The supervisor's LIVE binding, or null when nothing has been read.
 *
 * The catalog row is preferred for the model because it is the model the agent
 * ACTUALLY runs on (the server resolves overrides into it); the AgentConfig
 * row supplies provider + auth mode, which the catalog does not carry.
 */
export function supervisorBinding(
  config: SupervisorConfig | null,
  agent: SupervisorCatalogAgent | null,
): SupervisorBinding | null {
  const model = usableModel(agent?.model) ?? usableModel(config?.model);
  if (!model) return null;
  const provider = config?.provider ?? providerFromModelId(model);
  const authMode = config?.authMode ?? null;
  const providerText = providerLabel(config?.provider ?? null, authMode, model);
  return { model, provider: provider ?? null, authMode, providerText, chip: `${model} · ${providerText}` };
}

/** Shown in place of a chip when no config/catalog row has resolved yet. */
export const BINDING_UNREAD_TEXT = "model binding not read yet";

export interface FallbackLink {
  id: string;
  label: string;
  role: "primary" | "fallback";
  note: string;
}

/**
 * ADR-AGI-3 Decision 3, verbatim in order: the Supervisor is bound to the
 * operator's Anthropic subscription tier and falls back only on quota/credit
 * exhaustion, per attempt, retrying Anthropic first on every new plan.
 *
 * The ORDER is the constant; the ACTIVE binding is never read from here.
 */
export const SUPERVISOR_FALLBACK_CHAIN: readonly FallbackLink[] = [
  {
    id: "anthropic",
    label: "Anthropic subscription",
    role: "primary",
    note: "the operator's Anthropic subscription tier — retried first on every new plan",
  },
  { id: "openrouter", label: "OpenRouter", role: "fallback", note: "on quota or credit exhaustion" },
  { id: "abacus", label: "Abacus.ai", role: "fallback", note: "on quota or credit exhaustion" },
  { id: "google", label: "Google", role: "fallback", note: "on quota or credit exhaustion" },
];

export const FALLBACK_DISCLOSURE =
  "Fallbacks engage only on a quota or credit exhaustion signal, one attempt at " +
  "a time, and never silently: the model a run was actually served by is " +
  "recorded on the run and shown here when it differs.";

export interface FallbackEngagement {
  requestedModel: string;
  servedModel: string;
  reason: string | null;
  at: string | null;
}

/**
 * A RECORDED fallback engagement for `backend`, or null.
 *
 * Reads `requestedModel`/`servedModel` off the run's own output — the pair the
 * API already writes (agents.py) — and reports one only when they actually
 * differ. No run, no chip: the chain being configured is not evidence that it
 * was ever used.
 */
export function fallbackEngagement(
  runs: readonly AgentRun[],
  backend: string,
): FallbackEngagement | null {
  const candidates = runs
    .filter((r) => r.agentName === backend)
    .slice()
    .sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""));
  for (const run of candidates) {
    const output = (run.output ?? {}) as Record<string, unknown>;
    const requested = typeof output.requestedModel === "string" ? output.requestedModel : null;
    const served = typeof output.servedModel === "string" ? output.servedModel : null;
    if (!requested || !served || requested === served) continue;
    return {
      requestedModel: requested,
      servedModel: served,
      reason: typeof output.fallbackReason === "string" ? output.fallbackReason : null,
      at: run.createdAt ?? null,
    };
  }
  return null;
}

// ---------------------------------------------------------------------------
// The plan, grouped by the workflows it spans
// ---------------------------------------------------------------------------

export interface PlanCard {
  /** Catalog card key, e.g. `resumeTailoring`. */
  cardKey: string;
  /** The card's display name, as the SERVER named it. */
  cardName: string;
  /** The dispatch that covers it — several cards may share one. */
  backend: string;
  stepKey: string;
  metered: boolean;
  execClass: string | null;
  exclusive: boolean;
  rationale: string | null;
  /** Parallel group index from the plan, when the server stated one. */
  group: number | null;
}

export interface WorkflowPlanGroup {
  key: string;
  name: string;
  subtitle: string | null;
  cards: PlanCard[];
  /** Dispatches, NOT cards: three cards on one backend are one run. */
  dispatchCount: number;
  meteredCount: number;
}

export interface GroupedPlan {
  groups: WorkflowPlanGroup[];
  /** Cards the plan covers that no loaded map places — disclosed, not hidden. */
  unplaced: PlanCard[];
}

interface Placement {
  mapKey: string;
  mapName: string;
  agentName: string;
}

function placementsOf(maps: OrchestrationMapData | null): Map<string, Placement> {
  const index = new Map<string, Placement>();
  (maps?.maps ?? []).forEach((map) => {
    map.stages.forEach((stage) => {
      stage.agents.forEach((agent) => {
        if (!index.has(agent.agentKey)) {
          index.set(agent.agentKey, {
            mapKey: map.key,
            mapName: map.name,
            agentName: agent.name,
          });
        }
      });
    });
  });
  return index;
}

/** Every catalog card this plan covers, in plan order, with its dispatch. */
export function planCards(plan: OrchestrationPlan | null, maps: OrchestrationMapData | null): PlanCard[] {
  if (!plan) return [];
  const placed = placementsOf(maps);
  const cards: PlanCard[] = [];
  plan.steps.forEach((step) => {
    const backend = step.backend ?? step.key;
    step.coversCards.forEach((cardKey, i) => {
      cards.push({
        cardKey,
        cardName: step.cardNames[i] ?? placed.get(cardKey)?.agentName ?? cardKey,
        backend,
        stepKey: step.key,
        metered: step.metered === true,
        execClass: step.execClass ?? null,
        exclusive: step.exclusive === true,
        rationale: step.rationale ?? null,
        group: step.group ?? null,
      });
    });
  });
  return cards;
}

/**
 * The plan, split across the workflow maps the console has actually loaded.
 *
 * A card whose agent no loaded map places lands in `unplaced` rather than in
 * the nearest group: the plan endpoint and the map endpoint are separate reads
 * and may legitimately disagree for a moment, and inventing a placement is how
 * a UI starts asserting topology the server never described.
 */
export function groupPlanByWorkflow(
  plan: OrchestrationPlan | null,
  maps: OrchestrationMapData | null,
): GroupedPlan {
  const placed = placementsOf(maps);
  const cards = planCards(plan, maps);
  const byMap = new Map<string, PlanCard[]>();
  const unplaced: PlanCard[] = [];
  cards.forEach((card) => {
    const placement = placed.get(card.cardKey);
    if (!placement) {
      unplaced.push(card);
      return;
    }
    const bucket = byMap.get(placement.mapKey);
    if (bucket) bucket.push(card);
    else byMap.set(placement.mapKey, [card]);
  });
  const groups: WorkflowPlanGroup[] = (maps?.maps ?? [])
    .map((map) => {
      const groupCards = byMap.get(map.key) ?? [];
      return {
        key: map.key,
        name: map.name,
        subtitle: map.subtitle ?? null,
        cards: groupCards,
        dispatchCount: new Set(groupCards.map((c) => c.stepKey)).size,
        meteredCount: new Set(groupCards.filter((c) => c.metered).map((c) => c.stepKey)).size,
      };
    })
    .filter((group) => group.cards.length > 0);
  return { groups, unplaced };
}

/** The workflow names this console is showing, in payload order. */
export function conductedWorkflowNames(maps: OrchestrationMapData | null): string[] {
  return (maps?.maps ?? []).map((m) => m.name);
}

/**
 * The rail's statement in words — the accessible twin of the drawn edges, and
 * the reason the drawing may be decorative (`aria-hidden`) without losing the
 * claim it makes.
 */
export function conductorRailStatement(maps: OrchestrationMapData | null): string {
  const names = conductedWorkflowNames(maps);
  if (names.length === 0) return "No workflow map has loaded, so no workflow is being conducted on screen.";
  const list =
    names.length === 1
      ? names[0]
      : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  return `The supervisor schedules runs across all ${names.length} workflows shown below: ${list}.`;
}

// ---------------------------------------------------------------------------
// The linkage the owner asked to be able to see
// ---------------------------------------------------------------------------

export interface PlanLinkageRow {
  id: string;
  fromKey: string;
  toKey: string;
  fromName: string;
  toName: string;
  fromWorkflow: string;
  toWorkflow: string;
  label: string;
  meaning: string;
  via: string | null;
}

/**
 * The cross-workflow wiring INSIDE this plan — "story extraction feeds resume
 * tailoring and the cover letter", stated where the plan is read.
 *
 * Sourced from the checked-in provenance table (every edge carries the
 * file:line it was read out of the API with, re-verified in CI), filtered to
 * edges whose BOTH ends this plan actually covers and both maps place. A wire
 * to an agent the plan will not run would be a claim about this run that is
 * not true of it.
 */
export function planLinkages(
  plan: OrchestrationPlan | null,
  maps: OrchestrationMapData | null,
): PlanLinkageRow[] {
  if (!plan) return [];
  const placed = placementsOf(maps);
  const covered = new Map<string, PlanCard>();
  planCards(plan, maps).forEach((card) => covered.set(card.cardKey, card));
  return drawableLinkages(WORKFLOW_LINKAGES)
    .filter((link) => covered.has(link.from) && covered.has(link.to))
    .filter((link) => placed.has(link.from) && placed.has(link.to))
    .map((link) => {
      const from = placed.get(link.from) as Placement;
      const to = placed.get(link.to) as Placement;
      return {
        id: link.id,
        fromKey: link.from,
        toKey: link.to,
        fromName: covered.get(link.from)?.cardName ?? from.agentName,
        toName: covered.get(link.to)?.cardName ?? to.agentName,
        fromWorkflow: from.mapName,
        toWorkflow: to.mapName,
        label: link.label,
        meaning: link.meaning,
        via: link.via,
      };
    });
}

// ---------------------------------------------------------------------------
// What a recorded plan is allowed to say about itself
// ---------------------------------------------------------------------------

export interface PlanRunView {
  tone: "info" | "ok" | "warn" | "error";
  headline: string;
  detail: string | null;
  /** Per-state step counts, all read off the record. */
  counts: { total: number; completed: number; failed: number; refused: number; running: number };
}

function countStates(record: RunPlanRecord): PlanRunView["counts"] {
  const counts = { total: record.steps.length, completed: 0, failed: 0, refused: 0, running: 0 };
  record.steps.forEach((step) => {
    switch (step.state) {
      case "completed":
        counts.completed += 1;
        break;
      case "failed":
        counts.failed += 1;
        break;
      case "refused":
        counts.refused += 1;
        break;
      case "running":
        counts.running += 1;
        break;
      default:
        break;
    }
  });
  return counts;
}

/**
 * What the console may say about a recorded plan — and nothing beyond it.
 *
 * `partial` and `halted` get their own words because the server keeps them
 * apart for exactly that reason: a plan whose spine broke while nine enrichment
 * agents ran is neither a success nor a stop, and rendering either as "done"
 * would misreport what the user actually got.
 */
export function planRunView(record: RunPlanRecord | null): PlanRunView | null {
  if (!record) return null;
  const counts = countStates(record);
  const settled = counts.completed + counts.failed + counts.refused;
  const halted = record.haltedAtStep
    ? `Stopped at ${record.haltedAtStep}${record.haltReason ? `: ${record.haltReason}` : ""}.`
    : record.haltReason;
  switch (record.status) {
    case "planned":
      return {
        tone: "info",
        headline: "Plan queued — the worker has not started it yet.",
        detail: null,
        counts,
      };
    case "running":
      return {
        tone: "info",
        headline: `Running — ${settled} of ${counts.total} steps have reported back.`,
        detail: counts.running > 0 ? `${counts.running} in flight right now.` : null,
        counts,
      };
    case "completed":
      return {
        tone: "ok",
        headline: `Ran everything — all ${counts.completed} of ${counts.total} steps completed.`,
        detail: null,
        counts,
      };
    case "partial":
      return {
        tone: "warn",
        headline:
          `Ran partly — ${counts.completed} of ${counts.total} steps completed, ` +
          `${counts.failed} failed, ${counts.refused} refused.`,
        detail:
          "The steps that did not run are listed below; nothing was retried automatically.",
        counts,
      };
    case "halted":
      return {
        tone: "error",
        headline: `Plan halted after ${counts.completed} of ${counts.total} steps.`,
        detail: halted ?? "The server recorded a halt without a reason.",
        counts,
      };
    case "failed":
      return {
        tone: "error",
        headline: "Plan failed.",
        detail: halted ?? null,
        counts,
      };
    default:
      return {
        tone: "info",
        headline: `Plan state: ${record.status}.`,
        detail: null,
        counts,
      };
  }
}
