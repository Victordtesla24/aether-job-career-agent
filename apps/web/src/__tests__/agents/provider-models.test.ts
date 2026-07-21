/**
 * GAP-P7-MODEL-CHOICE-001 — `fetchProviderModels` contract + the pure model
 * picker helpers (budget/tier formatting, grouping, filtering, preset
 * derivation). Node/vitest env (no DOM): the API client is stubbed at the
 * transport boundary (`apiRequest`) while the REAL `ApiError` is kept, so the
 * honest no-key 400 path is exercised exactly as production throws it. The
 * component test proves these helpers render.
 */
import { describe, expect, it, vi } from "vitest";

const apiRequestMock = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api/client")>("../../lib/api/client");
  return { ...actual, apiRequest: apiRequestMock };
});

import {
  ProviderModelSchema,
  fetchProviderModels,
  type ProviderModel,
} from "../../components/agents/api";
import { ApiError } from "../../lib/api/client";
import {
  deriveBudgetPresetModel,
  filterModels,
  formatContextLength,
  formatModelPrice,
  groupModelsByTier,
} from "../../components/agents/logic";

const MODELS: ProviderModel[] = [
  { id: "free/reasoner", name: "Free Reasoner", promptPerM: 0, completionPerM: 0, contextLength: 65536, tier: "free", reasoning: true },
  { id: "deepseek/deepseek-chat", name: "DeepSeek Chat", promptPerM: 0.14, completionPerM: 0.28, contextLength: 128000, tier: "budget", reasoning: false },
  { id: "openai/gpt-4o-mini", name: "GPT-4o mini", promptPerM: 0.15, completionPerM: 0.6, contextLength: 128000, tier: "budget", reasoning: true },
  { id: "anthropic/claude-sonnet", name: "Claude Sonnet", promptPerM: 3, completionPerM: 15, contextLength: 200000, tier: "standard", reasoning: false },
  { id: "anthropic/claude-opus", name: "Claude Opus", promptPerM: 15, completionPerM: 75, contextLength: 200000, tier: "premium", reasoning: true },
  { id: "x-ai/grok-heavy", name: "Grok Heavy", promptPerM: 20, completionPerM: 100, contextLength: 131072, tier: "premium", reasoning: false },
];

const NO_KEY_DETAIL =
  "Add an OpenRouter API key (in the Agents panel or the server env) to browse the live model catalog.";

// NB: each test sets its own apiRequest mock behaviour (which fully replaces
// the prior implementation), so no shared reset hook is needed — and a
// `beforeEach` that calls mockReset/mockClear on a hoisted mock trips a
// vitest 2.1.9 phantom "unhandled rejection" for the rejecting-mock case.

