# ADR-SEEK-FIRECRAWL — Seek.com.au sourcing via the Firecrawl API

**STATUS: REFUSED**

**Adjudicated by:** acting risk-officer (GOLD-MASTER-V2), §0.2/§0.4 sole approver of risky changes
**Adjudicated (UTC):** 2026-07-30T23:12:00Z
**Supersedes:** the DRAFT of this file dated 2026-07-30 (authored by the Phase-6 Evidence Agent /
researcher). This FINAL version is an **independent** adjudication: the signer is not the researcher
who produced the evidence, and every load-bearing fact below was re-obtained first-hand this run.
**Independent verification log:** `uat/reports/evidence/gold-master-v2/phase0/seek-risk-adjudication.md`
**Relationship to ADR-P6-SEEK (D-0034):** upholds and reinforces it; does not amend it.

**Ruling in one line:** `AETHER_ENABLE_SEEK` **must remain unset in production**. The execution
prompt's premise that Firecrawl is "a licensed intermediary" whose use places the adapter outside
ADR-P6-SEEK's prohibition is **factually incorrect** and is rejected.

Evidence tags used throughout: **[VERIFIED]** = obtained first-hand this run (file:line, or URL +
retrieval timestamp) · **[INFERRED]** = reasoning over verified facts · **[ASSUMED-PENDING-PROBE]** =
prior testimony not re-confirmed this run and given no weight.

---

## 1. Question put to the risk officer

The GOLD-MASTER-V2 execution prompt (§1.2, §1.3, §6.1) directs that Seek.com.au sourcing be **enabled**
in production via `AETHER_ENABLE_SEEK=true`, on the stated premise
**[VERIFIED `/home/ubuntu/aether-gold-master-execution.md:124–128, 150–152`]**:

> "`SeekAdapter` exists and uses the Firecrawl API (licensed via Abacus.AI VM metadata credentials …).
> … Because the adapter uses the Firecrawl crawl API (**a licensed intermediary, not raw scraping**),
> enabling it is the intended production path."

> "ADR-P6-SEEK's scraping prohibition **does NOT apply to the Firecrawl API path** — it applies to
> direct HTML scraping."

**Should the risk officer approve setting `AETHER_ENABLE_SEEK=true` in production?**

---

## 2. ADR-P6-SEEK — verbatim

Quoted first-hand from `docs/delivery/DECISIONS.md:1020–1058`, read 2026-07-30T23:05:40Z **[VERIFIED]**.

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

**Critical reading [VERIFIED by inspection of the above]:** the words "direct", "raw scraping" and
"HTML scraping" appear **nowhere** in ADR-P6-SEEK as a carve-out. Its Alternatives section states the
prohibition is **"categorical (any automated gathering without consent), not a rate-limit question"**.
Its Context identifies **the Firecrawl-based scraper itself** as "a live compliance exposure, not a
hypothetical one". The prompt's asserted Firecrawl exemption is therefore not a reading of this ADR —
it is a reversal of the ADR's own stated subject matter.

---

## 3. Seek robots.txt — freshly retrieved by the adjudicator

**URL:** `https://www.seek.com.au/robots.txt` → HTTP 308 → `https://au.seek.com/robots.txt`
**Retrieved (UTC):** 2026-07-30T23:05:47Z · HTTP 200 · 853 bytes
**sha256:** `32fbbb98f660e636e106580d33f7aba4f43b68edbdeac916acc9da64d2ebfad8`
**Origin headers of note:** `server: cloudflare`, `set-cookie: __cf_bm=…` (Cloudflare Bot Management
active), `cf-ray: a23802694c536c24-PDX` **[VERIFIED 2026-07-30T23:05:40Z]**

Verbatim, byte-for-byte as retrieved **[VERIFIED]**:

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

**On the three items specifically asked about [VERIFIED]:**

- **`*/job/`** — `Disallow: */job/` appears **twice**: in the `User-agent: *` group, and again in the
  group headed by **`anthropic-ai`**. Job-detail paths are closed to the default crawler and closed
  again, by name, to `anthropic-ai`.
