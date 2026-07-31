import { AdminGuard } from "../../components/admin/admin-guard";
import { AdminShell } from "../../components/admin/admin-shell";

/**
 * Shell for every /admin/* route (GAP-P6-ADMIN-001). Admin-only: AdminGuard
 * resolves `isAdmin` from /auth/me and redirects non-admins (the backend
 * `AdminUser` gate is the real enforcement — GATE-17).
 *
 * The GOLD-MASTER-V2 §9.2.1/§9.2.2 admin sign-in entry point deliberately
 * lives OUTSIDE this tree, at /admin-login (not /admin/login) — see that
 * route's own file header for why nesting it under /admin/* is wrong both
 * architecturally (it would need to bypass this very guard, since a visitor
 * arriving there is by definition not yet authenticated) and functionally
 * (wg-admin-login-path.spec.ts's `waitForURL(/\/admin(\/|$|\?)/)` would
 * match the entry page's own URL before the post-login redirect ever fires,
 * since "/admin/login" contains the "/admin/" substring the regex is
 * matching on).
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminGuard>
      <AdminShell>{children}</AdminShell>
    </AdminGuard>
  );
}
