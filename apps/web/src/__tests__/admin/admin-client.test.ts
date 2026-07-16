/**
 * GAP-P6-ADMIN-001/003, SEC-001 — Admin API client coverage.
 *
 * Locks the request contract (paths, verbs, query strings, bodies) and the
 * USD-only presentation (§14.8: LLM spend is billed in USD — never AUD).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchAdminSpend,
  fetchAdminUsers,
  fetchMe,
  formatUsd,
  setSpendCap,
  setSuspended,
  updateAdminSettings,
} from "../../lib/api/admin";

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const USER_ROW = {
  id: "cadmin0000000000000000001",
  email: "user@example.com",
  name: "Test User",
  isAdmin: false,
  suspended: false,
  plan: "free",
  subStatus: "active",
  signupAt: "2026-07-01T00:00:00Z",
  lastLoginAt: "2026-07-10T00:00:00Z",
  spendUsd: 1.2345,
  runCount: 3,
  currency: "USD",
};

describe("Admin API client", () => {
  it("fetchMe surfaces the isAdmin flag from /auth/me", async () => {
    const fetchMock = mockFetchOnce({ id: "u1", email: "a@b.co", isAdmin: true });
    const me = await fetchMe({ token: "tok" });
    expect(me.isAdmin).toBe(true);
    expect(String(fetchMock.mock.calls[0]![0])).toContain("/auth/me");
  });

  it("fetchAdminUsers encodes filters into the query string", async () => {
    const fetchMock = mockFetchOnce({ users: [USER_ROW], total: 1, limit: 100, offset: 0 });
    const res = await fetchAdminUsers(
      { q: "user@example.com", plan: "pro", suspended: true },
      { token: "tok" },
    );
    expect(res.users[0]!.spendUsd).toBeCloseTo(1.2345);
    expect(res.users[0]!.currency).toBe("USD");
    const url = String(fetchMock.mock.calls[0]![0]);
    expect(url).toContain("/admin/users?");
    expect(url).toContain("q=user%40example.com");
    expect(url).toContain("plan=pro");
    expect(url).toContain("suspended=true");
  });

  it("setSpendCap POSTs the spendCapUsd body to the per-user route", async () => {
    const fetchMock = mockFetchOnce({ userId: "u1", spendCapUsd: 0, currency: "USD" });
    const res = await setSpendCap("u1", 0, { token: "tok" });
    expect(res.spendCapUsd).toBe(0);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/admin/users/u1/spend-cap");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((init as RequestInit).body)).spendCapUsd).toBe(0);
  });

  it("setSuspended targets suspend / unsuspend verbs", async () => {
    const suspendMock = mockFetchOnce({ userId: "u1", suspended: true });
    await setSuspended("u1", true, { token: "tok" });
    expect(String(suspendMock.mock.calls[0]![0])).toContain("/admin/users/u1/suspend");

    const unsuspendMock = mockFetchOnce({ userId: "u1", suspended: false });
    await setSuspended("u1", false, { token: "tok" });
    expect(String(unsuspendMock.mock.calls[0]![0])).toContain("/admin/users/u1/unsuspend");
  });

  it("fetchAdminSpend parses total + per-user USD spend", async () => {
    mockFetchOnce({
      totalUsd: 4.5,
      currency: "USD",
      perUser: [{ userId: "u1", email: "a@b.co", name: "A", spendUsd: 4.5, runCount: 2 }],
    });
    const spend = await fetchAdminSpend({ token: "tok" });
    expect(spend.totalUsd).toBe(4.5);
    expect(spend.perUser[0]!.spendUsd).toBe(4.5);
  });

  it("updateAdminSettings POSTs the toggle patch", async () => {
    const fetchMock = mockFetchOnce({ signupEnabled: false, emailVerificationEnabled: false });
    const res = await updateAdminSettings({ signupEnabled: false }, { token: "tok" });
    expect(res.signupEnabled).toBe(false);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/admin/settings");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((init as RequestInit).body)).signupEnabled).toBe(false);
  });

  it("formatUsd renders US dollars, never AUD", () => {
    const formatted = formatUsd(12.5);
    expect(formatted).toContain("$");
    expect(formatted).not.toContain("A$");
    expect(formatted).not.toContain("AUD");
    // en-US USD renders a bare $ symbol.
    expect(formatted).toBe("$12.50");
  });
});
