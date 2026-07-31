# Seek/Firecrawl — Independent Risk-Officer Verification Log

**Run:** GOLD-MASTER-V2 · Phase 0
**Role:** Acting risk-officer (§0.2/§0.4) — sole approver of risky changes for this run
**Adjudicator:** independent verifier; NOT the researcher who produced `seek-research.md`
**Log opened (UTC):** 2026-07-30T23:05:37Z
**Log closed (UTC):** 2026-07-30T23:12:00Z
**Ruling:** **REFUSED** — see `docs/delivery/ADR-SEEK-FIRECRAWL.md`

Scope discipline observed: no source code modified, no `.env` modified, no feature flag
changed, no pytest run, no headless browser launched. All probes were read-only.

Evidence tags: **[VERIFIED]** = I obtained it myself this run (file:line, or URL + retrieval
timestamp). **[INFERRED]** = reasoning over verified facts. **[ASSUMED-PENDING-PROBE]** = prior
testimony I could not independently re-confirm this run.

---

## 1. What I was asked to re-verify, and what I found

| # | Claim under test | My independent finding |
|---|---|---|
| 1 | ADR-P6-SEEK text | **[VERIFIED]** quoted verbatim below from `DECISIONS.md:1020–1058` |
| 2 | Seek robots.txt content | **[VERIFIED]** fetched fresh 2026-07-30T23:05:47Z; raw file reproduced below. Researcher's summary is **substantially right but imprecise** — see §3.2 correction |
| 3 | Adapter fetches Seek content via Firecrawl | **[VERIFIED]** `seek_adapter.py:65–75`, `316–318`, `341–368` |
| 4 | Firecrawl makes no licensed-intermediary representation | **[VERIFIED]** — and it is **stronger than the researcher reported**: Firecrawl's ToS affirmatively *prohibits* the use proposed. See §4 |
| 5 | Gate defaults OFF; Seek out of live rotation | **[VERIFIED]** `adapter_registry.py:37–39, 60–65, 68–79`; live prod process env confirms flag NOT-SET |

I also surfaced **two material findings the researcher did not report** (§5, §6) and **one
correction against the researcher's own conclusion** (§3.2). Both directions were pursued.

---

## 2. ADR-P6-SEEK — verbatim, quoted by me from source

**Source:** `/home/ubuntu/github_repos/aether-job-career-agent/docs/delivery/DECISIONS.md:1020–1058`
**Read (UTC):** 2026-07-30T23:05:40Z **[VERIFIED]**

```
## D-0034 — ADR-P6-SEEK: Seek scraping is ToS-prohibited; sourcing volume moves to licensed/official APIs

**Date:** 2026-07-16 · **Author:** Phase 6 orchestrator (researcher + fixer-hard) · **Status:** Adopted

**Context.** Phase 6 PROBE-13 and a dedicated live-research pass (`uat/reports/evidence/phase6/seek-tos-check.md`)
established that automated scraping of seek.com.au is explicitly prohibited: Seek's Terms of Service
clause 4(d) bans automated data gathering without written consent, and Seek's `robots.txt` blocks
`*/job/` and `/api/jobsearch/` and names `anthropic-ai` (alongside GPTBot/Bytespider) as disallowed
agents. Production was, at the time, sourcing Seek jobs via a Firecrawl-based scraper — a live compliance
exposure, not a hypothetical one. Simultaneously, `GAP-P6-SRC-001` required restoring job-sourcing volume
(a pre-fix baseline of only 6 live jobs across 4 sources failed the ≥25-job threshold).

**Decision.** Aether must **not** add to or continue automated scraping of seek.com.au. The `SeekAdapter`
is moved behind a compliance gate (`AETHER_ENABLE_SEEK`, default **OFF**) and excluded from the live
adapter registry (`apps/api/app/services/discovery/adapter_registry.py`) by construction — the scout
agent's live sync path cannot reach it unless the flag is explicitly set truthy. Sourcing volume is
restored instead through **ToS-compliant sources only**: Adzuna AU (a licensed aggregator API, optional
`ADZUNA_APP_ID`/`ADZUNA_APP_KEY`) plus official ATS job-board APIs (Greenhouse, Lever, Ashby, Workable)
and public aggregators (Remotive, RemoteOK). Historical Seek rows already in the database are retained
(never deleted) but are excluded from every user-facing "active feed" list by a display-time freshness/
source filter (`GAP-P6-DATA-001`), so stale/non-compliant data is never shown as live.

**Alternatives.** (a) Obtain Seek's written consent for automated access — rejected: no such consent
exists today and pursuing it is a business/legal process outside this engineering effort's scope or
timeline. (b) Keep scraping but reduce volume/frequency to "look" more compliant — rejected: the ToS
prohibition is categorical (any automated gathering without consent), not a rate-limit question; a
smaller violation is still a violation. (c) Drop Seek entirely (delete historical data too) — rejected:
unnecessarily destructive; retaining history with a display-time filter satisfies both compliance
(nothing new is scraped, nothing stale is shown as live) and non-destructiveness.

**Consequences.** `GAP-P6-SRC-001`/`GAP-P6-SRC-002`/`GAP-P6-DATA-001` are VERIFIED-CLOSED: a live
production re-probe after this fix shows 30 active-feed jobs across 5 compliant sources (up from the
6-job/4-source baseline), 100% fresh within 30 days, 0 duplicate URLs, 0 Seek rows in the active feed —
while 149 legacy Seek rows remain retrievable via an explicit `include_stale=true` query, proving the
filter does real work rather than coincidentally passing on empty data. The compliant-source margin is
real but not large (documented honestly in `docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md`'s GATE-07 risk
note) — Adzuna credentials, when supplied by an operator, would add independent source diversity.
**Reversible?** Yes — `AETHER_ENABLE_SEEK` is a single env flag; re-enabling Seek (if a consent
arrangement is ever reached) requires no code change, only a documented compliance decision.
```

