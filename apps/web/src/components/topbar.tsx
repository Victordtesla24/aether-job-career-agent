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
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { fetchAgents } from "../lib/api/agents";
import { fetchApprovals, type Approval } from "../lib/api/approvals";
import { isExpired } from "./approvals/lib";
import { fetchSettings } from "../lib/api/workspaces";
import { apiRequest } from "../lib/api/client";
import { fetchMe } from "../lib/api/admin";
import { UserMenu } from "./user-menu";
import { RealtimeStatusBadge } from "./realtime/RealtimeStatusBadge";

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

/**
 * How many approvals the bell may honestly claim are waiting (CRITICAL-4).
 *
 * `GET /approvals?status=pending` returns EVERY pending row, including ones
 * the backend has already voided: `ApprovalService.resolve` refuses a request
 * older than `EXPIRY_HOURS` (48h) with a 409 and tells the user to re-run the
 * agent. The Approvals page handles that correctly — it renders those rows
 * with an "expired" badge, disables Approve/Reject and offers "Clear expired"
 * — but the bell used the raw `items.length`, so it reported void requests as
 * pending work. Measured in production 2026-08-03: 91 pending rows, growing by
 * roughly 45/day from the autopilot, every one of which becomes a permanent
 * phantom in that count 48h after it is created.
 *
 * The count is therefore filtered by the SAME `isExpired` predicate the queue
 * screen uses (one 48h definition, shared with the server's). Expired rows are
 * not hidden anywhere — they remain listed and clearable on the queue screen;
 * they are only excluded from a number that means "things you can act on".
 */
export function actionableApprovalCount(
  approvals: Approval[],
  now: number = Date.now(),
): number {
  return approvals.filter((a) => a.status === "pending" && !isExpired(a, now)).length;
}

export interface BellPanelPosition {
  top: number;
  left: number;
  width: number;
}

/**
 * Anchors the notification panel's `position: fixed` box to the bell
 * button's bottom-right, clamped so it always stays fully inside the
 * viewport (BELL-OVERLAP-01 / BELL-OFFSCREEN-*).
 *
 * The previous implementation positioned the panel with `right: 0` relative
 * to its header wrapper, nested inside the `.glass` topbar's
 * `backdrop-filter`. That produced two live defects: on narrow (mobile)
 * viewports the panel's left edge landed well past x=0 (measured x=-107 on
 * a 390px viewport, live audit BELL-OFFSCREEN-*), and — because the panel's
 * lower portion extended outside the filtered header's own box — the
 * backdrop blur bled semi-transparent page content through the panel
 * (live audit BELL-OVERLAP-01 / KANBAN-HEADER-OVERLAP-01). Computing a
 * viewport-relative `fixed` position here (used together with rendering the
 * panel through a portal, out of the blurred ancestor's subtree) removes
 * both failure modes at the source instead of patching the symptom.
 */
export function computeBellPanelPosition(
  buttonRect: { right: number; bottom: number },
  viewportWidth: number,
  margin = 16,
  panelWidth = 320,
): BellPanelPosition {
  const width = Math.min(panelWidth, Math.max(0, viewportWidth - margin * 2));
  const maxLeft = Math.max(margin, viewportWidth - width - margin);
  const left = Math.min(Math.max(buttonRect.right - width, margin), maxLeft);
  return { top: buttonRect.bottom + 8, left, width };
}

