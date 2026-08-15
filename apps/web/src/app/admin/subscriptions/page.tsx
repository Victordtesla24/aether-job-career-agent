"use client";

/**
 * /admin/subscriptions — subscription management (H-07, QA-v2, ADMIN-MGMT E2).
 *
 * Originally a read-only re-projection of `GET /admin/users` (see the history
 * below) because no subscription-specific backend existed. ADMIN-MGMT adds
 * three real actions on TOP of that same read: Cancel and Refund now call the
 * existing per-user billing routes straight from this list, and non-billable
 * rows get a "Delete record" action against the new
 * `DELETE /admin/users/{id}/subscription` route (stray Subscription +
 * UsageQuota rows for an account whose billing is not live). Nothing here
 * touches Stripe except Cancel/Refund, which already did.
 *
 * History: the QA v2 report flagged /admin/subscriptions as a 404 with no way
 * for an operator to see who is on which plan. This page reads the SAME admin
 * user list /admin/users uses (`GET /api/admin/users`, which already carries
 * per-user plan, subscription status, spend and run-count) and presents it
 * through a subscription lens. `view: "all"` is passed explicitly so a
 * suspended or soft-deleted account's billing state is still visible here even
 * though the Users screen's own default view now hides deleted rows — a
 * subscription that still needs cancelling does not stop existing because the
 * account was deleted. Spend is shown in US$ because LLM providers bill USD,
 * matching /admin/users and /admin/spend.
 *
 * Tabs are computed CLIENT-SIDE over that one payload (`subStatus` +
 * `suspended`, already on every row) rather than as a second query — cheap,
 * and it keeps the four tab counts consistent with each other by construction.
 * Tabs are independent filters, not a partition: a suspended account whose
 * Stripe status still reads "active" appears on both Paying and Suspended,
 * because both statements are true about it at once.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import { FIELD, QUIET_BTN } from "../../../components/admin/admin-ui";
import SegmentedControl from "../../../components/ui/SegmentedControl";
import { formatDate } from "../../../lib/format";
import {
  cancelUserSubscription,
  deleteSubscriptionRecord,
  fetchAdminUsers,
  formatUsd,
  refundUserSubscription,
  type AdminUser,
} from "../../../lib/api/admin";

const PLAN_ORDER = ["free", "starter", "pro", "power"] as const;

/** The same rule the server enforces on DELETE .../subscription (409 otherwise):
 *  a row is billable-live while it still carries one of these statuses. The
 *  client only has `subStatus` to go on (no `stripeSubscriptionId`), so this is
 *  advisory — it disables the button with an honest reason; the server's own
 *  409 is still what actually protects the data if this ever disagrees. */
const BILLABLE_LIVE_STATUSES = new Set(["active", "past_due", "trialing"]);

function isBillableLive(u: AdminUser): boolean {
  return Boolean(u.subStatus && BILLABLE_LIVE_STATUSES.has(u.subStatus));
}

function planLabel(plan: string | null): string {
  if (!plan) return "Free";
  return plan.charAt(0).toUpperCase() + plan.slice(1);
}

function statusTone(status: string | null): string {
  const s = (status ?? "").toLowerCase();
  if (s === "active") return "bg-aether-green/15 text-aether-green border-aether-green/25";
  if (s === "trialing") return "bg-aether-indigo/15 text-aether-indigo border-aether-indigo/25";
  if (s === "past_due" || s === "unpaid")
    return "bg-aether-amber/15 text-aether-amber border-aether-amber/25";
  if (s === "canceled" || s === "cancelled")
    return "bg-red-500/10 text-red-300 border-red-500/25";
  return "bg-white/5 text-aether-muted-dim border-white/10";
}

type SubTab = "paying" | "suspended" | "canceled" | "all";

/**
 * Typed-confirm dialog for `DELETE /admin/users/{id}/subscription`. Same idiom
 * as the account purge/soft-delete dialogs elsewhere in admin: type the
 * account's email, the server re-checks the guard that actually matters
 * (billable-live), and its 409 — if it disagrees with the client's advisory
 * check — reaches the admin verbatim.
 */