- **`/api/jobsearch/`** — `Disallow: /api/jobsearch/` (with `Disallow: /graphql`) in the
  `User-agent: *` group: Seek closing its **programmatic job-data interfaces** to crawlers.
- **`anthropic-ai`** — named explicitly, grouped with `Bytespider`, `CCBot`, `Diffbot`,
  `Google-Extended`, `omgili`, `GPTBot`; that group is disallowed `/companies` and `*/job/`. Seek has
  singled out AI/LLM crawlers as a class and closed job and company pages to them **by name**.

### 3.1 Correction issued against the prior draft — and against this ruling's own convenience

The DRAFT and `seek-research.md` summarised this as "robots.txt blocks scraping: yes". That is **too
broad for the specific URL this adapter requests**, and the correction is recorded rather than
suppressed:

- The adapter fetches `https://www.seek.com.au/jobs?keywords={q}&where={loc}`
  **[VERIFIED `seek_adapter.py:316–318`]**.
- The `*` group contains `Disallow: *?` **but also** `Allow: *?keywords`. **[INFERRED]** Under
  RFC 9309 §2.2.2 (most-specific match wins; ties to Allow), the Allow prevails for that URL. And
  **[INFERRED]** under §2.2.1 only the single most-specific user-agent group binds, so an
  `anthropic-ai` crawler is governed **only** by `Disallow: /companies` + `Disallow: */job/`.
- **Conclusion: robots.txt does not, on its face, forbid the exact search URL the adapter requests.**
  This ADR does not claim otherwise.

**Why this sharpens rather than weakens the refusal.** What robots.txt unambiguously closes to
`anthropic-ai` is `*/job/` — the postings themselves. The adapter obtains exactly those postings by
parsing the `window.SEEK_REDUX_DATA` JSON island embedded in the search page
**[VERIFIED `seek_adapter.py:78–118`]** and synthesises `https://www.seek.com.au/job/{id}` for each
**[VERIFIED `seek_adapter.py:135`]** — i.e. it takes the content behind the disallowed path, and the
content served by the disallowed `/api/jobsearch/` endpoint, out of an incidentally permitted wrapper.
**[INFERRED]** That is compliance in form and non-compliance in substance. "You blocked the job pages
but forgot to block the page that embeds all the job data" is not a defence this product should elect
to stand on. The robots.txt leg is accordingly treated here as **strong evidence of the site owner's
expressed intent**, not as the load-bearing leg. The load-bearing legs are §5 and §6.2.

---

## 4. Technical finding — what the adapter actually does

**[VERIFIED `apps/api/app/services/discovery/seek_adapter.py:65–75`]** the sole outbound call:

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

- `search_url` = `https://www.seek.com.au/jobs?keywords={query}&where={location}`, paginated `&page=N`
  to `AETHER_SEEK_MAX_PAGES` (default **10**) / `AETHER_SEEK_MAX_JOBS` (default **100**)
  **[VERIFIED `:312–321`, `:325–366`]**
- The returned `rawHtml` is searched for `window.SEEK_REDUX_DATA` **[VERIFIED `:87`]** and recursively
  walked for job records — id, title, advertiser, locations, teaser, bulletPoints, listingDate
  **[VERIFIED `:99–118`]**
- Each record becomes a job row with `sourceUrl = "https://www.seek.com.au/job/{id}"`
  **[VERIFIED `:135`]**, persisted and shown to Aether's users
- The module's own docstring: *"Seek.com.au discovery adapter (P2-S02) — **LIVE via Firecrawl API** …
  **Scrapes** real job listings from seek.com.au"* **[VERIFIED `:1–5`]**

**Finding [INFERRED from the above]:** the content obtained is **Seek's job data**, at up to 100
listings per query per run, regardless of which HTTP intermediary issues the request. Firecrawl is the
transport, not the acquirer: it acts on Aether's instruction, under Aether's API key, and returns the
payload to Aether for Aether's use. Swapping `httpx.get(seek_url)` for a Firecrawl `POST /v1/scrape`
changes **which IP opens the TCP connection** and nothing else that matters.

