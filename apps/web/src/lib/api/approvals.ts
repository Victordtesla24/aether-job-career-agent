/** Typed approvals API client (P2-S07). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export const ApprovalSchema = z.object({
  id: z.string().min(1),
  userId: z.string(),
  applicationId: z.string().nullish(),
  type: z.enum(["application_submit", "email_send", "offer_response"]),
  status: z.enum(["pending", "approved", "rejected"]),
  payload: z.record(z.unknown()),
  createdAt: z.string(),
  resolvedAt: z.string().nullish(),
});

export type Approval = z.infer<typeof ApprovalSchema>;

export async function fetchApprovals(
  status: "pending" | "approved" | "rejected" | "all" = "pending",
  options: RequestOptions = {},
): Promise<Approval[]> {
  const data = await apiRequest<unknown>(`/approvals?status=${status}`, options);
  return z.array(ApprovalSchema).parse(data);
}

/** Re-request an approval via the EXISTING backend path (P0-3).
 *
 *  POST /approvals is the documented re-request capability: the repository's
 *  create() is idempotent per (job_id, kind, pending) — it refreshes an
 *  existing pending row instead of duplicating it. Used by the tracker's
 *  "Request approval" affordance for drafts whose approval expired/was purged,
 *  so they are not deadlocked outside the approval queue. */
export async function createApproval(
  body: {
    type: Approval["type"];
    application_id?: string | null;
    payload: Record<string, unknown>;
  },
  options: RequestOptions = {},
): Promise<Approval> {
  return ApprovalSchema.parse(
    await apiRequest<unknown>("/approvals", {
      ...options,
      method: "POST",
      body,
    }),
  );
}

/** Remove one stale (expired or resolved) approval request (FEAT-B1). */
export async function deleteApproval(
  id: string,
  options: RequestOptions = {},
): Promise<Approval> {
  return ApprovalSchema.parse(
    await apiRequest<unknown>(`/approvals/${id}`, { ...options, method: "DELETE" }),
  );
}

const PurgeExpiredResultSchema = z.object({
  purged: z.number(),
  ids: z.array(z.string()),
});

type PurgeExpiredResult = z.infer<typeof PurgeExpiredResultSchema>;

/** Bulk-remove every expired pending approval in ONE request (FEAT-B1).
 *  Expiry is decided server-side with the same 48h window as the UI badge. */
export async function purgeExpiredApprovals(
  options: RequestOptions = {},
): Promise<PurgeExpiredResult> {
  return PurgeExpiredResultSchema.parse(
    await apiRequest<unknown>("/approvals/purge-expired", { ...options, method: "POST" }),
  );
}
