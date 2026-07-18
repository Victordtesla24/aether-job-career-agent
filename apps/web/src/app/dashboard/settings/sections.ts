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
] as const;
