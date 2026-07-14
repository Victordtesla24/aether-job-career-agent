/**
 * /signup client validation (feat/auth-fe).
 *
 * RED first: components/auth/validation.ts does not exist yet. Mirrors the
 * server's real policy (apps/api/app/repositories/user.py
 * validate_password_policy: >=8 chars, >=1 digit) so client- and server-side
 * rules can never silently drift without both test suites failing.
 */
import { describe, expect, it } from "vitest";

import {
  emailLooksValid,
  hasErrors,
  passwordPolicyErrors,
  validateSignupForm,
} from "../../components/auth/validation";

describe("passwordPolicyErrors", () => {
  it("flags a password shorter than 8 characters", () => {
    expect(passwordPolicyErrors("abc1")).toContain("Password must be at least 8 characters.");
  });

  it("flags a password with no digit", () => {
    expect(passwordPolicyErrors("abcdefgh")).toContain("Password must contain at least one digit.");
  });

  it("accepts a password meeting both rules", () => {
    expect(passwordPolicyErrors("abcdefg1")).toEqual([]);
  });

  it("can report both violations at once", () => {
    expect(passwordPolicyErrors("abc")).toEqual([
      "Password must be at least 8 characters.",
      "Password must contain at least one digit.",
    ]);
  });
});

describe("emailLooksValid", () => {
  it("accepts a plausible email", () => {
    expect(emailLooksValid("new.user@example.com")).toBe(true);
  });

  it("rejects a missing @", () => {
    expect(emailLooksValid("not-an-email")).toBe(false);
  });

  it("rejects a missing domain dot", () => {
    expect(emailLooksValid("user@localhost")).toBe(false);
  });

  it("rejects embedded whitespace", () => {
    expect(emailLooksValid("us er@example.com")).toBe(false);
  });
});

describe("validateSignupForm", () => {
  it("is valid for a well-formed submission with no name", () => {
    const errors = validateSignupForm({ name: "", email: "new.user@example.com", password: "abcdefg1" });
    expect(hasErrors(errors)).toBe(false);
  });

  it("requires an email", () => {
    const errors = validateSignupForm({ name: "", email: "", password: "abcdefg1" });
    expect(errors.email).toBe("Email is required.");
  });

  it("rejects a malformed email", () => {
    const errors = validateSignupForm({ name: "", email: "nope", password: "abcdefg1" });
    expect(errors.email).toMatch(/valid email/i);
  });

  it("surfaces password policy violations", () => {
    const errors = validateSignupForm({ name: "", email: "new.user@example.com", password: "short" });
    expect(errors.password).toMatch(/8 characters/);
    expect(errors.password).toMatch(/digit/);
  });

  it("never produces a name error — name is optional", () => {
    const errors = validateSignupForm({ name: "", email: "bad", password: "short" });
    expect("name" in errors).toBe(false);
  });
});
