"use client";

/**
 * /admin — admin landing: the health overview plus quick links (§15 Tier 1).
 */
import Link from "next/link";

import { AdminPageHeader } from "../../components/admin/admin-shell";
import { HealthOverview } from "../../components/admin/health-overview";

const LINKS: Array<{ href: string; label: string; desc: string }> = [
  { href: "/admin/users", label: "Users", desc: "Accounts, plans & LLM spend" },
  { href: "/admin/spend", label: "Spend (US$)", desc: "Total & per-user LLM spend" },
  { href: "/admin/settings", label: "Settings", desc: "Signup & verification toggles" },
  { href: "/admin/audit-log", label: "Audit log", desc: "Append-only admin actions" },
];

export default function AdminOverviewPage() {
  return (
    <div>
      <AdminPageHeader title="Admin overview" subtitle="Service health and platform controls." />
      <HealthOverview />
      <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4 transition-colors hover:border-aether-indigo/40"
          >
            <p className="text-sm font-medium text-aether-text">{l.label}</p>
            <p className="mt-1 text-xs text-aether-muted">{l.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
