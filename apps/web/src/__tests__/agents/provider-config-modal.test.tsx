// @vitest-environment jsdom
/**
 * REQ-PC-1 / REQ-PC-2 / REQ-PC-3 — ProviderConfigModal component test.
 *
 * Proves the in-app provider-config flow that replaces the old "edit the
 * server .env" UX:
 *  - Anthropic exposes BOTH auth modes (subscription token vs API key).
 *  - Entering a secret + Save calls PUT /agents/providers/{id}/credential
 *    (via the api module) with the selected authMode + secret, and the
 *    backend-returned masked row drives the on-screen status/source badge —
 *    the UI never fabricates "connected".
 *  - "Test connection" calls the verify endpoint and surfaces the honest
 *    result through the onNotice banner callback.
 *  - OpenRouter is a single api_key mode and its billing note names
 *    OpenRouter credits (billing separation is legible in the copy).
 *
 * This project does not install @testing-library/jest-dom, so assertions use
 * plain DOM properties / vitest matchers only.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const putCredentialMock = vi.fn();
const deleteCredentialMock = vi.fn();
const verifyMock = vi.fn();

vi.mock("../../components/agents/api", () => ({
  putProviderCredential: (...args: unknown[]) => putCredentialMock(...args),
  deleteProviderCredential: (...args: unknown[]) => deleteCredentialMock(...args),
  verifyProvider: (...args: unknown[]) => verifyMock(...args),
}));

// eslint-disable-next-line import/first
import ProviderConfigModal from "../../components/agents/ProviderConfigModal";
// eslint-disable-next-line import/first
import type { Provider } from "../../components/agents/api";
// eslint-disable-next-line import/first
import { ApiError } from "../../lib/api/client";

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
  id: "openrouter",
  name: "OpenRouter",
  auth: "API Key",
  status: "unconfigured",
  model: "",
  detail: "Not configured",
  models: [],
  icon: "fa-route",
  color: "#6467F2",
  source: "none",
};

afterEach(() => {
  cleanup();
  putCredentialMock.mockReset();
  deleteCredentialMock.mockReset();
  verifyMock.mockReset();
});

describe("ProviderConfigModal", () => {
  it("does not render when no provider is selected (closed)", () => {
    render(
      <ProviderConfigModal provider={null} onClose={vi.fn()} onSaved={vi.fn()} onNotice={vi.fn()} />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Anthropic offers API key only — no subscription OAuth (GAP-AUTH-001)", () => {
    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    // Consumer subscription OAuth is removed: no subscription radio, no connect
    // button, and the API-key input is the sole credential entry.
    expect(screen.queryByRole("radio", { name: /claude subscription/i })).toBeNull();
    expect(screen.queryByTestId("authmode-subscription_oauth")).toBeNull();
    expect(screen.queryByTestId("anthropic-oauth-connect")).toBeNull();
    expect(screen.getByTestId("provider-secret-input")).toBeTruthy();
    // Billing implication must be legible: Anthropic bills to Anthropic, and
    // the crossover to OpenRouter for other models is stated.
    expect(screen.getByTestId("provider-config-billing").textContent).toMatch(/anthropic/i);
  });

  it("masks the secret input (password type)", () => {
    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    const input = screen.getByTestId("provider-secret-input") as HTMLInputElement;
    expect(input.type).toBe("password");
  });

  it("Save calls PUT credential with the selected authMode + secret and reflects the backend-returned state", async () => {
    putCredentialMock.mockResolvedValue({
      ...anthropic,
      status: "connected",
      source: "database",
      authMode: "api_key",
      secretHint: "…pi42",
      detail: "API key · billed to Anthropic API credits",
    });
    const onSaved = vi.fn().mockResolvedValue(undefined);
    const onNotice = vi.fn();

    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={onSaved}
        onNotice={onNotice}
      />,
    );

    // API key is the only Anthropic mode now — just paste the key.
    fireEvent.change(screen.getByTestId("provider-secret-input"), {
      target: { value: "sk-ant-api-abc123" },
    });
    fireEvent.click(screen.getByTestId("provider-config-save"));

    await waitFor(() => expect(putCredentialMock).toHaveBeenCalledTimes(1));
    expect(putCredentialMock).toHaveBeenCalledWith("anthropic", {
      authMode: "api_key",
      secret: "sk-ant-api-abc123",
    });
    // Backend-returned masked row drives the UI: "Saved in app" + last-4 hint.
    await waitFor(() => expect(screen.getByText(/saved in app/i)).toBeTruthy());
    expect(screen.getByTestId("provider-config-hint").textContent).toContain("…pi42");
    expect(onSaved).toHaveBeenCalled();
    expect(onNotice).toHaveBeenCalledWith(expect.objectContaining({ kind: "success" }));
  });

  it("Save failure surfaces the REAL backend detail via onNotice, not the generic 'AI model is busy' toast (QA finding)", async () => {
    putCredentialMock.mockRejectedValue(
      new ApiError(
        'PUT /agents/providers/anthropic/credential failed (503): {"detail":"Credential encryption unavailable: AETHER_CREDENTIAL_KEY is not configured on the server."}',
        503,
      ),
    );
    const onNotice = vi.fn();

    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={onNotice}
      />,
    );

    fireEvent.change(screen.getByTestId("provider-secret-input"), {
      target: { value: "sk-ant-api-abc123" },
    });
    fireEvent.click(screen.getByTestId("provider-config-save"));

    await waitFor(() => expect(putCredentialMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith(expect.objectContaining({ kind: "error" })));

    const errorNotice = onNotice.mock.calls.map((c) => c[0]).find((n) => n.kind === "error");
    expect(errorNotice.text).toContain("Credential encryption unavailable");
    expect(errorNotice.text).not.toMatch(/AI model is busy/i);
    expect(errorNotice.text).not.toMatch(/time budget was exceeded/i);
  });

  it("Save failure with a 422 validation detail surfaces that detail honestly, not the generic scout-first guidance", async () => {
    putCredentialMock.mockRejectedValue(
      new ApiError(
        'PUT /agents/providers/anthropic/credential failed (422): {"detail":"Anthropic api_key must start with \'sk-ant-api\'."}',
        422,
      ),
    );
    const onNotice = vi.fn();

    render(
      <ProviderConfigModal
        provider={anthropic}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={onNotice}
      />,
    );

    fireEvent.change(screen.getByTestId("provider-secret-input"), {
      target: { value: "not-a-valid-key" },
    });
    fireEvent.click(screen.getByTestId("provider-config-save"));

    await waitFor(() => expect(putCredentialMock).toHaveBeenCalledTimes(1));
    const errorNotice = await waitFor(() => {
      const found = onNotice.mock.calls.map((c) => c[0]).find((n) => n.kind === "error");
      expect(found).toBeTruthy();
      return found;
    });
    expect(errorNotice.text).toContain("Anthropic api_key must start with 'sk-ant-api'");
    expect(errorNotice.text).not.toMatch(/run Scout to discover jobs/i);
  });

  it("Verify transport failure surfaces the real backend detail via onNotice, not the generic 503 copy", async () => {
    verifyMock.mockRejectedValue(
      new ApiError(
        'POST /agents/providers/anthropic/verify failed (503): {"detail":"Credential encryption unavailable: AETHER_CREDENTIAL_KEY is not configured on the server."}',
        503,
      ),
    );
    const onNotice = vi.fn();

    render(
      <ProviderConfigModal
        provider={{ ...anthropic, status: "connected", source: "database", secretHint: "…pi42" }}
        onClose={vi.fn()}
        onSaved={vi.fn().mockResolvedValue(undefined)}
        onNotice={onNotice}
      />,
    );

    fireEvent.click(screen.getByTestId("provider-config-verify"));

    await waitFor(() => expect(verifyMock).toHaveBeenCalledWith("anthropic"));
    const errorNotice = await waitFor(() => {
      const found = onNotice.mock.calls.map((c) => c[0]).find((n) => n.kind === "error");
      expect(found).toBeTruthy();
      return found;
    });
    expect(errorNotice.text).toContain("Credential encryption unavailable");
    expect(errorNotice.text).not.toMatch(/AI model is busy/i);
  });

  it("Test connection calls verify and surfaces the honest result via onNotice", async () => {
    verifyMock.mockResolvedValue({
      ok: true,
      status: "connected",
      detail: "Anthropic reachable · HTTP 200",
    });
    const onNotice = vi.fn();

    render(
      <ProviderConfigModal
        provider={{ ...anthropic, status: "connected", source: "database", secretHint: "…pi42" }}
        onClose={vi.fn()}
        onSaved={vi.fn().mockResolvedValue(undefined)}
        onNotice={onNotice}
      />,
    );

    fireEvent.click(screen.getByTestId("provider-config-verify"));

    await waitFor(() => expect(verifyMock).toHaveBeenCalledWith("anthropic"));
    await waitFor(() =>
      expect(onNotice).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "success", text: expect.stringMatching(/HTTP 200/) }),
      ),
    );
  });

  it("surfaces a failed verify honestly (kind error), never a fake success", async () => {
    verifyMock.mockResolvedValue({
      ok: false,
      status: "error",
      detail: "401 unauthorized — key rejected",
    });
    const onNotice = vi.fn();

    render(
      <ProviderConfigModal
        provider={{ ...anthropic, status: "connected", source: "database", secretHint: "…pi42" }}
        onClose={vi.fn()}
        onSaved={vi.fn().mockResolvedValue(undefined)}
        onNotice={onNotice}
      />,
    );

    fireEvent.click(screen.getByTestId("provider-config-verify"));

    await waitFor(() =>
      expect(onNotice).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", text: expect.stringMatching(/rejected/) }),
      ),
    );
  });

  it("OpenRouter is a single api_key mode whose billing note names OpenRouter credits", () => {
    render(
      <ProviderConfigModal
        provider={openrouter}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    // No subscription auth-mode toggle for OpenRouter.
    expect(screen.queryByTestId("authmode-subscription_oauth")).toBeNull();
    expect(screen.getByTestId("provider-config-billing").textContent).toMatch(/openrouter credits/i);
  });

  it("Save on OpenRouter sends authMode api_key", async () => {
    putCredentialMock.mockResolvedValue({
      ...openrouter,
      status: "connected",
      source: "database",
      authMode: "api_key",
      secretHint: "…r7Kp",
    });
    render(
      <ProviderConfigModal
        provider={openrouter}
        onClose={vi.fn()}
        onSaved={vi.fn().mockResolvedValue(undefined)}
        onNotice={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByTestId("provider-secret-input"), {
      target: { value: "sk-or-v1-xyz" },
    });
    fireEvent.click(screen.getByTestId("provider-config-save"));
    await waitFor(() =>
      expect(putCredentialMock).toHaveBeenCalledWith("openrouter", {
        authMode: "api_key",
        secret: "sk-or-v1-xyz",
      }),
    );
  });
});
