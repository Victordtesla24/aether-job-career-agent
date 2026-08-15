"use client";

/**
 * /admin/users — user list with filters + LLM spend in US$ (§15 Tier 1).
 * Columns: name, email, plan, last-login, signup date, LLM spend (USD).
 *
 * ADMIN-2.0 FE-2 adds the ADD-USER flow. The whole design of that modal follows
 * from one property of `POST /admin/users`: it returns a generated temporary
 * password EXACTLY ONCE. The API hashes it, never stores the plaintext, never
 * writes it to the audit row, and exposes no route that can read it back — so
 * the modal cannot treat that value as something it can fetch again. It shows
 * the credential on its own step, says plainly that it is shown once, gives a
 * copy button that reports whether the copy actually happened, and requires a
 * deliberate acknowledgement to dismiss. The remedy if it is lost (set a new
 * password from the user's own page) is stated there rather than left to be
 * discovered.
 *
 * ADMIN-MGMT E2 — TRUTHFUL LIFECYCLE VIEWS. A soft-deleted account used to stay
 * in this list forever, flagged. That was honest about the delete not being an
 * erasure, but it also meant the default screen an operator opens every day
 * accumulates every account anyone has ever deleted. The default view is now
 * `active` (`deletedAt IS NULL` — a suspended-but-not-deleted account is still
 * "active" by this definition and still shows here, flagged with its own
 * pill) — the screen an operator actually wants day to day — with
 * Suspended / Deleted / All as explicit tabs, each carrying its own count so
 * nothing is silently hidden, only DEFAULT-hidden. The Deleted tab is where a
 * soft-deleted row now lives, with Restore (reverses the soft delete) and
 * "Purge permanently" (hard-deletes the account and all its data — step TWO,
 * only reachable once step one already happened) sitting right on the row
 * that needs them.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import {
  CopyButton,
  FIELD,
  PRIMARY_BTN,
  QUIET_BTN,
  StatusPill,
} from "../../../components/admin/admin-ui";
import SegmentedControl from "../../../components/ui/SegmentedControl";
import { formatDate } from "../../../lib/format";
import {
  createAdminUser,
  fetchAdminUsers,
  formatUsd,
  purgeUser,
  restoreAdminUser,
  type AdminUser,
  type AdminUserCounts,
  type AdminUserView,
  type CreatedUser,
  type UserFilters,
} from "../../../lib/api/admin";

const EMPTY_COUNTS: AdminUserCounts = { active: 0, suspended: 0, deleted: 0 };

const PLANS = ["", "free", "starter", "pro", "power"];

/**
 * The add-user modal. Two steps, deliberately: a form, then the credential.
 * They are never on screen together, so the moment the password exists it is
 * the only thing the admin is being asked to deal with.
 */
function AddUserModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  /** Called when the admin acknowledges the credential — the list reloads then. */
  onCreated: () => void;
}) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedUser | null>(null);

  const submit = async () => {
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !trimmedEmail.includes("@")) {
      setError("Enter the new user's email address.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await createAdminUser({
        email: trimmedEmail,
        // An empty display name is absence, not a blank name — don't send it.
        ...(name.trim() ? { name: name.trim() } : {}),
      });
      setCreated(result);
    } catch (e) {
      // The backend's own sentence ("That email is already registered.") is
      // more useful than anything this layer could invent.
      setError(e instanceof Error ? e.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:items-center">
      <div
        data-testid="admin-add-user-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Add user"
        className="elev-3 w-full max-w-lg rounded-2xl p-5"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-aether-text">
              {created ? "Account created" : "Add user"}
            </h2>
            <p className="type-meta mt-1">
              {created
                ? "Hand these credentials to the new user."
                : "Creates an ordinary account. Administrator access is never granted here."}
            </p>
          </div>
          {/* No dismiss affordance exists once the credential is on screen —
              the only way past it is the acknowledgement below. */}
          {created ? null : (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md border border-white/10 px-2 py-1 text-sm text-aether-muted hover:text-white"
            >
              ✕
            </button>
          )}
        </div>

        {error ? (
          <p role="alert" data-testid="admin-add-user-error" className="mb-3 text-sm text-red-300">
            {error}
          </p>
        ) : null}

        {created ? (
          <div>
            <dl className="mb-3 grid grid-cols-3 gap-y-2 text-sm">
              <dt className="text-aether-muted">Email</dt>
              <dd className="col-span-2 text-aether-text">{created.email}</dd>
              <dt className="text-aether-muted">Name</dt>
              <dd className="col-span-2 text-aether-text">{created.name || "—"}</dd>
            </dl>

            <p className="type-section mb-1.5">Temporary password</p>
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-aether-amber/40 bg-aether-amber/[0.06] p-3">
              <code
                data-testid="admin-temp-password"
                className="mono min-w-0 flex-1 break-all text-sm text-aether-text"
              >
                {created.tempPassword}
              </code>
              <CopyButton
                value={created.tempPassword}
                testId="admin-temp-password-copy"
                ariaLabel="Copy the temporary password"
              />
            </div>
            <p data-testid="admin-temp-password-warning" className="type-meta mt-2 max-w-prose">
              Shown once. It is stored only as a hash — it is not written to the audit
              log and cannot be retrieved from anywhere, by anyone, after you close
              this. If it is lost, set a new password from this user&apos;s page instead.
            </p>
            <p className="type-meta mt-1 max-w-prose text-aether-muted-dim">
              The account is flagged as still using an admin-generated password until
              the user sets one of their own.
            </p>

            <div className="mt-4 flex justify-end">
              <button
                type="button"
                data-testid="admin-add-user-done"
                onClick={onCreated}
                className={PRIMARY_BTN}
              >
                I&apos;ve saved the password
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <label className="text-xs text-aether-muted">
              Email
              <input
                aria-label="New user email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={`${FIELD} mt-1`}
              />
            </label>
            <label className="text-xs text-aether-muted">
              Name (optional)
              <input
                aria-label="New user name (optional)"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={`${FIELD} mt-1`}
              />
            </label>
            <div className="mt-1 flex justify-end gap-2">
              <button type="button" onClick={onClose} className={QUIET_BTN}>
                Cancel
              </button>
              <button
                type="button"
                data-testid="admin-add-user-submit"
                onClick={() => void submit()}
                disabled={busy}
                className={PRIMARY_BTN}
              >
                {busy ? "Creating…" : "Create account"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Purge confirmation — a HARD delete, so it gets its own dialog rather than
 * the inline `ConfirmPanel` the soft-delete on the detail page uses. Typing
 * the account's email is the same guard as soft-delete; the copy here spells
 * out the two things a hard delete adds over a soft one: it cannot be undone,
 * and the billing audit trail (unlike everything else) survives it.
 */
function PurgeUserModal({
  user,
  onClose,
  onPurged,
}: {
  user: AdminUser;
  onClose: () => void;
  /** Called once the server confirms the purge — the list reloads then. */
  onPurged: () => void;
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
      await purgeUser(user.id, typed.trim());
      onPurged();
    } catch (e) {
      // 409/422 guards are honest instructions ("Cancel the Stripe
      // subscription first…", "Soft-delete the account first…") — show them
      // verbatim rather than inventing a summary.
      setError(e instanceof Error ? e.message : "Could not purge this account.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:items-center">
      <div
        data-testid="admin-purge-user-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Purge account permanently"
        className="elev-3 w-full max-w-lg rounded-2xl p-5"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-aether-text">
              Purge {user.email} permanently?
            </h2>
            <p className="type-meta mt-1 max-w-prose">
              This hard-deletes the account and every row keyed to it — jobs,
              applications, runs, everything. It cannot be undone. The billing
              audit trail (this action itself included) is the one thing that is
              kept.
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
          <p role="alert" data-testid="admin-purge-user-error" className="mb-3 text-sm text-red-300">
            {error}
          </p>
        ) : null}

        <label className="text-xs text-aether-muted">
          Type the account&apos;s email address to confirm
          <input
            aria-label="Type the email address to confirm purge"
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
            data-testid="admin-purge-user-confirm"
            onClick={() => void submit()}
            disabled={busy || confirmDisabled}
            className="rounded-md bg-red-500/20 px-4 py-2 text-sm font-medium text-red-300 transition-colors hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Purging…" : "Purge permanently"}
          </button>
        </div>
      </div>
    </div>
  );
}

const VALID_VIEWS: readonly AdminUserView[] = ["active", "suspended", "deleted", "all"];

/** `?view=deleted` off `window.location.search` (no `useSearchParams` → no
 *  Suspense boundary needed, matching the rest of this app's query-param
 *  pages). SSR-safe: `window` is absent on the server, so this resolves to
 *  the honest default there. */
function initialViewFromLocation(): AdminUserView {
  if (typeof window === "undefined") return "active";
  const v = new URLSearchParams(window.location.search).get("view");
  return (VALID_VIEWS as readonly string[]).includes(v ?? "") ? (v as AdminUserView) : "active";
}

export default function AdminUsersPage() {
  // Deep-link support: the admin home page's "Stale data" panel links here as
  // `?view=deleted`. Read once at mount — this page's own tabs are the source
  // of truth after that, matching the rest of admin's (lack of) URL sync.
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<AdminUserCounts>(EMPTY_COUNTS);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [plan, setPlan] = useState("");
  const [view, setView] = useState<AdminUserView>(initialViewFromLocation);
  const [addOpen, setAddOpen] = useState(false);

  // Row-scoped actions on the Deleted tab. Only one busy at a time, since
  // both hit the same account and firing them together would race.
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<AdminUser | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const filters: UserFilters = { view };
    if (q.trim()) filters.q = q.trim();
    if (plan) filters.plan = plan;
    try {
      const res = await fetchAdminUsers(filters);
      setRows(res.users);
      setTotal(res.total);
      setCounts(res.counts);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, [q, plan, view]);

  useEffect(() => {
    void load();
  }, [load]);

  const restore = async (u: AdminUser) => {
    setRestoringId(u.id);
    setRestoreError(null);
    try {
      await restoreAdminUser(u.id);
      await load();
    } catch (e) {
      setRestoreError(e instanceof Error ? e.message : "Could not restore this account.");
    } finally {
      setRestoringId(null);
    }
  };

  return (
    <div>
      <AdminPageHeader
        title="Users"
        subtitle="Accounts with plan, activity and LLM spend (US$ — LLM providers bill USD)."
      />

      <SegmentedControl
        ariaLabel="Filter users by lifecycle state"
        idPrefix="admin-users-view"
        testId="admin-users-view-tabs"
        className="mb-4"
        value={view}
        onChange={(next) => setView(next)}
        items={[
          { value: "active", label: "Active", count: counts.active },
          { value: "suspended", label: "Suspended", count: counts.suspended },
          { value: "deleted", label: "Deleted", count: counts.deleted },
          { value: "all", label: "All", count: counts.active + counts.suspended + counts.deleted },
        ]}
      />

      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void load();
          }}
        >
          {/* ADMIN-FULL: the backend's `q` filter also matches `username` (a real
              login identity), so the hint below names all three fields it searches. */}
          <label className="flex flex-col text-xs text-aether-muted">
            Search
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="email, username or name"
              className="mt-1 w-56 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text placeholder:text-aether-muted-dim"
            />
          </label>
          <label className="flex flex-col text-xs text-aether-muted">
            Plan
            <select
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
              className="mt-1 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm text-aether-text"
            >
              {PLANS.map((p) => (
                <option key={p} value={p}>
                  {p === "" ? "All plans" : p}
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

        <button
          type="button"
          data-testid="admin-add-user"
          onClick={() => setAddOpen(true)}
          className={PRIMARY_BTN}
        >
          Add user
        </button>
      </div>

      {error ? <p className="mb-3 text-sm text-red-300">{error}</p> : null}
      {restoreError ? (
        <p role="alert" className="mb-3 text-sm text-red-300">
          {restoreError}
        </p>
      ) : null}

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-aether-bg-elevated text-left text-xs uppercase tracking-wide text-aether-muted-dim">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Plan</th>
              <th className="px-4 py-3">Last login</th>
              <th className="px-4 py-3">Signed up</th>
              <th className="px-4 py-3 text-right">LLM spend (US$)</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {rows.map((u) => (
              <tr key={u.id} data-testid={`admin-user-row-${u.id}`} className="hover:bg-white/5">
                <td className="px-4 py-3 text-aether-text">
                  <span className="mr-2">{u.name || "—"}</span>
                  <span className="inline-flex flex-wrap gap-1 align-middle">
                    {u.isAdmin ? <StatusPill tone="accent">admin</StatusPill> : null}
                    {/* Deleted first: it is the strongest fact about the row, and
                        a soft-deleted account is always suspended too, so the
                        suspension pill alone would under-state it. */}
                    {u.deletedAt ? (
                      <StatusPill tone="critical" title={`Soft-deleted ${u.deletedAt}`}>
                        deleted
                      </StatusPill>
                    ) : u.suspended ? (
                      <StatusPill tone="warn">suspended</StatusPill>
                    ) : null}
                  </span>
                </td>
                <td className="px-4 py-3 text-aether-muted">{u.email}</td>
                <td className="px-4 py-3 text-aether-muted">{u.plan ?? "—"}</td>
                <td className="px-4 py-3 text-aether-muted">{formatDate(u.lastLoginAt)}</td>
                <td className="px-4 py-3 text-aether-muted">{formatDate(u.signupAt)}</td>
                <td className="px-4 py-3 text-right font-mono text-aether-text">
                  {formatUsd(u.spendUsd)}
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="inline-flex items-center justify-end gap-3">
                    {/* Restore/Purge are ONLY meaningful on a soft-deleted row —
                        gated on the row's own state, not on which tab is open,
                        so a deleted row found via the All tab gets them too. */}
                    {u.deletedAt ? (
                      <>
                        <button
                          type="button"
                          data-testid={`admin-restore-user-${u.id}`}
                          onClick={() => void restore(u)}
                          disabled={restoringId === u.id}
                          className="text-xs text-aether-green hover:underline disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {restoringId === u.id ? "Restoring…" : "Restore"}
                        </button>
                        <button
                          type="button"
                          data-testid={`admin-purge-user-${u.id}`}
                          onClick={() => setPurgeTarget(u)}
                          className="text-xs text-red-300 hover:underline"
                        >
                          Purge permanently
                        </button>
                      </>
                    ) : null}
                    <Link
                      href={`/admin/users/${u.id}`}
                      className="text-xs text-aether-indigo hover:underline"
                    >
                      View
                    </Link>
                  </span>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-aether-muted">
                  {view === "active"
                    ? "No active users match these filters."
                    : view === "suspended"
                      ? "No suspended users match these filters."
                      : view === "deleted"
                        ? "No deleted users match these filters."
                        : "No users match these filters."}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-aether-muted-dim">
        {loading ? "Loading…" : `${rows.length} of ${total} users`}
      </p>

      {addOpen ? (
        <AddUserModal
          onClose={() => setAddOpen(false)}
          onCreated={() => {
            setAddOpen(false);
            void load();
          }}
        />
      ) : null}

      {purgeTarget ? (
        <PurgeUserModal
          user={purgeTarget}
          onClose={() => setPurgeTarget(null)}
          onPurged={() => {
            setPurgeTarget(null);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}
