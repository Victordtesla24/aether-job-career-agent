"use client";

/**
 * /admin/sales-agent — the NATIVE Sales AI Agent console.
 *
 * This page replaced the old "external growth engine" placeholder: the sales
 * agent now runs INSIDE this app (30-min systemd timer + admin "Run now"),
 * with its own AdminUser-gated API under /api/admin/sales-agent/*. Everything
 * shown here is a live database query — no estimates, no fabricated metrics;
 * reply rate honestly reads "not observable" until real sends exist.
 *
 * Compliance surfaced in the UI: LinkedIn items are DRAFTS ONLY (copy button,
 * never a post button — LinkedIn's Terms prohibit automated posting), the
 * suppression list is permanent, and shadow (dry-run) mode is prominently
 * labelled so the operator always knows whether emails can actually leave.
 */
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import { describeApiError } from "../../../lib/api/client";
import {
  fetchBrandDocumentPreview,
  fetchBrandDocuments,
  fetchSalesCampaignPreview,
  fetchSalesCampaigns,
  fetchSalesHealth,
  fetchSalesLeads,
  fetchSalesOutreach,
  fetchSalesOverview,
  fetchSalesSendingAccounts,
  runSalesAgentNow,
  setSalesSendingAccount,
  generateSalesContent,
  updateSalesCampaign,
  type BrandDocuments,
  type SalesCampaign,
  type SalesGenerateResult,
  type SalesHealth,
  type SalesLeadList,
  type SalesOutreachList,
  type SalesOverview,
  type SalesRunResult,
  type SalesSendingAccount,
} from "../../../lib/api/salesAgent";

type Tab = "campaigns" | "leads" | "outreach" | "linkedin" | "brand";

const TABS: { key: Tab; label: string }[] = [
  { key: "campaigns", label: "Campaigns" },
  { key: "leads", label: "Leads" },
  { key: "outreach", label: "Outreach log" },
  { key: "linkedin", label: "LinkedIn drafts" },
  { key: "brand", label: "Brand" },
];

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function StatCard({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
      <p className="text-xs uppercase tracking-wide text-aether-muted-dim">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-aether-text">{value}</p>
      {note ? <p className="mt-1 text-xs text-aether-muted-dim">{note}</p> : null}
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  const o = outcome ?? "unknown";
  const color =
    o === "sent"
      ? "bg-emerald-500/15 text-emerald-300"
      : o === "dry_run"
        ? "bg-sky-500/15 text-sky-300"
        : o === "draft_queued"
          ? "bg-indigo-500/15 text-indigo-300"
          : o === "blocked" || o === "unsubscribed"
            ? "bg-amber-500/15 text-amber-300"
            : o === "error" || o === "bounced"
              ? "bg-red-500/15 text-red-300"
              : "bg-white/10 text-aether-muted";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {o}
    </span>
  );
}

