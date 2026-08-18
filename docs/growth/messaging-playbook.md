# Aether — Messaging Playbook & Email Templates

## ICP
Active job seekers (career changers, layoff-affected professionals, early/mid-career knowledge workers) frustrated with (a) generic AI resume tools that fabricate experience, and (b) the sheer time cost of tailoring resumes/cover letters per application.

## Core positioning
"The AI job agent that refuses to lie on your resume — and never sends anything without your approval."
Differentiators: anti-fabrication entailment guard, human-approval gate on every outbound action, ToS-compliant job sourcing (licensed APIs, no scraping), transparent before/after ATS scoring.

## Pricing (GST-inclusive AUD, from docs/subscription/billing-architecture.md)
Every plan uses the same AI models and the same product features (resume
tailoring, cover letters, the story bank, the email agent, ATS scoring) — no
tier unlocks a feature another tier lacks. Plans differ by EXACTLY two
enforced facts: the monthly agent-run quota and the monthly AI spend cap
(ruling D4, `apps/api/tests/test_aud_mon_1_plans_payload.py`).
- Free: $0 — 5 agent runs/month, US$1.00 monthly AI spend cap, no card required
- Starter: $19/mo ($179/yr) — 30 agent runs/month, US$5.00 monthly AI spend cap
- Pro: $39/mo ($359/yr) — 100 agent runs/month, US$15.00 monthly AI spend cap
- Power: $69/mo ($649/yr) — 300 agent runs/month, US$40.00 monthly AI spend cap

## Compliance footer — append to EVERY commercial/outreach email (Spam Act 2003 requirement)
```
—
Sent by Vic (Aether Career Agent), aether-job-career-agent.
Live product: https://5cb5f0620.abacusai.cloud
If you'd rather not hear from me again, just reply "unsubscribe" and I will not email you again.
```

## Template 1 — Demo request response (send within minutes of an inbound request)
Subject: Your Aether demo — plus a quick win for your resume
Hi {first_name},
Thanks for asking about Aether. Quick context: it tailors your resume/cover letter from your own evidence only (no fabricated bullets), sources jobs from licensed APIs, and nothing goes out — no email, no application — without your approval first.
Fastest way to see it: sign up free (no card needed, 5 runs included) at https://5cb5f0620.abacusai.cloud/signup and run your resume against one real job posting. Takes about 3 minutes.
If you'd rather I walk you through it live, reply with a couple of times that work this week and I'll set it up.
—
Sent by Vic (Aether Career Agent), aether-job-career-agent.
Live product: https://5cb5f0620.abacusai.cloud
If you'd rather not hear from me again, just reply "unsubscribe" and I will not email you again.

## Template 2 — Warm network / founder-led outreach (only to people Vic has an existing relationship with — colleagues, ex-Accenture/ATO, GitHub followers who've engaged)
Subject: Built something for your job search — {specific_reason}
Hi {first_name},
{specific_personal_hook — e.g., "saw you mentioned you're looking at PM roles" / "since we worked together at Accenture"}.
I built an AI job agent called Aether because every resume tool I tried made up experience I didn't have. This one only writes what your own resume/story bank can back up, and it won't send or apply to anything without you approving it first.
Free to try, no card required: https://5cb5f0620.abacusai.cloud
Would love your honest take if you get five minutes with it.
—
Sent by Vic (Aether Career Agent), aether-job-career-agent.
Live product: https://5cb5f0620.abacusai.cloud
If you'd rather not hear from me again, just reply "unsubscribe" and I will not email you again.

## Template 3 — Free-to-paid upgrade nudge (trigger: user nearing/at 5-run Free limit)
Subject: You're close to your free run limit
Hi {first_name},
You've used {runs_used}/5 free Aether runs this month — nice, that means you're actively using it.
Starter ($19/mo) gives you 30 agent runs/month and a US$5.00 monthly AI spend cap — same AI models, same features you already have on Free, just more room to run them. Upgrade here: https://5cb5f0620.abacusai.cloud/pricing
—
Sent by Vic (Aether Career Agent), aether-job-career-agent.
Live product: https://5cb5f0620.abacusai.cloud
If you'd rather not hear from me again, just reply "unsubscribe" and I will not email you again.

## Template 4 — Re-engagement (signed up, went quiet)
Subject: Still job hunting, {first_name}?
Hi {first_name},
Noticed you signed up for Aether but haven't run it in a while. If the job search is still on, took a look and here's one thing worth trying: paste in a job you're eyeing and let the fit-scorer + tailoring agent do the first pass — free tier covers it.
If the search wrapped up, no action needed. If it's still going, reply and I'll point you at the fastest path to a first result.
—
Sent by Vic (Aether Career Agent), aether-job-career-agent.
Live product: https://5cb5f0620.abacusai.cloud
If you'd rather not hear from me again, just reply "unsubscribe" and I will not email you again.

## Hard rule for the autonomous engine
Never invent a recipient. Only send Template 1/3/4 in reply to a real inbound thread or a real in-app signal. Only send Template 2 to a contact Vic has a genuine prior email relationship with (never a scraped or purchased address). If no such real signal exists in a given run, generate LinkedIn content and log a Learnings entry instead of sending anything.
