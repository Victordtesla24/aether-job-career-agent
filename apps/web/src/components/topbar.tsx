"use client";

/**
 * Dashboard top bar: greeting, live activity subtitle, global search,
 * notifications, and the user chip. The user's name, target role and initials
 * are loaded live from the /settings API (fetchSettings). The greeting adapts
 * to the local time of day; the subtitle shows the real date and last agent
 * run; the search box indexes the user's real jobs, applications and agents
 * (wireframe topbar contract); the notification bell reflects the real
 * pending-approvals count and links to the queue. If a fetch fails we fall
 * back to neutral copy so the shell never breaks.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { fetchAgents } from "../lib/api/agents";
import { fetchApprovals } from "../lib/api/approvals";
import { fetchSettings } from "../lib/api/workspaces";
import { apiRequest } from "../lib/api/client";
import { UserMenu } from "./user-menu";

export interface SearchHit {
  kind: "job" | "application" | "agent";
  id: string;
  label: string;
  sublabel: string;
  href: string;
}

/** Case-insensitive substring match over label + sublabel; requires ≥2 chars. */
export function filterSearchHits(hits: SearchHit[], query: string, limit = 8): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  return hits
    .filter((h) => `${h.label} ${h.sublabel}`.toLowerCase().includes(q))
    .slice(0, limit);
}

/** Build the search index from the user's live jobs, applications and agents. */
async function loadSearchIndex(): Promise<SearchHit[]> {
  const [jobs, applications, agents] = await Promise.all([
    apiRequest<Array<{ id: string; title: string; company: string }>>("/jobs?"),
    apiRequest<Array<{ id: string; jobTitle?: string | null; company?: string | null }>>(
      "/applications",
    ),
    fetchAgents(),
  ]);
  return [
    ...jobs.map<SearchHit>((j) => ({
      kind: "job",
      id: j.id,
      label: j.title,
      sublabel: j.company,
      href: "/dashboard/jobs",
    })),
    ...applications.map<SearchHit>((a) => ({
      kind: "application",
      id: a.id,
      label: a.jobTitle ?? "Application",
      sublabel: a.company ?? "",
      href: "/dashboard/applications",
    })),
    ...agents.map<SearchHit>((a) => ({
      kind: "agent",
      id: a.name,
      label: a.name,
      sublabel: "agent",
      href: "/dashboard/agents",
    })),
  ];
}

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

/**
 * A display-name token safe to derive initials from: it begins with a Unicode
 * letter and contains only letters/marks plus intra-name punctuation
 * (apostrophe, hyphen, period). Markup ("<script>…") and emoji/symbol tokens
 * ("日本語🎉") are excluded so an adversarial or decorated name degrades
 * gracefully instead of garbling the avatar/label (MV-signup-004).
 */
const NAME_TOKEN_RE = /^[\p{L}\p{M}][\p{L}\p{M}'.’-]*$/u;

/** First code point of a string (surrogate-pair aware), or "". */
function firstCodePoint(value: string): string {
  return Array.from(value)[0] ?? "";
}

/** First letter code point at or after index 1 (the fallback second initial
 * for a single-token name), or "". */
function secondLetter(value: string): string {
  return Array.from(value).slice(1).find((c) => /\p{L}/u.test(c)) ?? "";
}

/** Build the chip fields from a full name + target role. Robust to markup,
 * emoji, and surrogate-pair characters in the name (MV-signup-004). */
export function deriveChip(fullName: string, targetRole: string): UserChip {
  const parts = fullName
    .trim()
    .split(/\s+/)
    .filter((p) => NAME_TOKEN_RE.test(p));
  const firstName = parts[0] ?? "";
  const lastInitial = parts.length > 1 ? firstCodePoint(parts[parts.length - 1]!) : "";
  const initials =
    (firstCodePoint(firstName) + (lastInitial || secondLetter(firstName))).toUpperCase() || "AE";
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
  const router = useRouter();
  const [greeting, setGreeting] = useState("Welcome");
  const [lastRun, setLastRun] = useState<string | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const searchIndex = useRef<SearchHit[] | null>(null);
  const [, setIndexReady] = useState(false);
  const [chip, setChip] = useState<UserChip>({
    firstName: "",
    initials: "AE",
    chipName: "Welcome",
    role: "",
  });

  // Lazy-load the search index on first focus so the topbar mount stays cheap.
  function ensureSearchIndex(): void {
    if (searchIndex.current) return;
    loadSearchIndex()
      .then((hits) => {
        searchIndex.current = hits;
        setIndexReady(true);
      })
      .catch(() => undefined);
  }

  const hits = filterSearchHits(searchIndex.current ?? [], query);

  function goTo(hit: SearchHit): void {
    setQuery("");
    setSearchOpen(false);
    router.push(hit.href);
  }

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
    <header className="min-h-16 shrink-0 border-b border-white/10 glass flex items-center justify-between gap-3 px-4 py-2 sm:px-8">
      {/*
        MV-mobile-dashboard-001: at a 390px viewport this greeting/subtitle
        previously wrapped to 2-3 lines inside a hard-clamped `h-16` header,
        clipping the first line above the viewport and overflowing the
        subtitle below the header box (DOM measurement: h1 top:-15,
        p.bottom:78 vs. header bottom:64). `min-w-0` lets this column shrink
        below its content's natural width inside the flex row so `truncate`
        can actually take effect instead of the row overflowing; `truncate`
        keeps each line to a single row (ellipsis instead of wrap) so it can
        never exceed the header's box regardless of viewport width; the
        header itself is now a `min-h` (can grow) rather than a fixed height
        as defense in depth.
      */}
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[13px] font-semibold sm:text-[15px]">{greeting}</h1>
        <p className="truncate text-[11px] text-aether-muted-dim mono sm:text-xs">{liveSubtitle}</p>
      </div>
      <div className="flex items-center gap-3">
        <div className="relative w-72 max-lg:hidden">
          <i className="fa-solid fa-magnifying-glass absolute left-3.5 top-1/2 -translate-y-1/2 text-aether-muted-dim text-sm" />
          <input
            type="text"
            role="combobox"
            aria-expanded={searchOpen && hits.length > 0}
            aria-controls="topbar-search-results"
            aria-label="Search jobs, applications, agents"
            placeholder="Search jobs, applications, agents…"
            value={query}
            onFocus={() => {
              ensureSearchIndex();
              setSearchOpen(true);
            }}
            onBlur={() => setTimeout(() => setSearchOpen(false), 150)}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && hits[0]) goTo(hits[0]);
              if (e.key === "Escape") {
                setQuery("");
                setSearchOpen(false);
              }
            }}
            className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
          />
          {searchOpen && hits.length > 0 ? (
            <ul
              id="topbar-search-results"
              role="listbox"
              className="absolute z-50 mt-2 w-full rounded-xl border border-white/10 bg-[#16162a] shadow-xl overflow-hidden"
            >
              {hits.map((hit) => (
                <li key={`${hit.kind}-${hit.id}`} role="option" aria-selected={false}>
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      goTo(hit);
                    }}
                    className="w-full text-left px-4 py-2.5 hover:bg-white/5 transition flex items-center gap-2"
                  >
                    <span className="text-[10px] uppercase tracking-wide text-aether-muted-dim w-20 shrink-0">
                      {hit.kind}
                    </span>
                    <span className="text-[13px] truncate">{hit.label}</span>
                    {hit.sublabel ? (
                      <span className="text-[11px] text-aether-muted-dim truncate">
                        {hit.sublabel}
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
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
        <UserMenu initials={chip.initials} name={chip.chipName} role={chip.role} />
      </div>
    </header>
  );
}
