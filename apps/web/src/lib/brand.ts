/**
 * Canonical brand identity constants — the ONE place the legal footer line,
 * product name, and support address live (owner directive 2026-08-16:
 * consistent footnote "across the board"). Every footer — web, email, future
 * surfaces — renders from these; a footer that hand-writes its own copy of
 * this line is a review failure.
 *
 * The company name carries a superscript 2 ("V² Group"). In React markup use
 * {COMPANY_NAME_SUP} parts to render a semantic <sup>; in plain text and
 * email bodies use COMPANY_NAME (unicode ²), which renders correctly in every
 * UTF-8 client.
 */

export const PRODUCT_NAME = "Aether CareerAI Agent";
export const COMPANY_NAME = "V² Group Pty. Ltd.";
export const SUPPORT_EMAIL = "sarkar.vikram@gmail.com";
export const COPYRIGHT_YEAR = 2026;

/** Plain-text legal line — emails, meta tags, anywhere markup can't render. */
export const LEGAL_LINE = `© ${COPYRIGHT_YEAR} ${PRODUCT_NAME} · A product of ${COMPANY_NAME} · All rights reserved.`;
