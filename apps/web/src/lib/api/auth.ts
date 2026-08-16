/**
 * Auth API client — register + login against apps/api/app/routers/auth.py.
 *
 * Kept separate from the generic authenticated `apiRequest` in ./client
 * (that one requires an existing token; these two calls are how a token is
 * first obtained). Both /signup and /login use this so the 409/429 handling
 * for register and the 401/429 handling for login are defined once.
 */
import { apiBaseUrl } from "./client";

export class AuthApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "AuthApiError";
  }
}

interface LoginResult {
  accessToken: string;
  userId: string;
  email: string;
}

interface RegisterInput {
  email: string;
  password: string;
  name?: string;
  /**
   * ADMIN-2.0 BE-2: a sales agent's referral code, from a `/signup?ref=CODE`
   * landing link. The API accepts it as a body field (or query param) and
   * attributes the signup AFTER the account is committed, swallowing any
   * failure there — the account is the user's, a referral credit is the
   * operator's bookkeeping, and one must never cost the other. Omitted
   * entirely when the visitor arrived without a code.
   */
  ref?: string;
}

interface RegisterResult {
  id: string;
  email: string;
  createdAt: string;
}

function parseRetryAfter(res: Response): number | undefined {
  const header = res.headers.get("Retry-After");
  if (!header) return undefined;
  const n = Number(header);
  return Number.isFinite(n) ? n : undefined;
}

/** Best-effort extraction of FastAPI's `{"detail": ...}` error body. */
async function extractDetail(res: Response): Promise<string | null> {
  try {
    const data: unknown = await res.json();
    if (data && typeof data === "object" && "detail" in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        const msgs = detail
          .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : null))
          .filter((m): m is string => Boolean(m));
        if (msgs.length > 0) return msgs.join("; ");
      }
    }
  } catch {
    // Body wasn't JSON — fall through to a generic message.
  }
  return null;
}

/**
 * Turn a raw FastAPI 422 `detail` into clean user-facing copy (MV-signup-003).
 * Pydantic wraps our field-validator messages as "Value error, <msg>" and
 * surfaces `EmailStr` failures with email_validator's internal text ("value is
 * not a valid email address: ...The email address is too long..."). Strip the
 * wrapper and replace the email-validator noise with one honest line, while
 * leaving genuine policy messages (e.g. password rules) intact.
 */
function cleanValidationDetail(detail: string | null): string {
  if (!detail) return "Please check your details and try again.";
  const stripped = detail.replace(/Value error,\s*/gi, "").trim();
  const mentionsEmail = /valid email address|email address is too long/i.test(stripped);
  // Only swallow the message when it is PURELY about the email; a combined 422
  // that also carries a password-policy message keeps that part intact.
  if (mentionsEmail && !/password/i.test(stripped)) {
    return "Please enter a valid email address.";
  }
  return stripped;
}

async function toAuthApiError(res: Response, action: "login" | "register"): Promise<AuthApiError> {
  if (res.status === 429) {
    const retryAfterSeconds = parseRetryAfter(res);
    const wait = retryAfterSeconds ? ` Try again in ${retryAfterSeconds}s.` : "";
    return new AuthApiError(`Too many attempts. Please wait and try again.${wait}`, 429, retryAfterSeconds);
  }
  if (action === "login" && res.status === 401) {
    return new AuthApiError("Invalid email or password.", 401);
  }
  if (action === "register" && res.status === 409) {
    return new AuthApiError("An account with this email already exists.", 409);
  }
  if (res.status === 422) {
    const detail = await extractDetail(res);
    return new AuthApiError(cleanValidationDetail(detail), 422);
  }
  const verb = action === "login" ? "Login" : "Registration";
  return new AuthApiError(`${verb} failed (${res.status}). Please try again.`, res.status);
}

/** `identifier` is an email OR a username — the backend accepts either. */
export async function login(
  identifier: string,
  password: string,
  baseUrl: string = apiBaseUrl(),
): Promise<LoginResult> {
  const res = await fetch(`${baseUrl}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: identifier, password }),
  });
  if (!res.ok) {
    throw await toAuthApiError(res, "login");
  }
  const body = (await res.json()) as { access_token: string; userId: string; email: string };
  return { accessToken: body.access_token, userId: body.userId, email: body.email };
}

export async function registerAccount(
  input: RegisterInput,
  baseUrl: string = apiBaseUrl(),
): Promise<RegisterResult> {
  const res = await fetch(`${baseUrl}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw await toAuthApiError(res, "register");
  }
  return (await res.json()) as RegisterResult;
}

/**
 * Result of POST /auth/forgot-password (O-4). ``ok`` is always true — the
 * endpoint never reveals whether the email matched an account
 * (anti-enumeration). ``emailSendingEnabled`` is the one honest signal: when
 * false, no outbound-email provider is configured on the backend today, so
 * no link was ever actually sent for ANY address.
 *
 * ``deliveryDegraded`` (MF-3): true when the provider IS configured but the
 * most recent attempted send in this deployment actually failed (bad
 * credentials, provider outage, unverified sending domain). A configured
 * provider is not the same as a working one — the UI must not claim "we've
 * sent a link" when the last real attempt failed.
 */
export interface ForgotPasswordResult {
  ok: boolean;
  emailSendingEnabled: boolean;
  deliveryDegraded: boolean;
}

function toRateLimitError(res: Response): AuthApiError {
  const retryAfterSeconds = parseRetryAfter(res);
  const wait = retryAfterSeconds ? ` Try again in ${retryAfterSeconds}s.` : "";
  return new AuthApiError(`Too many attempts. Please wait and try again.${wait}`, 429, retryAfterSeconds);
}

export async function forgotPassword(
  email: string,
  baseUrl: string = apiBaseUrl(),
): Promise<ForgotPasswordResult> {
  const res = await fetch(`${baseUrl}/auth/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    if (res.status === 429) throw toRateLimitError(res);
    if (res.status === 422) {
      const detail = await extractDetail(res);
      throw new AuthApiError(cleanValidationDetail(detail), 422);
    }
    throw new AuthApiError(`Request failed (${res.status}). Please try again.`, res.status);
  }
  return (await res.json()) as ForgotPasswordResult;
}

export async function resetPassword(
  token: string,
  password: string,
  baseUrl: string = apiBaseUrl(),
): Promise<void> {
  const res = await fetch(`${baseUrl}/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });
  if (!res.ok) {
    if (res.status === 429) throw toRateLimitError(res);
    if (res.status === 400) {
      const detail = await extractDetail(res);
      throw new AuthApiError(detail || "This reset link is invalid or has expired.", 400);
    }
    // 409 — the API refused because this identity's password is deployment-
    // managed (§14.7; RT-001: the API's message is professional and names no
    // internals — the operator remedy lives in the server log). Surface the
    // backend's own reason: the generic fallback below would tell the visitor
    // to retry something that can never succeed.
    if (res.status === 409) {
      const detail = await extractDetail(res);
      throw new AuthApiError(
        detail ||
          "This account's password is managed at the deployment level and cannot be reset here.",
        409,
      );
    }
    if (res.status === 422) {
      const detail = await extractDetail(res);
      throw new AuthApiError(cleanValidationDetail(detail), 422);
    }
    throw new AuthApiError(`Reset failed (${res.status}). Please try again.`, res.status);
  }
}
