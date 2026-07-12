/**
 * Shared API client core (P2 frontend wiring).
 *
 * - Resolves the API base URL: explicit env override → same-origin `/api`
 *   proxy in the browser → localhost FastAPI during SSR/dev.
 * - Manages the bearer token. For the deployed demo, an automatic login with
 *   the seeded demo account keeps every dashboard page live without a
 *   dedicated auth UI (full auth screens land in a later phase).
 */

export const DEMO_CREDENTIALS = {
  email: "demo@aether.dev",
  password: "AetherDemo1",
} as const;

const TOKEN_STORAGE_KEY = "aether_token";

export function apiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  if (typeof window !== "undefined") {
    return "/api";
  }
  return "http://localhost:8000";
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

/** Login with the demo account and cache the JWT. */
export async function getToken(baseUrl: string = apiBaseUrl()): Promise<string> {
  if (inMemoryToken) return inMemoryToken;
  if (typeof window !== "undefined") {
    const stored = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored) {
      inMemoryToken = stored;
      return stored;
    }
  }
  const res = await fetch(`${baseUrl}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(DEMO_CREDENTIALS),
  });
  if (!res.ok) {
    throw new ApiError(`Login failed (${res.status})`, res.status);
  }
  const body = (await res.json()) as { access_token: string };
  inMemoryToken = body.access_token;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, body.access_token);
  }
  return body.access_token;
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

  let token = options.token ?? (await getToken(baseUrl));
  let res = await doFetch(token);
  if (res.status === 401 && !options.token) {
    clearToken();
    token = await getToken(baseUrl);
    res = await doFetch(token);
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(`${options.method ?? "GET"} ${path} failed (${res.status}): ${detail}`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
