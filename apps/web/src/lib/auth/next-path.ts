/**
 * Open-redirect-safe resolution of a post-login "return to" path
 * (MV-login-002).
 *
 * AuthGuard sends an unauthenticated deep-link visitor to
 * `/login?next=<encoded pathname+search>`; after a successful login the app
 * returns them there instead of always dropping them on bare /dashboard. The
 * value rides in the URL and is therefore attacker-controllable, so it is
 * validated down to a clean, same-origin path confined to the authenticated
 * dashboard area. Anything else — external hosts, protocol-relative URLs,
 * backslash tricks, path traversal, or non-dashboard routes — falls back to
 * /dashboard.
 */
export const DEFAULT_POST_LOGIN_PATH = "/dashboard";

export function safeNextPath(raw: string | null | undefined): string {
  if (!raw) return DEFAULT_POST_LOGIN_PATH;

  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    // Malformed percent-encoding (e.g. a lone "%E0%A4") — this runs on the
    // unauthenticated /login page, so never throw; just fall back.
    return DEFAULT_POST_LOGIN_PATH;
  }

  if (
    decoded.startsWith("//") || // protocol-relative -> external host
    decoded.includes("\\") || // backslash host/scheme tricks
    decoded.includes("://") || // absolute URL
    decoded.includes("..") // path traversal out of the intended scope
  ) {
    return DEFAULT_POST_LOGIN_PATH;
  }

  // Confine the destination to the authenticated dashboard area. The character
  // after "/dashboard" must be a path/query boundary — a bare
  // startsWith("/dashboard") would also accept "/dashboardevil.com".
  const isDashboard =
    decoded === "/dashboard" ||
    decoded.startsWith("/dashboard/") ||
    decoded.startsWith("/dashboard?");

  return isDashboard ? decoded : DEFAULT_POST_LOGIN_PATH;
}
