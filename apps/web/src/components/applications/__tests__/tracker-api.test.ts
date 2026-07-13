/**
 * GAP-P4-053 regression — fetchAgentConfig must call the endpoint that
 * actually exists (`/workspaces/settings`), not a nonexistent `/settings`
 * alias (a 404 on every /dashboard/applications load).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchAgentConfig } from "../tracker-api";

const SETTINGS_FIXTURE = {
  agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 0.7 },
};

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  return vi.fn().mockResolvedValue(response);
}

describe("fetchAgentConfig", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the real /workspaces/settings endpoint, not /settings", async () => {
    const fetchMock = mockFetchOnce(SETTINGS_FIXTURE);
    vi.stubGlobal("fetch", fetchMock);

    await fetchAgentConfig({ token: "test-token" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/workspaces/settings");
    expect(String(url)).not.toMatch(/\/api\/settings(\?|$)/);
  });

  it("parses agentConfig from the settings payload", async () => {
    vi.stubGlobal("fetch", mockFetchOnce(SETTINGS_FIXTURE));
    const config = await fetchAgentConfig({ token: "test-token" });
    expect(config).toEqual(SETTINGS_FIXTURE.agentConfig);
  });
});