**Observation on the ADR's own text [VERIFIED by reading]:** the words "direct", "raw scraping",
"HTML scraping", and "Firecrawl" appear **nowhere** in the Decision, Alternatives, or Consequences
sections as a carve-out. The Decision reads "must **not** add to or continue automated scraping of
seek.com.au" and the Alternatives section characterises the prohibition as **"categorical (any
automated gathering without consent)"**. The Context section states that production *was at that time
scraping Seek via Firecrawl* and calls that "a live compliance exposure, not a hypothetical one" —
i.e. **the Firecrawl path is the exact configuration this ADR was written to stop.**

---

## 3. Seek robots.txt — my own fresh retrieval

### 3.1 Retrieval record [VERIFIED]

```
Request 1: https://www.seek.com.au/robots.txt
  Issued (UTC): 2026-07-30T23:05:37Z
  Response:     HTTP/2 308 → location: https://au.seek.com/robots.txt
  Headers of note: server: cloudflare · set-cookie: __cf_bm=... (Cloudflare Bot Management)
                   cf-ray: a23802694c536c24-PDX · date: Thu, 30 Jul 2026 23:05:40 GMT

Request 2: https://au.seek.com/robots.txt  (followed redirect)
  Issued (UTC):    2026-07-30T23:05:47Z
  Completed (UTC): 2026-07-30T23:05:47Z
  HTTP 200 · 853 bytes
  sha256: 32fbbb98f660e636e106580d33f7aba4f43b68edbdeac916acc9da64d2ebfad8
  Local copy: <scratchpad>/au-seek-robots.txt
```

### 3.2 RAW robots.txt, byte-for-byte as retrieved [VERIFIED 2026-07-30T23:05:47Z]

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

### 3.3 Exactly what this says about the three items I was asked about [VERIFIED]

- **`*/job/`** — `Disallow: */job/` appears **twice**: once in the `User-agent: *` group (line 10 of
  the file) and again in the group whose members include **`anthropic-ai`** (line 36). Job-detail
  paths are closed to the default crawler *and* re-closed, specifically and by name, to `anthropic-ai`.
- **`/api/jobsearch/`** — `Disallow: /api/jobsearch/` in the `User-agent: *` group. Alongside
  `Disallow: /graphql`, this is Seek closing its **programmatic job-data interfaces** to crawlers.
- **`anthropic-ai`** — named explicitly, in a group headed "# Exceptions" and shared with
  `Bytespider`, `CCBot`, `Diffbot`, `Google-Extended`, `omgili`, `GPTBot`. That group's rules are
  `Disallow: /companies` and `Disallow: */job/`. Seek has singled out AI/LLM crawlers as a class and
  closed company and job pages to them by name.

### 3.4 CORRECTION AGAINST THE PRIOR REPORT — issued against my own ruling's convenience

