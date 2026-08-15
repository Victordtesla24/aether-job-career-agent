"use client";

/**
 * /admin/sales-agents/[id] — one agent's commission report.
 *
 * THIS PAGE PAYS NOBODY. `GET /admin/sales-agents/{id}/report` writes nothing,
 * creates no Stripe object and schedules no payout — `reportOnly` /
 * `payoutPerformed` are in the payload precisely so a screen cannot quietly
 * imply otherwise. There is therefore no "Pay" or "Mark as paid" control here,
 * and the banner says what the figure is: an amount owed by arithmetic, not an
 * amount sent.
 *
 * TWO KINDS OF NUMBER, TWO DIFFERENT RULES, and conflating them is the mistake
 * this layout is arranged to prevent:
 *
 *   * MONEY IS EXACT AT ANY N. A commission is arithmetic over real payments —
 *     signature-verified Stripe webhook payloads recorded locally, net of real
 *     refunds. Three accounts or three thousand, the dollars are the dollars, so
 *     a small sample must NOT grey them out.
 *   * THE CONVERSION RATE IS A READING, and below the API's sample floor it
 *     arrives as `null`. A percentage of three accounts looks like precision
 *     that is not there, so the slot says how far off the floor it is instead.
 *
 * DISCLOSURE OVER TIDINESS. A payment record the report could not parse, a
 * refund with no customer attached, or two attributed accounts sharing one
 * Stripe customer are all SHOWN when present. Netting them away silently would
 * make the totals look cleaner than the evidence behind them actually is.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../../components/admin/admin-shell";
import {
  CopyButton,
  Panel,
  StatTile,
  StatusPill,
  formatAudExact,
} from "../../../../components/admin/admin-ui";
import { formatDate, formatDateTime } from "../../../../lib/format";
import {
  fetchSalesAgentReport,
  referralLink,
  type SalesAgentReport,
} from "../../../../lib/api/adminSalesAgents";

export default function AdminSalesAgentReportPage() {
  const params = useParams<{ id: string }>();
  const agentId = params?.id ?? "";
  const [report, setReport] = useState<SalesAgentReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await fetchSalesAgentReport(agentId));
      setError(null);
    } catch (e) {
      setReport(null);
      setError(e instanceof Error ? e.message : "Failed to load the commission report");
    }
  }, [agentId]);

  useEffect(() => {
    if (agentId) void load();
  }, [agentId, load]);

  if (error) {
    return (
      <div>
        <AdminPageHeader title="Commission report" />
        <p role="alert" data-testid="admin-agent-report-error" className="text-sm text-red-300">
          {error}
        </p>
        <p className="type-meta mt-3">
          <Link href="/admin/sales-agents" className="text-aether-coral hover:underline">
            ← All sales agents
          </Link>
        </p>
      </div>
    );
  }

  if (!report) return <p className="text-sm text-aether-muted">Loading…</p>;

  const { agent, totals } = report;
  const link = referralLink(agent.referralCode);
  const rateKnown = report.conversionRate !== null && !report.insufficientData;
  const disclosures =
    (report.unparsablePaymentEvents ?? 0) > 0 ||
    (report.refundEventsWithNoCustomer ?? 0) > 0 ||
    (report.sharedStripeCustomerAccounts ?? 0) > 0;

  return (
    <div>
      <AdminPageHeader
        title={agent.name}
        subtitle={`Commission report · ${agent.commissionPct}% of net payments · as at ${formatDateTime(report.asOf)}`}
      />

      <div
        data-testid="admin-agent-report-only"
        className="mb-4 rounded-xl border border-aether-indigo/40 bg-aether-indigo/[0.07] p-3"
      >
        <p className="text-sm font-medium text-aether-text">
          This is a report. Nothing was paid.
        </p>
        <p className="type-meta mt-1 max-w-prose">
          Reading this page moves no money: it creates no Stripe object, schedules no
          payout and writes nothing. The commission below is arithmetic on payments
          that really arrived — paying an agent stays a deliberate act performed
          outside this product.
          {report.gstRegistered ? "" : " No GST is included (the operator is not GST-registered)."}
        </p>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          testId="admin-agent-commission"
          label={`Commission owed (${agent.commissionPct}%)`}
          value={formatAudExact(totals.commissionAud)}
          hint="Net payments × the agent's rate. Exact, not a sample."
        />
        <StatTile
          label="Net paid by referrals"
          value={formatAudExact(totals.netPaidAud)}
          hint={`${formatAudExact(totals.grossPaidAud)} gross less ${formatAudExact(totals.refundedAud)} refunded.`}
        />
        <StatTile
          label="Attributed accounts"
          value={totals.attributedUsers ?? "—"}
          hint={`${totals.convertedUsers ?? 0} converted to paid · ${totals.payingUsers ?? 0} have actually paid.`}
        />
        {/* The testid spans the whole tile: the value and the reason it is (or
            is not) drawn are ONE statement, and asserting on the numeral alone
            would let a bare "—" pass for an explanation. */}
        <div data-testid="admin-agent-conversion-rate" className="elev-1 min-w-0 rounded-2xl p-4">
          <p className="type-section truncate">Conversion rate</p>
          <p
            className="mono mt-2 text-[24px] font-semibold leading-none tracking-[-0.02em] tabular-nums"
            style={rateKnown ? undefined : { color: "#8B8BA3" }}
          >
            {rateKnown ? `${((report.conversionRate ?? 0) * 100).toFixed(1)}%` : "—"}
          </p>
          {rateKnown ? (
            <p className="type-meta mt-2">Converted accounts over attributed accounts.</p>
          ) : (
            <p className="type-meta mt-2">
              Not enough data yet: {report.sampleSize ?? 0} of {report.rateSampleFloor ?? 20}{" "}
              attributed accounts. The money figures beside this are exact regardless —
              only this derived reading is withheld.
            </p>
          )}
        </div>
      </div>

      <Panel
        title="Totals"
        caption="Every figure below is counted, not estimated."
        testId="admin-agent-report-totals"
      >
        <dl className="grid grid-cols-2 gap-y-2 text-sm sm:grid-cols-4">
          <dt className="text-aether-muted">Gross paid</dt>
          <dd className="mono text-aether-text tabular-nums">
            {formatAudExact(totals.grossPaidAud)}
          </dd>
          <dt className="text-aether-muted">Refunded</dt>
          <dd className="mono text-aether-text tabular-nums">
            {formatAudExact(totals.refundedAud)}
          </dd>
          <dt className="text-aether-muted">Net paid</dt>
          <dd className="mono text-aether-text tabular-nums">
            {formatAudExact(totals.netPaidAud)}
          </dd>
          <dt className="text-aether-muted">Payments</dt>
          <dd className="mono text-aether-text tabular-nums">{totals.paymentCount ?? "—"}</dd>
        </dl>
        <p data-testid="admin-agent-report-source" className="type-meta mt-3 max-w-prose">
          Source: {report.source ?? "not declared by the API."}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="type-meta">Referral link:</span>
          <code className="mono break-all text-[11px] text-aether-text">{link}</code>
          <CopyButton value={link} ariaLabel={`Copy ${agent.name}'s referral link`} />
          <StatusPill tone={agent.status === "active" ? "good" : "neutral"} state={agent.status}>
            {agent.status}
          </StatusPill>
        </div>
      </Panel>

      {disclosures ? (
        <div className="mt-4">
          <Panel
            title="Records this report could not fully read"
            caption="Shown rather than dropped — the totals above exclude them."
            testId="admin-agent-disclosures"
          >
            <ul className="list-disc space-y-1 pl-5 text-sm text-aether-amber">
              {(report.unparsablePaymentEvents ?? 0) > 0 ? (
                <li>
                  {report.unparsablePaymentEvents} payment event(s) could not be parsed or
                  matched to a customer, so their amounts are not in the totals.
                </li>
              ) : null}
              {(report.refundEventsWithNoCustomer ?? 0) > 0 ? (
                <li>
                  {report.refundEventsWithNoCustomer} refund event(s) carry no customer id,
                  so they could not be deducted from any specific account.
                </li>
              ) : null}
              {(report.sharedStripeCustomerAccounts ?? 0) > 0 ? (
                <li>
                  Shared Stripe customer: {report.sharedStripeCustomerAccounts} attributed
                  account(s) point at a Stripe customer already claimed by an earlier
                  account. The first account by signup date keeps the payments; the later
                  one is shown at A$0 so the same money is not credited twice.
                </li>
              ) : null}
            </ul>
          </Panel>
        </div>
      ) : null}

      <div className="mt-4">
        <Panel title="Attributed accounts" testId="admin-agent-users">
          {report.attributedUsers.length === 0 ? (
            <p className="text-sm text-aether-muted">
              No accounts have signed up through this code yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-aether-muted-dim">
                  <tr>
                    <th className="py-2 pr-4">Account</th>
                    <th className="py-2 pr-4">Signed up</th>
                    <th className="py-2 pr-4">Plan</th>
                    <th className="py-2 pr-4 text-right">Gross</th>
                    <th className="py-2 pr-4 text-right">Refunded</th>
                    <th className="py-2 pr-4 text-right">Net</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {report.attributedUsers.map((entry) => (
                    <tr key={entry.userId} data-testid={`admin-agent-user-${entry.userId}`}>
                      <td className="py-2.5 pr-4 align-top">
                        <p className="text-aether-text">{entry.email ?? entry.userId}</p>
                        <span className="mt-1 inline-flex flex-wrap gap-1">
                          {entry.converted ? (
                            <StatusPill tone="good">paid</StatusPill>
                          ) : (
                            <StatusPill tone="neutral">not converted</StatusPill>
                          )}
                          {entry.deleted ? <StatusPill tone="warn">deleted</StatusPill> : null}
                        </span>
                        {entry.sharesStripeCustomerWith ? (
                          <p className="type-meta mt-1 text-aether-amber">
                            Shares a Stripe customer with an earlier attributed account —
                            its payments are credited there, not counted twice here.
                          </p>
                        ) : null}
                      </td>
                      <td className="py-2.5 pr-4 align-top text-aether-muted">
                        {formatDate(entry.signedUpAt)}
                      </td>
                      <td className="py-2.5 pr-4 align-top text-aether-muted">
                        {entry.planId ?? "—"}
                        {entry.subStatus ? ` · ${entry.subStatus}` : ""}
                      </td>
                      <td className="mono py-2.5 pr-4 text-right align-top tabular-nums text-aether-text">
                        {formatAudExact(entry.grossPaidAud)}
                      </td>
                      <td className="mono py-2.5 pr-4 text-right align-top tabular-nums text-aether-text">
                        {formatAudExact(entry.refundedAud)}
                      </td>
                      <td className="mono py-2.5 pr-4 text-right align-top tabular-nums text-aether-text">
                        {formatAudExact(entry.netPaidAud)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <p className="type-meta mt-4">
        <Link href="/admin/sales-agents" className="text-aether-coral hover:underline">
          ← All sales agents
        </Link>
      </p>
    </div>
  );
}
