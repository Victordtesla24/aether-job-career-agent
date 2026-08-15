"use client";

/**
 * /admin/sales-agents — the reseller management surface (ADMIN-2.0 BE-2).
 *
 * A sales agent is a human reseller with a referral code. Accounts that sign up
 * through their link are attributed to them, and each agent's report values that
 * attribution against what those accounts REALLY paid.
 *
 * THERE IS NO DELETE ON THIS PAGE, and that is the backend's design rather than
 * an omission here: `DELETE /admin/sales-agents/{id}` is a 405. A code that has
 * been handed out lives on in links and in the attribution history of every
 * account it brought in, so removal means DEACTIVATION — the code stops
 * attributing new signups and the earned history stays readable. The referral
 * code is immutable for the same reason: rewriting it would silently break every
 * link already in circulation.
 *
 * THE COUNTS ARE NOT DERIVED HERE. `attributedSignups` and `convertedPaid` come
 * from real rows counted by the API under the same rule the billing summary uses
 * for revenue (a non-free plan, a billable status, AND a real Stripe
 * subscription behind it). This page renders them and does no arithmetic of its
 * own — a "conversion rate" computed client-side over three accounts would be a
 * precise-looking reading of nothing.
 *
 * NOT TO BE CONFUSED WITH /admin/sales-agent (singular), which since
 * `origin/main@382f0c2` is the NATIVE in-app Sales AI Agent console — an
 * autonomous outreach agent with its own campaigns, leads and outreach log that
 * sends real email whenever it is not in shadow mode. Different system,
 * different source of truth, and the one that can actually contact a stranger;
 * linked below so neither is lost. (Before `382f0c2` that route was a
 * placeholder for an external, Google-Sheet-driven process with no backend in
 * this repo, which is how FE-2 originally described it here. That description
 * stopped being true when the native agent landed, so it is corrected rather
 * than carried forward.)
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import {
  CopyButton,
  FIELD,
  Panel,
  PRIMARY_BTN,
  QUIET_BTN,
  StatTile,
  StatusPill,
} from "../../../components/admin/admin-ui";
import { formatDate } from "../../../lib/format";
import {
  createSalesAgent,
  fetchSalesAgents,
  isValidReferralCode,
  normalizeReferralCode,
  referralLink,
  suggestReferralCode,
  updateSalesAgent,
  type SalesAgent,
} from "../../../lib/api/adminSalesAgents";

/** A count the API did carry, or an honest dash. Never a substituted zero. */
function count(value: number | null): string {
  return value === null ? "—" : String(value);
}

