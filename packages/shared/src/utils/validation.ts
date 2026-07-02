/**
 * Validation helpers built on zod, returning our Result type instead of throwing.
 */
import { z } from 'zod';
import { ok, err, type Result } from './result.js';

/**
 * Parse `input` against a zod schema, returning a Result. Errors are flattened
 * into a single human-readable string so callers never have to catch.
 */
export function validate<T>(schema: z.ZodType<T>, input: unknown): Result<T, string> {
  const parsed = schema.safeParse(input);
  if (parsed.success) {
    return ok(parsed.data);
  }
  const message = parsed.error.issues
    .map((issue) => `${issue.path.join('.') || '(root)'}: ${issue.message}`)
    .join('; ');
  return err(message);
}

/** Common reusable schemas. */
export const schemas = {
  /** Non-empty trimmed string. */
  nonEmptyString: z.string().trim().min(1, 'must not be empty'),
  /** Semantic version like 1.2.3. */
  semver: z.string().regex(/^\d+\.\d+\.\d+$/, 'must be a semver string'),
  /** RFC-ish email. */
  email: z.string().email(),
  /** Absolute http(s) URL. */
  url: z.string().url(),
};

export { z };
