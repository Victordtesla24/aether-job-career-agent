import { AuthGuard } from "@/components/auth-guard";
import { AppShell } from "@/components/shell/AppShell";
import { SubscriptionGate } from "@/components/subscription-gate";
import { getOperatorLegalConfig } from "@/lib/config/legal";

// O-1 (S-FIX slice C): read AETHER_SUPPORT_EMAIL at request time (never
// build-baked) so the rail's "Contact support" link reflects the live
// process environment, matching /dashboard/settings and the legal pages.
export const dynamic = "force-dynamic";

/**
 * Shell layout shared by every /dashboard/* route. The frame itself —
 * rail, command bar, mobile nav sheet, mobile tab bar and the shell-root
 * `MotionConfig` — lives in `components/shell/AppShell.tsx` (S-UI-REBUILD
 * §1), which is a client component because the hamburger's state and the
 * single shared `GET /billing/subscription` have to be held somewhere both
 * the rail and the sheet can read.
 *
 * The gating is unchanged: the whole shell sits behind AuthGuard — no
 * session, no workspace (SC-AUTH-03) — and behind SubscriptionGate: without
 * an active paid subscription the routed page is replaced by the "Subscribe
 * to unlock Aether" paywall (GAP-P6-PAYWALL). The gate self-exempts
 * account-management routes (/dashboard/settings) so a free user can always
 * view and manage/cancel their own subscription (MV-pricing-003 /
 * MV-settings-003); it fails CLOSED if entitlement can't be verified
 * (MV-agent-monitor-004). See subscription-gate.tsx.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { supportEmail } = getOperatorLegalConfig();
  return (
    <AuthGuard>
      <AppShell supportEmail={supportEmail}>
        <SubscriptionGate>{children}</SubscriptionGate>
      </AppShell>
    </AuthGuard>
  );
}
