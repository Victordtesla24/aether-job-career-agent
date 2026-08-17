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
  deleteNetworkingContact,
  fetchNetworkingContact,
  fetchNetworkingSummary,
  updateNetworkingContact,
  type NetworkingContactRecord,
  type NetworkingSummary,
} from "../../../lib/api/workspaces";
import { STAGE_ACCENT, buildPipelineColumns, formatOutreachKind, formatWhen, initials, totalContacts } from "./lib";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import {
  importGmailContacts,
  importLinkedInConnections,
  listContacts,
  refreshContactsFromInbox,
  type ContactListRow,
} from "../../../lib/api/networking";
import PageHeader from "../../../components/shell/PageHeader";

const EMPTY_FORM = { name: "", role: "", company: "", email: "", linkedinUrl: "" };
const CONTACT_STAGES = ["identified", "contacted", "responded", "meeting", "referral"] as const;

export default function NetworkingPage() {
  const [data, setData] = useState<NetworkingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  // W-NET-1: owner-initiated contact importers (Gmail correspondence /
  // LinkedIn export). One shared busy flag so the two can't race each other;
  // the notice reports the server's real counts, never a summary guess.
  const [importing, setImporting] = useState<"gmail" | "linkedin" | "inbox" | null>(null);
  const [importNotice, setImportNotice] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  // W-NET-2: the FULL contact browser. The kanban deliberately previews only
  // 5 cards per column; with hundreds of imported contacts that preview was
  // the ONLY window — "I cannot see my contacts" (owner, live). This modal
  // lists every contact from GET /networking/contacts with client-side
  // search, and rows open the existing detail panel.
  const [showAllContacts, setShowAllContacts] = useState(false);
  const [allContacts, setAllContacts] = useState<ContactListRow[] | null>(null);
  const [allContactsError, setAllContactsError] = useState<string | null>(null);
  const [contactSearch, setContactSearch] = useState("");
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
  // ML-networking-001: delete affordance for the EXISTING backend
  // DELETE /networking/contacts/{id} endpoint. Two-click confirm — the first
  // click arms the button, the second actually deletes.
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editStage, setEditStage] = useState("identified");
  const [editEmail, setEditEmail] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editCompany, setEditCompany] = useState("");
  const [editLinkedin, setEditLinkedin] = useState("");
  const [savingEdits, setSavingEdits] = useState(false);

  // ?demo=empty → render the real empty-state branch (state variant preview).
  useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("demo") === "empty") {
      setDemoEmpty(true);
    }
  }, []);

  const loadSummary = useCallback(() => {
    fetchNetworkingSummary()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load networking data"));
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  // W-RT — the shared realtime channel. This screen used to fetch ONCE on
  // mount, so a contact or outreach task written by the networking agent never
  // showed up without a manual reload. Both tables behind the summary are
  // subscribed.
  useRealtimeResources(["contacts", "outreach"], () => {
    loadSummary();
  });

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
    setDeleteArmed(false);
    fetchNetworkingContact(selectedContactId)
      .then((c) => {
        if (!cancelled) {
          setContactDetail(c);
          setEditStage(c.stage);
          setEditEmail(c.email || "");
          setEditTitle(c.title || "");
          setEditCompany(c.company || "");
          setEditLinkedin(c.linkedinUrl || "");
        }
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
    if (!showAdd && !selectedContactId && !showAllContacts) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (showAdd) closeAddModal();
      else if (showAllContacts) setShowAllContacts(false);
      else setSelectedContactId(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [showAdd, selectedContactId, showAllContacts, closeAddModal]);

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
        email: form.email.trim() || undefined,
        linkedinUrl: form.linkedinUrl.trim() || undefined,
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

  const saveContactEdits = async () => {
    if (!contactDetail) return;
    setSavingEdits(true);
    setContactDetailError(null);
    try {
      const updated = await updateNetworkingContact(contactDetail.id, {
        title: editTitle.trim() || undefined,
        company: editCompany.trim() || undefined,
        email: editEmail.trim() || undefined,
        linkedinUrl: editLinkedin.trim() || undefined,
        stage: editStage,
      });
      setContactDetail(updated);
      setData(await fetchNetworkingSummary());
    } catch (e) {
      setContactDetailError(e instanceof Error ? e.message : "Failed to save contact");
    } finally {
      setSavingEdits(false);
    }
  };

  const runRefreshFromInbox = async () => {
    setImporting("inbox");
    setImportNotice(null);
    setImportError(null);
    try {
      const r = await refreshContactsFromInbox();
      setImportNotice(
        `Inbox refresh: ${r.contactsCreated} contact(s) created, ` +
          `${r.contactsUpdated} updated, ${r.threadsLinked} thread(s) linked, ` +
          `${r.ignored} ignored.`,
      );
      loadSummary();
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "Inbox refresh failed.");
    } finally {
      setImporting(null);
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
            <div key={i} className="bg-surface-1 h-24 animate-pulse rounded-[14px] border border-white/10" />
          ))}
        </div>
        <div className="bg-surface-1 h-72 animate-pulse rounded-[14px] border border-white/10" />
      </div>
    );
  }

  const contactCount = totalContacts(data.stats, []);
  const isEmpty = contactCount === 0 || demoEmpty;
  const columns = buildPipelineColumns(data.pipeline);

  return (
    <div className="space-y-6" data-testid="networking-crm">
      <PageHeader
        title={<span className="text-gradient-brand">Networking</span>}
        subtitle="Recruiter and referral CRM — contacts stay current from Gmail and LinkedIn export."
        footnote={
          data.crmSummary.lastContactUpdatedAt ? (
            <span data-testid="networking-freshness">
              Last contact update {formatWhen(data.crmSummary.lastContactUpdatedAt)} ·{" "}
              {data.crmSummary.followUpsDueToday} follow-up{data.crmSummary.followUpsDueToday === 1 ? "" : "s"} due today
            </span>
          ) : (
            <span data-testid="networking-freshness">Last contact update not measured</span>
          )
        }
        action={
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="import-gmail-contacts-btn"
            disabled={importing !== null}
            onClick={async () => {
              setImporting("gmail");
              setImportNotice(null);
              setImportError(null);
              try {
                const r = await importGmailContacts();
                setImportNotice(
                  `Gmail import: ${r.contactsCreated} contact(s) created, ` +
                    `${r.duplicates} duplicate(s) skipped, ${r.suppressed} suppressed, ` +
                    `${r.ignored} non-professional sender(s) ignored.`,
                );
                loadSummary();
              } catch (e) {
                setImportError(e instanceof Error ? e.message : "Gmail import failed.");
              } finally {
                setImporting(null);
              }
            }}
            className="rounded-xl border border-white/15 px-3 py-2 text-sm font-semibold text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
          >
            <i className="fa-solid fa-envelope mr-2" aria-hidden="true" />
            {importing === "gmail" ? "Importing…" : "Import from Gmail"}
          </button>
          <button
            type="button"
            data-testid="refresh-from-inbox-btn"
            disabled={importing !== null}
            onClick={() => void runRefreshFromInbox()}
            className="rounded-xl border border-white/15 px-3 py-2 text-sm font-semibold text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
          >
            <i className="fa-solid fa-rotate mr-2" aria-hidden="true" />
            {importing === "inbox" ? "Refreshing…" : "Refresh from inbox"}
          </button>
          <label
            data-testid="import-linkedin-contacts-label"
            className={`cursor-pointer rounded-xl border border-white/15 px-3 py-2 text-sm font-semibold text-aether-muted hover:border-white/30 hover:text-white ${
              importing !== null ? "pointer-events-none opacity-50" : ""
            }`}
          >
            <i className="fa-brands fa-linkedin mr-2" aria-hidden="true" />
            {importing === "linkedin" ? "Importing…" : "Import LinkedIn export"}
            <input
              type="file"
              accept=".zip,.csv"
              className="hidden"
              data-testid="import-linkedin-contacts-input"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                setImporting("linkedin");
                setImportNotice(null);
                setImportError(null);
                try {
                  const r = await importLinkedInConnections(file);
                  setImportNotice(
                    `LinkedIn import: ${r.contactsCreated} contact(s) created, ` +
                      `${r.duplicates} duplicate(s) skipped, ${r.suppressed} suppressed.`,
                  );
                  loadSummary();
                } catch (err) {
                  setImportError(
                    err instanceof Error ? err.message : "LinkedIn import failed.",
                  );
                } finally {
                  setImporting(null);
                }
              }}
            />
          </label>
          <button
            type="button"
            data-testid="view-all-contacts-btn"
            onClick={() => {
              setShowAllContacts(true);
              setAllContactsError(null);
              listContacts()
                .then(setAllContacts)
                .catch((e) =>
                  setAllContactsError(
                    e instanceof Error ? e.message : "Could not load contacts.",
                  ),
                );
            }}
            className="rounded-xl border border-white/15 px-3 py-2 text-sm font-semibold text-aether-muted hover:border-white/30 hover:text-white"
          >
            <i className="fa-solid fa-address-book mr-2" aria-hidden="true" />
            View all ({contactCount})
          </button>
          <button
            type="button"
            data-testid="add-contact-btn"
            onClick={() => setShowAdd(true)}
            className="rounded-xl bg-gold px-4 py-2 text-sm font-semibold text-[#0a0a0a] hover:opacity-90"
          >
            Add Contact
          </button>
        </div>
        }
      />

      {showAllContacts ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-16"
          data-testid="all-contacts-modal"
          onClick={() => setShowAllContacts(false)}
        >
          <div
            className="bg-surface-1 max-h-[75vh] w-full max-w-2xl overflow-hidden rounded-[14px] border border-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-white/10 p-4">
              <h2 className="text-sm font-semibold">
                All contacts{allContacts ? ` (${allContacts.length})` : ""}
              </h2>
              <button
                type="button"
                data-testid="all-contacts-close"
                onClick={() => setShowAllContacts(false)}
                className="text-aether-muted hover:text-white"
                aria-label="Close"
              >
                <i className="fa-solid fa-xmark" aria-hidden="true" />
              </button>
            </div>
            <div className="p-4">
              <input
                type="search"
                data-testid="all-contacts-search"
                placeholder="Search name, company or title…"
                value={contactSearch}
                onChange={(e) => setContactSearch(e.target.value)}
                className="mb-3 w-full rounded-lg border border-white/10 bg-transparent px-3 py-2 text-sm"
              />
              {allContactsError ? (
                <p className="text-sm text-red-300" data-testid="all-contacts-error">
                  {allContactsError}
                </p>
              ) : allContacts === null ? (
                <p className="text-sm text-aether-muted">Loading…</p>
              ) : (
                <ul
                  className="max-h-[52vh] divide-y divide-white/5 overflow-y-auto"
                  data-testid="all-contacts-list"
                >
                  {allContacts
                    .filter((c) => {
                      const q = contactSearch.trim().toLowerCase();
                      if (!q) return true;
                      return [c.name, c.company, c.title, c.email]
                        .filter(Boolean)
                        .some((v) => String(v).toLowerCase().includes(q));
                    })
                    .map((c) => (
                      <li key={c.id}>
                        <button
                          type="button"
                          data-testid={`all-contacts-row-${c.id}`}
                          onClick={() => {
                            setShowAllContacts(false);
                            setSelectedContactId(c.id);
                          }}
                          className="flex w-full items-baseline justify-between gap-3 px-1 py-2 text-left hover:bg-white/5"
                        >
                          <span className="min-w-0 truncate text-sm font-medium">
                            {c.name}
                            {c.title || c.company ? (
                              <span className="ml-2 font-normal text-aether-muted">
                                {[c.title, c.company].filter(Boolean).join(" @ ")}
                              </span>
                            ) : null}
                          </span>
                          <span className="shrink-0 text-[11px] uppercase tracking-wide text-aether-muted-dim">
                            {c.stage}
                          </span>
                        </button>
                      </li>
                    ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {importNotice ? (
        <p data-testid="import-notice" className="text-sm text-aether-green">
          {importNotice}
        </p>
      ) : null}
      {importError ? (
        <p data-testid="import-error" className="text-sm text-red-300">
          {importError}
        </p>
      ) : null}

      {isEmpty ? (
        <div className="bg-surface-1 rounded-[14px] border border-white/10 p-12 text-center" data-testid="networking-empty-state">
          <p className="text-lg font-semibold">No connections yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-aether-muted">
            Import from Gmail or a LinkedIn Connections.csv export to keep this board current, or add a contact
            manually to begin tracking outreach.
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
            <Stat
              label="Response rate"
              value={data.stats.responseRate === null ? "not measured" : `${data.stats.responseRate}%`}
              accent={data.stats.responseRate === null ? "text-aether-muted" : "text-aether-green"}
            />
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
                              className="bg-surface-1 cursor-pointer rounded-xl border border-white/10 p-3 transition hover:border-aether-coral/40"
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
              <section className="bg-surface-1 rounded-[14px] border border-white/10 p-5" data-testid="outreach-queue">
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

              <section className="bg-surface-1 rounded-[14px] border border-white/10 p-5" data-testid="communication-log">
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
          <div className="w-full max-w-md rounded-[14px] border border-white/15 bg-surface-2 p-6" data-testid="add-contact-modal">
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
              <Field label="Email" value={form.email} onChange={(v) => setForm((f) => ({ ...f, email: v }))} testId="contact-email-input" />
              <Field label="LinkedIn URL" value={form.linkedinUrl} onChange={(v) => setForm((f) => ({ ...f, linkedinUrl: v }))} testId="contact-linkedin-input" />
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
                  className="rounded-lg bg-gold px-4 py-2 text-sm font-semibold text-[#0a0a0a] hover:opacity-90 disabled:opacity-60"
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
            className="w-full max-w-md rounded-[14px] border border-white/15 bg-surface-2 p-6"
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
              <div className="space-y-3" data-testid="contact-detail-body">
                <dl className="space-y-2 text-sm">
                  <DetailRow label="Name" value={contactDetail.name} />
                  <DetailRow label="Role" value={contactDetail.title || "—"} />
                  <DetailRow label="Company" value={contactDetail.company || "—"} />
                  <DetailRow label="Stage" value={contactDetail.stage} />
                  <DetailRow label="Email" value={contactDetail.email || "Not provided"} />
                  <DetailRow label="LinkedIn" value={contactDetail.linkedinUrl || "Not provided"} />
                </dl>
                <Field label="Role" value={editTitle} onChange={setEditTitle} testId="contact-edit-title" />
                <Field label="Company" value={editCompany} onChange={setEditCompany} testId="contact-edit-company" />
                <label className="block">
                  <span className="mb-1 block text-xs text-aether-muted">Stage</span>
                  <select
                    data-testid="contact-stage-select"
                    value={editStage}
                    onChange={(e) => setEditStage(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-gold/50"
                  >
                    {CONTACT_STAGES.map((stage) => (
                      <option key={stage} value={stage} className="bg-black">
                        {stage}
                      </option>
                    ))}
                  </select>
                </label>
                <Field label="Email" value={editEmail} onChange={setEditEmail} testId="contact-edit-email" />
                <Field label="LinkedIn" value={editLinkedin} onChange={setEditLinkedin} testId="contact-edit-linkedin" />
              </div>
            ) : null}
            {contactDetail ? (
              /* ML-networking-001: the backend DELETE endpoint existed with no
                 UI path. Two-click confirm, then refetch the summary so the
                 board reflects exactly what the server persisted. */
              <div className="mt-4 flex justify-between gap-2">
                <button
                  type="button"
                  data-testid="save-contact-edits-btn"
                  disabled={savingEdits || deleting}
                  onClick={() => void saveContactEdits()}
                  className="rounded-lg bg-gold px-4 py-2 text-sm font-semibold text-[#0a0a0a] hover:opacity-90 disabled:opacity-60"
                >
                  {savingEdits ? "Saving…" : "Save changes"}
                </button>
                <button
                  type="button"
                  data-testid="delete-contact-btn"
                  disabled={deleting}
                  onClick={async () => {
                    if (!deleteArmed) {
                      setDeleteArmed(true);
                      return;
                    }
                    setDeleting(true);
                    try {
                      await deleteNetworkingContact(contactDetail.id);
                      setSelectedContactId(null);
                      setData(await fetchNetworkingSummary());
                    } catch (e) {
                      setContactDetailError(
                        e instanceof Error ? e.message : "Failed to delete contact",
                      );
                    } finally {
                      setDeleting(false);
                      setDeleteArmed(false);
                    }
                  }}
                  className={`rounded-lg border px-4 py-2 text-sm transition disabled:opacity-60 ${
                    deleteArmed
                      ? "border-red-400/60 bg-red-500/20 text-red-200"
                      : "border-white/15 text-aether-muted hover:border-red-400/40 hover:text-red-200"
                  }`}
                >
                  {deleting
                    ? "Deleting..."
                    : deleteArmed
                      ? "Click again to confirm delete"
                      : "Delete contact"}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value, accent = "" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="bg-surface-1 rounded-[14px] border border-white/10 p-5">
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
