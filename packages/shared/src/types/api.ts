/**
 * Transport-level API envelope types shared by web and api.
 */

/** Standard success/error envelope for a single resource. */
export type ApiResponse<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError };

/** Structured API error. */
export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

/** Pagination metadata. */
export interface PageInfo {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

/** Envelope for a paginated list of resources. */
export interface PaginatedResponse<T> {
  ok: true;
  data: T[];
  page: PageInfo;
}
