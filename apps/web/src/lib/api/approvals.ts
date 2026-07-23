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

export async function approveRequest(id: string, options: RequestOptions = {}): Promise<Approval> {
  return ApprovalSchema.parse(
    await apiRequest<unknown>(`/approvals/${id}/approve`, { ...options, method: "POST" }),
  );
}

export async function rejectRequest(id: string, options: RequestOptions = {}): Promise<Approval> {
  return ApprovalSchema.parse(
    await apiRequest<unknown>(`/approvals/${id}/reject`, { ...options, method: "POST" }),
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

export const PurgeExpiredResultSchema = z.object({
  purged: z.number(),
  ids: z.array(z.string()),
});

export type PurgeExpiredResult = z.infer<typeof PurgeExpiredResultSchema>;

/** Bulk-remove every expired pending approval in ONE request (FEAT-B1).
 *  Expiry is decided server-side with the same 48h window as the UI badge. */
export async function purgeExpiredApprovals(
  options: RequestOptions = {},
): Promise<PurgeExpiredResult> {
  return PurgeExpiredResultSchema.parse(
    await apiRequest<unknown>("/approvals/purge-expired", { ...options, method: "POST" }),
  );
}