### 4.1 Aggravating finding — Seek actively blocks this access, and the adapter is built to get around it

Not reported in the DRAFT. All quotes **[VERIFIED]** from this repository's own source:

| Location | Text |
|---|---|
| `adapter_registry.py:11–12` | "Seek's ToS and robots.txt prohibit automated scraping (seek-tos-check.md verdict SCRAPING-PROHIBITED; **probe-13 10/10 cards HTTP 403**)" |
| `seek_adapter.py:59–61` | "a single search-page scrape yields the full job list — far more reliable than scraping each job detail page (**Seek blocks direct `/job/<id>` fetches with an interstitial error page**)" |
| `seek_adapter.py:312–315` | "The keyword/where query form is used rather than the `/<slug>-jobs/in-<slug>` path form: **the latter redirects to au.seek.com and scrapes an error page** (a root cause of discovery being stuck at persisted=0)" |
| `seek_adapter.py:342–349` | branch for "No data island → Seek served an interstitial/error page … **likely blocked**" |
| adjudicator's own fetch, 2026-07-30T23:05:40Z | origin returns `server: cloudflare` + `__cf_bm` bot-management cookie |

**[INFERRED]** These record Seek deploying technical access controls against this class of access
(403s, interstitials, redirect traps), and the adapter's URL form and parse strategy having been
**chosen to defeat them** — with Firecrawl's marketed "proxies, anti-bot, JavaScript rendering" as the
mechanism. This is not a question of honouring an advisory file. It is whether this run would
deliberately route around an access control the site owner erected against it. Legal characterisation
is for counsel, not for this office; but a matter that even raises unauthorised-access and
misleading-conduct questions under Australian law is disqualifying at this run's risk appetite.
**This finding alone is sufficient to refuse.**

---

## 5. Is Firecrawl a "licensed intermediary"? — No, and its own terms say the opposite

Retrieved first-hand 2026-07-30T23:06:41Z: `https://www.firecrawl.dev/terms-of-service` (HTTP 200,
443,159 B), `https://docs.firecrawl.dev/llms.txt` (HTTP 200, 24,827 B) **[VERIFIED]**.

### 5.1 Absence probes over Firecrawl's Terms of Service [VERIFIED 2026-07-30T23:06:41Z]

| Phrase (case-insensitive, full de-tagged ToS) | Occurrences |
|---|---|
| `licensed intermediar` | **0** |
| `on your behalf` | **0** |
| `website owner` | **0** |
| `site owner` | **0** |
| `target site` | **0** |
| `robots.txt` | **0** |

Firecrawl nowhere represents that it is licensed by, holds permission from, or clears terms with the
sites its customers direct it to.

### 5.2 What Firecrawl's terms DO say — verbatim [VERIFIED 2026-07-30T23:06:41Z]

From **"Prohibited Activities"**:

> "Use the Services for any unlawful activities or **in violation of any laws, regulations, or
> contractual provisions**, or to induce others to do or engage in the same"

From the waiver section:

> "Where our Services incorporate or utilize any information, software, or content of a third party,
> **you waive any liability or claim against us** based upon that information, software, or content —
> including based upon the negligence of that third party."

From "Limited Use of Services":

> "In no way should your use of the Services be construed to diminish our intellectual property rights
> or be construed as **a license or the ability to use the Services in any context other than as
> expressly permitted under this Agreement**."

`docs.firecrawl.dev/llms.txt` contains one compliance-adjacent entry only — *"Lockdown Mode:
Cache-only scrape mode for compliance and air-gapped environments. No outbound traffic."* — a
customer-side egress control, not a target-site permission scheme **[VERIFIED]**.

### 5.3 Finding

**[VERIFIED + INFERRED]** The "licensed intermediary" premise is not merely unsupported — it is
**contractually inverted**. Firecrawl (a) assigns the customer sole responsibility for third-party
**contractual provisions**, (b) expressly prohibits using the Services in violation of them, and
(c) waives its own liability for third-party content. Seek's Terms of Service are a contractual
provision. Using Firecrawl to gather Seek data contrary to Seek's terms would therefore breach
**Firecrawl's** agreement in addition to Seek's: the intermediary **adds a second counterparty to the
exposure rather than absorbing the first.**

