"use client";

/**
 * Interview Center — deferred to Phase 3+ (wireframe: interview-center.html).
 * No backend routes exist yet; placeholder shown until data is populated.
 */

export default function InterviewCenterPage() {
  return (
    <div className="space-y-6" data-testid="interview-center">
      <header>
        <h1 className="text-2xl font-bold">Interview Center</h1>
        <p className="text-sm text-aether-muted">Prep briefs · Live Assist · Debrief</p>
      </header>
      <div className="glass rounded-2xl border border-white/10 p-8 text-center">
        <i className="fa-solid fa-calendar-check text-3xl text-aether-muted-dim" aria-hidden="true" />
        <p className="mt-3 text-sm text-aether-muted">No interview scheduled.</p>
        <p className="mt-1 text-xs text-aether-muted-dim">
          Once an application progresses to interview stage, your prep brief appears here.
        </p>
        <a
          href="/dashboard/applications"
          className="mt-4 inline-block rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white transition hover:bg-aether-coral/80"
        >
          View Applications
        </a>
      </div>
    </div>
  );
}
