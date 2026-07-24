/**
 * Shared display formatters (W-C dedup — DEDUP-007/DEDUP-008).
 *
 * `formatAud` was duplicated verbatim on /pricing and /dashboard/settings;
 * `formatDateTime`/`formatDate` replace three byte-parallel `fmtDate` copies
 * on the admin screens (two `toLocaleString`, one date-only).
 */

/** AUD currency — whole dollars render without cents (matches /pricing). */
export function formatAud(amount: number): string {
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
  }).format(amount);
}

/** Locale date+time, em-dash on null/invalid (admin audit-log / user detail). */
export function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("en-AU");
}

/** Locale date only, em-dash on null/invalid (admin users list). */
export function formatDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("en-AU");
}
