"use client";

/**
 * Interview Center (wireframe: interview-center.html).
 *
 * Wires the real InterviewSchedule CRUD backend into the UI:
 *   GET    /interviews                 — the scheduled-interview list
 *   POST   /interviews                 — schedule a new interview
 *   POST   /interviews/{id}/complete   — status transition
 *   POST   /interviews/{id}/cancel     — status transition
 *   DELETE /interviews/{id}            — remove
 *
 * MV-interview-center-001/002/003: the screen was a static "No interview
 * scheduled" placeholder over a fully-working backend and there was no UI
 * anywhere to schedule an interview. This is the honest, functional
 * replacement — real data in, a real create affordance, real status changes.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchApplications, type Application } from "../../../lib/api/applications";
import {
  ACTIVE_INTERVIEW_STATUSES,
  cancelInterview,
  completeInterview,
  createInterview,
  deleteInterview,
  fetchInterviews,
  INTERVIEW_TYPES,
  type Interview,
  type InterviewInput,
  type InterviewStatus,
} from "../../../lib/api/interviews";

const STATUS_STYLES: Record<string, string> = {
  scheduled: "bg-aether-amber/15 text-aether-amber",
  confirmed: "bg-aether-green/15 text-aether-green",
  rescheduled: "bg-aether-yellow/15 text-aether-yellow",
  completed: "bg-aether-green/15 text-aether-green",
  cancelled: "bg-white/10 text-aether-muted-dim",
  no_show: "bg-red-500/15 text-red-300",
};

interface FormState {
  applicationId: string;
  type: string;
  scheduledAt: string;
  durationMinutes: string;
  location: string;
  meetingLink: string;
  notes: string;
  contactName: string;
  contactEmail: string;
}

const EMPTY_FORM: FormState = {
  applicationId: "",
  type: "video",
  scheduledAt: "",
  durationMinutes: "60",
  location: "",
  meetingLink: "",
  notes: "",
  contactName: "",
  contactEmail: "",
};

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Turn a form value into an InterviewInput, or throw a user-facing error. */
function buildInput(form: FormState): InterviewInput {
  if (!form.applicationId) throw new Error("Choose which application this interview is for.");
  if (!form.scheduledAt) throw new Error("Pick a date and time for the interview.");
  const when = new Date(form.scheduledAt);
  if (Number.isNaN(when.getTime())) throw new Error("That date and time is not valid.");
  const duration = Number(form.durationMinutes);
  return {
    application_id: form.applicationId,
    type: form.type as InterviewInput["type"],
    scheduled_at: when.toISOString(),
    duration_minutes: Number.isFinite(duration) && duration > 0 ? duration : 60,
    location: form.location.trim() || null,
    meeting_link: form.meetingLink.trim() || null,
    notes: form.notes.trim() || null,
    contact_name: form.contactName.trim() || null,
    contact_email: form.contactEmail.trim() || null,
  };
}