**The equivocation at the heart of the prompt [VERIFIED `/home/ubuntu/aether-gold-master-execution.md:124–126`]:**
the prompt writes "the Firecrawl API (licensed via Abacus.AI VM metadata credentials)". That is true
and irrelevant — it means **Aether is a licensed customer of Firecrawl**. The premise that would
matter is that **Firecrawl is licensed by Seek** to obtain and redistribute Seek's listings. The first
does not imply the second, and §5.1–5.2 show Firecrawl expressly declining the second role. Two
different senses of "licensed" are doing the work of one. The premise fails.

**[ASSUMED-PENDING-PROBE]** The prior draft's claim that Firecrawl "respects robots.txt rules set for
the 'FirecrawlAgent' directive" was **not reproducible** in the pages retrieved this run and is given
no weight. It is immaterial regardless: Seek's robots.txt does not name `FirecrawlAgent`, so a
Firecrawl fetch falls under `User-agent: *` — a generic-crawler default, not a permission grant.

---

## 6. Gate state, and an evidentiary gap disclosed against interest

### 6.1 The gate defaults OFF and is currently OFF in production [VERIFIED]

`adapter_registry.py:37–39`:

```python
_COMPLIANCE_GATED: dict[str, tuple[type[BaseAdapter], str]] = {
    "seek": (SeekAdapter, "AETHER_ENABLE_SEEK"),
}
```

`:60–65` builds the live registry by *excluding* every gated key; `:68–79` re-adds one only when its
flag is in `{"1","true","yes","on"}`; `:84` evaluates `ADAPTERS = build_live_registry()` at import.
**Live production check (read-only):** the running `aether-api` process (PID 234329, 80 env vars) has
**`AETHER_ENABLE_SEEK` NOT-SET**, and `apps/api/.env` contains no `SEEK` key
**[VERIFIED 2026-07-30T23:07:50Z]**. Seek is not in the live scout rotation. Nothing in this
adjudication changed that.

### 6.2 Disclosed gap: ADR-P6-SEEK's cited ToS artifact does not exist, and "clause 4(d)" is given no weight

ADR-P6-SEEK cites `uat/reports/evidence/phase6/seek-tos-check.md` for the "clause 4(d)" prohibition.
That file is **absent from the repository and has no git history** **[VERIFIED 2026-07-30T23:08:00Z]**.
Seven independent attempts to retrieve Seek's Terms of Service this run returned 404 on six URLs; the
seventh (`help.seek.com.au`) returned a JS-rendered shell yielding 27 characters of text and zero hits
for `automat`, `scrap`, `robot`, `written consent`, or `4(d)` **[VERIFIED 2026-07-30T23:06:27Z and
23:07:39Z]**. Rendering it requires a headless browser, which this run's charter forbids.

**Consequence, stated plainly:** "clause 4(d)" is **[ASSUMED-PENDING-PROBE]** and **this ruling places
no weight on it**. A refusal leaning on an unverifiable clause number would be precisely the
sloppiness this office exists to prevent. The ruling rests entirely on §3 (fresh robots.txt), §4
(source code), §4.1 (active blocking) and §5 (fresh Firecrawl ToS) — all **[VERIFIED]** this run. The
gap is separately noted as a finding against ADR-P6-SEEK's evidentiary hygiene, and it cuts *toward*
caution: **the absence of a retrievable permission is not a permission.**

### 6.3 Counterfactual — sourcing volume without Seek [VERIFIED `PROD-DB-STATE.md:159–174`]

| Source | Count |
|---|---|
| greenhouse | 21 |
| ashby | 16 |
| lever | 10 |
| remoteok | 3 |
| remotive | 1 |
| **seek** | **0** |
| **Total** | **51** |