export default function AdminSalesAgentsPage() {
  const [agents, setAgents] = useState<SalesAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Create form
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [codeTouched, setCodeTouched] = useState(false);
  const [commission, setCommission] = useState("");
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchSalesAgents();
      setAgents(res.agents);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load sales agents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Suggest a code as the name is typed, until the admin edits the field
   * themselves. `suggestReferralCode` returns null when no CSPRNG is available,
   * in which case the field is left blank and the SERVER mints the code — a
   * weak client-side random would look identical while being worth less.
   */
  const onNameChange = (value: string) => {
    setName(value);
    if (codeTouched) return;
    setCode(value.trim() ? (suggestReferralCode(value) ?? "") : "");
  };

  const totals = useMemo(() => {
    const active = agents.filter((a) => a.status === "active").length;
    const signups = agents.reduce((sum, a) => sum + (a.attributedSignups ?? 0), 0);
    const converted = agents.reduce((sum, a) => sum + (a.convertedPaid ?? 0), 0);
    return { active, signups, converted };
  }, [agents]);

  /** One mutation with shared busy/notice/error handling and a reload after. */
  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await action());
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  const onCreate = () => {
    if (!name.trim()) {
      setError("A sales agent needs a name.");
      return;
    }
    const typedCode = code.trim();
    if (typedCode && !isValidReferralCode(typedCode)) {
      setError(
        "A referral code must be 2-32 characters of A-Z, 0-9 or '-', and may not start with '-'.",
      );
      return;
    }
    const pct = commission.trim() === "" ? 0 : Number(commission);
    if (!Number.isFinite(pct) || pct < 0 || pct > 100) {
      setError("Commission must be a number between 0 and 100.");
      return;
    }
    void run(async () => {
      const created = await createSalesAgent({
        name: name.trim(),
        ...(email.trim() ? { email: email.trim() } : {}),
        // Blank means "let the server mint one with `secrets`" — a deliberate
        // path, not a fallback we hide.
        ...(typedCode ? { referralCode: normalizeReferralCode(typedCode) } : {}),
        commissionPct: pct,
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      });
      setName("");
      setEmail("");
      setCode("");
      setCodeTouched(false);
      setCommission("");
      setNotes("");
      return `Sales agent ${created.name} created with referral code ${created.referralCode}.`;
    });
  };

  const onToggle = (agent: SalesAgent) => {
    const next = agent.status === "active" ? "inactive" : "active";
    void run(async () => {
      await updateSalesAgent(agent.id, { status: next });
      return next === "inactive"
        ? `${agent.name} deactivated — ${agent.referralCode} will no longer attribute new signups. Their earned history is unchanged.`
        : `${agent.name} reactivated — ${agent.referralCode} attributes new signups again.`;
    });
  };

  return (
    <div>
      <AdminPageHeader
        title="Sales agents"
        subtitle="Resellers, their referral codes, and the accounts those codes really brought in."
      />

      {notice ? (
        <p role="status" data-testid="admin-sales-agents-notice" className="mb-3 text-sm text-aether-green">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p role="alert" data-testid="admin-sales-agents-error" className="mb-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile label="Active agents" value={loading ? "—" : totals.active} />
        <StatTile
          label="Attributed signups"
          value={loading ? "—" : totals.signups}
          hint="Accounts that arrived through an agent's referral link."
        />
        <StatTile
          label="Converted to paid"
          value={loading ? "—" : totals.converted}
          hint="Counted only with a real Stripe subscription behind the plan."
        />
      </div>

      <Panel
        title="Register a sales agent"
        caption="The code is minted with a CSPRNG — a guessable code is an attribution someone else can claim."
        testId="admin-sales-agent-form"
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-xs text-aether-muted">
            Name
            <input
              aria-label="Agent name"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              className={`${FIELD} mt-1`}
            />
          </label>
          <label className="text-xs text-aether-muted">
            Email (optional)
            <input
              aria-label="Agent email (optional)"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={`${FIELD} mt-1`}
            />
          </label>
          <label className="text-xs text-aether-muted">
            Referral code
            <input
              aria-label="Referral code"
              value={code}
              onChange={(e) => {
                setCodeTouched(true);
                setCode(e.target.value);
              }}
              placeholder="left blank, the server mints one"
              className={`${FIELD} mono mt-1`}
            />
          </label>
          <label className="text-xs text-aether-muted">
            Commission %
            <input
              aria-label="Commission %"
              inputMode="decimal"
              value={commission}
              onChange={(e) => setCommission(e.target.value)}
              placeholder="0"
              className={`${FIELD} mt-1`}
            />
          </label>
          <label className="text-xs text-aether-muted sm:col-span-2">
            Notes (optional)
            <input
              aria-label="Notes (optional)"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className={`${FIELD} mt-1`}
            />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="admin-sales-agent-create"
            onClick={onCreate}
            disabled={busy}
            className={PRIMARY_BTN}
          >
            Create agent
          </button>
          <span className="type-meta">
            The code cannot be changed afterwards — it will already be printed on links
            the agent has handed out.
          </span>
        </div>
      </Panel>

      <div className="mt-4">
        <Panel title="Agents" caption="Counts are real rows, not estimates." testId="admin-sales-agents-list">
          {loading ? (
            <p className="text-sm text-aether-muted">Loading…</p>
          ) : agents.length === 0 ? (
            <p data-testid="admin-sales-agents-empty" className="text-sm text-aether-muted">
              No sales agents yet. Register one above and hand them their referral link —
              signups that arrive through it are attributed automatically.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-aether-muted-dim">
                  <tr>
                    <th className="py-2 pr-4">Agent</th>
                    <th className="py-2 pr-4">Referral link</th>
                    <th className="py-2 pr-4 text-right">Signups</th>
                    <th className="py-2 pr-4 text-right">Paid</th>
                    <th className="py-2 pr-4 text-right">Commission</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {agents.map((a) => {
                    const link = referralLink(a.referralCode);
                    const inactive = a.status !== "active";
                    return (
                      <tr key={a.id} data-testid={`admin-sales-agent-row-${a.id}`}>
                        <td className="py-2.5 pr-4 align-top">
                          <p className="text-aether-text">{a.name}</p>
                          <p className="type-meta">{a.email ?? "no email on file"}</p>
                          <p className="type-meta">since {formatDate(a.createdAt)}</p>
                        </td>
                        <td className="py-2.5 pr-4 align-top">
                          <div className="flex flex-wrap items-center gap-2">
                            <code
                              data-testid={`admin-sales-agent-link-${a.id}`}
                              className="mono break-all text-[11px] text-aether-text"
                            >
                              {link}
                            </code>
                            <CopyButton
                              value={link}
                              testId={`admin-sales-agent-copy-${a.id}`}
                              ariaLabel={`Copy ${a.name}'s referral link`}
                            />
                          </div>
                          {inactive ? (
                            <p className="type-meta mt-1 text-aether-amber">
                              This code is no longer attributing new signups.
                            </p>
                          ) : null}
                        </td>
                        <td
                          data-testid={`admin-sales-agent-signups-${a.id}`}
                          className="mono py-2.5 pr-4 text-right align-top tabular-nums text-aether-text"
                        >
                          {count(a.attributedSignups)}
                        </td>
                        <td
                          data-testid={`admin-sales-agent-converted-${a.id}`}
                          className="mono py-2.5 pr-4 text-right align-top tabular-nums text-aether-text"
                        >
                          {count(a.convertedPaid)}
                        </td>
                        <td className="mono py-2.5 pr-4 text-right align-top tabular-nums text-aether-text">
                          {a.commissionPct}%
                        </td>
                        <td className="py-2.5 pr-4 align-top">
                          <StatusPill
                            testId={`admin-sales-agent-status-${a.id}`}
                            state={a.status}
                            tone={inactive ? "neutral" : "good"}
                          >
                            {a.status}
                          </StatusPill>
                        </td>
                        <td className="py-2.5 pr-4 text-right align-top">
                          <div className="flex flex-wrap justify-end gap-2">
                            <Link
                              href={`/admin/sales-agents/${a.id}`}
                              className="text-xs text-aether-indigo hover:underline"
                            >
                              Report
                            </Link>
                            <button
                              type="button"
                              data-testid={`admin-sales-agent-toggle-${a.id}`}
                              onClick={() => onToggle(a)}
                              disabled={busy}
                              className={`${QUIET_BTN} px-2 py-1 text-xs`}
                            >
                              {inactive ? "Reactivate" : "Deactivate"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="type-meta mt-3 max-w-prose">
            Deactivation is the only removal: a code already in circulation keeps its
            earned history, and its link simply stops attributing new signups.
          </p>
        </Panel>
      </div>

      <p className="type-meta mt-4">
        Looking for the autonomous outreach agent instead?{" "}
        <Link
          href="/admin/sales-agent"
          data-testid="admin-sales-agents-native-link"
          className="text-aether-coral hover:underline"
        >
          Sales AI agent
        </Link>{" "}
        — the native in-app agent that works campaigns and leads, and sends real
        email whenever it is not in shadow mode. A separate system from the
        resellers on this page.
      </p>
    </div>
  );
}
