// @vitest-environment jsdom
/**
 * U-AX build spec item 5(b) — per-run "policy inputs consumed".
 *
 * U-PLAN.md U-AX BUILD SPEC ADDITIONS item 2(b): "every new tailor/cover run
 * displays 'policy inputs consumed' (the metric snapshot the agent sourced)
 * and the resulting effort level." Item 5 (binding): "Every REAL agent's runs
 * record + display the metric snapshot consumed and the resulting rigor
 * level (per-run visibility ...) — per-agent, not just global."
 *
 * Component does not exist on `main` yet —
 * `../../components/agents/RunPolicyInputs` (test-author-chosen path).
 * Written BEFORE implementation.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import RunPolicyInputs from "../../components/agents/RunPolicyInputs";
import type { AgentRun } from "../../lib/api/agents";

afterEach(cleanup);

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "r1",
    agentName: "tailor",
    status: "completed",
    input: null,
    output: null,
    error: null,
    costUsd: null,
    startedAt: "2026-08-13T10:00:00Z",
    completedAt: "2026-08-13T10:00:05Z",
    createdAt: "2026-08-13T10:00:00Z",
    ...overrides,
  };
}

describe("RunPolicyInputs — per-run 'policy inputs consumed' visibility", () => {
  it("renders the metric snapshot consumed and the resulting effort level", () => {
    const withPolicy = run({
      input: {
        qualityPolicy: {
          tier: "heightened",
          triggers: ["conversion_below_20pct_target"],
          metricSnapshot: { sampleSize: 40, conversionRate: 0.12 },
        },
      },
    });
    render(<RunPolicyInputs run={withPolicy} />);
    const el = screen.getByTestId("run-policy-inputs");
    expect(el.textContent).toMatch(/policy inputs consumed/i);
    expect(el.textContent).toMatch(/heightened/i);
    expect(el.textContent).toMatch(/0\.12|12%/);
  });

  it("is honest ('not recorded') for a run predating this instrumentation, never fabricated", () => {
    const legacyRun = run({ input: { job_id: "j1" } }); // no qualityPolicy key
    render(<RunPolicyInputs run={legacyRun} />);
    const el = screen.getByTestId("run-policy-inputs");
    expect(el.textContent).toMatch(/not recorded|no policy/i);
    expect(el.textContent).not.toMatch(/heightened|standard/i);
  });
});
