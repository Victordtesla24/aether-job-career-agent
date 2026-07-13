/**
 * Shared API client core (P2 frontend wiring).
 *
 * - Resolves the API base URL: explicit env override → same-origin `/api`
 *   proxy in the browser → localhost FastAPI during SSR/dev.
 * - Manages the bearer token. There is NO silent auto-login: a visitor
 *   without a stored session is sent to /login (SC-AUTH-03). The /login form
 *   always starts with empty fields; there is no client-side demo-credential
 *   prefill (GAP-P4-068 removed the unused, hardcoded DEMO_CREDENTIALS
 *   export — LOGIN_EMAIL/LOGIN_PASSWORD in the repo .env are the only source
 *   of the demo credential).
 */

const TOKEN_STORAGE_KEY = "aether_token";

export function apiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  if (typeof window !== "undefined") {
    return "/api";
  }
  return "http://127.0.0.1:8000";
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let inMemoryToken: string | null = null;

/**
 * Return the stored session JWT. Never logs in on the caller's behalf: an
 * unauthenticated browser session is redirected to /login (SC-AUTH-03) and the
 * in-flight request fails with a 401 ApiError.
 */
export async function getToken(): Promise<string> {
  if (inMemoryToken) return inMemoryToken;
  if (typeof window !== "undefined") {
    const stored = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored) {
      inMemoryToken = stored;
      return stored;
    }
    window.location.replace("/login");
  }
  throw new ApiError("Not authenticated", 401);
}

export function clearToken(): void {
  inMemoryToken = null;
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  token?: string;
  baseUrl?: string;
}

/** Authenticated JSON request with a single retry on expired tokens. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const baseUrl = options.baseUrl ?? apiBaseUrl();
  const doFetch = async (token: string): Promise<Response> =>
    fetch(`${baseUrl}${path}`, {
      method: options.method ?? "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });

  let token = options.token ?? (await getToken());
  let res = await doFetch(token);
  if (res.status === 401 && !options.token) {
    // Session expired or revoked — drop it and send the visitor to /login.
    clearToken();
    token = await getToken();
    res = await doFetch(token);
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(`${options.method ?? "GET"} ${path} failed (${res.status}): ${detail}`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
