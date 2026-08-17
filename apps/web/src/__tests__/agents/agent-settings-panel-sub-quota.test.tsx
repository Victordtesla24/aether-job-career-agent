// @vitest-environment jsdom
/**
 * MODEL-SUB-QUOTA clause 3 + clause 5, round 3 — AgentSettingsPanel.
 *
 * OWNER DIRECTIVE 2026-08-17: "I want all the claude requests to use my
 * Anthropic Pro Subscription quota instead of consuming extra credits via an
 * API_KEY including for openrouter."
 *
 * The round-2 fix moved the routing seam, the OpenRouter guard, the credential
 * pin and the MODEL PICKER onto that rule — but `AgentSettingsPanel` (the
 * per-agent drawer rendered from AgentConfigGrid) kept a SECOND, private copy
 * of the provider rule and a THIRD idea of what "subscription" means. Three
 * consequences, all user-visible, all false under the enforced routing:
 *
 *  1. `providerForModel` was `startsWith("claude")`, so the namespaced spelling
 *     `anthropic/claude-*` resolved "openrouter". The drawer then labelled the
 *     agent's billing credential OpenRouter's, offered OpenRouter credentials
 *     for a Claude agent, and SAVED `provider: "openrouter"` onto the config
 *     row — a persisted claim that a Claude run bills OpenRouter, which
 *     `conductor.ts` prefers over the derived value when it labels the run.
 *  2. Only the LEGACY `subscription_oauth` mode was recognised as the
 *     subscription. The mode the operator's real subscription credential uses
 *     is `oauth_token` (`CLAUDE_AUTH_MODES`), so selecting the actual
 *     subscription displayed "Bills to: Metered API credits" — the exact
 *     opposite of the truth, and of the directive.
 *  3. An Anthropic **api_key** credential was offered as a billable choice for
 *     a Claude agent even though the API now refuses to serve Claude on one
 *     (clause 3): the drawer invited a selection that can never fund the run,
 *     and then described that run as metered.
 *
 * These pin the corrected behaviour against the REAL component.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchAgentConfigMock = vi.fn();
const listUserCredentialsMock = vi.fn();
const updateAgentConfigMock = vi.fn();

vi.mock("../../components/agents/api", () => ({
  fetchAgentConfig: (...args: unknown[]) => fetchAgentConfigMock(...args),
  listUserCredentials: (...args: unknown[]) => listUserCredentialsMock(...args),
  updateAgentConfig: (...args: unknown[]) => updateAgentConfigMock(...args),
}));

// eslint-disable-next-line import/first
import AgentSettingsPanel from "../../components/agents/AgentSettingsPanel";
// eslint-disable-next-line import/first
import type { CatalogAgent, UserCredential } from "../../components/agents/api";

const AGENT_KEY = "coverLetter";

function agent(model: string): CatalogAgent {
  return {
    key: AGENT_KEY,
    name: "Cover Letter",
    icon: "fa-pen",
    accent: "#fff",
    model,
    recommended: model,
    tip: "",
    runnable: true,
    backend: "llm",
    enabled: true,
    status: "active",
    modelOverridable: true,
    last_run: null,
  };
}

/** The operator's REAL subscription credential shape: authMode `oauth_token`. */
const SUBSCRIPTION_CRED: UserCredential = {
  id: "cred-sub",
  provider: "anthropic",
  authMode: "oauth_token",
  secretHint: "…oat01",
};

/** A metered Anthropic API key — never eligible to serve a Claude run. */
const ANTHROPIC_API_KEY_CRED: UserCredential = {
  id: "cred-anth-key",
  provider: "anthropic",
  authMode: "api_key",
  secretHint: "…ant1",
};

const OPENROUTER_CRED: UserCredential = {
  id: "cred-or",
  provider: "openrouter",
  authMode: "api_key",
  secretHint: "…or99",
};

function config(overrides: Record<string, unknown> = {}) {
  return {
    key: AGENT_KEY,
    enabled: true,
    model: "claude-opus-4-8",
    provider: "anthropic",
    authMode: null,
    credentialRef: null,
    temperature: 0.7,
    thinkingEffort: "medium",
    ...overrides,
  };
}

async function renderPanel(model: string, creds: UserCredential[]) {
  fetchAgentConfigMock.mockResolvedValue(config({ model }));
  listUserCredentialsMock.mockResolvedValue(creds);
  updateAgentConfigMock.mockResolvedValue(config({ model }));
  const utils = render(<AgentSettingsPanel agent={agent(model)} />);
  await waitFor(() =>
    expect(screen.queryByTestId(`agent-settings-${AGENT_KEY}`)).not.toBeNull(),
  );
  return utils;
}

