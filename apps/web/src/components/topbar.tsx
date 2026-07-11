"use client";

/**
 * Dashboard top bar: greeting, live activity subtitle, notifications, and the
 * user chip. The user's name, target role and initials are loaded live from
 * the /settings API (fetchSettings). The greeting adapts to the local time of
 * day; the subtitle shows the real date and last agent run; the notification
 * bell reflects the real pending-approvals count and links to the queue. If a
 * fetch fails we fall back to neutral copy so the shell never breaks.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchAgents } from "../lib/api/agents";
import { fetchApprovals } from "../lib/api/approvals";
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

function timeAgo(iso: string): string {
  const mins = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60_000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / (60 * 24))}d ago`;
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

export function Topbar({ subtitle }: { title?: string; subtitle?: string }) {
  const [greeting, setGreeting] = useState("Welcome");
  const [lastRun, setLastRun] = useState<string | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState(0);
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
    fetchAgents()
      .then((agents) => {
        if (cancelled) return;
        const latest = agents
          .map((a) => a.last_run)
          .filter((r): r is string => Boolean(r))
          .sort()
          .pop();
        setLastRun(latest ?? null);
      })
      .catch(() => undefined);
    const loadApprovals = () =>
      fetchApprovals("pending")
        .then((items) => {
          if (!cancelled) setPendingApprovals(items.length);
        })
        .catch(() => undefined);
    void loadApprovals();
    const timer = setInterval(loadApprovals, 60_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const today = new Date().toLocaleDateString("en-AU", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const liveSubtitle =
    subtitle ?? (lastRun ? `${today} · last agent run ${timeAgo(lastRun)}` : today);

  return (
    <header className="h-16 shrink-0 border-b border-white/10 glass flex items-center justify-between px-8">
      <div>
        <h1 className="text-[15px] font-semibold">{greeting}</h1>
        <p className="text-xs text-aether-muted-dim mono">{liveSubtitle}</p>
      </div>
      <div className="flex items-center gap-3">
        <Link
          href="/dashboard/approvals"
          aria-label={
            pendingApprovals > 0
              ? `Notifications — ${pendingApprovals} pending approval${pendingApprovals === 1 ? "" : "s"}`
              : "Notifications — no pending approvals"
          }
          data-design-id="m-notif-md02"
          className="relative w-10 h-10 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition flex items-center justify-center"
        >
          <i className="fa-regular fa-bell text-aether-muted" />
          {pendingApprovals > 0 ? (
            <span className="absolute top-2 right-2.5 w-2 h-2 rounded-full bg-aether-coral" />
          ) : null}
        </Link>
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
