/**
 * D-QDEPTH — worker queue depth (`GET /queue/status`).
 *
 * Mirrors the backend contract exactly: `queuedJobs` is `null` whenever the
 * server could not read Redis (`state: "unavailable"`) — never a fabricated
 * `0`. Callers must treat `null` and `0` as distinct: `0` means "asked and
 * the queue is empty", `null` means "could not ask".
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export const QueueStatusSchema = z.object({
  queuedJobs: z.number().int().nullable(),
  state: z.enum(["ok", "unavailable"]),
});
export type QueueStatus = z.infer<typeof QueueStatusSchema>;

export async function fetchQueueStatus(options: RequestOptions = {}): Promise<QueueStatus> {
  return QueueStatusSchema.parse(await apiRequest<unknown>("/queue/status", options));
}
