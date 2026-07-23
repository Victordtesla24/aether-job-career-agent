/**
 * Google / Gmail connect client (Email Agent).
 *
 * `fetchGoogleLoginUrl` asks the API (authenticated) for a Google consent URL;
 * `connectGmail` then performs a full-page navigation to it — OAuth consent
 * cannot happen inside an XHR. Google redirects the browser back to
 * `/dashboard/email?gmail_connected=1` (or `=0&error=...`), which
 * `gmailConnectResultFromParams` turns into an honest success/error banner.
 */
import { apiRequest, type RequestOptions } from "./client";

interface GoogleLoginResponse {
  authUrl: string;
}

async function fetchGoogleLoginUrl(o: RequestOptions = {}): Promise<GoogleLoginResponse> {
  return apiRequest<GoogleLoginResponse>("/auth/google/login", o);
}

/** Kick off the Gmail connect flow by navigating to Google's consent screen. */
export async function connectGmail(): Promise<void> {
  const { authUrl } = await fetchGoogleLoginUrl();
  window.location.href = authUrl;
}

type GmailConnectResult =
  | { kind: "success" }
  | { kind: "error"; message: string }
  | null;

/**
 * Map the `?gmail_connected=…&error=…` callback params to a banner result.
 * Returns `null` when the flow did not just complete (param absent), so the
 * page shows nothing on a normal visit. Pure + unit-testable.
 */
export function gmailConnectResultFromParams(
  params: { get(name: string): string | null },
): GmailConnectResult {
  const flag = params.get("gmail_connected");
  if (flag === "1") return { kind: "success" };
  if (flag === "0") {
    const raw = params.get("error");
    const message = raw && raw.trim() ? raw : "Google sign-in was cancelled or failed.";
    return { kind: "error", message };
  }
  return null;
}