**[INFERRED]** 51 jobs across 5 compliant sources — up ~70% from the 30/5 recorded in ADR-P6-SEEK's
Consequences at Phase 6, with zero Seek rows. Compliant sourcing is adequate and growing.

**And an untapped compliant lever exists right now:** `AdzunaAdapter` is implemented and **already in
the live registry** **[VERIFIED `adapter_registry.py:49`]** — Adzuna is a licensed AU aggregator that
legitimately resells Seek-class listings under commercial agreement. It contributes **0 of 51 rows**
solely because `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` are absent from production **[VERIFIED
`PROD-DB-STATE.md` by-source breakdown; corroborated at `docs/delivery/archive/PHASE7-CLAIM-LEDGER.md:53`]**.
The run's real objective — more Australian volume — has a fully compliant, already-coded,
zero-new-code route that is blocked only on two credentials.

---

## 7. Reasoning against the decision framework

**7.1 Does routing through a third-party crawling API change WHO obtains the data, or WHETHER the
target's ToS permits it? — No, on both counts. [INFERRED from §4, §5]** Firecrawl acts on Aether's
instruction, under Aether's key, returning the payload to Aether, which persists it and serves it to
Aether's users. Aether is the acquiring and using party throughout. ToS obligations attach to the
party gathering and using the data; no term is addressed to the identity of the intermediate IP. Were
it otherwise, every site's terms would be defeated by inserting one proxy — a reductio, not an
argument. **Is "licensed intermediary" accurate on the evidence? No [VERIFIED §5.1–5.3]:** zero
supporting representations, and an express prohibition running the other way.

**7.2 Seek naming `anthropic-ai`. [VERIFIED §3, weighed directly]** Seek listed `anthropic-ai`
alongside GPTBot, CCBot, Bytespider, Diffbot, Google-Extended and omgili and closed `/companies` and
`*/job/` to them. Aether is an Anthropic-model-driven system, and `*/job/` content is exactly what it
would ingest. **[INFERRED]** Enabling this puts an Anthropic-model-driven product in the position of
taking, at scale, the precise content the site owner named that class of agent to refuse. §3.1 grants
that the *search URL* escapes the letter of the pattern list. Nothing makes the owner's *intent*
unclear. Where a run is deciding whether to **start** doing something, unmistakable owner intent
governs, not a gap in their pattern list. The reputational dimension is equally direct: an AI career
product that harvests a job board which asked AI crawlers not to cannot credibly ask its users to
trust its honesty claims anywhere else in this run.

**7.3 ADR precedence (§1.3). [VERIFIED]** The prompt itself sets "DECISIONS.md ADRs > wireframes >
architecture doc > implementation guide > research docs", then asserts a Firecrawl carve-out that
**appears nowhere in ADR-P6-SEEK** (§2) — an ADR which instead calls the prohibition "categorical" and
names the Firecrawl scraper as the exposure it was written to close. The carve-out is the prompt
author's gloss, not an ADR provision. **By the prompt's own precedence rule the ADR governs and the
gloss loses.** The ADR is also the evidence-based side of the pair — its robots.txt claims reproduce
against a fresh fetch — while the gloss rests on an equivocation refuted at §5.3. It loses on
precedence and on merit.

**7.4 Counterfactual — adequate volume without Seek? Yes. [VERIFIED §6.3]** 51 jobs / 5 compliant
sources, up from 30 / 5, with 0 from Seek.

**7.5 Cost of refusing, and a compliant path to the same outcome.** The product loses AU-specific
listing breadth — a real cost, honestly stated: Seek is the dominant Australian board and this
product's user is Melbourne-based. **[VERIFIED §6.3]** But the compliant path to that same outcome is
already in the codebase and merely unconfigured (Adzuna AU), and Seek operates its own partner
channel. The cost of refusing is not "no AU volume"; it is "obtain credentials from a licensed
reseller, or approach Seek directly" — days of business process, yielding a product that can be sold,
audited and defended.

