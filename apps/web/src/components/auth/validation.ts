/**
 * Pure, unit-testable client-side validation for the /signup form (no
 * React/DOM). Mirrors the server's real policy so a user gets instant
 * feedback instead of a round-trip 422 — but the server
 * (apps/api/app/repositories/user.py: validate_password_policy) remains the
 * only source of truth; this is a courtesy check, not a security boundary.
 */

/** Mirrors apps/api/app/repositories/user.py MIN_PASSWORD_LENGTH. */
export const PASSWORD_MIN_LENGTH = 8;

/** Mirrors apps/api/app/security.py BCRYPT_MAX_PASSWORD_BYTES. bcrypt only
 * hashes the first 72 bytes, so the server rejects longer passwords
 * (MV-signup-001) — mirror the cap here for instant feedback. */
export const PASSWORD_MAX_BYTES = 72;

/** RFC 5321 total-length limit for an email address. The server's EmailStr
 * validator rejects longer addresses with a raw technical message, so cap it
 * client-side with an honest error instead (MV-signup-003). */
export const EMAIL_MAX_LENGTH = 254;

/** UTF-8 byte length — the unit bcrypt's 72-byte limit is measured in (a
 * multibyte character counts as its encoded length, not one character). */
function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

/** Mirrors apps/api/app/repositories/user.py validate_password_policy: at
 * least PASSWORD_MIN_LENGTH characters, at most PASSWORD_MAX_BYTES UTF-8
 * bytes, and at least one digit. */
export function passwordPolicyErrors(password: string): string[] {
  const errors: string[] = [];
  if (password.length < PASSWORD_MIN_LENGTH) {
    errors.push(`Password must be at least ${PASSWORD_MIN_LENGTH} characters.`);
  }
  if (utf8ByteLength(password) > PASSWORD_MAX_BYTES) {
    errors.push(`Password must be at most ${PASSWORD_MAX_BYTES} bytes.`);
  }
  if (!/\d/.test(password)) {
    errors.push("Password must contain at least one digit.");
  }
  return errors;
}

/** Lightweight shape check — the server's EmailStr validator has final say. */
export function emailLooksValid(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

export interface SignupFormValues {
  name: string;
  email: string;
  password: string;
}

export interface SignupFormErrors {
  email?: string;
  password?: string;
}

/** Validate the signup form; `name` is optional so it never produces an error. */
export function validateSignupForm(values: SignupFormValues): SignupFormErrors {
  const errors: SignupFormErrors = {};

  if (!values.email.trim()) {
    errors.email = "Email is required.";
  } else if (values.email.trim().length > EMAIL_MAX_LENGTH) {
    errors.email = `Email must be ${EMAIL_MAX_LENGTH} characters or fewer.`;
  } else if (!emailLooksValid(values.email)) {
    errors.email = "Enter a valid email address.";
  }

  const passwordErrors = passwordPolicyErrors(values.password);
  if (passwordErrors.length > 0) {
    errors.password = passwordErrors.join(" ");
  }

  return errors;
}

export function hasErrors(errors: SignupFormErrors): boolean {
  return Object.keys(errors).length > 0;
}
