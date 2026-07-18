/**
 * AGT-AGENTS — unit tests for the Agents screen's pure logic + API schemas.
 * (Node/vitest environment: no DOM — component rendering is proven by the
 * ProviderConfigModal component test + the Playwright E2E scripts.)
 *
 * REQ-PC-1 regression: the Agents screen configures provider credentials fully
 * in-UI. NO helper or copy may tell the user to edit the server `.env` — the
 * former `connectBlockedReason` .env instruction is gone, and the model-lock
 * tooltip points at the in-app config flow, not an environment variable.
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
  formatTokens,
  providerAction,
  providerModelDisabledReason,
  providerSourceBadge,
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
  it("connected → click opens the manage/rotate flow", () => {
    const a = providerAction("connected");
    expect(a.label).toBe("Connected · Manage");
  });
  it("warning → re-authenticate", () => {
    expect(providerAction("warning").label).toBe("Re-authenticate");
  });
  it("unconfigured → configure keys", () => {
    const a = providerAction("unconfigured");
    expect(a.label).toBe("Configure keys");
  });
});

describe("agentStatusLabel", () => {
  it("maps every status", () => {
    expect(agentStatusLabel("active")).toBe("Active");
    expect(agentStatusLabel("paused")).toBe("Paused");
    expect(agentStatusLabel("error")).toBe("Error");
  });
});

// REQ-PC-1: disabled controls must explain the lock via the in-app config
// flow — never by instructing the user to edit the server `.env`.
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

  it("points at the in-app config flow, never the server .env", () => {
    const reason = providerModelDisabledReason(base) ?? "";
    expect(reason.toLowerCase()).not.toContain(".env");
    expect(reason.toLowerCase()).not.toMatch(/environment variable/);
    expect(reason).toMatch(/configure/i);
  });

  it("returns null once the provider has models to choose from", () => {
    expect(providerModelDisabledReason({ ...base, models: ["claude-sonnet-5"] })).toBeNull();
  });
});

// REQ-PC-6: the source badge is derived honestly from the backend `source`
// field — "Saved in app" ONLY when the credential really lives in the DB.
describe("providerSourceBadge", () => {
  it("maps database → Saved in app", () => {
    expect(providerSourceBadge({ source: "database", status: "connected" })).toEqual({
      label: "Saved in app",
      tone: "saved",
    });
  });
  it("maps environment → From environment", () => {
    expect(providerSourceBadge({ source: "environment", status: "connected" })).toEqual({
      label: "From environment",
      tone: "env",
    });
  });
  it("maps none → Not configured", () => {
    expect(providerSourceBadge({ source: "none", status: "unconfigured" })).toEqual({
      label: "Not configured",
      tone: "none",
    });
  });
  it("never fabricates 'Saved in app' when the backend has not enriched source", () => {
    // Legacy row (no `source`): fall back to the honest status signal.
    expect(providerSourceBadge({ status: "connected" }).tone).not.toBe("saved");
    expect(providerSourceBadge({ status: "unconfigured" })).toEqual({
      label: "Not configured",
      tone: "none",
    });
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
      model: "claude-sonnet-5",
      recommended: "claude-sonnet-5",
      tip: "Best with claude-sonnet-5",
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
      model: "claude-sonnet-5",
      detail: "Claude Pro",
      models: ["claude-sonnet-5"],
      icon: "fa-a",
      color: "#D97757",
    });
    expect(p.id).toBe("anthropic");
    expect(() => ProviderSchema.parse({ ...p, status: "nope" })).toThrow();
  });

  it("parses the enriched provider fields (source/authMode/secretHint/lastVerify*)", () => {
    const p = ProviderSchema.parse({
      id: "anthropic",
      name: "Anthropic Claude",
      auth: "Subscription / API Key",
      status: "connected",
      model: "claude-opus-4-8",
      detail: "Claude subscription · quota billed to Anthropic",
      models: ["claude-opus-4-8"],
      icon: "fa-a",
      color: "#D97757",
      source: "database",
      authMode: "subscription_oauth",
      secretHint: "…x4Qz",
      lastVerifiedAt: "2026-07-14T00:00:00Z",
      lastVerifyStatus: "ok",
    });
    expect(p.source).toBe("database");
    expect(p.authMode).toBe("subscription_oauth");
    expect(p.secretHint).toBe("…x4Qz");
    expect(p.lastVerifyStatus).toBe("ok");
  });

  it("still parses a legacy provider row with no enriched fields", () => {
    const p = ProviderSchema.parse({
      id: "openrouter",
      name: "OpenRouter",
      auth: "API Key",
      status: "connected",
      model: "",
      detail: "API key configured",
      models: ["deepseek/deepseek-chat"],
      icon: "fa-route",
      color: "#6467F2",
    });
    expect(p.source).toBeUndefined();
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
        model: "claude-sonnet-5",
        estTokens: 4200,
        estCost: 0.032,
        actualCost: 0.031,
        actualTokens: 4180,
        responseSeconds: 1.8,
        creditsCharged: 0,
      }).creditsCharged,
    ).toBe(0);
  });

  it("MV-agents-003: accepts the honest null shape for a deterministic/planned agent's test-run (never throws)", () => {
    // The backend never returns a raw null `model` (it falls back to
    // "deterministic"), but genuinely has no cost/token ESTIMATE or "actual"
    // run figures for a non-LLM/never-run agent — those fields must parse as
    // null, not throw a raw Zod error, which was the exact reported defect.
    const parsed = TestRunSchema.parse({
      agent_key: "jobDiscovery",
      name: "Job Discovery Agent",
      model: "deterministic",
      estTokens: null,
      estCost: null,
      actualCost: null,
      actualTokens: null,
      responseSeconds: null,
      creditsCharged: 0,
    });
    expect(parsed.model).toBe("deterministic");
    expect(parsed.estTokens).toBeNull();
    expect(parsed.actualCost).toBeNull();
  });
});