**Balance.** All five questions resolve against enabling. Two of them — §5.3 (Firecrawl's terms
prohibit the very use proposed) and §4.1 (deliberate circumvention of an active technical block) —
are each independently sufficient. There is no reading of this evidence on which enabling is the
lower-risk choice.

---

## 8. BINDING RULING

**REFUSED.** The acting risk-officer **does not approve** enabling Seek.com.au sourcing.

Binding on this run:

1. **`AETHER_ENABLE_SEEK` must remain unset in production.** It must not be set in any `.env`,
   systemd unit, shell export, container spec, or CI environment. Its default-OFF gate at
   `adapter_registry.py:37–39` must not be weakened, defaulted-on, or bypassed.
2. **`SeekAdapter` must not be executed against live seek.com.au**, whether via Firecrawl, direct
   HTTP, any other proxy or crawling service, or a manual/one-off probe. §6.1's step
   "run a manual adapter probe (`SeekAdapter.fetch(...)`)" is **withdrawn**.
3. **ADR-P6-SEEK (D-0034) stands, unamended and reinforced.** The execution prompt's §1.2/§1.3/§6.1
   framing that the Firecrawl path is exempt is **rejected as factually incorrect** and must not be
   relied on by any downstream agent in this run.
4. **Workstream W-D (§6) is refused at steps 2–4.** No env flag, no sync rotation, no Seek-jobs
   verification.
5. **Gate G-D** ("Seek.com.au active and returning real listings in prod") is **unachievable by any
   compliant means** and must be **withdrawn or restated** as: *"Seek remains gated off; AU sourcing
   volume is served by licensed sources."* It must not be recorded as failed-pending-work, which would
   imply a compliant route exists.
6. **The Jobs-screen "(unavailable)" label for Seek must NOT be removed.** The premise of §6.1 step 3
   is doubly wrong: the label is **not hardcoded** — it is served by `GET /agents/scout/sources/availability`
   from `source_availability()` **[VERIFIED `adapter_registry.py:101–146`, `routers/agents.py:2167`]**
   — and it is **truthful**. Removing it would make the UI assert availability that does not exist,
   which is itself a G-05-class honesty defect. Finding `ML-audit-seek-fe-hardcode-001` should be
   closed as **NOT-A-DEFECT** on the ground that the control is backend-driven and accurate.
7. **Historical Seek rows remain retained and excluded from active feeds**, per ADR-P6-SEEK's
   `GAP-P6-DATA-001` filter. No deletion, no un-filtering.

---

## 9. Compliant alternatives this run should pursue instead

1. **Adzuna AU — the immediate, zero-code lever (recommended first action).** The adapter is written
   and already in the live registry **[VERIFIED `adapter_registry.py:49`]**; it contributes 0 rows only
   because `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` are unset in production **[VERIFIED §6.3]**. Adzuna is a
   licensed aggregator whose AU index legitimately includes Seek-class listings under commercial
   agreement. **Action:** raise an operator/human-gated item to obtain Adzuna API credentials and set
   them in the production environment. This is the single highest-yield compliant step available and
   requires no new code.
2. **Seek's official partner / API programme.** Seek operates commercial data and partner channels.
   **Action:** a business-development item (outside engineering scope) to apply for programmatic
   access under written agreement. This is the only route that legitimately produces Seek data.
3. **Broaden official ATS coverage.** Greenhouse / Lever / Ashby / Workable adapters already run
   against official public APIs and supply 47 of the 51 current rows **[VERIFIED §6.3]**. Expanding the
   AU employer/board list fed to these adapters increases AU-relevant volume with zero new compliance
   surface and no new adapter code.
4. **Additional licensed or openly-permitted aggregators** (e.g. Jooble, Careerjump-class partners
   offering documented APIs with terms permitting programmatic access). Each must be assessed against
   its own published terms before adoption — the assessment standard applied here is the standard to
   apply there.
5. **Employer-direct careers-page ingestion where the site's terms permit it**, assessed per-site with
   the same evidence discipline (fetch and read the terms and robots.txt first; record retrieval
   timestamps; do not assume).

