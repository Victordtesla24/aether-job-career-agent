import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";

/**
 * Shell layout shared by every /dashboard/* route: the persistent sidebar on
 * the left and a sticky top bar above the routed page content. The active nav
 * item is resolved client-side from the pathname in a later slice; for the
 * Phase 1 shell we highlight the dashboard root.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <Sidebar activeHref="/dashboard" />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 px-8 py-7">{children}</main>
      </div>
    </div>
  );
}
