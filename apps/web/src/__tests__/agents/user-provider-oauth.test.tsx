// @vitest-environment jsdom
/**
 * UPO-1 — per-user "Connect with Anthropic" subscription-token mint, frontend.
 *
 * Companion to ``apps/api/tests/test_user_anthropic_oauth_mint.py``.
 *
 * The deployment-wide flow (ML-agents-cred-002) is admin-only, so
 * ``ProviderConfigModal`` deliberately hides its Connect control from a
 * customer — otherwise it could only ever 403. The consequence was that a
 * customer opening Add Provider -> Anthropic saw an empty "Claude Code OAuth
 * Token" box and a placeholder, with no in-app way to obtain that token: they
 * had to leave, install the Claude CLI, run ``claude setup-token``, and paste
 * the result back.
 *
 * This suite pins the per-user affordance that closes that gap:
 *
 *  1. A customer sees a "Click here for subscription token" control.
 *  2. It drives the PER-USER endpoints, never the admin ones.
 *  3. On success the minted token is written INTO the OAuth-token field and
 *     the auth mode flips to ``oauth_token``, so the customer only has to
 *     press Save.
 *  4. Save stores it through the existing per-user credential write path.
 *  5. The primary button is labelled exactly "Save".
 *
 * Scope-distinct test ids (``anthropic-oauth-user-*`` vs the deployment
 * ``anthropic-oauth-*``) keep the F-01 guard in
 * ``f01-provider-panel-scope.test.tsx`` structurally meaningful: a customer
 * must still never be shown the deployment-wide control.
 *
 * This project does not install @testing-library/jest-dom, so assertions use
 * plain DOM properties / vitest matchers only (matches sibling test files).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const putUserCredentialMock = vi.fn();
const deleteUserCredentialMock = vi.fn();
const verifyUserMock = vi.fn();
const putCredentialMock = vi.fn();
const deleteCredentialMock = vi.fn();
const verifyMock = vi.fn();
const startAnthropicOAuthMock = vi.fn();
const exchangeAnthropicOAuthMock = vi.fn();
const refreshAnthropicOAuthMock = vi.fn();
const startUserAnthropicOAuthMock = vi.fn();
const exchangeUserAnthropicOAuthMock = vi.fn();

vi.mock("../../components/agents/api", () => ({
  putProviderCredential: (...a: unknown[]) => putCredentialMock(...a),
  deleteProviderCredential: (...a: unknown[]) => deleteCredentialMock(...a),
  verifyProvider: (...a: unknown[]) => verifyMock(...a),
  putUserProviderCredential: (...a: unknown[]) => putUserCredentialMock(...a),
  deleteUserProviderCredential: (...a: unknown[]) => deleteUserCredentialMock(...a),
  verifyUserProvider: (...a: unknown[]) => verifyUserMock(...a),
  startAnthropicOAuth: (...a: unknown[]) => startAnthropicOAuthMock(...a),
  exchangeAnthropicOAuth: (...a: unknown[]) => exchangeAnthropicOAuthMock(...a),
  refreshAnthropicOAuth: (...a: unknown[]) => refreshAnthropicOAuthMock(...a),
  // Not exported by api.ts today (UPO-1 fail-before) — supplied by the mock
  // factory regardless, so this file's fail-before signal is the MISSING UI
  // control, not a module-resolution error.
  startUserAnthropicOAuth: (...a: unknown[]) => startUserAnthropicOAuthMock(...a),
  exchangeUserAnthropicOAuth: (...a: unknown[]) => exchangeUserAnthropicOAuthMock(...a),
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

const openrouter: Provider = {
  ...anthropic,
  id: "openrouter",
  name: "OpenRouter",
  icon: "fa-route",
  color: "#6467F2",
};

/** A token shaped like the real ``claude setup-token`` output. Never a secret. */
const MINTED = "sk-ant-oat01-FAKEmintedFROMoauth00000000000deadbeef";

function renderUserScope(provider: Provider = anthropic, onNotice = vi.fn()) {
  return render(
    <ProviderConfigModal
      provider={provider}
      onClose={vi.fn()}
      onSaved={vi.fn()}
      onNotice={onNotice}
      scope="user"
    />,
  );
}

/** Drive the whole mint: click the control, paste the code, submit. */
async function completeMint(code = "FAKEONETIMECODE#FAKESTATE") {
  fireEvent.click(screen.getByTestId("anthropic-oauth-user-connect"));
  await waitFor(() =>
    expect(screen.getByTestId("anthropic-oauth-user-code-input")).toBeTruthy(),
  );
  fireEvent.change(screen.getByTestId("anthropic-oauth-user-code-input"), {
    target: { value: code },
  });
  fireEvent.click(screen.getByTestId("anthropic-oauth-user-complete"));
}

beforeEach(() => {
  startUserAnthropicOAuthMock.mockResolvedValue({
    authorizeUrl: "https://claude.com/cai/oauth/authorize?state=FAKESTATE",
  });
  exchangeUserAnthropicOAuthMock.mockResolvedValue({
    token: MINTED,
    authMode: "oauth_token",
    secretHint: "…beef",
    expiresAt: "2027-08-18T00:00:00Z",
    scope: "user:inference",
  });
  vi.spyOn(window, "open").mockReturnValue(null);
});

afterEach(() => {
  cleanup();
  [
    putUserCredentialMock, deleteUserCredentialMock, verifyUserMock,
    putCredentialMock, deleteCredentialMock, verifyMock,
    startAnthropicOAuthMock, exchangeAnthropicOAuthMock, refreshAnthropicOAuthMock,
    startUserAnthropicOAuthMock, exchangeUserAnthropicOAuthMock,
  ].forEach((m) => m.mockReset());
  vi.restoreAllMocks();
});

