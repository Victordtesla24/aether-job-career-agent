import { AuthGuard } from "@/components/auth-guard";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { MobileTabBar } from "@/components/mobile-tab-bar";

/**
 * Shell layout shared by every /dashboard/* route: the persistent sidebar on
 * the left and a sticky top bar above the routed page content. The sidebar
 * resolves the active nav item from the live pathname (P1-S12). The whole
 * shell sits behind AuthGuard — no session, no workspace (SC-AUTH-03).
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
          <main className="flex-1 px-4 py-5 pb-24 sm:px-6 lg:px-8 lg:py-7 lg:pb-7">{children}</main>
          <MobileTabBar />
        </div>
      </div>
    </AuthGuard>
  );
}