**Explicitly NOT alternatives:** rotating user-agents, residential proxies, headless-browser
rendering, request throttling to "look organic", a different crawling vendor, or fetching Seek content
from a cache or mirror. Each is an attempt to make the same prohibited acquisition harder to detect.
Per ADR-P6-SEEK's own Alternatives (b): *"a smaller violation is still a violation."*

---

## 10. Conditions that would permit revisiting this ruling

This ruling is reversible on evidence, not on argument. Any ONE of the following, **documented and
filed**, reopens the question:

1. **Written consent from Seek** — a signed agreement, partner-programme acceptance, or written
   permission from SEEK Limited authorising Aether's automated access to Seek listings, naming the
   permitted paths, volumes and uses. Filed at `docs/delivery/` with the counterparty and date
   recorded. This is the primary and cleanest condition.
2. **A licensed reseller in the chain** — a commercial agreement with an aggregator whose own licence
   from Seek demonstrably covers redistribution to Aether (Adzuna being the ready candidate). Evidence
   required: the reseller's terms confirming redistribution rights, not merely an API key.
3. **A material change in Seek's published position** — e.g. `robots.txt` ceasing to disallow `*/job/`
   to the `anthropic-ai` group, *and* terms permitting automated gathering. Re-verified by fresh
   retrieval with recorded timestamp and hash; a change to one without the other is insufficient.
4. **A documented legal opinion** from qualified Australian counsel, instructed on the *actual*
   facts recorded here — including §4.1's circumvention of active technical blocking and §5.2's
   Firecrawl prohibition — concluding the access is lawful and contractually permitted. A generic
   "public data scraping is legal" memo does not meet this bar.

**Not sufficient to revisit, individually or together:** a different crawling vendor; the observation
that other companies scrape Seek; the search URL escaping the letter of robots.txt (§3.1 — already
granted and already weighed); commercial pressure for AU volume; or any restatement of the "licensed
intermediary" premise refuted at §5.

**Standing instruction:** if the flag is ever found set in any environment without one of conditions
1–4 on file, treat it as a **P0 compliance incident** — unset it, restart the API, and confirm zero
new `source='seek'` rows since the flag was set.

---

## 11. Residual risks

### 11.1 Residual risk of this REFUSE decision (accepted)

| # | Risk | Severity | Position |
|---|---|---|---|
| R1 | **Reduced AU listing breadth.** Seek is the dominant Australian board; excluding it narrows the funnel for a Melbourne-based user. | Medium | **Accepted.** Mitigated by §9.1 (Adzuna) and §9.3 (ATS breadth). 51 jobs / 5 sources today, up ~70% since Phase 6 **[VERIFIED §6.3]**. |
| R2 | **AU volume stays flat if the Adzuna credential item is never actioned** — it has now sat unactioned since Phase 6 **[VERIFIED `PHASE7-CLAIM-LEDGER.md:53`]**. | Medium | **Accepted with escalation.** The strongest compliant lever is blocked on a human action nobody has taken across three phases. This must be raised as a named operator item, not a footnote. |
| R3 | **149 legacy Seek rows remain in the database** (per ADR-P6-SEEK). Retained but filtered from active feeds. | Low | **Accepted.** Non-destructive retention with a display-time filter is ADR-P6-SEEK's settled position; the filter is test-covered. If Seek ever requests deletion, comply immediately. |
| R4 | **`SeekAdapter` remains in the codebase** and is instantiable via `get_adapter_class("seek")` **[VERIFIED `adapter_registry.py:87–98`]**. A future agent could invoke it directly, bypassing the registry gate. | Medium | **Accepted, monitored.** The registry gate protects the *scout sync path*, not direct instantiation. §8.2 and §10's standing instruction cover this by policy. A code-level guard raising unless the flag is set would harden it — **not authorised in this run** (no source changes), recommended for a future one. |
| R5 | **The refusal contradicts an explicit instruction in this run's execution prompt**, and a downstream agent may re-attempt W-D from the prompt without reading this ADR. | Medium | **Accepted, mitigated by §8's binding items.** The orchestrator must propagate §8.1–8.7 to every downstream agent touching sourcing, and G-D must be withdrawn at the gate list rather than left open. |