/** Human label for the notifications panel (M-05/M-09). */
function approvalLabel(type: Approval["type"]): string {
  switch (type) {
    case "application_submit":
      return "Application ready to submit";
    case "email_send":
      return "Email ready to send";
    case "offer_response":
      return "Offer response awaiting your decision";
    default:
      return "Approval requested";
  }
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
  // M6: until the profile/session resolves we render skeletons rather than the
  // neutral "Welcome"/"AE" fallback, so the identity never visibly flips once
  // the real name loads (session flicker).
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [lastRun, setLastRun] = useState<string | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  // M-05/M-09: the bell now opens a real notifications panel (was a bare link).
  // We keep the actionable pending approvals themselves so the dropdown can
  // list them, honestly reflecting the same items the count is derived from.
  const [approvalItems, setApprovalItems] = useState<Approval[]>([]);
  const [bellOpen, setBellOpen] = useState(false);
  // U-UI BELL-OVERLAP-01/BELL-OFFSCREEN-*: the panel now renders through a
  // portal as a viewport-anchored `position: fixed` box (see
  // computeBellPanelPosition) instead of `absolute` inside the blurred
  // header. `bellRendered` keeps it mounted for a beat after close so the
  // exit transition can play instead of the panel vanishing instantly.
  const [bellRendered, setBellRendered] = useState(false);
  const [panelPos, setPanelPos] = useState<BellPanelPosition | null>(null);
  const [mounted, setMounted] = useState(false);
  const bellRef = useRef<HTMLDivElement | null>(null);
  const bellButtonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const searchIndex = useRef<SearchHit[] | null>(null);
  const [, setIndexReady] = useState(false);
  // GOLD-MASTER-V2 §9.2.3: persistent "Admin" indicator outside /admin/*.
  // Derived from the SAME live source AdminGuard already uses (/auth/me's
  // `isAdmin`, via the existing lib/api/admin fetchMe) — never a new
  // client-side flag, never cached beyond this mount, so a revoked admin
  // stops seeing it on their next page load like everything else gated by
  // /auth/me.
  const [isAdmin, setIsAdmin] = useState(false);
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
        setSettingsLoaded(true);
      })
      .catch(() => {
        // Graceful fallback — leave the neutral "Welcome" state in place.
        if (!cancelled) {
          setGreeting("Welcome");
          setSettingsLoaded(true);
        }
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
          // Only what the API will actually let the user act on — an expired
          // pending request answers 409, so counting it would be a promise the
          // backend refuses to keep (CRITICAL-4).
          if (cancelled) return;
          const now = Date.now();
          const actionable = items.filter((a) => a.status === "pending" && !isExpired(a, now));
          setApprovalItems(actionable);
          setPendingApprovals(actionable.length);
        })
        .catch(() => undefined);
    void loadApprovals();
    const timer = setInterval(loadApprovals, 60_000);
    fetchMe()
      .then((me) => {
        if (!cancelled) setIsAdmin(me.isAdmin);
      })
      .catch(() => {
        // Not resolvable (401, network error, revoked) — same graceful,
        // non-blocking fallback as fetchSettings/fetchAgents above: treat
        // as non-admin rather than surfacing anything.
        if (!cancelled) setIsAdmin(false);
      });
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  // The panel now portals to document.body (see the render below), so it
  // can only mount once we're on the client.
  useEffect(() => setMounted(true), []);

  // U-UI: keep the panel mounted for one transition tick after close so the
  // exit (opacity/scale) animation can play instead of the panel just
  // disappearing — "smooth open/close transition" per the design bar.
  useEffect(() => {
    if (bellOpen) {
      setBellRendered(true);
      return;
    }
    if (!bellRendered) return;
    const t = setTimeout(() => setBellRendered(false), 180);
    return () => clearTimeout(t);
  }, [bellOpen, bellRendered]);

  // M-05/M-09: close the notifications panel on an outside click or Escape.
  // The full-viewport backdrop rendered with the panel is the primary
  // click-to-close affordance; this listener is defence-in-depth for clicks
  // that land on the bell button itself (which sits under the backdrop) or
  // any future content stacked above it.
  useEffect(() => {
    if (!bellOpen) return;
    function onDown(e: MouseEvent) {
      const target = e.target as Node;
      if (bellRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setBellOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setBellOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [bellOpen]);

  // U-UI BELL-OFFSCREEN-*/BELL-OVERLAP-01: recompute the panel's
  // viewport-anchored position whenever it opens or the viewport changes —
  // getBoundingClientRect on the real bell button, not a class-based guess,
  // so the panel is provably on-screen at any width.
  useLayoutEffect(() => {
    if (!bellOpen) return;
    function update() {
      const btn = bellButtonRef.current;
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      setPanelPos(computeBellPanelPosition(rect, window.innerWidth));
    }
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [bellOpen]);

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
        <h1 className="truncate text-[13px] font-semibold sm:text-[15px]">
          {settingsLoaded ? (
            greeting
          ) : (
            <span
              aria-hidden="true"
              data-testid="greeting-skeleton"
              className="inline-block h-3.5 w-40 max-w-full rounded bg-white/10 align-middle animate-pulse"
            />
          )}
        </h1>
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
        {/* W-RT — the honest state of the shared realtime channel. Present on
            every dashboard screen so a user can always tell whether what they
            are looking at is being kept current or has quietly gone stale.
            Hidden on screens that subscribe to nothing, where there is genuinely
            nothing to report. */}
        <RealtimeStatusBadge compact hideWhenIdle className="max-w-[8.5rem] shrink-0 sm:max-w-none" />
        <div className="relative" ref={bellRef}>
          <button
            ref={bellButtonRef}
            type="button"
            onClick={() => setBellOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={bellOpen}
            aria-label={
              pendingApprovals > 0
                ? `Notifications — ${pendingApprovals} pending approval${pendingApprovals === 1 ? "" : "s"}`
                : "Notifications — no pending approvals"
            }
            data-design-id="m-notif-md02"
            data-testid="notification-bell"
            className="relative w-10 h-10 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition flex items-center justify-center"
          >
            <i className="fa-regular fa-bell text-aether-muted" />
            {pendingApprovals > 0 ? (
              <span className="absolute top-2 right-2.5 w-2 h-2 rounded-full bg-aether-coral" />
            ) : null}
          </button>
        </div>
        {/*
          U-UI BELL-OVERLAP-01 / KANBAN-HEADER-OVERLAP-01 / BELL-OFFSCREEN-*:
          the panel + its backdrop are portaled to document.body and
          positioned with `fixed` + computeBellPanelPosition instead of
          living `absolute` inside the `.glass` (backdrop-filter) header.
          That escapes the ancestor's filter/stacking context entirely, so
          the panel's own opaque surface renders correctly (no bleed-through)
          and its geometry is measured against the real viewport (never
          off-screen). It may still legitimately sit on top of page content
          (e.g. kanban column headers) — that's an intentional overlay now
          backed by a solid surface, a dismissible backdrop and a real
          z-index, not a rendering defect.
        */}
        {mounted && bellRendered
          ? createPortal(
              <>
                <div
                  aria-hidden="true"
                  onClick={() => setBellOpen(false)}
                  className={`fixed inset-0 z-[90] bg-black/20 transition-opacity duration-150 ${
                    bellOpen ? "opacity-100" : "pointer-events-none opacity-0"
                  }`}
                />
                <div
                  ref={panelRef}
                  role="menu"
                  data-testid="notification-panel"
                  style={
                    panelPos
                      ? { top: panelPos.top, left: panelPos.left, width: panelPos.width }
                      : { top: 0, left: 0, width: 320, visibility: "hidden" }
                  }
                  className={`fixed z-[100] max-w-[calc(100vw-2rem)] origin-top-right rounded-xl border border-white/10 bg-aether-bg-elevated shadow-xl shadow-black/40 transition duration-150 ease-out ${
                    bellOpen
                      ? "translate-y-0 scale-100 opacity-100"
                      : "pointer-events-none -translate-y-1 scale-95 opacity-0"
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
                    <span className="text-sm font-semibold text-aether-text">Notifications</span>
                    {pendingApprovals > 0 ? (
                      <span className="rounded-full bg-aether-coral/15 px-2 py-0.5 text-[11px] font-medium text-aether-coral">
                        {pendingApprovals} pending
                      </span>
                    ) : null}
                  </div>
                  {approvalItems.length === 0 ? (
                    <p
                      data-testid="notification-empty"
                      className="px-4 py-6 text-center text-sm text-aether-muted"
                    >
                      No new notifications.
                    </p>
                  ) : (
                    <ul className="max-h-80 overflow-y-auto py-1">
                      {approvalItems.slice(0, 6).map((a) => (
                        <li key={a.id}>
                          <Link
                            href="/dashboard/approvals"
                            role="menuitem"
                            onClick={() => setBellOpen(false)}
                            className="flex flex-col gap-0.5 px-4 py-2.5 hover:bg-white/5"
                          >
                            <span className="text-sm text-aether-text">{approvalLabel(a.type)}</span>
                            <span className="text-[11px] text-aether-muted-dim">
                              {timeAgo(a.createdAt)}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                  <Link
                    href="/dashboard/approvals"
                    onClick={() => setBellOpen(false)}
                    className="block border-t border-white/10 px-4 py-2.5 text-center text-xs font-semibold text-aether-indigo hover:bg-white/5"
                  >
                    View all approvals
                  </Link>
                </div>
              </>,
              document.body,
            )
          : null}
        {isAdmin ? (
          <Link
            href="/admin"
            aria-label="Admin — go to the admin portal"
            className="inline-flex items-center rounded-lg border border-aether-indigo/30 bg-aether-indigo/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-aether-indigo hover:bg-aether-indigo/20 transition"
          >
            Admin
          </Link>
        ) : null}
        <UserMenu
          initials={chip.initials}
          name={chip.chipName}
          role={chip.role}
          loading={!settingsLoaded}
        />
      </div>
    </header>
  );
}
