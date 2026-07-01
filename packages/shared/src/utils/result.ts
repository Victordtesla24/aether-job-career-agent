/**
 * A discriminated-union Result type for explicit, exception-free error handling.
 */
export type Result<T, E = string> =
  | { success: true; data: T }
  | { success: false; error: E };

/** Construct a successful Result. */
export function ok<T>(data: T): Result<T, never> {
  return { success: true, data };
}

/** Construct a failed Result. */
export function err<E>(error: E): Result<never, E> {
  return { success: false, error };
}

/** Type guard: is this a successful Result? */
export function isOk<T, E>(r: Result<T, E>): r is { success: true; data: T } {
  return r.success === true;
}

/** Type guard: is this a failed Result? */
export function isErr<T, E>(r: Result<T, E>): r is { success: false; error: E } {
  return r.success === false;
}

/** Map the data of a successful Result, passing failures through unchanged. */
export function mapResult<T, U, E>(r: Result<T, E>, fn: (data: T) => U): Result<U, E> {
  return isOk(r) ? ok(fn(r.data)) : r;
}
