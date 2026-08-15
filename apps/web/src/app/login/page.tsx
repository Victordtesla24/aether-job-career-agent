"use client";

/**
 * /login — identifier (email; a legacy username value is still accepted by the API) + password sign-in against
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
  // H-04/M-01: /pricing forwards an unauthenticated visitor here with the plan
  // + interval they chose. We surface which plan they're signing in for and
  // send them back to /pricing (with the interval preselected) afterwards, so
  // the selection survives the login round-trip.
  const [planContext, setPlanContext] = useState<{ plan: string; interval: string } | null>(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setJustRegistered(params.get("registered") === "1");
    const planParam = params.get("plan");
    // Confine to the known plan ids; anything else is ignored (this value is
    // URL-controllable and only ever drives display + a same-origin /pricing
    // return, never a charge).
    const knownPlans = ["starter", "pro", "power"];
    let dest = safeNextPath(params.get("next"));
    if (planParam && knownPlans.includes(planParam)) {
      const interval = params.get("interval") === "year" ? "year" : "month";
      setPlanContext({ plan: planParam, interval });
      dest = `/pricing?plan=${planParam}&interval=${interval}`;
    }
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
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-gold to-gold-dark flex items-center justify-center text-lg font-bold text-[#0a0a0a]">
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

          {planContext ? (
            <p
              role="status"
              data-testid="login-plan-context"
              className="rounded-lg border border-aether-indigo/30 bg-aether-indigo/10 px-3 py-2 text-sm text-aether-indigo"
            >
              Sign in to continue subscribing to the{" "}
              <span className="font-semibold capitalize">{planContext.plan}</span> plan
              {planContext.interval === "year" ? " (billed annually)" : ""}.
            </p>
          ) : null}

          <div className="flex flex-col gap-1.5 text-[13px] font-medium">
            <label htmlFor="login-identifier">Email</label>
            <input
              id="login-identifier"
              type="text"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-gold/60 transition"
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
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-gold/60 transition"
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
            <p role="alert" data-testid="login-error" className="text-sm text-red-300">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className="mt-1 rounded-xl bg-gradient-to-r from-gold to-gold-dark py-2.5 text-sm font-semibold text-[#0a0a0a] hover:opacity-90 transition disabled:opacity-50"
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

        {/*
          GOLD-MASTER-V2 §9.2.1: a distinct, clearly-labelled entry point into
          the admin sign-in path (/admin-login — see that route's own file
          header for why it is a sibling of /admin/* rather than nested
          under it), deliberately kept visually minor (small, muted, below
          the main sign-in card) so it reads as a secondary/administrative
          affordance rather than inviting a normal user to try it — matching
          the same subdued idiom PublicFooter below already uses for the
          legal links.

          A plain <a>, not next/link's <Link>, is deliberate: this crosses a
          trust boundary (general session -> admin sign-in) and a real
          top-level navigation guarantees the general /login form is fully
          torn down before the admin form can receive input — a Link's
          client-side transition briefly leaves BOTH forms' identically
          labelled fields ("Email" / "Password") resolvable at
          once, so a fast fill+submit (automation, or just a quick typist)
          can race the transition and submit the wrong form entirely.
        */}
        <div className="mt-4 text-center">
          <a
            href="/admin-login"
            className="text-[11px] text-aether-muted-dim hover:text-aether-muted transition"
          >
            Admin sign in
          </a>
        </div>

        <PublicFooter />
      </div>
    </main>
  );
}
