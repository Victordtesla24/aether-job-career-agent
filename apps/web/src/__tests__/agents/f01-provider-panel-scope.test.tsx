// @vitest-environment jsdom
/**
 * F-01 — /dashboard/agents must not render the OPERATOR's provider credentials
 * to an ordinary customer.
 *
 * FINDING (docs/delivery/PROD-UAT-2026-08-03.md F-01): the "AI Provider
 * Connections" panel was rendered unconditionally, for every signed-in user,
 * from `GET /agents/providers` — a deployment-wide store with no user id in it.
 * A free-tier customer's browser therefore received the operator's provider
 * rows: connection status, credential SOURCE, the last-4 `secretHint` of the
 * operator's real key, `lastVerifiedAt`, and a "Manage" button wired to the
 * deployment-wide PUT/DELETE/verify routes.
 *
 * Gating the buttons is not enough — a 403 that only appears after clicking
 * still means the data was sent. These tests assert the request is never made:
 *
 *  - a non-admin NEVER calls `fetchProviders`, gets the per-user catalog
 *    instead, and no byte of the operator's hint reaches the DOM;
 *  - an admin (the operator) still gets the deployment-wide panel unchanged;
 *  - the customer's credential modal writes the PER-USER store, and the
 *    deployment-wide Connect-with-Anthropic control (which writes the shared
 *    row, and is admin-only server-side) is not offered to them — they get
 *    the per-user mint instead (UPO-1).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));

const fetchAgentsMock = vi.hoisted(() => vi.fn());
const fetchAgentRunsMock = vi.hoisted(() => vi.fn());
const runAgentMock = vi.hoisted(() => vi.fn());
const runPipelineMock = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api/agents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/agents")>();
  return {
    ...actual,
    fetchAgents: fetchAgentsMock,
    fetchAgentRuns: fetchAgentRunsMock,
    runAgent: runAgentMock,
    runPipeline: runPipelineMock,
  };
});

const fetchMeMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/admin")>();
  return { ...actual, fetchMe: fetchMeMock };
});

const fetchCatalogMock = vi.hoisted(() => vi.fn());
const fetchProvidersMock = vi.hoisted(() => vi.fn());
const fetchUserProviderCatalogMock = vi.hoisted(() => vi.fn());
const fetchAgentStatsMock = vi.hoisted(() => vi.fn());
const updateAgentConfigMock = vi.hoisted(() => vi.fn());
const updateProviderMock = vi.hoisted(() => vi.fn());
const fetchProviderModelsMock = vi.hoisted(() => vi.fn());
const refreshProviderModelsMock = vi.hoisted(() => vi.fn());
const fetchProviderCatalogMock = vi.hoisted(() => vi.fn());
const putUserProviderCredentialMock = vi.hoisted(() => vi.fn());
const putProviderCredentialMock = vi.hoisted(() => vi.fn());

vi.mock("../../components/agents/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/agents/api")>();
  return {
    ...actual,
    fetchCatalog: fetchCatalogMock,
    fetchProviders: fetchProvidersMock,
    fetchUserProviderCatalog: fetchUserProviderCatalogMock,
    fetchAgentStats: fetchAgentStatsMock,
    updateAgentConfig: updateAgentConfigMock,
    updateProvider: updateProviderMock,
    fetchProviderModels: fetchProviderModelsMock,
    refreshProviderModels: refreshProviderModelsMock,
    fetchProviderCatalog: fetchProviderCatalogMock,
    putUserProviderCredential: putUserProviderCredentialMock,
    putProviderCredential: putProviderCredentialMock,
  };
});

import AgentsPage from "../../app/dashboard/agents/page";
import type { Provider } from "../../components/agents/api";

/** The operator's REAL deployment row shape, incl. the last-4 of their key. */
const OPERATOR_OPENROUTER: Provider = {
  id: "openrouter",
  name: "OpenRouter",
  auth: "OAuth + API Key",
  status: "connected",
  model: "",
  detail: "Credential stored in the encrypted vault (…7391)",
  models: [],
  icon: "fa-route",
  color: "#6467F2",
  source: "database",
  authMode: "api_key",
  secretHint: "…7391",
  lastVerifiedAt: "2026-08-01T00:00:00",
  lastVerifyStatus: "ok",
  needsReauth: false,
};

/** The same provider as a CUSTOMER sees it: their own store, which is empty. */
const CUSTOMER_OPENROUTER: Provider = {
  ...OPERATOR_OPENROUTER,
  status: "unconfigured",
  detail: "You have not added your own OpenRouter key.",
  source: "none",
  authMode: null,
  secretHint: null,
  lastVerifiedAt: null,
  lastVerifyStatus: null,
};

const CATALOG = { agents: [], counts: { total: 0, active: 0, paused: 0, error: 0, planned: 0 } };
const STATS = {
  spendUsd: 0,
  avgCostPerRun: 0,
  providerCount: 1,
  tokensTotal: 0,
  tokensIn: 0,
  tokensOut: 0,
  mostActiveAgent: null,
  successRate: 0,
  taskCount: 0,
};

