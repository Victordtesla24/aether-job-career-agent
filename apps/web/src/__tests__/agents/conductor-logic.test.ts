/**
 * P1-B CONDUCTOR — the pure logic behind the Conductor band (ADR-AGI-3
 * Decision 2 + the owner's 2026-08-14 addendum: "the orchestration/supervisor
 * agent manages all the 3 workflows — fix that and ensure UI too reflects
 * that", and "users must be able to run individual, multiple agents or the
 * whole workflow from the UI").
 *
 * WHAT EACH TEST PINS (each one a way the band could lie):
 *   1. the RENAME is real and its count is not invented: "Run All" becomes
 *      "Run pipeline (N steps)" where N is read out of the API's own
 *      `_PIPELINE_PLAN` — the assertion opens the LIVE server file, so the day
 *      someone adds a sixth pipeline step this test goes red instead of the
 *      button quietly lying;
 *   2. the global control's counts are the SERVER's (plan.agentCount /
 *      plan.cardCount) and no number is rendered at all before the plan loads;
 *   3. the supervisor's model chip is the LIVE binding — the ADR's example
 *      string may never be substituted for a config the console has not read;
 *   4. the fallback chain is the ADR constant, in the ADR's order, and it is
 *      never presented as the ACTIVE binding;
 *   5. the plan groups by the THREE live workflow maps, from the payload's own
 *      names, and a card the maps do not place is disclosed rather than hidden;
 *   6. the story-extraction → tailoring / cover-letter linkage the owner asked
 *      to see is surfaced from the checked-in provenance table, and only for
 *      agents this plan actually covers;
 *   7. a run plan's terminal state is reported as the server recorded it —
 *      `partial` and `halted` are never rendered as success;
 *   8. a fallback engagement is shown only when a run RECORDED one.
 *
 * The fixture is the VERBATIM production response captured on 2026-08-14 at
 * uat/reports/evidence/market-perf/u-model-default/verify/orchestration-plan-response.json
 * (that tree is gitignored, so the payload is checked in here instead). The
 * schema is written against THAT shape, not against a shape a spec imagined.
 *
 * Written BEFORE the implementation.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  PIPELINE_PLAN_PROVENANCE,
  PIPELINE_STEP_COUNT,
  RUN_PIPELINE_LABEL,
  SUPERVISOR_FALLBACK_CHAIN,
  conductedWorkflowNames,
  conductorRailStatement,
  fallbackEngagement,
  groupPlanByWorkflow,
  planLinkages,
  planRunView,
  providerLabel,
  runEverythingLabel,
  supervisorBinding,
} from "../../components/agents/conductor";
import {
  OrchestrationPlanSchema,
  RunPlanRecordSchema,
  type OrchestrationPlan,
} from "../../lib/api/orchestrationPlan";
import type { AgentRun } from "../../lib/api/agents";
import type { OrchestrationMapData } from "../../lib/api/agentPolicy";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../../../..");

const PROD_PLAN: OrchestrationPlan = OrchestrationPlanSchema.parse(
  JSON.parse(readFileSync(path.join(HERE, "fixtures/orchestration-plan.prod.json"), "utf8")),
);

/** The three live maps, named exactly as GET /agents/orchestration-map names them. */
const MAPS: OrchestrationMapData = {
  maps: [
    {
      key: "application-pipeline",
      name: "Application Pipeline",
      subtitle: "The path one job posting travels from discovery to a tracked application.",
      stages: [
        { stage: "Discovery", agents: [mapAgent("jobDiscovery", "Job Discovery Agent", "scout")] },
        {
          stage: "Fit Scoring",
          agents: [
            mapAgent("matchScoring", "Match Scoring Agent", "fitScorer"),
            mapAgent("atsOptimization", "ATS Optimization Agent", "fitScorer"),
            mapAgent("skillGap", "Skill Gap Agent", "fitScorer"),
            mapAgent("jobMatching", "Job Matching Agent", "matcher"),
          ],
        },
        { stage: "Tailoring", agents: [mapAgent("resumeTailoring", "Resume Tailoring Agent", "tailor")] },
        { stage: "Cover Letter", agents: [mapAgent("coverLetter", "Cover Letter Agent", "coverLetter")] },
        { stage: "Quality Gates", agents: [mapAgent("compliance", "Compliance Agent", "compliance")] },
        {
          stage: "Submission",
          agents: [
            mapAgent("submission", "Submission Agent", "submission"),
            mapAgent("emailAgent", "Email Agent", "emailAgent"),
          ],
        },
        {
          stage: "Tracking",
          agents: [
            mapAgent("notification", "Notification Agent", "notification"),
            mapAgent("scheduling", "Scheduling Agent", "scheduling"),
          ],
        },
      ],
    },
    {
      key: "learning-loop",
      name: "Learning Loop",
      subtitle: "The cycle that reads the pipeline's real outcomes.",
      stages: [
        { stage: "Orchestration", agents: [mapAgent("orchestration", "Orchestration Agent", "supervisor")] },
        {
          stage: "Signal Capture",
          agents: [
            mapAgent("storyExtraction", "Story Extraction Agent", "storyExtractor"),
            mapAgent("sentimentAnalysis", "Sentiment Analysis Agent", "sentimentAnalysis"),
          ],
        },
        {
          stage: "Learning",
          agents: [mapAgent("learningFeedback", "Learning Feedback Agent", "learningFeedback")],
        },
      ],
    },
    {
      key: "enrichment",
      name: "Context & Enrichment",
      subtitle: "Evidence and market context the pipeline draws on.",
      stages: [
        {
          stage: "Market Intelligence",
          agents: [
            mapAgent("marketTrends", "Market Trends Agent", "marketTrends"),
            mapAgent("salaryIntelligence", "Salary Intelligence Agent", "salaryIntelligence"),
          ],
        },
        {
          stage: "Employer Research",
          agents: [mapAgent("companyResearch", "Company Research Agent", "companyResearch")],
        },
        {
          stage: "Outreach",
          agents: [
            mapAgent("recruiterOutreach", "Recruiter Outreach Agent", "recruiterOutreach"),
            mapAgent("reference", "Reference Agent", "reference"),
          ],
        },
        {
          stage: "Interview Readiness",
          agents: [mapAgent("interviewPrep", "Interview Prep Agent", "interviewPrep")],
        },
      ],
    },
  ],
};

