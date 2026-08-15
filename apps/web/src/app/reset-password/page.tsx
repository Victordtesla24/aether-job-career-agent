"use client";

/**
 * /reset-password?token=... — O-4 self-service password reset completion
 * (S-FIX slice D).
 *
 * Reads ``token`` from the URL client-side via ``window.location.search``
 * (mirroring /login's convention — see that page's comment: no Suspense
 * boundary needed for a static page, unlike ``useSearchParams``). Submits
 * POST /api/auth/reset-password with the token + new password; on success,
 * redirects to /login (the reset invalidates every existing session token,
 * so the user must sign in again with the new password — there is no
 * auto-login here, matching /signup's existing convention).
 */
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import PublicFooter from "../../components/PublicFooter";
import { AuthApiError, resetPassword } from "../../lib/api/auth";

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success" }
  | { status: "error"; message: string };

export default function ResetPasswordPage() {
  const [token, setToken] = useState<string | null>(null);
  const [tokenChecked, setTokenChecked] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setToken(params.get("token"));
    setTokenChecked(true);
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    if (password !== confirmPassword) {
      setState({ status: "error", message: "Passwords do not match." });
      return;
    }
    setState({ status: "submitting" });
    try {
      await resetPassword(token, password);
      setState({ status: "success" });
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof AuthApiError ? err.message : "Could not reach the API. Please try again.",
      });
    }
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
            <div className="text-[11px] text-aether-muted-dim mono">job &amp; career agent</div>
          </div>
        </div>

        <div className="glass rounded-2xl border border-white/10 p-8 flex flex-col gap-5">
          <div>
            <h1 className="text-lg font-semibold">Choose a new password</h1>
          </div>

          {!tokenChecked ? null : !token ? (
            <p role="alert" data-testid="reset-password-missing-token" className="text-sm text-red-300 leading-relaxed">
              This reset link is missing its token.{" "}
              <Link href="/forgot-password" className="text-aether-indigo hover:underline">
                Request a new one
              </Link>
              .
            </p>
          ) : state.status === "success" ? (
            <div className="flex flex-col gap-4">
              <p role="status" data-testid="reset-password-success" className="text-sm text-aether-green leading-relaxed">
                Your password has been reset. Please sign in with your new password.
              </p>
              <Link
                href="/login"
                className="rounded-xl bg-gradient-to-r from-gold to-gold-dark py-2.5 text-sm font-semibold text-[#0a0a0a] text-center hover:opacity-90 transition"
              >
                Go to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Choose a new password">
              <div className="flex flex-col gap-1.5 text-[13px] font-medium">
                <label htmlFor="reset-password-new">New password</label>
                <input
                  id="reset-password-new"
                  type="password"
                  name="password"
                  autoComplete="new-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-gold/60 transition"
                />
              </div>

              <div className="flex flex-col gap-1.5 text-[13px] font-medium">
                <label htmlFor="reset-password-confirm">Confirm new password</label>
                <input
                  id="reset-password-confirm"
                  type="password"
                  name="confirmPassword"
                  autoComplete="new-password"
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-gold/60 transition"
                />
              </div>

              {state.status === "error" ? (
                <p role="alert" data-testid="reset-password-error" className="text-sm text-red-300">
                  {state.message}
                </p>
              ) : null}

              <button
                type="submit"
                disabled={state.status === "submitting"}
                className="mt-1 rounded-xl bg-gradient-to-r from-gold to-gold-dark py-2.5 text-sm font-semibold text-[#0a0a0a] hover:opacity-90 transition disabled:opacity-50"
              >
                {state.status === "submitting" ? "Resetting…" : "Reset password"}
              </button>
            </form>
          )}

          <Link
            href="/login"
            className="text-xs text-aether-muted hover:text-aether-indigo hover:underline text-center"
          >
            Back to sign in
          </Link>
        </div>

        <PublicFooter />
      </div>
    </main>
  );
}