export default function InterviewCenterPage() {
  const [interviews, setInterviews] = useState<Interview[] | null>(null);
  const [apps, setApps] = useState<Application[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setInterviews(await fetchInterviews());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load interviews");
      setInterviews([]);
    }
    // Applications feed the "which application" picker and the role/company
    // labels — non-fatal if it fails (the list still renders with ids).
    try {
      setApps(await fetchApplications());
    } catch {
      /* keep last-known apps */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const appLabels = useMemo(() => {
    const map = new Map<string, { title: string; company: string }>();
    for (const a of apps) map.set(a.id, { title: a.jobTitle, company: a.company });
    return map;
  }, [apps]);

  const setField = (key: keyof FormState, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const openCreate = () => {
    setForm({ ...EMPTY_FORM, applicationId: apps[0]?.id ?? "" });
    setFormError(null);
    setCreating(true);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    let input: InterviewInput;
    try {
      input = buildInput(form);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Invalid form");
      return;
    }
    setSubmitting(true);
    try {
      await createInterview(input);
      setCreating(false);
      setForm(EMPTY_FORM);
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to schedule interview");
    } finally {
      setSubmitting(false);
    }
  };

  const runTransition = async (
    id: string,
    fn: (id: string) => Promise<Interview>,
  ) => {
    setBusyId(id);
    setError(null);
    try {
      const updated = await fn(id);
      setInterviews((prev) => (prev ?? []).map((i) => (i.id === id ? updated : i)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update interview");
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      await deleteInterview(id);
      setInterviews((prev) => (prev ?? []).filter((i) => i.id !== id));
      setConfirmDeleteId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete interview");
    } finally {
      setBusyId(null);
    }
  };

  const hasApps = apps.length > 0;

  return (
    <div className="space-y-6" data-testid="interview-center">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">Interview Center</h1>
          <p className="mt-1 text-sm text-aether-muted">
            Schedule interviews, track their status and keep your prep notes in one place.
          </p>
        </div>
        <button
          type="button"
          data-testid="schedule-interview-btn"
          onClick={openCreate}
          className="flex min-h-[44px] items-center gap-2 rounded-xl bg-aether-coral px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-aether-coral/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50"
        >
          <i className="fa-solid fa-plus" aria-hidden="true" />
          Schedule interview
        </button>
      </header>

      {error ? (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3">
          <p role="alert" className="text-sm text-red-300">
            {error}
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-red-400/40 px-3 py-1.5 text-xs font-semibold text-red-200 transition hover:bg-red-500/20 max-sm:min-h-[44px]"
          >
            Retry
          </button>
        </div>
      ) : null}

      {creating ? (
        <section
          className="glass rounded-2xl border border-aether-coral/30 p-5"
          data-testid="schedule-interview-panel"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
              Schedule an interview
            </h2>
            <button
              type="button"
              onClick={() => setCreating(false)}
              aria-label="Close schedule form"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-aether-muted-dim transition hover:bg-white/10 hover:text-white"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true" />
            </button>
          </div>

          {!hasApps ? (
            <p className="rounded-xl border border-aether-amber/30 bg-aether-amber/10 p-3 text-sm text-aether-amber">
              You need an application first. An interview is always tied to one of your
              applications —{" "}
              <Link href="/dashboard/applications" className="underline">
                go to Applications
              </Link>{" "}
              to add one.
            </p>
          ) : (
            <form onSubmit={submit} data-testid="schedule-interview-form" className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-aether-muted">
                    Application *
                  </span>
                  <select
                    data-testid="interview-application-select"
                    value={form.applicationId}
                    onChange={(e) => setField("applicationId", e.target.value)}
                    required
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  >
                    <option value="">Select an application…</option>
                    {apps.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.jobTitle} · {a.company}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-aether-muted">Type</span>
                  <select
                    data-testid="interview-type-select"
                    value={form.type}
                    onChange={(e) => setField("type", e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  >
                    {INTERVIEW_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-aether-muted">
                    Date &amp; time *
                  </span>
                  <input
                    type="datetime-local"
                    data-testid="interview-scheduled-at"
                    value={form.scheduledAt}
                    onChange={(e) => setField("scheduledAt", e.target.value)}
                    required
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  />
                </label>

                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-aether-muted">
                    Duration (minutes)
                  </span>
                  <input
                    type="number"
                    min={15}
                    max={480}
                    data-testid="interview-duration"
                    value={form.durationMinutes}
                    onChange={(e) => setField("durationMinutes", e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  />
                </label>

                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-aether-muted">Location</span>
                  <input
                    type="text"
                    value={form.location}
                    onChange={(e) => setField("location", e.target.value)}
                    placeholder="e.g. Level 4, 55 Collins St — or leave blank"
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  />
                </label>

                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-aether-muted">
                    Meeting link
                  </span>
                  <input
                    type="url"
                    value={form.meetingLink}
                    onChange={(e) => setField("meetingLink", e.target.value)}
                    placeholder="https://…"
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  />
                </label>

                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-aether-muted">
                    Contact name
                  </span>
                  <input
                    type="text"
                    value={form.contactName}
                    onChange={(e) => setField("contactName", e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  />
                </label>

                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-aether-muted">
                    Contact email
                  </span>
                  <input
                    type="email"
                    value={form.contactEmail}
                    onChange={(e) => setField("contactEmail", e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  />
                </label>
              </div>

              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-aether-muted">
                  Prep notes
                </span>
                <textarea
                  rows={3}
                  value={form.notes}
                  onChange={(e) => setField("notes", e.target.value)}
                  placeholder="Predicted questions, stories to tell, things to research…"
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm"
                />
              </label>

              {formError ? (
                <p role="alert" className="text-sm text-red-300" data-testid="interview-form-error">
                  {formError}
                </p>
              ) : null}

              <div className="flex items-center gap-2">
                <button
                  type="submit"
                  data-testid="interview-submit-btn"
                  disabled={submitting}
                  className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white transition hover:bg-aether-coral/80 disabled:opacity-50"
                >
                  {submitting ? "Scheduling…" : "Schedule interview"}
                </button>
                <button
                  type="button"
                  onClick={() => setCreating(false)}
                  className="rounded-xl border border-white/10 px-4 py-2 text-sm font-medium text-aether-muted transition hover:bg-white/5"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </section>
      ) : null}

      {interviews === null ? (
        <div className="space-y-4" aria-busy="true" data-testid="interviews-loading">
          {[0, 1].map((i) => (
            <div key={i} className="glass h-32 animate-pulse rounded-2xl border border-white/10" />
          ))}
        </div>
      ) : interviews.length === 0 ? (
        <div
          className="glass rounded-2xl border border-white/10 p-8 text-center"
          data-testid="interviews-empty-state"
        >
          <i className="fa-solid fa-calendar-check text-3xl text-aether-muted-dim" aria-hidden="true" />
          <p className="mt-3 text-sm text-aether-muted">No interviews scheduled yet.</p>
          <p className="mt-1 text-xs text-aether-muted-dim">
            Schedule your first interview to keep prep, timing and status in one place.
          </p>
          <button
            type="button"
            onClick={openCreate}
            className="mt-4 inline-flex items-center gap-2 rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white transition hover:bg-aether-coral/80"
          >
            <i className="fa-solid fa-plus" aria-hidden="true" />
            Schedule interview
          </button>
        </div>
      ) : (
        <div className="space-y-4" data-testid="interview-list">
          {interviews.map((iv) => {
            const label = iv.application_id ? appLabels.get(iv.application_id) : undefined;
            const active = ACTIVE_INTERVIEW_STATUSES.includes(iv.status as InterviewStatus);
            const busy = busyId === iv.id;
            return (
              <article
                key={iv.id}
                data-testid="interview-card"
                className="glass rounded-2xl border border-white/10 p-5"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-base font-semibold">
                      {label ? (
                        <>
                          {label.title}{" "}
                          <span className="text-aether-muted">@ {label.company}</span>
                        </>
                      ) : (
                        <span className="text-aether-muted">
                          Application {iv.application_id ?? "—"}
                        </span>
                      )}
                    </h3>
                    <p className="mono mt-1 text-xs text-aether-muted-dim">
                      {formatWhen(iv.scheduled_at)} · {iv.duration_minutes} min · {iv.type}
                    </p>
                  </div>
                  <span
                    data-testid="interview-status"
                    className={`inline-block rounded-md px-2.5 py-1 text-xs font-medium capitalize ${
                      STATUS_STYLES[iv.status] ?? "bg-white/10 text-aether-muted"
                    }`}
                  >
                    {iv.status.replace("_", " ")}
                  </span>
                </div>

                {(iv.location || iv.meeting_link || iv.contact_name || iv.contact_email) ? (
                  <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-aether-muted">
                    {iv.location ? (
                      <span>
                        <i className="fa-solid fa-location-dot mr-1.5" aria-hidden="true" />
                        {iv.location}
                      </span>
                    ) : null}
                    {iv.meeting_link ? (
                      <a
                        href={iv.meeting_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-aether-coral underline"
                      >
                        <i className="fa-solid fa-video mr-1.5" aria-hidden="true" />
                        Join link
                      </a>
                    ) : null}
                    {iv.contact_name ? (
                      <span>
                        <i className="fa-solid fa-user mr-1.5" aria-hidden="true" />
                        {iv.contact_name}
                        {iv.contact_email ? ` · ${iv.contact_email}` : ""}
                      </span>
                    ) : null}
                  </div>
                ) : null}

                {iv.notes ? (
                  <div className="mt-3 rounded-lg border border-white/10 bg-white/5 p-3">
                    <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-aether-muted">
                      Prep notes
                    </h4>
                    <p className="whitespace-pre-line text-sm text-aether-muted">{iv.notes}</p>
                  </div>
                ) : null}

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {active ? (
                    <>
                      <button
                        type="button"
                        data-testid="interview-complete-btn"
                        onClick={() => void runTransition(iv.id, completeInterview)}
                        disabled={busy}
                        className="rounded-lg border border-aether-green/40 px-3 py-1.5 text-xs font-semibold text-aether-green transition hover:bg-aether-green/10 disabled:opacity-50 max-sm:min-h-[44px]"
                      >
                        Mark complete
                      </button>
                      <button
                        type="button"
                        data-testid="interview-cancel-btn"
                        onClick={() => void runTransition(iv.id, cancelInterview)}
                        disabled={busy}
                        className="rounded-lg border border-white/15 px-3 py-1.5 text-xs font-semibold text-aether-muted transition hover:bg-white/5 disabled:opacity-50 max-sm:min-h-[44px]"
                      >
                        Cancel interview
                      </button>
                    </>
                  ) : null}
                  {confirmDeleteId === iv.id ? (
                    <>
                      <button
                        type="button"
                        data-testid="interview-confirm-delete-btn"
                        onClick={() => void remove(iv.id)}
                        disabled={busy}
                        className="rounded-lg border border-red-400/40 px-3 py-1.5 text-xs font-semibold text-red-200 transition hover:bg-red-500/20 disabled:opacity-50 max-sm:min-h-[44px]"
                      >
                        Confirm delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(null)}
                        className="rounded-lg px-3 py-1.5 text-xs font-medium text-aether-muted transition hover:text-white max-sm:min-h-[44px]"
                      >
                        Keep
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      data-testid="interview-delete-btn"
                      onClick={() => setConfirmDeleteId(iv.id)}
                      disabled={busy}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-aether-muted-dim transition hover:text-red-300 disabled:opacity-50 max-sm:min-h-[44px]"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
