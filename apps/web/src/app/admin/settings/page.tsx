"use client";

/**
 * /admin/settings — platform settings (§15 Tier 1). Signup toggle: when off,
 * POST /api/auth/register returns 403. Email-verification is a placeholder
 * toggle wired to the same append-only audit trail.
 */
import { useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import {
  fetchAdminSettings,
  updateAdminSettings,
  type AdminSettings,
} from "../../../lib/api/admin";

function Toggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-aether-text">{label}</p>
        <p className="mt-1 text-xs text-aether-muted">{hint}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`mt-1 h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
          checked ? "bg-aether-green" : "bg-white/15"
        }`}
      >
        <span
          className={`block h-5 w-5 rounded-full bg-white transition-transform ${
            checked ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

export default function AdminSettingsPage() {
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchAdminSettings()
      .then((s) => !cancelled && setSettings(s))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Failed to load"));
    return () => {
      cancelled = true;
    };
  }, []);

  const patch = async (p: Partial<AdminSettings>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await updateAdminSettings(p);
      setSettings(next);
      setNotice("Settings saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setBusy(false);
    }
  };

  if (error && !settings) return <p className="text-sm text-red-300">{error}</p>;
  if (!settings) return <p className="text-sm text-aether-muted">Loading settings…</p>;

  return (
    <div className="max-w-2xl">
      <AdminPageHeader title="Settings" subtitle="Registration and verification controls." />

      {notice ? <p className="mb-3 text-sm text-aether-green">{notice}</p> : null}
      {error ? <p className="mb-3 text-sm text-red-300">{error}</p> : null}

      <div className="flex flex-col gap-3">
        <Toggle
          label="Public registration"
          hint="When off, self-service signup is disabled and POST /api/auth/register returns 403."
          checked={settings.signupEnabled}
          disabled={busy}
          onChange={(v) => void patch({ signupEnabled: v })}
        />
        <Toggle
          label="Email verification"
          hint="Placeholder toggle for the upcoming email-verification requirement."
          checked={settings.emailVerificationEnabled}
          disabled={busy}
          onChange={(v) => void patch({ emailVerificationEnabled: v })}
        />
      </div>
    </div>
  );
}
