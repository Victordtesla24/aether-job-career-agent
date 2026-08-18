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
 *
 * ML-W4B-OBS-1: also renders the Interview Prep brief
 * (GET /workspaces/interviews/prep) whenever an application is at the
 * interview stage — real predicted questions with story-grounded STAR+R
 * answer sketches, the honest "no matching story" state, the questionsNote
 * when the only brief on file belongs to another job, and an honest empty
 * state with a Run affordance (POST /agents/interviewPrep/run) when no prep
 * brief exists yet. That backend endpoint has worked end-to-end since
 * wave-4B, but until this fix no shipped frontend file ever requested it.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchApplications, type Application } from "../../../lib/api/applications";
import { runAgent } from "../../../lib/api/agents";
import { useRealtimeResources } from "../../../hooks/useRealtime";
import {
  ACTIVE_INTERVIEW_STATUSES,
  assembleInterviewPack,
  cancelInterview,
  completeInterview,
  createInterview,
  deleteInterview,
  downloadInterviewPack,
  downloadInterviewPackFile,
  fetchInterviewPrep,
  fetchInterviews,
  INTERVIEW_TYPES,
  type CalendarResult,
  type Interview,
  type InterviewInput,
  type InterviewPrepBrief,
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
  return d.toLocaleString("en-AU", {
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
  // W-CAL: what the backend reported about the Google Calendar write for the
  // interview that was just scheduled. Rendered verbatim — this banner never
  // says an event was created unless `status === "created"`, which the backend
  // sets only when Google returned a real event id.
  const [calendarNotice, setCalendarNotice] = useState<CalendarResult | null>(null);

  // Interview Prep brief — fetched when an application is at interview
  // stage or when InterviewSchedule rows already exist (a mailbox ingest
  // can land a schedule before GET /applications reflects the promotion).
  const [prep, setPrep] = useState<InterviewPrepBrief | null>(null);
  const [prepLoading, setPrepLoading] = useState(false);
  const [prepError, setPrepError] = useState<string | null>(null);
  const [prepRunning, setPrepRunning] = useState(false);
  const [prepRunError, setPrepRunError] = useState<string | null>(null);
  const [packBusy, setPackBusy] = useState(false);
  const [packError, setPackError] = useState<string | null>(null);

  const loadPrep = useCallback(async () => {
    setPrepLoading(true);
    setPrepError(null);
    try {
      setPrep(await fetchInterviewPrep());
    } catch (e) {
      setPrepError(e instanceof Error ? e.message : "Failed to load interview prep");
      setPrep(null);
    } finally {
      setPrepLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    let listed: Interview[] = [];
    try {
      listed = await fetchInterviews();
      setInterviews(listed);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load interviews");
      listed = [];
      setInterviews([]);
    }
    // Applications feed the "which application" picker, the role/company
    // labels, AND whether an interview-stage prep brief should be fetched —
    // non-fatal if it fails (the list still renders with ids, prep state
    // holds whatever it last was).
    try {
      const fetchedApps = await fetchApplications();
      setApps(fetchedApps);
      if (
        fetchedApps.some((a) => a.status === "interview") ||
        listed.length > 0
      ) {
        await loadPrep();
      } else {
        setPrep(null);
        setPrepError(null);
      }
    } catch {
      /* keep last-known apps and prep state */
    }
  }, [loadPrep]);

  useEffect(() => {
    void load();
  }, [load]);

  // W-RT — the shared realtime channel. This screen used to fetch ONCE on
  // mount. It renders scheduled interviews plus the interview-stage
  // applications that gate the prep panel, so both are subscribed: an interview
  // booked by the calendar path, or an application advanced to `interview` by an
  // agent, now shows up without a manual reload.
  useRealtimeResources(["interviews", "applications"], () => {
    void load();
  });

  const appLabels = useMemo(() => {
    const map = new Map<string, { title: string; company: string }>();
    for (const a of apps) map.set(a.id, { title: a.jobTitle, company: a.company });
    return map;
  }, [apps]);

  // Same signal `load()` uses to decide whether to fetch the prep brief —
  // gates whether the panel renders at all.
  const atInterviewStage = useMemo(
    () =>
      apps.some((a) => a.status === "interview") ||
      (interviews !== null && interviews.length > 0),
    [apps, interviews],
  );

  const runPrep = useCallback(async () => {
    setPrepRunning(true);
    setPrepRunError(null);
    try {
      // No job_id: the agent preps for the caller's most recent
      // interview-stage application, exactly the one this panel renders.
      await runAgent("interviewPrep", {});
      try {
        await assembleInterviewPack({ jobId: apps.find((a) => a.status === "interview")?.jobId });
      } catch (packErr) {
        setPackError(
          packErr instanceof Error
            ? packErr.message
            : "Interview Prep ran; the folder could not be assembled.",
        );
      }
      await loadPrep();
    } catch (e) {
      setPrepRunError(e instanceof Error ? e.message : "Failed to run Interview Prep");
    } finally {
      setPrepRunning(false);
    }
  }, [loadPrep, apps]);

  const runPack = useCallback(
    async (runMissing = false) => {
      setPackBusy(true);
      setPackError(null);
      try {
        await assembleInterviewPack({
          jobId: prep?.session?.jobId ?? apps.find((a) => a.status === "interview")?.jobId,
          runMissing,
        });
        await loadPrep();
      } catch (e) {
        setPackError(e instanceof Error ? e.message : "Failed to assemble the interview folder");
      } finally {
        setPackBusy(false);
      }
    },
    [apps, loadPrep, prep?.session?.jobId],
  );

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
      const created = await createInterview(input);
      // Report EXACTLY what the backend said about the calendar — including
      // "nothing was written". A backend that sent no calendar block at all
      // gets no banner rather than an assumed success.
      setCalendarNotice(created.calendar ?? null);
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

      {calendarNotice ? (
        <div
          data-testid={`interview-calendar-notice-${calendarNotice.status}`}
          className={`flex items-start justify-between gap-3 rounded-xl border p-3 ${
            calendarNotice.status === "created"
              ? "border-aether-green/30 bg-aether-green/10"
              : "border-aether-amber/30 bg-aether-amber/10"
          }`}
        >
          <div className="space-y-1">
            <p
              className={`text-sm ${
                calendarNotice.status === "created"
                  ? "text-aether-green"
                  : "text-aether-amber"
              }`}
              role={calendarNotice.status === "created" ? undefined : "alert"}
            >
              {calendarNotice.message}
            </p>
            {calendarNotice.status === "created" && calendarNotice.html_link ? (
              <a
                href={calendarNotice.html_link}
                target="_blank"
                rel="noreferrer noopener"
                className="text-xs font-semibold underline"
                data-testid="interview-calendar-event-link"
              >
                Open the event in Google Calendar
              </a>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => setCalendarNotice(null)}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-xs font-semibold transition hover:bg-white/10 max-sm:min-h-[44px]"
          >
            Dismiss
          </button>
        </div>
      ) : null}

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

      {atInterviewStage ? (
        <section
          className="bg-surface-1 rounded-[14px] border border-white/10 p-5"
          data-testid="interview-prep-panel"
        >
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted">
                Interview Prep
              </h2>
              {prep?.session ? (
                <>
                  <p className="mt-1 text-base font-semibold text-white">
                    {prep.session.role}{" "}
                    <span className="text-aether-muted">@ {prep.session.company}</span>
                  </p>
                  <p
                    className="mt-1 font-mono text-xs text-aether-muted-dim"
                    data-testid="interview-prep-session-meta"
                  >
                    {prep.session.format}
                    {prep.session.scheduledFor
                      ? ` · ${formatWhen(prep.session.scheduledFor)}`
                      : " · time not measured"}
                    {prep.session.location ? ` · ${prep.session.location}` : ""}
                  </p>
                </>
              ) : null}
            </div>
            <button
              type="button"
              data-testid="interview-prep-run-btn"
              onClick={() => void runPrep()}
              disabled={prepRunning}
              className="flex min-h-[36px] items-center gap-2 rounded-lg border border-aether-coral/40 px-3 py-1.5 text-xs font-semibold text-aether-coral transition hover:bg-aether-coral/10 disabled:opacity-50"
            >
              <i className="fa-solid fa-wand-magic-sparkles" aria-hidden="true" />
              {prepRunning ? "Running…" : "Run Interview Prep"}
            </button>
          </div>

          {prepRunError ? (
            <p
              role="alert"
              data-testid="interview-prep-run-error"
              className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
            >
              {prepRunError}
            </p>
          ) : null}

          {prepLoading && prep === null ? (
            <div
              className="bg-surface-1 h-24 animate-pulse rounded-xl border border-white/10"
              aria-busy="true"
              data-testid="interview-prep-loading"
            />
          ) : prepError ? (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3">
              <p role="alert" className="text-sm text-red-300" data-testid="interview-prep-error">
                {prepError}
              </p>
              <button
                type="button"
                onClick={() => void loadPrep()}
                className="rounded-lg border border-red-400/40 px-3 py-1.5 text-xs font-semibold text-red-200 transition hover:bg-red-500/20 max-sm:min-h-[44px]"
              >
                Retry
              </button>
            </div>
          ) : prep ? (
            <>
              {prep.questionsNote ? (
                <p
                  data-testid="interview-prep-questions-note"
                  className="mb-4 rounded-xl border border-aether-amber/30 bg-aether-amber/10 p-3 text-sm text-aether-amber"
                >
                  {prep.questionsNote}
                </p>
              ) : null}

              <InterviewPackFolder
                prep={prep}
                busy={packBusy}
                error={packError}
                onAssemble={() => void runPack(false)}
                onAssembleMissing={() => void runPack(true)}
              />

              {prep.briefing ? <InterviewBriefing briefing={prep.briefing} /> : null}

              {prep.questions.length === 0 ? (
                <div
                  className="rounded-xl border border-white/10 bg-white/5 p-6 text-center"
                  data-testid="interview-prep-empty"
                >
                  <i
                    className="fa-solid fa-comments text-2xl text-aether-muted-dim"
                    aria-hidden="true"
                  />
                  <p className="mt-2 text-sm text-aether-muted">
                    {prep.questionsNote
                      ? "Run Interview Prep for this job to get its own predicted questions and answer sketches."
                      : "No prep brief yet — run the Interview Prep agent to get predicted questions and STAR+R answer sketches for this interview."}
                  </p>
                </div>
              ) : (
                <div className="space-y-3" data-testid="interview-prep-questions">
                  {prep.questions.map((q, i) => (
                    <article
                      key={i}
                      data-testid="interview-prep-question"
                      className="rounded-xl border border-white/10 bg-white/5 p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-sm font-medium text-white">{q.question}</p>
                        {q.category ? (
                          <span className="shrink-0 rounded-md bg-white/10 px-2 py-0.5 text-[11px] font-medium capitalize text-aether-muted">
                            {q.category}
                          </span>
                        ) : null}
                      </div>

                      {q.whyAsked ? (
                        <p className="mt-2 text-xs text-aether-muted-dim">
                          <i className="fa-solid fa-circle-info mr-1.5" aria-hidden="true" />
                          {q.whyAsked}
                        </p>
                      ) : null}

                      {q.answerSketch ? (
                        <div
                          className="mt-3 rounded-lg border border-aether-green/20 bg-aether-green/5 p-3"
                          data-testid="interview-prep-answer-sketch"
                        >
                          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                            <span className="text-[11px] font-semibold uppercase tracking-wide text-aether-green">
                              STAR+R answer sketch
                            </span>
                            {q.suggestedStoryTitle ? (
                              <Link
                                href="/dashboard/stories"
                                data-testid="interview-prep-story-link"
                                className="text-[11px] text-aether-coral underline"
                              >
                                From: {q.suggestedStoryTitle}
                              </Link>
                            ) : null}
                          </div>
                          <dl className="space-y-1.5 text-xs text-aether-muted">
                            <div>
                              <dt className="inline font-semibold text-aether-muted-dim">
                                Situation:{" "}
                              </dt>
                              <dd className="m-0 inline">{q.answerSketch.situation}</dd>
                            </div>
                            <div>
                              <dt className="inline font-semibold text-aether-muted-dim">
                                Task:{" "}
                              </dt>
                              <dd className="m-0 inline">{q.answerSketch.task}</dd>
                            </div>
                            <div>
                              <dt className="inline font-semibold text-aether-muted-dim">
                                Action:{" "}
                              </dt>
                              <dd className="m-0 inline">{q.answerSketch.action}</dd>
                            </div>
                            <div>
                              <dt className="inline font-semibold text-aether-muted-dim">
                                Result:{" "}
                              </dt>
                              <dd className="m-0 inline">{q.answerSketch.result}</dd>
                            </div>
                            <div>
                              <dt className="inline font-semibold text-aether-muted-dim">
                                Reflection:{" "}
                              </dt>
                              <dd className="m-0 inline">{q.answerSketch.reflection}</dd>
                            </div>
                          </dl>
                        </div>
                      ) : (
                        <p
                          className="mt-3 rounded-lg border border-aether-amber/20 bg-aether-amber/5 p-3 text-xs text-aether-amber"
                          data-testid="interview-prep-no-story"
                        >
                          <i
                            className="fa-solid fa-triangle-exclamation mr-1.5"
                            aria-hidden="true"
                          />
                          {q.preparationNote ??
                            "No matching story — prepare one before the interview."}
                        </p>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </>
          ) : null}
        </section>
      ) : null}

      {creating ? (
        <section
          className="bg-surface-1 rounded-[14px] border border-aether-coral/30 p-5"
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
            <div key={i} className="bg-surface-1 h-32 animate-pulse rounded-[14px] border border-white/10" />
          ))}
        </div>
      ) : interviews.length === 0 ? (
        <div
          className="bg-surface-1 rounded-[14px] border border-white/10 p-8 text-center"
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
                className="bg-surface-1 rounded-[14px] border border-white/10 p-5"
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

function InterviewPackFolder({
  prep,
  busy,
  error,
  onAssemble,
  onAssembleMissing,
}: {
  prep: InterviewPrepBrief;
  busy: boolean;
  error: string | null;
  onAssemble: () => void;
  onAssembleMissing: () => void;
}) {
  const pack = prep.pack;
  const jobId = prep.session?.jobId;
  const files = pack?.files ?? [];
  const gaps = pack?.gaps ?? [];
  return (
    <section
      className="mb-5 overflow-hidden rounded-xl border border-gold/25 bg-surface-2/40"
      data-testid="interview-pack-folder"
    >
      <div className="h-[3px] bg-gold" aria-hidden="true" />
      <div className="p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-xs font-semibold uppercase tracking-[0.18em] text-gold">
            Interview folder
          </h3>
          <p className="mt-1 text-sm text-aether-muted">
            {pack?.folder
              ? pack.folder
              : "Orchestrator assembles the gilt prep brief, four-slide deck, tailored résumé and cover letter."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="interview-pack-assemble-btn"
            onClick={onAssemble}
            disabled={busy}
            className="rounded-lg bg-gold px-3 py-1.5 text-xs font-semibold text-aether-bg transition hover:bg-gold-light disabled:opacity-50"
          >
            {busy ? "Assembling…" : pack ? "Refresh folder" : "Assemble folder"}
          </button>
          {jobId && files.length > 0 ? (
            <button
              type="button"
              data-testid="interview-pack-download-zip-btn"
              onClick={() => void downloadInterviewPack(jobId)}
              className="rounded-lg border border-gold/40 px-3 py-1.5 text-xs font-semibold text-gold transition hover:bg-gold/10"
            >
              Download zip
            </button>
          ) : null}
        </div>
      </div>
      {error ? (
        <p role="alert" className="mb-3 text-sm text-red-300" data-testid="interview-pack-error">
          {error}
        </p>
      ) : null}
      {pack?.plan && pack.plan.length > 0 ? (
        <p className="mb-3 text-[11px] uppercase tracking-[0.12em] text-aether-muted-dim">
          Plan: {pack.plan.join(" → ")}
        </p>
      ) : null}
      {files.length > 0 ? (
        <ul className="space-y-2" data-testid="interview-pack-files">
          {files.map((file) => (
            <li
              key={file.name}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-surface-1 px-3 py-2"
              data-testid="interview-pack-file"
            >
              <div className="min-w-0">
                <p className="truncate text-sm text-aether-text">{file.name}</p>
                <p className="text-[11px] text-aether-muted-dim">
                  {file.branded ? "Aether-branded" : "Employer-facing"}
                  {file.agent ? ` · ${file.agent}` : ""}
                  {file.note ? ` · ${file.note}` : ""}
                </p>
              </div>
              {jobId ? (
                <button
                  type="button"
                  onClick={() => void downloadInterviewPackFile(jobId, file.name)}
                  className="shrink-0 text-xs font-semibold text-gold underline"
                >
                  Open
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-aether-muted" data-testid="interview-pack-empty">
          No folder on file yet. Assemble it to take the brief, slides and documents to the interview.
        </p>
      )}
      {gaps.length > 0 ? (
        <div className="mt-3 space-y-2" data-testid="interview-pack-gaps">
          {gaps.map((gap) => (
            <p key={gap} className="text-xs text-aether-amber">
              {gap}
            </p>
          ))}
          <button
            type="button"
            data-testid="interview-pack-fill-missing-btn"
            onClick={onAssembleMissing}
            disabled={busy}
            className="rounded-lg border border-aether-amber/40 px-3 py-1.5 text-xs font-semibold text-aether-amber transition hover:bg-aether-amber/10 disabled:opacity-50"
          >
            Run Tailor and Cover Letter for missing files
          </button>
        </div>
      ) : null}
      </div>
    </section>
  );
}

function InterviewBriefing({
  briefing,
}: {
  briefing: NonNullable<InterviewPrepBrief["briefing"]>;
}) {
  const traps = briefing.traps ?? [];
  const ask = briefing.questionsToAsk ?? [];
  const guidelines = briefing.guidelines ?? [];
  const logistics = briefing.logistics ?? [];
  const companyNotes = briefing.companyNotes ?? [];
  const interviewerNotes = briefing.interviewerNotes ?? [];
  const closing = briefing.closing ?? [];
  const card = (title: string, lines: string[], testId?: string) =>
    lines.length === 0 ? null : (
      <article
        className="rounded-xl border border-white/10 bg-white/5 p-4"
        data-testid={testId}
      >
        <h3 className="font-display text-xs font-semibold uppercase tracking-[0.12em] text-gold">
          {title}
        </h3>
        <ul className="mt-2 space-y-1 text-sm text-aether-text">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </article>
    );
  return (
    <div className="mb-5 grid gap-3 sm:grid-cols-2" data-testid="interview-prep-briefing">
      {card("Logistics", logistics)}
      {traps.length > 0 ? (
        <article className="rounded-xl border border-aether-amber/25 bg-aether-amber/5 p-4">
          <h3 className="font-display text-xs font-semibold uppercase tracking-[0.12em] text-aether-amber">
            Traps to avoid
          </h3>
          <ul className="mt-2 space-y-2 text-sm text-aether-text">
            {traps.map((trap) => (
              <li key={trap.title}>
                <span className="font-semibold">{trap.title}.</span> {trap.detail}
              </li>
            ))}
          </ul>
        </article>
      ) : null}
      {card("Company (your own postings)", companyNotes, "interview-prep-company-notes")}
      {card("Interviewer", interviewerNotes, "interview-prep-interviewer-notes")}
      {card("Guidelines", guidelines)}
      {card("Questions to ask", ask)}
      {card("Close", closing)}
    </div>
  );
}
