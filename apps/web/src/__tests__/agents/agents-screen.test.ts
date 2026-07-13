/**
 * AGT-AGENTS — unit tests for the Agents screen's pure logic + API schemas.
 * (Node/vitest environment: no DOM — component rendering is proven by the
 * Playwright E2E scripts in the evidence dir.)
 */
import { describe, expect, it } from "vitest";

import {
  CatalogAgentSchema,
  ProviderSchema,
  StatsSchema,
  TestRunSchema,
} from "../../components/agents/api";
import {
  agentRunDisabledReason,
  agentStatusLabel,
  connectBlockedReason,
  formatTokens,
  providerAction,
  providerModelDisabledReason,
} from "../../components/agents/logic";
import type { CatalogAgent, Provider } from "../../components/agents/api";

describe("formatTokens", () => {
  it("formats millions / thousands / units", () => {
    expect(formatTokens(3_420_000)).toBe("3.42M");
    expect(formatTokens(4_200)).toBe("4.2K");
    expect(formatTokens(120)).toBe("120");
    expect(formatTokens(0)).toBe("0");
  });
});

describe("providerAction", () => {
  it("connected → click disconnects", () => {
    const a = providerAction("connected");
    expect(a.label).toBe("Connected · Manage");
    expect(a.next).toBe("unconfigured");
  });
  it("warning → re-authenticate connects", () => {
    expect(providerAction("warning").next).toBe("connected");
  });
  it("unconfigured → configure keys connects", () => {
    const a = providerAction("unconfigured");
    expect(a.label).toBe("Configure keys");
    expect(a.next).toBe("connected");
  });
});

describe("connectBlockedReason", () => {
  // GAP-P4-054 regression: the "Configure keys" / "Add Provider" actions must
  // not fire a PUT that the server is guaranteed to 409 (D-0020). The client
  // already knows a provider is unconfigured from GET /agents/providers, so
  // it should short-circuit locally instead of letting the request fail.
  it("blocks connecting an unconfigured provider (server has no credential)", () => {
    const reason = connectBlockedReason({ name: "Anthropic Claude", status: "unconfigured" });
    expect(reason).not.toBeNull();
    expect(reason).toContain("Anthropic Claude");
    expect(reason).toContain("credential");
  });

  it("does not block a connected provider", () => {
    expect(connectBlockedReason({ name: "OpenAI", status: "connected" })).toBeNull();
  });

  it("does not block a warning-status provider (re-authenticate may succeed)", () => {
    expect(connectBlockedReason({ name: "Google Gemini", status: "warning" })).toBeNull();
  });
});

describe("agentStatusLabel", () => {
  it("maps every status", () => {
    expect(agentStatusLabel("active")).toBe("Active");
    expect(agentStatusLabel("paused")).toBe("Paused");
    expect(agentStatusLabel("error")).toBe("Error");
  });
});

// GAP-P4-056: disabled controls (unconfigured provider models, disabled
// agents) must explain the D-0020 lock via a tooltip, not just render
// disabled with no reason surfaced.
describe("providerModelDisabledReason", () => {
  const base: Provider = {
    id: "anthropic",
    name: "Anthropic Claude",
    auth: "API Key",
    status: "unconfigured",
    model: "",
    detail: "Not configured",
    models: [],
    icon: "fa-a",
    color: "#D97757",
  };

  it("explains the lock when a provider has no selectable models", () => {
    const reason = providerModelDisabledReason(base);
    expect(reason).toContain("Anthropic Claude");
    expect(reason).toMatch(/no selectable models/i);
  });

  it("returns null once the provider has models to choose from", () => {
    expect(providerModelDisabledReason({ ...base, models: ["claude-sonnet-4"] })).toBeNull();
  });
});

describe("agentRunDisabledReason", () => {
  const base: Pick<CatalogAgent, "name" | "enabled"> = {
    name: "Match Scoring Agent",
    enabled: false,
  };

  it("explains the lock when the agent is disabled", () => {
    const reason = agentRunDisabledReason(base);
    expect(reason).toContain("Match Scoring Agent");
    expect(reason).toMatch(/disabled/i);
  });

  it("returns null once the agent is enabled", () => {
    expect(agentRunDisabledReason({ ...base, enabled: true })).toBeNull();
  });
});

describe("API schemas", () => {
  it("parses a valid catalog agent", () => {
    const parsed = CatalogAgentSchema.parse({
      key: "resumeTailoring",
      name: "Resume Tailoring Agent",
      icon: "fa-file-pen",
      accent: "coral",
      model: "claude-sonnet-4",
      recommended: "claude-sonnet-4",
      tip: "Best with claude-sonnet-4",
      runnable: true,
      backend: "tailor",
      enabled: true,
      status: "active",
      last_run: null,
    });
    expect(parsed.status).toBe("active");
  });

  it("rejects an invalid agent status", () => {
    expect(() =>
      CatalogAgentSchema.parse({
        key: "x",
        name: "x",
        icon: "x",
        accent: "coral",
        model: "m",
        recommended: "m",
        tip: "t",
        runnable: false,
        enabled: true,
        status: "on-fire",
      }),
    ).toThrow();
  });

  it("parses a provider and rejects a bad status", () => {
    const p = ProviderSchema.parse({
      id: "anthropic",
      name: "Anthropic Claude",
      auth: "API Key",
      status: "connected",
      model: "claude-sonnet-4",
      detail: "Claude Pro",
      models: ["claude-sonnet-4"],
      icon: "fa-a",
      color: "#D97757",
    });
    expect(p.id).toBe("anthropic");
    expect(() => ProviderSchema.parse({ ...p, status: "nope" })).toThrow();
  });

  it("parses stats and a test-run result", () => {
    expect(
      StatsSchema.parse({
        spendUsd: 1.2,
        avgCostPerRun: 0.04,
        providerCount: 6,
        tokensTotal: 4200,
        tokensIn: 2800,
        tokensOut: 1400,
        mostActiveAgent: { name: "Resume Tailoring", tasks: 3 },
        successRate: 94.2,
        taskCount: 10,
      }).providerCount,
    ).toBe(6);

    expect(
      TestRunSchema.parse({
        agent_key: "resumeTailoring",
        name: "Resume Tailoring Agent",
        model: "claude-sonnet-4",
        estTokens: 4200,
        estCost: 0.032,
        actualCost: 0.031,
        actualTokens: 4180,
        responseSeconds: 1.8,
        creditsCharged: 0,
      }).creditsCharged,
    ).toBe(0);
  });
});
