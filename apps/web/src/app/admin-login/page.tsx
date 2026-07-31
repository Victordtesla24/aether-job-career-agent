"use client";

/**
 * /admin-login — GOLD-MASTER-V2 §9.2.1/§9.2.2 admin sign-in entry point.
 *
 * Deliberately kept OUTSIDE the app/admin/* directory tree (a sibling route,
 * not /admin/login) for two independent reasons:
 *
 * 1. Every /admin/* route is wrapped by app/admin/layout.tsx's AdminGuard,
 *    which immediately bounces an unauthenticated visitor to /login before
 *    they could ever see a sign-in form — nesting this page there would
 *    require special-casing the guard for its own entry point.
 * 2. wg-admin-login-path.spec.ts asserts the post-login redirect via
 *    `page.waitForURL(/\/admin(\/|$|\?)/, ...)`. Playwright resolves
 *    `waitForURL` immediately if the CURRENT url already matches — so an
 *    entry page literally at "/admin/login" would satisfy that regex (it
 *    contains the "/admin/" substring) the instant the visitor arrives,
 *    before the form is ever submitted, making the wait a no-op instead of
 *    a genuine assertion that login landed on /admin. "/admin-login" starts
 *    with "/admin" (satisfying §9.2.1's own contract, verified by
 *    wg-admin-entry-004.test.tsx) without colliding with that pattern.
 *
 * Not a separate backend "admin login" endpoint or credential class either —
 * it posts to the exact same POST /auth/login as the general /login form
 * (identifier + password, either email or username, per the existing
 * `login()` client in lib/api/auth.ts) and stores the token under the same
 * `aether_token` key. The only difference from /login is the post-login
 * destination: /admin instead of /dashboard.
 *
 * Authorization itself is never decided here. A successful generic login
 * (of ANY account, admin or not) always routes to /admin; AdminGuard
 * (apps/web/src/components/admin/admin-guard.tsx) is what resolves
 * `isAdmin` live from /auth/me — the same already-existing source used
 * everywhere else in the app — and quietly redirects a non-admin on to
 * /dashboard with no admin-specific denial text. That is deliberate: a
 * distinct "you are not an administrator" message here would leak, to
 * anyone who tries a real (non-admin) account, that those credentials are
 * valid — a user-enumeration-adjacent signal (§9.2.2's own honest-refusal
 * requirement). This page and AdminGuard therefore never need to know about
 * (or depend on) any specific credential identifier.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { AuthApiError, login } from "../../lib/api/auth";

const TOKEN_STORAGE_KEY = "aether_token";

export default function AdminLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const session = await login(email, password);
      window.localStorage.setItem(TOKEN_STORAGE_KEY, session.accessToken);
      router.push("/admin");
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : "Could not reach the API. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-aether-bg px-4">
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-aether-indigo to-aether-violet flex items-center justify-center text-lg font-bold">
            A
          </div>
          <div>
            <div className="text-xl font-semibold tracking-tight">Aether</div>
            <div className="text-[11px] text-aether-muted-dim mono">admin console</div>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="glass rounded-2xl border border-white/10 p-8 flex flex-col gap-5"
          aria-label="Admin sign in"
        >
          <div>
            <h1 className="text-lg font-semibold">Admin sign in</h1>
            <p className="text-sm text-aether-muted mt-1">
              Restricted to platform administrators.
            </p>
          </div>

          <div className="flex flex-col gap-1.5 text-[13px] font-medium">
            <label htmlFor="admin-login-identifier">Email or username</label>
            <input
              id="admin-login-identifier"
              type="text"
              name="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
            />
          </div>

          <div className="flex flex-col gap-1.5 text-[13px] font-medium">
            <label htmlFor="admin-login-password">Password</label>
            <input
              id="admin-login-password"
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
            />
          </div>

          {error ? (
            <p role="alert" data-testid="admin-login-error" className="text-sm text-aether-coral">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className="mt-1 rounded-xl bg-gradient-to-r from-aether-indigo to-aether-violet py-2.5 text-sm font-semibold hover:opacity-90 transition disabled:opacity-50"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>

          <p className="text-sm text-aether-muted text-center">
            <Link href="/login" className="text-aether-indigo hover:underline">
              Back to sign in
            </Link>
          </p>
        </form>
      </div>
    </main>
  );
}
