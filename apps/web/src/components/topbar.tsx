"use client";

/**
 * Dashboard top bar: greeting, global search, notifications, and the user chip.
 * The user's name, target role and initials are loaded live from the /settings
 * API (fetchSettings). The greeting adapts to the local time of day. If the
 * fetch fails we fall back to a neutral "Welcome" so the shell never breaks.
 */
import { useEffect, useState } from "react";
import { fetchSettings } from "../lib/api/workspaces";

interface UserChip {
  firstName: string;
  initials: string;
  chipName: string;
  role: string;
}

function timeOfDayGreeting(date: Date): string {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/** Build the chip fields from a full name + target role. */
function deriveChip(fullName: string, targetRole: string): UserChip {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  const firstName = parts[0] ?? "";
  const lastInitial = parts.length > 1 ? parts[parts.length - 1]!.charAt(0) : "";
  const initials =
    (firstName.charAt(0) + (lastInitial || (parts[0]?.charAt(1) ?? ""))).toUpperCase() || "AE";
  const chipName = lastInitial ? `${firstName} ${lastInitial}.` : firstName;
  return { firstName, initials, chipName, role: shortenRole(targetRole) };
}

/** Compact a long target role for the chip subtitle (e.g. "Senior TPM"). */
function shortenRole(role: string): string {
  if (!role) return "";
  const compact = role
    .replace(/Technical Program Manager/i, "TPM")
    .replace(/Product Manager/i, "PM")
    .replace(/Business Analyst/i, "BA")
    .replace(/Program Manager/i, "PM");
  return compact.length > 22 ? `${compact.slice(0, 21).trimEnd()}…` : compact;
}

export function Topbar({
  subtitle = "Your agents worked through the night",
}: {
  title?: string;
  subtitle?: string;
}) {
  const [greeting, setGreeting] = useState("Welcome");
  const [chip, setChip] = useState<UserChip>({
    firstName: "",
    initials: "AE",
    chipName: "Welcome",
    role: "",
  });

  useEffect(() => {
    let cancelled = false;
    fetchSettings()
      .then((settings) => {
        if (cancelled) return;
        const fullName = settings.profile.fullName || "";
        const derived = deriveChip(fullName, settings.profile.targetRole || "");
        setChip(derived);
        setGreeting(
          derived.firstName
            ? `${timeOfDayGreeting(new Date())}, ${derived.firstName}`
            : "Welcome",
        );
      })
      .catch(() => {
        // Graceful fallback — leave the neutral "Welcome" state in place.
        if (!cancelled) setGreeting("Welcome");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="h-16 shrink-0 border-b border-white/10 glass flex items-center justify-between px-8">
      <div>
        <h1 className="text-[15px] font-semibold">{greeting}</h1>
        <p className="text-xs text-aether-muted-dim mono">{subtitle}</p>
      </div>
      <div className="flex items-center gap-3">
        <div className="relative w-72 hidden md:block">
          <i className="fa-solid fa-magnifying-glass absolute left-3.5 top-1/2 -translate-y-1/2 text-aether-muted-dim text-sm" />
          <input
            type="text"
            placeholder="Search jobs, applications, agents..."
            aria-label="Search"
            className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
          />
        </div>
        <button
          type="button"
          aria-label="Notifications"
          data-design-id="m-notif-md02"
          className="relative w-10 h-10 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition flex items-center justify-center"
        >
          <i className="fa-regular fa-bell text-aether-muted" />
          <span className="absolute top-2 right-2.5 w-2 h-2 rounded-full bg-aether-coral" />
        </button>
        <div className="flex items-center gap-2.5 pl-3 border-l border-white/10">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-aether-indigo to-aether-violet flex items-center justify-center text-sm font-semibold">
            {chip.initials}
          </div>
          <div className="leading-tight">
            <div className="text-[13px] font-medium">{chip.chipName}</div>
            {chip.role ? (
              <div className="text-[11px] text-aether-muted-dim">{chip.role}</div>
            ) : null}
          </div>
        </div>
      </div>
    </header>
  );
}
