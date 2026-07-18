"use client";

/**
 * /login — identifier (email or username) + password sign-in against
 * POST /api/auth/login (the backend accepts either credential — GAP
 * FEATURE CONTRACT). A successful login stores the JWT under the same
 * `aether_token` localStorage key the shared API client uses before
 * redirecting to /dashboard.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import PublicFooter from "../../components/PublicFooter";
import { AuthApiError, login } from "../../lib/api/auth";
import { safeNextPath } from "../../lib/auth/next-path";

const TOKEN_STORAGE_KEY = "aether_token";

export default function LoginPage() {
  const router = useRouter();
  // Read client-side only (no Suspense boundary needed for a static page,
  // unlike useSearchParams) — set by /signup when a fresh account's
  // auto-login didn't complete, so the account exists but the user still
  // needs to sign in.
  const [justRegistered, setJustRegistered] = useState(false);
  // The validated post-login destination — /dashboard, or the deep-link the
  // visitor was sent to /login from (MV-login-002).
  const [nextPath, setNextPath] = useState("/dashboard");
  const [redirecting, setRedirecting] = useState(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setJustRegistered(params.get("registered") === "1");
    const dest = safeNextPath(params.get("next"));
    setNextPath(dest);
    // Already signed in? Don't re-present the form — forward to the intended
    // destination (MV-login-001 / MV-login-002).
    if (window.localStorage.getItem(TOKEN_STORAGE_KEY)) {
      setRedirecting(true);
      router.replace(dest);
    }
  }, [router]);
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const session = await login(email, password);
      window.localStorage.setItem(TOKEN_STORAGE_KEY, session.accessToken);
      router.push(nextPath);
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : "Could not reach the API. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (redirecting) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-aether-bg px-4">
        <p className="text-sm text-aether-muted">Redirecting…</p>
      </main>
    );
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
            <div className="text-[11px] text-aether-muted-dim mono">
              job &amp; career agent
            </div>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="glass rounded-2xl border border-white/10 p-8 flex flex-col gap-5"
          aria-label="Sign in"
        >
          <div>
            <h1 className="text-lg font-semibold">Sign in</h1>
            <p className="text-sm text-aether-muted mt-1">
              Access your agent dashboard.
            </p>
          </div>

          {justRegistered ? (
            <p role="status" data-testid="signup-success" className="text-sm text-aether-green">
              Account created — sign in to continue.
            </p>
          ) : null}

          <div className="flex flex-col gap-1.5 text-[13px] font-medium">
            <label htmlFor="login-identifier">Email or username</label>
            <input
              id="login-identifier"
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
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
            />
            <div className="text-right">
              <Link
                href="/forgot-password"
                className="text-xs text-aether-muted hover:text-aether-indigo hover:underline"
              >
                Forgot password?
              </Link>
            </div>
          </div>

          {error ? (
            <p role="alert" data-testid="login-error" className="text-sm text-aether-coral">
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
            Don&apos;t have an account?{" "}
            <Link href="/signup" className="text-aether-indigo hover:underline">
              Create account
            </Link>
          </p>
        </form>

        <PublicFooter />
      </div>
    </main>
  );
}
