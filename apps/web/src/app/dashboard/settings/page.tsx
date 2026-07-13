"use client";

/**
 * Settings — profile, resume management, portfolio sync, agent configuration,
 * job board integrations and connected accounts. Backed by GET/PUT /settings
 * (wireframe: settings.html). The Save button validates and persists via PUT.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { apiBaseUrl, getToken } from "../../../lib/api/client";
import {
  fetchCareerData,
  fetchSettings,
  refreshCareerData,
  saveSettings,
  type CareerData,
  type CareerDataSource,
  type SettingsPayload,
} from "../../../lib/api/workspaces";
import {
  bySource,
  buildRefreshPayload,
  careerStatusLabel,
  careerStatusStyle,
  deriveInputs,
  type CareerDataInputs,
} from "../../../components/settings/career-data";
import { SECTIONS } from "./sections";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const STATUS_STYLE: Record<string, string> = {
  connected: "bg-aether-green/15 text-aether-green border-aether-green/25",
  syncing: "bg-aether-amber/15 text-aether-amber border-aether-amber/25",
  not_configured: "bg-white/5 text-aether-muted-dim border-white/10",
  disconnected: "bg-red-500/10 text-red-300 border-red-500/25",
};

export default function SettingsPage() {
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string>("profile");
  const [profile, setProfile] = useState({ fullName: "", email: "", targetRole: "", location: "" });
  const [agentConfig, setAgentConfig] = useState({ autoApply: false, approvalGate: true, matchThreshold: 80 });
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Career Data (GAP-P4-047 · ADR D-0031): real GitHub + portfolio ingestion
  // and a workspace-stored LinkedIn paste, all feeding tailoring context.
  const [career, setCareer] = useState<CareerData | null>(null);
  const [careerInputs, setCareerInputs] = useState<CareerDataInputs>({
    githubUsername: "",
    portfolioUrl: "",
    linkedinSummary: "",
  });
  const [linkedinDirty, setLinkedinDirty] = useState(false);
  const [careerSyncing, setCareerSyncing] = useState(false);
  const [careerError, setCareerError] = useState<string | null>(null);
  const [careerNotice, setCareerNotice] = useState<string | null>(null);

  // Gate "Sync now" on the initial GET having resolved: until `career` is
  // populated, `careerInputs` still holds its un-loaded default (empty
  // strings), and submitting that verbatim would send an implicit clear of
  // a githubUsername/portfolioUrl the server already has configured
  // (GAP-P4-047 Wave-1 regression).
  const careerLoaded = career !== null;

  const refreshCareer = async () => {
    if (!careerLoaded) return;
    setCareerSyncing(true);
    setCareerError(null);
    setCareerNotice(null);
    try {
      const updated = await refreshCareerData(
        buildRefreshPayload(careerInputs, linkedinDirty, careerLoaded),
      );
      setCareer(updated);
      setCareerInputs(deriveInputs(updated));
      setLinkedinDirty(false);
      const failed = updated.sources.filter((s) => s.status === "error");
      setCareerNotice(
        failed.length > 0
          ? `Synced with ${failed.length} source error${failed.length > 1 ? "s" : ""} — see below.`
          : "Career data synced ✓",
      );
    } catch (e) {
      setCareerError(e instanceof Error ? e.message : "Career data refresh failed");
    } finally {
      setCareerSyncing(false);
    }
  };

  const uploadResume = async (file: File) => {
    setUploading(true);
    setUploadNotice(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${apiBaseUrl()}/resumes/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${await getToken()}` },
        body: form,
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(`Upload failed (${res.status}): ${detail.slice(0, 160)}`);
      }
      const created = (await res.json()) as { label?: string; version?: number };
      setUploadNotice(
        `Uploaded and parsed — registered as v${created.version} (“${created.label}”); story extraction ran.`,
      );
      setData(await fetchSettings());
    } catch (e) {
      setUploadNotice(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    fetchSettings()
      .then((s) => {
        setData(s);
        setProfile(s.profile);
        setAgentConfig(s.agentConfig);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load settings"));
  }, []);

  useEffect(() => {
    fetchCareerData()
      .then((c) => {
        setCareer(c);
        setCareerInputs(deriveInputs(c));
      })
      .catch((e: unknown) =>
        setCareerError(e instanceof Error ? e.message : "Failed to load career data"),
      );
  }, []);

  const validation = useMemo(() => {
    const errors: Record<string, string> = {};
    if (!profile.fullName.trim()) errors.fullName = "Full name is required";
    if (!EMAIL_RE.test(profile.email)) errors.email = "Enter a valid email address";
    if (!profile.targetRole.trim()) errors.targetRole = "Target role is required";
    if (!profile.location.trim()) errors.location = "Location is required";
    return errors;
  }, [profile]);

  const save = async () => {
    if (Object.keys(validation).length > 0) {
      setSavedNotice(null);
      setError("Fix the highlighted fields before saving.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await saveSettings(profile, agentConfig);
      setData(updated);
      setSavedNotice("Settings saved ✓");
      setTimeout(() => setSavedNotice(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const syncOne = (name: string) => {
    setSyncing((prev) => ({ ...prev, [name]: true }));
    setTimeout(() => setSyncing((prev) => ({ ...prev, [name]: false })), 1500);
  };

  if (error && data === null) {
    return <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>;
  }

  if (data === null) {
    return (
      <div className="space-y-4" aria-busy="true" data-testid="settings-skeleton">
        {[0, 1].map((i) => (
          <div key={i} className="glass h-56 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </div>
    );
  }

  const avatarInitials = profile.fullName
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="space-y-6" data-testid="settings-page">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Settings &amp; Profile</h1>
          <p className="text-sm text-aether-muted">Profile, agent behaviour and integrations.</p>
        </div>
        <div className="flex items-center gap-3">
          {savedNotice ? (
            <span role="status" data-testid="settings-saved-notice" className="text-sm text-aether-green">
              {savedNotice}
            </span>
          ) : null}
          <button
            type="button"
            data-testid="save-settings-btn"
            onClick={() => void save()}
            disabled={saving}
            className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </header>

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-4">
        {/* Subnav */}
        <nav className="glass h-fit rounded-2xl border border-white/10 p-2 xl:col-span-1" aria-label="Settings sections">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              data-testid={`settings-nav-${s.id}`}
              onClick={() => setActive(s.id)}
              aria-pressed={active === s.id}
              className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                active === s.id ? "bg-aether-coral/15 font-semibold text-aether-coral" : "text-aether-muted hover:text-white"
              }`}
            >
              {s.label}
            </button>
          ))}
        </nav>

        {/* Sections */}
        <div className="space-y-6 xl:col-span-3">
          {(active === "profile" || active === "privacy") && (
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-profile">
              <h2 className="mb-4 text-[15px] font-semibold">Profile</h2>
              <div className="mb-5 flex items-center gap-4">
                <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-aether-violet/20 text-lg font-bold text-aether-violet">
                  {avatarInitials || "?"}
                </span>
                <div>
                  <p className="text-sm font-semibold">{profile.fullName || "Your name"}</p>
                  <p className="text-xs text-aether-muted-dim">{profile.targetRole || "Target role"}</p>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <Input label="Full name" value={profile.fullName} error={validation.fullName} testId="settings-fullname"
                  onChange={(v) => setProfile((p) => ({ ...p, fullName: v }))} />
                <Input label="Email" value={profile.email} error={validation.email} testId="settings-email"
                  onChange={(v) => setProfile((p) => ({ ...p, email: v }))} />
                <Input label="Target role" value={profile.targetRole} error={validation.targetRole} testId="settings-targetrole"
                  onChange={(v) => setProfile((p) => ({ ...p, targetRole: v }))} />
                <Input label="Location" value={profile.location} error={validation.location} testId="settings-location"
                  onChange={(v) => setProfile((p) => ({ ...p, location: v }))} />
              </div>
              {active === "privacy" ? (
                <p className="mt-4 rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-aether-muted">
                  <i className="fa-solid fa-shield-halved mr-2 text-aether-green" aria-hidden="true" />
                  Aether stores your data locally to this workspace. Agents never submit an application, send an
                  email, or share your profile without an explicit approval. You can export or delete all data at any time.
                </p>
              ) : null}
            </section>
          )}

          {(active === "resume" || active === "portfolio" || active === "profile") && (
            <div className="space-y-6">
              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-resume">
                <h2 className="mb-3 text-[15px] font-semibold">Resume Management</h2>
                <div className="flex items-center justify-between rounded-xl border border-aether-green/25 bg-aether-green/5 p-3">
                  <div className="flex items-center gap-2.5">
                    <i className="fa-solid fa-file-pdf text-aether-coral" aria-hidden="true" />
                    <div>
                      <p className="text-xs font-semibold">{data.resume.activeFile}</p>
                      <p className="mono text-[10px] text-aether-muted-dim">
                        uploaded {data.resume.uploadedAt} · {data.resume.versions} versions
                      </p>
                    </div>
                  </div>
                  <span className="rounded-md bg-aether-green/15 px-2 py-0.5 text-[10px] font-medium text-aether-green">
                    Active
                  </span>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.txt,.md,application/pdf,text/plain"
                  className="hidden"
                  data-testid="resume-upload-input"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void uploadResume(f);
                    e.target.value = "";
                  }}
                />
                <button
                  type="button"
                  data-testid="resume-upload-btn"
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                  className="mt-3 w-full rounded-lg border border-dashed border-white/15 py-2 text-xs text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
                >
                  <i
                    className={`fa-solid ${uploading ? "fa-spinner fa-spin" : "fa-upload"} mr-2`}
                    aria-hidden="true"
                  />
                  {uploading ? "Parsing…" : "Upload new version"}
                </button>
                {uploadNotice ? (
                  <p
                    className="mt-2 text-[11px] text-aether-muted"
                    data-testid="resume-upload-notice"
                    role="status"
                  >
                    {uploadNotice}
                  </p>
                ) : null}
              </section>

              <section
                className="glass rounded-2xl border border-white/10 p-5"
                data-testid="settings-portfolio"
                aria-labelledby="career-data-heading"
              >
                <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
                  <h2 id="career-data-heading" className="text-[15px] font-semibold">
                    Career Data
                  </h2>
                  {careerNotice ? (
                    <span role="status" data-testid="career-data-notice" className="text-[11px] text-aether-green">
                      {careerNotice}
                    </span>
                  ) : null}
                </div>
                <p className="mb-4 text-[11px] text-aether-muted-dim">
                  Aether consolidates your public GitHub, portfolio site and LinkedIn summary into the
                  evidence your tailoring and cover-letter agents draw on. Update a source and press
                  “Sync now” to re-ingest it.
                </p>

                {careerError ? (
                  <p
                    className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-[11px] text-red-300"
                    role="alert"
                    data-testid="career-data-error"
                  >
                    {careerError}
                  </p>
                ) : null}

                <div className="space-y-4">
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label
                        htmlFor="career-github"
                        className="text-[11px] font-medium uppercase tracking-wide text-aether-muted"
                      >
                        GitHub username
                      </label>
                      <SourceStatusChip source={bySource(career, "github")} />
                    </div>
                    <input
                      id="career-github"
                      type="text"
                      data-testid="career-github-input"
                      value={careerInputs.githubUsername}
                      onChange={(e) => setCareerInputs((c) => ({ ...c, githubUsername: e.target.value }))}
                      placeholder="e.g. octocat"
                      autoComplete="off"
                      className="mono w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-aether-coral/50"
                    />
                    <SourceError source={bySource(career, "github")} />
                  </div>

                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label
                        htmlFor="career-portfolio"
                        className="text-[11px] font-medium uppercase tracking-wide text-aether-muted"
                      >
                        Portfolio URL
                      </label>
                      <SourceStatusChip source={bySource(career, "portfolio")} />
                    </div>
                    <input
                      id="career-portfolio"
                      type="url"
                      data-testid="career-portfolio-input"
                      value={careerInputs.portfolioUrl}
                      onChange={(e) => setCareerInputs((c) => ({ ...c, portfolioUrl: e.target.value }))}
                      placeholder="https://your-portfolio.example"
                      autoComplete="off"
                      className="mono w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-aether-coral/50"
                    />
                    <SourceError source={bySource(career, "portfolio")} />
                  </div>

                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label
                        htmlFor="career-linkedin"
                        className="text-[11px] font-medium uppercase tracking-wide text-aether-muted"
                      >
                        Paste your LinkedIn summary
                      </label>
                      <SourceStatusChip source={bySource(career, "linkedin")} />
                    </div>
                    <textarea
                      id="career-linkedin"
                      data-testid="career-linkedin-input"
                      value={careerInputs.linkedinSummary}
                      onChange={(e) => {
                        setCareerInputs((c) => ({ ...c, linkedinSummary: e.target.value }));
                        setLinkedinDirty(true);
                      }}
                      rows={4}
                      placeholder="Paste the text from your LinkedIn ‘About’ / summary section…"
                      className="w-full resize-y rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-aether-coral/50"
                    />
                    <p className="mt-1 text-[10px] text-aether-muted-dim">
                      {career?.linkedinNote ??
                        "LinkedIn has no public profile API — paste your summary to include it in tailoring."}
                    </p>
                    <SourceError source={bySource(career, "linkedin")} />
                  </div>
                </div>

                <button
                  type="button"
                  data-testid="career-sync-btn"
                  onClick={() => void refreshCareer()}
                  disabled={careerSyncing || !careerLoaded}
                  title={careerLoaded ? undefined : "Loading your career data…"}
                  className="mt-4 w-full rounded-lg border border-white/15 py-2 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
                >
                  {careerSyncing ? "Syncing…" : "Sync now"}
                </button>
              </section>
            </div>
          )}

          {(active === "agents" || active === "profile") && (
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-agents">
              <h2 className="mb-4 text-[15px] font-semibold">Agent Configuration</h2>
              <div className="space-y-4">
                <Toggle
                  label="Auto-apply"
                  description="Let agents submit applications without a manual approval step"
                  value={agentConfig.autoApply}
                  testId="toggle-autoapply"
                  onChange={(v) => setAgentConfig((c) => ({ ...c, autoApply: v }))}
                />
                <Toggle
                  label="Approval gate"
                  description="Require explicit approval for anything that leaves the system"
                  value={agentConfig.approvalGate}
                  testId="toggle-approvalgate"
                  onChange={(v) => setAgentConfig((c) => ({ ...c, approvalGate: v }))}
                />
                <div>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-aether-muted">Match threshold — only surface jobs above</span>
                    <span className="mono font-semibold">{agentConfig.matchThreshold}%</span>
                  </div>
                  <input
                    type="range"
                    min={50}
                    max={100}
                    step={5}
                    value={agentConfig.matchThreshold}
                    data-testid="threshold-slider"
                    onChange={(e) => setAgentConfig((c) => ({ ...c, matchThreshold: Number(e.target.value) }))}
                    className="w-full accent-[#FF6B35]"
                    aria-label="Match threshold"
                  />
                </div>
              </div>
            </section>
          )}

          {active === "notifications" && (
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-notifications">
              <h2 className="mb-4 text-[15px] font-semibold">Notifications</h2>
              <div className="space-y-4">
                <Toggle label="Approval requests" description="Notify me when an agent needs my approval"
                  value={true} testId="toggle-notif-approvals" onChange={() => undefined} />
                <Toggle label="Application updates" description="Status changes, recruiter views and responses"
                  value={true} testId="toggle-notif-apps" onChange={() => undefined} />
                <Toggle label="Weekly digest" description="Summary of agent activity every Monday morning"
                  value={false} testId="toggle-notif-digest" onChange={() => undefined} />
              </div>
            </section>
          )}

          {(active === "integrations" || active === "profile") && (
            <>
              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-integrations">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-[15px] font-semibold">Job Board Integrations</h2>
                  <button
                    type="button"
                    data-testid="sync-all-btn"
                    onClick={() => data.integrations.forEach((i) => syncOne(i.name))}
                    className="rounded-lg border border-white/15 px-3 py-1.5 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white"
                  >
                    Sync All
                  </button>
                </div>
                <div className="space-y-2.5">
                  {data.integrations.map((i) => (
                    <div key={i.name} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 p-3">
                      <div>
                        <p className="text-xs font-semibold">{i.name}</p>
                        <p className="text-[11px] text-aether-muted-dim">{syncing[i.name] ? "Syncing…" : i.detail}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${STATUS_STYLE[i.status] ?? STATUS_STYLE.not_configured}`}>
                          {syncing[i.name] ? "syncing" : i.status.replace("_", " ")}
                        </span>
                        <button
                          type="button"
                          data-testid={`sync-${i.name.toLowerCase().replace(/\s/g, "-")}`}
                          onClick={() => syncOne(i.name)}
                          className="rounded-md border border-white/15 px-2 py-1 text-[10px] text-aether-muted hover:border-white/30 hover:text-white"
                        >
                          {syncing[i.name] ? "…" : "Sync"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-accounts">
                <h2 className="mb-3 text-[15px] font-semibold">Connected Accounts &amp; API Keys</h2>
                <div className="space-y-2.5">
                  {data.connectedAccounts.map((a) => (
                    <div key={a.name} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 p-3">
                      <div>
                        <p className="text-xs font-semibold">
                          {a.name} <span className="ml-1 rounded-md border border-aether-green/25 bg-aether-green/15 px-2 py-0.5 text-[10px] font-medium text-aether-green">Connected</span>
                        </p>
                        <p className="mono mt-1 text-[11px] text-aether-muted-dim">{a.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** Status chip for one career-data source (GAP-P4-047). */
function SourceStatusChip({ source }: { source?: CareerDataSource }) {
  const status = source?.status ?? "not_configured";
  return (
    <span
      data-testid={`career-${source?.source ?? "unknown"}-status`}
      className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${careerStatusStyle(status)}`}
    >
      {careerStatusLabel(status)}
      {source?.lastSynced ? (
        <span className="ml-1 text-aether-muted-dim">· {source.lastSynced.slice(0, 10)}</span>
      ) : null}
    </span>
  );
}

/**
 * Honest per-source detail line: red for a true error, muted guidance for an
 * "empty"/"not configured" source, nothing once the source is synced.
 */
function SourceError({ source }: { source?: CareerDataSource }) {
  if (!source || source.status === "ok" || !source.error) return null;
  const tone = source.status === "error" ? "text-red-300" : "text-aether-muted-dim";
  return (
    <p className={`mt-1 text-[10px] ${tone}`} data-testid={`career-${source.source}-detail`}>
      {source.error}
    </p>
  );
}

function Input({
  label,
  value,
  onChange,
  error,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  testId: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-aether-muted">{label}</span>
      <input
        type="text"
        value={value}
        data-testid={testId}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={Boolean(error)}
        className={`w-full rounded-lg border bg-white/5 px-3 py-2 text-sm outline-none ${
          error ? "border-red-500/50" : "border-white/10 focus:border-aether-coral/50"
        }`}
      />
      {error ? <span className="mt-1 block text-[11px] text-red-300">{error}</span> : null}
    </label>
  );
}

function Toggle({
  label,
  description,
  value,
  onChange,
  testId,
}: {
  label: string;
  description: string;
  value: boolean;
  onChange: (v: boolean) => void;
  testId: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-semibold">{label}</p>
        <p className="text-xs text-aether-muted-dim">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        data-testid={testId}
        onClick={() => onChange(!value)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition ${value ? "bg-aether-green" : "bg-white/15"}`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${value ? "left-[22px]" : "left-0.5"}`}
        />
      </button>
    </div>
  );
}
