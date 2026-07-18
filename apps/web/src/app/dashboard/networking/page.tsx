"use client";

/**
 * Networking — Recruiter & Referral CRM backed by GET /networking/summary
 * (wireframe: networking.html). Stat tiles, 5-stage contact pipeline,
 * outreach queue and communication log, with a real Add Contact flow and a
 * contact-detail panel.
 *
 * MV-networking-001: "Add Contact" persists via POST /networking/contacts
 * (app/routers/networking.py) — no more client-side-only fake success.
 * MV-networking-002: Outreach Queue / Communication Log render the actual
 * fields GET /workspaces/networking/summary sends (contactName/company/
 * subject/kind/status/scheduledAt/sentAt), not a made-up shape.
 * MV-networking-003: the empty-state control that used to claim "Import from
 * LinkedIn" (while only opening the manual Add-Contact modal) is relabeled
 * honestly — there is no LinkedIn OAuth integration behind it.
 * MV-networking-004: the dead "Review all drafts" button (no handler, no
 * destination screen) is removed rather than left as a no-op.
 * MV-networking-005: contact cards open a detail panel sourced from the real
 * GET /networking/contacts/{id} endpoint.
 * MV-networking-006: contact cards show their pipeline-stage badge.
 * MV-networking-009 / -010: Cancel resets the Add Contact form; Escape closes
 * whichever modal is open regardless of DOM focus.
 */
import { useCallback, useEffect, useState } from "react";

import {
  createNetworkingContact,
  fetchNetworkingContact,
  fetchNetworkingSummary,
  type NetworkingContactRecord,
  type NetworkingSummary,
} from "../../../lib/api/workspaces";
import { STAGE_ACCENT, buildPipelineColumns, formatOutreachKind, formatWhen, initials, totalContacts } from "./lib";

const EMPTY_FORM = { name: "", role: "", company: "" };

