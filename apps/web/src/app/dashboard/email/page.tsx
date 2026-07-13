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
  emailSendErrorMessage,
  fetchEmailInbox,
  sendEmailReply,
  type EmailInbox,
  type EmailMessage,
} from "../../../lib/api/workspaces";

const CATEGORIES = [
  { key: "priority", label: "Priority" },
  { key: "all", label: "All Recruiter" },
  { key: "followup", label: "Follow-Up Due" },
  { key: "auto", label: "Auto-Replied" },
  { key: "trashed", label: "Trashed" },
] as const;

const TONES = ["Professional", "Warm", "Direct"] as const;

function scoreColor(score: number) {
  if (score >= 75) return "text-aether-green border-aether-green/40";
  if (score >= 50) return "text-aether-amber border-aether-amber/40";
  return "text-red-300 border-red-500/40";
}

export default function EmailCenterPage() {
  const [inbox, setInbox] = useState<EmailInbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<string>("priority");
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tone, setTone] = useState<string>("Professional");
  const [draft, setDraft] = useState<string>("");
  const [gateOpen, setGateOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [sentNotice, setSentNotice] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);

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
          setDraft(first.draftReply);
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load inbox"));
  }, []);

  const selected: EmailMessage | undefined = useMemo(
    () => inbox?.messages.find((m) => m.id === selectedId),
    [inbox, selectedId],
  );

  // Guarded AI-intelligence view: `intelligence` is null until a real scoring
  // backend is wired (GAP-P4-041), so never dereference it directly.
  const intelligence = useMemo(
    () => (selected ? emailIntelligenceView(selected) : ({ available: false } as const)),
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
    setDraft(m.draftReply);
    setSentNotice(null);
    setSendError(null);
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
            onClick={openCompose}
            className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <i className="fa-solid fa-pen mr-2" aria-hidden="true" />
            Compose
          </button>
        </div>
      </header>

      {/* Connected accounts */}
      <div className="glass flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 p-3" data-testid="email-accounts">
        <span className="text-xs uppercase tracking-wide text-aether-muted-dim">Accounts</span>
        <button
          type="button"
          onClick={() => setAccountFilter("all")}
          className={`rounded-lg border px-3 py-1.5 text-xs transition ${
            accountFilter === "all" ? "border-aether-coral/50 text-white" : "border-white/10 text-aether-muted"
          }`}
        >
          All accounts
        </button>
        {inbox.accounts.map((a) => (
          <button
            key={a.email}
            type="button"
            onClick={() => setAccountFilter(a.email)}
            className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition ${
              accountFilter === a.email ? "border-aether-coral/50 text-white" : "border-white/10 text-aether-muted"
            }`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-aether-green" />
            {a.email}
            <span className="mono text-[10px] text-aether-muted-dim">{a.unread} unread</span>
          </button>
        ))}
        <button type="button" className="rounded-lg border border-dashed border-white/15 px-3 py-1.5 text-xs text-aether-muted-dim hover:text-white">
          + Connect account
        </button>
      </div>

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
          <div className="space-y-2">
            {visibleMessages.length === 0 ? (
              <p className="py-6 text-center text-xs text-aether-muted-dim" data-testid="inbox-empty">
                No emails in this view.
              </p>
            ) : (
              visibleMessages.map((m) => (
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
                      title={`Intelligence score ${m.score}`}
                    >
                      {m.score}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-aether-coral">{m.subject}</p>
                  <p className="mt-0.5 truncate text-[11px] text-aether-muted-dim">{m.preview}</p>
                  <p className="mono mt-1 text-[10px] text-aether-muted-dim">{m.receivedAt}</p>
                </button>
              ))
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
                      {selected.from} &lt;{selected.fromEmail}&gt; · {selected.receivedAt} ·{" "}
                      <a
                        href="https://www.linkedin.com/"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-aether-coral hover:underline"
                      >
                        LinkedIn Profile
                      </a>
                    </p>
                  </div>
                  <span className={`mono flex h-10 w-10 shrink-0 items-center justify-center rounded-full border text-xs font-bold ${scoreColor(selected.score)}`}>
                    {selected.score}
                  </span>
                </div>
                <p className="whitespace-pre-line rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-aether-muted">
                  {selected.body}
                </p>

                {/* AI intelligence — guarded: the backend returns no score yet */}
                {intelligence.available ? (
                  <div className="mt-4 rounded-xl border border-aether-violet/30 bg-aether-violet/5 p-4" data-testid="ai-intelligence">
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-aether-violet">
                      AI Intelligence · score {intelligence.score}
                    </h3>
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
                      No intelligence available yet — connect your Gmail account to enable AI
                      scoring on your real threads.
                    </p>
                  </div>
                )}
              </div>

              {/* Draft reply */}
              {selected.draftReply ? (
                <div className="glass rounded-2xl border border-white/10 p-5" data-testid="draft-reply">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-[15px] font-semibold">AI Draft Reply</h3>
                    <div className="flex items-center gap-2">
                      <span className="mono text-[11px] text-aether-green">Voice DNA {selected.voiceDna}%</span>
                      <span className="rounded-md border border-aether-violet/25 bg-aether-violet/10 px-2 py-0.5 text-[10px] text-aether-violet">
                        Expert · Humble · Professional
                      </span>
                      <div className="flex rounded-lg border border-white/10 p-0.5">
                        {TONES.map((t) => (
                          <button
                            key={t}
                            type="button"
                            onClick={() => setTone(t)}
                            aria-pressed={tone === t}
                            className={`rounded-md px-2 py-1 text-[11px] transition ${
                              tone === t ? "bg-white/10 text-white" : "text-aether-muted-dim hover:text-white"
                            }`}
                          >
                            {t}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
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
                      onClick={() => setDraft(selected.draftReply)}
                      className="rounded-lg border border-white/15 px-4 py-2 text-sm text-aether-muted hover:border-white/30"
                    >
                      Regenerate
                    </button>
                  </div>
                </div>
              ) : (
                <p className="glass rounded-2xl border border-white/10 p-5 text-sm text-aether-muted-dim">
                  No reply needed for this email.
                </p>
              )}
            </>
          ) : (
            <p className="glass rounded-2xl border border-white/10 p-8 text-center text-sm text-aether-muted-dim">
              Select an email to view details.
            </p>
          )}
        </section>

        {/* Right rail */}
        <div className="space-y-4 xl:col-span-1">
          <section className="glass rounded-2xl border border-white/10 p-5" data-testid="followups">
            <h2 className="mb-3 text-[15px] font-semibold">Automated Follow-Ups</h2>
            {inbox.followUps.length === 0 ? (
              <p className="text-xs text-aether-muted-dim">
                No follow-ups queued yet — connect your Gmail account to enable the
                follow-up engine on real threads.
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
