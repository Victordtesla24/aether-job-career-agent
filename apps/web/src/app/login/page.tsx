"use client";

/**
 * /login — email+password sign-in against POST /api/auth/login.
 *
 * The deployed environment is a demo: the form is prefilled with the seeded
 * demo account, and a successful login stores the JWT under the same
 * `aether_token` localStorage key the shared API client uses before
 * redirecting to /dashboard.
 */
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { apiBaseUrl, DEMO_CREDENTIALS } from "../../lib/api/client";

const TOKEN_STORAGE_KEY = "aether_token";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string>(DEMO_CREDENTIALS.email);
  const [password, setPassword] = useState<string>(DEMO_CREDENTIALS.password);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch(`${apiBaseUrl()}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        setError(
          res.status === 401
            ? "Invalid email or password."
            : `Login failed (${res.status}). Please try again.`,
        );
        return;
      }
      const body = (await res.json()) as { access_token: string };
      window.localStorage.setItem(TOKEN_STORAGE_KEY, body.access_token);
      router.push("/dashboard");
    } catch {
      setError("Could not reach the API. Please try again.");
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

          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Email
            <input
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
            />
          </label>

          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Password
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
            />
          </label>

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

          <p className="text-[12px] text-aether-muted-dim leading-relaxed">
            <i className="fa-solid fa-circle-info mr-1.5" aria-hidden />
            Demo environment — credentials are prefilled with the seeded demo
            account (<span className="mono">demo@aether.dev</span>). No real
            personal data is stored.
          </p>
        </form>
      </div>
    </main>
  );
}
