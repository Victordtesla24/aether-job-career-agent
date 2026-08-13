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
  creditsBannerState,
  formatTokens,
  LOW_CREDIT_USD_THRESHOLD,
  providerAction,
  providerModelDisabledReason,
  providerSelectCopy,
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

  // ML-U1X-b honesty fix, SUPERSEDED in review round 2 (R-2): this pin
  // originally asserted the reason came back null for ANY connected
  // provider with an empty models seed, on the theory that "connected"
  // alone proves real options exist elsewhere (e.g. Anthropic's static
  // catalog). The round-2 adversarial review found the failure mode that
  // assumption hides: a connected provider whose ACTUAL rendered option
  // count is genuinely zero (cold cache, failed live fetch, an empty
  // published catalog such as abacus/bedrock's seed) would then render a
  // SILENTLY locked control with no explanation at all — worse than a wrong
  // reason. F-4 restored a reason for that case; R-2 fixed what it SAYS —
  // it now branches on the real cause instead of ever claiming credentials
  // are missing. This pin is superseded to assert the surviving contract: a
  // connected provider is NEVER told to "configure its credentials" (that
  // claim is only ever true when `status !== "connected"`), independent of
  // whether a reason string comes back at all. See also the sibling pins in
  // u1x_refix_review.test.tsx ("R-2 — providerModelDisabledReason branches
  // on the real cause").
  it("never claims a connected provider needs to configure credentials, even with an empty models seed", () => {
    const reason = providerModelDisabledReason({ ...base, status: "connected", models: [] });
    expect(reason).not.toMatch(/configure its credentials/i);
  });

  it("still explains the lock for a NOT-connected provider with an empty models seed", () => {
    const reason = providerModelDisabledReason({ ...base, status: "warning", models: [] });
    expect(reason).toMatch(/no selectable models/i);
  });
});

// ML-U1X-refix4 (round-4 structural ruling): providerSelectCopy is now the
// SINGLE branch tree behind both the `title` tooltip AND the visible empty
// `<option>` text for every provider select — no component may hand-write
// either string again (that hand-writing is exactly what let the generic
// branch's option text diverge from its own title; see ProviderConnections
// component pins below). Exhaustive table over every
// status × models-empty/non-empty × fetchError present/absent combination.
describe("providerSelectCopy — single source for title + empty-option text", () => {
  const base: Provider = {
    id: "bedrock",
    name: "AWS Bedrock",
    auth: "IAM / API Key",
    status: "unconfigured",
    model: "",
    detail: "Not configured",
    models: [],
    icon: "fa-aws",
    color: "#FF9900",
  };

  const providerWith = (status: Provider["status"], models: string[]): Provider => ({
    ...base,
    status,
    models,
  });

  type Case = [
    label: string,
    provider: Provider,
    optionCount: number,
    fetchError: string | undefined,
    expectTitle: RegExp | null,
    expectOption: string,
  ];

  const cases: Case[] = [
    // -- connected --------------------------------------------------------
    [
      "connected + empty + no fetchError",
      providerWith("connected", []),
      0,
      undefined,
      /no published models to choose from yet/i,
      "No published models yet",
    ],
    [
      "connected + empty + fetchError",
      providerWith("connected", []),
      0,
      "network timeout after 3 retries",
      /network timeout after 3 retries/,
      "Catalog unavailable — network timeout after 3 retries",
    ],
    [
      "connected + non-empty + no fetchError",
      providerWith("connected", ["m1", "m2"]),
      2,
      undefined,
      null,
      "",
    ],
    [
      "connected + non-empty + fetchError (irrelevant once options exist)",
      providerWith("connected", ["m1", "m2"]),
      2,
      "network timeout after 3 retries",
      null,
      "",
    ],
    // -- warning (needs-reauth) --------------------------------------------
    [
      "warning + empty + no fetchError",
      providerWith("warning", []),
      0,
      undefined,
      /configure its credentials/i,
      "No preset models — configure below",
    ],
    [
      "warning + empty + fetchError (irrelevant while not connected)",
      providerWith("warning", []),
      0,
      "irrelevant — not connected",
      /configure its credentials/i,
      "No preset models — configure below",
    ],
    [
      "warning + non-empty + no fetchError",
      providerWith("warning", ["m1"]),
      1,
      undefined,
      null,
      "",
    ],
    [
      "warning + non-empty + fetchError",
      providerWith("warning", ["m1"]),
      1,
      "irrelevant — not connected",
      null,
      "",
    ],
    // -- unconfigured -------------------------------------------------------
    [
      "unconfigured + empty + no fetchError",
      providerWith("unconfigured", []),
      0,
      undefined,
      /configure its credentials/i,
      "No preset models — configure below",
    ],
    [
      "unconfigured + empty + fetchError (irrelevant while not connected)",
      providerWith("unconfigured", []),
      0,
      "irrelevant — not connected",
      /configure its credentials/i,
      "No preset models — configure below",
    ],
    [
      "unconfigured + non-empty + no fetchError",
      providerWith("unconfigured", ["m1"]),
      1,
      undefined,
      null,
      "",
    ],
    [
      "unconfigured + non-empty + fetchError",
      providerWith("unconfigured", ["m1"]),
      1,
      "irrelevant — not connected",
      null,
      "",
    ],
  ];

  it.each(cases)("%s", (_label, provider, optionCount, fetchError, expectTitle, expectOption) => {
    const copy = providerSelectCopy(provider, optionCount, fetchError);
    if (expectTitle === null) {
      expect(copy.title).toBeNull();
    } else {
      expect(copy.title).toMatch(expectTitle);
    }
    expect(copy.emptyOptionLabel).toBe(expectOption);
  });

  it("providerModelDisabledReason (back-compat wrapper) always returns exactly providerSelectCopy(...).title", () => {
    for (const [, provider, optionCount, fetchError] of cases) {
      expect(providerModelDisabledReason(provider, optionCount, fetchError)).toBe(
        providerSelectCopy(provider, optionCount, fetchError).title,
      );
    }
  });
});

// ML-U1X-b: the low-credit banner's pure display logic — never fabricates a
// number, and distinguishes "no reading yet" from "the reading failed" from
// "a real reading came back low."
describe("creditsBannerState", () => {
  it("stays hidden before the first reading resolves", () => {
    expect(creditsBannerState(null)).toEqual({ kind: "hidden" });
  });

  it("stays hidden for a healthy real reading", () => {
    expect(
      creditsBannerState({ available: true, remaining: 500, total: 1000 }),
    ).toEqual({ kind: "hidden" });
  });

  it("warns with the REAL figures once remaining drops under the threshold", () => {
    const remaining = LOW_CREDIT_USD_THRESHOLD - 1;
    expect(
      creditsBannerState({ available: true, remaining, total: 1000 }),
    ).toEqual({ kind: "low", remaining, total: 1000 });
  });

  it("renders an honest 'unavailable' state on available:false — never hides (which would look healthy)", () => {
    expect(
      creditsBannerState({ available: false, remaining: null, total: null }),
    ).toEqual({ kind: "unavailable" });
  });

  it("renders 'unavailable' for an available:true reading with a null remaining (malformed, never trusted)", () => {
    expect(
      creditsBannerState({ available: true, remaining: null, total: 1000 }),
    ).toEqual({ kind: "unavailable" });
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
