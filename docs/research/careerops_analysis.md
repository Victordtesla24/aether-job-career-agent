# Career-Ops Platform Capability Analysis

This document provides a detailed analysis of the Career-Ops platform, focusing on unique and advanced features that could provide a competitive advantage for Aether.

---

### 1. Rubric-Guided 6-Block Job Evaluation
- **Description**: A comprehensive qualitative and quantitative assessment of job fit using a multi-dimensional rubric.
- **How it works**: When a job URL or description is provided, the AI agent uses a 10-weighted dimension rubric (North Star alignment, CV match, seniority level, estimated compensation, growth trajectory, etc.) to score the role from 1.0 to 5.0. It produces a "6-block" report covering role summary, gap analysis, strategy, compensation research, personalization notes, and interview prep.
- **Why it's valuable**: It moves beyond simple keyword matching to "actual reasoning," evaluating cultural signals, red flags (Block G legitimacy check), and strategic positioning.
- **How it could enhance Aether**: Aether can implement a similar "Reasoning-First" evaluation that goes deeper than ATS scores, providing users with specific "Strategic Angles" for each application and flagging "Ghost Jobs" or scams automatically.

### 2. Contextual "Voice DNA" Guardrails
- **Description**: A set of advanced LLM instructions that enforce a specific, human-like writing identity while banning common "AI tells."
- **How it works**: Enforces rules like "No em-dashes," "No negative parallelisms," "Banned AI words (delve, harness, tapestry)," and "Rhythmic sentence variation." It applies these constraints to every resume, cover letter, and email draft.
- **Why it's valuable**: Generative AI text is increasingly easy to detect and filter. Voice DNA ensures materials sound authentic, sharp, and results-oriented, bypassing "AI fatigue" in recruiters.
- **How it could enhance Aether**: Integrating Voice DNA into Aether's tailoring studio would make the generated resumes and cover letters significantly more persuasive and harder for automated AI detectors to flag.

### 3. Interview Audience-Specific Intelligence (`interview-prep`)
- **Description**: Targeted interview preparation based on the specific audience of the round.
- **How it works**: Classifies rounds into "Recruiter Screen," "Hiring Manager," "Peer-Tech," or "Panel-Mixed." It then generates tailored talking points: Recruiter hears logistics and "why us"; HM hears scope and ownership; Peers hear architecture and tradeoffs.
- **Why it's valuable**: Candidates often fail by giving the same "canned" answers to everyone. This feature ensures the candidate speaks the "language" of their specific listener at each stage.
- **How it could enhance Aether**: Aether could expand its interview prep to include "Audience Maps" and "Reverse Question Packs" tailored to the specific people the candidate is scheduled to meet.

### 4. Behavioral "Story Bank" Mapping
- **Description**: A systematic library of STAR (Situation, Task, Action, Result) stories mapped to predicted interview questions.
- **How it works**: During onboarding, a conversational interview extracts specific metrics and achievements. These are stored in a "Story Bank." Whenever a new job is evaluated, the system maps existing stories to the job's specific requirements and flags "Story Gaps."
- **Why it's valuable**: Having a pre-mapped bank of quantified achievements reduces interview anxiety and ensures the candidate uses their strongest proof points for the most relevant questions.
- **How it could enhance Aether**: Aether could maintain a persistent "Achievement Database" for each user, automatically suggesting which "Story" to use for specific application questions or interview rounds.

### 5. Multi-Offer Scoring Matrix (`ofertas`)
- **Description**: A detailed comparison tool for ranking and deciding between multiple competing offers.
- **How it works**: Uses a weighted matrix of 10 dimensions (tech stack modernity, remote quality, growth trajectory, time-to-offer speed, etc.) to calculate a comparative score across multiple roles.
- **Why it's valuable**: Career decisions are often emotional; this provides a rational, data-driven framework for trade-off analysis during the final decision phase.
- **How it could enhance Aether**: Aether can offer an "Offer Decision Engine" that helps users compare total rewards, career growth, and work-life balance across their pipeline.

### 6. Recruiter Relationship Management & Follow-up Cadence
- **Description**: A CRM-like tracker for maintaining high-touch communication with recruiters.
- **How it works**: Tracks application age and recruiter response status. It defines specific cadence rules (e.g., follow up after 7 days if no response; follow up 1 day after an interview). It drafts value-led follow-up emails that reference specific project updates or role-relevant news.
- **Why it's valuable**: Constant, professional follow-up is one of the most effective ways to stay top-of-mind, but it is tedious to manage manually.
- **How it could enhance Aether**: Aether's Application Tracker can integrate "Urgency Alarms" and "Value-Add Drafts" to automate the follow-up process while maintaining a personal touch.

### 7. Recruiter-Side Risk Mapping
- **Description**: A heuristic analysis that anticipates doubts a recruiter might have about the candidate.
- **How it works**: Before tailoring materials, the system builds an internal "Risk Map" (e.g., "Is the candidate too senior?", "Is their stack a 100% match?"). It then writes the CV and cover letter specifically to neutralize those risks.
- **Why it's valuable**: It flips the script from "What can I do?" to "What is the recruiter afraid of, and how can I fix it?"
- **How it could enhance Aether**: Aether's Resume Tailoring Studio could adopt a "Risk Mitigation Mode" to proactively address profile gaps or transitions.

### 8. Liveness & Legitimacy Verification (Block G)
- **Description**: Automated checks to see if a job is still active and if it is a "real" listing.
- **How it works**: Uses API-based checks (Greenhouse/Lever) and Playwright browser checks to detect expired links or "Ghost Jobs." Block G identifies patterns common in fake or outdated listings.
- **Why it's valuable**: Saves users from wasting time on roles that aren't actually hiring.
- **How it could enhance Aether**: Aether can incorporate a "Trust Score" or "Liveness Badge" for every job discovered, filtering out low-quality or inactive postings.

### 9. Interactive Metric Enrichment (`/career-ops interview`)
- **Description**: A conversational agent mode dedicated to "digging for metrics."
- **How it works**: Instead of just reading a resume, the agent interviews the user, asking "What tools/architecture were used?" and "What was the measurable outcome?" to transform vague bullets into "Business-Value Bullets."
- **Why it's valuable**: Most resumes lack the quantified impact that LLM/ATS filters and human recruiters look for.
- **How it could enhance Aether**: Use a conversational "Metric Hunter" agent to help users beef up their "Resume Tailoring Studio" with hard numbers and proof points.

### 10. `contacto` Mode (LinkedIn Power Move)
- **Description**: Targeted, research-backed LinkedIn outreach strategy.
- **How it works**: Identifies the Hiring Manager, Recruiter, and Peers. Generates a 3-sentence message framework: (Hook/Fit) -> (Proof) -> (CTA). Each message is adapted to the contact's role (Recruiter vs. Peer).
- **Why it's valuable**: Increases the "Interview Conversion" rate by creating direct-to-human connections outside the ATS.
- **How it could enhance Aether**: Aether could offer a "Social Engineering Skill" that guides users on who to contact on LinkedIn for every job they apply to, providing the exact script.
