// @vitest-environment jsdom
/**
 * GAP-P7-MODEL-CHOICE-001 — ModelPicker component test.
 *
 * Drives the REAL ModelPicker against a mocked api client (mirroring the
 * ProviderConfigModal test's boundary mocking) and proves the core UX:
 *  - the LIVE catalog renders grouped by budget tier with $/M prices;
 *  - selecting a model persists it via updateProvider(id, {model});
 *  - the Economy / Balanced / Premium presets persist a model id DERIVED from
 *    the fetched catalog (Balanced clears the override with {model: ""});
 *  - the honest no-key 400 path renders the backend detail and never crashes
 *    or fabricates a list;
 *  - a loading spinner shows while the catalog is in flight, and search filters
 *    the list.
 *
 * This project does not install @testing-library/jest-dom, so assertions use
 * plain DOM properties / vitest matchers only.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchProviderModelsMock = vi.hoisted(() => vi.fn());
const updateProviderMock = vi.hoisted(() => vi.fn());

vi.mock("../../components/agents/api", () => ({
  fetchProviderModels: fetchProviderModelsMock,
  updateProvider: updateProviderMock,
}));

import ModelPicker from "../../components/agents/ModelPicker";
import type { Provider, ProviderModel } from "../../components/agents/api";
import { ApiError } from "../../lib/api/client";

const openrouter: Provider = {
  id: "openrouter",
  name: "OpenRouter",
  auth: "API Key",
  status: "connected",
  model: "",
  detail: "Connected",
  models: [],
  icon: "fa-route",
  color: "#6467F2",
  source: "database",
};

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

afterEach(() => {
  cleanup();
  fetchProviderModelsMock.mockReset();
  updateProviderMock.mockReset();
});

describe("ModelPicker", () => {
  it("renders nothing (and fetches nothing) when there is no provider", () => {
    const { container } = render(<ModelPicker provider={null} />);
    expect(container.firstChild).toBeNull();
    expect(fetchProviderModelsMock).not.toHaveBeenCalled();
  });

  it("shows a loading spinner while the catalog is in flight", async () => {
    let resolve!: (v: ProviderModel[]) => void;
    fetchProviderModelsMock.mockReturnValue(
      new Promise<ProviderModel[]>((r) => {
        resolve = r;
      }),
    );

    render(<ModelPicker provider={openrouter} />);
    expect(screen.getByTestId("model-picker-loading")).toBeTruthy();

    resolve(MODELS);
    await waitFor(() => expect(screen.queryByTestId("model-picker-loading")).toBeNull());
    expect(screen.getByTestId("model-list")).toBeTruthy();
  });

  it("renders the fetched catalog grouped by budget tier with $/M prices", async () => {
    fetchProviderModelsMock.mockResolvedValue(MODELS);
    render(<ModelPicker provider={openrouter} />);

    await waitFor(() => expect(screen.getByTestId("model-list")).toBeTruthy());
    expect(fetchProviderModelsMock).toHaveBeenCalledWith("openrouter");
    // Tier groups render in cheapest-first order.
    expect(screen.getByTestId("model-group-free")).toBeTruthy();
    expect(screen.getByTestId("model-group-budget")).toBeTruthy();
    expect(screen.getByTestId("model-group-premium")).toBeTruthy();
    // Per-model pricing is visible.
    expect(screen.getByText("$3.00/M in · $15.00/M out")).toBeTruthy();
    expect(screen.getByText("$15.00/M in · $75.00/M out")).toBeTruthy();
  });

  it("selecting a model persists it via updateProvider(id, {model}) and refreshes", async () => {
    fetchProviderModelsMock.mockResolvedValue(MODELS);
    updateProviderMock.mockResolvedValue({ ...openrouter, model: "anthropic/claude-sonnet" });
    const onSaved = vi.fn();

    render(<ModelPicker provider={openrouter} onSaved={onSaved} />);
    await waitFor(() => screen.getByTestId("model-option-anthropic/claude-sonnet"));

    fireEvent.click(screen.getByTestId("model-option-anthropic/claude-sonnet"));

    await waitFor(() =>
      expect(updateProviderMock).toHaveBeenCalledWith("openrouter", {
        model: "anthropic/claude-sonnet",
      }),
    );
    expect(onSaved).toHaveBeenCalled();
  });

  it("Premium preset persists a frontier id DERIVED from the catalog", async () => {
    fetchProviderModelsMock.mockResolvedValue(MODELS);
    updateProviderMock.mockResolvedValue({ ...openrouter });

    render(<ModelPicker provider={openrouter} />);
    await waitFor(() => screen.getByTestId("model-preset-premium"));

    fireEvent.click(screen.getByTestId("model-preset-premium"));

    await waitFor(() =>
      expect(updateProviderMock).toHaveBeenCalledWith("openrouter", {
        model: "anthropic/claude-opus",
      }),
    );
  });

  it("Economy preset persists the cheapest reasoning-capable id", async () => {
    fetchProviderModelsMock.mockResolvedValue(MODELS);
    updateProviderMock.mockResolvedValue({ ...openrouter });

    render(<ModelPicker provider={openrouter} />);
    await waitFor(() => screen.getByTestId("model-preset-economy"));

    fireEvent.click(screen.getByTestId("model-preset-economy"));

    await waitFor(() =>
      expect(updateProviderMock).toHaveBeenCalledWith("openrouter", { model: "free/reasoner" }),
    );
  });

  it("Balanced preset clears the override (updateProvider with {model: ''})", async () => {
    fetchProviderModelsMock.mockResolvedValue(MODELS);
    updateProviderMock.mockResolvedValue({ ...openrouter });

    render(<ModelPicker provider={openrouter} />);
    await waitFor(() => screen.getByTestId("model-preset-balanced"));

    fireEvent.click(screen.getByTestId("model-preset-balanced"));

    await waitFor(() =>
      expect(updateProviderMock).toHaveBeenCalledWith("openrouter", { model: "" }),
    );
  });

  it("no-key 400: shows the honest backend detail, never crashes, never fabricates a list", async () => {
    fetchProviderModelsMock.mockRejectedValue(new ApiError(NO_KEY_DETAIL, 400));
    const onNotice = vi.fn();

    render(<ModelPicker provider={openrouter} onNotice={onNotice} />);

    const err = await screen.findByTestId("model-picker-error");
    expect(err.textContent).toContain("Add an OpenRouter API key");
    expect(screen.queryByTestId("model-list")).toBeNull();
    expect(updateProviderMock).not.toHaveBeenCalled();
  });

  it("search filters the catalog by name/id", async () => {
    fetchProviderModelsMock.mockResolvedValue(MODELS);
    render(<ModelPicker provider={openrouter} />);
    await waitFor(() => screen.getByTestId("model-list"));

    fireEvent.change(screen.getByTestId("model-search"), { target: { value: "grok" } });

    await waitFor(() => expect(screen.getByTestId("model-option-x-ai/grok-heavy")).toBeTruthy());
    expect(screen.queryByTestId("model-option-free/reasoner")).toBeNull();
    expect(screen.queryByTestId("model-option-anthropic/claude-opus")).toBeNull();
  });
});
