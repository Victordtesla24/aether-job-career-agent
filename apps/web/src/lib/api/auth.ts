/**
 * Auth API client (P2-S01).
 *
 * Delegates credential verification to the FastAPI backend's `/auth/login`
 * endpoint, which owns the bcrypt hashes and never exposes them. On success it
 * returns the public user identity used to seed the NextAuth session.
 *
 * SECURITY: the password is sent only to our own backend over the configured
 * API base URL; the response never contains a password hash.
 */
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface AuthenticatedUser {
  id: string;
  email: string;
  name?: string;
}

interface LoginApiResponse {
  access_token: string;
  token_type: string;
  user: { id: string; email: string };
}

/**
 * Verify credentials against the backend. Returns the authenticated user, or
 * `null` for any invalid-credential / non-2xx / malformed response.
 */
export async function loginWithCredentials(
  email: string,
  password: string,
): Promise<AuthenticatedUser | null> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    // Network/backend unreachable — treat as a failed sign-in, never throw.
    return null;
  }

  if (!res.ok) {
    return null;
  }

  const data = (await res.json()) as LoginApiResponse;
  if (!data?.user?.id || !data?.user?.email) {
    return null;
  }
  return { id: data.user.id, email: data.user.email };
}
