import type { Metadata } from "next";

import PrivacyPolicyPage from "../privacy-policy/page";

export const metadata: Metadata = {
  title: "Privacy Policy · Aether Career Agent",
  description:
    "How Aether Career Agent collects, uses, and protects your data.",
};

// Read the operator support-contact env var at request time, not baked in at
// build time (MV-privacy-policy-003, H-3 — see lib/config/legal.ts).
export const dynamic = "force-dynamic";

/**
 * Canonical public privacy policy route at /privacy (C-01, QA-v2).
 *
 * A subscription service that collects personal data and processes payments
 * must expose a privacy policy at the conventional /privacy path — the QA v2
 * report flagged /privacy returning 404 as a legal-compliance blocker. The
 * full, Australian-Privacy-Act-compliant document already lives in the
 * <PrivacyPolicyPage> component (rendered at the legacy /privacy-policy path
 * that Google's OAuth consent screen links to); this route reuses that exact
 * component so there is a single source of truth and the two paths can never
 * drift. Like /privacy-policy and /terms it is intentionally NOT wrapped in
 * the dashboard layout, so it is reachable without authentication.
 */
export default function PrivacyPage() {
  return <PrivacyPolicyPage />;
}
