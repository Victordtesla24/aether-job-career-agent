import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy · Aether Career Agent",
  description:
    "How Aether Career Agent collects, uses, and protects your data.",
};

/**
 * Standalone public privacy policy page. It is intentionally NOT wrapped in the
 * dashboard layout so it is reachable without authentication — Google's OAuth
 * consent screen links directly here. The app name is rendered exactly as
 * "Aether Career Agent" to match the OAuth consent configuration.
 */
export default function PrivacyPolicyPage() {
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
            Last updated: July 11, 2026
          </p>

          <p className="mt-6 text-[15px] leading-relaxed text-aether-muted">
            This Privacy Policy explains how{" "}
            <strong className="text-aether-text">Aether Career Agent</strong>{" "}
            (&ldquo;Aether Career Agent&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;, or
            &ldquo;our&rdquo;) collects, uses, retains, and protects your information when
            you use our application. By using Aether Career Agent, you agree to the
            practices described below.
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
                Access can be revoked at any time.
              </li>
              <li>
                <strong className="text-aether-text">AI model providers</strong> — large
                language model inference is used to generate resumes, cover letters, and
                interview material. Content is sent to these providers only as needed to
                produce your requested output.
              </li>
              <li>
                <strong className="text-aether-text">PostgreSQL database hosting</strong> —
                your account and application data is stored in a managed PostgreSQL database.
              </li>
            </ul>
          </Section>

          <Section title="4. Data Retention">
            <ul className="list-disc space-y-2 pl-5">
              <li>Account data is retained for as long as your account remains active.</li>
              <li>
                Gmail access tokens are revocable at any time from the{" "}
                <strong className="text-aether-text">Settings</strong> page; revoking access
                immediately stops all Gmail data access.
              </li>
              <li>
                Upon an account deletion request, your data is permanently deleted within 30
                days.
              </li>
            </ul>
          </Section>

          <Section title="5. Your Rights">
            <p>You remain in control of your data. At any time you can:</p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>Access and export the data associated with your account.</li>
              <li>Correct inaccurate account or resume information.</li>
              <li>
                Delete your data via the{" "}
                <strong className="text-aether-text">Settings</strong> page.
              </li>
              <li>Revoke Gmail access at any time, independently of your account.</li>
            </ul>
          </Section>

          <Section title="6. Security">
            <ul className="list-disc space-y-2 pl-5">
              <li>All data is encrypted in transit using TLS.</li>
              <li>Stored data is encrypted at rest.</li>
              <li>
                OAuth tokens are stored server-side only and are never exposed to the
                browser or third parties.
              </li>
            </ul>
          </Section>

          <Section title="7. Contact">
            <p>
              If you have questions about this Privacy Policy or how your data is handled,
              you can reach us via the{" "}
              <strong className="text-aether-text">Settings</strong> page or the in-app
              support channel.
            </p>
          </Section>

          <Section title="8. Changes to This Policy">
            <p>
              We may update this Privacy Policy from time to time. If we make material
              changes, we will notify you through an in-app notification so you are aware
              before the changes take effect.
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