function DeleteSubscriptionModal({
  user,
  onClose,
  onDeleted,
}: {
  user: AdminUser;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirmDisabled = typed.trim().toLowerCase() !== user.email.trim().toLowerCase();

  const submit = async () => {
    if (confirmDisabled) return;
    setBusy(true);
    setError(null);
    try {
      const result = await deleteSubscriptionRecord(user.id);
      onDeleted();
      void result;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete this subscription record.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:items-center">
      <div
        data-testid="admin-delete-sub-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Delete subscription record"
        className="elev-3 w-full max-w-lg rounded-2xl p-5"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-aether-text">
              Delete the subscription record for {user.email}?
            </h2>
            <p className="type-meta mt-1 max-w-prose">
              Deletes the local Subscription and UsageQuota rows for this account
              only — no Stripe call is made, and nothing else about the account
              changes. Use this to clear stale local billing data once it is not
              live.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md border border-white/10 px-2 py-1 text-sm text-aether-muted hover:text-white"
          >
            ✕
          </button>
        </div>

        {error ? (
          <p role="alert" data-testid="admin-delete-sub-error" className="mb-3 text-sm text-red-300">
            {error}
          </p>
        ) : null}

        <label className="text-xs text-aether-muted">
          Type the account&apos;s email address to confirm
          <input
            aria-label="Type the email address to confirm deleting the subscription record"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={user.email}
            className={`${FIELD} mt-1`}
          />
        </label>

        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy} className={QUIET_BTN}>
            Cancel
          </button>
          <button
            type="button"
            data-testid="admin-delete-sub-confirm"
            onClick={() => void submit()}
            disabled={busy || confirmDisabled}
            className="rounded-md bg-red-500/20 px-4 py-2 text-sm font-medium text-red-300 transition-colors hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Deleting…" : "Delete record"}
          </button>
        </div>
      </div>
    </div>
  );
}

const VALID_TABS: readonly SubTab[] = ["paying", "suspended", "canceled", "all"];

/** `?tab=canceled` off `window.location.search` (no `useSearchParams` → no
 *  Suspense boundary needed, matching the rest of this app's query-param
 *  pages, e.g. /admin/users' `view`). SSR-safe. */
function initialTabFromLocation(): SubTab {
  if (typeof window === "undefined") return "paying";
  const t = new URLSearchParams(window.location.search).get("tab");
  return (VALID_TABS as readonly string[]).includes(t ?? "") ? (t as SubTab) : "paying";
}

