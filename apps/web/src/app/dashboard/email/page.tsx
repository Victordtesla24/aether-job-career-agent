"use client";

/**
 * Email Command Center — smart inbox, AI intelligence panel, drafted replies
 * with a two-step send confirmation gate, follow-up automation and weekly
 * stats. Backed by GET /emails/inbox + POST /emails/send
 * (wireframe: email-center.html).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createEmailDraft,
  emailIntelligenceView,
  emailScoreBadge,
  emailSendErrorMessage,
  fetchEmailInbox,
  linkedInSearchUrl,
  parseEmailDraft,
  parseEmailDraftFlags,
  parseEmailInsights,
  sendEmailReply,
  type EmailInbox,
  type EmailIntelligence,
  type EmailMessage,
} from "../../../lib/api/workspaces";
import { runAgent } from "../../../lib/api/agents";
import { connectGmail, gmailConnectResultFromParams } from "../../../lib/api/google";
import { connectAnotherGmail, disconnectAccount, setPrimaryAccount } from "../../../lib/api/emails";

const CATEGORIES = [
  { key: "priority", label: "Priority" },
  { key: "all", label: "All Recruiter" },
  { key: "followup", label: "Follow-Up Due" },
  { key: "auto", label: "Auto-Replied" },
  { key: "trashed", label: "Trashed" },
] as const;

// Score badge colour. `null` (never-triaged thread) is a neutral, muted
// placeholder — NOT the red "low score" style — so a not-yet-analyzed thread
// never masquerades as a real low verdict (MV-email-center-001).
function scoreColor(score: number | null) {
  if (typeof score !== "number") return "text-aether-muted-dim border-white/15";
  if (score >= 75) return "text-aether-green border-aether-green/40";
  if (score >= 50) return "text-aether-amber border-aether-amber/40";
  return "text-red-300 border-red-500/40";
}

export default function EmailCenterPage() {
  const [inbox, setInbox] = useState<EmailInbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Default to "All Recruiter": it always has content, so the screen never opens
  // on a structurally-empty tab that reads as broken (MV-email-center-003).
  const [category, setCategory] = useState<string>("all");
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<string>("");
  const [gateOpen, setGateOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [sentNotice, setSentNotice] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [connectNotice, setConnectNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [accountBusy, setAccountBusy] = useState<string | null>(null);

  // On-demand AI (MV-email-center-001/002): the emailAgent is invoked per thread
  // only when the user asks, so the inbox load never fans out to 64 LLM calls.
  // Computed insights + drafts are cached per thread id.
  const [computedIntel, setComputedIntel] = useState<Record<string, EmailIntelligence>>({});
  const [intelBusy, setIntelBusy] = useState(false);
  const [intelError, setIntelError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [draftFlags, setDraftFlags] = useState<Record<string, string[]>>({});
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [triageBusy, setTriageBusy] = useState(false);
  const [triageNotice, setTriageNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);

  // Compose modal state
  const [composeOpen, setComposeOpen] = useState(false);
  const [composeTo, setComposeTo] = useState("");
  const [composeSubject, setComposeSubject] = useState("");
  const [composeBody, setComposeBody] = useState("");
  const [composeSaving, setComposeSaving] = useState(false);
  const [composeError, setComposeError] = useState<string | null>(null);

  useEffect(() => {
    fetchEmailInbox()
      .then((data) => {
        setInbox(data);
        const first = data.messages[0];
        if (first) {
          setSelectedId(first.id);
          setDraft("");
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load inbox"));
  }, []);

  // Handle the Google OAuth callback landing (…/email?gmail_connected=1|0).
  // Read the query string directly (no useSearchParams → no Suspense boundary
  // required), show an honest banner, refetch the now-synced inbox on success,
  // then strip the params so a refresh doesn't re-show the notice.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const result = gmailConnectResultFromParams(new URLSearchParams(window.location.search));
    if (!result) return;
    if (result.kind === "success") {
      setConnectNotice({ kind: "success", message: "Gmail connected ✓ — syncing your inbox…" });
      fetchEmailInbox()
        .then((data) => setInbox(data))
        .catch(() => {});
    } else {
      setConnectNotice({ kind: "error", message: result.message });
    }
    window.history.replaceState(null, "", "/dashboard/email");
  }, []);

  const startConnect = useCallback(() => {
    setConnecting(true);
    setConnectNotice(null);
    void connectGmail().catch((e: unknown) => {
      setConnecting(false);
      setConnectNotice({
        kind: "error",
        message: e instanceof Error ? e.message : "Could not start Gmail sign-in.",
      });
    });
  }, []);

  // Add ANOTHER Gmail inbox (Google always shows the account chooser, so this
  // never overwrites an already-connected account — GAP-D2).
  const addAccount = useCallback(() => {
    setConnecting(true);
    setConnectNotice(null);
    void connectAnotherGmail().catch((e: unknown) => {
      setConnecting(false);
      setConnectNotice({
        kind: "error",
        message: e instanceof Error ? e.message : "Could not start Gmail sign-in.",
      });
    });
  }, []);

  const refreshInbox = useCallback(() => {
    fetchEmailInbox()
      .then((data) => setInbox(data))
      .catch(() => {});
  }, []);

  // Run the REAL emailAgent triage over the inbox (one batch LLM call) so the
  // list scores + Priority/Follow-Up/Auto tabs populate. User-initiated — never
  // auto-fired on load (MV-email-center-001/003).
  const runTriage = useCallback(async () => {
    setTriageBusy(true);
    setTriageNotice(null);
    try {
      const res = await runAgent("email", { mode: "triage" });
      const triaged = typeof res.triaged === "number" ? res.triaged : 0;
      const data = await fetchEmailInbox();
      setInbox(data);
      setTriageNotice({
        kind: "success",
        message:
          triaged > 0
            ? `Triaged ${triaged} thread${triaged === 1 ? "" : "s"} — scores and tabs updated.`
            : "No threads to triage yet.",
      });
    } catch (e) {
      setTriageNotice({
        kind: "error",
        message: e instanceof Error ? e.message : "Could not run AI triage.",
      });
    } finally {
      setTriageBusy(false);
    }
  }, []);

  // Compute the REAL AI-intelligence view for ONE thread on demand.
  const analyzeThread = useCallback(async (threadId: string) => {
    setIntelBusy(true);
    setIntelError(null);
    try {
      const res = await runAgent("email", { mode: "insights", thread_id: threadId });
      const intel = parseEmailInsights(res);
      if (!intel) {
        setIntelError("The AI returned no usable score for this thread — please try again.");
        return;
      }
      setComputedIntel((prev) => ({ ...prev, [threadId]: intel }));
    } catch (e) {
      setIntelError(e instanceof Error ? e.message : "Could not analyze this thread.");
    } finally {
      setIntelBusy(false);
    }
  }, []);

  // Generate a REAL fabrication-guarded draft reply for ONE thread on demand,
  // then the existing send-gate becomes reachable (MV-email-center-002).
  const generateDraft = useCallback(async (threadId: string) => {
    setDraftBusy(true);
    setDraftError(null);
    try {
      const res = await runAgent("email", { mode: "draft_reply", thread_id: threadId });
      const text = parseEmailDraft(res);
      if (!text) {
        setDraftError("The AI returned an empty draft — please try again.");
        return;
      }
      setDrafts((prev) => ({ ...prev, [threadId]: text }));
      setDraftFlags((prev) => ({ ...prev, [threadId]: parseEmailDraftFlags(res) }));
      setDraft(text);
    } catch (e) {
      setDraftError(e instanceof Error ? e.message : "Could not generate a draft reply.");
    } finally {
      setDraftBusy(false);
    }
  }, []);

  const makePrimary = useCallback(
    async (id: string) => {
      setAccountBusy(id);
      setConnectNotice(null);
      try {
        await setPrimaryAccount(id);
        refreshInbox();
      } catch (e) {
        setConnectNotice({
          kind: "error",
          message: e instanceof Error ? e.message : "Could not set primary inbox.",
        });
      } finally {
        setAccountBusy(null);
      }
    },
    [refreshInbox],
  );

  const removeAccount = useCallback(
    async (id: string, email: string) => {
      setAccountBusy(id);
      setConnectNotice(null);
      try {
        await disconnectAccount(id);
        setAccountFilter((prev) => (prev === email ? "all" : prev));
        refreshInbox();
        setConnectNotice({ kind: "success", message: `Disconnected ${email}.` });
      } catch (e) {
        setConnectNotice({
          kind: "error",
          message: e instanceof Error ? e.message : "Could not disconnect this inbox.",
        });
      } finally {
        setAccountBusy(null);
      }
    },
    [refreshInbox],
  );

  const selected: EmailMessage | undefined = useMemo(
    () => inbox?.messages.find((m) => m.id === selectedId),
    [inbox, selectedId],
  );

  // AI-intelligence view — reconciles the on-demand computed intelligence for the
  // selected thread with the inbox value (always null on load). The null-guard in
  // emailIntelligenceView keeps this crash-free before any analysis runs.
  const intelligence = useMemo(
    () =>
      selected
        ? emailIntelligenceView({
            intelligence: computedIntel[selected.id] ?? selected.intelligence,
          })
        : ({ available: false } as const),
    [selected, computedIntel],
  );

  const connected = useMemo(
    () => (inbox?.accounts ?? []).some((a) => a.status === "connected"),
    [inbox],
  );

  // Whether ANY thread has a real triage score yet — drives honest per-tab empty
  // copy ("Run AI Triage…" vs "No emails…").
  const anyTriaged = useMemo(
    () => (inbox?.messages ?? []).some((m) => m.score !== null),
    [inbox],
  );

  // Honest per-sender LinkedIn *search* link (MV-email-center-007) — null when we
  // have no real name, so the link is omitted rather than pointing at a generic
  // linkedin.com/.
  const senderLinkedIn = useMemo(
    () => (selected ? linkedInSearchUrl(selected.from, selected.company) : null),
    [selected],
  );

  const visibleMessages = useMemo(() => {
    if (!inbox) return [];
    return inbox.messages.filter((m) => {
      const inCategory = category === "all" ? m.category !== "trashed" : m.category === category;
      const inAccount = accountFilter === "all" || m.account === accountFilter;
      return inCategory && inAccount;
    });
  }, [inbox, category, accountFilter]);

  const selectMessage = (m: EmailMessage) => {
    setSelectedId(m.id);
    setDraft(drafts[m.id] ?? "");
    setSentNotice(null);
    setSendError(null);
    setIntelError(null);
    setDraftError(null);
  };

  const closeGate = useCallback(() => setGateOpen(false), []);

  // Escape closes the send gate (wireframe behaviour).
  useEffect(() => {
    if (!gateOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeGate();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [gateOpen, closeGate]);

  // Escape closes the compose modal.
  useEffect(() => {
    if (!composeOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setComposeOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [composeOpen]);

  const openCompose = useCallback(() => {
    setComposeTo("");
    setComposeSubject("");
    setComposeBody("");
    setComposeError(null);
    setComposeOpen(true);
  }, []);

  const saveDraft = useCallback(async () => {
    if (!composeSubject.trim() || !composeBody.trim()) return;
    setComposeSaving(true);
    setComposeError(null);
    try {
      const bodyWithTo = composeTo.trim()
        ? `To: ${composeTo.trim()}\n\n${composeBody}`
        : composeBody;
      await createEmailDraft({
        subject: composeSubject.trim(),
        body: bodyWithTo,
      });
      setComposeOpen(false);
    } catch (e) {
      setComposeError(e instanceof Error ? e.message : "Failed to save draft");
    } finally {
      setComposeSaving(false);
    }
  }, [composeSubject, composeBody, composeTo]);

  const confirmSend = async () => {
    if (!selected) return;
    setSending(true);
    setSendError(null);
    try {
      await sendEmailReply(selected.id, draft);
      setSentNotice(`Reply to ${selected.from} sent ✓ — logged to the communication trail.`);
      setGateOpen(false);
    } catch (e) {
      // Honest failure surface (GAP-P4-042 / ADR D-0029): no provider is
      // connected, so the send is rejected and the user is told plainly —
      // never a silent swallow or a fabricated "sent" toast.
      setSentNotice(null);
      setSendError(emailSendErrorMessage(e));
      setGateOpen(false);
    } finally {
      setSending(false);
    }
  };

  if (error && inbox === null) {
    return <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>;
  }

  if (inbox === null) {
    return (
      <div className="grid gap-4 xl:grid-cols-3" aria-busy="true" data-testid="email-skeleton">
        {[0, 1, 2].map((i) => (
          <div key={i} className="glass h-96 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-5" data-testid="email-center">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Email Command Center</h1>
          <p className="text-sm text-aether-muted">
            Every outbound reply passes the send confirmation gate — nothing leaves without you.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-2 rounded-lg border border-aether-green/30 bg-aether-green/10 px-3 py-1.5 text-xs text-aether-green">
            <span className="h-1.5 w-1.5 rounded-full bg-aether-green live-dot" />
            Monitoring Active
          </span>
          <button
            type="button"
            data-testid="run-triage-btn"
            onClick={() => void runTriage()}
            disabled={triageBusy}
            title="Score and sort your inbox with the AI email agent"
            className="rounded-xl border border-aether-violet/40 bg-aether-violet/10 px-4 py-2 text-sm font-semibold text-aether-violet hover:bg-aether-violet/20 disabled:opacity-50"
          >
            <i className="fa-solid fa-wand-magic-sparkles mr-2" aria-hidden="true" />
            {triageBusy ? "Triaging…" : "Run AI Triage"}
          </button>
          <button
            type="button"
            onClick={openCompose}
            className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <i className="fa-solid fa-pen mr-2" aria-hidden="true" />
            Compose
          </button>
        </div>
      </header>

      {/* Inboxes — one entry per connected Gmail account, plus a unified view */}
      <div className="glass rounded-2xl border border-white/10 p-3" data-testid="email-accounts">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-xs uppercase tracking-wide text-aether-muted-dim">Inboxes</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="inbox-all"
            onClick={() => setAccountFilter("all")}
            className={`rounded-lg border px-3 py-1.5 text-xs transition ${
              accountFilter === "all" ? "border-aether-coral/50 text-white" : "border-white/10 text-aether-muted"
            }`}
          >
            All Inboxes
          </button>

          {inbox.accounts
            .filter((a) => a.status === "connected")
            .map((a) => (
              <div
                key={a.id ?? a.email}
                data-testid="inbox-account"
                className={`flex min-w-0 max-w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs transition ${
                  accountFilter === a.email ? "border-aether-coral/50 text-white" : "border-white/10 text-aether-muted"
                }`}
              >
                <button
                  type="button"
                  onClick={() => setAccountFilter(a.email)}
                  className="flex min-w-0 items-center gap-2"
                >
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-aether-green" />
                  <span className="min-w-0 truncate">{a.email}</span>
                  {a.isPrimary ? (
                    <span className="rounded border border-aether-violet/30 bg-aether-violet/10 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-aether-violet">
                      Primary
                    </span>
                  ) : null}
                  <span className="mono text-[10px] text-aether-muted-dim">{a.unread} unread</span>
                </button>
                {a.id ? (
                  <span className="flex items-center gap-1">
                    {!a.isPrimary ? (
                      <button
                        type="button"
                        data-testid="inbox-set-primary"
                        onClick={() => void makePrimary(a.id as string)}
                        disabled={accountBusy === a.id}
                        title="Make primary inbox"
                        className="text-[10px] text-aether-muted-dim hover:text-white disabled:opacity-50"
                      >
                        Set primary
                      </button>
                    ) : null}
                    <button
                      type="button"
                      data-testid="inbox-disconnect"
                      onClick={() => void removeAccount(a.id as string, a.email)}
                      disabled={accountBusy === a.id}
                      title="Disconnect this inbox"
                      className="text-[10px] text-red-300/80 hover:text-red-300 disabled:opacity-50"
                    >
                      <i className="fa-solid fa-xmark" aria-hidden="true" />
                    </button>
                  </span>
                ) : null}
              </div>
            ))}

          <button
            type="button"
            data-testid="connect-gmail-btn"
            onClick={inbox.accounts.some((a) => a.status === "connected") ? addAccount : startConnect}
            disabled={connecting}
            className="rounded-lg border border-dashed border-white/15 px-3 py-1.5 text-xs text-aether-muted-dim hover:text-white disabled:opacity-50"
          >
            <i className="fa-brands fa-google mr-1.5" aria-hidden="true" />
            {connecting
              ? "Opening Google…"
              : inbox.accounts.some((a) => a.status === "connected")
                ? "Add Gmail Account"
                : "Connect Gmail"}
          </button>
        </div>
      </div>

      {connectNotice ? (
        <p
          data-testid="gmail-connect-notice"
          role={connectNotice.kind === "error" ? "alert" : "status"}
          className={`rounded-xl border p-3 text-sm ${
            connectNotice.kind === "error"
              ? "border-red-500/30 bg-red-500/10 text-red-300"
              : "border-aether-green/30 bg-aether-green/10 text-aether-green"
          }`}
        >
          {connectNotice.message}
        </p>
      ) : null}

      {triageNotice ? (
        <p
          data-testid="triage-notice"
          role={triageNotice.kind === "error" ? "alert" : "status"}
          className={`rounded-xl border p-3 text-sm ${
            triageNotice.kind === "error"
              ? "border-red-500/30 bg-red-500/10 text-red-300"
              : "border-aether-violet/30 bg-aether-violet/10 text-aether-violet"
          }`}
        >
          {triageNotice.message}
        </p>
      ) : null}

      {sentNotice ? (
        <p
          data-testid="email-sent-notice"
          role="status"
          className="rounded-xl border border-aether-green/30 bg-aether-green/10 p-3 text-sm text-aether-green"
        >
          {sentNotice}
        </p>
      ) : null}

      {sendError ? (
        <p
          data-testid="email-send-error"
          role="alert"
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
        >
          {sendError}
        </p>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-4">
        {/* Smart Inbox */}
        <section className="glass min-w-0 rounded-2xl border border-white/10 p-4 xl:col-span-1" data-testid="smart-inbox">
          <h2 className="mb-3 text-[15px] font-semibold">Smart Inbox</h2>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {CATEGORIES.map((c) => (
              <button
                key={c.key}
                type="button"
                data-testid={`inbox-tab-${c.key}`}
                onClick={() => setCategory(c.key)}
                aria-pressed={category === c.key}
                className={`rounded-md px-2 py-1 text-[11px] font-medium transition ${
                  category === c.key ? "bg-aether-coral text-white" : "bg-white/5 text-aether-muted hover:text-white"
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div className="max-h-[70vh] space-y-2 overflow-y-auto pr-1" data-testid="inbox-list">
            {visibleMessages.length === 0 ? (
              <p className="py-6 text-center text-xs text-aether-muted-dim" data-testid="inbox-empty">
                {category === "trashed"
                  ? "Trash is empty."
                  : !anyTriaged && category !== "all"
                    ? "Run AI Triage to sort your inbox into this tab."
                    : "No emails in this view."}
              </p>
            ) : (
              visibleMessages.map((m) => {
                const badge = emailScoreBadge(m.score);
                return (
                <button
                  key={m.id}
                  type="button"
                  data-testid="email-card"
                  onClick={() => selectMessage(m)}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    selectedId === m.id
                      ? "border-aether-coral/50 bg-aether-coral/5"
                      : "border-white/10 bg-white/5 hover:border-white/20"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-semibold">{m.from}</p>
                    <span
                      className={`mono flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold ${scoreColor(m.score)}`}
                      title={badge.scored ? `Intelligence score ${badge.text}` : "Not analyzed yet — run AI Triage"}
                    >
                      {badge.text}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-aether-coral">{m.subject}</p>
                  <p className="mt-0.5 truncate text-[11px] text-aether-muted-dim">{m.preview}</p>
                  <div className="mt-1 flex items-center justify-between gap-2">
                    <p className="mono text-[10px] text-aether-muted-dim">{m.receivedAt}</p>
                    {m.account ? (
                      <span
                        data-testid="thread-source-account"
                        title={`Received in ${m.account}`}
                        className="truncate rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] text-aether-muted-dim"
                      >
                        <i className="fa-brands fa-google mr-1" aria-hidden="true" />
                        {m.account}
                      </span>
                    ) : null}
                  </div>
                </button>
                );
              })
            )}
          </div>
        </section>

        {/* Email detail + AI panel */}
        <section className="min-w-0 space-y-4 xl:col-span-2" data-testid="email-detail">
          {selected ? (
            <>
              <div className="glass rounded-2xl border border-white/10 p-5">
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-[15px] font-semibold">{selected.subject}</h2>
                    <p className="mt-0.5 text-xs text-aether-muted">
                      {selected.from} &lt;{selected.fromEmail}&gt; · {selected.receivedAt}
                      {senderLinkedIn ? (
                        <>
                          {" · "}
                          <a
                            href={senderLinkedIn}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-testid="linkedin-search-link"
                            className="text-aether-coral hover:underline"
                          >
                            Find on LinkedIn
                          </a>
                        </>
                      ) : null}
                    </p>
                  </div>
                  {(() => {
                    const detailBadge = emailScoreBadge(
                      computedIntel[selected.id]?.score ?? selected.score,
                    );
                    return (
                      <span
                        title={
                          detailBadge.scored
                            ? `Intelligence score ${detailBadge.text}`
                            : "Not analyzed yet"
                        }
                        className={`mono flex h-10 w-10 shrink-0 items-center justify-center rounded-full border text-xs font-bold ${scoreColor(
                          computedIntel[selected.id]?.score ?? selected.score,
                        )}`}
                      >
                        {detailBadge.text}
                      </span>
                    );
                  })()}
                </div>
                <p className="whitespace-pre-line rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-aether-muted">
                  {selected.body}
                </p>

                {/* AI intelligence — computed ON DEMAND for the selected thread */}
                {intelligence.available ? (
                  <div className="mt-4 rounded-xl border border-aether-violet/30 bg-aether-violet/5 p-4" data-testid="ai-intelligence">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-aether-violet">
                        AI Intelligence · score {intelligence.score}
                      </h3>
                      <button
                        type="button"
                        data-testid="reanalyze-btn"
                        onClick={() => void analyzeThread(selected.id)}
                        disabled={intelBusy}
                        className="text-[10px] text-aether-muted-dim hover:text-white disabled:opacity-50"
                      >
                        {intelBusy ? "Analyzing…" : "Re-analyze"}
                      </button>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {intelligence.breakdown.map((b) => (
                        <div key={b.label}>
                          <div className="mb-1 flex justify-between text-[11px]">
                            <span className="text-aether-muted">{b.label}</span>
                            <span className="mono">{b.value}</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-white/10">
                            <div className="h-1.5 rounded-full bg-aether-violet" style={{ width: `${b.value}%` }} />
                          </div>
                        </div>
                      ))}
                    </div>
                    <p className="mt-3 text-xs text-aether-muted">{intelligence.summary}</p>
                  </div>
                ) : (
                  <div className="mt-4 rounded-xl border border-white/10 bg-white/5 p-4" data-testid="ai-intelligence-empty">
                    <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
                      AI Intelligence
                    </h3>
                    <p className="text-xs text-aether-muted-dim">
                      Not analyzed yet — run the AI email agent on this thread to see a real
                      recruiter-engagement score, breakdown and summary.
                    </p>
                    <button
                      type="button"
                      data-testid="analyze-thread-btn"
                      onClick={() => void analyzeThread(selected.id)}
                      disabled={intelBusy}
                      className="mt-3 rounded-lg border border-aether-violet/40 bg-aether-violet/10 px-3 py-1.5 text-xs font-semibold text-aether-violet hover:bg-aether-violet/20 disabled:opacity-50"
                    >
                      <i className="fa-solid fa-wand-magic-sparkles mr-1.5" aria-hidden="true" />
                      {intelBusy ? "Analyzing…" : "Analyze this thread"}
                    </button>
                    {intelError ? (
                      <p className="mt-2 text-[11px] text-red-300" role="alert" data-testid="analyze-error">
                        {intelError}
                      </p>
                    ) : null}
                  </div>
                )}
              </div>

              {/* Draft reply — generated ON DEMAND by the real emailAgent; once a
                  draft exists the (honest) send confirmation gate is reachable. */}
              {(drafts[selected.id] ?? "").length > 0 ? (
                <div className="glass rounded-2xl border border-white/10 p-5" data-testid="draft-reply">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-[15px] font-semibold">AI Draft Reply</h3>
                    <span className="rounded-md border border-aether-violet/25 bg-aether-violet/10 px-2 py-0.5 text-[10px] text-aether-violet">
                      Grounded in your resume · fabrication-guarded
                    </span>
                  </div>
                  {(draftFlags[selected.id] ?? []).length > 0 ? (
                    <p
                      className="mb-3 rounded-lg border border-aether-amber/30 bg-aether-amber/10 p-2 text-[11px] text-aether-amber"
                      role="status"
                      data-testid="draft-flags"
                    >
                      Review before sending — the AI flagged claims with no evidence in your
                      resume/thread: {(draftFlags[selected.id] ?? []).join(", ")}
                    </p>
                  ) : null}
                  <textarea
                    value={draft}
                    aria-label="Draft reply"
                    data-testid="draft-textarea"
                    onChange={(e) => setDraft(e.target.value)}
                    rows={8}
                    className="w-full rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-aether-muted outline-none focus:border-aether-coral/40"
                  />
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      data-testid="open-send-gate-btn"
                      onClick={() => setGateOpen(true)}
                      disabled={draft.trim().length === 0}
                      className="rounded-lg bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
                    >
                      Send Reply
                    </button>
                    <button
                      type="button"
                      data-testid="regenerate-draft-btn"
                      onClick={() => void generateDraft(selected.id)}
                      disabled={draftBusy}
                      className="rounded-lg border border-white/15 px-4 py-2 text-sm text-aether-muted hover:border-white/30 disabled:opacity-50"
                    >
                      {draftBusy ? "Regenerating…" : "Regenerate"}
                    </button>
                  </div>
                  {draftError ? (
                    <p className="mt-2 text-[11px] text-red-300" role="alert" data-testid="draft-error">
                      {draftError}
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="glass rounded-2xl border border-white/10 p-5" data-testid="draft-reply-empty">
                  <h3 className="text-[15px] font-semibold">AI Draft Reply</h3>
                  <p className="mt-1 text-sm text-aether-muted-dim">
                    Generate a resume-grounded, fabrication-guarded reply you can review, edit
                    and send through the confirmation gate — nothing is sent automatically.
                  </p>
                  <button
                    type="button"
                    data-testid="generate-draft-btn"
                    onClick={() => void generateDraft(selected.id)}
                    disabled={draftBusy}
                    className="mt-3 rounded-lg bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
                  >
                    <i className="fa-solid fa-wand-magic-sparkles mr-2" aria-hidden="true" />
                    {draftBusy ? "Drafting…" : "AI Draft Reply"}
                  </button>
                  {draftError ? (
                    <p className="mt-2 text-[11px] text-red-300" role="alert" data-testid="draft-error">
                      {draftError}
                    </p>
                  ) : null}
                </div>
              )}
            </>
          ) : (
            <p className="glass rounded-2xl border border-white/10 p-8 text-center text-sm text-aether-muted-dim">
              Select an email to view details.
            </p>
          )}
        </section>

        {/* Right rail */}
        <div className="min-w-0 space-y-4 xl:col-span-1">
          <section className="glass rounded-2xl border border-white/10 p-5" data-testid="followups">
            <h2 className="mb-3 text-[15px] font-semibold">Automated Follow-Ups</h2>
            {inbox.followUps.length === 0 ? (
              <p className="text-xs text-aether-muted-dim">
                {connected
                  ? "No automated follow-ups queued yet. Aether drafts a silence-triggered nudge you approve before it sends — nothing goes out automatically."
                  : "Connect your Gmail account to enable the follow-up engine on real threads."}
              </p>
            ) : null}
            <div className="space-y-2.5">
              {inbox.followUps.map((f) => (
                <div key={`${f.company}-${f.role}`} className="rounded-xl border border-white/10 bg-white/5 p-3">
                  <p className="text-xs font-semibold">
                    {f.role} · {f.company}
                  </p>
                  <p className={`mono mt-1 text-[11px] ${f.status === "sent" ? "text-aether-green" : "text-aether-amber"}`}>
                    {f.dueIn}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section className="glass rounded-2xl border border-white/10 p-5" data-testid="email-stats">
            <h2 className="mb-3 text-[15px] font-semibold">This Week&apos;s Email Stats</h2>
            <div className="grid grid-cols-2 gap-2.5">
              <MiniStat label="Received" value={String(inbox.stats.received)} />
              <MiniStat label="Recruiter" value={String(inbox.stats.recruiterEmails)} />
              <MiniStat label="Auto-drafted" value={String(inbox.stats.autoDrafted)} />
              <MiniStat label="Sent (approved)" value={String(inbox.stats.sentApproved)} />
              <MiniStat label="Follow-ups" value={String(inbox.stats.followUpsSent)} />
              <MiniStat label="Avg response" value={`${inbox.stats.avgResponseHrs}h`} />
            </div>
          </section>

          {inbox.recruiterProfile ? (
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="recruiter-profile">
              <h2 className="mb-2 text-[15px] font-semibold">Recruiter Profile</h2>
              <p className="text-sm font-semibold">{inbox.recruiterProfile.name}</p>
              <p className="text-xs text-aether-muted">{inbox.recruiterProfile.role}</p>
              <p className="mono mt-2 text-[11px] text-aether-muted-dim">{inbox.recruiterProfile.history}</p>
              <p className="mt-2 text-xs text-aether-muted">{inbox.recruiterProfile.notes}</p>
            </section>
          ) : null}
        </div>
      </div>

      {/* Send confirmation gate */}
      {gateOpen && selected ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Confirm send"
        >
          <div className="glass w-full max-w-lg rounded-2xl border border-white/15 bg-[#12121C] p-6" data-testid="send-gate-modal">
            <div className="mb-3 flex items-center gap-2">
              <i className="fa-solid fa-shield-halved text-aether-amber" aria-hidden="true" />
              <h2 className="text-lg font-semibold">Confirm before sending</h2>
            </div>
            <p className="text-sm text-aether-muted">
              You&apos;re about to send this reply to <span className="font-semibold text-white">{selected.from}</span>{" "}
              ({selected.fromEmail}). This action is irreversible — Aether never sends without your explicit approval.
            </p>
            <p className="mt-3 max-h-40 overflow-y-auto whitespace-pre-line rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-aether-muted">
              {draft}
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                data-testid="send-gate-cancel"
                onClick={closeGate}
                className="rounded-lg border border-white/15 px-4 py-2 text-sm text-aether-muted hover:border-white/30"
              >
                Cancel (Esc)
              </button>
              <button
                type="button"
                data-testid="send-gate-confirm"
                onClick={() => void confirmSend()}
                disabled={sending}
                className="rounded-lg bg-aether-green px-4 py-2 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
              >
                {sending ? "Sending…" : "Confirm & Send"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Compose modal */}
      {composeOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Compose email"
        >
          <div className="glass w-full max-w-lg rounded-2xl border border-white/15 bg-[#12121C] p-6" data-testid="compose-modal">
            <div className="mb-4 flex items-center gap-2">
              <i className="fa-solid fa-pen-to-square text-aether-coral" aria-hidden="true" />
              <h2 className="text-lg font-semibold">Compose Draft</h2>
            </div>

            {composeError ? (
              <p className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-300" role="alert">
                {composeError}
              </p>
            ) : null}

            <div className="space-y-3">
              <div>
                <label htmlFor="compose-to" className="mb-1 block text-xs font-medium text-aether-muted">
                  To
                </label>
                <input
                  id="compose-to"
                  type="email"
                  value={composeTo}
                  onChange={(e) => setComposeTo(e.target.value)}
                  placeholder="recipient@example.com"
                  data-testid="compose-to"
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none placeholder:text-aether-muted-dim focus:border-aether-coral/40"
                />
              </div>
              <div>
                <label htmlFor="compose-subject" className="mb-1 block text-xs font-medium text-aether-muted">
                  Subject
                </label>
                <input
                  id="compose-subject"
                  type="text"
                  value={composeSubject}
                  onChange={(e) => setComposeSubject(e.target.value)}
                  placeholder="Email subject"
                  data-testid="compose-subject"
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none placeholder:text-aether-muted-dim focus:border-aether-coral/40"
                />
              </div>
              <div>
                <label htmlFor="compose-body" className="mb-1 block text-xs font-medium text-aether-muted">
                  Body
                </label>
                <textarea
                  id="compose-body"
                  value={composeBody}
                  onChange={(e) => setComposeBody(e.target.value)}
                  rows={8}
                  placeholder="Write your email…"
                  data-testid="compose-body"
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none placeholder:text-aether-muted-dim focus:border-aether-coral/40"
                />
              </div>
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                data-testid="compose-cancel"
                onClick={() => setComposeOpen(false)}
                className="rounded-lg border border-white/15 px-4 py-2 text-sm text-aether-muted hover:border-white/30"
              >
                Cancel (Esc)
              </button>
              <button
                type="button"
                data-testid="compose-save-draft"
                onClick={() => void saveDraft()}
                disabled={composeSaving || !composeSubject.trim() || !composeBody.trim()}
                className="rounded-lg bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
              >
                {composeSaving ? "Saving…" : "Save Draft"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-2.5 text-center">
      <div className="mono text-base font-bold">{value}</div>
      <div className="text-[10px] text-aether-muted-dim">{label}</div>
    </div>
  );
}
