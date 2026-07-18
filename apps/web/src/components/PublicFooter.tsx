import Link from "next/link";

/**
 * Shared legal-links row for public, unauthenticated pages — MV-terms-001 /
 * MV-privacy-policy-001. Before this, /login, /signup, and /pricing had no
 * link to /privacy-policy or /terms anywhere (confirmed via full DOM anchor
 * enumeration), so a prospective user had no in-context way to reach either
 * document before creating an account or paying. Mirrors the equivalent
 * authenticated sidebar footer (components/sidebar.tsx: "Privacy Policy ·
 * Terms · © 2026 Aether") so the same courtesy applies pre-authentication.
 */
export default function PublicFooter() {
  return (
    <footer
      data-testid="public-legal-footer"
      className="mt-10 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[11px] text-aether-muted-dim"
    >
      <Link href="/privacy-policy" className="hover:text-white transition">
        Privacy Policy
      </Link>
      <span aria-hidden="true">·</span>
      <Link href="/terms" className="hover:text-white transition">
        Terms
      </Link>
      <span aria-hidden="true">·</span>
      <span>&copy; 2026 Aether</span>
    </footer>
  );
}