export default function SalesAgentPage() {
  const [overview, setOverview] = useState<SalesOverview | null>(null);
  const [health, setHealth] = useState<SalesHealth | null>(null);
  const [accounts, setAccounts] = useState<SalesSendingAccount[]>([]);
  const [campaigns, setCampaigns] = useState<SalesCampaign[]>([]);
  const [leads, setLeads] = useState<SalesLeadList | null>(null);
  const [outreach, setOutreach] = useState<SalesOutreachList | null>(null);
  const [drafts, setDrafts] = useState<SalesOutreachList | null>(null);
  const [tab, setTab] = useState<Tab>("campaigns");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<SalesRunResult | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [previewHtml, setPreviewHtml] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genResult, setGenResult] = useState<SalesGenerateResult | null>(null);
  const [brand, setBrand] = useState<BrandDocuments | null>(null);
  const [brandKind, setBrandKind] = useState<string | null>(null);
  const [brandHtml, setBrandHtml] = useState("");
  const [brandLoading, setBrandLoading] = useState(false);
  const [brandPlan, setBrandPlan] = useState("starter");
  const [brandInterval, setBrandInterval] = useState("monthly");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ov, he, ac, ca, le, ou, dr, bd] = await Promise.all([
        fetchSalesOverview(),
        fetchSalesHealth(),
        fetchSalesSendingAccounts(),
        fetchSalesCampaigns(),
        fetchSalesLeads({ limit: 100 }),
        fetchSalesOutreach({ limit: 100 }),
        fetchSalesOutreach({ channel: "linkedin_draft", limit: 50 }),
        fetchBrandDocuments(),
      ]);
      setOverview(ov);
      setHealth(he);
      setAccounts(ac);
      setCampaigns(ca);
      setLeads(le);
      setOutreach(ou);
      setDrafts(dr);
      setBrand(bd);
    } catch (err) {
      setError(describeApiError(err, "Failed to load the sales agent console."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onRunNow = useCallback(async () => {
    setRunning(true);
    setError("");
    try {
      const result = await runSalesAgentNow();
      setRunResult(result);
      await load();
    } catch (err) {
      setError(describeApiError(err, "Run failed."));
    } finally {
      setRunning(false);
    }
  }, [load]);

  const onToggleAccount = useCallback(
    async (account: SalesSendingAccount) => {
      setError("");
      try {
        await setSalesSendingAccount(account.id, !account.usedForSalesAgent);
        await load();
      } catch (err) {
        setError(describeApiError(err, "Could not update the sending account."));
      }
    },
    [load],
  );

  const onSaveCampaign = useCallback(
    async (c: SalesCampaign) => {
      setSaving(true);
      setError("");
      try {
        await updateSalesCampaign(c.id, { templateBody: editBody });
        setEditing(null);
        await load();
      } catch (err) {
        setError(describeApiError(err, "Could not save the campaign."));
      } finally {
        setSaving(false);
      }
    },
    [editBody, load],
  );

  const onToggleCampaign = useCallback(
    async (c: SalesCampaign) => {
      setError("");
      try {
        await updateSalesCampaign(c.id, { active: !c.active });
        await load();
      } catch (err) {
        setError(describeApiError(err, "Could not update the campaign."));
      }
    },
    [load],
  );

  const onPreviewCampaign = useCallback(
    async (c: SalesCampaign) => {
      if (previewing === c.id) {
        setPreviewing(null);
        setPreviewHtml("");
        return;
      }
      setPreviewLoading(true);
      setError("");
      try {
        const preview = await fetchSalesCampaignPreview(c.id);
        setPreviewing(c.id);
        setPreviewHtml(preview.html);
      } catch (err) {
        setError(describeApiError(err, "Could not render the branded preview."));
      } finally {
        setPreviewLoading(false);
      }
    },
    [previewing],
  );

  const onGenerateContent = useCallback(async () => {
    setGenerating(true);
    setError("");
    try {
      const result = await generateSalesContent();
      setGenResult(result);
      await load();
    } catch (err) {
      setError(describeApiError(err, "Content generation failed."));
    } finally {
      setGenerating(false);
    }
  }, [load]);

  const onPreviewBrandDoc = useCallback(
    async (kind: string, plan?: string, interval?: string) => {
      const nextPlan = plan ?? brandPlan;
      const nextInterval = interval ?? brandInterval;
      // Toggle off only when re-clicking the SAME kind with unchanged params.
      if (brandKind === kind && plan === undefined && interval === undefined) {
        setBrandKind(null);
        setBrandHtml("");
        return;
      }
      setBrandLoading(true);
      setError("");
      try {
        const preview = await fetchBrandDocumentPreview(kind, {
          plan: nextPlan,
          interval: nextInterval,
        });
        setBrandKind(kind);
        setBrandHtml(preview.html);
      } catch (err) {
        setError(describeApiError(err, "Could not render the document preview."));
      } finally {
        setBrandLoading(false);
      }
    },
    [brandKind, brandPlan, brandInterval],
  );

  const copyDraft = useCallback(async (id: string, body: string | null) => {
    if (!body) return;
    try {
      await navigator.clipboard.writeText(body);
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      /* clipboard unavailable — non-fatal */
    }
  }, []);

  // Health alarm: red banner when the timer has been silent past the stale
  // line (2× the 30-min interval) or the ledger itself errored.
  const healthAlarm =
    health != null && (health.status === "stale" || health.status === "error");

  return (
    <div>
      <AdminPageHeader
        title="Sales Agent"
        subtitle="Native in-app growth agent — inbound leads, lifecycle emails, LinkedIn drafts. Every number below is a live database query."
      />

      {error ? <p className="mb-3 text-sm text-red-300">{error}</p> : null}

      {healthAlarm ? (
        <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          <p className="font-semibold">Sales agent scheduler alarm</p>
          <p className="mt-1">{health?.detail}</p>
        </div>
      ) : null}

      {/* Health / control strip */}
      <div className="mb-5 rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
              health?.status === "ok"
                ? "bg-emerald-500/15 text-emerald-300"
                : healthAlarm
                  ? "bg-red-500/15 text-red-300"
                  : "bg-white/10 text-aether-muted"
            }`}
          >
            {health ? `scheduler: ${health.status}` : "scheduler: …"}
          </span>
          <span
            className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
              health?.enabled ? "bg-emerald-500/15 text-emerald-300" : "bg-white/10 text-aether-muted"
            }`}
          >
            {health?.enabled ? "enabled" : "disabled"}
          </span>
          <span
            className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
              health?.dryRun ? "bg-sky-500/15 text-sky-300" : "bg-amber-500/15 text-amber-300"
            }`}
          >
            {health?.dryRun ? "shadow mode (dry-run — no email leaves)" : "LIVE sending"}
          </span>
          <span className="text-xs text-aether-muted-dim">
            Last run: {fmtDate(health?.lastRunAt)} · fires every {health?.intervalMinutes ?? 30} min
          </span>
          <button
            type="button"
            onClick={() => void onRunNow()}
            disabled={running}
            className="ml-auto rounded-md bg-aether-indigo px-4 py-2 text-sm font-medium text-white hover:bg-aether-indigo/90 disabled:opacity-50"
          >
            {running ? "Running…" : "Run now"}
          </button>
        </div>
        {health?.detail ? (
          <p className="mt-2 text-xs text-aether-muted-dim">{health.detail}</p>
        ) : null}

        {/* Sending accounts */}
        <div className="mt-3 border-t border-white/10 pt-3">
          <p className="text-xs uppercase tracking-wide text-aether-muted-dim">
            Sending Gmail accounts (the agent polls + sends ONLY from flagged accounts)
          </p>
          {accounts.length === 0 ? (
            <p className="mt-2 text-sm text-aether-muted">
              No Gmail accounts connected for the admin user.
            </p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-2">
              {accounts.map((a) => (
                <li
                  key={a.id}
                  className="flex items-center gap-2 rounded-md border border-white/10 bg-aether-bg px-3 py-2 text-sm"
                >
                  <span className="text-aether-text">{a.accountEmail ?? a.id}</span>
                  {a.isPrimary ? (
                    <span className="text-xs text-aether-muted-dim">(primary)</span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void onToggleAccount(a)}
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      a.usedForSalesAgent
                        ? "bg-emerald-500/15 text-emerald-300"
                        : "bg-white/10 text-aether-muted hover:bg-white/20"
                    }`}
                  >
                    {a.usedForSalesAgent ? "sales sending: ON" : "sales sending: off"}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {health && health.sendingAccounts === 0 ? (
            <p className="mt-2 text-xs text-amber-300">
              No account is flagged — the agent honestly no-ops inbound polling and sending
              until one is enabled above.
            </p>
          ) : null}
        </div>

        {runResult ? (
          <div className="mt-3 rounded-md border border-white/10 bg-aether-bg p-3 text-xs text-aether-muted">
            <p className="font-medium text-aether-text">Last manual run</p>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(runResult, null, 2)}
            </pre>
          </div>
        ) : null}
      </div>

      {/* Overview cards */}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Signups" value={overview ? String(overview.signups) : "…"} />
        <StatCard
          label="Paid conversions"
          value={overview ? String(overview.paidConversions) : "…"}
        />
        <StatCard
          label="MRR (A$)"
          value={overview ? overview.mrrAud.toFixed(2) : "…"}
          note="billingInterval-aware (annual ÷ 12)"
        />
        <StatCard label="Leads" value={overview ? String(overview.leads) : "…"} />
        <StatCard
          label="Reply rate"
          value={
            overview
              ? overview.replyRate === null
                ? "n/a"
                : `${(overview.replyRate * 100).toFixed(1)}%`
              : "…"
          }
          note={
            overview && overview.replyRate === null
              ? "not observable — no real sends yet"
              : undefined
          }
        />
        <StatCard
          label="Suppressed"
          value={overview ? String(overview.suppressionCount) : "…"}
          note="permanent unsubscribe list"
        />
      </div>

      {/* Tabs */}
      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`rounded-md px-4 py-2 text-sm font-medium ${
              tab === t.key
                ? "bg-aether-indigo text-white"
                : "border border-white/10 bg-aether-bg-elevated text-aether-muted hover:text-aether-text"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? <p className="text-sm text-aether-muted">Loading…</p> : null}

      {/* -------------------------------------------------------- campaigns */}
      {tab === "campaigns" && !loading ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-aether-muted-dim">
              Templates use {"{{name}}"} placeholders. The compliance footer (sender identity +
              unsubscribe instruction) is appended server-side on every send — it is not part of
              the editable template and cannot be removed here.
            </p>
            <button
              type="button"
              onClick={() => void onGenerateContent()}
              disabled={generating}
              className="ml-auto rounded-md border border-amber-400/40 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
            >
              {generating ? "Agent writing..." : "Generate content (agent)"}
            </button>
          </div>
          {genResult ? (
            <div className="rounded-md border border-white/10 bg-aether-bg-elevated p-3 text-xs text-aether-muted">
              {genResult.ran ? (
                <>
                  <span className="text-aether-text">
                    Agent run complete (model: {genResult.model ?? "?"}).
                  </span>{" "}
                  Campaigns created: {genResult.campaignsCreated.map((c) => c.name).join(", ") || "none"}
                  {genResult.campaignsSkipped.length > 0
                    ? ` (already existed: ${genResult.campaignsSkipped.join(", ")})`
                    : ""}
                  . LinkedIn drafts queued: {genResult.linkedinDrafts ?? 0}. New campaigns are
                  created INACTIVE — review and activate them here.
                  {genResult.errors.length > 0 ? ` Errors: ${genResult.errors.join("; ")}` : ""}
                </>
              ) : (
                <>Generation did not run: {genResult.reason ?? "unknown reason"}</>
              )}
            </div>
          ) : null}
          {campaigns.map((c) => (
            <div key={c.id} className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
              <div className="flex flex-wrap items-center gap-3">
                <p className="font-medium text-aether-text">{c.name}</p>
                <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-aether-muted">
                  {c.type}
                </span>
                <button
                  type="button"
                  onClick={() => void onToggleCampaign(c)}
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    c.active
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "bg-white/10 text-aether-muted hover:bg-white/20"
                  }`}
                >
                  {c.active ? "active" : "inactive"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(editing === c.id ? null : c.id);
                    setEditBody(c.templateBody);
                  }}
                  className="ml-auto rounded-md border border-white/10 px-3 py-1 text-xs text-aether-muted hover:text-aether-text"
                >
                  {editing === c.id ? "Cancel" : "Edit template"}
                </button>
                <button
                  type="button"
                  disabled={previewLoading}
                  onClick={() => void onPreviewCampaign(c)}
                  className="rounded-md border border-amber-400/40 px-3 py-1 text-xs text-amber-200 hover:bg-amber-500/10 disabled:opacity-50"
                >
                  {previewing === c.id ? "Hide preview" : "Branded preview"}
                </button>
              </div>
              {previewing === c.id && previewHtml ? (
                <div className="mt-3 overflow-hidden rounded-md border border-white/10">
                  <iframe
                    title={`Branded preview — ${c.name}`}
                    srcDoc={previewHtml}
                    sandbox=""
                    className="h-[560px] w-full border-0 bg-black"
                  />
                </div>
              ) : null}
              {editing === c.id ? (
                <div className="mt-3">
                  <textarea
                    value={editBody}
                    onChange={(e) => setEditBody(e.target.value)}
                    rows={10}
                    className="w-full rounded-md border border-white/10 bg-aether-bg p-3 font-mono text-xs text-aether-text"
                  />
                  <button
                    type="button"
                    disabled={saving || !editBody.trim()}
                    onClick={() => void onSaveCampaign(c)}
                    className="mt-2 rounded-md bg-aether-indigo px-4 py-2 text-sm font-medium text-white hover:bg-aether-indigo/90 disabled:opacity-50"
                  >
                    {saving ? "Saving…" : "Save template"}
                  </button>
                </div>
              ) : (
                <pre className="mt-3 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-aether-bg p-3 text-xs text-aether-muted">
                  {c.templateBody}
                </pre>
              )}
            </div>
          ))}
        </div>
      ) : null}

      {/* ------------------------------------------------------------ leads */}
      {tab === "leads" && !loading ? (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="min-w-full text-sm">
            <thead className="bg-aether-bg-elevated text-left text-xs uppercase tracking-wide text-aether-muted-dim">
              <tr>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Consent</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {(leads?.leads ?? []).map((l) => (
                <tr key={l.id} className="hover:bg-white/5">
                  <td className="px-4 py-3 text-aether-text">{l.email}</td>
                  <td className="px-4 py-3 text-aether-muted">{l.name ?? "—"}</td>
                  <td className="px-4 py-3 text-aether-muted">{l.source}</td>
                  <td className="px-4 py-3">
                    <span title={l.consentEvidence} className="text-aether-muted">
                      {l.consentType}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <OutcomeBadge outcome={l.status} />
                  </td>
                  <td className="px-4 py-3 text-aether-muted">{fmtDate(l.createdAt)}</td>
                </tr>
              ))}
              {(leads?.leads ?? []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-aether-muted">
                    No leads yet. Leads are only ever created from ratified consent signals
                    (inbound email, existing accounts) — never from guessed addresses.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}

      {/* --------------------------------------------------------- outreach */}
      {tab === "outreach" && !loading ? (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="min-w-full text-sm">
            <thead className="bg-aether-bg-elevated text-left text-xs uppercase tracking-wide text-aether-muted-dim">
              <tr>
                <th className="px-4 py-3">When</th>
                <th className="px-4 py-3">Channel</th>
                <th className="px-4 py-3">Recipient</th>
                <th className="px-4 py-3">Subject</th>
                <th className="px-4 py-3">Outcome</th>
                <th className="px-4 py-3">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {(outreach?.entries ?? []).map((o) => (
                <tr key={o.id} className="hover:bg-white/5">
                  <td className="px-4 py-3 text-aether-muted">{fmtDate(o.createdAt)}</td>
                  <td className="px-4 py-3 text-aether-muted">{o.channel}</td>
                  <td className="px-4 py-3 text-aether-text">{o.recipient ?? "—"}</td>
                  <td className="px-4 py-3 text-aether-muted" title={o.body ?? undefined}>
                    {o.subject ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <OutcomeBadge outcome={o.outcome} />
                  </td>
                  <td className="px-4 py-3 text-xs text-aether-muted-dim">{o.detail ?? "—"}</td>
                </tr>
              ))}
              {(outreach?.entries ?? []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-aether-muted">
                    No outreach recorded yet. In shadow mode, would-be sends appear here as
                    dry_run rows with the full email body.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}

      {/* --------------------------------------------------------- linkedin */}
      {tab === "linkedin" && !loading ? (
        <div className="space-y-3">
          <p className="text-xs text-aether-muted-dim">
            Drafts only — LinkedIn&apos;s Terms prohibit automated posting, so there is no
            &quot;post&quot; button anywhere. Copy a draft and post it manually.
          </p>
          {(drafts?.entries ?? []).map((d) => (
            <div key={d.id} className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
              <div className="flex items-center gap-3">
                <OutcomeBadge outcome={d.outcome} />
                <span className="text-xs text-aether-muted-dim">{fmtDate(d.createdAt)}</span>
                <button
                  type="button"
                  onClick={() => void copyDraft(d.id, d.body)}
                  className="ml-auto rounded-md border border-white/10 px-3 py-1 text-xs text-aether-muted hover:text-aether-text"
                >
                  {copiedId === d.id ? "Copied ✓" : "Copy draft"}
                </button>
              </div>
              <pre className="mt-3 whitespace-pre-wrap rounded-md bg-aether-bg p-3 text-xs text-aether-muted">
                {d.body ?? d.detail ?? "(no body)"}
              </pre>
            </div>
          ))}
          {(drafts?.entries ?? []).length === 0 ? (
            <p className="rounded-xl border border-white/10 bg-aether-bg-elevated p-6 text-center text-sm text-aether-muted">
              No LinkedIn drafts queued yet — the agent queues at most one per 24 hours when
              the linkedin_draft campaign is active.
            </p>
          ) : null}
        </div>
      ) : null}

      {/* ------------------------------------------------------------ brand */}
      {tab === "brand" && !loading ? (
        <div className="space-y-4">
          <p className="text-xs text-aether-muted-dim">
            Brand-templated admin documents — invoice, auto-reply and Stripe-lifecycle email
            templates — rendered from the same design system as the campaign emails. Prices and
            GST come live from the Plan catalog; customer fields render as explicit{" "}
            {"{{merge_field}}"} tokens, never fabricated sample data.
          </p>

          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs text-aether-muted">
              Plan{" "}
              <select
                value={brandPlan}
                onChange={(e) => {
                  setBrandPlan(e.target.value);
                  if (brandKind) void onPreviewBrandDoc(brandKind, e.target.value, brandInterval);
                }}
                className="ml-1 rounded-md border border-white/10 bg-aether-bg-elevated px-2 py-1 text-xs text-aether-text"
              >
                {(brand?.plans ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — A${p.priceAudMonthly}/mo
                    {p.priceAudAnnual != null ? ` · A$${p.priceAudAnnual}/yr` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-aether-muted">
              Interval{" "}
              <select
                value={brandInterval}
                onChange={(e) => {
                  setBrandInterval(e.target.value);
                  if (brandKind) void onPreviewBrandDoc(brandKind, brandPlan, e.target.value);
                }}
                className="ml-1 rounded-md border border-white/10 bg-aether-bg-elevated px-2 py-1 text-xs text-aether-text"
              >
                <option value="monthly">monthly</option>
                <option value="annual">annual</option>
              </select>
            </label>
          </div>

          {(brand?.documents ?? []).map((d) => (
            <div key={d.kind} className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div>
                  <p className="font-medium text-aether-text">{d.title}</p>
                  <p className="mt-0.5 text-xs text-aether-muted-dim">{d.description}</p>
                </div>
                <button
                  type="button"
                  disabled={brandLoading}
                  onClick={() => void onPreviewBrandDoc(d.kind)}
                  className="ml-auto shrink-0 rounded-md border border-amber-400/40 px-3 py-1 text-xs text-amber-200 hover:bg-amber-500/10 disabled:opacity-50"
                >
                  {brandKind === d.kind ? "Hide preview" : "Preview"}
                </button>
              </div>
              {brandKind === d.kind && brandHtml ? (
                <div className="mt-3 overflow-hidden rounded-md border border-white/10">
                  <iframe
                    title={`Document preview — ${d.title}`}
                    srcDoc={brandHtml}
                    sandbox=""
                    className="h-[620px] w-full border-0 bg-black"
                  />
                </div>
              ) : null}
            </div>
          ))}

          <div className="rounded-xl border border-white/10 bg-aether-bg-elevated p-4">
            <p className="font-medium text-aether-text">Brand assets</p>
            <p className="mt-0.5 text-xs text-aether-muted-dim">
              Static SVG/PNG assets served by the web app — right-click to save, or use the
              path in emails and documents.
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {(brand?.assets ?? []).map((a) => (
                <div key={a.path} className="rounded-md border border-white/10 bg-aether-bg p-3">
                  {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset preview, natural size */}
                  <img
                    src={a.path}
                    alt={a.description}
                    className="h-24 w-full rounded bg-black object-contain"
                  />
                  <p className="mt-2 text-xs font-medium text-aether-text">{a.name}</p>
                  <p className="text-[11px] text-aether-muted-dim">{a.description}</p>
                  <code className="mt-1 block break-all text-[11px] text-aether-muted">{a.path}</code>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
