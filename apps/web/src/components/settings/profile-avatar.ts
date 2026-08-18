/**
 * Pure helpers for Settings → Profile photo upload (wireframe btn-avatar-st08).
 *
 * Contract: PNG or JPG, max 2MB. Client checks are UX only — the server
 * re-sniffs magic bytes and enforces the same cap. Photo is account chrome;
 * it is never applied to employer-facing résumés or application emails.
 */

import { describeUploadError } from "./resume-upload";

/** Hard ceiling mirroring ``MAX_AVATAR_BYTES`` on the API. */
export const MAX_AVATAR_BYTES = 2 * 1024 * 1024;

/** ``accept`` attribute for the file input. */
export const AVATAR_ACCEPT = "image/png,image/jpeg,.png,.jpg,.jpeg";

/** Helper copy under the Change avatar control (wireframe). */
export const AVATAR_HELP_TEXT = "PNG or JPG, max 2MB";

/** Change-avatar button label (wireframe). */
export const AVATAR_CHANGE_LABEL = "Change avatar";

/** Remove control — only shown when a photo is stored. */
export const AVATAR_REMOVE_LABEL = "Remove photo";

const ALLOWED_EXTENSIONS = new Set([".png", ".jpg", ".jpeg"]);
const ALLOWED_MIME = new Set(["image/png", "image/jpeg"]);

/**
 * Return a human-readable rejection, or ``null`` when the file may be sent.
 * Extension / declared MIME are best-effort; the server is the real gate.
 */
export function validateAvatarFile(file: File): string | null {
  if (file.size > MAX_AVATAR_BYTES) {
    return `Profile photo is larger than the ${MAX_AVATAR_BYTES / (1024 * 1024)}MB upload limit.`;
  }
  const name = file.name.toLowerCase();
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot) : "";
  const mimeOk = ALLOWED_MIME.has(file.type);
  const extOk = ALLOWED_EXTENSIONS.has(ext);
  // Empty type is common for some pickers — allow when the extension is right.
  if (!mimeOk && !extOk) {
    return "Aether accepts PNG or JPG photos up to 2 MB. This file is not a readable PNG or JPEG.";
  }
  if (!extOk && file.type && !mimeOk) {
    return "Aether accepts PNG or JPG photos up to 2 MB. This file is not a readable PNG or JPEG.";
  }
  return null;
}

/** Bounded honest message from a failed avatar upload/delete response. */
export function describeAvatarUploadError(status: number, rawBody: string): string {
  return describeUploadError(status, rawBody);
}
