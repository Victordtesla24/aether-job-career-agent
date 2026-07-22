// @vitest-environment jsdom
/**
 * ML-agents-cred-002 (MODELS-LIVE, BLOCKER) — frontend half of the in-app
 * "Connect with Anthropic" (subscription) OAuth flow.
 *
 * Companion to ``apps/api/tests/test_ml_cred_002_anthropic_oauth.py``
 * (backend). Governing decisions: ADR-ML-1 (operator mandate — the Anthropic
 * configure-credentials window MUST open Anthropic's own auth web page for
 * subscription users) + ADR-ML-2/2a in
 * ``docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md`` + ``docs/delivery/
 * ML-agents-cred-002-BLUEPRINT.md`` §5.2.
 *
 * **Nothing under test exists in current code.** ``ProviderConfigModal.tsx``
 * has NO "Connect with Anthropic" affordance today — a sibling guard test in
 * ``provider-config-modal.test.tsx`` (cred-001, line ~97) explicitly asserts
 * ``queryByTestId("anthropic-oauth-connect")`` is ``null`` right now, which is
 * the CURRENT correct behaviour (ADR-P7-01/Gate-14 removed the old, non-
 * compliant in-app OAuth). ADR-ML-1 supersedes that removal for a NEW,
 * compliant, manual-redirect + code-paste-back flow — so that cred-001 guard
 * assertion is expected to need updating by the fixer alongside this file
 * turning green (see notes_for_fixer in the dispatch record).
 *
 * ``api.ts`` also has NO ``startAnthropicOAuth`` / ``exchangeAnthropicOAuth``
 * exports yet — mocked here per the module's OWN typed-call contract
 * (blueprint §5.1); the mock factory does not care whether the real exports
 * exist, so the fail-before signal is purely the MISSING UI element below,
 * not an import error (kept intentionally distinct from the backend suite's
 * ModuleNotFoundError/404 fail-before signals).
 *
 * data-testid convention pinned by the EXISTING cred-001 guard test's forward
 * reference (`anthropic-oauth-connect`) plus the blueprint's paste-step ids:
 *   - anthropic-oauth-connect      "Connect with Anthropic" button
 *   - anthropic-oauth-code-input   the paste-back "code#state" text field
 *   - anthropic-oauth-complete     "Finish connecting" / submit button
 *
 * This project does not install @testing-library/jest-dom, so assertions use
 * plain DOM properties / vitest matchers only (matches sibling test files).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const putCredentialMock = vi.fn();
const deleteCredentialMock = vi.fn();
const verifyMock = vi.fn();
const startAnthropicOAuthMock = vi.fn();
const exchangeAnthropicOAuthMock = vi.fn();

vi.mock("../../components/agents/api", () => ({
  putProviderCredential: (...args: unknown[]) => putCredentialMock(...args),
  deleteProviderCredential: (...args: unknown[]) => deleteCredentialMock(...args),
  verifyProvider: (...args: unknown[]) => verifyMock(...args),
  // Not exported by api.ts today (ML-agents-cred-002 fail-before) — the mock
  // factory supplies them regardless so THIS file's fail-before signal is
  // isolated to the missing UI control, not a module-resolution error.
  startAnthropicOAuth: (...args: unknown[]) => startAnthropicOAuthMock(...args),
  exchangeAnthropicOAuth: (...args: unknown[]) => exchangeAnthropicOAuthMock(...args),
}));

// eslint-disable-next-line import/first
import ProviderConfigModal from "../../components/agents/ProviderConfigModal";
// eslint-disable-next-line import/first
import type { Provider } from "../../components/agents/api";

const anthropic: Provider = {
  id: "anthropic",
  name: "Anthropic Claude",
  auth: "API Key",
  status: "unconfigured",
  model: "",
  detail: "Not configured",
  models: [],
  icon: "fa-a",
  color: "#D97757",
  source: "none",
};

afterEach(() => {
  cleanup();
  putCredentialMock.mockReset();
  deleteCredentialMock.mockReset();
  verifyMock.mockReset();
  startAnthropicOAuthMock.mockReset();
  exchangeAnthropicOAuthMock.mockReset();
  vi.restoreAllMocks();
});

describe("ProviderConfigModal — Connect with Anthropic (ML-agents-cred-002, ADR-ML-1)", () => {
  it("shows a 'Connect with Anthropic' action for the anthropic provider", () => {
    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    // FAIL-BEFORE (WHY): ProviderConfigModal renders only the two manual-paste
    // authmode radios today — no Connect button exists at all.
    const connectButton = screen.getByTestId("anthropic-oauth-connect");
    expect(connectButton).toBeTruthy();
    expect(connectButton.textContent ?? "").toMatch(/connect.*anthropic/i);
  });

  it("does NOT show a Connect action for a non-Anthropic provider (OpenRouter)", () => {
    const openrouter: Provider = {
      ...anthropic,
      id: "openrouter",
      name: "OpenRouter",
      icon: "fa-route",
      color: "#6467F2",
    };
    render(
      <ProviderConfigModal
        provider={openrouter}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("anthropic-oauth-connect")).toBeNull();
  });

  it("manual api_key / oauth_token paste modes remain available alongside Connect (ADR-ML-1 honest fallback)", () => {
    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.getByTestId("anthropic-oauth-connect")).toBeTruthy();
    // FAIL-BEFORE (WHY): these two already exist today, so on their own they
    // would pass before the fix too — this test only has fail-before value
    // in combination with the Connect-button assertion above (same `it`),
    // proving BOTH the new affordance and the preserved fallback coexist.
    expect(screen.getByTestId("authmode-api_key")).toBeTruthy();
    expect(screen.getByTestId("authmode-oauth_token")).toBeTruthy();
    expect(screen.getByTestId("provider-secret-input")).toBeTruthy();
  });

  it("clicking Connect calls startAnthropicOAuth and opens the returned authorizeUrl in a new tab", async () => {
    startAnthropicOAuthMock.mockResolvedValue({
      authorizeUrl:
        "https://claude.com/cai/oauth/authorize?client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e&response_type=code&scope=user%3Ainference&code_challenge=FAKE&code_challenge_method=S256&state=FAKESTATE",
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("anthropic-oauth-connect"));

    await waitFor(() => expect(startAnthropicOAuthMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(openSpy).toHaveBeenCalledWith(
        expect.stringContaining("claude.com/cai/oauth/authorize"),
        expect.anything(),
        expect.anything(),
      ),
    );

    // The paste-back code step must then be revealed.
    await waitFor(() => expect(screen.getByTestId("anthropic-oauth-code-input")).toBeTruthy());
  });

  it("pasting the code and completing calls exchangeAnthropicOAuth with the pasted value and reflects the connected state", async () => {
    startAnthropicOAuthMock.mockResolvedValue({
      authorizeUrl: "https://claude.com/cai/oauth/authorize?state=FAKESTATE",
    });
    exchangeAnthropicOAuthMock.mockResolvedValue({
      ...anthropic,
      status: "connected",
      source: "database",
      authMode: "oauth_token",
      secretHint: "…f00d",
      detail: "Subscription session active",
    });
    vi.spyOn(window, "open").mockImplementation(() => null);
    const onSaved = vi.fn().mockResolvedValue(undefined);

    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={onSaved}
        onNotice={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("anthropic-oauth-connect"));
    await waitFor(() => expect(screen.getByTestId("anthropic-oauth-code-input")).toBeTruthy());

    fireEvent.change(screen.getByTestId("anthropic-oauth-code-input"), {
      target: { value: "FAKEONETIMECODE#FAKESTATE" },
    });
    fireEvent.click(screen.getByTestId("anthropic-oauth-complete"));

    await waitFor(() => expect(exchangeAnthropicOAuthMock).toHaveBeenCalledTimes(1));
    expect(exchangeAnthropicOAuthMock).toHaveBeenCalledWith("FAKEONETIMECODE#FAKESTATE");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    // The raw pasted code must not remain visible in the DOM once submitted.
    expect(screen.queryByDisplayValue("FAKEONETIMECODE#FAKESTATE")).toBeNull();
  });
});
