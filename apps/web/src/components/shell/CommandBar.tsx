"use client";

/**
 * S-UI-REBUILD §1.3 — the top bar becomes the COMMAND BAR.
 *
 * WHAT IS UNCHANGED (Binding Constraint 1)
 * ----------------------------------------
 * Every data source, every fetch, every interval, every `aria-label`, every
 * testid and every honesty string is carried over from `components/topbar.tsx`
 * verbatim:
 *   - `fetchSettings` → greeting via `timeOfDayGreeting`, the `today`
 *     `en-AU` locale string, `timeAgo(lastRun)`, and the M6
 *     `greeting-skeleton` anti-flicker state;
 *   - `fetchApprovals("pending")` on the same 60s interval, filtered by the
 *     same `isExpired` predicate — `actionableApprovalCount`'s CRITICAL-4
 *     rule that the bell may only claim what the API will actually let the
 *     user act on;
 *   - `fetchMe().isAdmin` for the Admin chip;
 *   - the notification panel's portal, its opaque `elev-3` surface, its
 *     backdrop, its viewport-safe `inset-x-4` bound and its REV-U-UI-05
 *     focus management, with testids `notification-bell`,
 *     `notification-panel`, `notification-backdrop`, `notification-empty`;
 *   - `min-h-16` (never a hard `h-16`) and `truncate` on both the greeting
 *     and the subtitle — the MV-mobile-dashboard-001 clip fix.
 *
 * WHAT IS NEW (presentation only)
 * -------------------------------
 *   - the search INPUT becomes a TRIGGER BUTTON showing ⌘K; the palette
 *     (`CommandPalette.tsx`) is the real search and reuses the exact same
 *     `loadSearchIndex` / `filterSearchHits` on the same lazy-on-first-open
 *     trigger, so the request list is unchanged;
 *   - a hamburger below `lg` (U-NAV-MOBILE-01) — rendered only when the
 *     shell actually supplies a handler, so it is never a dead control;
 *   - `RealtimeStatusBadge` is wrapped by `SystemStatus` (§1.4), which is a
 *     reader over the one existing store and opens no connection;
 *   - a 1px coral scroll-progress hairline. It is ornament, but it is tied
 *     to a real input (the user's own scrolling), so doctrine D-β holds;
 *   - the bell dot plays ONE scale pop when `pendingApprovals` RISES. It
 *     never loops, and a decrease plays nothing.
 */

import Link from "next/link";
import { motion, useMotionValue } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { fetchMe } from "../../lib/api/admin";
import { fetchAgents } from "../../lib/api/agents";
import { fetchApprovals, type Approval } from "../../lib/api/approvals";
import { apiBaseUrl, getToken } from "../../lib/api/client";
import { fetchSettings } from "../../lib/api/workspaces";
import { SPRING } from "../../lib/motion";
import { isExpired } from "../approvals/lib";
import { UserMenu } from "../user-menu";
import { CommandPalette } from "./CommandPalette";
import { QueueStatusBadge } from "./QueueStatusBadge";
import { SystemStatus } from "./SystemStatus";

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

