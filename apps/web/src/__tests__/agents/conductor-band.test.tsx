// @vitest-environment jsdom
/**
 * P1-B CONDUCTOR BAND — the surface ADR-AGI-3 Decision 2 (+ the owner's
 * 2026-08-14 addendum) requires above the three workflow maps.
 *
 * WHAT THESE TESTS PIN (each one a way the band could lie to the user):
 *   1. the band states the FULL mandate — the supervisor conducts all three
 *      workflows — and names them from the live payload, not from a constant;
 *   2. the model chip is the LIVE orchestration binding; a console that has
 *      read no config shows that, rather than the ADR's example model;
 *   3. the fallback chain is disclosed as a chain, never as the active binding;
 *   4. the status strip's figures come from GET /agents/orchestration/plan and
 *      the plan preview is stated to cost $0.00 — which is a fact about the
 *      endpoint, not a projection;
 *   5. "Run everything" carries the SERVER's counts, and pressing it runs
 *      NOTHING: it opens a confirmation that shows the plan first;
 *   6. the plan view is reachable WITHOUT running anything, groups the plan by
 *      the three workflows, and shows the story-extraction → tailoring /
 *      cover-letter linkage the owner asked to be able to see;
 *   7. run states are honest end to end: running says running, `partial` is
 *      never dressed as success, a failure shows the server's own words;
 *   8. a refusal from the plan endpoint disables the control and quotes the
 *      refusal verbatim;
 *   9. the band exposes one rail anchor per workflow map, so the connecting
 *      rail cannot be drawn to a workflow that is not on screen.
 *
 * Written BEFORE the implementation.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ConductorBand from "../../components/agents/ConductorBand";
import type { ConductorBandProps } from "../../components/agents/ConductorBand";
import ConductorRail from "../../components/agents/ConductorRail";
import { OrchestrationPlanSchema, type OrchestrationPlan } from "../../lib/api/orchestrationPlan";
import type { OrchestrationMapData } from "../../lib/api/agentPolicy";

import PROD_PLAN_JSON from "./fixtures/orchestration-plan.prod.json";

afterEach(cleanup);

const PLAN: OrchestrationPlan = OrchestrationPlanSchema.parse(PROD_PLAN_JSON);

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

function props(over: Partial<ConductorBandProps> = {}): ConductorBandProps {
  return {
    plan: PLAN,
    planFetchedAt: Date.parse("2026-08-14T21:20:00Z"),
    planError: null,
    maps: MAPS,
    supervisorConfig: {
      key: "orchestration",
      model: "claude-opus-4-8",
      provider: "anthropic",
      authMode: "oauth_token",
    },
    supervisorAgent: { key: "orchestration", name: "Orchestration Agent", model: "claude-opus-4-8" },
    runs: [],
    run: { phase: "idle", planId: null, record: null, error: null },
    onRunEverything: vi.fn(),
    onDismissRun: vi.fn(),
    busyBackend: null,
    ...over,
  };
}

/** A recorded run plan, in the shape GET /agents/orchestration/plans/{id} returns. */
function runRecord(over: Record<string, unknown>) {
  return {
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
  };
}

// ---------------------------------------------------------------------------
// 1. The mandate
// ---------------------------------------------------------------------------

describe("CONDUCTOR BAND — states the full mandate", () => {
  it("mounts as the Conductor and names all three live workflows", () => {
    render(<ConductorBand {...props()} />);
    const band = screen.getByTestId("conductor-band");
    expect(within(band).getByRole("heading", { level: 2 }).textContent).toMatch(/conductor/i);
    expect(band.textContent).toContain("Application Pipeline");
    expect(band.textContent).toContain("Learning Loop");
    expect(band.textContent).toContain("Context & Enrichment");
  });

  it("exposes one rail anchor per workflow map, and no anchor for a map that is not loaded", () => {
    const { rerender } = render(<ConductorBand {...props()} />);
    expect(screen.getByTestId("conductor-anchor-application-pipeline")).toBeTruthy();
    expect(screen.getByTestId("conductor-anchor-learning-loop")).toBeTruthy();
    expect(screen.getByTestId("conductor-anchor-enrichment")).toBeTruthy();
    rerender(
      <ConductorBand
        {...props({ maps: { maps: MAPS.maps.filter((m) => m.key !== "enrichment") } })}
      />,
    );
    expect(screen.queryByTestId("conductor-anchor-enrichment")).toBeNull();
  });
});