describe("ProviderConfigModal — per-user subscription-token mint (UPO-1)", () => {
  it("offers a customer a 'click here for subscription token' control", () => {
    renderUserScope();
    // FAIL-BEFORE (WHY): in user scope the modal renders only the manual paste
    // field today — the whole OAuth panel is gated behind `!userScope`.
    const control = screen.getByTestId("anthropic-oauth-user-connect");
    expect(control).toBeTruthy();
    expect(control.textContent ?? "").toMatch(/click here for subscription token/i);
  });

  it("never shows the customer the DEPLOYMENT-WIDE control (F-01)", () => {
    renderUserScope();
    // The admin control can only 403 for a customer, so it must stay hidden;
    // the per-user control above is its replacement, not an addition.
    expect(screen.queryByTestId("anthropic-oauth-connect")).toBeNull();
    expect(screen.queryByTestId("anthropic-oauth-reconnect")).toBeNull();
  });

  it("offers the control for Anthropic only — no other provider mints tokens", () => {
    renderUserScope(openrouter);
    expect(screen.queryByTestId("anthropic-oauth-user-connect")).toBeNull();
  });

  it("opens Anthropic's own sign-in page via the PER-USER start endpoint", async () => {
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    renderUserScope();

    fireEvent.click(screen.getByTestId("anthropic-oauth-user-connect"));

    await waitFor(() => expect(startUserAnthropicOAuthMock).toHaveBeenCalledTimes(1));
    expect(openSpy).toHaveBeenCalledWith(
      "https://claude.com/cai/oauth/authorize?state=FAKESTATE",
      "_blank",
      "noopener",
    );
    // Cross-wiring to the admin route would 403 for every customer.
    expect(startAnthropicOAuthMock).not.toHaveBeenCalled();
  });

  it("populates the OAuth-token field with the minted token and selects oauth_token", async () => {
    renderUserScope();
    await completeMint();

    await waitFor(() =>
      expect(exchangeUserAnthropicOAuthMock).toHaveBeenCalledWith("FAKEONETIMECODE#FAKESTATE"),
    );
    // THE requirement: the customer never types the token themselves.
    await waitFor(() => {
      const secret = screen.getByTestId("provider-secret-input") as HTMLInputElement;
      expect(secret.value).toBe(MINTED);
    });
    const oauthRadio = screen.getByTestId("authmode-oauth_token") as HTMLInputElement;
    expect(oauthRadio.checked).toBe(true);
    expect(exchangeAnthropicOAuthMock).not.toHaveBeenCalled();
  });

  it("clears the one-time code and closes the paste step once redeemed", async () => {
    renderUserScope();
    await completeMint();

    await waitFor(() =>
      expect(screen.queryByTestId("anthropic-oauth-user-code-input")).toBeNull(),
    );
  });

  it("saves the minted token through the PER-USER credential write path", async () => {
    putUserCredentialMock.mockResolvedValue({
      id: "cred-1",
      provider: "anthropic",
      authMode: "oauth_token",
      secretHint: "…beef",
      lastVerifyStatus: "ok",
    });
    renderUserScope();
    await completeMint();
    await waitFor(() => {
      const secret = screen.getByTestId("provider-secret-input") as HTMLInputElement;
      expect(secret.value).toBe(MINTED);
    });

    fireEvent.click(screen.getByTestId("provider-config-save"));

    await waitFor(() =>
      expect(putUserCredentialMock).toHaveBeenCalledWith("anthropic", {
        authMode: "oauth_token",
        secret: MINTED,
      }),
    );
    // Save must never reach the operator's shared store.
    expect(putCredentialMock).not.toHaveBeenCalled();
  });

  it("tells the customer the token is ready and still needs saving", async () => {
    const onNotice = vi.fn();
    renderUserScope(anthropic, onNotice);
    await completeMint();

    await waitFor(() => {
      const texts = onNotice.mock.calls.map((c) => String((c[0] as { text: string }).text));
      expect(texts.some((t) => /save/i.test(t))).toBe(true);
    });
    // The token itself is never echoed into a user-facing notice.
    const allText = onNotice.mock.calls
      .map((c) => String((c[0] as { text: string }).text))
      .join(" ");
    expect(allText).not.toContain(MINTED);
  });

  it("surfaces an honest failure and leaves the field empty", async () => {
    exchangeUserAnthropicOAuthMock.mockRejectedValue(
      new Error("Anthropic rejected the authorization code — restart Connect with Anthropic."),
    );
    const onNotice = vi.fn();
    renderUserScope(anthropic, onNotice);
    await completeMint("STALE#FAKESTATE");

    await waitFor(() => expect(screen.getByTestId("provider-config-error")).toBeTruthy());
    // No fabricated success: nothing is placed in the field, nothing is saved.
    const secret = screen.getByTestId("provider-secret-input") as HTMLInputElement;
    expect(secret.value).toBe("");
    expect(putUserCredentialMock).not.toHaveBeenCalled();
  });

  it("keeps the manual paste available as an honest fallback", () => {
    renderUserScope();
    expect(screen.getByTestId("provider-secret-input")).toBeTruthy();
    expect(screen.getByTestId("authmode-api_key")).toBeTruthy();
    expect(screen.getByTestId("authmode-oauth_token")).toBeTruthy();
  });
});

describe("ProviderConfigModal — primary button label", () => {
  it("reads exactly 'Save' in the per-user scope", () => {
    renderUserScope();
    const save = screen.getByTestId("provider-config-save");
    expect((save.textContent ?? "").trim()).toBe("Save");
  });

  it("reads exactly 'Save' in the deployment scope too", () => {
    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    const save = screen.getByTestId("provider-config-save");
    expect((save.textContent ?? "").trim()).toBe("Save");
  });
});
