/**
 * `requireAuth` — a framework-agnostic authentication guard (P1-S03).
 *
 * It accepts a minimal request-like object (anything exposing `headers.get`
 * and, optionally, `cookies.get`) so it works with the Fetch `Request` used by
 * Next.js route handlers and middleware, as well as plain test doubles. It
 * looks for a Bearer token first, then falls back to the session cookie, and
 * returns a discriminated result the caller can switch on.
 */
import {
  getSessionFromToken,
  SESSION_COOKIE_NAME,
  type AetherSession,
} from "./session";

export type AuthFailureReason = "no_token" | "invalid_token";

export type AuthResult =
  | { authenticated: true; session: AetherSession }
  | { authenticated: false; reason: AuthFailureReason };

export interface RequestLike {
  headers: { get(name: string): string | null };
  cookies?: { get(name: string): { value: string } | undefined };
}

/** Extract the token from an `Authorization: Bearer <token>` header. */
export function extractBearerToken(authHeader: string | null): string | null {
  if (!authHeader) {
    return null;
  }
  const match = /^Bearer\s+(.+)$/i.exec(authHeader.trim());
  return match ? match[1] : null;
}

export async function requireAuth(
  request: RequestLike,
  secret: string,
): Promise<AuthResult> {
  const bearer = extractBearerToken(request.headers.get("authorization"));
  const cookieToken = request.cookies?.get(SESSION_COOKIE_NAME)?.value ?? null;
  const token = bearer ?? cookieToken;

  if (!token) {
    return { authenticated: false, reason: "no_token" };
  }

  const session = await getSessionFromToken(token, secret);
  if (!session) {
    return { authenticated: false, reason: "invalid_token" };
  }

  return { authenticated: true, session };
}
