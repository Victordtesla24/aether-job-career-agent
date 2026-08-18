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
 *
 * ADMIN-2.0 FE-2 adds three more, each with its own honesty rule:
 *
 * * "Billing truth" shows the LOCAL `Subscription` row and STRIPE side by side.
 *   They can disagree — the owner account is the live proof (a stale `pro/active`
 *   row with nothing cancellable behind it) — and merging them into one figure
 *   would hide the very discrepancy an admin is here to resolve. "Stripe could
 *   not be read" is a THIRD state, never rendered as "Stripe has nothing".
 * * "Reconcile local" clears a stale row in OUR database and makes no Stripe
 *   call at all. It is offered only where the backend can actually perform it.
 * * "Delete" is SOFT and says so: `deletedAt` plus a suspension, with the
 *   account's work and audit history preserved, reversible with Restore. The
 *   admin/owner refusal is a server guard; this page surfaces that 409 rather
 *   than pretending a hidden button is the protection.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../../components/admin/admin-shell";
import {
  ConfirmPanel,
  StatusPill,
  formatAudExact,
} from "../../../../components/admin/admin-ui";
import { ApiError } from "../../../../lib/api/client";
import { formatDateTime } from "../../../../lib/format";
import {
  cancelUserSubscription,
  deleteAdminUser,
  fetchAdminUser,
  fetchUserAuditLog,
  formatUsd,
  refundUserSubscription,
  restoreAdminUser,
  setEntitlementOverride,
  setSpendCap,
  setSuspended,
  setUserPassword,
  updateUserIdentity,
  type AdminUserDetail,
  type AuditEntry,
  type EntitlementOverrideKind,
} from "../../../../lib/api/admin";
import {
  fetchUserBilling,
  reconcileLocalBilling,
  setCustomPrice,
  type AdminUserBilling,
} from "../../../../lib/api/adminBilling";

const OVERRIDE_PLANS = ["free", "starter", "pro", "power"] as const;