describe("CONDUCTOR RAIL — measured or absent", () => {
  function Host({ maps }: { maps: OrchestrationMapData | null }) {
    const ref = { current: null } as React.RefObject<HTMLElement | null>;
    return (
      <div
        ref={(el) => {
          (ref as { current: HTMLElement | null }).current = el;
        }}
      >
        <ConductorRail wrapperRef={ref} maps={maps} />
      </div>
    );
  }

  it("draws nothing when no box can be measured — never a guessed coordinate", () => {
    // jsdom reports zero-sized rects for everything, which is the same state a
    // server render, a hidden tab or a collapsed panel is in.
    render(<Host maps={MAPS} />);
    expect(screen.queryByTestId("conductor-rail")).toBeNull();
  });

  it("draws nothing when no workflow map is loaded", () => {
    render(<Host maps={null} />);
    expect(screen.queryByTestId("conductor-rail")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2 + 3. Binding and fallback chain
// ---------------------------------------------------------------------------

describe("CONDUCTOR BAND — the model binding is live, the chain is disclosed", () => {
  it("shows the live model + credential source", () => {
    render(<ConductorBand {...props()} />);
    expect(screen.getByTestId("conductor-model-chip").textContent).toContain(
      "claude-opus-4-8 · Anthropic subscription",
    );
  });

  it("follows a different live binding instead of the ADR's example", () => {
    render(
      <ConductorBand
        {...props({
          supervisorConfig: {
            key: "orchestration",
            model: "claude-opus-4-9",
            provider: "anthropic",
            authMode: "api_key",
          },
          supervisorAgent: { key: "orchestration", name: "Orchestration Agent", model: "claude-opus-4-9" },
        })}
      />,
    );
    const chip = screen.getByTestId("conductor-model-chip");
    expect(chip.textContent).toContain("claude-opus-4-9 · Anthropic API key");
    expect(screen.getByTestId("conductor-band").textContent).not.toContain("claude-opus-4-8");
  });

  it("says the binding is not read yet rather than printing a model it has not seen", () => {
    render(<ConductorBand {...props({ supervisorConfig: null, supervisorAgent: null })} />);
    const chip = screen.getByTestId("conductor-model-chip");
    expect(chip.textContent).not.toMatch(/claude/i);
    expect(chip.textContent).toMatch(/not read|unavailable|unknown/i);
  });

  it("renders the four-link chain in the ADR's order, marked as fallbacks", () => {
    render(<ConductorBand {...props()} />);
    const chain = screen.getByTestId("conductor-fallback-chain");
    const labels = Array.from(chain.querySelectorAll("[data-fallback-link]")).map(
      (el) => (el as HTMLElement).textContent?.trim() ?? "",
    );
    expect(labels[0]).toContain("Anthropic subscription");
    expect(labels[1]).toContain("OpenRouter");
    expect(labels[2]).toContain("Abacus.ai");
    expect(labels[3]).toContain("Google");
    expect(chain.textContent).toMatch(/quota|exhaust/i);
  });

  it("shows a served-by-fallback chip only when a run recorded one", () => {
    render(<ConductorBand {...props()} />);
    expect(screen.queryByTestId("conductor-fallback-engaged")).toBeNull();
    cleanup();
    render(
      <ConductorBand
        {...props({
          runs: [
            {
              id: "r1",
              agentName: "supervisor",
              status: "completed",
              input: null,
              output: {
                requestedModel: "claude-opus-4-8",
                servedModel: "anthropic/claude-opus-4-8",
                fallbackReason: "anthropic subscription quota exhausted",
              },
              error: null,
              costUsd: 0,
              startedAt: "2026-08-14T09:00:00",
              completedAt: "2026-08-14T09:01:00",
              createdAt: "2026-08-14T09:00:00",
              heartbeatAt: null,
            },
          ],
        })}
      />,
    );
    expect(screen.getByTestId("conductor-fallback-engaged").textContent).toContain(
      "anthropic/claude-opus-4-8",
    );
  });
});

// ---------------------------------------------------------------------------
// 4. The status strip
// ---------------------------------------------------------------------------

describe("CONDUCTOR BAND — the status strip reports the plan endpoint", () => {
  it("states the server's counts and the $0.00 preview cost", () => {
    render(<ConductorBand {...props()} />);
    const strip = screen.getByTestId("conductor-status-strip");
    expect(strip.textContent).toContain("19");
    expect(strip.textContent).toContain("21");
    expect(strip.textContent).toContain("$0.00");
  });

  it("states WHEN the plan was read, and says so honestly before any read", () => {
    render(<ConductorBand {...props()} />);
    expect(screen.getByTestId("conductor-plan-read-at").textContent).toMatch(/\d{1,2}:\d{2}/);
    cleanup();
    render(<ConductorBand {...props({ plan: null, planFetchedAt: null })} />);
    const strip = screen.getByTestId("conductor-status-strip");
    expect(strip.textContent).toMatch(/not read yet|could not|unavailable/i);
    expect(strip.textContent).not.toContain("19");
  });

  it("quotes the plan endpoint's own error when the read failed", () => {
    render(
      <ConductorBand
        {...props({ plan: null, planFetchedAt: null, planError: "plan unavailable (503)" })}
      />,
    );
    expect(screen.getByTestId("conductor-status-strip").textContent).toContain(
      "plan unavailable (503)",
    );
  });
});

// ---------------------------------------------------------------------------
// 5. Run everything — the plan is shown BEFORE anything runs
// ---------------------------------------------------------------------------

describe("CONDUCTOR BAND — Run everything confirms with the plan first", () => {
  it("labels the control with the server's counts", () => {
    render(<ConductorBand {...props()} />);
    expect(screen.getByTestId("conductor-run-everything").textContent).toContain(
      "Run everything (19 agents / 21 cards)",
    );
  });

  it("runs NOTHING on the first press — it opens the plan confirmation", () => {
    const onRunEverything = vi.fn();
    render(<ConductorBand {...props({ onRunEverything })} />);
    fireEvent.click(screen.getByTestId("conductor-run-everything"));
    expect(onRunEverything).not.toHaveBeenCalled();
    const dialog = screen.getByTestId("conductor-confirm");
    expect(dialog.getAttribute("role")).toBe("dialog");
    expect(dialog.textContent).toContain("19");
    expect(dialog.textContent).toContain("21");
    expect(dialog.textContent).toContain("$0.00");
    expect(within(dialog).getByTestId("conductor-plan-view")).toBeTruthy();
  });

  it("dispatches once when the plan is confirmed, and not at all when cancelled", () => {
    const onRunEverything = vi.fn();
    render(<ConductorBand {...props({ onRunEverything })} />);
    fireEvent.click(screen.getByTestId("conductor-run-everything"));
    fireEvent.click(screen.getByTestId("conductor-confirm-cancel"));
    expect(screen.queryByTestId("conductor-confirm")).toBeNull();
    expect(onRunEverything).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("conductor-run-everything"));
    fireEvent.click(screen.getByTestId("conductor-confirm-start"));
    expect(onRunEverything).toHaveBeenCalledTimes(1);
  });

  it("refuses in the API's own words when the plan is not runnable", () => {
    const refusal =
      "background generation is disabled on this deployment, so a plan cannot run";
    render(
      <ConductorBand {...props({ plan: { ...PLAN, runnable: false, refusal } })} />,
    );
    const btn = screen.getByTestId("conductor-run-everything") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.getByTestId("conductor-band").textContent).toContain(refusal);
  });

  it("cannot start a second plan while one is in flight", () => {
    render(
      <ConductorBand
        {...props({ run: { phase: "running", planId: "plan-1", record: null, error: null } })}
      />,
    );
    expect((screen.getByTestId("conductor-run-everything") as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});

// ---------------------------------------------------------------------------
// 6. The plan view, without running anything
// ---------------------------------------------------------------------------

describe("CONDUCTOR BAND — the plan view", () => {
  it("expands without dispatching anything and groups the plan by the three workflows", () => {
    const onRunEverything = vi.fn();
    render(<ConductorBand {...props({ onRunEverything })} />);
    expect(screen.queryByTestId("conductor-plan-view")).toBeNull();
    fireEvent.click(screen.getByTestId("conductor-plan-toggle"));
    const view = screen.getByTestId("conductor-plan-view");
    expect(onRunEverything).not.toHaveBeenCalled();
    expect(within(view).getByTestId("conductor-plan-group-application-pipeline")).toBeTruthy();
    expect(within(view).getByTestId("conductor-plan-group-learning-loop")).toBeTruthy();
    expect(within(view).getByTestId("conductor-plan-group-enrichment")).toBeTruthy();
    expect(view.textContent).toContain("Job Discovery Agent");
    expect(view.textContent).toContain("Story Extraction Agent");
  });

  it("shows the story-extraction linkage into tailoring and the cover letter", () => {
    render(<ConductorBand {...props()} />);
    fireEvent.click(screen.getByTestId("conductor-plan-toggle"));
    const linkages = screen.getByTestId("conductor-plan-linkages");
    expect(linkages.textContent).toContain("Story Extraction Agent");
    expect(linkages.textContent).toContain("Resume Tailoring Agent");
    expect(linkages.textContent).toContain("Cover Letter Agent");
  });
});

// ---------------------------------------------------------------------------
// 7. Honest run states
// ---------------------------------------------------------------------------

describe("CONDUCTOR BAND — run states are honest", () => {
  const record = runRecord;

  it("says running while the server says running, and claims no outcome", () => {
    render(
      <ConductorBand
        {...props({
          run: { phase: "running", planId: "plan-1", record: record({}), error: null },
        })}
      />,
    );
    const status = screen.getByTestId("conductor-run-status");
    expect(status.textContent).toMatch(/running/i);
    expect(status.textContent).not.toMatch(/complete|success/i);
  });

  it("reports a partial plan as partial, never as a completed run", () => {
    render(
      <ConductorBand
        {...props({
          run: {
            phase: "settled",
            planId: "plan-1",
            record: record({
              status: "partial",
              finishedAt: "2026-08-14T09:30:00",
              steps: [
                { key: "scout", backend: "scout", group: 0, state: "completed" },
                { key: "tailor", backend: "tailor", group: 1, state: "failed" },
              ],
            }),
            error: null,
          },
        })}
      />,
    );
    const status = screen.getByTestId("conductor-run-status");
    expect(status.textContent).toMatch(/partly|partial/i);
    expect(status.textContent).not.toMatch(/all \d+ steps? completed/i);
  });

  it("surfaces a start failure in the server's words and offers no fake success", () => {
    render(
      <ConductorBand
        {...props({
          run: {
            phase: "error",
            planId: null,
            record: null,
            error: "A run plan is already in flight for this account",
          },
        })}
      />,
    );
    const status = screen.getByTestId("conductor-run-status");
    expect(status.textContent).toContain("A run plan is already in flight for this account");
    expect(status.textContent).not.toMatch(/success|complete/i);
  });
});

// ---------------------------------------------------------------------------
// 8. The failure signal is PAINTED, not just worded
// ---------------------------------------------------------------------------
/**
 * P1-B round-1 review, must-fix #1.
 *
 * Every assertion in section 7 reads `textContent`. That is the whole hole: a
 * class name naming a colour token Tailwind does not define keeps the words
 * correct while emitting ZERO css rules, so the halted/failed banner — the one
 * element in this component whose job is to signal that something went wrong —
 * renders with no red tint and reads, at a glance, exactly like a healthy one.
 * The shipped band did precisely that: `state-err` is not in the palette
 * (apps/web/tailwind.config.ts defines ok/warn/danger/info/neutral/degraded).
 *
 * These tests close it generically rather than pinning one string: the palette
 * is read out of the REAL Tailwind config at test time, and every `state-*`
 * utility the band can paint with must name a token that file actually defines.
 * A future invented token fails here whatever it is called.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../../../..");
const TAILWIND_CONFIG = "apps/web/tailwind.config.ts";

/** The colour utilities Tailwind can prefix a palette token with. */
const COLOUR_UTILITY =
  "(?:bg|text|border|ring|outline|fill|stroke|from|via|to|shadow|divide|decoration|accent|caret|placeholder)(?:-[trblxyse])?";

/** The `state` palette, read out of the real config — never re-declared here. */
function definedStateTokens(): string[] {
  const source = readFileSync(path.join(REPO_ROOT, TAILWIND_CONFIG), "utf8");
  const block = /\n\s*state:\s*\{([^}]*)\}/.exec(source);
  if (!block) throw new Error(`no theme.extend.colors.state block in ${TAILWIND_CONFIG}`);
  return Array.from(block[1].matchAll(/^\s*([A-Za-z][\w-]*)\s*:/gm)).map((m) => m[1]);
}

/** Every `state-<token>` a source file paints with, from a colour utility only. */
function stateTokensInSource(relPath: string): string[] {
  const source = readFileSync(path.join(REPO_ROOT, relPath), "utf8");
  const found = source.matchAll(new RegExp(`${COLOUR_UTILITY}-state-([a-z][a-z0-9]*)`, "g"));
  return Array.from(new Set(Array.from(found).map((m) => m[1])));
}

/** Every `state-<token>` actually present on a rendered node's class list. */
function stateTokensInDom(root: HTMLElement): string[] {
  const seen = new Set<string>();
  root.querySelectorAll("[class]").forEach((node) => {
    node.classList.forEach((cls) => {
      const m = new RegExp(`^(?:[a-z-]+:)*${COLOUR_UTILITY}-state-([a-z][a-z0-9]*)`).exec(cls);
      if (m) seen.add(m[1]);
    });
  });
  return Array.from(seen);
}

describe("CONDUCTOR BAND — the status banner paints with tokens that exist", () => {
  const record = runRecord;

  it("reads a real state palette out of tailwind.config.ts (and it has no 'err')", () => {
    const tokens = definedStateTokens();
    expect(tokens).toContain("danger");
    expect(tokens).toContain("ok");
    expect(tokens).not.toContain("err");
  });

  it.each([
    "apps/web/src/components/agents/ConductorBand.tsx",
    "apps/web/src/components/agents/ConductorRail.tsx",
  ])("%s paints only with defined state tokens, on every branch", (relPath) => {
    const defined = definedStateTokens();
    const used = stateTokensInSource(relPath);
    const undefinedTokens = used.filter((t) => !defined.includes(t));
    expect({ file: relPath, undefinedTokens }).toEqual({ file: relPath, undefinedTokens: [] });
  });

  const BANNER_CASES = {
    halted: record({ status: "halted", haltedAtStep: "tailor", haltReason: "quota" }),
    failed: record({ status: "failed" }),
    partial: record({ status: "partial" }),
    completed: record({ status: "completed" }),
    running: record({}),
  };

  Object.entries(BANNER_CASES).forEach(([status, rec]) => {
    it(`renders the ${status} banner with state classes Tailwind can resolve`, () => {
      const { container } = render(
        <ConductorBand
          {...props({
            run: { phase: "settled", planId: "plan-1", record: rec, error: null },
          })}
        />,
      );
      const defined = definedStateTokens();
      expect(stateTokensInDom(container).filter((t) => !defined.includes(t))).toEqual([]);
    });
  });

  it("tints the halted banner red — the border AND the background, not the words alone", () => {
    render(
      <ConductorBand
        {...props({
          run: {
            phase: "settled",
            planId: "plan-1",
            record: record({ status: "halted", haltedAtStep: "tailor", haltReason: "quota" }),
            error: null,
          },
        })}
      />,
    );
    const status = screen.getByTestId("conductor-run-status");
    expect(status.className).toContain("border-state-danger/40");
    expect(status.className).toContain("bg-state-danger/10");
  });

  it("tints the 'plan did not start' banner red too", () => {
    render(
      <ConductorBand
        {...props({
          run: { phase: "error", planId: null, record: null, error: "upstream refused" },
        })}
      />,
    );
    const status = screen.getByTestId("conductor-run-status");
    expect(status.className).toContain("border-state-danger/40");
    expect(status.className).toContain("bg-state-danger/10");
  });
});