beforeEach(() => {
  vi.clearAllMocks();
  fetchCatalogMock.mockResolvedValue(CATALOG);
  fetchAgentStatsMock.mockResolvedValue(STATS);
  fetchAgentsMock.mockResolvedValue([]);
  fetchAgentRunsMock.mockResolvedValue([]);
  fetchProvidersMock.mockResolvedValue([OPERATOR_OPENROUTER]);
  fetchUserProviderCatalogMock.mockResolvedValue([CUSTOMER_OPENROUTER]);
  fetchProviderModelsMock.mockResolvedValue([]);
  fetchProviderCatalogMock.mockResolvedValue({
    provider: "openrouter",
    count: 0,
    models: [],
    lastRefreshedAt: null,
    stale: false,
  });
});

afterEach(cleanup);

describe("F-01 — the operator's provider credentials are not shipped to customers", () => {
  it("never requests the deployment-wide provider list for a non-admin", async () => {
    fetchMeMock.mockResolvedValue({ id: "u-cust", email: "c@example.com", name: "", isAdmin: false });

    render(<AgentsPage />);

    await waitFor(() => expect(fetchUserProviderCatalogMock).toHaveBeenCalled());
    expect(fetchProvidersMock).not.toHaveBeenCalled();
  });

  it("shows a non-admin their OWN key panel — no operator hint, source or timestamp", async () => {
    fetchMeMock.mockResolvedValue({ id: "u-cust", email: "c@example.com", name: "", isAdmin: false });

    const { container } = render(<AgentsPage />);

    // Wait for the CARDS, not just the heading: the heading renders as soon as
    // isAdmin resolves, while the rows arrive one tick later.
    await waitFor(() => expect(screen.getByTestId("provider-openrouter")).toBeTruthy());
    expect(screen.getByText("Your AI Provider Keys")).toBeTruthy();
    expect(screen.queryByText("AI Provider Connections")).toBeNull();
    // The operator's last-4 must be nowhere in the rendered document.
    expect(container.textContent).not.toContain("7391");
    expect(screen.queryByTestId("provider-hint-openrouter")).toBeNull();
    expect(screen.getByTestId("provider-source-openrouter").textContent).not.toContain("Saved");
  });

  it("keeps the operator's own panel intact for an admin", async () => {
    fetchMeMock.mockResolvedValue({ id: "u-op", email: "op@example.com", name: "", isAdmin: true });

    render(<AgentsPage />);

    await waitFor(() => expect(screen.getByTestId("provider-hint-openrouter")).toBeTruthy());
    expect(screen.getByText("AI Provider Connections")).toBeTruthy();
    expect(fetchProvidersMock).toHaveBeenCalled();
    expect(fetchUserProviderCatalogMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("provider-hint-openrouter").textContent).toContain("…7391");
  });

  it("routes a customer's credential save to the PER-USER store, not the operator's", async () => {
    fetchMeMock.mockResolvedValue({ id: "u-cust", email: "c@example.com", name: "", isAdmin: false });
    putUserProviderCredentialMock.mockResolvedValue({
      id: "cred-1",
      provider: "openrouter",
      authMode: "api_key",
      secretHint: "…5150",
      lastVerifiedAt: null,
      lastVerifyStatus: "ok",
    });

    render(<AgentsPage />);
    await waitFor(() => expect(screen.getByTestId("provider-action-openrouter")).toBeTruthy());

    fireEvent.click(screen.getByTestId("provider-action-openrouter"));
    await waitFor(() => expect(screen.getByTestId("provider-secret-input")).toBeTruthy());
    fireEvent.change(screen.getByTestId("provider-secret-input"), {
      target: { value: "sk-or-customer-own-key5150" },
    });
    fireEvent.click(screen.getByTestId("provider-config-save"));

    await waitFor(() => expect(putUserProviderCredentialMock).toHaveBeenCalledWith("openrouter", {
      authMode: "api_key",
      secret: "sk-or-customer-own-key5150",
    }));
    expect(putProviderCredentialMock).not.toHaveBeenCalled();
  });

  it("gives a customer the per-user token mint, never the deployment-wide control", async () => {
    fetchMeMock.mockResolvedValue({ id: "u-cust", email: "c@example.com", name: "", isAdmin: false });
    fetchUserProviderCatalogMock.mockResolvedValue([
      { ...CUSTOMER_OPENROUTER, id: "anthropic", name: "Anthropic Claude", auth: "API Key" },
    ]);

    render(<AgentsPage />);
    await waitFor(() => expect(screen.getByTestId("provider-action-anthropic")).toBeTruthy());
    fireEvent.click(screen.getByTestId("provider-action-anthropic"));

    await waitFor(() => expect(screen.getByTestId("provider-config-modal")).toBeTruthy());
    expect(screen.queryByTestId("anthropic-oauth-connect")).toBeNull();
    expect(screen.queryByTestId("anthropic-oauth-reconnect")).toBeNull();
    expect(screen.getByTestId("anthropic-oauth-user-connect")).toBeTruthy();
  });
});