/** Mirrors `admin_billing.BILLABLE_STATUSES` — "really on the hook" locally. */
const BILLABLE_STATUSES = ["active", "trialing", "past_due"];
/** Mirrors `stripe_gateway.LIVE_SUBSCRIPTION_STATUSES`. */
const LIVE_STRIPE_STATUSES = [
  "active",
  "trialing",
  "past_due",
  "unpaid",
  "incomplete",
  "paused",
];

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

  // Billing truth (ADMIN-2.0). Loaded alongside the account but failing
  // independently: a Stripe outage must not blank the page it sits on.
  const [billing, setBilling] = useState<AdminUserBilling | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [reconcileOpen, setReconcileOpen] = useState(false);
  const [priceAmount, setPriceAmount] = useState("");
  const [priceInterval, setPriceInterval] = useState<"month" | "year">("month");

  // Delete flow
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");

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
      try {
        const b = await fetchUserBilling(userId);
        setBilling(b);
        setBillingError(null);
        // Seed the negotiated-price field from whatever is really charged today,
        // so the admin edits a number rather than retyping one from memory.
        const current = b.local?.customPrice?.amountAud ?? b.stripe.subscription?.amountAud;
        if (typeof current === "number") setPriceAmount(String(current));
        const interval = b.local?.customPrice?.interval ?? b.stripe.subscription?.interval;
        if (interval === "month" || interval === "year") setPriceInterval(interval);
      } catch (e) {
        // Same rule as the audit trail: this panel failing must not take the
        // account with it. The reason is shown IN the panel, not swallowed.
        setBilling(null);
        setBillingError(e instanceof Error ? e.message : "Failed to load billing");
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
    // An action may RETURN its own notice when the honest wording depends on
    // what the API reported back (e.g. whether sessions were really
    // invalidated); ``successMessage`` is the fixed fallback.
    async (action: () => Promise<string | void>, successMessage: string) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        const outcome = await action();
        setNotice(typeof outcome === "string" ? outcome : successMessage);
        await load();
      } catch (e) {
        // A 409 is the backend REFUSING honestly (nothing to cancel, §14.7
        // owner-password rule, ...) — word it as a refusal with the server's
        // own explanation, never as a generic failure.
        if (e instanceof ApiError && e.status === 409) {
          setError(`Not applicable: ${e.message}`);
        } else {
          setError(e instanceof Error ? e.message : "Action failed");
        }
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
      const result = await setUserPassword(userId, newPassword);
      setNewPassword("");
      // Repeat what the API measured. It waits out the JWT iat grace window so
      // this is normally true, but a false must never be dressed up as a
      // lockout that did not happen.
      return result.sessionsInvalidated
        ? "Password set. This user's existing sessions were invalidated."
        : "Password set — but session invalidation could not be confirmed (API/database clock skew). Existing sessions for this user may still be live.";
    }, "Password set.");
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

  const onReconcileLocal = () => {
    setReconcileOpen(false);
    void run(async () => {
      const result = await reconcileLocalBilling(userId);
      // Report which Stripe answer authorised the clear, and that nothing was
      // written to Stripe — the two facts that make this action safe.
      const checked =
        result.stripeChecked === "no_customer_on_file"
          ? "no Stripe customer was on file"
          : result.stripeChecked === "customer_not_found_at_stripe"
            ? "the recorded Stripe customer does not exist at Stripe"
            : "Stripe showed no live subscription";
      return `Local subscription row cleared to Free — ${checked}, and no Stripe object was changed.`;
    }, "Local subscription row cleared.");
  };

  const onSaveCustomPrice = () => {
    const amount = Number(priceAmount);
    if (priceAmount.trim() === "" || !Number.isFinite(amount) || amount <= 0) {
      setError("The negotiated amount must be a number greater than 0 (AUD).");
      return;
    }
    void run(async () => {
      const result = await setCustomPrice(userId, {
        amountAud: Math.round(amount * 100) / 100,
        interval: priceInterval,
      });
      return (
        `Repriced to ${formatAudExact(result.amountAud)} per ${result.interval} — ` +
        "the existing subscription was changed in place with no proration, so no " +
        "charge, credit or refund was raised. It applies from the next renewal."
      );
    }, "Negotiated price saved.");
  };

  const onDeleteUser = () => {
    const typed = deleteConfirm.trim();
    void run(async () => {
      const result = await deleteAdminUser(userId, typed);
      setDeleteOpen(false);
      setDeleteConfirm("");
      return (
        `Account soft-deleted${result.deletedAt ? ` at ${formatDateTime(result.deletedAt)}` : ""}: ` +
        "it is suspended and hidden from normal use, its jobs, applications, runs " +
        "and audit history are preserved, and it is reversible with Restore."
      );
    }, "Account soft-deleted (reversible with Restore).");
  };

  const onRestoreUser = () => {
    void run(async () => {
      const result = await restoreAdminUser(userId);
      // Restore deliberately does NOT lift the suspension. Never imply it did.
      return result.suspended
        ? "Account restored — it is still suspended. Lift the suspension deliberately below."
        : "Account restored.";
    }, "Account restored.");
  };

  if (error && !detail) return <p className="text-sm text-red-300">{error}</p>;
  if (!detail) return <p className="text-sm text-aether-muted">Loading…</p>;

  const u = detail.user;
  const ent = detail.entitlement;
  const unlimited = ent?.unlimited === true;
  const overrideActive = ent?.overrideActive === true;
  const deleted = Boolean(u.deletedAt);

  // ---- Billing truth, derived exactly as the backend derives it ------------
  const local = billing?.local ?? null;
  const truth = billing?.stripe ?? null;
  const mismatchState: "match" | "mismatch" | "not-evaluated" = !billing
    ? "not-evaluated"
    : !billing.mismatch.evaluated
      ? "not-evaluated"
      : billing.mismatch.hasMismatch
        ? "mismatch"
        : "match";
  const stripeHasLive = Boolean(
    truth?.available &&
      (truth.subscriptions ?? []).some((s) => LIVE_STRIPE_STATUSES.includes(s.status ?? "")),
  );
  /** A row worth reconciling at all: paid-looking, or pointing at a subscription. */
  const staleCandidate = Boolean(
    local && ((local.planId ?? "free") !== "free" || local.stripeSubscriptionId),
  );
  /**
   * Only offer reconcile where the backend can actually perform it (the
   * 29ea6bc rule: never present a control whose only possible outcome is a
   * refusal). The backend consults Stripe first and its answer is binding — a
   * live subscription is a 409, and an unreadable Stripe with a customer on
   * file is a 503 — so both of those cases are explained instead of offered.
   */
  const needsStripeAnswer = Boolean(local?.stripeCustomerId);
  const canReconcile =
    staleCandidate && (!needsStripeAnswer || Boolean(truth?.available && !stripeHasLive));
  /** Repricing needs a live LOCAL subscription id in a billable status. */
  const canReprice = Boolean(
    local?.stripeSubscriptionId && BILLABLE_STATUSES.includes(local?.status ?? ""),
  );

  return (
    <div>
      <AdminPageHeader title={u.name || u.email} subtitle={u.email} />

      {deleted ? (
        <div
          data-testid="admin-user-deleted-banner"
          className="mb-4 rounded-xl border border-red-500/40 bg-red-500/[0.07] p-3"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-red-200">
                This account is deleted (soft) — deleted {formatDateTime(u.deletedAt)}.
              </p>
              <p className="type-meta mt-1 max-w-prose">
                It is suspended and cannot be used, while its jobs, applications, runs
                and audit history are preserved. Restoring returns the record; it does
                not lift the suspension.
              </p>
            </div>
            <button
              type="button"
              data-testid="admin-restore-user"
              onClick={onRestoreUser}
              disabled={busy}
              className={PRIMARY_BTN}
            >
              Restore account
            </button>
          </div>
        </div>
      ) : null}

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
          {u.isAdmin ? (
            /* Administrator/owner accounts are exempt from plans by design
               (entitlements.resolve: isAdmin wins), so there is never a Stripe
               subscription here — offering Cancel would only ever produce the
               backend's honest 409 refusal. */
            <p data-testid="admin-sub-exempt" className="text-sm text-aether-muted">
              This is an administrator account — it is exempt from plans and
              subscriptions, so there is no Stripe subscription to cancel or
              refund.
            </p>
          ) : detail.subscription ? (
            <>
              <p className="mb-2 text-xs text-aether-muted">
                These act on the user&apos;s REAL Stripe subscription through
                Aether&apos;s billing service.
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
              <p className="mt-3 text-xs text-aether-muted-dim">
                {detail.subscription.planId} · {detail.subscription.status}
                {detail.subscription.cancelAtPeriodEnd ? " · cancels at period end" : ""}
              </p>
            </>
          ) : (
            <>
              <p data-testid="admin-sub-none" className="text-sm text-aether-muted">
                No Stripe subscription on this account — plan access is
                controlled by the Entitlement override above. A past paid charge
                can still be refunded.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
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
            </>
          )}
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
          {detail.passwordManaged ? (
            /* RT-001: this identity's password is deployment-managed — offering
               the control here was a dead affordance that ended in a 409 on
               submit. State it upfront, professionally, and offer nothing. */
            <p
              className="text-xs text-aether-muted"
              data-testid="admin-password-managed-note"
            >
              This account&apos;s password is managed at the deployment level and
              can&apos;t be changed from the admin console. Contact your operator to
              rotate it.
            </p>
          ) : (
            <>
              <p className="mb-2 text-xs text-aether-muted">
                Hashed server-side with the app&apos;s own hasher. The value is never stored in
                the clear, never shown again and never written to the audit log. Every existing
                session for this user is invalidated before this call returns — it waits out the
                token-timestamp grace window (about a second) so that is true, not assumed.
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
            </>
          )}
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

      {/* ------------------------------------------------------------------ *
       * BILLING TRUTH. Two columns because there are genuinely two sources of
       * truth, and the panel's job is to show whether they agree — not to pick
       * one and present it as "the subscription".
       * ------------------------------------------------------------------ */}
      <div className="mt-4">
        <Panel title="Billing truth — local row vs Stripe" testId="admin-billing-panel">
          {billingError ? (
            <p data-testid="admin-billing-error" className="text-sm text-red-300">
              Could not load the billing surface: {billingError}. Nothing on this
              panel is being shown from cache or guessed — retry, or check Stripe
              directly.
            </p>
          ) : !billing ? (
            <p className="text-sm text-aether-muted">Loading billing…</p>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <StatusPill
                  testId="admin-billing-mismatch"
                  state={mismatchState}
                  tone={
                    mismatchState === "match"
                      ? "good"
                      : mismatchState === "mismatch"
                        ? "warn"
                        : "neutral"
                  }
                  title={
                    mismatchState === "not-evaluated"
                      ? "Stripe could not be read, so no comparison was made."
                      : undefined
                  }
                >
                  {mismatchState === "match"
                    ? "Match"
                    : mismatchState === "mismatch"
                      ? "Mismatch"
                      : "Not compared"}
                </StatusPill>
                <span className="type-meta">
                  {mismatchState === "match"
                    ? "The local row and Stripe agree."
                    : mismatchState === "mismatch"
                      ? "The local row and Stripe disagree — see the reasons below."
                      : "Stripe could not be read, so no comparison was performed. This is not a claim that Stripe holds nothing."}
                </span>
              </div>

              {mismatchState === "mismatch" ? (
                <ul
                  data-testid="admin-billing-mismatch-reasons"
                  className="mb-3 list-disc space-y-1 rounded-xl border border-aether-amber/40 bg-aether-amber/[0.06] py-2 pl-8 pr-3 text-xs text-aether-amber"
                >
                  {billing.mismatch.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : null}

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div data-testid="admin-billing-local" className="min-w-0">
                  <p className="type-section mb-2">This database (Subscription row)</p>
                  {local ? (
                    <dl className="grid grid-cols-2 gap-y-1.5 text-sm">
                      <dt className="text-aether-muted">Plan</dt>
                      <dd className="text-aether-text">{local.planId ?? "—"}</dd>
                      <dt className="text-aether-muted">Status</dt>
                      <dd className="text-aether-text">{local.status ?? "—"}</dd>
                      <dt className="text-aether-muted">Interval</dt>
                      <dd className="text-aether-text">{local.billingInterval ?? "—"}</dd>
                      <dt className="text-aether-muted">Stripe customer</dt>
                      <dd className="mono break-all text-[11px] text-aether-text">
                        {local.stripeCustomerId ?? "—"}
                      </dd>
                      <dt className="text-aether-muted">Stripe subscription</dt>
                      <dd className="mono break-all text-[11px] text-aether-text">
                        {local.stripeSubscriptionId ?? "—"}
                      </dd>
                      <dt className="text-aether-muted">Period ends</dt>
                      <dd className="text-aether-text">
                        {formatDateTime(local.currentPeriodEnd)}
                        {local.cancelAtPeriodEnd ? " · cancels then" : ""}
                      </dd>
                      <dt className="text-aether-muted">Row updated</dt>
                      <dd className="text-aether-text">{formatDateTime(local.updatedAt)}</dd>
                    </dl>
                  ) : (
                    <p className="text-sm text-aether-muted">
                      No local subscription row for this account.
                    </p>
                  )}
                </div>

                <div data-testid="admin-billing-stripe" className="min-w-0">
                  <p className="type-section mb-2">Stripe (live)</p>
                  {!truth?.available ? (
                    <p
                      data-testid="admin-billing-stripe-unavailable"
                      className="rounded-lg border border-white/10 bg-white/[0.02] p-2.5 text-xs text-aether-amber"
                    >
                      Stripe could not be read: {truth?.reason ?? "no reason reported."} Nothing
                      below is inferred in its place.
                    </p>
                  ) : truth.customer ? (
                    <dl className="grid grid-cols-2 gap-y-1.5 text-sm">
                      <dt className="text-aether-muted">Customer</dt>
                      <dd className="mono break-all text-[11px] text-aether-text">
                        {truth.customer.id ?? "—"}
                      </dd>
                      <dt className="text-aether-muted">Email at Stripe</dt>
                      <dd className="break-all text-aether-text">{truth.customer.email ?? "—"}</dd>
                      <dt className="text-aether-muted">Subscription</dt>
                      <dd className="text-aether-text">
                        {truth.subscription
                          ? `${truth.subscription.status ?? "—"}${
                              truth.subscription.amountAud !== null
                                ? ` · ${formatAudExact(truth.subscription.amountAud)}/${truth.subscription.interval ?? "?"}`
                                : ""
                            }`
                          : "none"}
                      </dd>
                      <dt className="text-aether-muted">Live subscriptions</dt>
                      <dd className="mono text-aether-text tabular-nums">
                        {(truth.subscriptions ?? []).filter((s) =>
                          LIVE_STRIPE_STATUSES.includes(s.status ?? ""),
                        ).length}
                      </dd>
                      <dt className="text-aether-muted">Payment method</dt>
                      <dd className="text-aether-text">
                        {truth.paymentMethod?.last4
                          ? `${truth.paymentMethod.brand ?? "card"} ···· ${truth.paymentMethod.last4}` +
                            (truth.paymentMethod.expMonth && truth.paymentMethod.expYear
                              ? ` (exp ${truth.paymentMethod.expMonth}/${truth.paymentMethod.expYear})`
                              : "")
                          : "none on file"}
                      </dd>
                      <dt className="text-aether-muted">Invoices</dt>
                      <dd className="mono text-aether-text tabular-nums">
                        {(truth.invoices ?? []).length}
                      </dd>
                      {truth.customer.delinquent ? (
                        <>
                          <dt className="text-aether-muted">Delinquent</dt>
                          <dd className="text-aether-amber">yes</dd>
                        </>
                      ) : null}
                    </dl>
                  ) : (
                    <p className="text-sm text-aether-muted">
                      {truth.note ??
                        "Stripe holds no customer for this account. (This IS Stripe's answer, not a failed read.)"}
                    </p>
                  )}
                </div>
              </div>

              <div className="mt-4 border-t border-white/5 pt-3">
                {canReconcile ? (
                  <>
                    <button
                      type="button"
                      data-testid="admin-billing-reconcile"
                      onClick={() => setReconcileOpen(true)}
                      disabled={busy}
                      className={QUIET_BTN}
                    >
                      Reconcile local row
                    </button>
                    {reconcileOpen ? (
                      <ConfirmPanel
                        testId="admin-billing-reconcile-confirm-panel"
                        confirmTestId="admin-billing-reconcile-confirm"
                        cancelTestId="admin-billing-reconcile-cancel"
                        title="Clear the local subscription row?"
                        confirmLabel="Clear the local row"
                        busy={busy}
                        onConfirm={onReconcileLocal}
                        onCancel={() => setReconcileOpen(false)}
                        body={
                          <>
                            This edits ONLY this database: the local row is set back to
                            Free and any negotiated price on it is cleared. No Stripe
                            call is made — nothing is cancelled, charged or refunded at
                            Stripe, and the customer is not notified. The server checks
                            Stripe first and refuses if a live subscription exists.
                          </>
                        }
                      />
                    ) : null}
                  </>
                ) : (
                  <p data-testid="admin-billing-reconcile-na" className="type-meta max-w-prose">
                    {!staleCandidate
                      ? "Nothing to reconcile: the local row is already Free with no Stripe subscription attached."
                      : stripeHasLive
                        ? "Not reconcilable: Stripe shows a live subscription for this customer, so the local row is correct rather than stale. Cancel or refund it instead."
                        : "Not reconcilable right now: Stripe could not be read, and this account has a Stripe customer on file. Clearing the row without Stripe's answer could destroy a live customer's record."}
                  </p>
                )}
              </div>
            </>
          )}
        </Panel>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Negotiated price (AUD)" testId="admin-custom-price">
          {local?.customPrice?.amountAud ? (
            <p
              data-testid="admin-custom-price-current"
              className="mb-3 rounded-lg border border-aether-indigo/40 bg-aether-indigo/[0.08] p-2.5 text-xs text-aether-text"
            >
              Currently {formatAudExact(local.customPrice.amountAud)} per{" "}
              {local.customPrice.interval ?? "period"} — set{" "}
              {formatDateTime(local.customPrice.setAt)}
              {local.customPrice.setBy ? ` by ${local.customPrice.setBy}` : ""}.
            </p>
          ) : null}

          {canReprice ? (
            <>
              <p className="mb-2 text-xs text-aether-muted">
                Reprices the customer&apos;s EXISTING subscription in place. No second
                subscription is opened, no proration is applied, and no charge, credit
                or refund is raised — the amount takes effect at the next renewal. No
                GST line is added (the operator is not GST-registered).
              </p>
              <div className="flex flex-wrap items-end gap-2">
                <label className="text-xs text-aether-muted">
                  Amount (AUD)
                  <input
                    aria-label="Custom amount (AUD)"
                    inputMode="decimal"
                    value={priceAmount}
                    onChange={(e) => setPriceAmount(e.target.value)}
                    className={`${FIELD} mt-1 w-32`}
                  />
                </label>
                <label className="text-xs text-aether-muted">
                  Interval
                  <select
                    aria-label="Billing interval"
                    value={priceInterval}
                    onChange={(e) => setPriceInterval(e.target.value === "year" ? "year" : "month")}
                    className={`${FIELD} mt-1`}
                  >
                    <option value="month">per month</option>
                    <option value="year">per year</option>
                  </select>
                </label>
                <button
                  type="button"
                  data-testid="admin-custom-price-save"
                  onClick={onSaveCustomPrice}
                  disabled={busy}
                  className={PRIMARY_BTN}
                >
                  Save negotiated price
                </button>
              </div>
            </>
          ) : (
            <p data-testid="admin-custom-price-na" className="text-sm text-aether-muted">
              This account has no live Stripe subscription to reprice. A negotiated
              price only exists as a change to a real subscription — to grant access
              without one, use the entitlement override above.
            </p>
          )}
        </Panel>

        <Panel title="Delete account" testId="admin-danger-zone">
          {deleted ? (
            <p className="text-sm text-aether-muted">
              Already deleted (soft) — use Restore at the top of this page to reverse
              it. There is no hard delete: every job, application, run and audit row
              references this account, and destroying them is not something this panel
              can undo.
            </p>
          ) : (
            <>
              <p className="mb-2 text-xs text-aether-muted">
                A soft delete: the account is stamped deleted and suspended, so it
                really cannot be used, while its work and audit history are preserved.
                Reversible with Restore. Administrator accounts and the owner identity
                are refused by the server.
              </p>
              {deleteOpen ? (
                <ConfirmPanel
                  tone="critical"
                  testId="admin-delete-user-panel"
                  confirmTestId="admin-delete-user-confirm"
                  cancelTestId="admin-delete-user-cancel"
                  title={`Delete ${u.email}?`}
                  confirmLabel="Delete this account"
                  busy={busy}
                  confirmDisabled={
                    deleteConfirm.trim().toLowerCase() !== u.email.trim().toLowerCase()
                  }
                  onConfirm={onDeleteUser}
                  onCancel={() => {
                    setDeleteOpen(false);
                    setDeleteConfirm("");
                  }}
                  body={
                    <>
                      Type the account&apos;s email address to confirm. The server checks
                      it too, so a mis-routed link cannot delete the wrong person.
                    </>
                  }
                >
                  <input
                    aria-label="Type the email address to confirm deletion"
                    value={deleteConfirm}
                    onChange={(e) => setDeleteConfirm(e.target.value)}
                    placeholder={u.email}
                    className={`${FIELD} mt-2`}
                  />
                </ConfirmPanel>
              ) : (
                <button
                  type="button"
                  data-testid="admin-delete-user"
                  onClick={() => setDeleteOpen(true)}
                  disabled={busy}
                  className="rounded-md bg-red-500/20 px-4 py-2 text-sm font-medium text-red-300 hover:bg-red-500/30 disabled:opacity-50"
                >
                  Delete account…
                </button>
              )}
            </>
          )}
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
            <Link href="/admin/audit-log" className="text-gold hover:underline">
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
