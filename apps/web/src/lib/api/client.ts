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
    /** Seconds from a `Retry-After` response header, when the server sent one
     * (429 rate-limit responses on /billing/checkout and /billing/portal). */
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Human-readable "try again in …" phrasing for an ApiError's retryAfterSeconds. */
export function formatRetryAfter(seconds: number): string {
  if (seconds < 60) return `${seconds} second${seconds === 1 ? "" : "s"}`;
  const minutes = Math.ceil(seconds / 60);
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}

/** Field-name labels for the human-readable validation messages below, keyed
 * by the last segment of a Pydantic error's `loc` (ML-settings-001). Unlisted
 * fields fall back to a camelCase/snake_case → "Title case" conversion. */
const FIELD_LABELS: Record<string, string> = {
  fullName: "Full name",
  email: "Email",
  targetRole: "Target role",
  location: "Location",
};

function humanizeFieldName(loc: unknown): string {
  if (!Array.isArray(loc) || loc.length === 0) return "This field";
  const key = String(loc[loc.length - 1]);
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  const spaced = key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .trim()
    .toLowerCase();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : "This field";
}

interface PydanticValidationError {
  type?: unknown;
  loc?: unknown;
  msg?: unknown;
  ctx?: Record<string, unknown>;
}

/** One field's validation failure -> a short, human sentence. Never echoes
 * the invalid `input` the server sent back (that's exactly the raw payload
 * ML-settings-001 was blowing page layout out with). */
function friendlyValidationMessage(err: PydanticValidationError): string {
  const field = humanizeFieldName(err.loc);
  const ctx = err.ctx ?? {};
  switch (err.type) {
    case "string_too_long":
      return typeof ctx.max_length === "number"
        ? `${field} must be ${ctx.max_length} characters or fewer.`
        : `${field} is too long.`;
    case "string_too_short":
      return typeof ctx.min_length === "number"
        ? `${field} must be at least ${ctx.min_length} characters.`
        : `${field} is too short.`;
    case "missing":
      return `${field} is required.`;
    default:
      return `${field}: ${typeof err.msg === "string" && err.msg ? err.msg : "invalid value"}`;
  }
}

/**
 * Extract a FastAPI/Pydantic validation error list from an ApiError.message
 * built by apiRequest() as `` `${method} ${path} failed (${status}): ${raw
 * body}` ``. Returns null when the body isn't that shape (nothing to parse,
 * or a 422 that isn't a Pydantic validation error).
 */
function parsePydanticDetail(message: string): PydanticValidationError[] | null {
  const marker = "): ";
  const idx = message.indexOf(marker);
  if (idx === -1) return null;
  const rawBody = message.slice(idx + marker.length);
  try {
    const parsed = JSON.parse(rawBody) as { detail?: unknown };
    if (Array.isArray(parsed.detail) && parsed.detail.length > 0) {
      return parsed.detail as PydanticValidationError[];
    }
  } catch {
    return null;
  }
  return null;
}

/** Hard cap on any rendered API error message — a defensive backstop so no
 * error text (structured or not) can ever balloon page layout again. */
const ERROR_MESSAGE_MAX_CHARS = 300;

function bound(text: string): string {
  return text.length <= ERROR_MESSAGE_MAX_CHARS
    ? text
    : `${text.slice(0, ERROR_MESSAGE_MAX_CHARS - 1)}…`;
}

/**
 * Bounded, human-readable message for an error caught from an API call. A
 * 422 field-validation error from FastAPI/Pydantic echoes the entire raw
 * request body — including any oversized invalid input — into
 * `ApiError.message`; this must never be shown to the user verbatim
 * (ML-settings-001: a 5000-char invalid `fullName` blew
 * `document.scrollWidth` out by ~49,800px). Structured validation failures
 * get a short, field-specific sentence instead; anything else falls back to
 * the original message, still defensively bounded.
 */
export function describeApiError(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status === 422) {
    const details = parsePydanticDetail(error.message);
    if (details) {
      return bound(details.slice(0, 3).map(friendlyValidationMessage).join(" "));
    }
  }
  if (error instanceof Error) return bound(error.message);
  return bound(fallback);
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
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
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
    // Entitlement gate (GAP-P6-PAYWALL): a 402 `subscription_required` means the
    // user tried an actionable feature without an active paid subscription. Route
    // them to the subscribe wall instead of surfacing a raw error toast.
    if (
      res.status === 402 &&
      detail.includes("subscription_required") &&
      typeof window !== "undefined"
    ) {
      window.location.assign("/pricing");
    }
    // 429 rate-limit responses (checkout, portal) carry a Retry-After header
    // (seconds) — surface it so the caller can tell the user honestly when to
    // retry instead of a generic "try again" (MV-pricing-004).
    const retryAfterHeader = res.headers.get("Retry-After");
    const retryAfterSeconds =
      retryAfterHeader !== null && Number.isFinite(Number(retryAfterHeader))
        ? Number(retryAfterHeader)
        : undefined;
    throw new ApiError(
      `${options.method ?? "GET"} ${path} failed (${res.status}): ${detail}`,
      res.status,
      retryAfterSeconds,
    );
  }
  if (res.status === 204) {
    // Drain the (empty) body before returning. Leaving a 204's body stream
    // unread lets Chromium's network stack treat it as cancelled mid-flight,
    // which surfaces as a client-observed net::ERR_ABORTED on an otherwise
    // fully-successful request (MV-story-bank-004, seen on DELETE /stories/{id}).
    await res.text().catch(() => undefined);
    return undefined as T;
  }
  return (await res.json()) as T;
}
