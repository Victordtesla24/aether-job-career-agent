// @vitest-environment jsdom
/**
 * U-AX build spec item 5(a) — the "Agent Performance Policy" panel.
 *
 * U-PLAN.md U-AX BUILD SPEC ADDITIONS item 2(a): "a 'Agent Performance
 * Policy' panel — current rigor tier, WHICH metrics triggered it (conversion
 * vs 20% target, dimension scores vs 80% floor), and what the agents are
 * doing differently at this tier."
 *
 * Component does not exist on `main` yet — `../../components/agents/AgentPolicyPanel`
 * (test-author-chosen path, mirroring the existing `components/agents/Orchestration`
 * sibling). Written BEFORE implementation.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import AgentPolicyPanel from "../../components/agents/AgentPolicyPanel";
import type { AgentDirective, AgentPolicy } from "../../lib/api/agentPolicy";

afterEach(cleanup);

function policy(overrides: Partial<AgentPolicy> = {}): AgentPolicy {
  return {
    tier: "standard",
    triggers: [],
    metricSnapshot: { sampleSize: 50, conversionRate: 0.25, dimensionScores: {} },
    perAgent: [],
    ...overrides,
  };
}

describe("AgentPolicyPanel — honest tier + trigger disclosure", () => {
  it("renders the current tier", () => {
    render(<AgentPolicyPanel policy={policy({ tier: "heightened" })} />);
    expect(screen.getByTestId("agent-policy-tier").textContent).toMatch(/heightened/i);
  });

  it("renders which metrics triggered a heightened tier", () => {
    render(
      <AgentPolicyPanel
        policy={policy({
          tier: "heightened",
          triggers: ["conversion_below_20pct_target", "dimension_below_80pct_floor:cultureFit"],
        })}
      />,
    );
    const panel = screen.getByTestId("agent-policy-panel");
    expect(panel.textContent).toMatch(/conversion/i);
    expect(panel.textContent).toMatch(/culturefit/i);
  });

  it("never claims a trigger when the tier is standard (honest empty state)", () => {
    render(<AgentPolicyPanel policy={policy({ tier: "standard", triggers: [] })} />);
    expect(screen.queryByTestId("agent-policy-triggers")?.textContent ?? "").not.toMatch(
      /below.*target|below.*floor/i,
    );
  });

  it("renders an honest 'insufficient data' state distinct from standard/heightened", () => {
    render(
      <AgentPolicyPanel
        policy={policy({ tier: "insufficient_data", triggers: [] })}
      />,
    );
    const tier = screen.getByTestId("agent-policy-tier").textContent ?? "";
    expect(tier).toMatch(/insufficient/i);
    expect(tier).not.toMatch(/standard|healthy/i);
  });

  // F-UAX-04: this panel's metrics are computed ALL-TIME
  // (quality_policy.resolve_policy_for_user has no period filter) while the
  // page's own conversion figures honour the selected period — the window
  // must be labelled so the two are never read as the same measurement.
  it("labels its metric window as all-time", () => {
    render(<AgentPolicyPanel policy={policy()} />);
    expect(screen.getByTestId("agent-policy-window").textContent).toMatch(/all-time/i);
  });
});

// ---------------------------------------------------------------------------
// B1b (ADR-AGI-2 P1) — the "Supervisor directives" block,
// ORCH-B1-BLUEPRINT-2026-08-14.md §8.1/§8.2.
// ---------------------------------------------------------------------------

function directive(overrides: Partial<AgentDirective> = {}): AgentDirective {
  return {
    id: "dir-1",
    agentKey: "tailor",
    status: "active",
    directive: { maxIterations: 7, targetScore: 88 },
    clamped: {},
    rejectedKeys: [],
    rationale: "Tighten tailoring effort — interview conversion 0.0% over 50 submissions.",
    metricsCited: { conversionRate: 0, sampleSize: 50 },
    issuedBy: "supervisor-rules",
    supersededById: null,
    outcome: null,
    issuedAt: "2026-08-14T00:00:00Z",
    expiresAt: null,
    ...overrides,
  };
}

describe("AgentPolicyPanel — B1b Supervisor directives (present/absent states)", () => {
  it("renders NOTHING for the directives block when there are none (absent state)", () => {
    render(<AgentPolicyPanel policy={policy({ knobs: { maxIterations: 5, targetScore: 85 } })} directives={[]} />);
    expect(screen.queryByTestId("agent-policy-directives")).toBeNull();
  });

  it("renders NOTHING when the directives prop is simply omitted (backward-compatible default)", () => {
    render(<AgentPolicyPanel policy={policy()} />);
    expect(screen.queryByTestId("agent-policy-directives")).toBeNull();
  });

  it("renders an active directive with its rationale VERBATIM and the tier baseline beside it", () => {
    render(
      <AgentPolicyPanel
        policy={policy({
          tier: "heightened",
          knobs: { maxIterations: 5, targetScore: 85, coverLetterRetries: 2 },
        })}
        directives={[directive()]}
      />,
    );
    const block = screen.getByTestId("agent-policy-directives");
    expect(block.textContent).toMatch(/1 active/i);
    expect(block.textContent).toMatch(/Résumé Tailoring/i);
    // Amended value AND baseline both legible — "tightened" must be a
    // visible delta, never a bare number.
    expect(block.textContent).toMatch(/7/);
    expect(block.textContent).toMatch(/baseline 5/i);
    // The rationale is the API's own string, unparaphrased.
    expect(screen.getByTestId("agent-policy-directive-rationale").textContent).toBe(
      "Tighten tailoring effort — interview conversion 0.0% over 50 submissions.",
    );
  });

  it("renders multiple active directives, one row each", () => {
    render(
      <AgentPolicyPanel
        policy={policy({ knobs: { maxIterations: 5, targetScore: 85, coverLetterRetries: 2 } })}
        directives={[
          directive({ id: "dir-1", agentKey: "tailor" }),
          directive({
            id: "dir-2",
            agentKey: "coverLetter",
            directive: { coverLetterRetries: 3 },
            rationale: "Tighten cover-letter correction — cultureFit scored 45.0 against the 80 floor.",
          }),
        ]}
      />,
    );
    const rows = screen.getAllByTestId("agent-policy-directive-row");
    expect(rows).toHaveLength(2);
    expect(screen.getByTestId("agent-policy-directives").textContent).toMatch(/2 active/i);
    expect(rows[1].textContent).toMatch(/Cover Letter/i);
  });

  it("renders a clamped entry plainly (the clamp is a product-honesty feature)", () => {
    render(
      <AgentPolicyPanel
        policy={policy({ knobs: { maxIterations: 5 } })}
        directives={[
          directive({
            directive: { maxIterations: 10 },
            clamped: { maxIterations: { requested: 12, applied: 10, reason: "ceiling" } },
          }),
        ]}
      />,
    );
    const clamped = screen.getByTestId("agent-policy-directive-clamped");
    expect(clamped.textContent).toMatch(/asked for 12/i);
    expect(clamped.textContent).toMatch(/ceiling is 10/i);
  });

  it("never renders a directive AS the tier — the tier badge is unaffected by directives", () => {
    render(
      <AgentPolicyPanel
        policy={policy({ tier: "standard", knobs: { maxIterations: 5 } })}
        directives={[directive()]}
      />,
    );
    expect(screen.getByTestId("agent-policy-tier").textContent).toMatch(/standard/i);
    expect(screen.getByTestId("agent-policy-tier").textContent).not.toMatch(/heightened/i);
  });

  it("renders the paused caption and greys the block when directive issuance is paused", () => {
    render(
      <AgentPolicyPanel
        policy={policy({ knobs: { maxIterations: 5 } })}
        directives={[directive()]}
        directivesPaused
      />,
    );
    const block = screen.getByTestId("agent-policy-directives");
    expect(block.getAttribute("data-paused")).toBe("true");
    expect(block.textContent).toMatch(/not currently applied/i);
    expect(block.textContent).toMatch(/paused/i);
  });

  it("does NOT show the paused caption when directives are live", () => {
    render(
      <AgentPolicyPanel
        policy={policy({ knobs: { maxIterations: 5 } })}
        directives={[directive()]}
        directivesPaused={false}
      />,
    );
    const block = screen.getByTestId("agent-policy-directives");
    expect(block.getAttribute("data-paused")).toBe("false");
    expect(block.textContent).not.toMatch(/paused/i);
  });
});