The researcher's `seek-research.md` summary line "**robots.txt blocks scraping? Yes**" is too broad
for the specific URL this adapter fetches, and I record the correction rather than let a ruling rest
on an overstatement:

- The adapter's live fetch target is `https://www.seek.com.au/jobs?keywords={q}&where={loc}`
  **[VERIFIED `seek_adapter.py:316–318`]**.
- The `User-agent: *` group contains `Disallow: *?` **but also** `Allow: *?keywords`.
- **[INFERRED]** Under RFC 9309 §2.2.2 most-specific-match precedence (longest matching pattern wins;
  ties resolve to Allow), `Allow: *?keywords` beats `Disallow: *?` for that URL. Also **[INFERRED]**
  under RFC 9309 §2.2.1 only the *single most specific* matching user-agent group applies, so a
  crawler identifying as `anthropic-ai` is governed **only** by `Disallow: /companies` +
  `Disallow: */job/` — the `*` group's `Disallow: *?` would not bind it.
- **Therefore: robots.txt does not, on its face, forbid the specific search URL the adapter requests.**
  Any REFUSE that claimed otherwise would be wrong, and I decline to make that claim.

**Why the correction does not change the ruling — it sharpens it.** What robots.txt *does*
unambiguously forbid to `anthropic-ai` is `*/job/`: the job postings themselves. The adapter obtains
those very postings — title, advertiser, location, teaser, bullet points, listing date — by parsing
the `window.SEEK_REDUX_DATA` JSON island embedded in the search page **[VERIFIED
`seek_adapter.py:78–118`]**, and then synthesises `sourceUrl = https://www.seek.com.au/job/{id}`
for each one **[VERIFIED `seek_adapter.py:135`]**. That is the content behind the disallowed path,
and the content served by the disallowed `/api/jobsearch/` endpoint, harvested from an incidentally
permitted page. **[INFERRED]** Extracting a disallowed resource's payload from a permitted wrapper is
compliance in form and non-compliance in substance; a "we only fetched the URL you forgot to block"
defence is not one this project should choose to rely on. The robots.txt leg is therefore
**supporting evidence of the site owner's expressed intent**, not the load-bearing leg. The
load-bearing legs are §4 and §5.

---

## 4. Firecrawl — is "licensed intermediary" accurate? [VERIFIED, and the answer is worse than reported]

### 4.1 Retrievals [VERIFIED]

| URL | Retrieved (UTC) | Status | Size |
|---|---|---|---|
| `https://www.firecrawl.dev/terms-of-service` | 2026-07-30T23:06:41Z | 200 | 443,159 B |
| `https://docs.firecrawl.dev/llms.txt` | 2026-07-30T23:06:41Z | 200 | 24,827 B |
| `https://www.firecrawl.dev/robots.txt` | 2026-07-30T23:06:41Z | 200 | 366 B |

### 4.2 Absence probes over Firecrawl's own Terms of Service [VERIFIED 2026-07-30T23:06:41Z]

Case-insensitive occurrence counts across the full de-tagged ToS text:

| Phrase | Hits |
|---|---|
| `licensed intermediar` | **0** |
| `on your behalf` | **0** |
| `website owner` | **0** |
| `site owner` | **0** |
| `target site` | **0** |
| `robots.txt` | **0** |

Firecrawl nowhere represents that it is licensed by, has permission from, or clears terms with the
sites its customers point it at.

### 4.3 What Firecrawl's ToS DOES say — verbatim [VERIFIED 2026-07-30T23:06:41Z]

From the **"Prohibited Activities"** enumeration:

> "Use the Services for any unlawful activities or **in violation of any laws, regulations, or
> contractual provisions**, or to induce others to do or engage in the same"

From the liability section:

> "Where our Services incorporate or utilize any information, software, or content of a third party,
> **you waive any liability or claim against us** based upon that information, software, or content —
> including based upon the negligence of that third party."

From "Limited Use of Services":

> "In no way should your use of the Services be construed to diminish our intellectual property rights
> or be construed as **a license or the ability to use the Services in any context other than as
> expressly permitted under this Agreement**."

### 4.4 Finding

