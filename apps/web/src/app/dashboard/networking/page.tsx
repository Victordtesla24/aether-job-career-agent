"use client";

/**
 * Networking — Recruiter & Referral CRM backed by GET /networking/summary
 * (wireframe: networking.html). Stat tiles, 5-stage contact pipeline,
 * outreach queue and communication log, with an Add Contact modal.
 */
import { useEffect, useState } from "react";

import {
  fetchNetworkingSummary,
  type NetworkingContact,
  type NetworkingSummary,
} from "../../../lib/api/workspaces";

const STAGE_ACCENT: Record<string, string> = {
  New: "bg-white/40",
  Warm: "bg-aether-amber",
  Active: "bg-aether-coral",
  Scheduled: "bg-aether-violet",
  Placed: "bg-aether-green",
};

function initials(name: string) {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default function NetworkingPage() {
  const [data, setData] = useState<NetworkingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", role: "", company: "" });
  const [formError, setFormError] = useState<string | null>(null);
  // Locally-added contacts land in the "New" stage (demo scope).
  const [added, setAdded] = useState<NetworkingContact[]>([]);

  useEffect(() => {
    fetchNetworkingSummary()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load networking data"));
  }, []);

  const addContact = () => {
    if (!form.name.trim()) {
      setFormError("Name is required");
      return;
    }
    setAdded((prev) => [
      { name: form.name.trim(), role: form.role.trim() || "Contact", company: form.company.trim() || "—", warmth: 1 },
      ...prev,
    ]);
    setForm({ name: "", role: "", company: "" });
    setFormError(null);
    setShowAdd(false);
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

  const totalContacts = data.stats.contacts + added.length;
  const isEmpty = totalContacts === 0;

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
          <p className="text-lg font-semibold">No contacts yet</p>
          <p className="mt-1 text-sm text-aether-muted">
            Add your first recruiter or referral contact — or import your network.
          </p>
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="mt-4 rounded-xl border border-aether-violet/40 px-4 py-2 text-sm font-semibold text-aether-violet hover:bg-aether-violet/10"
          >
            <i className="fa-brands fa-linkedin mr-2" aria-hidden="true" />
            Import from LinkedIn
          </button>
        </div>
      ) : (
        <>
          {/* Stat tiles */}
          <section className="grid grid-cols-2 gap-4 md:grid-cols-4" data-testid="networking-stats">
            <Stat label="Contacts" value={String(totalContacts)} />
            <Stat label="Active conversations" value={String(data.stats.activeConversations)} accent="text-aether-coral" />
            <Stat label="Referrals in flight" value={String(data.stats.referralsInFlight)} accent="text-aether-violet" />
            <Stat label="Response rate" value={`${data.stats.responseRate}%`} accent="text-aether-green" />
          </section>

          <div className="grid gap-6 xl:grid-cols-3">
            {/* Contact pipeline */}
            <section className="xl:col-span-2" data-testid="contact-pipeline">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-aether-muted">
                Contact Pipeline
              </h2>
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
                {data.pipeline.map((col) => {
                  const contacts =
                    col.stage === "New" ? [...added, ...col.contacts] : col.contacts;
                  const count = col.stage === "New" ? col.count + added.length : col.count;
                  return (
                    <div key={col.stage} data-testid={`pipeline-${col.stage.toLowerCase()}`}>
                      <div className="mb-2 flex items-center justify-between px-1">
                        <div className="flex items-center gap-1.5">
                          <span className={`h-2 w-2 rounded-full ${STAGE_ACCENT[col.stage] ?? "bg-white/40"}`} />
                          <span className="text-xs font-semibold">{col.stage}</span>
                        </div>
                        <span className="mono text-[11px] text-aether-muted-dim">{count}</span>
                      </div>
                      <div className="space-y-2">
                        {contacts.map((c) => (
                          <article
                            key={`${c.name}-${c.company}`}
                            data-testid="contact-card"
                            className="glass rounded-xl border border-white/10 p-3 transition hover:border-aether-coral/40"
                          >
                            <div className="flex items-center gap-2">
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
                            <p className="mt-1.5 text-[10px] text-aether-amber" aria-label={`Warmth ${c.warmth} of 5`}>
                              {"★".repeat(c.warmth)}
                              <span className="text-white/15">{"★".repeat(Math.max(0, 5 - c.warmth))}</span>
                            </p>
                          </article>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Right column */}
            <div className="space-y-6">
              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="outreach-queue">
                <h2 className="mb-3 text-[15px] font-semibold">Outreach Queue</h2>
                <div className="space-y-3">
                  {data.outreachQueue.map((o) => (
                    <article key={o.subject} className="rounded-xl border border-white/10 bg-white/5 p-3">
                      <p className="text-xs font-semibold">{o.to}</p>
                      <p className="mt-0.5 text-xs text-aether-coral">{o.subject}</p>
                      <p className="mt-1 truncate text-[11px] text-aether-muted-dim">{o.preview}</p>
                      <span className="mono mt-1.5 inline-block rounded bg-aether-violet/15 px-1.5 py-0.5 text-[10px] text-aether-violet">
                        tone: {o.tone}
                      </span>
                    </article>
                  ))}
                </div>
                <button
                  type="button"
                  className="mt-3 w-full rounded-lg border border-white/15 py-2 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white"
                >
                  Review all drafts
                </button>
              </section>

              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="communication-log">
                <h2 className="mb-3 text-[15px] font-semibold">Communication Log</h2>
                <div className="space-y-3">
                  {data.communicationLog.map((l) => (
                    <div key={`${l.when}-${l.who}`} className="border-l-2 border-white/10 pl-3">
                      <p className="mono text-[10px] text-aether-muted-dim">
                        {l.when} · {l.channel}
                      </p>
                      <p className="text-xs">
                        <span className="font-semibold">{l.who}</span>{" "}
                        <span className="text-aether-muted">— {l.note}</span>
                      </p>
                    </div>
                  ))}
                </div>
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
          onKeyDown={(e) => {
            if (e.key === "Escape") setShowAdd(false);
          }}
        >
          <div className="glass w-full max-w-md rounded-2xl border border-white/15 bg-[#12121C] p-6" data-testid="add-contact-modal">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Add Contact</h2>
              <button type="button" onClick={() => setShowAdd(false)} className="text-aether-muted-dim hover:text-white">
                ✕
              </button>
            </div>
            <div className="space-y-3">
              <Field label="Name *" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} testId="contact-name-input" />
              <Field label="Role" value={form.role} onChange={(v) => setForm((f) => ({ ...f, role: v }))} testId="contact-role-input" />
              <Field label="Company" value={form.company} onChange={(v) => setForm((f) => ({ ...f, company: v }))} testId="contact-company-input" />
              {formError ? <p className="text-xs text-red-300">{formError}</p> : null}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAdd(false)}
                  className="rounded-lg border border-white/15 px-4 py-2 text-sm text-aether-muted hover:border-white/30"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  data-testid="save-contact-btn"
                  onClick={addContact}
                  className="rounded-lg bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
                >
                  Save Contact
                </button>
              </div>
            </div>
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
