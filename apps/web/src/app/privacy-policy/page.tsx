import type { Metadata } from "next";
import Link from "next/link";

import { getOperatorLegalConfig } from "../../lib/config/legal";

export const metadata: Metadata = {
  title: "Privacy Policy · Aether Career Agent",
  description:
    "How Aether Career Agent collects, uses, and protects your data.",
};

// Read the operator support-contact env var at request time, not baked in at
// build time (MV-privacy-policy-003, H-3 — see lib/config/legal.ts).
export const dynamic = "force-dynamic";

/**
 * Standalone public privacy policy page. It is intentionally NOT wrapped in the
 * dashboard layout so it is reachable without authentication — Google's OAuth
 * consent screen links directly here. The app name is rendered exactly as
 * "Aether Career Agent" to match the OAuth consent configuration.
 */
export default function PrivacyPolicyPage() {
  const { supportEmail, supportPhone } = getOperatorLegalConfig();

  return (
    <div className="min-h-screen bg-aether-bg text-aether-text">
      {/* Header */}
      <header className="border-b border-white/10 glass">
        <div className="mx-auto max-w-3xl px-6 py-5">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-3 group"
            aria-label="Back to Aether Career Agent dashboard"
          >
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-aether-coral to-aether-amber flex items-center justify-center shadow-lg shadow-aether-coral/30">
              <i className="fa-solid fa-bolt text-white text-sm" aria-hidden="true" />
            </div>
            <div>
              <div className="font-bold text-[15px] leading-none group-hover:text-white transition">
                Aether
              </div>
              <div className="text-[11px] text-aether-muted-dim mt-1">Career Agent</div>
            </div>
          </Link>
        </div>
      </header>

      {/* Body */}
      <main className="mx-auto max-w-3xl px-6 py-12">
        <div className="glass-raised rounded-2xl border border-white/10 p-8 md:p-10">
          <h1 className="text-3xl font-extrabold tracking-tight">Privacy Policy</h1>
          <p className="mt-2 text-sm text-aether-muted-dim mono">
            Last updated: July 16, 2026
          </p>

          <p className="mt-6 text-[15px] leading-relaxed text-aether-muted">
            This Privacy Policy explains how{" "}
            <strong className="text-aether-text">Aether Career Agent</strong>{" "}
            (&ldquo;Aether Career Agent&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;, or
            &ldquo;our&rdquo;) collects, uses, retains, and protects your information when
            you use our application. Aether Career Agent is billed in Australian dollars
            (AUD) with GST and is offered to an Australian market; this Policy is intended
            to comply with the{" "}
            <strong className="text-aether-text">Privacy Act 1988 (Cth)</strong> and the{" "}
            <strong className="text-aether-text">Australian Privacy Principles (APPs)</strong>{" "}
            (see §9 below). By using Aether Career Agent, you agree to the practices
            described below.
          </p>

          <Section title="1. Information We Collect">
            <p>We collect the following categories of information to operate the service:</p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>
                <strong className="text-aether-text">Account information</strong> — your
                email address and name, used to create and secure your account.
              </li>
              <li>
                <strong className="text-aether-text">Resume data</strong> — the resumes you
                upload or generate, including work history, skills, and contact details.
              </li>
              <li>
                <strong className="text-aether-text">Job applications</strong> — the roles
                you save, apply to, and track, along with their status and related notes.
              </li>
              <li>
                <strong className="text-aether-text">Subscription &amp; billing metadata</strong>{" "}
                — your selected plan (Free, Starter, Pro, or Power), billing interval,
                subscription status, and monthly agent-run usage, used to enforce plan
                limits and to bill you for paid plans.
              </li>
              <li>
                <strong className="text-aether-text">Gmail messages</strong> — if you
                connect your Google account, we access relevant email messages via the
                Gmail API strictly to help you manage job-related correspondence.
              </li>
              <li>
                <strong className="text-aether-text">Interview recordings</strong> —
                practice interview sessions and their transcripts, when you choose to use
                interview preparation features.
              </li>
              <li>
                <strong className="text-aether-text">Usage analytics</strong> — anonymized
                interaction data (such as features used and application activity) that helps
                us improve the product.
              </li>
            </ul>
          </Section>

          <Section title="2. How We Use Your Information">
            <p>We use your information solely to provide and improve Aether Career Agent:</p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>
                <strong className="text-aether-text">AI-powered job matching</strong> — to
                discover and rank roles that fit your experience and preferences.
              </li>
              <li>
                <strong className="text-aether-text">
                  Cover letter and resume generation
                </strong>{" "}
                — to tailor resumes and draft cover letters for specific roles.
              </li>
              <li>
                <strong className="text-aether-text">Email management</strong> — to
                organize, summarize, and draft responses to job-related messages in your
                connected inbox.
              </li>
              <li>
                <strong className="text-aether-text">Interview preparation</strong> — to
                generate practice questions and feedback based on your target roles.
              </li>
              <li>
                <strong className="text-aether-text">Analytics dashboard</strong> — to give
                you visibility into your application funnel and progress.
              </li>
            </ul>
          </Section>

          <Section title="3. Third-Party Services">
            <p>
              Aether Career Agent relies on a small number of trusted third-party services:
            </p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>
                <strong className="text-aether-text">Google Gmail API (OAuth2)</strong> —
                used, with your explicit consent, to read and manage job-related email.
                OAuth tokens are encrypted at rest, and access can be revoked at any time.
              </li>
              <li>
                <strong className="text-aether-text">Stripe</strong> — securely processes
                card payments for paid subscription plans. Card details are entered directly
                with Stripe (a PCI DSS Level 1 provider) and are never stored on our servers;
                we retain only your subscription status and billing metadata. See our{" "}
                <Link href="/terms" className="text-aether-coral hover:underline">
                  Terms &amp; Conditions
                </Link>{" "}
                for full pricing, GST, and billing details.
              </li>
              <li>
                <strong className="text-aether-text">LLM provider</strong> — large
                language model inference (our configured provider, currently OpenRouter)
                is used to generate resumes, cover letters, and interview material.
                Content is sent to this provider only as needed to produce your
                requested output.
              </li>
              <li>
                <strong className="text-aether-text">Hosted PostgreSQL database</strong> —
                your account and application data is stored in a single hosted
                PostgreSQL database.
              </li>
            </ul>
          </Section>

          <Section title="4. Data Retention">
            <ul className="list-disc space-y-2 pl-5">
              <li>Account data is retained for as long as your account remains active.</li>
              <li>
                A connected Gmail account can be disconnected at any time from the Email
                Center; disconnecting immediately deletes that account&rsquo;s stored
                (encrypted) tokens and stops all Gmail data access for that account.
              </li>
              <li>
                Full account data export or deletion is not yet a self-service, in-app
                feature (see &ldquo;Your Rights&rdquo; below) — there is no automatic
                deletion timeline guaranteed by the app; requests are handled manually by
                us.
              </li>
            </ul>
          </Section>

          <Section title="5. Your Rights">
            <p>You remain in control of your data.</p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>
                <strong className="text-aether-text">Correction (self-service)</strong> —
                you can correct inaccurate account, profile, or resume information
                directly in the app at any time.
              </li>
              <li>
                <strong className="text-aether-text">
                  Gmail access revocation (self-service)
                </strong>{" "}
                — you can disconnect any connected Gmail account at any time from the
                Email Center, which immediately deletes that account&rsquo;s stored
                tokens.
              </li>
              <li>
                <strong className="text-aether-text">
                  Data export or full account deletion
                </strong>{" "}
                — there is currently no self-service &ldquo;export my data&rdquo; or
                &ldquo;delete my account&rdquo; button in the app. To request an export
                or deletion of your data, contact us (see{" "}
                <strong className="text-aether-text">Contact</strong> below) and we will
                process your request manually.
              </li>
            </ul>
          </Section>

          <Section title="6. Security">
            <ul className="list-disc space-y-2 pl-5">
              <li>All data is encrypted in transit using TLS.</li>
              <li>
                OAuth tokens and any LLM provider API keys you supply are encrypted at
                rest (Fernet symmetric encryption) and stored server-side only, never
                exposed to the browser or third parties.
              </li>
              <li>
                Passwords are never stored in plaintext — they are one-way hashed
                (bcrypt).
              </li>
              <li>
                Login and registration are rate-limited to slow automated abuse; billing
                actions (checkout, billing portal) are separately rate-limited.
              </li>
              <li>
                No secrets or API keys are stored in our source code — they are
                configured through environment variables only.
              </li>
              <li>
                An administrator can suspend an account found to violate our Terms &amp;
                Conditions, which blocks that account&rsquo;s access until the
                suspension is lifted.
              </li>
            </ul>
          </Section>

          <Section title="7. Contact">
            <p>
              {supportEmail ? (
                <>
                  If you have questions about this Privacy Policy or how your data is
                  handled, or to request a data export or account deletion, email us at{" "}
                  <a
                    href={`mailto:${supportEmail}`}
                    className="text-aether-coral hover:underline"
                  >
                    {supportEmail}
                  </a>
                  {supportPhone ? (
                    <>
                      {" "}or call{" "}
                      <a
                        href={`tel:${supportPhone.replace(/[^\d+]/g, "")}`}
                        className="text-aether-coral hover:underline"
                      >
                        {supportPhone}
                      </a>
                    </>
                  ) : null}
                  .
                </>
              ) : (
                <>
                  A support contact address has not yet been published for this service.
                  Once the operator configures one, it will be shown here and used to
                  process questions about this Privacy Policy and data export/deletion
                  requests.
                  {supportPhone ? (
                    <>
                      {" "}In the meantime, you can call{" "}
                      <a
                        href={`tel:${supportPhone.replace(/[^\d+]/g, "")}`}
                        className="text-aether-coral hover:underline"
                      >
                        {supportPhone}
                      </a>
                      .
                    </>
                  ) : null}
                </>
              )}
            </p>
          </Section>

          <Section title="8. Changes to This Policy">
            <p>
              We may update this Privacy Policy from time to time. If we make material
              changes, we will notify you through an in-app notification so you are aware
              before the changes take effect.
            </p>
          </Section>

          <Section title="9. Australian Privacy Law">
            <p>
              Aether Career Agent is offered to an Australian market and handles personal
              information — including resume content, Gmail messages you choose to
              connect, and billing metadata — in a manner intended to comply with the{" "}
              <strong className="text-aether-text">Privacy Act 1988 (Cth)</strong> and the{" "}
              <strong className="text-aether-text">
                Australian Privacy Principles (APPs)
              </strong>{" "}
              that Act sets out. If you believe we have mishandled your personal
              information and are not satisfied with our response after contacting us (see
              §7 Contact above), you may lodge a complaint with the{" "}
              <strong className="text-aether-text">
                Office of the Australian Information Commissioner (OAIC)
              </strong>{" "}
              at{" "}
              <a
                href="https://www.oaic.gov.au"
                className="text-aether-coral hover:underline"
                target="_blank"
                rel="noreferrer"
              >
                oaic.gov.au
              </a>
              .
            </p>
          </Section>
        </div>

        <div className="mt-8 text-center">
          <Link
            href="/dashboard"
            className="text-sm text-aether-muted hover:text-white transition"
          >
            ← Back to Dashboard
          </Link>
        </div>
      </main>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-8">
      <h2 className="text-xl font-semibold text-aether-text">{title}</h2>
      <div className="mt-3 text-[15px] leading-relaxed text-aether-muted">{children}</div>
    </section>
  );
}
