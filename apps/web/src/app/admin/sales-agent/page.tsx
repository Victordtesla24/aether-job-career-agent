"use client";

/**
 * /admin/sales-agent — the NATIVE Sales AI Agent console.
 *
 * This page replaced the old "external growth engine" placeholder: the sales
 * agent now runs INSIDE this app (30-min systemd timer + admin "Run now"),
 * with its own AdminUser-gated API under /api/admin/sales-agent/*. Everything
 * shown here is a live database query — no estimates, no fabricated metrics;
 * reply rate honestly reads "n/a — reply detection not yet implemented" (CLI-004).
 *
 * Compliance surfaced in the UI: LinkedIn items are DRAFTS ONLY (copy button,
 * never a post button — LinkedIn's Terms prohibit automated posting), the
 * suppression list is permanent, and shadow (dry-run) mode is prominently
 * labelled so the operator always knows whether emails can actually leave.
 */
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
// Aether Career Design System skin — every rule is scoped under
// `.aether-ds-scope`, so ONLY this console is restyled (not the admin shell).
import "./sales-agent.css";
import { describeApiError } from "../../../lib/api/client";
import {
  fetchBrandDocumentPreview,
  fetchBrandDocuments,
  fetchBrandTemplates,
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
  updateBrandTemplate,
  type BrandDocuments,
  type BrandTemplate,
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
    <div className="sa-card-gilt p-4">
      <p className="sa-eyebrow">{label}</p>
      <p className="sa-figure mt-1">{value}</p>
      {note ? <p className="sa-meta mt-1">{note}</p> : null}
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  const o = outcome ?? "unknown";
  // DS state law: ok green / info / warn copper / danger — gold is brand,
  // never a state; sapphire marks agent-drafted work; no-data is neutral.
  // `reserved` is a weekly LinkedIn draft slot claimed before the model was
  // called — a real in-flight state, shown as such and never as a finished
  // draft.
  const variants: Record<string, string> = {
    sent: "sa-badge-ok",
    dry_run: "sa-badge-info",
    reserved: "sa-badge-info",
    draft_queued: "sa-badge-sapphire",
    blocked: "sa-badge-warn",
    unsubscribed: "sa-badge-warn",
    error: "sa-badge-danger",
    bounced: "sa-badge-danger",
  };
  const variant = variants[o] ?? "sa-badge-neutral";
  return <span className={`sa-badge ${variant}`}>{o}</span>;
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
  const [brandTemplates, setBrandTemplates] = useState<BrandTemplate[]>([]);
  const [brandEditing, setBrandEditing] = useState<string | null>(null);
  const [brandDraft, setBrandDraft] = useState<Pick<BrandTemplate, "body" | "footnote" | "footer"> | null>(null);
  const [brandSaving, setBrandSaving] = useState(false);
  const [brandKind, setBrandKind] = useState<string | null>(null);
  const [brandHtml, setBrandHtml] = useState("");
  const [brandLoading, setBrandLoading] = useState(false);
  const [brandPlan, setBrandPlan] = useState("starter");
  const [brandInterval, setBrandInterval] = useState("monthly");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ov, he, ac, ca, le, ou, dr, bd, bt] = await Promise.all([
        fetchSalesOverview(),
        fetchSalesHealth(),
        fetchSalesSendingAccounts(),
        fetchSalesCampaigns(),
        fetchSalesLeads({ limit: 100 }),
        fetchSalesOutreach({ limit: 100 }),
        fetchSalesOutreach({ channel: "linkedin_draft", limit: 50 }),
        fetchBrandDocuments(),
        fetchBrandTemplates(),
      ]);
      setOverview(ov);
      setHealth(he);
      setAccounts(ac);
      setCampaigns(ca);
      setLeads(le);
      setOutreach(ou);
      setDrafts(dr);
      setBrand(bd);
      setBrandTemplates(bt);
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

  const onSaveBrandTemplate = useCallback(async () => {
    if (!brandEditing || !brandDraft) return;
    setBrandSaving(true);
    setError("");
    try {
      await updateBrandTemplate(brandEditing, brandDraft);
      setBrandEditing(null);
      setBrandDraft(null);
      await load();
      await onPreviewBrandDoc(brandEditing, brandPlan, brandInterval);
    } catch (err) {
      setError(describeApiError(err, "Could not save the brand template."));
    } finally {
      setBrandSaving(false);
    }
  }, [brandDraft, brandEditing, brandInterval, brandPlan, load, onPreviewBrandDoc]);

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
    <div className="aether-ds-scope">
      <div className="sa-header">
        <AdminPageHeader
          title="Sales Agent"
          subtitle="Native in-app growth agent — inbound leads, lifecycle emails, LinkedIn drafts. Every number below is a live database query."
        />
      </div>

      {error ? (
        <p className="mb-3 text-sm" style={{ color: "var(--state-danger)" }}>
          {error}
        </p>
      ) : null}

      {healthAlarm ? (
        <div className="sa-alarm mb-4 p-4 text-sm">
          <p className="font-semibold">Sales agent scheduler alarm</p>
          <p className="mt-1">{health?.detail}</p>
        </div>
      ) : null}

      {/* Health / control strip */}
      <div className="sa-card mb-5 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`sa-badge ${health?.status === "ok"
                ? "sa-badge-ok"
                : healthAlarm
                  ? "sa-badge-danger"
                  : "sa-badge-neutral"
              }`}
          >
            {health ? `scheduler: ${health.status}` : "scheduler: …"}
          </span>
          <span className={`sa-badge ${health?.enabled ? "sa-badge-ok" : "sa-badge-neutral"}`}>
            {health?.enabled ? "enabled" : "disabled"}
          </span>
          <span className={`sa-badge ${health?.dryRun ? "sa-badge-info" : "sa-badge-warn"}`}>
            {health?.dryRun ? "shadow mode (dry-run — no email leaves)" : "LIVE sending"}
          </span>
          <span className="sa-meta">
            Last run: {fmtDate(health?.lastRunAt)} · fires every {health?.intervalMinutes ?? 30} min
          </span>
          <button
            type="button"
            onClick={() => void onRunNow()}
            disabled={running}
            className="sa-btn-primary ml-auto px-4 py-2 text-sm"
          >
            {running ? "Running…" : "Run now"}
          </button>
        </div>
        {health?.detail ? <p className="sa-meta mt-2">{health.detail}</p> : null}

        {/* Sending accounts */}
        <div className="sa-hairline-top mt-3 pt-3">
          <p className="sa-eyebrow">
            Sending Gmail accounts (the agent polls + sends ONLY from flagged accounts)
          </p>
          {accounts.length === 0 ? (
            <p className="mt-2 text-sm" style={{ color: "var(--fg-2)" }}>
              No Gmail accounts connected for the admin user.
            </p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-2">
              {accounts.map((a) => (
                <li key={a.id} className="sa-well flex items-center gap-2 px-3 py-2 text-sm">
                  <span style={{ color: "var(--fg-1)" }}>{a.accountEmail ?? a.id}</span>
                  {a.isPrimary ? <span className="sa-meta">(primary)</span> : null}
                  <button
                    type="button"
                    onClick={() => void onToggleAccount(a)}
                    className={`sa-badge ${a.usedForSalesAgent ? "sa-badge-ok" : "sa-badge-neutral"
                      }`}
                  >
                    {a.usedForSalesAgent ? "sales sending: ON" : "sales sending: off"}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {health && health.sendingAccounts === 0 ? (
            <p className="mt-2 text-xs" style={{ color: "var(--state-warn)" }}>
              No account is flagged — the agent honestly no-ops inbound polling and sending
              until one is enabled above.
            </p>
          ) : null}
        </div>

        {runResult ? (
          <div className="sa-well mt-3 p-3 text-xs" style={{ color: "var(--fg-2)" }}>
            <p className="font-medium" style={{ color: "var(--fg-1)" }}>
              Last manual run
            </p>
            {runResult.explanation ? (
              <p className="mt-1" style={{ color: "var(--fg-1)" }}>
                {runResult.explanation}
              </p>
            ) : null}
            {runResult.linkedinCadence?.reason ? (
              <p className="mt-1">LinkedIn drafts: {runResult.linkedinCadence.reason}.</p>
            ) : null}
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
              ? "reply detection not yet implemented"
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
            className={`px-4 py-2 text-sm ${tab === t.key ? "sa-tab-active" : "sa-tab"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-sm" style={{ color: "var(--fg-2)" }}>
          Loading…
        </p>
      ) : null}

      {/* -------------------------------------------------------- campaigns */}
      {tab === "campaigns" && !loading ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <p className="sa-meta">
              Templates use {"{{name}}"} placeholders. The compliance footer (sender identity +
              unsubscribe instruction) is appended server-side on every send — it is not part of
              the editable template and cannot be removed here.
            </p>
            <button
              type="button"
              onClick={() => void onGenerateContent()}
              disabled={generating}
              className="sa-btn-sapphire ml-auto px-4 py-2 text-sm font-medium"
            >
              {generating ? "Agent writing..." : "Generate content (agent)"}
            </button>
          </div>
          {genResult ? (
            <div className="sa-card p-3 text-xs" style={{ color: "var(--fg-2)" }}>
              {genResult.ran ? (
                <>
                  <span style={{ color: "var(--fg-1)" }}>
                    Agent run complete (model: {genResult.model ?? "?"}).
                  </span>{" "}
                  Campaigns created: {genResult.campaignsCreated.map((c) => c.name).join(", ") || "none"}
                  {genResult.campaignsSkipped.length > 0
                    ? ` (already existed: ${genResult.campaignsSkipped.join(", ")})`
                    : ""}
                  . Promos authored:{" "}
                  {genResult.promosCreated.map((p) => p.code).join(", ") ||
                    (genResult.promosSkipped.length > 0
                      ? `none (already in Stripe: ${genResult.promosSkipped.join(", ")})`
                      : "none")}
                  . LinkedIn drafts queued: {genResult.linkedinDrafts ?? 0}. New campaigns and
                  promos are created INACTIVE — review and activate them.
                  {genResult.errors.length > 0 ? ` Errors: ${genResult.errors.join("; ")}` : ""}
                </>
              ) : (
                <>Generation did not run: {genResult.reason ?? "unknown reason"}</>
              )}
            </div>
          ) : null}
          {campaigns.map((c) => (
            <div key={c.id} className="sa-card p-4">
              <div className="flex flex-wrap items-center gap-3">
                <p className="sa-card-title">{c.name}</p>
                <span className="sa-badge sa-badge-neutral">{c.type}</span>
                <button
                  type="button"
                  onClick={() => void onToggleCampaign(c)}
                  className={`sa-badge ${c.active ? "sa-badge-ok" : "sa-badge-neutral"}`}
                >
                  {c.active ? "active" : "inactive"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(editing === c.id ? null : c.id);
                    setEditBody(c.templateBody);
                  }}
                  className="sa-btn-ghost ml-auto px-3 py-1 text-xs"
                >
                  {editing === c.id ? "Cancel" : "Edit template"}
                </button>
                <button
                  type="button"
                  disabled={previewLoading}
                  onClick={() => void onPreviewCampaign(c)}
                  className="sa-btn-gilt px-3 py-1 text-xs"
                >
                  {previewing === c.id ? "Hide preview" : "Branded preview"}
                </button>
              </div>
              {previewing === c.id && previewHtml ? (
                <div
                  className="mt-3 overflow-hidden"
                  style={{
                    borderRadius: "var(--radius-lg)",
                    border: "1px solid var(--gold-border)",
                  }}
                >
                  <iframe
                    title={`Branded preview — ${c.name}`}
                    srcDoc={previewHtml}
                    sandbox=""
                    className="h-[560px] w-full border-0"
                    style={{ background: "var(--ink-0)" }}
                  />
                </div>
              ) : null}
              {editing === c.id ? (
                <div className="mt-3">
                  <textarea
                    value={editBody}
                    onChange={(e) => setEditBody(e.target.value)}
                    rows={10}
                    className="w-full p-3 text-xs"
                  />
                  <button
                    type="button"
                    disabled={saving || !editBody.trim()}
                    onClick={() => void onSaveCampaign(c)}
                    className="sa-btn-primary mt-2 px-4 py-2 text-sm"
                  >
                    {saving ? "Saving…" : "Save template"}
                  </button>
                </div>
              ) : (
                <pre
                  className="sa-well mt-3 max-h-48 overflow-y-auto whitespace-pre-wrap p-3 text-xs"
                  style={{ color: "var(--fg-2)" }}
                >
                  {c.templateBody}
                </pre>
              )}
            </div>
          ))}
        </div>
      ) : null}

      {/* ------------------------------------------------------------ leads */}
      {tab === "leads" && !loading ? (
        <div className="sa-table-wrap">
          <table className="sa-table min-w-full text-sm">
            <thead>
              <tr>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Consent</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {(leads?.leads ?? []).map((l) => (
                <tr key={l.id}>
                  <td className="px-4 py-3" style={{ color: "var(--fg-1)" }}>{l.email}</td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-2)" }}>{l.name ?? "—"}</td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-2)" }}>{l.source}</td>
                  <td className="px-4 py-3">
                    <span title={l.consentEvidence} style={{ color: "var(--fg-2)" }}>
                      {l.consentType}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <OutcomeBadge outcome={l.status} />
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-2)" }}>
                    {fmtDate(l.createdAt)}
                  </td>
                </tr>
              ))}
              {(leads?.leads ?? []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center" style={{ color: "var(--fg-2)" }}>
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
        <div className="sa-table-wrap">
          <table className="sa-table min-w-full text-sm">
            <thead>
              <tr>
                <th className="px-4 py-3">When</th>
                <th className="px-4 py-3">Channel</th>
                <th className="px-4 py-3">Recipient</th>
                <th className="px-4 py-3">Subject</th>
                <th className="px-4 py-3">Outcome</th>
                <th className="px-4 py-3">Detail</th>
              </tr>
            </thead>
            <tbody>
              {(outreach?.entries ?? []).map((o) => (
                <tr key={o.id}>
                  <td className="px-4 py-3" style={{ color: "var(--fg-2)" }}>
                    {fmtDate(o.createdAt)}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-2)" }}>{o.channel}</td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-1)" }}>
                    {o.recipient ?? "—"}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--fg-2)" }} title={o.body ?? undefined}>
                    {o.subject ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <OutcomeBadge outcome={o.outcome} />
                  </td>
                  <td className="sa-meta px-4 py-3">{o.detail ?? "—"}</td>
                </tr>
              ))}
              {(outreach?.entries ?? []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center" style={{ color: "var(--fg-2)" }}>
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
          <p className="sa-meta">
            Drafts only — LinkedIn&apos;s Terms prohibit automated posting, so there is no
            &quot;post&quot; button anywhere. Copy a draft and post it manually.
          </p>
          {(drafts?.entries ?? []).map((d) => (
            <div key={d.id} className="sa-card p-4">
              <div className="flex items-center gap-3">
                <OutcomeBadge outcome={d.outcome} />
                <span className="sa-meta">{fmtDate(d.createdAt)}</span>
                <button
                  type="button"
                  onClick={() => void copyDraft(d.id, d.body)}
                  className="sa-btn-ghost ml-auto px-3 py-1 text-xs"
                >
                  {copiedId === d.id ? "Copied ✓" : "Copy draft"}
                </button>
              </div>
              <pre
                className="sa-well mt-3 whitespace-pre-wrap p-3 text-xs"
                style={{ color: "var(--fg-2)" }}
              >
                {d.body ?? d.detail ?? "(no body)"}
              </pre>
            </div>
          ))}
          {(drafts?.entries ?? []).length === 0 ? (
            <p className="sa-card p-6 text-center text-sm" style={{ color: "var(--fg-2)" }}>
              No LinkedIn drafts queued yet — the agent queues at most one per 24 hours when
              the linkedin_draft campaign is active.
            </p>
          ) : null}
        </div>
      ) : null}

      {/* ------------------------------------------------------------ brand */}
      {tab === "brand" && !loading ? (
        <div className="space-y-4">
          <p className="sa-meta">
            Brand-templated artefacts — the single catalogue for every
            Aether-owned email, invoice, document and business card. Preview
            HTML is the same renderer the live send path uses (obsidian and
            gilt). Transactional mail (welcome, reset, Stripe lifecycle,
            founder digest, notification digest, inbound auto-reply, operator
            systemd alert) is bulletproof (no images). Sales outreach and the
            print invoice include the brand mark. Prices and GST come live
            from the Plan catalog; customer fields render as explicit
            {"{{merge_field}}"} tokens, never fabricated sample data.
            Candidate mail to an employer stays unbranded on purpose.
          </p>

          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs" style={{ color: "var(--fg-2)" }}>
              Plan{" "}
              <select
                value={brandPlan}
                onChange={(e) => {
                  setBrandPlan(e.target.value);
                  if (brandKind) void onPreviewBrandDoc(brandKind, e.target.value, brandInterval);
                }}
                className="ml-1 px-2 py-1 text-xs"
              >
                {(brand?.plans ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — A${p.priceAudMonthly}/mo
                    {p.priceAudAnnual != null ? ` · A$${p.priceAudAnnual}/yr` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs" style={{ color: "var(--fg-2)" }}>
              Interval{" "}
              <select
                value={brandInterval}
                onChange={(e) => {
                  setBrandInterval(e.target.value);
                  if (brandKind) void onPreviewBrandDoc(brandKind, brandPlan, e.target.value);
                }}
                className="ml-1 px-2 py-1 text-xs"
              >
                <option value="monthly">monthly</option>
                <option value="annual">annual</option>
              </select>
            </label>
          </div>

          {(brand?.documents ?? []).map((d) => (
            <div key={d.kind} className="sa-card p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div>
                  <p className="sa-card-title">{d.title}</p>
                  <p className="sa-meta mt-0.5">{d.description}</p>
                </div>
                <div className="ml-auto flex shrink-0 gap-2">
                  {d.kind === "auto_reply" ? (
                    <button
                      type="button"
                      onClick={() => {
                        const template = brandTemplates.find((t) => t.kind === d.kind);
                        if (!template) return;
                        setBrandEditing(brandEditing === d.kind ? null : d.kind);
                        setBrandDraft({ body: template.body, footnote: template.footnote, footer: template.footer });
                      }}
                      className="sa-btn-ghost px-3 py-1 text-xs"
                    >
                      {brandEditing === d.kind ? "Cancel edit" : "Edit copy & footer"}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    disabled={brandLoading}
                    onClick={() => void onPreviewBrandDoc(d.kind)}
                    className="sa-btn-gilt px-3 py-1 text-xs"
                  >
                    {brandKind === d.kind ? "Hide preview" : "Preview"}
                  </button>
                </div>
              </div>
              {brandEditing === d.kind && brandDraft ? (
                <div className="mt-3 space-y-3 sa-well p-3">
                  <p className="text-xs" style={{ color: "var(--fg-2)" }}>
                    Compliance footer is enforced server-side: it must retain the product identity and an absolute HTTPS unsubscribe URL.
                  </p>
                  <label className="block text-xs" style={{ color: "var(--fg-2)" }}>
                    Template copy
                    <textarea value={brandDraft.body} onChange={(e) => setBrandDraft({ ...brandDraft, body: e.target.value })} rows={6} className="mt-1 w-full p-2 text-xs" />
                  </label>
                  <label className="block text-xs" style={{ color: "var(--fg-2)" }}>
                    Footnote
                    <textarea value={brandDraft.footnote} onChange={(e) => setBrandDraft({ ...brandDraft, footnote: e.target.value })} rows={3} className="mt-1 w-full p-2 text-xs" />
                  </label>
                  <label className="block text-xs" style={{ color: "var(--fg-2)" }}>
                    Compliance footer
                    <textarea value={brandDraft.footer} onChange={(e) => setBrandDraft({ ...brandDraft, footer: e.target.value })} rows={3} className="mt-1 w-full p-2 text-xs" />
                  </label>
                  <button type="button" disabled={brandSaving || !brandDraft.body.trim() || !brandDraft.footnote.trim() || !brandDraft.footer.trim()} onClick={() => void onSaveBrandTemplate()} className="sa-btn-primary px-4 py-2 text-sm">
                    {brandSaving ? "Saving…" : "Save template"}
                  </button>
                </div>
              ) : null}
              {brandKind === d.kind && brandHtml ? (
                <div
                  className="mt-3 overflow-hidden"
                  style={{
                    borderRadius: "var(--radius-lg)",
                    border: "1px solid var(--gold-border)",
                  }}
                >
                  <iframe
                    title={`Document preview — ${d.title}`}
                    srcDoc={brandHtml}
                    sandbox=""
                    className="h-[620px] w-full border-0"
                    style={{ background: "var(--ink-0)" }}
                  />
                </div>
              ) : null}
            </div>
          ))}

          <div className="sa-card p-4">
            <p className="sa-card-title">Brand assets</p>
            <p className="sa-meta mt-0.5">
              Static SVG/PNG assets served by the web app — right-click to save, or use the
              path in emails and documents.
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {(brand?.assets ?? []).map((a) => (
                <div key={a.path} className="sa-well p-3">
                  {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset preview, natural size */}
                  <img
                    src={a.path}
                    alt={a.description}
                    className="h-24 w-full object-contain"
                    style={{ background: "var(--ink-0)", borderRadius: "var(--radius-md)" }}
                  />
                  <p className="mt-2 text-xs font-medium" style={{ color: "var(--fg-1)" }}>
                    {a.name}
                  </p>
                  <p className="sa-meta">{a.description}</p>
                  <code className="sa-meta mt-1 block break-all">{a.path}</code>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
