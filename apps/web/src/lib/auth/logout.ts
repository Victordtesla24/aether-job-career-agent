/**
 * Client-side session teardown for the user-initiated "Sign out" control
 * (MV-login-003). The app previously had no way for a user to end a session —
 * the 24h bearer token in localStorage could only be cleared by the automatic
 * 401 handler or by manually wiping browser storage.
 */
import { clearToken } from "../api/client";

const TOKEN_STORAGE_KEY = "aether_token";

/**
 * Clear all client-side session state: the in-memory token and the
 * localStorage `aether_token` (both via `clearToken`), plus — defensively — an
 * `aether_token` cookie. The app is localStorage-only today, so the cookie
 * clear is belt-and-suspenders: it guarantees "Sign out" leaves nothing behind
 * even if a future change (or SSR) ever mirrors the token into a cookie, which
 * is exactly the teardown the finding asks for.
 */
export function clearClientSession(): void {
  clearToken();
  if (typeof document !== "undefined") {
    document.cookie = `${TOKEN_STORAGE_KEY}=; Max-Age=0; path=/; SameSite=Lax`;
  }
}
