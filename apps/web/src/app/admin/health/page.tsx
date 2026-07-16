"use client";

/**
 * /admin/health — dedicated service/agent/cron/provider health overview (§15).
 */
import { AdminPageHeader } from "../../../components/admin/admin-shell";
import { HealthOverview } from "../../../components/admin/health-overview";

export default function AdminHealthPage() {
  return (
    <div>
      <AdminPageHeader
        title="System health"
        subtitle="Live service, agent-success-rate, cron and provider status."
      />
      <HealthOverview />
    </div>
  );
}