describe("fetchProviderModels", () => {
  it("parses the {provider,count,models} contract and returns the models", async () => {
    apiRequestMock.mockReset();
    apiRequestMock.mockResolvedValue({ provider: "openrouter", count: MODELS.length, models: MODELS });

    const out = await fetchProviderModels("openrouter");

    expect(apiRequestMock).toHaveBeenCalledWith("/agents/providers/openrouter/models", {});
    expect(out).toHaveLength(MODELS.length);
    expect(out[0]).toMatchObject({ id: "free/reasoner", tier: "free", reasoning: true });
  });

  it("accepts a null contextLength (contract: number|null)", () => {
    const parsed = ProviderModelSchema.parse({
      id: "a/b",
      name: "A B",
      promptPerM: 1,
      completionPerM: 2,
      contextLength: null,
      tier: "standard",
      reasoning: false,
    });
    expect(parsed.contextLength).toBeNull();
  });

  it("throws a READABLE ApiError carrying the backend detail on the no-key 400", async () => {
    apiRequestMock.mockReset();
    apiRequestMock.mockRejectedValue(
      new ApiError(
        `GET /agents/providers/openrouter/models failed (400): {"detail":"${NO_KEY_DETAIL}"}`,
        400,
      ),
    );

    let err: unknown;
    try {
      await fetchProviderModels("openrouter");
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(400);
    // The thrown message is the clean detail — not apiRequest's raw wrapper.
    expect((err as ApiError).message).toBe(NO_KEY_DETAIL);
    expect((err as ApiError).message).not.toContain("failed (400)");
  });

  it("rejects a malformed catalog row (bad tier) instead of rendering garbage", async () => {
    apiRequestMock.mockReset();
    apiRequestMock.mockResolvedValue({
      provider: "openrouter",
      count: 1,
      models: [{ ...MODELS[0], tier: "cheap" }],
    });
    await expect(fetchProviderModels("openrouter")).rejects.toBeTruthy();
  });
});

describe("formatModelPrice", () => {
  it("renders $/M prompt + completion, or Free for a zero-priced model", () => {
    expect(formatModelPrice(3, 15)).toBe("$3.00/M in · $15.00/M out");
    expect(formatModelPrice(0.15, 0.6)).toBe("$0.15/M in · $0.60/M out");
    expect(formatModelPrice(0, 0)).toBe("Free");
  });
});

describe("formatContextLength", () => {
  it("compacts to K / M ctx and returns null when unknown", () => {
    expect(formatContextLength(200000)).toBe("200K ctx");
    expect(formatContextLength(1_000_000)).toBe("1M ctx");
    expect(formatContextLength(131072)).toBe("131K ctx");
    expect(formatContextLength(null)).toBeNull();
    expect(formatContextLength(0)).toBeNull();
  });
});

describe("groupModelsByTier", () => {
  it("orders free→budget→standard→premium and drops empty groups", () => {
    const groups = groupModelsByTier(MODELS);
    expect(groups.map((g) => g.tier)).toEqual(["free", "budget", "standard", "premium"]);
    expect(groups.find((g) => g.tier === "budget")?.models).toHaveLength(2);
  });

  it("drops a tier with no models", () => {
    const onlyPremium = MODELS.filter((m) => m.tier === "premium");
    expect(groupModelsByTier(onlyPremium).map((g) => g.tier)).toEqual(["premium"]);
  });
});

describe("filterModels", () => {
  it("filters by name/id substring (case-insensitive)", () => {
    expect(filterModels(MODELS, "grok", "all").map((m) => m.id)).toEqual(["x-ai/grok-heavy"]);
    expect(filterModels(MODELS, "CLAUDE", "all").map((m) => m.id)).toEqual([
      "anthropic/claude-sonnet",
      "anthropic/claude-opus",
    ]);
  });

  it("filters by tier and can combine tier + query", () => {
    expect(filterModels(MODELS, "", "budget").map((m) => m.id)).toEqual([
      "deepseek/deepseek-chat",
      "openai/gpt-4o-mini",
    ]);
    expect(filterModels(MODELS, "gpt", "budget").map((m) => m.id)).toEqual(["openai/gpt-4o-mini"]);
  });
});

describe("deriveBudgetPresetModel", () => {
  it("economy → cheapest reasoning-capable model (free reasoner)", () => {
    expect(deriveBudgetPresetModel(MODELS, "economy")).toBe("free/reasoner");
  });

  it("economy falls back to the cheapest overall when nothing is reasoning-capable", () => {
    const noReason = MODELS.map((m) => ({ ...m, reasoning: false }));
    expect(deriveBudgetPresetModel(noReason, "economy")).toBe("free/reasoner");
  });

  it("balanced → '' (clear the override → app default)", () => {
    expect(deriveBudgetPresetModel(MODELS, "balanced")).toBe("");
  });

  it("premium → a recognised frontier id that exists in the catalog", () => {
    expect(deriveBudgetPresetModel(MODELS, "premium")).toBe("anthropic/claude-opus");
  });

  it("premium → priciest premium-tier model when no id matches a frontier family", () => {
    const generic: ProviderModel[] = [
      { id: "vendor/small", name: "Small", promptPerM: 1, completionPerM: 2, contextLength: 8000, tier: "premium", reasoning: false },
      { id: "vendor/large", name: "Large", promptPerM: 9, completionPerM: 18, contextLength: 8000, tier: "premium", reasoning: false },
    ];
    expect(deriveBudgetPresetModel(generic, "premium")).toBe("vendor/large");
  });

  it("returns null for economy/premium on an empty catalog", () => {
    expect(deriveBudgetPresetModel([], "economy")).toBeNull();
    expect(deriveBudgetPresetModel([], "premium")).toBeNull();
  });
});
