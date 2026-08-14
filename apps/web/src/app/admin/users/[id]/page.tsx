"use client";

/**
 * /admin/users/[id] — the admin user-management panel (ADMIN-FULL).
 *
 * USER MANDATE (2026-08-14): an admin can change the plan, subscription,
 * username and password of ANY user. Everything on this page is a thin client
 * over an `AdminUser`-gated backend route; the backend is the enforcement point
 * and the audit writer, and this page renders that trail back for the same user.
 *
 * WHAT THE CONTROLS ARE, HONESTLY
 * -------------------------------
 * * "Entitlement" is an IN-APP override (comp / tier / unlimited). It is
 *   immediate and Stripe-independent, so it is labelled as an override wherever
 *   it is active — never dressed up as a payment. `Real billing` beside it keeps
 *   showing what Stripe actually says, so the two facts are never conflated.
 * * "Subscription" actions touch a REAL Stripe subscription and route through
 *   the app's existing billing service (cancel-at-period-end / the existing
 *   admin-refund path). A user with no Stripe subscription gets an honest 409
 *   back, which is surfaced verbatim rather than swallowed.
 * * "Credentials" sets a password (hashed server-side, never displayed or
 *   logged, existing sessions invalidated) or changes email/username, both
 *   uniqueness-checked server-side.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../../components/admin/admin-shell";
import { formatDateTime } from "../../../../lib/format";
import {
  cancelUserSubscription,
  fetchAdminUser,
  fetchUserAuditLog,
  formatUsd,
  refundUserSubscription,
  setEntitlementOverride,
  setSpendCap,
  setSuspended,
  setUserPassword,
  updateUserIdentity,
  type AdminUserDetail,
  type AuditEntry,
  type EntitlementOverrideKind,
} from "../../../../lib/api/admin";

const OVERRIDE_PLANS = ["free", "starter", "pro", "power"] as const;

function Panel({
  title,
  children,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4"
    >
      <p className="mb-3 text-xs uppercase tracking-wide text-aether-muted-dim">{title}</p>
      {children}
    </div>
  );
}

const FIELD =
  "w-full rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text";
const PRIMARY_BTN =
  "rounded-md bg-aether-indigo px-4 py-2 text-sm font-medium text-white hover:bg-aether-indigo/90 disabled:opacity-50";
const QUIET_BTN =
  "rounded-md border border-white/15 px-4 py-2 text-sm font-medium text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50";

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const userId = params?.id ?? "";
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [capInput, setCapInput] = useState("");
  const [busy, setBusy] = useState(false);

  // Entitlement override form
  const [overrideKind, setOverrideKind] = useState<EntitlementOverrideKind>("none");
  const [overridePlan, setOverridePlan] = useState<string>("pro");
  const [overrideNote, setOverrideNote] = useState("");

  // Credentials forms
  const [newPassword, setNewPassword] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [usernameInput, setUsernameInput] = useState("");
  const [nameInput, setNameInput] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await fetchAdminUser(userId);
      setDetail(d);
      if (d.quota) setCapInput(String(d.quota.spendCapUsd));
      setEmailInput(d.user.email);
      setUsernameInput(d.user.username ?? "");
      setNameInput(d.user.name ?? "");
      const kind = d.entitlement?.overrideKind;
      setOverrideKind(
        kind === "comp" || kind === "tier" || kind === "unlimited" ? kind : "none",
      );
      if (d.entitlement?.overridePlanId) setOverridePlan(d.entitlement.overridePlanId);
      setOverrideNote(d.entitlement?.overrideNote ?? "");
      try {
        setAudit((await fetchUserAuditLog(userId)).entries);
      } catch {
        // The trail is supplementary: a failure here must not blank the page.
        setAudit([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load user");
    }
  }, [userId]);

  useEffect(() => {
    if (userId) void load();
  }, [userId, load]);

  /** Run one admin mutation with shared busy/notice/error handling. */
  const run = useCallback(
    async (action: () => Promise<void>, successMessage: string) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        await action();
        setNotice(successMessage);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  const onSaveCap = () => {
    const value = Number(capInput);
    if (capInput.trim() === "" || !Number.isFinite(value) || value < 0) {
      setError("Spend cap must be a non-negative number (US$).");
      return;
    }
    void run(async () => {
      await setSpendCap(userId, value);
    }, `Spend cap set to ${formatUsd(value)}.`);
  };

  const onToggleSuspend = () => {
    if (!detail) return;
    const next = !detail.user.suspended;
    void run(async () => {
      await setSuspended(userId, next);
    }, next ? "User suspended." : "User unsuspended.");
  };

  const onSaveEntitlement = () => {
    const needsPlan = overrideKind === "comp" || overrideKind === "tier";
    void run(
      async () => {
        await setEntitlementOverride(userId, {
          kind: overrideKind,
          ...(needsPlan ? { planId: overridePlan } : {}),
          ...(overrideNote.trim() ? { note: overrideNote.trim() } : {}),
        });
      },
      overrideKind === "none"
        ? "Entitlement override cleared — this user is back on their real plan."
        : `Entitlement override saved (${overrideKind}).`,
    );
  };

  const onSetPassword = () => {
    if (!newPassword) {
      setError("Enter the new password.");
      return;
    }
    void run(async () => {
      await setUserPassword(userId, newPassword);
      setNewPassword("");
    }, "Password set. This user's existing sessions were invalidated.");
  };

  const onSaveIdentity = () => {
    if (!detail) return;
    const patch: { email?: string; username?: string; name?: string } = {};
    if (emailInput.trim() && emailInput.trim() !== detail.user.email) {
      patch.email = emailInput.trim();
    }
    if (usernameInput.trim() !== (detail.user.username ?? "")) {
      patch.username = usernameInput.trim();
    }
    if (nameInput.trim() !== (detail.user.name ?? "")) patch.name = nameInput.trim();
    if (Object.keys(patch).length === 0) {
      setError("Nothing to change.");
      return;
    }
    void run(async () => {
      await updateUserIdentity(userId, patch);
    }, "Identity updated.");
  };

  const onCancelSubscription = (atPeriodEnd: boolean) => {
    void run(
      async () => {
        await cancelUserSubscription(userId, atPeriodEnd);
      },
      atPeriodEnd
        ? "Subscription set to cancel at the end of the paid period."
        : "Subscription cancelled and the account revoked to Free.",
    );
  };

  const onRefund = () => {
    void run(async () => {
      await refundUserSubscription(userId);
    }, "Latest paid charge refunded; the account was revoked to Free.");
  };

  if (error && !detail) return <p className="text-sm text-red-300">{error}</p>;
  if (!detail) return <p className="text-sm text-aether-muted">Loading…</p>;

  const u = detail.user;
  const ent = detail.entitlement;
  const unlimited = ent?.unlimited === true;
  const overrideActive = ent?.overrideActive === true;

  return (
    <div>
      <AdminPageHeader title={u.name || u.email} subtitle={u.email} />

      {notice ? (
        <p role="status" className="mb-3 text-sm text-aether-green" data-testid="admin-user-notice">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mb-3 text-sm text-red-300" data-testid="admin-user-error">
          {error}
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Account">
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-aether-muted">Plan</dt>
            <dd className="text-aether-text">{u.plan ?? "—"}</dd>
            <dt className="text-aether-muted">Username</dt>
            <dd className="text-aether-text">{u.username ?? "—"}</dd>
            <dt className="text-aether-muted">Status</dt>
            <dd className="text-aether-text">{u.suspended ? "suspended" : "active"}</dd>
            <dt className="text-aether-muted">Admin</dt>
            <dd className="text-aether-text">{u.isAdmin ? "yes" : "no"}</dd>
            <dt className="text-aether-muted">Signed up</dt>
            <dd className="text-aether-text">{formatDateTime(u.signupAt)}</dd>
            <dt className="text-aether-muted">Last login</dt>
            <dd className="text-aether-text">{formatDateTime(u.lastLoginAt)}</dd>
            <dt className="text-aether-muted">Total LLM spend</dt>
            <dd className="font-mono text-aether-text">{formatUsd(detail.spendUsd)} US$</dd>
            <dt className="text-aether-muted">Runs</dt>
            <dd className="text-aether-text">{detail.runCount}</dd>
          </dl>
        </Panel>

        <Panel title="Entitlement (what the server actually enforces)" testId="admin-entitlement">
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-aether-muted">Enforced as</dt>
            <dd className="text-aether-text" data-testid="admin-entitlement-state">
              {unlimited ? "Unlimited — no quota, cap or paywall" : `Plan limits (${ent?.planId ?? u.plan ?? "free"})`}
            </dd>
            <dt className="text-aether-muted">Source</dt>
            <dd className="text-aether-text">{ent?.source ?? "plan"}</dd>
            <dt className="text-aether-muted">Real billing</dt>
            <dd className="text-aether-text" data-testid="admin-entitlement-billing">
              {ent?.activePaid ? "active paid subscription" : "no active paid subscription"}
            </dd>
          </dl>
          {overrideActive ? (
            <p
              data-testid="admin-entitlement-override-flag"
              className="mt-3 rounded-lg border border-aether-amber/40 bg-aether-amber/10 p-2.5 text-xs text-aether-amber"
            >
              Admin override active ({ent?.overrideKind}
              {ent?.overridePlanId ? ` → ${ent.overridePlanId}` : ""}) — set by{" "}
              {ent?.overrideSetBy ?? "an admin"} on {formatDateTime(ent?.overrideSetAt ?? null)}.
              This is an in-app grant, not a payment.
              {ent?.overrideNote ? ` Note: ${ent.overrideNote}` : ""}
            </p>
          ) : null}
          {u.isAdmin ? (
            /* Precedence in app/services/entitlements.resolve: isAdmin wins over
               any override. Say so rather than let an admin set a grant here and
               believe it changed something. */
            <p
              data-testid="admin-entitlement-is-admin-note"
              className="mt-3 text-xs text-aether-muted-dim"
            >
              This account is an administrator, so it is unlimited by the admin
              flag alone — an entitlement override would have no additional
              effect while that flag is set.
            </p>
          ) : null}
        </Panel>

        <Panel title="Change entitlement (in-app, immediate)" testId="admin-entitlement-form">
          <p className="mb-2 text-xs text-aether-muted">
            An override changes what Aether enforces for this user right away. It never
            charges, refunds or edits Stripe — use the subscription actions for that.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-aether-muted">
              Kind
              <select
                aria-label="Entitlement kind"
                value={overrideKind}
                onChange={(e) => setOverrideKind(e.target.value as EntitlementOverrideKind)}
                className={`${FIELD} mt-1`}
              >
                <option value="none">none (use their real plan)</option>
                <option value="comp">comp (complimentary plan)</option>
                <option value="tier">tier (grant plan limits)</option>
                <option value="unlimited">unlimited</option>
              </select>
            </label>
            {overrideKind === "comp" || overrideKind === "tier" ? (
              <label className="text-xs text-aether-muted">
                Plan
                <select
                  aria-label="Override plan"
                  value={overridePlan}
                  onChange={(e) => setOverridePlan(e.target.value)}
                  className={`${FIELD} mt-1`}
                >
                  {OVERRIDE_PLANS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <label className="min-w-[12rem] flex-1 text-xs text-aether-muted">
              Note (recorded in the audit trail)
              <input
                aria-label="Override note"
                value={overrideNote}
                onChange={(e) => setOverrideNote(e.target.value)}
                className={`${FIELD} mt-1`}
              />
            </label>
            <button
              type="button"
              data-testid="admin-save-entitlement"
              onClick={onSaveEntitlement}
              disabled={busy}
              className={PRIMARY_BTN}
            >
              Save entitlement
            </button>
          </div>
        </Panel>

        <Panel title="Subscription & quota">
          {detail.quota ? (
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-aether-muted">Runs used</dt>
              <dd className="text-aether-text">
                {detail.quota.runsUsed} / {detail.quota.runsAllowed}
              </dd>
              <dt className="text-aether-muted">Spend used</dt>
              <dd className="font-mono text-aether-text">{formatUsd(detail.quota.spendUsedUsd)}</dd>
              <dt className="text-aether-muted">Spend cap</dt>
              <dd className="font-mono text-aether-text">{formatUsd(detail.quota.spendCapUsd)}</dd>
              <dt className="text-aether-muted">Period ends</dt>
              <dd className="text-aether-text">{formatDateTime(detail.quota.periodEnd)}</dd>
            </dl>
          ) : (
            <p className="text-sm text-aether-muted">No quota row.</p>
          )}
          {unlimited ? (
            <p className="mt-3 text-xs text-aether-muted-dim">
              These figures are recorded for accounting only — this account is unlimited, so
              no run counter or cap is enforced against it.
            </p>
          ) : null}
        </Panel>

        <Panel title="Stripe subscription actions" testId="admin-subscription-actions">
          <p className="mb-2 text-xs text-aether-muted">
            These act on a REAL Stripe subscription through Aether&apos;s billing service. A
            user without one is refused — grant an entitlement override instead.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              data-testid="admin-cancel-at-period-end"
              onClick={() => onCancelSubscription(true)}
              disabled={busy}
              className={QUIET_BTN}
            >
              Cancel at period end
            </button>
            <button
              type="button"
              data-testid="admin-cancel-now"
              onClick={() => onCancelSubscription(false)}
              disabled={busy}
              className={QUIET_BTN}
            >
              Cancel now (revoke to Free)
            </button>
            <button
              type="button"
              data-testid="admin-refund"
              onClick={onRefund}
              disabled={busy}
              className="rounded-md bg-red-500/20 px-4 py-2 text-sm font-medium text-red-300 hover:bg-red-500/30 disabled:opacity-50"
            >
              Refund latest charge
            </button>
          </div>
          {detail.subscription ? (
            <p className="mt-3 text-xs text-aether-muted-dim">
              {detail.subscription.planId} · {detail.subscription.status}
              {detail.subscription.cancelAtPeriodEnd ? " · cancels at period end" : ""}
            </p>
          ) : null}
        </Panel>

        <Panel title="Spend cap (US$)">
          <p className="mb-2 text-xs text-aether-muted">
            Enforced before every metered agent run — a run is blocked with 429 once
            accumulated spend reaches the cap.
          </p>
          <div className="flex items-center gap-2">
            <span className="text-aether-muted">US$</span>
            <input
              aria-label="Spend cap in US dollars"
              value={capInput}
              onChange={(e) => setCapInput(e.target.value)}
              inputMode="decimal"
              className="w-32 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text"
            />
            <button type="button" onClick={onSaveCap} disabled={busy} className={PRIMARY_BTN}>
              Save cap
            </button>
          </div>
        </Panel>

        <Panel title="Credentials — password" testId="admin-password-panel">
          <p className="mb-2 text-xs text-aether-muted">
            Hashed server-side with the app&apos;s own hasher. The value is never stored in
            the clear, never shown again and never written to the audit log — and every
            existing session for this user is invalidated immediately.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="password"
              aria-label="New password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-56 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text"
            />
            <button
              type="button"
              data-testid="admin-set-password"
              onClick={onSetPassword}
              disabled={busy}
              className={PRIMARY_BTN}
            >
              Set password
            </button>
          </div>
        </Panel>

        <Panel title="Credentials — email, username, name" testId="admin-identity-panel">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <label className="text-xs text-aether-muted">
              Email
              <input
                aria-label="Email"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                className={`${FIELD} mt-1`}
              />
            </label>
            <label className="text-xs text-aether-muted">
              Username
              <input
                aria-label="Username"
                value={usernameInput}
                onChange={(e) => setUsernameInput(e.target.value)}
                className={`${FIELD} mt-1`}
              />
            </label>
            <label className="text-xs text-aether-muted">
              Display name
              <input
                aria-label="Display name"
                value={nameInput}
                onChange={(e) => setNameInput(e.target.value)}
                className={`${FIELD} mt-1`}
              />
            </label>
          </div>
          <button
            type="button"
            data-testid="admin-save-identity"
            onClick={onSaveIdentity}
            disabled={busy}
            className={`${PRIMARY_BTN} mt-3`}
          >
            Save identity
          </button>
        </Panel>

        <Panel title="Suspension">
          <p className="mb-2 text-xs text-aether-muted">
            A suspended user is refused (403) on every authenticated route until reinstated.
          </p>
          <button
            type="button"
            onClick={onToggleSuspend}
            disabled={busy}
            className={`rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50 ${
              u.suspended
                ? "bg-aether-green/20 text-aether-green hover:bg-aether-green/30"
                : "bg-red-500/20 text-red-300 hover:bg-red-500/30"
            }`}
          >
            {u.suspended ? "Unsuspend user" : "Suspend user"}
          </button>
        </Panel>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4">
        <Panel title="Admin audit trail for this user" testId="admin-user-audit">
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-aether-muted-dim">
                <tr>
                  <th className="py-2 pr-4">When</th>
                  <th className="py-2 pr-4">Action</th>
                  <th className="py-2 pr-4">Actor</th>
                  <th className="py-2 pr-4">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {audit.map((e) => (
                  <tr key={e.id}>
                    <td className="py-2 pr-4 text-aether-muted">{formatDateTime(e.createdAt)}</td>
                    <td className="py-2 pr-4 text-aether-text">{e.action}</td>
                    <td className="py-2 pr-4 text-aether-muted">
                      {e.actorEmail ?? e.actorUserId}
                    </td>
                    <td className="max-w-md truncate py-2 pr-4 font-mono text-[11px] text-aether-muted-dim">
                      {e.detail ? JSON.stringify(e.detail) : "—"}
                    </td>
                  </tr>
                ))}
                {audit.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="py-4 text-center text-aether-muted">
                      No admin actions recorded for this user yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-aether-muted-dim">
            Append-only. Password changes record the event, never the value. The full
            platform log lives at{" "}
            <Link href="/admin/audit-log" className="text-aether-coral hover:underline">
              /admin/audit-log
            </Link>
            .
          </p>
        </Panel>

        <Panel title="Recent runs">
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-aether-muted-dim">
                <tr>
                  <th className="py-2 pr-4">Agent</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4 text-right">Cost (US$)</th>
                  <th className="py-2 pr-4">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {detail.recentRuns.map((r) => (
                  <tr key={r.id}>
                    <td className="py-2 pr-4 text-aether-text">{r.agentName}</td>
                    <td className="py-2 pr-4 text-aether-muted">{r.status}</td>
                    <td className="py-2 pr-4 text-right font-mono text-aether-text">
                      {formatUsd(r.costUsd)}
                    </td>
                    <td className="py-2 pr-4 text-aether-muted">{formatDateTime(r.createdAt)}</td>
                  </tr>
                ))}
                {detail.recentRuns.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="py-4 text-center text-aether-muted">
                      No runs yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
