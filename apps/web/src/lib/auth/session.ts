/**
 * Session model + token→session resolution (P1-S03).
 *
 * A resolved session is the shape consumed by both server components and the
 * `requireAuth` guard. `getSessionFromToken` is intentionally forgiving: it
 * returns `null` (rather than throwing) for any invalid/expired/missing token
 * so callers can branch on presence without try/catch noise.
 */
import { verifySessionToken } from "./jwt";

/** Cookie name for the stateless session token (matches NextAuth conventions). */
export const SESSION_COOKIE_NAME = "aether.session-token";

export interface AetherSessionUser {
  id: string;
  email: string;
  name?: string;
}

export interface AetherSession {
  user: AetherSessionUser;
  /** ISO-8601 expiry timestamp. */
  expires: string;
}

export async function getSessionFromToken(
  token: string | undefined | null,
  secret: string,
): Promise<AetherSession | null> {
  if (!token) {
    return null;
  }
  try {
    const claims = await verifySessionToken(token, secret);
    return {
      user: { id: claims.sub, email: claims.email, name: claims.name },
      expires: new Date(claims.exp * 1000).toISOString(),
    };
  } catch {
    return null;
  }
}
