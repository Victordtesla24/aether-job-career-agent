"use client";

/**
 * ADMIN-2.0 FE-1 — the executive dashboard's OPERATIONAL STRIP.
 *
 * Three lists that turn the numbers above into something the owner can act on
 * in one click: who is bringing accounts in (sales agents), who arrived most
 * recently (linked straight to their user page), and what an admin last did
 * (the append-only audit trail).
 *
 * WHERE THE LAST TWO COME FROM. `GET /admin/metrics/executive` carries the
 * referrers but NOT the latest signups or the audit tail — so rather than ask
 * BE-2 to grow the payload, this strip reads the two endpoints the admin panel
 * already ships and already authorises: `GET /admin/users` (which carries
 * `signupAt` per row) and `GET /admin/audit-log`. No new backend surface, no
 * new permission, and the data is the same data /admin/users and
 * /admin/audit-log render.
 *
 * Each list has its own honest empty state rather than a shared one, because
 * "no sales agent has brought in an account yet" and "no admin action has been
 * recorded yet" are different facts and collapsing them into one grey "no
 * data" would lose the distinction.
 */
import Link from "next/link";

import { NOT_MEASURED } from "../../charts";
import type { ReferrerModel } from "../../../lib/admin/executive";
import { formatCount, formatPct } from "../../../lib/admin/executive";
import type { AdminUser, AuditEntry } from "../../../lib/api/admin";
import { formatDateTime } from "../../../lib/format";
import { InsufficientData, Panel } from "./panels";

export function ReferrersPanel({ model }: { model: ReferrerModel }) {
  return (
    <Panel
      testId="admin-exec-referrers"
      measured={model.measured}
      title="Top referrers"
      caption="sales agents, by accounts converted then referred"
    >
      {model.measured ? (
        <ul className="flex flex-col gap-2">
          {model.agents.map((agent) => (
            <li key={agent.id} className="flex items-baseline justify-between gap-3 text-[13px]">
              <span className="min-w-0 truncate text-aether-text">
                {agent.name ?? agent.id}
                {agent.referralCode ? (
                  <span className="type-mono-micro ml-2 text-aether-muted-dim">
                    {agent.referralCode}
                  </span>
                ) : null}
              </span>
              <span className="type-mono-micro flex shrink-0 items-baseline gap-3 text-aether-muted">
                <span title="accounts attributed to this referrer">
                  {typeof agent.attributedSignups === "number"
                    ? formatCount(agent.attributedSignups)
                    : NOT_MEASURED}{" "}
                  signups
                </span>
                <span title="attributed accounts that became paid">
                  {typeof agent.convertedPaid === "number"
                    ? formatCount(agent.convertedPaid)
                    : NOT_MEASURED}{" "}
                  paid
                </span>
                <span title="agreed commission rate">
                  {typeof agent.commissionPct === "number"
                    ? formatPct(agent.commissionPct * 100)
                    : NOT_MEASURED}
                </span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <InsufficientData
          reason={model.reason ?? "No referrer has been recorded yet."}
          nextStep="A referrer appears here once their link brings in its first account."
          compact
        />
      )}
    </Panel>
  );
}

export function LatestSignupsPanel({
  rows,
  error,
}: {
  rows: readonly AdminUser[];
  error: string | null;
}) {
  return (
    <Panel
      testId="admin-exec-latest-signups"
      measured={rows.length > 0}
      title="Latest signups"
      caption="most recently created accounts"
      action={
        <Link href="/admin/users" className="type-mono-micro text-aether-muted hover:text-aether-text">
          All users →
        </Link>
      }
    >
      {rows.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {rows.map((row) => (
            <li key={row.id}>
              {/* ONE link per row: the whole row is the target, so the
                  accessible name carries the name AND the email rather than
                  splitting one person across two competing links. */}
              <Link
                href={`/admin/users/${encodeURIComponent(row.id)}`}
                className="-mx-2 flex items-baseline justify-between gap-3 rounded-lg px-2 py-1.5 text-[13px] transition-colors hover:bg-white/[0.04]"
              >
                <span className="min-w-0 truncate text-aether-text">
                  {row.name?.trim() ? `${row.name} ` : ""}
                  <span className="text-aether-muted">{row.email}</span>
                </span>
                <span className="type-mono-micro shrink-0 text-aether-muted-dim">
                  {row.plan ?? "free"} · {formatDateTime(row.signupAt)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <InsufficientData
          reason={error ?? "No account has signed up yet."}
          compact
        />
      )}
    </Panel>
  );
}

export function RecentAuditPanel({
  rows,
  error,
}: {
  rows: readonly AuditEntry[];
  error: string | null;
}) {
  return (
    <Panel
      testId="admin-exec-audit"
      measured={rows.length > 0}
      title="Recent admin actions"
      caption="append-only audit trail"
      action={
        <Link
          href="/admin/audit-log"
          className="type-mono-micro text-aether-muted hover:text-aether-text"
        >
          View all →
        </Link>
      }
    >
      {rows.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {rows.map((row) => (
            <li key={row.id} className="flex items-baseline justify-between gap-3 text-[12px]">
              <span className="mono min-w-0 truncate text-aether-text" title={row.action}>
                {row.action}
              </span>
              <span className="type-mono-micro shrink-0 text-aether-muted-dim">
                {row.actorEmail ?? row.actorUserId} · {formatDateTime(row.createdAt)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <InsufficientData
          reason={error ?? "No admin action has been recorded yet."}
          compact
        />
      )}
    </Panel>
  );
}
