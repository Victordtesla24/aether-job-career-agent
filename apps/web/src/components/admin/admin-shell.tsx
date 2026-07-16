"use client";

/**
 * Admin panel chrome (GAP-P6-ADMIN-001): a left nav shared by every /admin/*
 * page, styled with the same `aether` dark tokens as the dashboard shell.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV: Array<{ href: string; label: string }> = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/health", label: "Health" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/spend", label: "Spend (US$)" },
  { href: "/admin/settings", label: "Settings" },
  { href: "/admin/audit-log", label: "Audit log" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/admin";
  return (
    <div className="flex min-h-screen bg-aether-bg text-aether-text">
      <aside className="w-56 shrink-0 border-r border-white/10 bg-aether-bg-elevated px-3 py-5">
        <div className="mb-6 px-2">
          <p className="text-sm font-semibold text-aether-text">Aether Admin</p>
          <p className="text-xs text-aether-muted-dim">Platform control</p>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-md px-3 py-2 text-sm transition-colors ${
                isActive(pathname, item.href)
                  ? "bg-aether-indigo/20 text-aether-text"
                  : "text-aether-muted hover:bg-white/5 hover:text-aether-text"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="mt-8 border-t border-white/10 pt-4 px-2">
          <Link href="/dashboard" className="text-xs text-aether-muted-dim hover:text-aether-text">
            ← Back to dashboard
          </Link>
        </div>
      </aside>
      <main className="flex-1 min-w-0 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}

/** Consistent page header. */
export function AdminPageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="mb-6">
      <h1 className="text-xl font-semibold text-aether-text">{title}</h1>
      {subtitle ? <p className="mt-1 text-sm text-aether-muted">{subtitle}</p> : null}
    </header>
  );
}
