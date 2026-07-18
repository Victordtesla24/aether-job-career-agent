"use client";

/**
 * Topbar user chip + account menu (MV-login-003). Renders the avatar / name /
 * role as a button that opens a small dropdown whose only item today is
 * "Sign out" — the app previously had no user-initiated way to end a session.
 * Signing out clears all client-side session state and returns to /login. The
 * menu closes on outside-click and Escape.
 */
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { clearClientSession } from "../lib/auth/logout";

export function UserMenu({
  initials,
  name,
  role,
}: {
  initials: string;
  name: string;
  role: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function handleSignOut() {
    clearClientSession();
    setOpen(false);
    router.replace("/login");
  }

  return (
    <div ref={containerRef} className="relative pl-3 border-l border-white/10">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className="flex items-center gap-2.5 rounded-xl px-1 py-1 hover:bg-white/5 transition"
      >
        <span className="w-9 h-9 rounded-full bg-gradient-to-br from-aether-indigo to-aether-violet flex items-center justify-center text-sm font-semibold">
          {initials}
        </span>
        <span className="leading-tight text-left">
          <span className="block text-[13px] font-medium">{name}</span>
          {role ? <span className="block text-[11px] text-aether-muted-dim">{role}</span> : null}
        </span>
        <i className="fa-solid fa-chevron-down text-[10px] text-aether-muted-dim" aria-hidden="true" />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-44 rounded-xl border border-white/10 bg-[#16162a] shadow-xl overflow-hidden z-50"
        >
          <button
            type="button"
            role="menuitem"
            onClick={handleSignOut}
            className="w-full text-left px-4 py-2.5 text-sm hover:bg-white/5 transition flex items-center gap-2"
          >
            <i className="fa-solid fa-right-from-bracket text-aether-muted" aria-hidden="true" />
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