**[VERIFIED]** The "licensed intermediary" premise is not merely unsupported — it is **contractually
inverted**. Firecrawl's own agreement (a) assigns the customer sole responsibility for compliance with
third-party **contractual provisions**, (b) prohibits using the Services in violation of them, and
(c) waives Firecrawl's liability for third-party content. Seek's Terms of Service are a contractual
provision. **[INFERRED]** Therefore, using Firecrawl to gather Seek job data contrary to Seek's terms
would breach *Firecrawl's* agreement as well as Seek's — the intermediary adds a second counterparty
to the exposure rather than absorbing the first.

**[VERIFIED]** `docs.firecrawl.dev/llms.txt` contains exactly one compliance-adjacent entry —
"Lockdown Mode: Cache-only scrape mode for compliance and air-gapped environments. No outbound
traffic." — which is a *customer-side egress control*, not a target-site permission scheme.

**[ASSUMED-PENDING-PROBE]** The researcher's claim that Firecrawl "respects robots.txt rules set for
the 'FirecrawlAgent' directive" was **not reproducible** in the pages I retrieved (0 hits for
`robots.txt` in the ToS; no robots discussion in `llms.txt`). I neither confirm nor deny it. It is
immaterial either way: Seek's robots.txt does not name `FirecrawlAgent`, so a Firecrawl fetch falls
under `User-agent: *` — which is precisely the generic-crawler group, not a permission grant.

### 4.5 The prompt's own wording, examined [VERIFIED `/home/ubuntu/aether-gold-master-execution.md:124–128`]

> "`SeekAdapter` exists and uses the Firecrawl API (**licensed via Abacus.AI VM metadata credentials**
> — `ABACUS_API_KEY` + `FIRECRAWL_API_URL` auto-discovered from IMDS) … Because the adapter uses the
> Firecrawl crawl API (**a licensed intermediary**, not raw scraping), enabling it is the intended
> production path."

**[INFERRED]** These two uses of "licensed" are different words. The first is true and irrelevant:
Aether holds valid credentials, i.e. Aether is a **licensed customer of Firecrawl**. The second is the
one that would matter and is unevidenced: it asserts Firecrawl is **licensed by Seek** to obtain and
redistribute Seek's listings. The first does not imply the second, and §4.2/§4.3 show Firecrawl
expressly declines the second role. The premise fails on an equivocation.

---

## 5. What the adapter actually does — including two facts not previously reported

### 5.1 It obtains Seek's content; Firecrawl is only the transport [VERIFIED]

`seek_adapter.py:65–75` — the HTTP call:

```python
response = httpx.post(
    f"{firecrawl_url}/v1/scrape",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={"url": search_url, "formats": ["rawHtml"]},
    timeout=60,
)
```

`search_url` is built at `seek_adapter.py:316–318` as
`https://www.seek.com.au/jobs?keywords={query}&where={location}`; the loop paginates `&page=N` up to
`AETHER_SEEK_MAX_PAGES` (default 10) / `AETHER_SEEK_MAX_JOBS` (default 100)
**[VERIFIED `seek_adapter.py:320–366`]**. The response HTML is parsed for `window.SEEK_REDUX_DATA`
**[VERIFIED `:87`]**, walked for job records **[VERIFIED `:99–118`]**, and each record is mapped to a
job row carrying `sourceUrl = https://www.seek.com.au/job/{id}` **[VERIFIED `:135`]**.

**[INFERRED]** The data crossing into Aether's database is Seek's job listing content, at up to 100
listings per query per run. Substituting Firecrawl for `httpx.get(seek_url)` changes *which IP issues
the TCP connection*. It does not change **who obtains the data** (Aether — Firecrawl is a
pass-through acting on Aether's instruction, for Aether's account, delivering the payload to Aether),
**what data is obtained** (Seek's listings), **what is done with it** (persisted and shown to Aether's
users), or **whether Seek permitted it**. The file's own module docstring is candid about the nature
of the operation: `seek_adapter.py:1` reads *"Seek.com.au discovery adapter (P2-S02) — LIVE via
Firecrawl API"* and `:3` *"**Scrapes** real job listings from seek.com.au"*.

### 5.2 NEW FINDING (not in the researcher's report): the codebase records Seek actively blocking Aether, and the adapter is engineered around the block [VERIFIED]

- `adapter_registry.py:11–12`: *"Seek's ToS and robots.txt prohibit automated scraping (seek-tos-check.md
  verdict SCRAPING-PROHIBITED; **probe-13 10/10 cards HTTP 403**)"*
