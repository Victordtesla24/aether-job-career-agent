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

/**
 * Structured `detail` object FastAPI attaches to an HTTPException, when the body
 * parses as `{"detail": {...}}`.
 *
 * DROP-001. The plan-quota 429 (`routers/agents.py`) documents itself as carrying
 * "an upgrade CTA (/pricing) and the period reset time so the UI can prompt an
 * upgrade or a wait" — but every field was flattened into the message string here
 * and lost, so no caller could ever act on it. Preserving the object is what makes
 * an honest quota wall possible; it changes nothing for callers that ignore it.
 */
export interface ApiErrorDetail {
  code?: string;
  message?: string;
  runsUsed?: number | null;
  runsAllowed?: number | null;
  /** ISO-8601 instant the quota period resets, or null when not known. */
  quotaReset?: string | null;
  upgradeUrl?: string | null;
  [key: string]: unknown;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Seconds from a `Retry-After` response header, when the server sent one
     * (429 rate-limit responses on /billing/checkout and /billing/portal). */
    readonly retryAfterSeconds?: number,
    /** Parsed `detail` object when the server sent one; `undefined` for plain
     * string details. Never fabricated — absent means the server sent none. */
    readonly detail?: ApiErrorDetail,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Lift FastAPI's structured `detail` out of a raw error body. Returns `undefined`
 * for a non-JSON body or a plain-string detail — callers must not be handed a
 * synthesized object that the server never sent.
 */
export function parseApiErrorDetail(body: string): ApiErrorDetail | undefined {
  if (!body) return undefined;
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const d = (parsed as { detail: unknown }).detail;
      if (d && typeof d === "object" && !Array.isArray(d)) return d as ApiErrorDetail;
    }
  } catch {
    // Non-JSON body (HTML error page, plain text) — nothing structured to lift.
  }
  return undefined;
}

/**
 * Whether an error body came from an INTERMEDIARY (CDN / reverse proxy / load
 * balancer) rather than from our own API — i.e. it is an HTML page, not JSON.
 *
 * MON-020. A discovery run legitimately takes minutes (production discovery-cron
 * measurement: 255-473s typical, 968s worst case), Cloudflare gave up at ~100s,
 * and its `text/html` "Error 524" page was embedded verbatim into
 * `ApiError.message` — so every screen rendering `e.message` dumped raw
 * Cloudflare markup (Ray ID and all) at the user.
 *
 * The Content-Type header alone is not enough: some proxies label an HTML body
 * `text/plain`, so the body itself is sniffed too.
 *
 * EXPORTED because `apiRequest` is not the only caller that reads an error body:
 * `lib/api/resumes.ts` (`downloadResume` needs the blob, not JSON) and
 * `lib/realtime/transport.ts` (`openWorkspaceStream` needs the raw stream) build
 * their own `fetch`, and both put the body in front of the user. They reuse THIS
 * predicate and `gatewayErrorMessage` below so the three paths cannot drift.
 */
export function isNonApiHtmlBody(contentType: string | null, body: string): boolean {
  if (contentType && contentType.toLowerCase().includes("text/html")) return true;
  const head = body.trimStart().slice(0, 256).toLowerCase();
  return (
    head.startsWith("<!doctype") ||
    head.startsWith("<html") ||
    head.startsWith("<head") ||
    head.startsWith("<body") ||
    head.startsWith("<?xml")
  );
}

/**
 * The honest sentence shown in place of an intermediary's HTML page.
 *
 * Deliberately says only what is actually known: the transport failed and with
 * which class of failure. It never claims the operation succeeded, never claims
 * it definitely failed when a timeout leaves that genuinely unknown, and never
 * invents a retry ETA. The real status stays on `ApiError.status` for callers
 * that branch on it.
 */
export function gatewayErrorMessage(status: number): string {
  if (status === 408 || status === 504 || status === 522 || status === 524) {
    return (
      "The server took too long to respond. Your request may still be running — " +
      "check back in a moment before trying again."
    );
  }
  if (status === 502 || status === 503) {
    return "The service is temporarily unavailable. Please try again in a moment.";
  }
  if (status >= 500) {
    return `The server returned an unexpected response (HTTP ${status}). Please try again.`;
  }
  return `The request was rejected before it reached Aether (HTTP ${status}).`;
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
  /**
   * Abort the request if the server has not responded within this many
   * milliseconds (MF-A, round-5 re-review). Optional and opt-in: omitting it
   * keeps today's unbounded `fetch` — this module never bounded ANY call
   * with a timeout, which is exactly what let a hung fidelity check leave a
   * frozen claim on screen indefinitely (see
   * `components/approvals/ApprovalModal.tsx`'s live-fidelity effect). A
   * caller that opts in gets an honest rejection instead of a silent hang;
   * every other caller is byte-identical to before.
   */
  timeoutMs?: number;
}

/** Authenticated JSON request with a single retry on expired tokens. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const baseUrl = options.baseUrl ?? apiBaseUrl();
  const doFetch = async (token: string): Promise<Response> => {
    const controller = options.timeoutMs !== undefined ? new AbortController() : undefined;
    const timer =
      controller !== undefined
        ? setTimeout(() => controller.abort(), options.timeoutMs)
        : undefined;
    try {
      return await fetch(`${baseUrl}${path}`, {
        method: options.method ?? "GET",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller?.signal,
      });
    } catch (error) {
      // A timeout abort rejects `fetch` with an opaque `AbortError` — name it
      // honestly instead of letting that cryptic message reach a caller/UI.
      if (controller?.signal.aborted) {
        throw new Error(
          `${options.method ?? "GET"} ${path} timed out after ${options.timeoutMs}ms — the server did not respond in time.`,
        );
      }
      throw error;
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  };

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
    // MON-020: an intermediary's HTML error page is not something any caller can
    // parse or any user should read. Replace the body with an honest sentence
    // BEFORE it reaches `ApiError.message`, and drop the
    // "METHOD /path failed (status):" prefix with it — that prefix exists to
    // carry a server payload, and there is none here. A JSON body from our own
    // API is untouched, so every existing parser (`parsePydanticDetail`,
    // `components/cover-letters/rejection.ts`, `lib/agents-feedback`) keeps
    // seeing exactly the string it was written against.
    if (isNonApiHtmlBody(res.headers.get("Content-Type"), detail)) {
      throw new ApiError(gatewayErrorMessage(res.status), res.status);
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
      parseApiErrorDetail(detail),
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
