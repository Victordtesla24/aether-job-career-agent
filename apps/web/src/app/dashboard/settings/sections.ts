/**
 * Settings sub-nav definition (GAP-P4-062). Kept out of page.tsx because
 * Next.js App Router route files may only export the reserved names
 * (default, metadata, etc.) — an arbitrary named export like SECTIONS fails
 * the route's generated type-check.
 *
 * The first seven entries match design/screens/settings.html's
 * settings-subnav-st06 order exactly (Profile, Resume Management, Portfolio
 * Sync, Notifications, Agent Configuration, Integrations, Privacy &
 * Compliance — see settings-subnav.test.ts, a regression guard for
 * GAP-P4-062). "Billing & Subscription" (MV-settings-003) is a genuine new
 * section absent from that wireframe — the wireframe never accounted for
 * billing self-service at all — appended last so it doesn't reorder any of
 * the seven wireframe-pinned entries.
 *
 * "Screening Answers" (SETUP-1) is appended after Billing for the same reason:
 * the wireframe predates the Answer Bank entirely. It belongs on this screen
 * rather than only on /dashboard/answer-bank because it is the third thing the
 * Submission Agent needs from a new subscriber — after the résumé and the
 * profile links, both of which are already here — and asking for all three in
 * one place is the difference between an agent that can send an application and
 * one that stops on the first screening question.
 */
export const SECTIONS = [
  { id: "profile", label: "Profile" },
  { id: "resume", label: "Resume Management" },
  { id: "portfolio", label: "Portfolio Sync" },
  { id: "notifications", label: "Notifications" },
  { id: "agents", label: "Agent Configuration" },
  { id: "integrations", label: "Integrations" },
  { id: "privacy", label: "Privacy & Compliance" },
  { id: "billing", label: "Billing & Subscription" },
  { id: "screening", label: "Screening Answers" },
] as const;
