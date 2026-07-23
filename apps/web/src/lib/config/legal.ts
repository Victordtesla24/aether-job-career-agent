/**
 * Operator-held legal identity + support-contact configuration for the public
 * legal pages (/terms, /privacy-policy) — MV-terms-002, MV-terms-003,
 * MV-privacy-policy-003 (H-3, BLOCKED-ON-HUMAN).
 *
 * The real business name, Australian Business Number (ABN), and support
 * email are held by the business operator; the app must never invent them.
 * Each value is read from an environment variable at render time (both pages
 * are Next.js server components with `export const dynamic = "force-dynamic"`,
 * so this always reflects the live process environment, not a stale build).
 *
 *   - AETHER_OPERATOR_BUSINESS_NAME — defaults to "Aether" (the product's own
 *     name) when unset: a truthful generic, never a bracket placeholder or an
 *     invented legal entity.
 *   - AETHER_OPERATOR_ABN — no default. An ABN cannot be honestly fabricated;
 *     when unset, the pages state plainly that one has not yet been
 *     published rather than showing a placeholder.
 *   - AETHER_SUPPORT_EMAIL — no default. A contact address cannot be
 *     honestly fabricated either; when unset, the pages state the actual
 *     (manual, operator-mediated) process instead of promising a support
 *     channel that does not exist.
 *   - AETHER_SUPPORT_PHONE — no default, same rule as AETHER_SUPPORT_EMAIL:
 *     never fabricated, null (rendered as nothing) when unset.
 *
 * Set these in the repo-root `.env` (see `.env.example`); `start-web.sh`
 * loads it before `pnpm start` (docs/delivery/DEPLOYMENT-RUNBOOK.md).
 */
interface OperatorLegalConfig {
  businessName: string;
  abn: string | null;
  supportEmail: string | null;
  supportPhone: string | null;
}

/**
 * Format an Australian Business Number for display: 11 digits grouped
 * "NN NNN NNN NNN" (2-3-3-3), per the ABR's standard presentation. Strips
 * any existing non-digit separators first so both a raw 11-digit value and
 * an already-spaced one produce the same, correctly-grouped result. Any
 * value that isn't exactly 11 digits (e.g. a placeholder or malformed
 * entry) is returned unchanged, trimmed, rather than guessed at.
 */
function formatAbn(value: string): string {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 11) {
    return `${digits.slice(0, 2)} ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8, 11)}`;
  }
  return value;
}

export function getOperatorLegalConfig(): OperatorLegalConfig {
  const businessName = process.env.AETHER_OPERATOR_BUSINESS_NAME?.trim();
  const abn = process.env.AETHER_OPERATOR_ABN?.trim();
  const supportEmail = process.env.AETHER_SUPPORT_EMAIL?.trim();
  const supportPhone = process.env.AETHER_SUPPORT_PHONE?.trim();

  return {
    businessName: businessName && businessName.length > 0 ? businessName : "Aether",
    abn: abn && abn.length > 0 ? formatAbn(abn) : null,
    supportEmail: supportEmail && supportEmail.length > 0 ? supportEmail : null,
    supportPhone: supportPhone && supportPhone.length > 0 ? supportPhone : null,
  };
}
