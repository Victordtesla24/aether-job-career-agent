// @vitest-environment jsdom
/**
 * MODEL-SUB-QUOTA clause 5 (DISCLOSURE) — OWNER DIRECTIVE 2026-08-17.
 *
 * "I want all the claude requests to use my Anthropic Pro Subscription quota
 *  instead of consuming extra credits via an API_KEY including for openrouter."
 *
 * The routing half of that directive lives in the API (see
 * apps/api/tests/test_model_sub_quota.py). This file pins the half a USER can
 * see: a Claude model must be offered under its OWN "Anthropic — your
 * subscription" group, never inside the OpenRouter tier list, and the picker's
 * billing disclosure must say so. A picker that lists Claude among the
 * OpenRouter models tells the user their Claude runs bill to OpenRouter —
 * which is now false, and was the misleading half of the defect.
 *
 * Drives the REAL AgentModelPicker; no network, no api-client mock needed (the
 * component is fed its catalogs as props).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AgentModelPicker from "../../components/agents/AgentModelPicker";
import type { ProviderModel } from "../../components/agents/api";

/** The curated OpenRouter catalog — post-fix it carries NO claude row. */
const OPENROUTER_MODELS: ProviderModel[] = [
  { id: "deepseek/deepseek-chat", name: "DeepSeek Chat", promptPerM: 0.14, completionPerM: 0.28, contextLength: 128000, tier: "budget", reasoning: false },
  { id: "x-ai/grok-4", name: "Grok 4", promptPerM: 20, completionPerM: 100, contextLength: 131072, tier: "premium", reasoning: false },
];

/** The app's Anthropic catalog — what the operator's subscription serves. */
const ANTHROPIC_MODELS: ProviderModel[] = [
  { id: "claude-haiku-4-5", name: "Claude Haiku 4.5", promptPerM: 1, completionPerM: 5, contextLength: 200000, tier: "budget", reasoning: false },
  { id: "claude-opus-4-8", name: "Claude Opus 4.8", promptPerM: 15, completionPerM: 75, contextLength: 200000, tier: "premium", reasoning: true },
];

function renderPicker(overrides: Record<string, unknown> = {}) {
  return render(
    <AgentModelPicker
      agentKey="coverLetter"
      currentModel="claude-opus-4-8"
      models={OPENROUTER_MODELS}
      loading={false}
      error={null}
      saving={false}
      subscriptionModels={ANTHROPIC_MODELS}
      onSelect={vi.fn()}
      {...overrides}
    />,
  );
}

function openPanel() {
  fireEvent.click(screen.getByTestId("agent-model-trigger-coverLetter"));
}

afterEach(() => {
  cleanup();
});

describe("MODEL-SUB-QUOTA — Claude models are disclosed as subscription-served", () => {
  it("lists the Claude models under an 'Anthropic — your subscription' group", () => {
    renderPicker();
    openPanel();

    const group = screen.getByTestId("agent-model-group-anthropic-coverLetter");
    expect(group.textContent).toContain("Anthropic — your subscription");
    // Both Claude models are offered, and they live INSIDE that group — not in
    // the OpenRouter tier list rendered below it.
    for (const m of ANTHROPIC_MODELS) {
      const option = screen.getByTestId(`model-option-${m.id}`);
      expect(group.contains(option)).toBe(true);
    }
    // The OpenRouter models are still offered, outside that group.
    for (const m of OPENROUTER_MODELS) {
      const option = screen.getByTestId(`model-option-${m.id}`);
      expect(group.contains(option)).toBe(false);
    }
  });

  it("says Claude never routes through OpenRouter in the billing disclosure", () => {
    renderPicker();
    openPanel();

    const panel = screen.getByTestId("agent-model-picker-coverLetter");
    const text = panel.textContent ?? "";
    expect(text).toContain("Anthropic");
    expect(text).toMatch(/never route through OpenRouter/i);
    expect(text).toContain("served on the Anthropic subscription");
  });

  it("selects a Claude model by its BARE id — never a namespaced one", () => {
    const onSelect = vi.fn();
    renderPicker({ onSelect });
    openPanel();

    fireEvent.click(screen.getByTestId("model-option-claude-opus-4-8"));
    expect(onSelect).toHaveBeenCalledWith("claude-opus-4-8");
    // A namespaced spelling would route through OpenRouter's catalog in the
    // user's mind and is not what the picker offers.
    for (const call of onSelect.mock.calls) {
      expect(String(call[0])).not.toContain("anthropic/");
    }
  });

  it("filters the subscription group with the same search box as the rest", () => {
    renderPicker();
    openPanel();

    fireEvent.change(screen.getByTestId("agent-model-search-coverLetter"), {
      target: { value: "haiku" },
    });
    expect(screen.getByTestId("model-option-claude-haiku-4-5")).toBeTruthy();
    expect(screen.queryByTestId("model-option-claude-opus-4-8")).toBeNull();
    expect(screen.queryByTestId("model-option-x-ai/grok-4")).toBeNull();
  });

  it("shows no subscription group on the Orchestrator card (already Anthropic-fed)", () => {
    renderPicker({
      agentKey: "coverLetter",
      catalogProvider: "anthropic",
      models: ANTHROPIC_MODELS,
    });
    openPanel();

    expect(
      screen.queryByTestId("agent-model-group-anthropic-coverLetter"),
    ).toBeNull();
    // …and the Claude models are still offered — from the main list.
    expect(screen.getByTestId("model-option-claude-opus-4-8")).toBeTruthy();
  });

  it("renders no subscription group when no Anthropic catalog was supplied", () => {
    renderPicker({ subscriptionModels: null });
    openPanel();

    expect(
      screen.queryByTestId("agent-model-group-anthropic-coverLetter"),
    ).toBeNull();
    expect(screen.getByTestId("model-option-deepseek/deepseek-chat")).toBeTruthy();
  });
});
