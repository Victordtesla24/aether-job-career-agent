// @vitest-environment node
/**
 * ORCH-ADV-011 — the orchestration legend must not glow in retired coral.
 * ORCH-ADV-014 — node detail must be able to name team role / neighbours.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { OrchestrationMapAgentSchema } from "../../lib/api/agentPolicy";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAP_SRC = path.resolve(
  HERE,
  "../../components/agents/OrchestrationMap.tsx",
);

describe("ORCH-ADV — brand and team contract on the orchestration map", () => {
  it("does not hardcode retired coral #FF6B35 in the live-run legend", () => {
    const src = readFileSync(MAP_SRC, "utf8");
    expect(src.toUpperCase()).not.toContain("FF6B35");
    expect(src).not.toContain("255,107,53");
  });

  it("renders the team's role and neighbours in the node detail panel", () => {
    const src = readFileSync(MAP_SRC, "utf8");
    expect(src).toContain("Team role");
    expect(src).toContain("Depends on");
    expect(src).toContain("Supports");
  });

  it("keeps team fields on the orchestration-map client schema", () => {
    const parsed = OrchestrationMapAgentSchema.parse({
      agentKey: "storyExtraction",
      name: "Story Extraction Agent",
      backend: "storyExtractor",
      status: "real",
      metricsConsumed: ["evidence stories captured"],
      thresholds: [],
      lastRunPolicyTier: null,
      trend: null,
      teamRole: "Banks STAR evidence the writing agents are allowed to use.",
      dependsOn: [],
      supports: ["resumeTailoring", "coverLetter"],
    });
    expect(parsed.teamRole).toMatch(/STAR evidence/);
    expect(parsed.dependsOn).toEqual([]);
    expect(parsed.supports).toEqual(["resumeTailoring", "coverLetter"]);
  });
});