export default function NetworkingPage() {
  const [data, setData] = useState<NetworkingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [demoEmpty, setDemoEmpty] = useState(false);

  // Contact-detail panel (MV-networking-005): the id of the contact whose
  // details are being viewed, or null when the panel is closed.
  const [selectedContactId, setSelectedContactId] = useState<string | null>(null);
  const [contactDetail, setContactDetail] = useState<NetworkingContactRecord | null>(null);
  const [contactDetailLoading, setContactDetailLoading] = useState(false);
  const [contactDetailError, setContactDetailError] = useState<string | null>(null);

  // ?demo=empty → render the real empty-state branch (state variant preview).
  useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("demo") === "empty") {
      setDemoEmpty(true);
    }
  }, []);

  useEffect(() => {
    fetchNetworkingSummary()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load networking data"));
  }, []);

  // Contact detail: fetch on demand via the real GET /networking/contacts/{id}
  // endpoint whenever a card is selected.
  useEffect(() => {
    if (!selectedContactId) {
      setContactDetail(null);
      setContactDetailError(null);
      return;
    }
    let cancelled = false;
    setContactDetailLoading(true);
    setContactDetailError(null);
    fetchNetworkingContact(selectedContactId)
      .then((c) => {
        if (!cancelled) setContactDetail(c);
      })
      .catch((e: unknown) => {
        if (!cancelled) setContactDetailError(e instanceof Error ? e.message : "Failed to load contact");
      })
      .finally(() => {
        if (!cancelled) setContactDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedContactId]);

  const closeAddModal = useCallback(() => {
    setShowAdd(false);
    setForm(EMPTY_FORM);
    setFormError(null);
  }, []);

  // Escape closes whichever modal is open — a document-level listener so it
  // fires regardless of which element currently has focus (MV-networking-010:
  // the previous per-dialog onKeyDown only fired when focus was already
  // inside the modal's DOM subtree).
  useEffect(() => {
    if (!showAdd && !selectedContactId) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (showAdd) closeAddModal();
      else setSelectedContactId(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [showAdd, selectedContactId, closeAddModal]);

  const saveContact = async () => {
    if (!form.name.trim()) {
      setFormError("Name is required");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await createNetworkingContact({
        name: form.name.trim(),
        title: form.role.trim() || undefined,
        company: form.company.trim() || undefined,
      });
      // Re-fetch from the source of truth so the board reflects exactly what
      // the backend persisted — no optimistic local-only echo (MV-networking-001).
      const refreshed = await fetchNetworkingSummary();
      setData(refreshed);
      setForm(EMPTY_FORM);
      setFormError(null);
      setShowAdd(false);
    } catch (e) {
      // Honest failure: modal stays open, no fabricated success.
      setFormError(e instanceof Error ? e.message : "Failed to save contact");
    } finally {
      setSaving(false);
    }
  };

  if (error) {
    return <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>;
  }

  if (data === null) {
    return (
      <div className="space-y-4" aria-busy="true" data-testid="networking-skeleton">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="glass h-24 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
        <div className="glass h-72 animate-pulse rounded-2xl border border-white/10" />
      </div>
    );
  }

  const contactCount = totalContacts(data.stats, []);
  const isEmpty = contactCount === 0 || demoEmpty;
  const columns = buildPipelineColumns(data.pipeline);

  return (
    <div className="space-y-6" data-testid="networking-crm">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Networking</h1>
          <p className="text-sm text-aether-muted">Recruiter &amp; Referral CRM — warm intros beat cold applies.</p>
        </div>
        <button
          type="button"
          data-testid="add-contact-btn"
          onClick={() => setShowAdd(true)}
          className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
        >
          + Add Contact
        </button>
      </header>

      {isEmpty ? (
        <div className="glass rounded-2xl border border-white/10 p-12 text-center" data-testid="networking-empty-state">
          <p className="text-lg font-semibold">No connections yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-aether-muted">
            Start building your recruiter &amp; referral network by adding a contact manually to begin tracking
            outreach.
          </p>
          <button
            type="button"
            data-testid="empty-state-add-contact-btn"
            onClick={() => setShowAdd(true)}
            className="mt-4 rounded-xl border border-aether-violet/40 px-4 py-2 text-sm font-semibold text-aether-violet hover:bg-aether-violet/10"
          >
            <i className="fa-solid fa-user-plus mr-2" aria-hidden="true" />
            Add contact manually
          </button>
        </div>
      ) : (
        <>
          {/* Stat tiles */}
          <section className="grid grid-cols-2 gap-4 md:grid-cols-4" data-testid="networking-stats">
            <Stat label="Contacts" value={String(contactCount)} />
            <Stat label="Active conversations" value={String(data.stats.activeConversations)} accent="text-aether-coral" />
            <Stat label="Referrals in flight" value={String(data.stats.referralsInFlight)} accent="text-aether-violet" />
            <Stat label="Response rate" value={`${data.stats.responseRate}%`} accent="text-aether-green" />
          </section>

          <div className="grid gap-6 xl:grid-cols-3">
            {/* Contact pipeline */}
            <section className="min-w-0 xl:col-span-2" data-testid="contact-pipeline">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-aether-muted">
                Contact Pipeline
              </h2>
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
                {columns.map((col) => {
                  return (
                    <div key={col.stage} className="min-w-0" data-testid={`pipeline-${col.stage.toLowerCase()}`}>
                      <div className="mb-2 flex items-center justify-between px-1">
                        <div className="flex items-center gap-1.5">
                          <span className={`h-2 w-2 rounded-full ${STAGE_ACCENT[col.stage] ?? "bg-white/40"}`} />
                          <span className="text-xs font-semibold">{col.stage}</span>
                        </div>
                        <span className="mono text-[11px] text-aether-muted-dim">{col.count}</span>
                      </div>
                      {col.contacts.length === 0 ? (
                        <div
                          className="rounded-xl border border-dashed border-white/10 px-2 py-3 text-center text-[10px] text-aether-muted-dim"
                          data-testid={`pipeline-${col.stage.toLowerCase()}-empty`}
                        >
                          No contacts yet
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {col.contacts.map((c) => (
                            <article
                              key={c.id ?? `${c.name}-${c.company}`}
                              data-testid="contact-card"
                              role="button"
                              tabIndex={0}
                              onClick={() => c.id && setSelectedContactId(c.id)}
                              onKeyDown={(e) => {
                                if ((e.key === "Enter" || e.key === " ") && c.id) {
                                  e.preventDefault();
                                  setSelectedContactId(c.id);
                                }
                              }}
                              className="glass cursor-pointer rounded-xl border border-white/10 p-3 transition hover:border-aether-coral/40"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex min-w-0 items-center gap-2">
                                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[10px] font-bold">
                                    {initials(c.name)}
                                  </span>
                                  <div className="min-w-0">
                                    <p className="truncate text-xs font-semibold">{c.name}</p>
                                    <p className="truncate text-[10px] text-aether-muted-dim">
                                      {c.role} · {c.company}
                                    </p>
                                  </div>
                                </div>
                                {/* MV-networking-006: honest stage badge on each card. */}
                                <span
                                  className={`mono shrink-0 rounded px-1.5 py-0.5 text-[9px] ${STAGE_ACCENT[col.stage] ?? "bg-white/40"} bg-opacity-20 text-white/80`}
                                  data-testid="contact-stage-badge"
                                >
                                  {col.stage}
                                </span>
                              </div>
                              <p className="mt-1.5 text-[10px] text-aether-amber" aria-label={`Warmth ${c.warmth} of 5`}>
                                {"★".repeat(c.warmth)}
                                <span className="text-white/15">{"★".repeat(Math.max(0, 5 - c.warmth))}</span>
                              </p>
                            </article>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Right column */}
            <div className="min-w-0 space-y-6">
              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="outreach-queue">
                <h2 className="mb-3 text-[15px] font-semibold">Outreach Queue</h2>
                {data.outreachQueue.length === 0 ? (
                  <p className="text-xs text-aether-muted-dim" data-testid="outreach-queue-empty">
                    No outreach queued yet.
                  </p>
                ) : (
                  <div className="space-y-3">
                    {data.outreachQueue.map((o) => (
                      <article key={o.id} className="rounded-xl border border-white/10 bg-white/5 p-3">
                        <p className="text-xs font-semibold">
                          {o.contactName || "Unknown contact"}
                          {o.company ? ` · ${o.company}` : ""}
                        </p>
                        <p className="mt-0.5 text-xs text-aether-coral">{o.subject}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <span className="mono inline-block rounded bg-aether-violet/15 px-1.5 py-0.5 text-[10px] text-aether-violet">
                            {formatOutreachKind(o.kind)}
                          </span>
                          <span className="mono inline-block rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-aether-muted">
                            {o.status}
                          </span>
                        </div>
                        {o.scheduledAt ? (
                          <p className="mt-1 text-[10px] text-aether-muted-dim">
                            Scheduled: {formatWhen(o.scheduledAt)}
                          </p>
                        ) : null}
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="communication-log">
                <h2 className="mb-3 text-[15px] font-semibold">Communication Log</h2>
                {data.communicationLog.length === 0 ? (
                  <p className="text-xs text-aether-muted-dim" data-testid="communication-log-empty">
                    No communications logged yet.
                  </p>
                ) : (
                  <div className="space-y-3">
                    {data.communicationLog.map((l) => (
                      <div key={l.id} className="border-l-2 border-white/10 pl-3">
                        <p className="mono text-[10px] text-aether-muted-dim">
                          {formatWhen(l.sentAt)} · {formatOutreachKind(l.kind)}
                        </p>
                        <p className="text-xs">
                          <span className="font-semibold">{l.contactName || "Unknown contact"}</span>{" "}
                          <span className="text-aether-muted">— {l.subject}</span>
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </div>
        </>
      )}

      {/* Add Contact modal */}
      {showAdd ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Add contact"
        >
          <div className="glass w-full max-w-md rounded-2xl border border-white/15 bg-[#12121C] p-6" data-testid="add-contact-modal">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Add Contact</h2>
              <button type="button" onClick={closeAddModal} className="text-aether-muted-dim hover:text-white">
                ✕
              </button>
            </div>
            <div className="space-y-3">
              <Field label="Name *" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} testId="contact-name-input" />
              <Field label="Role" value={form.role} onChange={(v) => setForm((f) => ({ ...f, role: v }))} testId="contact-role-input" />
              <Field label="Company" value={form.company} onChange={(v) => setForm((f) => ({ ...f, company: v }))} testId="contact-company-input" />
              {formError ? <p className="text-xs text-red-300" data-testid="add-contact-error">{formError}</p> : null}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={closeAddModal}
                  className="rounded-lg border border-white/15 px-4 py-2 text-sm text-aether-muted hover:border-white/30"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  data-testid="save-contact-btn"
                  onClick={saveContact}
                  disabled={saving}
                  className="rounded-lg bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60"
                >
                  {saving ? "Saving…" : "Save Contact"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Contact detail panel (MV-networking-005) */}
      {selectedContactId ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Contact details"
        >
          <div
            className="glass w-full max-w-md rounded-2xl border border-white/15 bg-[#12121C] p-6"
            data-testid="contact-detail-modal"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Contact details</h2>
              <button
                type="button"
                onClick={() => setSelectedContactId(null)}
                className="text-aether-muted-dim hover:text-white"
              >
                ✕
              </button>
            </div>
            {contactDetailLoading ? (
              <p className="text-sm text-aether-muted" data-testid="contact-detail-loading">
                Loading…
              </p>
            ) : contactDetailError ? (
              <p className="text-sm text-red-300" data-testid="contact-detail-error">
                {contactDetailError}
              </p>
            ) : contactDetail ? (
              <dl className="space-y-2 text-sm" data-testid="contact-detail-body">
                <DetailRow label="Name" value={contactDetail.name} />
                <DetailRow label="Role" value={contactDetail.title || "—"} />
                <DetailRow label="Company" value={contactDetail.company || "—"} />
                <DetailRow label="Stage" value={contactDetail.stage} />
                <DetailRow label="Email" value={contactDetail.email || "Not provided"} />
                <DetailRow label="LinkedIn" value={contactDetail.linkedinUrl || "Not provided"} />
              </dl>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value, accent = "" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="glass rounded-2xl border border-white/10 p-5">
      <div className={`mono text-2xl font-bold ${accent}`}>{value}</div>
      <div className="mt-1 text-[11px] uppercase tracking-wide text-aether-muted-dim">{label}</div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
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
        className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-aether-coral/50"
      />
    </label>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-white/5 pb-2">
      <dt className="text-aether-muted-dim">{label}</dt>
      <dd className="max-w-[65%] break-words text-right font-medium">{value}</dd>
    </div>
  );
}
