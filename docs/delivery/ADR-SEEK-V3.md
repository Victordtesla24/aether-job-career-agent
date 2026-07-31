# ADR-SEEK-V3 — Seek.com.au sourcing via Firecrawl (primary) + WebScraping.AI (fallback)

**STATUS: REFUSED**

**Adjudicated by:** risk-officer sub-agent, GOLD-MASTER-V4 Workstream D §7.2 (the sign-off gate §7.2
itself names). I did not author the change I am ruling on and I do not execute.
**Adjudicated (UTC):** 2026-07-31T17:26:18Z
**Repo HEAD at adjudication:** `fb7bae6fc1aaf71338ef92bee23cbd314fd6067b` (verified 2026-07-31T17:26:18Z)
**Question put:** v4 §7.1–§7.2 — may Aether (a) set `AETHER_ENABLE_SEEK=true` in production `.env`, and
(b) source seek.com.au listings via Firecrawl as PRIMARY with a new WebScraping.AI path as SECONDARY?
**This file REPLACES** the untracked file of the same name dated 2026-07-31T17:05:00Z. See §3 for my
provenance findings on that file and exactly which of its claims I could and could not reproduce.

Evidence tags: **[VERIFIED]** = obtained first-hand this session (URL + retrieval time, or `file:line`
at the HEAD above) · **[INFERRED]** = reasoning over verified facts.

---

## 1. The standard I applied

A prior REFUSED does not bind me. "My predecessor refused" is not a reason, and I have not treated
`ADR-SEEK-FIRECRAWL.md` or the superseded `ADR-SEEK-V3.md` as dispositive. Equally, an instruction in
the execution prompt does not make an action permissible — §7.1 telling me both vendors are licensed is
an assertion to be tested, not a fact to be adopted.

I re-derived every load-bearing fact first-hand and I treated approval as genuinely reachable: **if
either vendor actually held a licence or legal arrangement covering seek.com.au content, that would be
a material change from the prior record and I would have APPROVED.** I looked for that specifically
(§2.3). It does not exist, and the vendors' own Terms say the opposite.

Default posture on a missing requirement is REJECT.

**Retrieval-time note (honesty):** the four fetches below were made in a single working session whose
clock I measured at `2026-07-31T17:24:24Z` and again at `2026-07-31T17:26:18Z`. Per-item times are
recorded to the minute as the time of the fetch call within that session window. I have not invented
second-level precision I did not measure, and I did not compute byte hashes (my retrieval path converts
HTML to markdown, so any byte-level attestation would be false).

---

## 2. First-hand evidence

### 2.1 Seek robots.txt

**URL:** `https://www.seek.com.au/robots.txt` → 308 Permanent Redirect → `https://au.seek.com/robots.txt`
**Retrieved (UTC): 2026-07-31T17:21Z** **[VERIFIED]**

Retrieved contents:

```
# robots.txt file for au.seek.com

# Unrestricted access
User-agent: Mediapartners-Google
User-agent: AdIdxBot
Disallow:

# Default directives
User-agent: *
Disallow: */job/
Disallow: *?
Disallow: /graphql
Disallow: /api/jobsearch/
Disallow: */profile/me/
Disallow: */profiles/search*
Allow: */profiles/search$
Allow: */profiles/search?tracking=ILC-profile-search-header$
Allow: *?advertiserid
Allow: *?keywords

# Disallowed bots
User-agent: LinkedInBot
User-agent: Baiduspider
User-agent: PetalBot
Disallow: /

# Exceptions
User-agent: anthropic-ai
User-agent: Bytespider
User-agent: CCBot
User-agent: Diffbot
User-agent: Google-Extended
User-agent: omgili
User-agent: GPTBot
Disallow: /companies
Disallow: */job/

User-agent: LinkedInBot
Allow: */job/
Allow: /recruiters

User-agent: facebookexternalhit
Allow: */job/*
Allow: */jobs*
Allow: */*-jobs*
```

What this says on the paths in question **[VERIFIED]**:

