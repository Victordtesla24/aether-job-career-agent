/**
 * /dashboard/settings — server wrapper.
 *
 * The page is a server component only so it can read the operator's
 * AETHER_SUPPORT_EMAIL at request time (never inlined at build time — see
 * `getOperatorLegalConfig`'s docstring) and hand it to the interactive
 * client UI as a prop, for the honest "Manage subscription" contact-fallback
 * copy (MV-settings-003). All the page's actual state/behaviour lives in
 * SettingsClient.
 */
import { getOperatorLegalConfig } from "../../../lib/config/legal";
import SettingsClient from "./settings-client";

export const dynamic = "force-dynamic";

export default function SettingsPage() {
  const { supportEmail } = getOperatorLegalConfig();
  return <SettingsClient supportEmail={supportEmail} />;
}
