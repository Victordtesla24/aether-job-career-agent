"use client";

/**
 * /signup — open self-registration against POST /api/auth/register
 * (FEATURE CONTRACT: name/email/password, client validation mirroring the
 * server's password policy, honest 409/429 handling).
 *
 * On success (201) the same credentials are used to auto-login so the new
 * user lands straight on /dashboard without retyping anything. If that
 * auto-login call unexpectedly fails (the account is real either way — it
 * was just created), we fall back to /login with a success flash rather
 * than stranding the user on a dead-end error.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { validateSignupForm, type SignupFormErrors } from "../../components/auth/validation";
import { AuthApiError, login, registerAccount } from "../../lib/api/auth";

const TOKEN_STORAGE_KEY = "aether_token";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<SignupFormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const errors = validateSignupForm({ name, email, password });
    setFieldErrors(errors);
    if (errors.email || errors.password) {
      return;
    }

    setSubmitting(true);
    try {
      await registerAccount({ email, password, name: name.trim() || undefined });

      // Auto-login with the same credentials, then go straight to the
      // dashboard. The account now exists regardless of what happens next.
      try {
        const session = await login(email, password);
        window.localStorage.setItem(TOKEN_STORAGE_KEY, session.accessToken);
        router.push("/dashboard");
      } catch {
        router.push("/login?registered=1");
      }
    } catch (err) {
      if (err instanceof AuthApiError) {
        setFormError(err.message);
      } else {
        setFormError("Could not reach the API. Please try again.");
      }
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
          aria-label="Create account"
          noValidate
        >
          <div>
            <h1 className="text-lg font-semibold">Create account</h1>
            <p className="text-sm text-aether-muted mt-1">
              Set up your own agent workspace.
            </p>
          </div>

          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Name (optional)
            <input
              type="text"
              name="name"
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
            />
          </label>

          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Email
            <input
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={fieldErrors.email ? true : undefined}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
            />
            {fieldErrors.email ? (
              <span role="alert" className="text-xs text-aether-coral">
                {fieldErrors.email}
              </span>
            ) : null}
          </label>

          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Password
            <input
              type="password"
              name="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={fieldErrors.password ? true : undefined}
              className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-aether-indigo/50 transition"
            />
            <span className="text-xs text-aether-muted-dim">
              At least 8 characters, including a digit.
            </span>
            {fieldErrors.password ? (
              <span role="alert" className="text-xs text-aether-coral">
                {fieldErrors.password}
              </span>
            ) : null}
          </label>

          {formError ? (
            <p role="alert" data-testid="signup-error" className="text-sm text-aether-coral">
              {formError}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className="mt-1 rounded-xl bg-gradient-to-r from-aether-indigo to-aether-violet py-2.5 text-sm font-semibold hover:opacity-90 transition disabled:opacity-50"
          >
            {submitting ? "Creating account…" : "Create account"}
          </button>

          <p className="text-sm text-aether-muted text-center">
            Already have an account?{" "}
            <Link href="/login" className="text-aether-indigo hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </main>
  );
}
