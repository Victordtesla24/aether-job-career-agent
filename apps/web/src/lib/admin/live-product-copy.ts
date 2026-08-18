/** Retired Abacus product origin — never copy this host out of the console. */
export const RETIRED_PRODUCT_HOST =
  /https?:\/\/(?:www\.)?(?:5cb5f0620\.)?abacusai\.cloud/gi;

export function containsRetiredHost(text: string | null | undefined): boolean {
  return /abacusai\.cloud/i.test(text || "");
}

export function liveProductCopy(
  text: string,
  liveOrigin: string | null | undefined,
): string {
  const live = (liveOrigin || "").replace(/\/+$/, "");
  if (!live) return text;
  return text.replace(RETIRED_PRODUCT_HOST, live);
}
