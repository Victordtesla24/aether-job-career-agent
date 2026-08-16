// @vitest-environment jsdom
/**
 * R1.2 — decision guidance on the non-executive admin metric surfaces.
 *
 * Each admin page that renders measured figures (health, spend, billing
 * catalog, subscriptions, audit log) must carry the shared
 * "What this tells you / What to do next" affordance so an admin knows what
 * decision each surface supports. RED first: these pages had honest data but
 * no decision annotation.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchAdminHealthMock = vi.fn();
const fetchAdminSpendMock = vi.fn();
const fetchAuditLogMock = vi.fn();
const fetchAdminUsersMock = vi.fn();
const fetchAdminPlansMock = vi.fn();

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("../../../lib/api/adminPlans", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/adminPlans")>();
  return {
    ...actual,
    fetchAdminPlans: (...a: unknown[]) => fetchAdminPlansMock(...a),
  };
});

vi.mock("../../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/admin")>();
  return {
    ...actual,
    fetchAdminHealth: (...a: unknown[]) => fetchAdminHealthMock(...a),
    fetchAdminSpend: (...a: unknown[]) => fetchAdminSpendMock(...a),
    fetchAuditLog: (...a: unknown[]) => fetchAuditLogMock(...a),
    fetchAdminUsers: (...a: unknown[]) => fetchAdminUsersMock(...a),
    fetchAdminPlans: (...a: unknown[]) => fetchAdminPlansMock(...a),
  };
});

import { HealthOverview } from "../../../components/admin/health-overview";
import AdminSpendPage from "../spend/page";
import AdminAuditLogPage from "../audit-log/page";
import AdminBillingPage from "../billing/page";
import AdminSubscriptionsPage from "../subscriptions/page";

beforeEach(() => {
  fetchAdminHealthMock.mockReset().mockResolvedValue({
    services: { api: "ok", database: "ok" },
    agents: { totalRuns: 4, succeeded: 3, failed: 1, running: 0, queued: 0, successRate: 0.75 },
    llm: { mode: "live" },
    cron: { status: "ok", detail: "scheduler heartbeat 12s ago" },
    providers: { configuredTiers: ["standard"], count: 1 },
  });
  fetchAdminSpendMock.mockReset().mockResolvedValue({
    totalUsd: 12.6,
    perUser: [{ userId: "u1", name: "A", email: "a@example.com", runCount: 3, spendUsd: 12.6 }],
  });
  fetchAuditLogMock.mockReset().mockResolvedValue({
    entries: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
  fetchAdminUsersMock.mockReset().mockResolvedValue({ users: [], total: 0 });
  fetchAdminPlansMock.mockReset().mockResolvedValue({ plans: [] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function expectGuidance(minCount = 1) {
  await waitFor(() => {
    const notes = screen.getAllByTestId("decision-guidance");
    expect(notes.length).toBeGreaterThanOrEqual(minCount);
    for (const note of notes) {
      expect(note.textContent).toContain("What this tells you");
      expect(note.textContent).toContain("What to do next");
      expect((note.textContent ?? "").length).toBeGreaterThan(60);
    }
  });
}

describe("R1.2 decision guidance on admin metric surfaces", () => {
  it("health overview carries a decision affordance", async () => {
    render(<HealthOverview />);
    await waitFor(() => expect(screen.getAllByText(/Agent success rate/i).length).toBeGreaterThan(0));
    await expectGuidance(1);
  });

  it("/admin/spend carries a decision affordance", async () => {
    render(<AdminSpendPage />);
    await waitFor(() => expect(screen.getByText(/Total LLM spend/i)).toBeTruthy());
    await expectGuidance(1);
  });

  it("/admin/audit-log carries a decision affordance", async () => {
    render(<AdminAuditLogPage />);
    await waitFor(() => expect(fetchAuditLogMock).toHaveBeenCalled());
    await expectGuidance(1);
  });

  it("/admin/billing carries a decision affordance", async () => {
    render(<AdminBillingPage />);
    await waitFor(() => expect(fetchAdminPlansMock).toHaveBeenCalled());
    await expectGuidance(1);
  });

  it("/admin/subscriptions carries a decision affordance", async () => {
    render(<AdminSubscriptionsPage />);
    await waitFor(() => expect(fetchAdminUsersMock).toHaveBeenCalled());
    await expectGuidance(1);
  });
});
