/**
 * /forgot-password — an HONEST account-recovery affordance (MV-login-004).
 *
 * A real self-service reset requires transactional email infrastructure, which
 * is not confirmed available for this deployment, so this page deliberately
 * does NOT fake a reset flow. Instead it points the user at the operator's
 * support contact (the same env-backed value the /terms and /privacy-policy
 * pages use — lib/config/legal.ts), read at request time so it reflects the
 * live process environment. When no support address has been configured it
 * says so plainly rather than promising a channel that does not exist.
 */
import Link from "next/link";

import PublicFooter from "../../components/PublicFooter";
import { getOperatorLegalConfig } from "../../lib/config/legal";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Reset your password · Aether",
};

export default function ForgotPasswordPage() {
  const { supportEmail, supportPhone } = getOperatorLegalConfig();

  return (
    <main className="min-h-screen flex items-center justify-center bg-aether-bg px-4">
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-aether-indigo to-aether-violet flex items-center justify-center text-lg font-bold">
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
              Self-service password reset isn&apos;t available yet.
            </p>
          </div>

          {supportEmail ? (
            <p className="text-sm text-aether-muted leading-relaxed">
              To regain access to your account, email{" "}
              <a href={`mailto:${supportEmail}`} className="text-aether-indigo hover:underline">
                {supportEmail}
              </a>{" "}
              from the address you registered with and we&apos;ll help you reset it.
              {supportPhone ? (
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
              ) : null}
            </p>
          ) : (
            <p className="text-sm text-aether-muted leading-relaxed">
              A support contact address has not yet been published for this service. Once the
              operator configures one it will appear here so you can request a password reset;
              until then, please reach the operator through the channel described on our{" "}
              <Link href="/terms" className="text-aether-indigo hover:underline">
                Terms
              </Link>{" "}
              page.
              {supportPhone ? (
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
              ) : null}
            </p>
          )}

          <Link
            href="/login"
            className="mt-1 rounded-xl bg-gradient-to-r from-aether-indigo to-aether-violet py-2.5 text-sm font-semibold text-center hover:opacity-90 transition"
          >
            Back to sign in
          </Link>
        </div>

        <PublicFooter />
      </div>
    </main>
  );
}
