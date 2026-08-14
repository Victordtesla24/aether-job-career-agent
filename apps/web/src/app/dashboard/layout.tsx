import { AuthGuard } from "@/components/auth-guard";
import { Sidebar } from "@/components/sidebar";
import { SubscriptionGate } from "@/components/subscription-gate";
import { Topbar } from "@/components/topbar";
import { MobileTabBar } from "@/components/mobile-tab-bar";
import { getOperatorLegalConfig } from "@/lib/config/legal";

// O-1 (S-FIX slice C): read AETHER_SUPPORT_EMAIL at request time (never
// build-baked) so the sidebar's "Contact support" link reflects the live
// process environment, matching /dashboard/settings and the legal pages.
export const dynamic = "force-dynamic";

/**
 * Shell layout shared by every /dashboard/* route: the persistent sidebar on
 * the left and a sticky top bar above the routed page content. The sidebar
 * resolves the active nav item from the live pathname (P1-S12). The whole
 * shell sits behind AuthGuard — no session, no workspace (SC-AUTH-03) — and
 * behind SubscriptionGate: without an active paid subscription the routed page
 * is replaced by the "Subscribe to unlock Aether" paywall (GAP-P6-PAYWALL).
 * The gate self-exempts account-management routes (/dashboard/settings) so a
 * free user can always view and manage/cancel their own subscription
 * (MV-pricing-003 / MV-settings-003); it fails CLOSED if entitlement can't be
 * verified (MV-agent-monitor-004). See subscription-gate.tsx.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { supportEmail } = getOperatorLegalConfig();
  return (
    <AuthGuard>
      <div className="flex min-h-screen">
        <Sidebar supportEmail={supportEmail} />
        <div className="flex-1 flex flex-col min-w-0">
          <Topbar />
          <main className="flex-1 px-4 py-5 pb-24 sm:px-6 lg:px-8 lg:py-7 lg:pb-7">
            <SubscriptionGate>{children}</SubscriptionGate>
          </main>
          <MobileTabBar />
        </div>
      </div>
    </AuthGuard>
  );
}
