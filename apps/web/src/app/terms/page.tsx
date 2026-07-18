import type { Metadata } from "next";
import Link from "next/link";

import { getOperatorLegalConfig } from "../../lib/config/legal";

export const metadata: Metadata = {
  title: "Terms & Conditions · Aether Career Agent",
  description:
    "The terms and conditions governing your use of Aether Career Agent.",
};

// Read the operator identity/contact env vars at request time, not baked in
// at build time (MV-terms-002/003, H-3 — see lib/config/legal.ts).
export const dynamic = "force-dynamic";

/**
 * Standalone public terms & conditions page. It is intentionally NOT wrapped in
 * the dashboard layout so it is reachable without authentication. The app name
 * is rendered exactly as "Aether Career Agent" to match the OAuth consent
 * configuration and the privacy policy page.
 */
export default function TermsPage() {
  const { businessName, abn, supportEmail } = getOperatorLegalConfig();

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
          <h1 className="text-3xl font-extrabold tracking-tight">Terms &amp; Conditions</h1>
          <p className="mt-2 text-sm text-aether-muted-dim mono">
            Last updated: July 16, 2026
          </p>

          <p className="mt-6 text-[15px] leading-relaxed text-aether-muted">
            These Terms &amp; Conditions (&ldquo;Terms&rdquo;) govern your access to and use of{" "}
            <strong className="text-aether-text">Aether Career Agent</strong>{" "}
            (&ldquo;Aether Career Agent&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;, or
            &ldquo;our&rdquo;). Please read them carefully before using the service.
          </p>

          <Section title="1. Acceptance of Terms">
            <p>
              By accessing or using Aether Career Agent, you acknowledge that you have read,
              understood, and agree to be bound by these Terms and our Privacy Policy. If you do
              not agree with any part of these Terms, you must not access or use the service.
            </p>
          </Section>

          <Section title="2. Description of Service">
            <p>
              Aether Career Agent is an AI-powered career management platform. Its features
              include:
            </p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>Autonomous job discovery and role matching across multiple job boards.</li>
              <li>AI-assisted resume enhancement and cover letter generation.</li>
              <li>
                Email management for job-related correspondence via Gmail OAuth (optional).
              </li>
              <li>Interview preparation with practice questions and feedback.</li>
              <li>Application tracking and status management.</li>
              <li>Networking CRM to organize professional contacts.</li>
              <li>Analytics on your application funnel and progress.</li>
            </ul>
          </Section>

          <Section title="3. Eligibility">
            <p>
              You must be at least 18 years of age to use Aether Career Agent. By using the
              service, you represent that you have the legal right to work in any jurisdiction in
              which you apply to jobs through the platform, and that all information you provide
              is accurate and lawful.
            </p>
          </Section>

          <Section title="4. User Accounts">
            <ul className="list-disc space-y-2 pl-5">
              <li>
                You are responsible for maintaining the confidentiality of your account
                credentials and for all activity that occurs under your account.
              </li>
              <li>
                Demo accounts are provided for evaluation purposes only and may be reset or
                removed at any time.
              </li>
              <li>
                You must not share your login credentials with any third party or allow others to
                access your account.
              </li>
            </ul>
          </Section>

          <Section title="5. Subscription Plans &amp; Pricing">
            <p>
              Aether Career Agent is offered on four plans, priced in Australian dollars (AUD)
              and inclusive of the 10% Goods and Services Tax (GST):
            </p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>
                <strong className="text-aether-text">Free</strong> — A$0/month · 5 agent runs
                per month.
              </li>
              <li>
                <strong className="text-aether-text">Starter</strong> — A$19/month or
                A$179/year · 30 agent runs per month.
              </li>
              <li>
                <strong className="text-aether-text">Pro</strong> — A$39/month or A$359/year ·
                100 agent runs per month.
              </li>
              <li>
                <strong className="text-aether-text">Power</strong> — A$69/month or A$649/year
                · 300 agent runs per month.
              </li>
            </ul>
            <p className="mt-4">
              <strong className="text-aether-text">GST disclosure:</strong> all prices above are
              GST-inclusive. The GST component of any price is computed as{" "}
              <code className="text-aether-text">gst = round(total / 11, 2)</code>, with the net
              (ex-GST) amount equal to the total minus the GST. This computation is shown on
              every invoice and is available for each plan from the pricing page.
            </p>
            <p className="mt-4">
              Tax invoices require a registered Australian Business Number. Aether Career Agent
              is operated by <strong className="text-aether-text">{businessName}</strong>
              {abn ? (
                <>
                  {" "}(ABN <strong className="text-aether-text">{abn}</strong>).
                </>
              ) : (
                <>
                  . An Australian Business Number has not yet been published for this entity;
                  once the operator configures one, it will appear here and on GST tax invoices.
                </>
              )}
            </p>
          </Section>

          <Section title="6. Billing Cycle &amp; Payment">
            <ul className="list-disc space-y-2 pl-5">
              <li>You choose monthly or annual billing at checkout for any paid plan.</li>
              <li>
                Payment is processed by Stripe; the current billing period and renewal are
                managed by Stripe and kept in sync with your Aether account automatically.
              </li>
              <li>
                <strong className="text-aether-text">
                  Live payment processing is not yet active
                </strong>{" "}
                in production. Going live requires the operator to complete Stripe account
                setup (secret key, product/price configuration, and webhook registration).
                Until then, starting checkout or opening the billing portal returns an honest
                error rather than pretending to process a payment.
              </li>
            </ul>
          </Section>

          <Section title="7. Agent-Run Quota">
            <p>
              Each plan includes a monthly quota of metered agent runs — actions that invoke the
              LLM, such as resume tailoring, cover letter drafting, story extraction, and email
              drafting (see the plan quotas in §5 above: 5 agent runs per month on Free, 30
              agent runs per month on Starter, 100 agent runs per month on Pro, and 300 agent
              runs per month on Power).
            </p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>
                Your quota resets automatically at the start of each billing period — no
                manual action is needed.
              </li>
              <li>
                When your quota is exhausted, further metered runs are blocked and the app will
                prompt you to upgrade your plan.
              </li>
              <li>
                A run that fails or errors does not count against your quota.
              </li>
            </ul>
          </Section>

          <Section title="8. Cancellation">
            <p>
              You can manage or cancel a paid subscription at any time through the{" "}
              <strong className="text-aether-text">Stripe Billing Portal</strong> (&ldquo;Manage
              billing&rdquo; from your dashboard). From the portal you can change plan, update
              your payment method, or cancel.
            </p>
            <p className="mt-3">
              Cancellation takes effect at the end of your current billing period — you keep
              your plan&rsquo;s access (run quota and model tier) through that date; there is no
              pro-rated mid-period cutoff. When the period ends, your account is automatically
              moved to the Free plan.
            </p>
          </Section>

          <Section title="9. Refunds">
            <p>
              No automated refund flow is built into the service. There is no self-service
              &ldquo;request a refund&rdquo; option. Refund requests are handled manually, on a
              case-by-case basis, by the operator via the contact method in §18 (Contact) below;
              this page does not itself guarantee any specific refund outcome.
            </p>
          </Section>

          <Section title="10. Acceptable Use">
            <p>When using Aether Career Agent, you agree that you will not:</p>
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>
                Perform automated scraping or data extraction beyond the functionality the app
                provides.
              </li>
              <li>Submit fraudulent, misleading, or spam job applications.</li>
              <li>
                Misrepresent your qualifications, experience, or credentials in any AI-generated
                documents.
              </li>
              <li>
                Reverse engineer, decompile, or attempt to derive the source code of the platform
                or its AI models.
              </li>
              <li>
                Circumvent your plan&rsquo;s agent-run quota by any technical means.
              </li>
              <li>
                Share your account credentials or a single paid subscription across multiple
                distinct users.
              </li>
              <li>Use the service for any unlawful purpose or in violation of any applicable law.</li>
            </ul>
          </Section>

          <Section title="11. Gmail &amp; Third-Party Integrations">
            <ul className="list-disc space-y-2 pl-5">
              <li>Gmail access is entirely optional and is never required to use the service.</li>
              <li>
                If you connect your Google account, you grant Aether Career Agent permission to
                read, send, and modify emails solely to operate the Email Center feature.
              </li>
              <li>
                You may revoke Gmail access at any time from the Email Center.
              </li>
              <li>We do not sell or share your email content with any third party.</li>
            </ul>
          </Section>

          <Section title="12. AI-Generated Content">
            <p>
              Resume enhancements, cover letters, and interview answers produced by Aether Career
              Agent are AI-generated suggestions. You are solely responsible for reviewing the
              accuracy, completeness, and truthfulness of this content before submitting it to any
              employer. Aether Career Agent makes no guarantee of employment outcomes, interviews,
              or offers.
            </p>
          </Section>

          <Section title="13. Intellectual Property">
            <p>
              Your resume data and any content you upload remain your property. Aether Career
              Agent retains all rights, title, and interest in the platform, its user interface,
              software, and underlying AI models. Nothing in these Terms transfers ownership of
              our intellectual property to you.
            </p>
          </Section>

          <Section title="14. Disclaimers &amp; Limitation of Liability">
            <ul className="list-disc space-y-2 pl-5">
              <li>
                The service is provided on an &ldquo;as is&rdquo; and &ldquo;as available&rdquo;
                basis, without warranties of any kind, express or implied.
              </li>
              <li>We make no guarantee of job placement, interviews, or employment outcomes.</li>
              <li>
                To the maximum extent permitted by law, our total liability for any claim arising
                out of or relating to the service is capped at the amounts you paid to us in the
                twelve (12) months prior to the claim, or fifty Australian dollars (A$50) if you
                are on the free tier.
              </li>
              <li>
                We are not liable for hiring, rejection, or other decisions made by employers or
                third parties.
              </li>
            </ul>
          </Section>

          <Section title="15. Termination">
            <p>
              We may suspend or terminate accounts that violate these Terms, at our discretion and
              without prior notice where reasonably necessary. There is currently no self-service
              option to delete your account from within the app. If you wish to close your
              account, contact us (see Contact below) and we will process the closure manually.
            </p>
          </Section>

          <Section title="16. Changes to These Terms">
            <p>
              We may update these Terms from time to time. If we make material changes, we will
              notify you through an in-app notification. Your continued use of the service after
              such notice constitutes your acceptance of the updated Terms.
            </p>
          </Section>

          <Section title="17. Governing Law">
            <p>
              These Terms are governed by and construed in accordance with the laws of Victoria,
              Australia. You and Aether Career Agent submit to the non-exclusive jurisdiction of
              the courts of Victoria, Australia, without regard to conflict-of-law principles.
            </p>
          </Section>

          <Section title="18. Contact">
            <p>
              {supportEmail ? (
                <>
                  If you have questions about these Terms, or need to request a refund, account
                  closure, or a GST tax invoice correction, email us at{" "}
                  <a
                    href={`mailto:${supportEmail}`}
                    className="text-aether-coral hover:underline"
                  >
                    {supportEmail}
                  </a>
                  .
                </>
              ) : (
                <>
                  A support contact address has not yet been published for this service. Once
                  the operator configures one, it will be shown here and used to process
                  questions about these Terms, refund requests, account closures, and GST tax
                  invoice details.
                </>
              )}
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
