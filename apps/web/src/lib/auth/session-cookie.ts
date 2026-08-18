/**
 * Mirror the session JWT into a same-origin cookie so Next.js middleware can
 * see it. The API still authorises from the Authorization bearer / localStorage
 * token; this cookie is the HTTP-level "a session exists" signal for /admin.
 */
export const SESSION_COOKIE_NAME = "aether_token";
const MAX_AGE_SECONDS = 60 * 60 * 24;

export function persistSessionToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SESSION_COOKIE_NAME, token);
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie =
    `${SESSION_COOKIE_NAME}=${encodeURIComponent(token)}; Max-Age=${MAX_AGE_SECONDS}; ` +
    `path=/; SameSite=Lax${secure}`;
}

export function persistSessionTokenFromStorage(): void {
  if (typeof window === "undefined") return;
  const token = window.localStorage.getItem(SESSION_COOKIE_NAME);
  if (token) persistSessionToken(token);
}
