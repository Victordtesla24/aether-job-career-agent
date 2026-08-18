/**
 * Networking contact-import API client (W-NET-1, owner directive 2026-08-16).
 *
 * Two owner-initiated importers, deliberately separate consent scopes
 * (mirroring the API design in apps/api/app/routers/networking.py):
 *
 *  - Gmail: derives professional contacts from the owner's connected
 *    mailboxes' correspondence. No file needed.
 *  - LinkedIn export: accepts LinkedIn's "Download your data" .zip (ONLY
 *    Connections.csv is opened server-side) or a loose Connections.csv.
 *    Zero network calls to LinkedIn — ever.
 *
 * Both dedupe into the Contact table; suppressed emails are never saved.
 */
import { apiBaseUrl, apiRequest, getToken } from "./client";

export interface GmailImportResult {
  contactsCreated: number;
  contactsUpdated?: number;
  leadsCreated: number;
  duplicates: number;
  suppressed: number;
  ignored: number;
}

export interface LinkedInImportResult {
  contactsCreated: number;
  contactsUpdated?: number;
  duplicates: number;
  suppressed: number;
  /** Kept for older servers; CRM imports no longer create SalesLead rows. */
  leadsCreated?: number;
  /** Server field is ``rows`` (parsed Connections.csv rows). */
  rows?: number;
  /** @deprecated alias — prefer ``rows``. */
  rowsParsed?: number;
}

/** One row of GET /networking/contacts (full, uncapped contact list). */
export interface ContactListRow {
  id: string;
  name: string;
  title: string | null;
  company: string | null;
  stage: string;
  email: string | null;
  linkedinUrl: string | null;
  createdAt?: string;
}

/** The FULL contact list — the pipeline summary previews only 5 per column. */
export const listContacts = (company?: string): Promise<ContactListRow[]> => {
  const q = company?.trim()
    ? `?company=${encodeURIComponent(company.trim())}`
    : "";
  return apiRequest<ContactListRow[]>(`/networking/contacts${q}`);
};

export const createOutreachTask = (input: {
  contactId: string;
  type?: string;
  message?: string;
}): Promise<Record<string, unknown>> =>
  apiRequest("/networking/outreach", {
    method: "POST",
    body: {
      contact_id: input.contactId,
      type: input.type ?? "message",
      message: input.message,
    },
  });

export const deleteOutreachTask = (outreachId: string): Promise<void> =>
  apiRequest<void>(`/networking/outreach/${outreachId}`, { method: "DELETE" });

export const importGmailContacts = (): Promise<GmailImportResult> =>
  apiRequest<GmailImportResult>("/networking/gmail/import-contacts", {
    method: "POST",
  });

export const refreshContactsFromInbox = (): Promise<{
  contactsCreated: number;
  contactsUpdated: number;
  threadsLinked: number;
  ignored: number;
}> =>
  apiRequest("/networking/refresh-from-inbox", { method: "POST" });

export async function importLinkedInConnections(
  file: File,
): Promise<LinkedInImportResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${apiBaseUrl()}/networking/linkedin/import-contacts`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await getToken()}` },
    body: form,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON body — fall through to the generic message
    }
    throw new Error(
      detail || `LinkedIn import failed (${res.status}). Please try again.`,
    );
  }
  return (await res.json()) as LinkedInImportResult;
}