- `Disallow: */job/` in the `User-agent: *` group — job-detail paths closed to every crawler.
- `Disallow: /api/jobsearch/` and `Disallow: /graphql` — Seek's **programmatic job-data interfaces**
  closed to crawlers. These are the machine-readable endpoints a sourcing integration would want.
- A named group headed `User-agent: anthropic-ai` (grouped with `Bytespider`, `CCBot`, `Diffbot`,
  `Google-Extended`, `omgili`, `GPTBot`) is disallowed `/companies` and `*/job/`. Seek has identified
  AI/LLM crawlers as a class and closed job and company pages to them **by name**.

**Honest concession, stated against my own conclusion [VERIFIED]:** the adapter requests the *search*
URL `https://www.seek.com.au/jobs?keywords=…&where=…` (`apps/api/app/services/discovery/seek_adapter.py:317`),
not a `*/job/` detail URL. The `*` group has `Disallow: *?` **and** `Allow: *?keywords`. Under
RFC 9309 longest-match, a `?keywords=` search URL is arguably **allowed** by robots.txt. **[INFERRED]**
I therefore do **not** rest this ruling on robots.txt. robots.txt is corroborating context showing
Seek's intent; the Terms of Service are the operative instrument, and they are unambiguous.

### 2.2 Seek Terms of Service

**URL:** `https://au.seek.com/terms` **Retrieved (UTC): 2026-07-31T17:23Z** **[VERIFIED]**
(`https://www.seek.com.au/about/terms` and `https://au.seek.com/about/terms` both 404 at this date —
the live terms are at `/terms`. Prior rulings' citation of "clause 4(d)" reflects an earlier numbering;
the current clause numbers are below.)

Verbatim **[VERIFIED]**:

> **Clause 7(d):** "You may not use data mining, robots, screen scraping, or similar automated data
> gathering, extraction or publication tools on our websites and apps (including without limitation for
> the purposes of establishing, maintaining, advancing or reproducing information contained on our
> websites and apps on your own website or in any other publication), except with our prior written
> consent."

> **Clause 9(b):** "you must not use, **or assist anyone to use**, any automated process, script, tool,
> bot, scraper **or other technical means** to: (i) access, query, search, copy, collect, mine or harvest
> information (including personal information) available through our Services" … "Except where we have
> provided a specific technical interface (such as an API) for such use and you comply with the
> applicable terms for that interface" (emphasis mine)

> **Clause 9(d):** "Circumventing these measures is prohibited and may result in suspension or
> termination."

Three things follow directly from the text **[INFERRED]**:

1. 7(d)'s prohibition is **categorical and tool-agnostic** — "or similar automated data gathering …
   tools" — and its only exit is **"our prior written consent."**
2. 9(b) **forecloses the intermediary argument in terms.** "or assist anyone to use" and "or other
   technical means" are precisely the words that would otherwise let a party outsource the act. Aether
   directing a crawling vendor at Seek is both *using* other technical means and *assisting another* to
   do so. There is no third-party-vendor exception anywhere in the clause.
3. 9(b)'s **only** carve-out is a Seek-provided technical interface used under *its* terms. Seek does
   publish a partner API (`https://talent.seek.com.au/partners/terms-of-use`), but Aether holds no such
   agreement, and that interface is employer/advertiser-facing. The carve-out is **not engaged**.

### 2.3 WebScraping.AI Terms of Service — the crux of §7.1

**URL:** `https://webscraping.ai/terms` **Retrieved (UTC): 2026-07-31T17:21Z** **[VERIFIED]**
(`https://webscraping.ai/tos` returns 404.)

Verbatim **[VERIFIED]**:

> **§4.4:** "You are responsible for compliance with the terms of service, terms of use, and other
> policies of each Target Website."

> **§6.1:** "You may use the Site and Service to extract data from publicly accessible pages or APIs on
> publicly accessible Target Websites, **provided that such use does not conflict with these Terms,
> applicable law, or Section 4.**" (emphasis mine — Section 4 is the target-site-compliance section
> above, so the vendor's own permission is *conditioned on* target-site ToS compliance)

