import { AdminGuard } from "../../components/admin/admin-guard";
import { AdminShell } from "../../components/admin/admin-shell";

/**
 * Shell for every /admin/* route (GAP-P6-ADMIN-001). Admin-only: AdminGuard
 * resolves `isAdmin` from /auth/me and redirects non-admins (the backend
 * `AdminUser` gate is the real enforcement — GATE-17).
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminGuard>
      <AdminShell>{children}</AdminShell>
    </AdminGuard>
  );
}
