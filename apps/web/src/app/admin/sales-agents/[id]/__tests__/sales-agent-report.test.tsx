// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-2 (c) — /admin/sales-agents/[id], the commission report.
 *
 * RED-first: the page does not exist in this tree yet.
 *
 * THIS SCREEN PAYS NOBODY, and it has to say so. BE-2's route writes nothing,
 * creates no Stripe object and schedules no payout — `reportOnly: true` /
 * `payoutPerformed: false` are in the payload for exactly this reason. A screen
 * with a confident "Commission owed" figure and no such labelling invites an
 * admin to believe the money moved.
 *
 * THE SECOND HONESTY RULE HERE is BE-2's own: the money totals are EXACT at any
 * N (a commission is arithmetic on real payments), while the derived CONVERSION
 * RATE is suppressed below the sample floor and arrives as `null`. So a small
 * sample must NOT grey out the dollars, and must NOT print a percentage.
 *
 * The disclosure counters (`unparsablePaymentEvents`, `refundEventsWithNoCustomer`,
 * `sharedStripeCustomerAccounts`) exist so a record the report could not read is
 * SHOWN rather than quietly dropped — the specs pin that they surface when
 * non-zero.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../../lib/api/client";

const useParamsMock = vi.fn();
vi.mock("next/navigation", () => ({ useParams: () => useParamsMock() }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)}>{children}</a>
  ),
}));

const fetchSalesAgentReportMock = vi.fn();
vi.mock("../../../../../lib/api/adminSalesAgents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../../lib/api/adminSalesAgents")>();
  return {
    ...actual,
    fetchSalesAgentReport: (...a: unknown[]) => fetchSalesAgentReportMock(...a),
  };
});

// eslint-disable-next-line import/first
import AdminSalesAgentReportPage from "../page";

const AGENT_ID = "agent-1";

function report(overrides: Record<string, unknown> = {}) {
  return {
    agent: {
      id: AGENT_ID,
      name: "Jane Reseller",
      email: "jane@partner.example",
      referralCode: "JANERES-K7M2QP4X",
      commissionPct: 12.5,
      status: "active",
      notes: null,
      createdAt: "2026-08-01T00:00:00Z",
      updatedAt: "2026-08-01T00:00:00Z",
      createdBy: "admin-1",
      attributedSignups: 3,
      convertedPaid: 1,
    },
    asOf: "2026-08-15T02:00:00Z",
    currency: "AUD",
    commissionPct: 12.5,
    reportOnly: true,
    payoutPerformed: false,
    gstRegistered: false,
    source:
      "signature-verified Stripe webhook payloads recorded locally in StripeEvent",
    attributedUsers: [
      {
        userId: "u1",
        email: "paid@example.com",
        name: "Paid Person",
        signedUpAt: "2026-08-02T00:00:00Z",
        deleted: false,
        planId: "pro",
        subStatus: "active",
        stripeCustomerId: "cus_1",
        sharesStripeCustomerWith: null,
        converted: true,
        paymentCount: 2,
        grossPaidAud: 78,
        refundedAud: 0,
        netPaidAud: 78,
      },
      {
        userId: "u2",
        email: "free@example.com",
        name: null,
        signedUpAt: "2026-08-03T00:00:00Z",
        deleted: false,
        planId: "free",
        subStatus: "canceled",
        stripeCustomerId: null,
        sharesStripeCustomerWith: null,
        converted: false,
        paymentCount: 0,
        grossPaidAud: 0,
        refundedAud: 0,
        netPaidAud: 0,
      },
    ],
    totals: {
      attributedUsers: 3,
      convertedUsers: 1,
      payingUsers: 1,
      paymentCount: 2,
      grossPaidAud: 78,
      refundedAud: 0,
      netPaidAud: 78,
      commissionAud: 9.75,
    },
    otherCurrencies: {},
    conversionRate: null,
    sampleSize: 3,
    rateSampleFloor: 20,
    insufficientData: true,
    unparsablePaymentEvents: 0,
    refundEventsWithNoCustomer: 0,
    sharedStripeCustomerAccounts: 0,
    ...overrides,
  };
}

