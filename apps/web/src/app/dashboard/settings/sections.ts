/**
 * Settings sub-nav definition (GAP-P4-062). Kept out of page.tsx because
 * Next.js App Router route files may only export the reserved names
 * (default, metadata, etc.) — an arbitrary named export like SECTIONS fails
 * the route's generated type-check.
 *
 * Order matches design/screens/settings.html's settings-subnav-st06:
 * Profile, Resume Management, Portfolio Sync, Notifications, Agent
 * Configuration, Integrations, Privacy & Compliance.
 */
export const SECTIONS = [
  { id: "profile", label: "Profile" },
  { id: "resume", label: "Resume Management" },
  { id: "portfolio", label: "Portfolio Sync" },
  { id: "notifications", label: "Notifications" },
  { id: "agents", label: "Agent Configuration" },
  { id: "integrations", label: "Integrations" },
  { id: "privacy", label: "Privacy & Compliance" },
] as const;