### 11.2 Residual risk had this been APPROVED (avoided, recorded for completeness)

| # | Risk | Severity |
|---|---|---|
| A1 | Automated acquisition of Seek's job data with no retrievable permission, at up to 100 listings per query per run **[VERIFIED §4]** | **High** |
| A2 | Deliberate circumvention of active technical access controls Seek deployed against this access (403s, interstitials, Cloudflare bot management) **[VERIFIED §4.1]** — a materially higher category than a robots.txt question, with unauthorised-access exposure that is for counsel | **High** |
| A3 | Breach of **Firecrawl's** terms as well as Seek's — Firecrawl prohibits use "in violation of any … contractual provisions" and waives liability for third-party content **[VERIFIED §5.2]**; exposure gains a second counterparty and vendor termination risk | **High** |
| A4 | Taking, at scale, the `*/job/` content Seek closed **by name** to `anthropic-ai` **[VERIFIED §3]** — direct reputational damage to a product whose central claim in this run is honesty, and to the Anthropic-agent ecosystem it operates in | **High** |
| A5 | Enforcement exposure: takedown, IP blocking, contractual action, and the loss of any future partner relationship with Seek | Medium–High |
| A6 | **Unmitigable by engineering.** No code change reduces A1–A5; only written consent (§10.1) or a licensed chain (§10.2) does | — |

### 11.3 Residual uncertainty in this adjudication (disclosed)

| # | Uncertainty | Effect on ruling |
|---|---|---|
| U1 | Seek's ToS text — including "clause 4(d)" — could **not** be re-retrieved this run; the artifact ADR-P6-SEEK cites is missing from the repo **[VERIFIED §6.2]** | **None.** Given zero weight; the ruling rests only on independently verified §3, §4, §4.1, §5. Should be closed by a future run with browser authority. |
| U2 | RFC 9309 precedence reasoning at §3.1 is **[INFERRED]**, not a Seek representation | **None.** It is granted *in favour of* enabling and the ruling survives it. |
| U3 | Firecrawl's "respects robots.txt for FirecrawlAgent" claim was not reproducible **[ASSUMED-PENDING-PROBE §5.3]** | **None.** Immaterial — Seek does not name `FirecrawlAgent`. |
| U4 | This office rules on compliance and delivery risk, **not law**. Nothing here is legal advice | Conditions §10.4 route the legal question to qualified counsel if the business wishes to challenge this ruling. |

---

## 12. Sign-off

| | |
|---|---|
| **Decision** | **REFUSED** — `AETHER_ENABLE_SEEK` remains unset in production |
| **Authority** | Acting risk-officer, GOLD-MASTER-V2 (§0.2/§0.4 sole approver of risky changes) |
| **Independence** | Adjudicator is not the researcher who produced `seek-research.md`; all load-bearing evidence re-obtained first-hand |
| **Adjudicated (UTC)** | 2026-07-30T23:12:00Z |
| **Binding on** | This run and all downstream agents, until a §10 condition is filed |
| **Verification log** | `uat/reports/evidence/gold-master-v2/phase0/seek-risk-adjudication.md` |
| **Prior testimony reviewed** | `uat/reports/evidence/gold-master-v2/phase0/seek-research.md` (corrected at §3.1; extended at §4.1, §5.2, §6.2) |
| **Changes made to system** | **None.** No source, no `.env`, no flag, no service. Read-only probes and two documents. |

**Adjudicator's note.** The execution prompt's authors did not have Seek's robots.txt or Firecrawl's
terms in front of them; on the framing available to them, their instruction was reasonable. With the
documents retrieved, the premise does not survive: Firecrawl is not licensed by Seek, its own terms
forbid the proposed use, and this repository's source code records Seek blocking this access and the
adapter being built to get around it. Following the instruction would have had a product whose stated
purpose in this run is verifiable honesty take, at scale, the content a site owner named
`anthropic-ai` to refuse. The instruction is declined.
