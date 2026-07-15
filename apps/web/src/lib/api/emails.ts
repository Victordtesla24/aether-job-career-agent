/**
 * Multi-account Gmail inbox client (GAP-D2).
 *
 * A user can connect several Gmail inboxes. These helpers list the connected
 * accounts, kick off adding another (full-page navigation to Google's account
 * chooser), set which one is primary, and disconnect one at a time. Account
 * emails returned here are masked by the server; tokens are never exposed.
 */
import { apiRequest, type RequestOptions } from "./client";

export interface GmailAccount {
  id: string;
  accountEmail: string | null;
  isPrimary: boolean;
  scopes: string | null;
  connectedAt: string | null;
  updatedAt: string | null;
}

export interface OAuthStatus {
  configured: boolean;
  connected: boolean;
  accountCount: number;
}

export async function fetchGmailAccounts(o: RequestOptions = {}): Promise<GmailAccount[]> {
  return apiRequest<GmailAccount[]>("/emails/accounts", o);
}

export async function fetchOAuthStatus(o: RequestOptions = {}): Promise<OAuthStatus> {
  return apiRequest<OAuthStatus>("/emails/oauth/status", o);
}

/** Start connecting ANOTHER Gmail account — navigates to Google's chooser. */
export async function connectAnotherGmail(o: RequestOptions = {}): Promise<void> {
  const { authUrl } = await apiRequest<{ authUrl: string }>("/emails/accounts/connect", {
    ...o,
    method: "POST",
  });
  window.location.href = authUrl;
}

export async function setPrimaryAccount(accountId: string, o: RequestOptions = {}): Promise<void> {
  await apiRequest(`/emails/accounts/${encodeURIComponent(accountId)}/set-primary`, {
    ...o,
    method: "PATCH",
  });
}

export async function disconnectAccount(accountId: string, o: RequestOptions = {}): Promise<void> {
  await apiRequest(`/emails/accounts/${encodeURIComponent(accountId)}`, {
    ...o,
    method: "DELETE",
  });
}