- `seek_adapter.py:59–61`: *"a single search-page scrape yields the full job list — far more reliable
  than scraping each job detail page (**Seek blocks direct `/job/<id>` fetches with an interstitial
  error page**)"*
- `seek_adapter.py:312–315`: *"The keyword/where query form is used rather than the
  `/<slug>-jobs/in-<slug>` path form: **the latter redirects to au.seek.com and scrapes an error page**
  (a root cause of discovery being stuck at persisted=0)"*
- `seek_adapter.py:342–349`: explicit branch for *"No data island → Seek served an interstitial/error
  page … likely blocked"*
- My own retrieval independently confirms live bot management on the origin: `server: cloudflare`,
  `set-cookie: __cf_bm=…` **[VERIFIED 2026-07-30T23:05:40Z]**

**[INFERRED]** Read together, these are a record of Seek deploying technical access controls against
this exact class of access (403s, interstitials, redirect traps), and of the adapter's URL form and
parse strategy having been **selected to defeat those controls**. Firecrawl's marketed capability set
("handles proxies, anti-bot, JavaScript rendering") is the mechanism by which the block is overcome.
This reframes the question materially: it is not "did we honour an advisory file", it is "would we
deliberately route around an access control the site owner erected against us". That is a
categorically higher exposure — contract breach at minimum, with adjacent unauthorised-access and
misleading-conduct considerations under Australian law that are **for counsel, not for me**, but whose
mere availability is disqualifying at this run's risk appetite. **This finding alone would be
sufficient to refuse.**

### 5.3 NEW FINDING (not in the researcher's report): the ToS artifact ADR-P6-SEEK relies on is MISSING [VERIFIED]

ADR-P6-SEEK cites `uat/reports/evidence/phase6/seek-tos-check.md` as the basis for "clause 4(d)".

```
$ find uat -iname "*seek*"
uat/reports/evidence/gold-master-v2/phase0/seek-research.md      # this run's file only
$ git log --oneline --all -- 'uat/reports/evidence/phase6/seek-tos-check.md'
(no output)
```

The cited artifact is **not present in the repository and has no git history** **[VERIFIED
2026-07-30T23:08:00Z]**.

I additionally attempted seven independent retrievals of Seek's Terms of Service this run
**[VERIFIED 2026-07-30T23:06:27Z and 23:07:39Z]**:

| URL | Result |
|---|---|
| `https://www.seek.com.au/about/terms` | 404 |
| `https://au.seek.com/about/terms` | 404 |
| `https://au.seek.com/legal/terms` | 404 |
| `https://au.seek.com/pages/legal/terms-of-service` | 404 |
| `https://au.seek.com/pages/about/terms-and-conditions` | 404 |
| `https://www.seek.com.au/pages/about/terms-and-conditions` | 404 |
| `https://help.seek.com.au/s/article/seek-terms-and-conditions` | 200, but JS-rendered shell — 27 characters of extractable text ("Welcome to Job Seeker Help!"); 0 hits for `automat`, `scrap`, `robot`, `written consent`, `4(d)` |

Rendering that page requires a headless browser, which this run's charter forbids (2-CPU box).

**Ruling on this gap, stated plainly:** the specific string "clause 4(d)" is
**[ASSUMED-PENDING-PROBE]** — prior testimony whose cited artifact does not exist and which I could
not re-retrieve. **I therefore place no weight on it.** A REFUSE that leaned on an unverifiable
clause number would be exactly the sloppiness this role exists to prevent. The ruling below rests
solely on §3 (fresh robots.txt), §4 (fresh Firecrawl ToS), and §5.1–5.2 (source code) — all
**[VERIFIED]** this run. I record separately that this gap is **itself a finding against
ADR-P6-SEEK's evidentiary hygiene**, and it cuts *toward* caution, not away from it: the absence of a
retrievable permission is not a permission.

---

## 6. Gate state and production counterfactual

### 6.1 Gate defaults OFF — verified in code and in the live process [VERIFIED]

`adapter_registry.py:37–39`:

```python
_COMPLIANCE_GATED: dict[str, tuple[type[BaseAdapter], str]] = {
    "seek": (SeekAdapter, "AETHER_ENABLE_SEEK"),
}
```

