import { AuthGuard } from "@/components/auth-guard";
import { Sidebar } from "@/components/sidebar";
import { SubscriptionGate } from "@/components/subscription-gate";
import { Topbar } from "@/components/topbar";
import { MobileTabBar } from "@/components/mobile-tab-bar";

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
  return (
    <AuthGuard>
      <div className="flex min-h-screen">
        <Sidebar />
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