async function renderPage(r: unknown = report()) {
  useParamsMock.mockReturnValue({ id: AGENT_ID });
  if (r instanceof Error) fetchSalesAgentReportMock.mockRejectedValue(r);
  else fetchSalesAgentReportMock.mockResolvedValue(r);
  render(<AdminSalesAgentReportPage />);
  await waitFor(() => expect(fetchSalesAgentReportMock).toHaveBeenCalledWith(AGENT_ID));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("report-only labelling", () => {
  it("states that nothing was paid and no payout was scheduled", async () => {
    await renderPage();
    const banner = await screen.findByTestId("admin-agent-report-only");
    expect(banner.textContent).toMatch(/report/i);
    expect(banner.textContent).toMatch(/no (payout|money)|pays nobody|nothing was paid/i);
  });

  it("offers no pay/payout action of any kind", async () => {
    await renderPage();
    await screen.findByTestId("admin-agent-report-only");
    expect(screen.queryByRole("button", { name: /pay |payout|mark.*paid/i })).toBeNull();
  });

  it("names the evidence the figures come from", async () => {
    await renderPage();
    expect((await screen.findByTestId("admin-agent-report-source")).textContent).toContain(
      "Stripe webhook payloads",
    );
  });
});

describe("money is exact at any sample size; the rate is not", () => {
  it("shows the commission and net totals even on a tiny sample", async () => {
    await renderPage();
    const totals = await screen.findByTestId("admin-agent-report-totals");
    expect(totals.textContent).toContain("78");
    expect(screen.getByTestId("admin-agent-commission").textContent).toContain("9.75");
  });

  it("suppresses the conversion rate below the floor and says why", async () => {
    await renderPage();
    const rate = await screen.findByTestId("admin-agent-conversion-rate");
    expect(rate.textContent).not.toMatch(/\d+(\.\d+)?%/);
    expect(rate.textContent).toMatch(/3 of 20|sample|not enough/i);
  });

  it("shows the rate as a percentage once the sample clears the floor", async () => {
    await renderPage(
      report({ conversionRate: 0.25, sampleSize: 24, insufficientData: false }),
    );
    expect((await screen.findByTestId("admin-agent-conversion-rate")).textContent).toContain(
      "25",
    );
  });
});

describe("attributed accounts", () => {
  it("lists each referred account with what it really paid", async () => {
    await renderPage();
    const paid = await screen.findByTestId("admin-agent-user-u1");
    expect(paid.textContent).toContain("paid@example.com");
    expect(paid.textContent).toContain("78");
    const free = screen.getByTestId("admin-agent-user-u2");
    expect(free.textContent).toContain("free@example.com");
  });

  it("flags an account that shares a Stripe customer instead of double-counting it", async () => {
    await renderPage(
      report({
        attributedUsers: [
          {
            ...report().attributedUsers[0],
            userId: "u3",
            email: "dup@example.com",
            sharesStripeCustomerWith: "u1",
            grossPaidAud: 0,
            netPaidAud: 0,
            paymentCount: 0,
          },
        ],
        sharedStripeCustomerAccounts: 1,
      }),
    );
    const row = await screen.findByTestId("admin-agent-user-u3");
    expect(row.textContent).toMatch(/shares/i);
    expect(screen.getByTestId("admin-agent-disclosures").textContent).toMatch(/shares|shared/i);
  });

  it("shows disclosure counters when records could not be read", async () => {
    await renderPage(
      report({ unparsablePaymentEvents: 2, refundEventsWithNoCustomer: 1 }),
    );
    const disclosures = await screen.findByTestId("admin-agent-disclosures");
    expect(disclosures.textContent).toContain("2");
    expect(disclosures.textContent).toContain("1");
  });

  it("hides the disclosure block entirely when every record parsed", async () => {
    await renderPage();
    await screen.findByTestId("admin-agent-report-totals");
    expect(screen.queryByTestId("admin-agent-disclosures")).toBeNull();
  });
});

describe("failures", () => {
  it("reports a missing agent honestly instead of an empty report", async () => {
    await renderPage(new ApiError("Sales agent not found", 404));
    expect((await screen.findByTestId("admin-agent-report-error")).textContent).toContain(
      "Sales agent not found",
    );
    expect(screen.queryByTestId("admin-agent-report-totals")).toBeNull();
  });
});