`adapter_registry.py:60–65` builds `_COMPLIANT_ADAPTERS` by *excluding* every key in
`_COMPLIANCE_GATED`; `:68–79` re-adds a gated source only when the flag is in
`{"1","true","yes","on"}`; `:84` evaluates `ADAPTERS = build_live_registry()` at import.

**Live production check (read-only, no mutation):** the running `aether-api` process
(PID 234329, 80 environment variables) has **`AETHER_ENABLE_SEEK` NOT-SET**
**[VERIFIED 2026-07-30T23:07:50Z via `/proc/234329/environ`]**. `apps/api/.env` contains no `SEEK`
key **[VERIFIED same timestamp]**. Seek is not in the live scout rotation right now, and nothing I
did changed that.

### 6.2 Counterfactual — is volume adequate without Seek? [VERIFIED]

From `PROD-DB-STATE.md:159–174` (this run's Phase-0 production probe):

| Source | Count |
|---|---|
| greenhouse | 21 |
| ashby | 16 |
| lever | 10 |
| remoteok | 3 |
| remotive | 1 |
| **seek** | **0** |
| **Total** | **51** |

**[INFERRED]** 51 jobs across 5 compliant sources, versus the 30/5 recorded in ADR-P6-SEEK's
Consequences at Phase 6 — compliant sourcing has grown ~70% since the gate closed, with zero Seek
rows. The compliant path is not stagnating; it is working.

### 6.3 An untapped compliant volume lever exists RIGHT NOW [VERIFIED]

`AdzunaAdapter` is implemented and **already in the live registry**
**[VERIFIED `adapter_registry.py:49`]** — Adzuna is a licensed AU aggregator that legitimately
resells Seek-class listings under commercial agreement. It contributes **0 of the 51 rows** because
`ADZUNA_APP_ID` / `ADZUNA_APP_KEY` are absent from the production environment
**[VERIFIED `PROD-DB-STATE.md` by_source breakdown has no adzuna entry; corroborated by
`docs/delivery/archive/PHASE7-CLAIM-LEDGER.md:53`, which records the same absence at Phase 7]**.

**[INFERRED]** This is decisive for the cost-of-refusing analysis. The run's actual goal is more
Australian job volume. There is a fully compliant, already-coded, zero-new-code route to exactly that
outcome, blocked only on an operator obtaining two API credentials. Refusing Seek does not leave the
product without a path; it redirects the run to the path that was always the right one.

---

## 7. Decision framework — my reasoning, point by point

**Q1. Does routing a fetch through a third-party crawling API change WHO obtains the data, or WHETHER
the target site's ToS permits it?**
**No, on both counts. [INFERRED from §4, §5.1]** Firecrawl acts on Aether's instruction, under
Aether's API key, and returns the payload to Aether, which persists it and shows it to Aether's users.
Aether is the party obtaining and using the data throughout; Firecrawl is transport. ToS obligations
attach to the party gathering and using the data, and no term of Seek's is addressed to the identity
of the intermediate IP. If it were otherwise, every site's terms would be defeatable by inserting one
proxy — which is a reductio, not an argument. Is "licensed intermediary" accurate on the evidence?
**No. [VERIFIED §4.2–4.4]** Zero supporting representations, and an express prohibition running the
other way.

**Q2. Seek's robots.txt naming `anthropic-ai`.**
Weighed directly, and weighed *narrowly* so it is not overweighted. **[VERIFIED §3.2]** Seek listed
`anthropic-ai` alongside GPTBot, CCBot, Bytespider, Diffbot, Google-Extended and omgili and closed
`/companies` and `*/job/` to them. That is a job board making an unusually explicit, unusually
current statement about a specific class of automated consumer. Aether is an Anthropic-model-driven
system, and the postings it would ingest are the `*/job/` content. **[INFERRED]** Enabling this would
put an Anthropic-model-driven product in the position of taking, at scale, precisely the content the
site owner named that class of agent to refuse. There is a version of this that is a technicality
about pattern matching (§3.4 — the search URL is not itself disallowed). There is no version of it in
which the site owner's intent is unclear. Where a run is choosing whether to *start* doing something,
unmistakable owner intent is the thing that governs, not the gap in their pattern list. It is also
squarely reputational: an AI career product that harvests a job board which asked AI crawlers not to,
cannot credibly ask its own users to trust its honesty claims elsewhere in this run.

**Q3. ADR precedence (§1.3).**
**[VERIFIED]** The prompt at `/home/ubuntu/aether-gold-master-execution.md:150–152` sets the order
"`docs/delivery/DECISIONS.md` ADRs > wireframes > architecture doc > implementation guide > research
docs" and then states "ADR-P6-SEEK's scraping prohibition does NOT apply to the Firecrawl API path —
it applies to direct HTML scraping." **[VERIFIED §2]** No such distinction exists anywhere in
ADR-P6-SEEK; the ADR calls the prohibition "categorical (any automated gathering without consent)",
and its Context identifies the *Firecrawl-based scraper* as the live exposure being closed. So the
prompt's carve-out is not an ADR provision — it is the prompt author's gloss on an ADR that says the
opposite. **By the prompt's own precedence rule, the ADR governs and the gloss loses.** The ADR is
additionally the evidence-based side of the pair (its factual claims about robots.txt reproduce
against my fresh fetch), while the gloss rests on an equivocation refuted at §4.5. It loses on
precedence and on merit.

**Q4. Counterfactual — is volume adequate without Seek?**
**Yes. [VERIFIED §6.2]** 51 jobs across 5 compliant sources today, up from 30/5 at Phase 6, with 0
from Seek. Volume is adequate and trending up on the compliant path alone.

**Q5. Cost of refusing, and is there a compliant path to the same outcome?**
The product loses AU-specific listing breadth — a real cost, honestly acknowledged, since Seek is the
dominant Australian board and Aether's user is Melbourne-based. **[VERIFIED §6.3]** But a compliant
path to the same outcome already exists in the codebase and is switched off for want of credentials:
Adzuna AU, a licensed aggregator, live in the registry, contributing zero only because
`ADZUNA_APP_ID`/`ADZUNA_APP_KEY` are unset. The cost of refusing is therefore not "no AU volume"; it
is "obtain two credentials from a licensed reseller, or approach Seek's own partner programme". Those
are days of business process, not an engineering impossibility — and they produce a product that can
be sold, audited and defended.

**Balance.** Every one of the five questions resolves against enabling, and two of them (§4.4, §5.2)
would each be independently sufficient. There is no reading of this evidence on which enabling is the
lower-risk choice.

---

## 8. Ruling

**REFUSED.** `AETHER_ENABLE_SEEK` must remain unset in production. Full binding ruling, compliant
alternatives, conditions to revisit and residual risks: `docs/delivery/ADR-SEEK-FIRECRAWL.md`
(STATUS: REFUSED, adjudicated 2026-07-30T23:12:00Z).

Consequential instructions for the run are in that ADR §9 — in summary: §6/W-D steps 2–4 are
withdrawn; gate **G-D** is unachievable as written and must be withdrawn or restated; the Jobs-screen
"(unavailable)" label for Seek is **truthful and backed by a live backend endpoint** and must **not**
be removed; and the run's AU-volume objective is redirected to Adzuna credentials.

---

## 9. Config and data footprint of this adjudication

- **Config changed:** none. No `.env`, no feature flag, no systemd unit, no source file.
- **Data left in production:** none. All production access was read-only (one `/proc/<pid>/environ`
  read, and Phase-0's pre-existing DB probe artifacts).
- **Network calls made:** 13 outbound GETs to `seek.com.au` / `au.seek.com` / `help.seek.com.au` /
  `firecrawl.dev` / `docs.firecrawl.dev` — all retrievals of `robots.txt`, terms, and public
  documentation pages, made by me for compliance-assessment purposes. **No job data was fetched, and
  the SeekAdapter was not executed.**
- **Files written by me:** this log, and `docs/delivery/ADR-SEEK-FIRECRAWL.md` (rewritten to FINAL).
- **Scratch artifacts (not committed):** `au-seek-robots.txt` (sha256
  `32fbbb98f660e636e106580d33f7aba4f43b68edbdeac916acc9da64d2ebfad8`), `seek-robots-headers.txt`,
  Firecrawl ToS/docs captures — under this session's scratchpad. The full robots.txt is reproduced
  verbatim at §3.2 above, so this log is self-contained if the scratch copies expire.
- **Prohibitions observed:** no source modified · no `.env` touched · no flag enabled · no pytest run
  (baseline lock `/tmp/aether-pytest.lock` respected) · no headless browser launched.

**Adjudicator:** acting risk-officer, GOLD-MASTER-V2 · **Closed:** 2026-07-30T23:12:00Z
