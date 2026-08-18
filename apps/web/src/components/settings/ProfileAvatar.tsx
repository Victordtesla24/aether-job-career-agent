/**
 * Settings → Profile identity chip + Change avatar / Remove photo.
 *
 * Loads the stored photo via authenticated fetch → blob URL (JWT is in
 * localStorage; a bare ``<img src>`` cannot send Authorization). Revokes the
 * object URL on unmount / revision change.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiBaseUrl, getToken } from "../../lib/api/client";
import type { SettingsPayload } from "../../lib/api/workspaces";
import {
  AVATAR_ACCEPT,
  AVATAR_CHANGE_LABEL,
  AVATAR_HELP_TEXT,
  AVATAR_REMOVE_LABEL,
  announceProfileAvatarChanged,
  describeAvatarUploadError,
  validateAvatarFile,
} from "./profile-avatar";

export function ProfileAvatar({
  initials,
  fullName,
  hasAvatar,
  avatarRevision,
  onChanged,
}: {
  initials: string;
  fullName: string;
  hasAvatar: boolean;
  avatarRevision: string | null;
  onChanged: (payload: SettingsPayload) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [photoSrc, setPhotoSrc] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    async function load() {
      if (!hasAvatar) {
        setPhotoSrc(null);
        return;
      }
      try {
        const token = await getToken();
        const res = await fetch(`${apiBaseUrl()}/workspaces/settings/avatar`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          if (!cancelled) setPhotoSrc(null);
          return;
        }
        const blob = await res.blob();
        objectUrl = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setPhotoSrc(objectUrl);
      } catch {
        if (!cancelled) setPhotoSrc(null);
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [hasAvatar, avatarRevision]);

  const upload = useCallback(
    async (file: File) => {
      const clientError = validateAvatarFile(file);
      if (clientError) {
        setError(clientError);
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`${apiBaseUrl()}/workspaces/settings/avatar`, {
          method: "POST",
          headers: { Authorization: `Bearer ${await getToken()}` },
          body: form,
        });
        if (!res.ok) {
          const rawBody = await res.text().catch(() => "");
          throw new Error(describeAvatarUploadError(res.status, rawBody));
        }
        const updated = (await res.json()) as SettingsPayload;
        onChanged(updated);
        announceProfileAvatarChanged({
          hasAvatar: updated.profile.hasAvatar,
          avatarRevision: updated.profile.avatarRevision,
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setBusy(false);
        if (inputRef.current) inputRef.current.value = "";
      }
    },
    [onChanged],
  );

  const remove = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl()}/workspaces/settings/avatar`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${await getToken()}` },
      });
      if (!res.ok) {
        const rawBody = await res.text().catch(() => "");
        throw new Error(describeAvatarUploadError(res.status, rawBody));
      }
      const updated = (await res.json()) as SettingsPayload;
      onChanged(updated);
      announceProfileAvatarChanged({
        hasAvatar: updated.profile.hasAvatar,
        avatarRevision: updated.profile.avatarRevision,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Remove failed");
    } finally {
      setBusy(false);
    }
  }, [onChanged]);

  return (
    <div className="mb-5 flex items-center gap-4" data-testid="settings-profile-avatar">
      {photoSrc ? (
        // eslint-disable-next-line @next/next/no-img-element -- blob: URL from authenticated fetch
        <img
          src={photoSrc}
          alt={fullName.trim() || "Profile photo"}
          data-testid="settings-avatar-img"
          className="h-14 w-14 shrink-0 rounded-[10px] object-cover"
        />
      ) : (
        <span
          data-testid="settings-avatar-initials"
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[10px] bg-sapphire/20 text-lg font-bold text-sapphire"
        >
          {initials || "?"}
        </span>
      )}
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="settings-avatar-change"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            className="rounded-lg border border-white/8 bg-white/5 px-3 py-1.5 text-xs font-medium transition hover:bg-white/10 disabled:opacity-50"
          >
            {busy ? "Working…" : AVATAR_CHANGE_LABEL}
          </button>
          {hasAvatar ? (
            <button
              type="button"
              data-testid="settings-avatar-remove"
              disabled={busy}
              onClick={() => void remove()}
              className="rounded-lg border border-white/8 bg-transparent px-3 py-1.5 text-xs font-medium text-aether-muted transition hover:bg-white/5 hover:text-white disabled:opacity-50"
            >
              {AVATAR_REMOVE_LABEL}
            </button>
          ) : null}
        </div>
        <p className="mt-1.5 text-[11px] text-aether-muted">{AVATAR_HELP_TEXT}</p>
        {error ? (
          <p
            role="alert"
            data-testid="settings-avatar-error"
            className="mt-1.5 break-words text-xs text-red-300"
          >
            {error}
          </p>
        ) : null}
        <input
          ref={inputRef}
          type="file"
          accept={AVATAR_ACCEPT}
          className="hidden"
          data-testid="settings-avatar-input"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
          }}
        />
      </div>
    </div>
  );
}
