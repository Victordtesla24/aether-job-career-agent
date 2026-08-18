// @vitest-environment jsdom
/**
 * GAP-PROVIDER-OAUTH-1 — per-user, provider-agnostic OAuth "Connect" (app-
 * hosted callback, auto-return, zero-paste primary path).
 *
 * TDD fail-before suite: before this slice, ProviderConfigModal renders no
 * `user-oauth-connect` control at all in the per-user scope — every "Connect
 * opens…"/"postMessage flips…" assertion below fails against the pre-slice
 * component with "Unable to find an element with the testid" (RTL's own
 * honest not-found error), and the key-only-provider guard trivially passes
 * before AND after (there is nothing to render either way) — a real
 * regression guard, not a fail-before assertion.
 *
 * Only the module boundary (`./api`) is mocked — never fetch/network
 * directly — mirroring the backend suite's "mock only the outbound provider
 * HTTP boundary" convention.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProviderConfigModal from "../ProviderConfigModal";
import type { Provider } from "../api";

const startUserProviderOAuth = vi.fn();
const exchangeUserProviderOAuth = vi.fn();
const listUserCredentials = vi.fn();
const verifyUserProvider = vi.fn();
const putUserProviderCredential = vi.fn();
const deleteUserProviderCredential = vi.fn();

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    startUserProviderOAuth: (...args: unknown[]) => startUserProviderOAuth(...args),
    exchangeUserProviderOAuth: (...args: unknown[]) => exchangeUserProviderOAuth(...args),
    listUserCredentials: (...args: unknown[]) => listUserCredentials(...args),
    verifyUserProvider: (...args: unknown[]) => verifyUserProvider(...args),
    putUserProviderCredential: (...args: unknown[]) => putUserProviderCredential(...args),
    deleteUserProviderCredential: (...args: unknown[]) => deleteUserProviderCredential(...args),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function provider(overrides: Partial<Provider> = {}): Provider {
  return {
    id: "anthropic",
    name: "Anthropic Claude",
    auth: "API Key",
    status: "unconfigured",
    model: "",
    detail: "You have not added your own Anthropic Claude key.",
    models: [],
    icon: "fa-a",
    color: "#D97757",
    source: "none",
    authMode: null,
    secretHint: null,
    lastVerifiedAt: null,
    lastVerifyStatus: null,
    needsReauth: null,
    ...overrides,
  };
}

const noop = () => {};
const asyncNoop = async () => {};

describe("GAP-PROVIDER-OAUTH-1 — user-scope Connect button", () => {
  it("shows a Connect button for an OAuth-capable provider in user scope", () => {
    render(
      <ProviderConfigModal
        provider={provider()}
        onClose={noop}
        onSaved={asyncNoop}
        onNotice={noop}
        scope="user"
      />,
    );
    expect(screen.getByTestId("user-oauth-connect")).toBeTruthy();
  });

  it("Connect opens a popup and navigates it to the real authorize URL (same tick, popup-blocker-safe)", async () => {
    const fakePopup = { location: { href: "" }, close: vi.fn(), closed: false };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(fakePopup as unknown as Window);
    startUserProviderOAuth.mockResolvedValue({
      authorizeUrl: "https://openrouter.ai/auth?callback_url=https%3A%2F%2Fapp.test%2Fcb%3Fstate%3Dxyz",
      flow: "app_callback",
      provider: "openrouter",
    });

    render(
      <ProviderConfigModal
        provider={provider({ id: "openrouter", name: "OpenRouter", color: "#6467F2", icon: "fa-route" })}
        onClose={noop}
        onSaved={asyncNoop}
        onNotice={noop}
        scope="user"
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId("user-oauth-connect"));
    });

    // The blank popup must be opened synchronously (before the async start()
    // call resolves) so a real browser's popup blocker sees a direct result
    // of the click — never a second window.open() call after the await.
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("", "aether-oauth-connect", expect.stringContaining("width"));
    expect(startUserProviderOAuth).toHaveBeenCalledWith("openrouter");

    await waitFor(() => {
      expect(fakePopup.location.href).toBe(
        "https://openrouter.ai/auth?callback_url=https%3A%2F%2Fapp.test%2Fcb%3Fstate%3Dxyz",
      );
    });
    // Zero-paste: no code-paste field is shown for the app_callback flow.
    expect(screen.queryByTestId("user-oauth-code-input")).toBeNull();
  });

  it("postMessage({connected:true}) flips the UI to Connected with zero paste", async () => {
    startUserProviderOAuth.mockResolvedValue({
      authorizeUrl: "https://openrouter.ai/auth?callback_url=https%3A%2F%2Fapp.test%2Fcb",
      flow: "app_callback",
      provider: "openrouter",
    });
    listUserCredentials.mockResolvedValue([
      {
        id: "cred-1",
        provider: "openrouter",
        authMode: "api_key",
        secretHint: "…9f2a",
        baseUrl: null,
        expiresAt: null,
        lastVerifiedAt: "2026-08-18T00:00:00Z",
        lastVerifyStatus: "ok",
      },
    ]);
    vi.spyOn(window, "open").mockReturnValue({
      location: { href: "" },
      close: vi.fn(),
      closed: false,
    } as unknown as Window);

    const onSaved = vi.fn(asyncNoop);
    const onNotice = vi.fn();

    render(
      <ProviderConfigModal
        provider={provider({ id: "openrouter", name: "OpenRouter", color: "#6467F2", icon: "fa-route" })}
        onClose={noop}
        onSaved={onSaved}
        onNotice={onNotice}
        scope="user"
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId("user-oauth-connect"));
    });
    await waitFor(() => expect(startUserProviderOAuth).toHaveBeenCalled());

    // Never a code paste — the popup callback page does the round-trip; the
    // opener only ever learns the honest {provider, connected} status.
    expect(screen.queryByTestId("user-oauth-code-input")).toBeNull();

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: { source: "aether-oauth", provider: "openrouter", connected: true },
        }),
      );
      // flush the listener's async listUserCredentials()/onSaved() chain
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByTestId("provider-config-hint").textContent).toContain("9f2a");
    });
    expect(onSaved).toHaveBeenCalled();
    expect(
      onNotice.mock.calls.some((call) => {
        const n = call[0] as { kind: string; text: string };
        return n.kind === "success" && /connected/i.test(n.text);
      }),
    ).toBe(true);
    // Still zero paste after connecting.
    expect(screen.queryByTestId("user-oauth-code-input")).toBeNull();
  });

  it("a postMessage for a DIFFERENT provider is ignored (origin/provider-scoped)", async () => {
    startUserProviderOAuth.mockResolvedValue({
      authorizeUrl: "https://openrouter.ai/auth?callback_url=https%3A%2F%2Fapp.test%2Fcb",
      flow: "app_callback",
      provider: "openrouter",
    });
    vi.spyOn(window, "open").mockReturnValue({
      location: { href: "" },
      close: vi.fn(),
      closed: false,
    } as unknown as Window);
    const onSaved = vi.fn(asyncNoop);

    render(
      <ProviderConfigModal
        provider={provider({ id: "openrouter", name: "OpenRouter", color: "#6467F2", icon: "fa-route" })}
        onClose={noop}
        onSaved={onSaved}
        onNotice={noop}
        scope="user"
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("user-oauth-connect"));
    });
    await waitFor(() => expect(startUserProviderOAuth).toHaveBeenCalled());

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: { source: "aether-oauth", provider: "anthropic", connected: true },
        }),
      );
      await Promise.resolve();
    });
    expect(onSaved).not.toHaveBeenCalled();
    expect(listUserCredentials).not.toHaveBeenCalled();
  });

  it("code_relay flow shows the paste-back field instead of claiming zero-paste", async () => {
    startUserProviderOAuth.mockResolvedValue({
      authorizeUrl: "https://platform.claude.com/oauth/code/callback?client_id=abc&state=xyz",
      flow: "code_relay",
      provider: "anthropic",
    });
    vi.spyOn(window, "open").mockReturnValue({
      location: { href: "" },
      close: vi.fn(),
      closed: false,
    } as unknown as Window);

    render(
      <ProviderConfigModal
        provider={provider({ id: "anthropic" })}
        onClose={noop}
        onSaved={asyncNoop}
        onNotice={noop}
        scope="user"
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("user-oauth-connect"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("user-oauth-code-input")).toBeTruthy();
    });
  });

  it("submitting the pasted code calls exchangeUserProviderOAuth and shows Connected", async () => {
    startUserProviderOAuth.mockResolvedValue({
      authorizeUrl: "https://platform.claude.com/oauth/code/callback?client_id=abc&state=xyz",
      flow: "code_relay",
      provider: "anthropic",
    });
    exchangeUserProviderOAuth.mockResolvedValue({
      id: "cred-2",
      provider: "anthropic",
      authMode: "oauth_token",
      secretHint: "…be2f",
      lastVerifiedAt: "2026-08-18T00:00:00Z",
      lastVerifyStatus: "ok",
    });
    vi.spyOn(window, "open").mockReturnValue({
      location: { href: "" },
      close: vi.fn(),
      closed: false,
    } as unknown as Window);
    const onSaved = vi.fn(asyncNoop);

    render(
      <ProviderConfigModal
        provider={provider({ id: "anthropic" })}
        onClose={noop}
        onSaved={onSaved}
        onNotice={noop}
        scope="user"
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("user-oauth-connect"));
    });
    await waitFor(() => screen.getByTestId("user-oauth-code-input"));

    fireEvent.change(screen.getByTestId("user-oauth-code-input"), {
      target: { value: "ONETIMECODE#xyz" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("user-oauth-complete"));
    });

    await waitFor(() => {
      expect(exchangeUserProviderOAuth).toHaveBeenCalledWith("anthropic", "ONETIMECODE#xyz");
    });
    await waitFor(() => {
      expect(screen.getByTestId("provider-config-hint").textContent).toContain("be2f");
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("a key-only provider (no OAuth descriptor) shows ONLY the key field — no Connect button", () => {
    render(
      <ProviderConfigModal
        provider={provider({
          id: "openai",
          name: "OpenAI",
          auth: "API Key",
          color: "#10A37F",
          icon: "fa-brain",
          detail: "You have not added your own OpenAI key.",
        })}
        onClose={noop}
        onSaved={asyncNoop}
        onNotice={noop}
        scope="user"
      />,
    );
    expect(screen.queryByTestId("user-oauth-connect")).toBeNull();
    expect(screen.queryByTestId("user-oauth-code-input")).toBeNull();
    expect(screen.getByTestId("provider-secret-input")).toBeTruthy();
  });

  it("deployment scope (admin) never shows the per-user Connect button", () => {
    render(
      <ProviderConfigModal
        provider={provider({ id: "openrouter", name: "OpenRouter", color: "#6467F2", icon: "fa-route" })}
        onClose={noop}
        onSaved={asyncNoop}
        onNotice={noop}
        scope="deployment"
      />,
    );
    expect(screen.queryByTestId("user-oauth-connect")).toBeNull();
  });
});