export default function AdminSubscriptionsPage() {
  // Deep-link support: the admin home page's "Stale data" panel links here as
  // `?tab=canceled`. Read once at mount, same pattern as /admin/users' `view`.
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [plan, setPlan] = useState("");
  const [tab, setTab] = useState<SubTab>(initialTabFromLocation);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // `view: "all"` — a subscription still needs managing even on a
      // suspended or soft-deleted account.
      const res = await fetchAdminUsers({ ...(plan ? { plan } : {}), view: "all" });
      setRows(res.users);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load subscriptions");
    } finally {
      setLoading(false);
    }
  }, [plan]);

  useEffect(() => {
    void load();
  }, [load]);

  const buckets = useMemo(() => {
    const paying = rows.filter(
      (u) => u.subStatus === "active" || u.subStatus === "past_due",
    );
    const suspended = rows.filter((u) => u.suspended);
    const canceled = rows.filter(
      (u) => u.subStatus === "canceled" || u.subStatus === "cancelled",
    );
    return { paying, suspended, canceled, all: rows };
  }, [rows]);

  const visible = buckets[tab];

  // Plan-mix summary — always over the FULL loaded set (not the tab), so it
  // reads as "everyone on this plan filter" rather than shifting with tabs.
  const planCounts = useMemo(() => {
    const counts: Record<string, number> = { free: 0, starter: 0, pro: 0, power: 0 };
    for (const u of rows) {
      const key = (u.plan ?? "free").toLowerCase();
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [rows]);

  const paidCount = useMemo(
    () => rows.filter((u) => (u.plan ?? "free").toLowerCase() !== "free").length,
    [rows],
  );

  const withBusy = async (userId: string, action: () => Promise<unknown>, successMessage: string) => {
    setBusyId(userId);
    setActionError(null);
    setActionMessage(null);
    try {
      await action();
      setActionMessage(successMessage);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "That action could not be completed.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <AdminPageHeader
        title="Subscriptions"
        subtitle="Every account's plan, subscription status and usage. Spend is US$ (LLM providers bill USD)."
      />

      {/* Plan-mix summary */}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
          <p className="text-xs uppercase tracking-wide text-aether-muted-dim">Paid</p>
          <p className="mt-1 text-2xl font-semibold text-aether-text">{paidCount}</p>
        </div>
        {PLAN_ORDER.map((p) => (
          <div key={p} className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
            <p className="text-xs uppercase tracking-wide text-aether-muted-dim">{planLabel(p)}</p>
            <p className="mt-1 text-2xl font-semibold text-aether-text">{planCounts[p] ?? 0}</p>
          </div>
        ))}
      </div>

      <SegmentedControl
        ariaLabel="Filter subscriptions by status"
        idPrefix="admin-subs-tab"
        testId="admin-subs-tabs"
        className="mb-4"
        value={tab}
        onChange={(next) => setTab(next)}
        items={[
          { value: "paying", label: "Paying", count: buckets.paying.length },
          { value: "suspended", label: "Suspended", count: buckets.suspended.length },
          { value: "canceled", label: "Canceled", count: buckets.canceled.length },
          { value: "all", label: "All", count: buckets.all.length },
        ]}
      />

      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <label className="flex flex-col text-xs text-aether-muted">
          Plan
          <select
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
            className="mt-1 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text"
          >
            <option value="">All plans</option>
            {PLAN_ORDER.map((p) => (
              <option key={p} value={p}>
                {planLabel(p)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="rounded-md bg-aether-indigo px-4 py-2 text-sm font-medium text-white hover:bg-aether-indigo/90"
        >
          Apply
        </button>
      </form>

      {error ? <p className="mb-3 text-sm text-red-300">{error}</p> : null}
      {actionMessage ? (
        <p role="status" className="mb-3 text-sm text-aether-green">
          {actionMessage}
        </p>
      ) : null}
      {actionError ? (
        <p role="alert" className="mb-3 text-sm text-red-300">
          {actionError}
        </p>
      ) : null}

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-aether-bg-elevated text-left text-xs uppercase tracking-wide text-aether-muted-dim">
            <tr>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Plan</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Runs</th>
              <th className="px-4 py-3 text-right">LLM spend (US$)</th>
              <th className="px-4 py-3">Signed up</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {visible.map((u) => {
              const busy = busyId === u.id;
              const billableLive = isBillableLive(u);
              const canCancel = !u.isAdmin && billableLive;
              return (
                <tr key={u.id} data-testid={`admin-sub-row-${u.id}`} className="hover:bg-white/5">
                  <td className="px-4 py-3 text-aether-text">
                    <div className="font-medium">{u.name || "—"}</div>
                    <div className="text-xs text-aether-muted">{u.email}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-md bg-white/5 px-2 py-0.5 text-xs text-aether-text">
                      {planLabel(u.plan)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full border px-2.5 py-1 text-xs ${statusTone(u.subStatus)}`}
                    >
                      {u.subStatus ?? "—"}
                    </span>
                    {u.suspended ? (
                      <span className="ml-1.5 rounded-full border border-aether-amber/40 bg-aether-amber/10 px-2 py-0.5 text-[11px] text-aether-amber">
                        suspended
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-aether-muted">{u.runCount}</td>
                  <td className="px-4 py-3 text-right font-mono text-aether-text">
                    {formatUsd(u.spendUsd)}
                  </td>
                  <td className="px-4 py-3 text-aether-muted">{formatDate(u.signupAt)}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        data-testid={`admin-sub-cancel-${u.id}`}
                        disabled={busy || !canCancel}
                        title={
                          u.isAdmin
                            ? "Administrator accounts are exempt from plans — there is no subscription to cancel."
                            : !billableLive
                              ? `No live subscription to cancel (status: ${u.subStatus ?? "none"}).`
                              : "Cancels at the end of the current paid period."
                        }
                        onClick={() =>
                          void withBusy(
                            u.id,
                            () => cancelUserSubscription(u.id, true),
                            "Subscription set to cancel at the end of the paid period.",
                          )
                        }
                        className="text-xs text-aether-amber hover:underline disabled:cursor-not-allowed disabled:text-aether-muted-dim disabled:no-underline"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        data-testid={`admin-sub-refund-${u.id}`}
                        disabled={busy || u.isAdmin}
                        title={
                          u.isAdmin
                            ? "Administrator accounts are exempt from plans — there is nothing to refund."
                            : "Refunds this account's latest paid charge and revokes it to Free."
                        }
                        onClick={() =>
                          void withBusy(
                            u.id,
                            () => refundUserSubscription(u.id),
                            "Latest paid charge refunded; the account was revoked to Free.",
                          )
                        }
                        className="text-xs text-red-300 hover:underline disabled:cursor-not-allowed disabled:text-aether-muted-dim disabled:no-underline"
                      >
                        Refund
                      </button>
                      <button
                        type="button"
                        data-testid={`admin-sub-delete-record-${u.id}`}
                        disabled={busy || billableLive}
                        title={
                          billableLive
                            ? `Cancel the subscription first — this account's billing still looks live (status: ${u.subStatus}).`
                            : "Deletes the local Subscription and UsageQuota rows for this account. No Stripe call."
                        }
                        onClick={() => setDeleteTarget(u)}
                        className="text-xs text-aether-muted hover:text-red-300 hover:underline disabled:cursor-not-allowed disabled:text-aether-muted-dim disabled:no-underline"
                      >
                        Delete record
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {!loading && visible.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-aether-muted">
                  No subscriptions match this filter.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-aether-muted-dim">
        {loading ? "Loading..." : `${visible.length} of ${total} accounts loaded`}
      </p>

      {deleteTarget ? (
        <DeleteSubscriptionModal
          user={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={() => {
            setDeleteTarget(null);
            setActionMessage("Subscription record deleted.");
            void load();
          }}
        />
      ) : null}
    </div>
  );
}
