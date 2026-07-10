/**
 * Story Bank derivations (P2-S09 / AGT-STORY).
 *
 * Every value the UI shows is computed from live `GET /stories` data — no
 * hardcoded fixtures and no fabricated metrics. Where the wireframe implies a
 * datum the model does not carry (e.g. voice-match), we surface it honestly
 * (`—`) rather than inventing a number.
 */
import type { Story } from "../../lib/api/stories";

export const STORY_CATEGORIES = ["Leadership", "Delivery", "Technical", "Risk & Compliance"] as const;
export type StoryCategory = (typeof STORY_CATEGORIES)[number];

/** Chip filter values: the four categories plus the "All" pass-through. */
export type StoryFilter = "All" | StoryCategory;
export const STORY_FILTERS: StoryFilter[] = ["All", ...STORY_CATEGORIES];

const CATEGORY_KEYWORDS: Record<StoryCategory, string[]> = {
  Leadership: ["leadership", "lead", "team", "people", "mentor", "manage"],
  Delivery: ["delivery", "deliver", "program", "project", "automation", "execution", "agile", "scrum"],
  Technical: ["technical", "engineering", "architecture", "platform", "code", "data", "api", "cloud"],
  "Risk & Compliance": ["risk", "compliance", "audit", "governance", "security", "regulatory", "control"],
};

/** Per-category accent used for the card left-border and badge (wireframe palette). */
export const CATEGORY_COLOR: Record<StoryCategory, { border: string; badgeBg: string; badgeText: string }> = {
  Leadership: { border: "#4F46E5", badgeBg: "rgba(79,70,229,0.20)", badgeText: "#818CF8" },
  Delivery: { border: "#FF6B35", badgeBg: "rgba(255,107,53,0.15)", badgeText: "#FF6B35" },
  Technical: { border: "#60A5FA", badgeBg: "rgba(96,165,250,0.15)", badgeText: "#60A5FA" },
  "Risk & Compliance": { border: "#A78BFA", badgeBg: "rgba(167,139,250,0.20)", badgeText: "#A78BFA" },
};

function haystack(story: Story): string {
  return [story.title, story.situation, story.task, story.action, story.result, ...story.tags]
    .join(" ")
    .toLowerCase();
}

/** Best-fit category for a story, or null when nothing matches. */
export function categoryOf(story: Story): StoryCategory | null {
  const text = haystack(story);
  let best: { category: StoryCategory; hits: number } | null = null;
  for (const category of STORY_CATEGORIES) {
    const hits = CATEGORY_KEYWORDS[category].filter((kw) => text.includes(kw)).length;
    if (hits > 0 && (best === null || hits > best.hits)) best = { category, hits };
  }
  return best?.category ?? null;
}

export function matchesFilter(story: Story, filter: StoryFilter): boolean {
  return filter === "All" || categoryOf(story) === filter;
}

/** Numeric voice-match score (0–100) if the story carries one, else null. */
export function voiceMatchOf(story: Story): number | null {
  if (!story.metrics) return null;
  for (const [key, value] of Object.entries(story.metrics)) {
    if (/voice/i.test(key)) {
      const num = Number(String(value).replace(/[^\d.]/g, ""));
      if (Number.isFinite(num)) return Math.round(num);
    }
  }
  return null;
}

/** First evidenced metric shown as the card impact badge, or null. */
export function impactBadge(story: Story): string | null {
  if (!story.metrics) return null;
  for (const [key, value] of Object.entries(story.metrics)) {
    if (/voice/i.test(key)) continue;
    const str = String(value);
    if (/\d/.test(str)) return str;
  }
  return null;
}

export interface StoryStats {
  total: number;
  quantified: number;
  addedThisMonth: number;
  voiceAvg: number | null;
}

export function computeStats(stories: Story[]): StoryStats {
  const now = new Date();
  let quantified = 0;
  let addedThisMonth = 0;
  const voices: number[] = [];
  for (const story of stories) {
    if (story.metrics && Object.keys(story.metrics).length > 0) quantified += 1;
    const created = new Date(story.createdAt);
    if (
      !Number.isNaN(created.getTime()) &&
      created.getUTCFullYear() === now.getUTCFullYear() &&
      created.getUTCMonth() === now.getUTCMonth()
    ) {
      addedThisMonth += 1;
    }
    const voice = voiceMatchOf(story);
    if (voice !== null) voices.push(voice);
  }
  return {
    total: stories.length,
    quantified,
    addedThisMonth,
    voiceAvg: voices.length ? Math.round(voices.reduce((a, b) => a + b, 0) / voices.length) : null,
  };
}

export interface QuestionMapping {
  question: string;
  story: Story | null;
  accent: string;
}

const COMMON_QUESTIONS: { question: string; keywords: string[]; accent: string }[] = [
  { question: "Tell me about a time you improved a process.", keywords: ["automat", "process", "efficien", "reduc", "delivery"], accent: "#FF6B35" },
  { question: "Describe leading a large team.", keywords: ["leadership", "lead", "team", "people", "manage"], accent: "#818CF8" },
  { question: "A time you handled compliance risk.", keywords: ["risk", "complian", "audit", "governance"], accent: "#A78BFA" },
  { question: "Tell me about a conflict you resolved.", keywords: ["conflict", "resolution", "stakeholder", "align"], accent: "#60A5FA" },
  { question: "Describe a failure and what you learned.", keywords: ["failure", "lesson", "learn", "mistake"], accent: "#FBBF24" },
];

export function mapQuestions(stories: Story[]): QuestionMapping[] {
  return COMMON_QUESTIONS.map(({ question, keywords, accent }) => {
    const story =
      stories.find((s) => {
        const text = haystack(s);
        return keywords.some((kw) => text.includes(kw));
      }) ?? null;
    return { question, story, accent };
  });
}

export interface CoverageGap {
  competency: string;
  count: number;
  status: "No story" | "Thin";
}

const COMPETENCIES: { competency: string; keywords: string[] }[] = [
  { competency: "Conflict resolution", keywords: ["conflict", "resolution", "mediat"] },
  { competency: "Failure / lessons learned", keywords: ["failure", "lesson", "learn", "mistake"] },
  { competency: "Stakeholder influence", keywords: ["stakeholder", "influence", "persuad", "align"] },
  { competency: "Leadership", keywords: ["leadership", "lead", "team"] },
  { competency: "Delivery", keywords: ["delivery", "program", "execution", "automat"] },
  { competency: "Risk & Compliance", keywords: ["risk", "complian", "audit"] },
];

/** Competencies with fewer than two backing stories, worst-covered first. */
export function coverageGaps(stories: Story[]): CoverageGap[] {
  return COMPETENCIES.map(({ competency, keywords }) => {
    const count = stories.filter((s) => {
      const text = haystack(s);
      return keywords.some((kw) => text.includes(kw));
    }).length;
    return { competency, count };
  })
    .filter((c) => c.count < 2)
    .sort((a, b) => a.count - b.count)
    .map((c) => ({ ...c, status: c.count === 0 ? ("No story" as const) : ("Thin" as const) }));
}

/** Flatten a story into copyable STAR+R text for the Insert action. */
export function storyToText(story: Story): string {
  return [
    story.title,
    `Situation: ${story.situation}`,
    `Task: ${story.task}`,
    `Action: ${story.action}`,
    `Result: ${story.result}`,
  ].join("\n");
}
