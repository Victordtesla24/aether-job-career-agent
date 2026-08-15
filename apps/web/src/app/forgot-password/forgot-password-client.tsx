"use client";

/**
 * /forgot-password interactive UI — O-4 self-service password reset
 * (S-FIX slice D). Split from `page.tsx` (a server wrapper) purely so the
 * operator's support-contact env vars can be read at request time via
 * `getOperatorLegalConfig` (server-only `process.env` access — see that
 * function's docstring) and handed down as props, mirroring
 * `dashboard/settings`'s `SettingsClient` split.
 *
 * Submits POST /api/auth/forgot-password with the visitor's email. The
 * response is ALWAYS a 200 (anti-enumeration — it never reveals whether an
 * account exists for that address) with two honest signals:
 * ``emailSendingEnabled`` and ``deliveryDegraded``. When
 * ``emailSendingEnabled`` is true AND delivery is not degraded, a reset link
 * was genuinely attempted and the page shows the standard "check your
 * inbox" state. When ``emailSendingEnabled`` is false, no outbound-email
 * provider is configured on this deployment today, and the page falls back
 * to the PRE-EXISTING honest copy (MV-login-004): it does NOT claim an
 * email was sent, and instead points the visitor at the operator's support
 * contact so a manual reset can still happen. When ``emailSendingEnabled``
 * is true but ``deliveryDegraded`` is true (MF-3), a provider IS configured
 * but its most recent attempted send actually failed (bad credentials,
 * outage, unverified domain) — the page must NOT render the fake-success
 * "we've sent a link" copy in that case either, since nothing was
 * confirmed delivered.
 */
import Link from "next/link";
import { FormEvent, useState } from "react";

import PublicFooter from "../../components/PublicFooter";
import { AuthApiError, forgotPassword } from "../../lib/api/auth";

/** Optional "You can also call ..." tail, shared by both render branches (DEDUP-011). */
function SupportPhoneLine({ supportPhone }: { supportPhone: string | null }) {
  if (!supportPhone) return null;
  return (
    <>
      {" "}You can also call{" "}
      <a
        href={`tel:${supportPhone.replace(/[^\d+]/g, "")}`}
        className="text-aether-indigo hover:underline"
      >
        {supportPhone}
      </a>
      .
    </>
  );
}

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "sent" }
  | { status: "not-configured" }
  | { status: "degraded" }
  | { status: "error"; message: string };

export default function ForgotPasswordClient({
  supportEmail,
  supportPhone,
}: {
  supportEmail: string | null;
  supportPhone: string | null;
}) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState({ status: "submitting" });
    try {
      const result = await forgotPassword(email);
      if (!result.emailSendingEnabled) {
        setState({ status: "not-configured" });
      } else if (result.deliveryDegraded) {
        setState({ status: "degraded" });
      } else {
        setState({ status: "sent" });
      }
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
            <h1 className="text-lg font-semibold">Reset your password</h1>
            <p className="text-sm text-aether-muted mt-1">
              Enter the email address on your account and we&apos;ll send you a reset link.
            </p>
          </div>

          {state.status === "sent" ? (
            <p
              role="status"
              data-testid="forgot-password-sent"
              className="text-sm text-aether-green leading-relaxed"
            >
              If an account exists for that email, we&apos;ve sent a link to reset your password. It
              expires in 1 hour and can only be used once.
            </p>
          ) : state.status === "degraded" ? (
            <p
              role="status"
              data-testid="forgot-password-degraded"
              className="text-sm text-aether-muted leading-relaxed"
            >
              We&apos;re having trouble delivering reset emails right now, so we can&apos;t confirm one
              was sent.{" "}
              {supportEmail ? (
                <>
                  To regain access to your account, email{" "}
                  <a href={`mailto:${supportEmail}`} className="text-aether-indigo hover:underline">
                    {supportEmail}
                  </a>{" "}
                  from the address you registered with and we&apos;ll help you reset it.
                  <SupportPhoneLine supportPhone={supportPhone} />
                </>
              ) : (
                <>
                  Please try again shortly, or reach the operator through the channel described on
                  our{" "}
                  <Link href="/terms" className="text-aether-indigo hover:underline">
                    Terms
                  </Link>{" "}
                  page.
                  <SupportPhoneLine supportPhone={supportPhone} />
                </>
              )}
            </p>
          ) : state.status === "not-configured" ? (
            <p
              role="status"
              data-testid="forgot-password-not-configured"
              className="text-sm text-aether-muted leading-relaxed"
            >
              Self-service password reset isn&apos;t enabled yet on this deployment.{" "}
              {supportEmail ? (
                <>
                  To regain access to your account, email{" "}
                  <a href={`mailto:${supportEmail}`} className="text-aether-indigo hover:underline">
                    {supportEmail}
                  </a>{" "}
                  from the address you registered with and we&apos;ll help you reset it.
                  <SupportPhoneLine supportPhone={supportPhone} />
                </>
              ) : (
                <>
                  A support contact address has not yet been published for this service. Once the
                  operator configures one it will appear here; until then, please reach the operator
                  through the channel described on our{" "}
                  <Link href="/terms" className="text-aether-indigo hover:underline">
                    Terms
                  </Link>{" "}
                  page.
                  <SupportPhoneLine supportPhone={supportPhone} />
                </>
              )}
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Reset your password">
              <div className="flex flex-col gap-1.5 text-[13px] font-medium">
                <label htmlFor="forgot-password-email">Email</label>
                <input
                  id="forgot-password-email"
                  type="email"
                  name="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder:text-aether-muted-dim focus:outline-none focus:border-gold/60 transition"
                />
              </div>

              {state.status === "error" ? (
                <p role="alert" data-testid="forgot-password-error" className="text-sm text-red-300">
                  {state.message}
                </p>
              ) : null}

              <button
                type="submit"
                disabled={state.status === "submitting"}
                className="mt-1 rounded-xl bg-gradient-to-r from-gold to-gold-dark py-2.5 text-sm font-semibold text-[#0a0a0a] hover:opacity-90 transition disabled:opacity-50"
              >
                {state.status === "submitting" ? "Sending…" : "Send reset link"}
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
