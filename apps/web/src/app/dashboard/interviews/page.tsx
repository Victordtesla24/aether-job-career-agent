"use client";

/**
 * Interview Center — prep brief, predicted questions, Live Assist preview and
 * last debrief, backed by GET /interviews/prep (wireframe: interview-center.html).
 */
import { useEffect, useState } from "react";

import { fetchInterviewPrep, type InterviewPrep } from "../../../lib/api/workspaces";

const TABS = ["Prep", "Live Assist", "Debrief"] as const;
type Tab = (typeof TABS)[number];

const LIKELIHOOD_STYLE: Record<string, string> = {
  High: "bg-aether-green/15 text-aether-green border-aether-green/25",
  Medium: "bg-aether-amber/15 text-aether-amber border-aether-amber/25",
  Low: "bg-white/5 text-aether-muted border-white/10",
};

export default function InterviewCenterPage() {
  const [prep, setPrep] = useState<InterviewPrep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Prep");
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [muted, setMuted] = useState(true);

  useEffect(() => {
    fetchInterviewPrep()
      .then(setPrep)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load interview prep"));
  }, []);

  if (error) {
    return (
      <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>
    );
  }

  if (prep === null || prep.session === null) {
    return (
      <div className="space-y-6" data-testid="interview-center">
        <header><h1 className="text-2xl font-bold">Interview Center</h1></header>
        <div className="glass rounded-2xl border border-white/10 p-8 text-center">
          <i className="fa-solid fa-calendar-check text-3xl text-aether-muted-dim" aria-hidden="true" />
          <p className="mt-3 text-sm text-aether-muted">{prep?.compliance?.message ?? "No interview scheduled."}</p>
          <p className="mt-1 text-xs text-aether-muted-dim">Once an application progresses to interview stage, your prep brief appears here.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="interview-center">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Interview Center</h1>
          <p className="text-sm text-aether-muted">
            {prep.session.role} · {prep.session.company} — {prep.session.round}
          </p>
          <p className="mono mt-1 text-xs text-aether-muted-dim">
            {new Date(prep.session.scheduledFor).toLocaleString()} · {prep.session.format}
          </p>
        </div>
        <nav className="glass flex rounded-xl border border-white/10 p-1" aria-label="Interview tabs">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              data-testid={`interview-tab-${t.toLowerCase().replace(" ", "-")}`}
              onClick={() => setTab(t)}
              aria-pressed={tab === t}
              className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${
                tab === t ? "bg-aether-coral text-white" : "text-aether-muted hover:text-white"
              }`}
            >
              {t}
            </button>
          ))}
        </nav>
      </header>

      {/* Compliance banner */}
      {!bannerDismissed ? (
        <div
          data-testid="compliance-banner"
          className="flex items-start justify-between gap-3 rounded-xl border border-aether-amber/40 bg-aether-amber/10 p-3 text-sm text-aether-amber"
        >
          <p>
            <i className="fa-solid fa-shield-halved mr-2" aria-hidden="true" />
            {prep.compliance.message}
          </p>
          <button
            type="button"
            onClick={() => setBannerDismissed(true)}
            className="shrink-0 text-xs text-aether-amber/70 hover:text-aether-amber"
            title="Dismiss"
          >
            ✕
          </button>
        </div>
      ) : null}

      {tab === "Prep" ? (
        <div className="grid gap-6 xl:grid-cols-3">
          <div className="space-y-6 xl:col-span-2">
            {/* Company & Role brief */}
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="role-brief">
              <h2 className="mb-4 text-[15px] font-semibold">Company &amp; Role Brief</h2>
              <div className="grid gap-4 md:grid-cols-3">
                {prep.brief.columns.map((col) => (
                  <div key={col.title} className="rounded-xl border border-white/10 bg-white/5 p-4">
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-aether-muted-dim">
                      {col.title}
                    </h3>
                    <ul className="space-y-1.5 text-xs text-aether-muted">
                      {col.items.map((item) => (
                        <li key={item} className="flex items-start gap-1.5">
                          <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-aether-coral" />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
              <p className="mt-4 rounded-xl border border-aether-violet/30 bg-aether-violet/10 p-3 text-xs text-aether-muted">
                <i className="fa-solid fa-lightbulb mr-2 text-aether-violet" aria-hidden="true" />
                {prep.brief.insight}
              </p>
            </section>

            {/* Predicted questions */}
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="predicted-questions">
              <h2 className="mb-4 text-[15px] font-semibold">Predicted Questions</h2>
              <div className="space-y-3">
                {prep.questions.map((q) => (
                  <article key={q.question} className="rounded-xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-sm font-semibold leading-snug">{q.question}</h3>
                      <span
                        className={`shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-medium ${LIKELIHOOD_STYLE[q.likelihood]}`}
                      >
                        {q.likelihood} likelihood
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-aether-muted">
                      <span className="text-aether-muted-dim">Mapped story:</span>{" "}
                      <span className="text-aether-coral">{q.mappedStory}</span>
                    </p>
                    <p className="mt-1 text-xs text-aether-muted-dim">{q.angle}</p>
                  </article>
                ))}
              </div>
            </section>
          </div>

          {/* Right column mirrors Live Assist preview + last debrief */}
          <div className="space-y-6">
            <LiveAssistCard prep={prep} muted={muted} onToggleMute={() => setMuted((m) => !m)} compact />
            <DebriefCard prep={prep} />
          </div>
        </div>
      ) : null}

      {tab === "Live Assist" ? (
        <LiveAssistCard prep={prep} muted={muted} onToggleMute={() => setMuted((m) => !m)} />
      ) : null}

      {tab === "Debrief" ? <DebriefCard prep={prep} full /> : null}
    </div>
  );
}

function LiveAssistCard({
  prep,
  muted,
  onToggleMute,
  compact = false,
}: {
  prep: InterviewPrep;
  muted: boolean;
  onToggleMute: () => void;
  compact?: boolean;
}) {
  const { liveAssist } = prep;
  return (
    <section
      className={`glass rounded-2xl border border-white/10 p-5 ${compact ? "" : "max-w-2xl"}`}
      data-testid="live-assist"
    >
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${muted ? "bg-aether-muted-dim" : "bg-aether-green live-dot"}`} />
          <h2 className="text-[15px] font-semibold">Live Assist</h2>
          <span className="mono text-[11px] text-aether-muted-dim">{muted ? "standby" : "listening"}</span>
        </div>
        <button
          type="button"
          data-testid="mute-toggle"
          onClick={onToggleMute}
          aria-pressed={muted}
          className={`rounded-lg border px-3 py-1 text-xs font-semibold transition ${
            muted
              ? "border-white/15 text-aether-muted hover:border-white/30"
              : "border-aether-green/40 text-aether-green"
          }`}
        >
          {muted ? "🔇 Muted — click to enable" : "🎙 Live — click to mute"}
        </button>
      </div>
      {muted ? (
        <p className="mb-3 rounded-lg border border-white/10 bg-white/5 p-2.5 text-xs text-aether-muted-dim" data-testid="muted-notice">
          Live Assist muted — no audio is being captured or analysed.
        </p>
      ) : null}
      <div className="grid grid-cols-3 gap-3">
        <Metric label="Filler words" value={`${liveAssist.fillerWordsPerMin}/min`} />
        <Metric label="Pace" value={`${liveAssist.wordsPerMin} wpm`} />
        <Metric
          label="Talk / Listen"
          value={`${liveAssist.talkListenRatio.talk}/${liveAssist.talkListenRatio.listen}`}
        />
      </div>
      <p className="mt-4 rounded-xl border border-aether-coral/30 bg-aether-coral/10 p-3 text-xs text-aether-muted">
        <i className="fa-solid fa-comment-dots mr-2 text-aether-coral" aria-hidden="true" />
        {liveAssist.coachingCue}
      </p>
    </section>
  );
}

function DebriefCard({ prep, full = false }: { prep: InterviewPrep; full?: boolean }) {
  const { debrief } = prep;
  return (
    <section
      className={`glass rounded-2xl border border-white/10 p-5 ${full ? "max-w-2xl" : ""}`}
      data-testid="last-debrief"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[15px] font-semibold">Last Debrief</h2>
        <span className="mono text-lg font-bold text-aether-green">{debrief.score.toFixed(1)}</span>
      </div>
      <p className="text-xs text-aether-muted">
        {debrief.company} · {debrief.round}
      </p>
      <div className="mt-3 space-y-1.5">
        {debrief.strengths.map((s) => (
          <p key={s} className="flex items-start gap-2 text-xs text-aether-muted">
            <i className="fa-solid fa-circle-check mt-0.5 text-aether-green" aria-hidden="true" />
            {s}
          </p>
        ))}
        {debrief.warnings.map((w) => (
          <p key={w} className="flex items-start gap-2 text-xs text-aether-muted">
            <i className="fa-solid fa-triangle-exclamation mt-0.5 text-aether-amber" aria-hidden="true" />
            {w}
          </p>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-center">
      <div className="mono text-lg font-bold">{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wide text-aether-muted-dim">{label}</div>
    </div>
  );
}