const credentialSelect = () =>
  screen.getByTestId(`agent-credential-${AGENT_KEY}`) as HTMLSelectElement;
const billingPath = () =>
  screen.getByTestId(`agent-billing-path-${AGENT_KEY}`).textContent ?? "";
const optionLabels = () =>
  Array.from(credentialSelect().options).map((o) => o.textContent ?? "");

beforeEach(() => {
  fetchAgentConfigMock.mockReset();
  listUserCredentialsMock.mockReset();
  updateAgentConfigMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("AgentSettingsPanel — a Claude agent is an Anthropic-subscription agent", () => {
  it.each(["claude-opus-4-8", "anthropic/claude-opus-4-8", "Anthropic/Claude-Opus-4-8"])(
    "treats %s as Anthropic, not OpenRouter",
    async (model) => {
      await renderPanel(model, [SUBSCRIPTION_CRED, OPENROUTER_CRED]);

      // The credential label names the provider that will actually serve it.
      expect(screen.getByText(/Billing credential \(anthropic\)/i)).toBeTruthy();
      // ...and the OpenRouter credential is NOT offered for a Claude agent.
      expect(optionLabels().join(" ")).not.toMatch(/or99/);
    },
  );

  it("saves provider 'anthropic' for a namespaced Claude pin, never 'openrouter'", async () => {
    await renderPanel("anthropic/claude-opus-4-8", [SUBSCRIPTION_CRED]);

    fireEvent.click(screen.getByTestId(`agent-settings-save-${AGENT_KEY}`));

    await waitFor(() => expect(updateAgentConfigMock).toHaveBeenCalled());
    const [, patch] = updateAgentConfigMock.mock.calls[0] as [string, { provider: string }];
    expect(patch.provider).toBe("anthropic");
  });
});

describe("AgentSettingsPanel — the subscription is disclosed as the subscription", () => {
  it("labels an oauth_token credential 'Subscription' and bills it to the quota", async () => {
    await renderPanel("claude-opus-4-8", [SUBSCRIPTION_CRED]);

    expect(optionLabels().some((l) => /Subscription/i.test(l))).toBe(true);
    expect(optionLabels().some((l) => /API key/i.test(l))).toBe(false);

    fireEvent.change(credentialSelect(), { target: { value: SUBSCRIPTION_CRED.id } });
    expect(billingPath()).toMatch(/Subscription quota/i);
    expect(billingPath()).not.toMatch(/Metered/i);
  });

  it("never offers a metered Anthropic API key as a Claude agent's billing credential", async () => {
    // Clause 3: the API refuses to serve Claude on an api_key credential, so
    // offering it here would invite a pin that can never fund the run.
    await renderPanel("claude-opus-4-8", [SUBSCRIPTION_CRED, ANTHROPIC_API_KEY_CRED]);

    const values = Array.from(credentialSelect().options).map((o) => o.value);
    expect(values).toContain(SUBSCRIPTION_CRED.id);
    expect(values).not.toContain(ANTHROPIC_API_KEY_CRED.id);
  });

  it("explains honestly when the only Anthropic credential is a metered key", async () => {
    await renderPanel("claude-opus-4-8", [ANTHROPIC_API_KEY_CRED]);

    // No selectable credential, and the copy must not claim metered billing for
    // a run the subscription (or nothing at all) will serve.
    const values = Array.from(credentialSelect().options).map((o) => o.value);
    expect(values).not.toContain(ANTHROPIC_API_KEY_CRED.id);
    expect(billingPath()).not.toMatch(/Metered API credits/i);
    expect(billingPath()).toMatch(/subscription/i);
  });
});

describe("AgentSettingsPanel — non-Claude agents are untouched", () => {
  it("keeps an OpenRouter model on OpenRouter credentials and metered copy", async () => {
    await renderPanel("deepseek/deepseek-chat", [OPENROUTER_CRED, SUBSCRIPTION_CRED]);

    expect(screen.getByText(/Billing credential \(openrouter\)/i)).toBeTruthy();
    const values = Array.from(credentialSelect().options).map((o) => o.value);
    expect(values).toContain(OPENROUTER_CRED.id);
    expect(values).not.toContain(SUBSCRIPTION_CRED.id);

    fireEvent.change(credentialSelect(), { target: { value: OPENROUTER_CRED.id } });
    expect(billingPath()).toMatch(/Metered API credits/i);

    fireEvent.click(screen.getByTestId(`agent-settings-save-${AGENT_KEY}`));
    await waitFor(() => expect(updateAgentConfigMock).toHaveBeenCalled());
    const [, patch] = updateAgentConfigMock.mock.calls[0] as [string, { provider: string }];
    expect(patch.provider).toBe("openrouter");
  });
});
