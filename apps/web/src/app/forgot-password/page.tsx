/**
 * /forgot-password — server wrapper (O-4 self-service password reset).
 *
 * The page is a server component only so it can read the operator's
 * AETHER_SUPPORT_EMAIL / AETHER_SUPPORT_PHONE at request time (never inlined
 * at build time — see `getOperatorLegalConfig`'s docstring) and hand it to
 * the interactive client UI as a prop — mirrors `dashboard/settings`'s
 * `SettingsClient` split. All the page's actual state/behaviour lives in
 * ForgotPasswordClient.
 */
import ForgotPasswordClient from "./forgot-password-client";
import { getOperatorLegalConfig } from "../../lib/config/legal";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Reset your password · Aether",
};

export default function ForgotPasswordPage() {
  const { supportEmail, supportPhone } = getOperatorLegalConfig();
  return <ForgotPasswordClient supportEmail={supportEmail} supportPhone={supportPhone} />;
}
