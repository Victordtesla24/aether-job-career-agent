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
import type { AgentPolicy } from "../../lib/api/agentPolicy";

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