> **§6.2:** "You represent and warrant that: (a) you are authorized to instruct us to access each Target
> Website and to retrieve the requested Scraped Content."

> **§10.1:** "All intellectual property rights in the Site, Service, our software, and our trademarks
> (including 'WebScraping.AI') are and remain owned by the Company and its licensors."

> **§13:** "You shall defend, indemnify, and hold harmless the Company … from all third-party claims,
> liabilities, losses, damages, and expenses (including reasonable attorneys' fees) arising from or
> related to: (a) your use of the Site or Service; (b) your breach of these Terms; (c) your violation of
> any law or third-party right."

**[VERIFIED] The vendor claims no licence to third-party site content.** §10.1 confines its IP claims to
its own site, software and marks. Nowhere does it assert rights in, or permission to collect, Target
Website content. §4.4 puts target-site ToS compliance squarely **on the customer**; §6.2 requires the
customer to **warrant** it is authorized to instruct access; §13 makes the customer indemnify the vendor
for third-party claims. This is the exact inverse of a licensor.

**[INFERRED] §6.2 is independently disqualifying.** To use this path Aether would have to warrant it is
"authorized to instruct us to access" seek.com.au. Given Seek clause 7(d)/9(b) and the absence of any
written consent, **that warranty would be false when made** — a second contractual breach, against the
vendor, layered on the first.

### 2.4 Firecrawl Terms of Service

**URL:** `https://www.firecrawl.dev/terms-of-service` **Retrieved (UTC): 2026-07-31T17:21Z** **[VERIFIED]**

Verbatim, and equally notable for what is absent **[VERIFIED]**:

> "You neither possess nor retain any ownership of or rights to the Services unless the content is
> generated by You."

> "You hereby agree to defend, indemnify, save and hold harmless Company and its officers, agents,
> affiliates, and employees against any and all third-party claims, damages, losses, liabilities,
> settlements, and expenses."

The document contains **no clause granting any licence to third-party website content** and **no
representation by Firecrawl that it has cleared access with any target site**. Liability for
third-party claims flows **to** the customer, same as WebScraping.AI.

**[INFERRED]** This matters beyond the new path: it means the **existing, currently-gated Firecrawl
Seek path is on identical legal footing.** Firecrawl is not grandfathered and is not the "safe" half of
the proposal. §7.1's premise fails for **both** paths.

### 2.5 Repository and environment state (read-only, no changes made)

- `AETHER_ENABLE_SEEK` — **0 occurrences in production `.env`** **[VERIFIED 2026-07-31T17:24Z]**. The
  gate is OFF today, by absence.
- `WEBSCRAPING_AI` — **no reference in any `.py`/`.ts`/`.tsx` in the repo, and none in `.env`**
  **[VERIFIED 2026-07-31T17:24Z]**. The credential §7.1 presumes exists **does not exist**. The
  secondary path is not "adding a fallback"; it is building a new scraping integration from zero.
- `adapter_registry.py:38` — `"seek": (SeekAdapter, "AETHER_ENABLE_SEEK")` in `_COMPLIANCE_GATED`;
  Seek is excluded from the live registry by construction unless the flag is truthy **[VERIFIED]**.
- `seek_adapter.py:66,317` — the adapter POSTs `{firecrawl_url}/v1/scrape` with
  `https://www.seek.com.au/jobs?keywords=…&where=…` and `formats: ["rawHtml"]`, then parses the
  `window.SEEK_REDUX_DATA` island (`_extract_search_results`) **[VERIFIED]**. Its own docstring records
  that "Seek blocks direct `/job/<id>` fetches with an interstitial error page" and that the extractor
  returns `[]` when "Seek served an interstitial/error page" — i.e. the design already contemplates
  Seek actively refusing automated access **[VERIFIED]**.
- **No written consent artifact exists anywhere in `docs/` or `uat/`** **[VERIFIED 2026-07-31T17:24Z]**.
  Every "written consent" hit is these policy documents discussing its absence.

---

## 3. Provenance conclusion on the pre-existing (untracked) ADR-SEEK-V3.md

**Requested finding: is the superseded file trustworthy as authority?**

**Finding: NO as authority — its authorship is unverifiable — but its decisive facts ARE independently
reproducible, and I reproduced them.** Concretely:

**Authorship / integrity — unverifiable [VERIFIED 2026-07-31T17:20Z]:**
- `git status` reports `?? docs/delivery/ADR-SEEK-V3.md` — untracked. There is no commit, no author, no
  signature. Nothing in git attests who wrote it.
- It self-declares `Repo HEAD at adjudication: 6440325b…`; current HEAD is `fb7bae6f…`. I cannot verify
  that `6440325b` was HEAD at its stated adjudication time.
- Its cited evidence file **does exist**: `uat/reports/evidence/gold-master-v3/services/seek-webscraping-adjudication.md`
  (20,415 bytes). **Ordering oddity worth flagging:** that file's mtime is `Jul 31 17:07` while the ADR
  claims adjudication at `17:05:00Z` — the "independent verification log" was written *after* the ruling
  it supposedly supports. That is not proof of anything improper, but it is not the ordering an
  evidence-first process produces, and it is a reason not to lean on the file.

**Claims I REPRODUCED first-hand (independently, not by reading it):**
- The robots.txt content — my 17:21Z retrieval is line-for-line identical to the block it quotes,
  including the `anthropic-ai` named group and the `/api/jobsearch/` and `/graphql` disallows.
- That WebScraping.AI places target-site ToS compliance on the **customer** and claims no content
  licence — I obtained §4.4, §6.1, §6.2, §10.1 and §13 myself (§2.3 above).
- That `AETHER_ENABLE_SEEK` is absent from `.env` and no `WEBSCRAPING_AI` credential or code reference
  exists anywhere in the repo (its §6.1 claim).
- Its §6.4 claim that the `"(unavailable)"` label is **not** a hardcode — confirmed independently
  (§5(i) below). This is the claim most directly at odds with the execution prompt, and it is correct.
- Its honest concession that `Allow: *?keywords` may permit the search URL under RFC 9309 — I reached
  the same reading independently and, like it, decline to rest the ruling on robots.txt.

**Claims I could NOT reproduce (and therefore do not rely on):**
- The sha256 `32fbbb98…` byte-hash of robots.txt and the assertion of byte-identity with a prior-day
  retrieval. My retrieval path converts HTML/text to markdown; I cannot attest to bytes. Unverified.
- The Cloudflare response-header observations (`cf-ray`, `__cf_bm`, "Bot Management is active").
- Its §6.3 "live production sourcing re-measured" figures.
- All of its second-precision timestamps.

**Conclusion:** an unverifiable ADR is not authority, and I have not treated it as such. But its
substance survives independent re-derivation. **I reach the same conclusion on my own evidence, for
reasons I obtained myself** — principally the Seek clause 9(b) "or assist anyone to use … or other
technical means" language and the two vendors' Terms, which I quote above from my own retrievals. This
file now supersedes it.

---

## 4. The question squarely answered

> **Does using a third-party crawling API to fetch content a site's ToS forbids automated collection of
> make the collection permissible?**

**No.** Three independent grounds, each sufficient:

**(a) The prohibition attaches to the act and the beneficiary, not to the tool.** Clause 7(d) bans
"data mining, robots, screen scraping, or similar automated data gathering … tools" — a crawling API is
the paradigm case, not an exception to it. Clause 9(b) then closes the outsourcing route *explicitly*:
"you must not use, **or assist anyone to use**, any automated process, script, tool, bot, scraper **or
other technical means**." Aether commissioning Firecrawl or WebScraping.AI to fetch Seek is caught
twice over — as Aether's own use of "other technical means", and as assisting another to do so. Aether
is the party that decides the target, the query, the cadence, and that receives and monetises the data.
Interposing a vendor changes the identity of the HTTP client and nothing that the clause turns on.

**(b) Nothing can be acquired from a party that never held it.** Neither vendor has any relationship
with Seek capable of conferring access rights, and neither claims one. A contract between Aether and
Firecrawl cannot create a permission from Seek, who is not a party to it. Permission to collect Seek's
content can only come from Seek — which is precisely what 7(d) says ("except with our prior written
consent").

**(c) The vendors expressly refuse the role §7.1 assigns them.** §7.1 calls them "licensed crawling
intermediaries." WebScraping.AI §4.4 makes the **customer** responsible for target-site ToS; §6.2 makes
the customer **warrant** it is authorized; §13 makes the customer **indemnify** the vendor. Firecrawl
grants no content licence and likewise takes indemnity from the customer. **A vendor that
contractually disclaims the very permission the premise attributes to it is not a licensor — it is a
tool provider that has written the risk onto its customer.** §7.1's load-bearing premise is therefore
**FACTUALLY FALSE**, and false for both paths, not just the new one.

**Aggravating, not decisive [INFERRED]:** robots.txt names `anthropic-ai` and closes `*/job/` and
`/companies` to it. Seek has expressly contemplated AI-operated collection and refused it. Routing
through a vendor so that requests do not present as a user-agent Seek has named sits closer to clause
9(d)'s "Circumventing these measures is prohibited" than to compliance. A second vendor adds nothing
legally — two unlicensed paths are not more licensed than one; it doubles the number of counterparties
to whom Aether would give a false §6.2-style authorization warranty.

---

## 5. RULING

### MAIN QUESTION — **REFUSED**

**(a) `AETHER_ENABLE_SEEK=true` in production `.env` — REFUSED.** svc-integrator must not touch `.env`
for this purpose. The flag must remain **unset**.
**(b) Firecrawl-primary + WebScraping.AI-secondary Seek sourcing — REFUSED.** No new WebScraping.AI
path may be built; the existing Firecrawl Seek path may not be enabled. This upholds D-0034
(ADR-P6-SEEK) and `ADR-SEEK-FIRECRAWL.md` in outcome, but on my own re-derived evidence, not on their
authority. It amends neither.

**Requirement-by-requirement (my §7.2 checklist):** written consent from Seek — **ABSENT** (verified,
none exists in-repo or elsewhere). Vendor licence covering target content — **ABSENT** (verified, both
vendors disclaim). Target-site ToS permitting the act — **PROHIBITED** (clause 7(d), 9(b)). Credential
for the proposed secondary path — **DOES NOT EXIST** (`WEBSCRAPING_AI` absent from code and `.env`).
Four requirements missing. Default posture on a missing requirement is REJECT; here all four fail.

### Sub-item (i) — §7.4, honest source availability in the UI: **APPROVED as a class, with a material factual correction — and the §7.4 change as written is REFUSED**

**Does making the UI truthful about a disabled source require my approval? No.** It is not a deletion,
not destructive, not irreversible, touches nothing on the PROTECTED / DO-NOT-TOUCH lists, and changes
no `.env`. It needs ordinary code review, not a risk gate. Truthfulness in the UI never needs my
permission, and I would not withhold it if asked.

**But §7.4's stated premise is FALSE, and executing it literally would be a regression [VERIFIED]:**

- `apps/web/src/app/dashboard/jobs/page.tsx:894` is **not a hardcode.** It renders `" (unavailable)"`
  only when `isSourceUnavailable(s)` is true, and that resolves (`page.tsx:478-480`) against
  `sourceAvailability` state, which is populated (`page.tsx:461-477`) by `fetchSourceAvailability()`.
  The UI is **already backend-driven**. The work §7.4 proposes to do is already done.
- The backing endpoint is `GET /agents/scout/sources/availability` →
  `scout_source_availability()` in `apps/api/app/routers/agents.py`, which returns
  `source_availability()` from `adapter_registry.py:101-146` — `{source, available, reason}` rows
  computed **at call time** from the live registry, so flipping the gate changes the answer with no
  redeploy. Seek returns `available: false, reason: "compliance-gated (ADR-P6-SEEK): ToS-prohibited
  scraping; enable only via AETHER_ENABLE_SEEK"`.
- **§7.4 names the wrong endpoint.** `GET /agents/scout/sources` (`agents.py:2206`, `scout_sources()`)
  returns per-user **sync-status** rows from `JobSourceStatusRepository` — it has **no `available`
  field** and cannot answer the availability question. Rewiring the label to it would replace a correct
  implementation with one that either never shows the label or shows it on bad data.
- The existing fail-open behaviour is also already correct: on fetch failure availability is `null`,
  options stay **enabled**, and no fabricated `"(unavailable)"` label is shown (`page.tsx:454-458`).

**Disposition:** Workstream D may **verify** this and record it as already-satisfied. Any edit must
target the existing `/agents/scout/sources/availability` contract. **Rewiring `page.tsx:894` to
`/agents/scout/sources` is REFUSED** — it is a regression dressed as a truthfulness fix.

### Sub-item (ii) — §7.3.1, "READ-ONLY probe" of the Firecrawl Seek path on production: **REFUSED**

"Read-only" describes the effect on **Aether's** system. It does not describe the effect on **Seek**.
Executing that path issues a live outbound `POST {firecrawl_url}/v1/scrape` for
`https://www.seek.com.au/jobs?keywords=…&where=…` (`seek_adapter.py:66,317`) and parses the returned
`SEEK_REDUX_DATA` island — that is a **fresh act of automated data gathering**, the precise act clause
7(d) prohibits and 9(b) names. A probe is not an observation of the prohibited act; it *is* the
prohibited act, performed once. "We only did it to document it" is not a defence available under 7(d),
and "no env change, no new path built" is irrelevant — the breach is the request, not the config.

**PERMITTED SUBSTITUTE — APPROVED, and it yields the same documentation with zero requests to Seek:**
1. Record that `AETHER_ENABLE_SEEK` is absent from `.env` (0 occurrences) → gate OFF.
2. Record that `build_live_registry()` excludes `seek` while `_COMPLIANCE_GATED` retains it
   (`adapter_registry.py:38`).
3. Call `GET /agents/scout/sources/availability` **on production** — a first-party Aether endpoint,
   genuinely read-only, no outbound traffic to Seek — and record the `seek` row's `available:false` and
   its `reason` string. This documents "current behaviour" authoritatively.
4. Cite `seek_adapter.py:55-76,300-330` for what the path *would* do, statically.

### Sub-item (iii) — §7.5, verify `aether-discovery.timer` and sourcing volume from ALREADY-LICENSED sources: **APPROVED**

No `.env` change, no new source, no destructive or irreversible operation, no PROTECTED-list contact.
This is exactly the compliant work D-0034 directs sourcing volume toward. I independently confirmed the
timer is live **[VERIFIED 2026-07-31T17:24Z]**: `aether-discovery.timer` active, last run
`2026-07-31T17:01:02Z`, next `2026-07-31T17:30:58Z`, units at `/etc/systemd/system/aether-discovery.{service,timer}`.

**Conditions of this approval:** (1) `AETHER_ENABLE_SEEK` must not be set, not even transiently or in a
test shell; (2) volume must be measured over the licensed sources only (Adzuna AU, Greenhouse, Lever,
Ashby, Workable, Remotive, RemoteOK) with the active-feed filter applied, so legacy Seek rows are
excluded as D-0034 requires; (3) the count must be reported **honestly even if it is below threshold** —
a low number is a finding to escalate, never a reason to reach for Seek.

---

## 6. Blast radius

**If this refusal is WRONG:** one job source stays disabled. The already-licensed sources (Adzuna AU,
Greenhouse, Lever, Ashby, Workable, Remotive, RemoteOK) continue to supply the feed. The cost is
recoverable at any time by flipping one env flag once a consent or licence exists — D-0034 designed the
gate precisely so this is a one-line, no-code-change reversal. **Cost: bounded, reversible, visible.**

**If an approval here were WRONG:** this is a commercial product onboarding **paying Australian
customers tomorrow**. The exposure is (1) contractual breach of Seek's Terms by the operator, in an
Australian jurisdiction, against a large domestic incumbent with an obvious commercial interest in the
breach; (2) a **second** breach against the vendor via WebScraping.AI §6.2's false authorization
warranty, with §13 indemnity meaning the operator absorbs any Seek claim against the vendor too;
(3) IP block, account termination, or legal action from Seek — and clause 9(d) makes circumvention
independently sanctionable; (4) job data of **unclear provenance shown to paying users**, who would be
paying for a feed that could vanish or be enjoined mid-subscription. **Cost: unbounded, not reversible
by us, and it lands on the operator personally.**

The asymmetry is stark and it runs one way. **Given a categorical ToS prohibition, no consent, no
vendor licence, and a non-existent credential, refusal is the only defensible call the day before
taking money from customers.**

---

## 7. What would change my mind — precisely

Any **one** of these, filed in-repo with counterparty, date, scope and expiry, reopens this immediately
and I would approve on it:

1. **Written consent from SEEK Limited** naming Aether or its operating entity, authorizing automated
   collection of the specific paths and uses in question. This is the exit clause 7(d) itself names
   ("except with our prior written consent"). Nothing less closes the point.
2. **Admission to Seek's own published partner API programme** (`https://talent.seek.com.au/partners/terms-of-use`)
   with sourcing done through that interface in compliance with its terms — this engages clause 9(b)'s
   "specific technical interface" carve-out. Caveat to check *before* building: it is an
   employer/advertiser-side interface, so whether it can lawfully supply job-seeker search data is
   itself an open question that must be answered first.
3. **A vendor licence that actually exists** — a contract term from Firecrawl or WebScraping.AI, in
   writing, either granting a licence to seek.com.au content or warranting the vendor has cleared
   automated access with Seek and will indemnify Aether for it. Their current public Terms say the
   opposite (§2.3, §2.4). A salesperson's email is not sufficient; it must be a term that displaces
   WebScraping.AI §4.4/§6.2 and Firecrawl's indemnity, because a vendor cannot both disclaim
   responsibility and be the source of permission.
4. **A material change in Seek's published position** — clause 7(d)/9(b) removed or amended, or
   robots.txt opened for these paths. Re-fetch both and re-adjudicate.

**Explicitly NOT sufficient, and I will reject these if re-presented:** a legal opinion that the risk is
commercially acceptable; low volume or low frequency (7(d) is categorical, not a rate limit — a smaller
violation is still a violation); routing through a further intermediary or a proxy pool; presenting a
different user-agent; the argument that the data is "publicly accessible" (7(d) governs the *method* of
collection, not the visibility of the page); or the fact that the Firecrawl path already exists in the
codebase (it is gated OFF and is on identical footing — §2.4).

---

## 8. What Workstream D may legitimately do without touching Seek

- **§7.5 as approved** — verify the discovery timer and measure real sourcing volume from the licensed
  sources under the three conditions in §5(iii).
- **§7.4 as corrected** — verify the availability wiring is already honest and backend-driven; do not
  rewire it to `/agents/scout/sources`.
- **The §5(ii) permitted substitute** — document the Seek path's current state statically plus one
  first-party `/agents/scout/sources/availability` call. No outbound Seek traffic.
- **Supply `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`** — D-0034 already identifies Adzuna AU as the licensed
  route to AU job volume and the adapter exists. This is the correct answer to "we need more AU jobs,"
  and it is an operator credential task, not a compliance question. **I pre-approve this in principle**;
  it still needs the normal `.env` change process, and I will sign it when presented.
- **Tune the licensed ATS/aggregator adapters** (Greenhouse, Lever, Ashby, Workable, Remotive,
  RemoteOK) for coverage and freshness.
- **Make the UI and docs honest** that Seek is compliance-disabled and why — including surfacing the
  backend `reason` string to users if the orchestrator wants the disabled state explained rather than
  merely shown.

---

**Signed:** risk-officer sub-agent, GOLD-MASTER-V4 Workstream D §7.2
**2026-07-31T17:26:18Z** · HEAD `fb7bae6fc1aaf71338ef92bee23cbd314fd6067b`
I did not execute any change and did not author the proposal I ruled on. No agent message was treated
as consent. Governance copy: `uat/reports/evidence/launch-ready/governance/ADR-SEEK-V3-ruling-20260731.md`
