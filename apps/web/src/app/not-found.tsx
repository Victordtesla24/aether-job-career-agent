import Link from "next/link";

import { getOperatorLegalConfig } from "../lib/config/legal";

// Read AETHER_SUPPORT_EMAIL at request time, not baked in at build time —
// same convention as /privacy-policy, /terms, /forgot-password (lib/config/legal.ts).
export const dynamic = "force-dynamic";

export const metadata = {
  title: "Page not found · Aether",
};

/**
 * Root app/not-found.tsx (O-5, S-FIX slice C).
 *
 * Next.js renders this for any route with no matching page — e.g. a typo'd
 * URL — anywhere in the app. Before this, no top-level not-found.tsx
 * existed, so a bogus route fell through to Next.js's stock, unbranded 404
 * with no path back into the app or to support. Honest, like the rest of
 * lib/config/legal.ts's consumers: a real mailto contact when
 * AETHER_SUPPORT_EMAIL is configured, otherwise a link to the Privacy
 * Policy's own live Contact section — never a fabricated address.
 */
export default function NotFound() {
  const { supportEmail } = getOperatorLegalConfig();

  return (
    <div className="min-h-screen flex items-center justify-center bg-aether-bg text-aether-text px-4">
      <div className="w-full max-w-md text-center">
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-aether-coral to-aether-amber shadow-lg shadow-aether-coral/30">
          <i className="fa-solid fa-bolt text-white text-xl" aria-hidden="true" />
        </div>
        <p className="mono text-sm text-aether-muted-dim">404</p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">Page not found</h1>
        <p className="mt-3 text-sm text-aether-muted leading-relaxed">
          The page you&rsquo;re looking for doesn&rsquo;t exist or may have moved.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          {/*
            "/" is the session-aware landing (see app/page.tsx): it routes an
            authenticated visitor straight to /dashboard and an anonymous one
            to /pricing, so one link here is correct for both — a direct
            /dashboard link would bounce a logged-out visitor through
            AuthGuard first.
          */}
          <Link
            href="/"
            className="rounded-xl bg-gradient-to-r from-gold to-gold-dark px-4 py-2 text-sm font-semibold text-[#0a0a0a] transition hover:opacity-90"
          >
            Go home
          </Link>
        </div>
        <p className="mt-6 text-xs text-aether-muted-dim">
          {supportEmail ? (
            <>
              Still stuck?{" "}
              <a href={`mailto:${supportEmail}`} className="text-aether-coral hover:underline">
                Contact support
              </a>
              .
            </>
          ) : (
            <>
              Still stuck? See the{" "}
              <Link href="/privacy-policy" className="text-aether-coral hover:underline">
                contact section
              </Link>{" "}
              of our Privacy Policy.
            </>
          )}
        </p>
      </div>
    </div>
  );
}
