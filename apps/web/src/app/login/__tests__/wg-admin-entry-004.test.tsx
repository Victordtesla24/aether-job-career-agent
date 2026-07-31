// @vitest-environment jsdom
/**
 * GOLD-MASTER-V2 §9.2.1 (W-G) — /login has NO admin entry point.
 *
 * VERIFIED TWICE on production (screen-test evidence:
 * uat/reports/evidence/gold-master-v2/screens/admin-portal-screen-test.md):
 * there is no "Admin Login" button/link anywhere on /login routing to a
 * distinct admin login path, even though the admin portal itself (/admin
 * and its 7 sub-routes) is fully built and correctly gated.
 *
 * RCA against current code (apps/web/src/app/login/page.tsx, read in full):
 * the rendered tree is exactly: logo block, the "Sign in" form (identifier +
 * password + submit), a "Create account" link to /signup, a "Forgot
 * password?" link, and PublicFooter (privacy/terms links). There is no
 * third link anywhere on the page whose accessible name references "admin".
 *
 * This is append-only — it does not touch apps/web/src/app/login/__tests__/
 * page.test.tsx (the pre-existing, still-relevant regression suite for the
 * "Email or username" relabel / create-account link / redirect behaviour).
 *
 * Fail-before: no such link exists, so `getByRole("link", { name: /admin/i })`
 * throws. Not implementation-prescriptive about the destination page name —
 * only that the link exists, is clearly labelled "admin", and its href is
 * under the /admin path family (never /dashboard or an external URL), so a
 * fixer building /admin/login (matching the existing /admin/settings,
 * /admin/audit-log sibling convention) satisfies this without inventing a
 * requirement not in the brief.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

// eslint-disable-next-line import/first
import LoginPage from "../page";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/login");
});

describe("W-G §9.2.1: /login admin entry point", () => {
  it('exposes a clearly-labelled "Admin" entry point linking to an admin login path', () => {
    render(<LoginPage />);

    const adminLink = screen.getByRole("link", { name: /admin/i });
    expect(adminLink).toBeTruthy();

    const href = adminLink.getAttribute("href") || "";
    expect(href.startsWith("/admin")).toBe(true);
    // Must be a DISTINCT entry from the general sign-in path — not a link
    // back to the same /login form.
    expect(href).not.toBe("/login");
  });
});