function mapAgent(agentKey: string, name: string, backend: string) {
  return {
    agentKey,
    name,
    backend,
    status: "real" as const,
    runnable: true,
    metricsConsumed: [],
    thresholds: [],
    lastRunPolicyTier: null,
    lastRunAt: null,
    lastRunStatus: null,
    trend: null,
  };
}

// ---------------------------------------------------------------------------
// 1. The rename, and its count pinned to the server's own pipeline plan
// ---------------------------------------------------------------------------

describe("CONDUCTOR — the ADR-AGI-3 rename", () => {
  it("renames the header control to 'Run pipeline (N steps)'", () => {
    expect(RUN_PIPELINE_LABEL).toBe(`Run pipeline (${PIPELINE_STEP_COUNT} steps)`);
    expect(RUN_PIPELINE_LABEL).not.toMatch(/run all/i);
  });

  it("takes N from the API's own _PIPELINE_PLAN, read out of the live server file", () => {
    const [file, symbol] = PIPELINE_PLAN_PROVENANCE.split("::");
    expect(symbol).toBe("_PIPELINE_PLAN");
    const source = readFileSync(path.join(REPO_ROOT, file), "utf8");
    const match = /^_PIPELINE_PLAN\s*=\s*\[([^\]]*)\]/m.exec(source);
    expect(match).not.toBeNull();
    const serverSteps = (match as RegExpExecArray)[1]
      .split(",")
      .map((s) => s.trim().replace(/^["']|["']$/g, ""))
      .filter((s) => s.length > 0);
    expect(serverSteps.length).toBe(PIPELINE_STEP_COUNT);
  });

  it("never leaves 'Run All' as the name of a control over a different set", () => {
    // Two controls named alike over different sets is the failure mode the ADR
    // names; the global control must not reuse the pipeline's words either.
    expect(runEverythingLabel(PROD_PLAN)).not.toMatch(/run all/i);
    expect(runEverythingLabel(PROD_PLAN)).not.toContain(RUN_PIPELINE_LABEL);
  });
});

// ---------------------------------------------------------------------------
// 2. Global control counts are the server's, or absent
// ---------------------------------------------------------------------------

describe("CONDUCTOR — 'Run everything' counts come from the plan endpoint", () => {
  it("states the server's dispatch and card counts", () => {
    expect(PROD_PLAN.agentCount).toBe(19);
    expect(PROD_PLAN.cardCount).toBe(21);
    expect(runEverythingLabel(PROD_PLAN)).toBe("Run everything (19 agents / 21 cards)");
  });

  it("invents no number before the plan has been read", () => {
    expect(runEverythingLabel(null)).toBe("Run everything");
    expect(runEverythingLabel(null)).not.toMatch(/\d/);
  });

  it("follows the server when the counts change", () => {
    const smaller: OrchestrationPlan = { ...PROD_PLAN, agentCount: 4, cardCount: 5 };
    expect(runEverythingLabel(smaller)).toBe("Run everything (4 agents / 5 cards)");
  });
});

// ---------------------------------------------------------------------------
// 3 + 4. Supervisor binding and the fallback chain
// ---------------------------------------------------------------------------

describe("CONDUCTOR — the supervisor's model binding is the LIVE one", () => {
  it("reads model + provider off the live AgentConfig / catalog row", () => {
    const binding = supervisorBinding(
      { key: "orchestration", model: "claude-opus-4-8", provider: "anthropic", authMode: "oauth_token" },
      { key: "orchestration", name: "Orchestration Agent", model: "claude-opus-4-8" },
    );
    expect(binding).not.toBeNull();
    expect(binding?.model).toBe("claude-opus-4-8");
    expect(binding?.chip).toBe("claude-opus-4-8 · Anthropic subscription");
  });

  it("follows a DIFFERENT live binding rather than the ADR's example string", () => {
    const binding = supervisorBinding(
      { key: "orchestration", model: "claude-opus-4-9", provider: "anthropic", authMode: "api_key" },
      { key: "orchestration", name: "Orchestration Agent", model: "claude-opus-4-9" },
    );
    expect(binding?.chip).toBe("claude-opus-4-9 · Anthropic API key");
    expect(binding?.chip).not.toContain("claude-opus-4-8");
  });

  it("resolves an unset provider by the SAME rule the server bills on", () => {
    // llm_client.resolve_provider: ANY Claude id — bare or `anthropic/`-
    // namespaced — is served by the operator's Anthropic subscription
    // (MODEL-SUB-QUOTA, OWNER DIRECTIVE 2026-08-17); every OTHER `vendor/model`
    // id is OpenRouter's. Nothing here may cross those.
    expect(providerLabel(null, null, "anthropic/claude-opus-4-8")).toBe("Anthropic");
    expect(providerLabel(null, null, "claude-opus-4-8")).toBe("Anthropic");
    expect(providerLabel(null, null, "deepseek/deepseek-v4-pro")).toBe("OpenRouter");
    expect(providerLabel(null, null, "anthropic/some-non-claude-model")).toBe("OpenRouter");
    expect(providerLabel("abacus", null, "some-model")).toBe("Abacus.ai");
    expect(providerLabel("google", null, "gemini-3.5-flash")).toBe("Google");
  });

  it("returns null — never a placeholder model — when nothing has been read yet", () => {
    expect(supervisorBinding(null, null)).toBeNull();
    expect(supervisorBinding(null, { key: "orchestration", name: "Orchestration Agent", model: "—" })).toBeNull();
  });
});

describe("CONDUCTOR — the fallback chain", () => {
  it("is the ADR chain in the ADR's order", () => {
    expect(SUPERVISOR_FALLBACK_CHAIN.map((l) => l.label)).toEqual([
      "Anthropic subscription",
      "OpenRouter",
      "Abacus.ai",
      "Google",
    ]);
  });

  it("marks exactly one link as the primary binding and the rest as fallbacks", () => {
    expect(SUPERVISOR_FALLBACK_CHAIN.filter((l) => l.role === "primary")).toHaveLength(1);
    expect(SUPERVISOR_FALLBACK_CHAIN[0].role).toBe("primary");
    expect(SUPERVISOR_FALLBACK_CHAIN.slice(1).every((l) => l.role === "fallback")).toBe(true);
  });
});

describe("CONDUCTOR — a fallback is only shown when a run recorded one", () => {
  const run = (output: Record<string, unknown> | null): AgentRun => ({
    id: "r1",
    agentName: "supervisor",
    status: "completed",
    input: null,
    output,
    error: null,
    costUsd: 0,
    startedAt: "2026-08-14T09:00:00",
    completedAt: "2026-08-14T09:01:00",
    createdAt: "2026-08-14T09:00:00",
    heartbeatAt: null,
  });

  it("reports nothing when no run records a served model", () => {
    expect(fallbackEngagement([run(null)], "supervisor")).toBeNull();
    expect(fallbackEngagement([run({ model: "claude-opus-4-8" })], "supervisor")).toBeNull();
  });

  it("reports the recorded substitution, in the server's own words", () => {
    const engaged = fallbackEngagement(
      [
        run({
          requestedModel: "claude-opus-4-8",
          servedModel: "anthropic/claude-opus-4-8",
          fallbackReason: "anthropic subscription quota exhausted",
        }),
      ],
      "supervisor",
    );
    expect(engaged?.servedModel).toBe("anthropic/claude-opus-4-8");
    expect(engaged?.requestedModel).toBe("claude-opus-4-8");
    expect(engaged?.reason).toBe("anthropic subscription quota exhausted");
  });

  it("never calls an unchanged model a fallback", () => {
    expect(
      fallbackEngagement(
        [run({ requestedModel: "claude-opus-4-8", servedModel: "claude-opus-4-8" })],
        "supervisor",
      ),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 5. The plan, grouped by the THREE workflows the supervisor conducts
// ---------------------------------------------------------------------------

describe("CONDUCTOR — the plan view groups by the three live workflow maps", () => {
  it("names every workflow from the payload, never from a constant", () => {
    expect(conductedWorkflowNames(MAPS)).toEqual([
      "Application Pipeline",
      "Learning Loop",
      "Context & Enrichment",
    ]);
    expect(conductorRailStatement(MAPS)).toContain("Application Pipeline");
    expect(conductorRailStatement(MAPS)).toContain("Learning Loop");
    expect(conductorRailStatement(MAPS)).toContain("Context & Enrichment");
  });

  it("places all 21 covered cards across the three maps, none lost, none duplicated", () => {
    const { groups, unplaced } = groupPlanByWorkflow(PROD_PLAN, MAPS);
    expect(groups.map((g) => g.key)).toEqual([
      "application-pipeline",
      "learning-loop",
      "enrichment",
    ]);
    const placed = groups.reduce((n, g) => n + g.cards.length, 0);
    expect(placed + unplaced.length).toBe(PROD_PLAN.cardCount);
    expect(unplaced).toHaveLength(0);
    const keys = groups.flatMap((g) => g.cards.map((c) => c.cardKey));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("counts DISPATCHES per workflow, not cards — shared backends run once", () => {
    const { groups } = groupPlanByWorkflow(PROD_PLAN, MAPS);
    const pipeline = groups[0];
    // matchScoring / atsOptimization / skillGap all resolve to fitScorer.
    expect(pipeline.cards.filter((c) => c.backend === "fitScorer")).toHaveLength(3);
    expect(pipeline.dispatchCount).toBeLessThan(pipeline.cards.length);
    const totalDispatches = new Set(
      groups.flatMap((g) => g.cards.map((c) => c.backend)),
    ).size;
    expect(totalDispatches).toBe(PROD_PLAN.agentCount);
  });

  it("uses the SERVER's card names", () => {
    const { groups } = groupPlanByWorkflow(PROD_PLAN, MAPS);
    const names = groups.flatMap((g) => g.cards.map((c) => c.cardName));
    expect(names).toContain("Job Discovery Agent");
    expect(names).toContain("Story Extraction Agent");
  });

  it("discloses a covered card the maps do not place instead of dropping it", () => {
    const strippedMaps: OrchestrationMapData = {
      maps: MAPS.maps.map((m) =>
        m.key === "learning-loop"
          ? { ...m, stages: m.stages.filter((s) => s.stage !== "Signal Capture") }
          : m,
      ),
    };
    const { groups, unplaced } = groupPlanByWorkflow(PROD_PLAN, strippedMaps);
    expect(unplaced.map((c) => c.cardKey)).toContain("storyExtraction");
    const placed = groups.reduce((n, g) => n + g.cards.length, 0);
    expect(placed + unplaced.length).toBe(PROD_PLAN.cardCount);
  });
});

// ---------------------------------------------------------------------------
// 6. The linkage the owner asked to see
// ---------------------------------------------------------------------------

describe("CONDUCTOR — story extraction feeds resume tailoring + cover letter", () => {
  it("surfaces both linkages, with the workflows each end sits on", () => {
    const rows = planLinkages(PROD_PLAN, MAPS);
    const ids = rows.map((r) => r.id);
    expect(ids).toContain("storyExtraction->resumeTailoring");
    expect(ids).toContain("storyExtraction->coverLetter");
    const tailoring = rows.find((r) => r.id === "storyExtraction->resumeTailoring");
    expect(tailoring?.fromName).toBe("Story Extraction Agent");
    expect(tailoring?.toName).toBe("Resume Tailoring Agent");
    expect(tailoring?.fromWorkflow).toBe("Learning Loop");
    expect(tailoring?.toWorkflow).toBe("Application Pipeline");
    expect(tailoring?.meaning).toMatch(/evidence/i);
  });

  it("drops a linkage whose ends this plan does not cover", () => {
    const trimmed: OrchestrationPlan = {
      ...PROD_PLAN,
      steps: PROD_PLAN.steps.filter((s) => s.key !== "storyExtractor"),
    };
    const ids = planLinkages(trimmed, MAPS).map((r) => r.id);
    expect(ids).not.toContain("storyExtraction->resumeTailoring");
  });
});

// ---------------------------------------------------------------------------
// 7. Honest terminal states for a recorded run plan
// ---------------------------------------------------------------------------

/** A view that must exist — keeps the assertions below free of `?.`, which
 *  would let a null view pass every one of them silently. */
function mustView(view: ReturnType<typeof planRunView>) {
  expect(view).not.toBeNull();
  return view as NonNullable<typeof view>;
}

describe("CONDUCTOR — a run plan reports what the server recorded", () => {
  const record = (over: Record<string, unknown>) =>
    RunPlanRecordSchema.parse({
      id: "plan-1",
      status: "running",
      initiator: "user",
      concurrency: 1,
      spacingSeconds: 5,
      steps: [],
      summary: null,
      haltedAtStep: null,
      haltReason: null,
      startedAt: "2026-08-14T09:00:00",
      finishedAt: null,
      createdAt: "2026-08-14T09:00:00",
      updatedAt: "2026-08-14T09:00:00",
      ...over,
    });

  it("calls a running plan running, and claims nothing about its outcome", () => {
    const view = mustView(planRunView(record({ status: "running" })));
    expect(view.tone).toBe("info");
    expect(view.headline).toMatch(/running/i);
    expect(view.headline).not.toMatch(/complete|success|finished/i);
  });

  it("never renders 'partial' as success", () => {
    const view = mustView(planRunView(
      record({
        status: "partial",
        steps: [
          { key: "scout", backend: "scout", group: 0, state: "completed" },
          { key: "tailor", backend: "tailor", group: 1, state: "failed" },
        ],
      }),
    ));
    expect(view.tone).toBe("warn");
    expect(view.headline).toMatch(/partly|partial/i);
    expect(view.headline).not.toMatch(/^Ran everything/i);
  });

  it("quotes the server's halt reason on a halted plan", () => {
    const view = mustView(planRunView(
      record({
        status: "halted",
        haltedAtStep: "tailor",
        haltReason: "the account's run quota or spend cap was reached",
      }),
    ));
    expect(view.tone).toBe("error");
    expect(view.detail).toContain("run quota or spend cap was reached");
    expect(view.detail).toContain("tailor");
  });

  it("reports a completed plan as completed, with its step counts", () => {
    const view = mustView(planRunView(
      record({
        status: "completed",
        finishedAt: "2026-08-14T09:30:00",
        steps: [
          { key: "scout", backend: "scout", group: 0, state: "completed" },
          { key: "tailor", backend: "tailor", group: 1, state: "completed" },
        ],
      }),
    ));
    expect(view.tone).toBe("ok");
    expect(view.headline).toMatch(/2/);
  });

  it("says nothing at all when there is no plan record", () => {
    expect(planRunView(null)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 8. The schema is the LIVE payload's shape
// ---------------------------------------------------------------------------

describe("CONDUCTOR — the plan schema matches production", () => {
  it("parses the captured production payload without loss", () => {
    expect(PROD_PLAN.steps).toHaveLength(19);
    expect(PROD_PLAN.estimatedCostUsd).toBe(0);
    expect(PROD_PLAN.runnable).toBe(true);
    expect(PROD_PLAN.refusal).toBeNull();
    expect(PROD_PLAN.steps[0].key).toBe("scout");
    expect(PROD_PLAN.steps[0].cardNames).toEqual(["Job Discovery Agent"]);
    expect(PROD_PLAN.steps[0].execClass).toBe("silo");
    expect(PROD_PLAN.notes.length).toBeGreaterThan(0);
  });
});