export function CommandBar({
  subtitle,
  onOpenNav,
}: {
  title?: string;
  subtitle?: string;
  /** Supplied by the shell to open the mobile nav sheet (U-NAV-MOBILE-01).
   * Absent → no hamburger is rendered, so there is never a dead control. */
  onOpenNav?: () => void;
}) {
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  // U-UI BELL-OVERLAP-01/BELL-OFFSCREEN-*: the panel (+ its backdrop) render
  // through a portal, out of the blurred header's subtree, as a
  // `position: fixed` box positioned entirely with viewport-safe CSS.
  // `mounted` gates the portal until we're on the client (SSR safety).
  const [mounted, setMounted] = useState(false);
  const bellRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const bellButtonRef = useRef<HTMLButtonElement | null>(null);
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
  const [photoSrc, setPhotoSrc] = useState<string | null>(null);
  // One pop when the count RISES; never on a decrease, never a loop (§1.3).
  const previousApprovals = useRef(0);
  const [bellPop, setBellPop] = useState(0);
  const scrollProgress = useMotionValue(0);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchSettings()
      .then(async (settings) => {
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
        if (settings.profile.hasAvatar) {
          try {
            const token = await getToken();
            const res = await fetch(`${apiBaseUrl()}/workspaces/settings/avatar`, {
              headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok || cancelled) return;
            const blob = await res.blob();
            objectUrl = URL.createObjectURL(blob);
            if (cancelled) {
              URL.revokeObjectURL(objectUrl);
              return;
            }
            setPhotoSrc(objectUrl);
          } catch {
            // Keep initials — never a broken image.
            if (!cancelled) setPhotoSrc(null);
          }
        } else if (!cancelled) {
          setPhotoSrc(null);
        }
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
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, []);

  // The panel now portals to document.body (see the render below), so it
  // can only mount once we're on the client.
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (pendingApprovals > previousApprovals.current) setBellPop((n) => n + 1);
    previousApprovals.current = pendingApprovals;
  }, [pendingApprovals]);

  /*
   * The scroll-progress hairline. Written with a plain scroll listener and a
   * motion value rather than framer's `useScroll`, which reaches for DOM
   * measurement APIs jsdom does not implement — the existing shell test
   * suites render this component and must keep passing untouched.
   */
  useEffect(() => {
    function onScroll() {
      const doc = document.documentElement;
      const max = doc.scrollHeight - doc.clientHeight;
      scrollProgress.set(max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0);
    }
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [scrollProgress]);

  // ⌘K / Ctrl-K toggles the palette from anywhere in the shell (§1.6).
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

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

  // REV-U-UI-05: the panel is portaled to the end of document.body, so
  // without this, Tab from the bell no longer reaches its menuitems — a
  // keyboard user would have to traverse the rest of the header, sidebar and
  // page first. Move focus into the panel's first focusable item the instant
  // it opens; on close, hand focus back to the bell — but only when nothing
  // else already claimed it.
  useEffect(() => {
    if (!bellOpen) return;
    const panel = panelRef.current;
    if (!panel) return;
    const bellButton = bellButtonRef.current;
    const focusable = panel.querySelector<HTMLElement>(
      '[role="menuitem"], a[href], button, [tabindex]:not([tabindex="-1"])',
    );
    (focusable ?? panel).focus();
    return () => {
      if (document.activeElement === document.body) {
        bellButton?.focus();
      }
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
    <header className="chrome-blur sticky top-0 z-30 min-h-16 shrink-0 border-b border-hairline">
      <div className="flex items-center justify-between gap-3 px-4 py-2 sm:px-8">
        {onOpenNav ? (
          <button
            type="button"
            data-testid="mobile-nav-trigger"
            onClick={onOpenNav}
            aria-label="Open navigation"
            aria-haspopup="dialog"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-aether-muted transition-colors duration-[--dur-fast] hover:bg-surface-2 hover:text-aether-text focus:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/60 lg:hidden"
          >
            <i className="fa-solid fa-bars text-sm" aria-hidden="true" />
          </button>
        ) : null}
        {/*
          MV-mobile-dashboard-001: at a 390px viewport this greeting/subtitle
          previously wrapped to 2-3 lines inside a hard-clamped `h-16` header,
          clipping the first line above the viewport and overflowing the
          subtitle below the header box. `min-w-0` lets this column shrink
          below its content's natural width inside the flex row so `truncate`
          can actually take effect; `truncate` keeps each line to a single row
          (ellipsis instead of wrap) so it can never exceed the header's box;
          the header itself is a `min-h` (can grow) rather than a fixed height
          as defence in depth.
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
          <p className="type-mono-micro truncate text-aether-muted-dim max-sm:hidden">
            {liveSubtitle}
          </p>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          {/* §1.3 — the search box is now a TRIGGER, not an input. The palette
              is the real search and reuses the same index loader. */}
          <button
            type="button"
            data-testid="command-palette-trigger"
            onClick={() => setPaletteOpen(true)}
            aria-haspopup="dialog"
            aria-label="Search jobs, applications, agents"
            className="hidden w-64 items-center gap-2.5 rounded-lg border border-hairline bg-surface-1 px-3 py-2 text-left text-[13px] text-aether-muted-dim transition-colors duration-[--dur-fast] hover:border-hairline-strong hover:text-aether-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/60 lg:flex"
          >
            <i className="fa-solid fa-magnifying-glass text-[12px]" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">Search or jump to…</span>
            <kbd className="type-mono-micro rounded border border-hairline px-1.5">⌘K</kbd>
          </button>
          <button
            type="button"
            data-testid="command-palette-trigger-compact"
            onClick={() => setPaletteOpen(true)}
            aria-haspopup="dialog"
            aria-label="Search jobs, applications, agents"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-aether-muted transition-colors duration-[--dur-fast] hover:bg-surface-2 hover:text-aether-text focus:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/60 lg:hidden"
          >
            <i className="fa-solid fa-magnifying-glass text-sm" aria-hidden="true" />
          </button>
          {/* W-RT — the honest state of the shared realtime channel, now a
              popover (§1.4). Present on every dashboard screen so a user can
              always tell whether what they are looking at is being kept
              current or has quietly gone stale. Hidden on screens that
              subscribe to nothing, where there is genuinely nothing to
              report. */}
          <SystemStatus compact className="max-w-[9.5rem] shrink-0 max-sm:hidden sm:max-w-none" />
          {/* D-QDEPTH — honest worker-queue depth; renders only when there is
              a real backlog to report (>=1 queued job), silent otherwise. */}
          <QueueStatusBadge className="max-sm:hidden" />
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
              className="relative flex h-10 w-10 items-center justify-center rounded-lg border border-hairline bg-surface-1 transition-colors duration-[--dur-fast] hover:border-hairline-strong hover:bg-surface-2"
            >
              <i className="fa-regular fa-bell text-aether-muted" aria-hidden="true" />
              {pendingApprovals > 0 ? (
                <motion.span
                  key={bellPop}
                  initial={{ scale: 1 }}
                  animate={{ scale: [1, 1.35, 1] }}
                  transition={SPRING.snappy}
                  className="absolute right-2.5 top-2 h-2 w-2 rounded-full bg-aether-coral"
                />
              ) : null}
            </button>
          </div>
          {/*
            U-UI BELL-OVERLAP-01 / KANBAN-HEADER-OVERLAP-01 / BELL-OFFSCREEN-*:
            the panel + its backdrop are portaled to document.body instead of
            living `absolute` inside the blurred header — that escapes the
            ancestor's filter/stacking context entirely, so the panel's own
            opaque surface renders correctly (no bleed-through) regardless of
            where in the header tree the bell button sits. Horizontal position
            is plain viewport-safe CSS (no JS measurement to go stale on
            resize/scroll): `inset-x-4` keeps it fully on-screen with equal
            margins on narrow viewports; `sm:inset-x-auto sm:right-8 sm:w-80`
            anchors it flush with the header's own right content edge once
            there's room (REV-U-UI-03).
          */}
          {mounted && bellOpen
            ? createPortal(
                <>
                  <div
                    aria-hidden="true"
                    data-testid="notification-backdrop"
                    onClick={() => setBellOpen(false)}
                    className="fixed inset-0 z-40 bg-black/20"
                  />
                  <div
                    ref={panelRef}
                    role="menu"
                    // REV-U-UI-05: focusable as a last-resort landing spot.
                    tabIndex={-1}
                    data-testid="notification-panel"
                    className="animate-fade-in fixed top-16 z-50 inset-x-4 sm:inset-x-auto sm:right-8 sm:w-80 rounded-xl border border-hairline-strong bg-aether-bg-elevated shadow-xl shadow-black/40"
                  >
                    <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
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
                              className="flex flex-col gap-0.5 px-4 py-2.5 hover:bg-surface-2"
                            >
                              <span className="text-sm text-aether-text">
                                {approvalLabel(a.type)}
                              </span>
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
                      className="block border-t border-hairline px-4 py-2.5 text-center text-xs font-semibold text-aether-indigo hover:bg-surface-2"
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
              className="inline-flex items-center rounded-lg border border-aether-indigo/30 bg-aether-indigo/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-aether-indigo transition hover:bg-aether-indigo/20"
            >
              Admin
            </Link>
          ) : null}
          <UserMenu
            initials={chip.initials}
            name={chip.chipName}
            role={chip.role}
            photoSrc={photoSrc}
            loading={!settingsLoaded}
          />
        </div>
      </div>
      {/* D-β: ornament, but driven by a real input — the user's own scroll. */}
      <motion.div
        aria-hidden="true"
        data-testid="scroll-progress"
        style={{ scaleX: scrollProgress }}
        className="h-px origin-left bg-aether-coral"
      />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </header>
  );
}

export default CommandBar;
