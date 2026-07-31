# Verification log — ADR-SEEK-V3 (Seek + WebScraping.AI re-adjudication)

**Adjudicator:** acting risk-officer, GOLD-MASTER-V4 §7.2
**Session window (UTC):** 2026-07-31T16:59:49Z – 2026-07-31T17:05:00Z
**Ruling produced:** `docs/delivery/ADR-SEEK-V3.md` — **STATUS: REFUSED**
**Repo HEAD:** `6440325b363e2b9a684f54742ad02781babefe47` ("fix(BLOCKER-001): stop the weak-credential
diagnostic from logging the plaintext admin password", 2026-07-31 16:54:14 +0000)
**Charter compliance:** no sub-agents spawned; serial execution; **no `.env`, source, config or
production state modified**; no flag enabled; nothing deployed or pushed; user never consulted.

Tags: **[VERIFIED]** = obtained first-hand this run · **[INFERRED]** = reasoning over verified facts.

---

## 1. Method

I treated the predecessor's REFUSED as **non-dispositive** and re-derived every load-bearing fact. I
also treated APPROVAL as genuinely reachable: the decisive test I set in advance was —

> *Does WebScraping.AI hold a licence or legal arrangement covering Seek content, or represent itself as
> clearing permission with target sites?*

**If yes → material change → APPROVE.** I searched for that in the vendor's Terms, docs, FAQ, homepage,
use-case index, and its dedicated job-listing-aggregation page. The answer was an unambiguous no, and
the vendor's terms affirmatively assign the opposite position. The refusal follows from that finding,
not from the predecessor's conclusion.

---

## 2. Commands run and results

### 2.1 Seek robots.txt — fresh retrieval

```
curl -sS -L -D headers -o seek_robots.txt https://au.seek.com/robots.txt
FETCH_UTC=2026-07-31T16:59:49Z
HTTP=200  FINAL_URL=https://au.seek.com/robots.txt  BYTES=853
sha256 = 32fbbb98f660e636e106580d33f7aba4f43b68edbdeac916acc9da64d2ebfad8
```
**[VERIFIED]**

**Hash comparison against the prior ruling (`ADR-SEEK-FIRECRAWL.md` §3, retrieved
2026-07-30T23:05:47Z): `32fbbb98f660e636e106580d33f7aba4f43b68edbdeac916acc9da64d2ebfad8` —
BYTE-IDENTICAL.** Seek's published position is unchanged over the intervening ~18 hours. Prior ruling's
revisit condition 3 ("material change in Seek's published position") is **NOT MET** **[VERIFIED]**.

Response headers **[VERIFIED 2026-07-31T16:59:52Z]**:
```
HTTP/2 200
date: Fri, 31 Jul 2026 16:59:52 GMT
content-type: text/plain; charset=utf-8
content-length: 853
cf-ray: a23e27f67d2bff02-PDX
cf-cache-status: HIT
server: cloudflare
seek-melways: true
set-cookie: __cf_bm=…; HttpOnly; SameSite=None; Secure; Path=/; Domain=seek.com
```
→ **Cloudflare Bot Management active on the origin, freshly confirmed** (`__cf_bm` is Cloudflare's bot
management cookie).

**Directives asked about, quoted verbatim from the retrieved file [VERIFIED]:**

| Line | Content | Group |
|---|---|---|
| 9 | `User-agent: *` | default group opens |
| 10 | `Disallow: */job/` | default group |
| 11 | `Disallow: *?` | default group |
| 13 | `Disallow: /api/jobsearch/` | default group |
| 12 | `Disallow: /graphql` | default group |
| 19 | `Allow: *?keywords` | default group |
| 28 | `User-agent: anthropic-ai` | named-agent group opens |
| 29–34 | `Bytespider`, `CCBot`, `Diffbot`, `Google-Extended`, `omgili`, `GPTBot` | same group |
| 35 | `Disallow: /companies` | anthropic-ai group |
| 36 | `Disallow: */job/` | **anthropic-ai group** |

`Disallow: */job/` appears **twice** — default group and the `anthropic-ai`-headed group.

**Concession re-affirmed [INFERRED, RFC 9309 §2.2.1–2.2.2]:** the adapter's actual request URL
(`…/jobs?keywords=…&where=…`) is matched by `Allow: *?keywords` (more specific than `Disallow: *?`,
ties to Allow), and only the single most-specific UA group binds. **robots.txt does not, on its face,
forbid that exact URL.** Granted here as it was granted by the predecessor — and, as the predecessor's
revisit list states, already weighed and not sufficient. What *is* unambiguously closed to
`anthropic-ai` is `*/job/`, which is what the adapter extracts (§2.3).

### 2.2 WebScraping.AI — legal-surface discovery

```
FETCH_UTC=2026-07-31T17:00:02Z
https://webscraping.ai/                  -> 200  107426 B
https://webscraping.ai/tos               -> 404
https://webscraping.ai/terms             -> 200   91548 B   <-- canonical ToS
https://webscraping.ai/terms-of-service  -> 404
https://webscraping.ai/legal             -> 404
https://webscraping.ai/privacy           -> 200   66813 B
https://webscraping.ai/docs              -> 200  172091 B
https://webscraping.ai/faq               -> 200  107558 B
```
**[VERIFIED]**

Canonical ToS: `https://webscraping.ai/terms`, sha256
`b72303d204072f6922884e461204c8eab86a84fd2f88e715c3443e0156bb7234`, document self-dated
**"Last Updated: May 24, 2026"**, provider **Urlooker LLC** (Wyoming LLC, Portland OR), governed by
**Wyoming law** **[VERIFIED]**.

### 2.3 Absence probes — the decisive test

Over the full de-tagged ToS (36,282 chars), case-insensitive **[VERIFIED 2026-07-31T17:00:02Z]**:

| Phrase | Count |
|---|---|
| `licensed intermediar` | **0** |
| `licensed intermediary` | **0** |
| `intermediar` (any form) | **0** |
| `license from` | **0** |
| `permission from` | **0** |
| `on your behalf` | **0** |
| `clears permission` | **0** |
| `consent of the` | **0** |
| `robots.txt` | **0** |
| `robots` | **0** |
| `seek.com` | **0** |
| `at your direction` | 1 (definition of *Scraped Content* — customer directs) |
| `target website` | 17 |
| `publicly accessible` | 4 |
| `authoriz*` | 14 (all obligations **on the customer**) |

Same probes over **docs**, **FAQ**, **homepage** **[VERIFIED]**:

| Page | `licensed` | `license` | `permission` | `robots.txt` | `compliance` | `lawful` |
|---|---|---|---|---|---|---|
| `/docs` (46,165 chars) | 0 | 0 | 0 | 0 | 0 | 0 |
| `/faq` | 0 | 0 | 0 | 0 | 0 | 0 |
| `/` (homepage) | 0 | 0 | 0 | 0 | 0 | 0 |

**Strongest-case check.** I enumerated the vendor's use-case index
(`https://webscraping.ai/use-cases`, 2026-07-31T17:02:15Z, HTTP 200) and found the on-point page
`/use-cases/job-listing-aggregation` — where a job-board licensing arrangement would be the headline
selling point if one existed. Retrieved 2026-07-31T17:02:29Z, HTTP 200, sha256 `9af60c73f2…`
**[VERIFIED]**:

| Probe | Count |
|---|---|
| `licensed` / `license` | **0** / **0** |
| `permission` / `authoriz` | **0** / **0** |
| `robots` | **0** |
| `seek` | **0** |
| `lawful` / `compliance` | 0 / 0 |

Its own headline **[VERIFIED]**: *"Job scraping at scale: pull job postings from any board or careers
page to build job boards, analyze hiring trends, and research compensation."*

**FINDING: WebScraping.AI holds no licence covering Seek, claims none anywhere on its site, and
describes its own offering as scraping.** v4 §7.1's "licensed crawling intermediaries — neither is raw
scraping" is **false as to WebScraping.AI** on the vendor's own words. **The APPROVAL path I set in §1
is closed on the evidence.**

### 2.4 What the ToS affirmatively says — verbatim [VERIFIED 2026-07-31T17:00:02Z]

Intro: *"WebScraping.AI operates a **web scraping platform** enabling users to extract data from publicly
accessible websites. The service includes **proxy servers**, crawler configuration, AI-powered data
extraction…"*

| § | Verbatim | Effect |
|---|---|---|
| 2 | *"**"Scraped Content"** means … content that the Service retrieves from a Target Website **at your direction**."* | customer is the acquiring party |
| 4.4 | *"**You are responsible for compliance with the terms of service, terms of use, and other policies of each Target Website.**"* | target-ToS burden → customer |
| 6.2(a) | *"You represent and warrant that: (a) **you are authorized to instruct us to access each Target Website** and to retrieve the requested Scraped Content"* | **customer warrants authorisation Aether does not hold** |
| 6.3 | *"If you breach Section 6.2, **you are solely liable** … We are not liable for any breach of third-party rights arising from your use."* | liability → customer |
| 6.6(h) | *"You shall not … **continue attempting requests against Target Websites from which you have received failure notifications or other indications of unavailability**"* | **directly triggered by Seek's 403s/interstitials** |
| 7.1 | *"You are solely responsible for compliance with all applicable laws … including … **(c) the terms of service of Target Websites** … **(e) the U.S. Computer Fraud and Abuse Act**"* | anti-circumvention law named |
| 7.4 | *"**The Company provides a technical service only.** We do not monitor or control the Scraped Content you retrieve"* | explicit non-intermediary posture |
| 12.5 | *"**You release the Company** … from any claims … connected with **any dispute you have or may have with any Target Website or its operator**."* | vendor exits target disputes |
| 13(c) | *"… **your violation of any law or third-party right (including any Target Website's terms)**"* | customer indemnifies vendor |
| 17.2(d) | *"… **a Target Website operator presents a credible demand that we cease providing you service**"* | vendor terminates on Seek complaint |
| 5.8 | *"For certain **protected, high-risk, or technically challenging** Target Websites, we may apply credit multipliers."* | protected targets priced, not permitted |

**[INFERRED] §6.2(a) is decisive.** Using this service against Seek requires Aether to **warrant it is
authorized to instruct access to Seek**. It holds no such authorization. Enabling this path would have
Aether make a **false warranty to a vendor as the price of breaching a third party's terms** — a second
counterparty added to the exposure, not a shield. This is the same structural defect the predecessor
found in Firecrawl's terms, stated here **more explicitly and in more places**.

### 2.5 Vendor documentation — the evasion parameters v4 hard-codes

v4 §7.3 step 2 specifies `&js=true&proxy=residential`
**[VERIFIED `/home/ubuntu/aether-gold-master-execution-v4.md:408–410`]**.

WebScraping.AI's own `/docs` **[VERIFIED 2026-07-31T17:00:03Z]**:

> *"**Proxy Strategy.** Start with datacenter proxies (default) for speed and cost. **Switch to
> residential proxies if: website blocks datacenter IPs, getting 403 errors, need to bypass anti-bot
> protection**, or scraping geo-restricted content."*

> *"Residential proxy (no JS) — 5 — **For anti-bot protected sites**"*
> *"… — 50 — **For sites with the strongest anti-bot protection**"*
> *"**Use residential proxies** — Set `proxy=residential` **if datacenter proxies are blocked**"*

Homepage **[VERIFIED 2026-07-31T17:00:02Z]**:
> *"**Automatic CAPTCHA solving** for uninterrupted data extraction."*
> *"Rotating Proxies — Datacenter and residential proxies with **automatic rotation** and retry logic."*

**[INFERRED] Aggravating finding.** The prompt does not incidentally pick a parameter that happens to
evade blocking — it hard-codes the exact mode the vendor documents for **"getting 403 errors"** and
**"bypass anti-bot protection"**, against a target this repo records as returning **403** to this system
(§2.6) behind **Cloudflare bot management** (§2.1). The circumvention the predecessor had to *infer* is,
in this proposal, **written into the configuration string**. This is new evidence, and it points away
from approval.

### 2.6 Circumvention evidence in repo source — re-confirmed by me at HEAD `6440325`

All read first-hand 2026-07-31T17:00:52Z–17:01:05Z **[VERIFIED]**:

| file:line | Verbatim |
|---|---|
| `apps/api/app/services/discovery/adapter_registry.py:10–13` | "Seek is EXCLUDED here by default (ADR-P6-SEEK): Seek's ToS and robots.txt prohibit automated scraping (seek-tos-check.md verdict SCRAPING-PROHIBITED; **probe-13 10/10 cards HTTP 403**)" |
| `seek_adapter.py:1–3` | "Seek.com.au discovery adapter (P2-S02) — LIVE via Firecrawl API. **Scrapes** real job listings from seek.com.au" |
| `seek_adapter.py:68–71` | "far more reliable than scraping each job detail page (**Seek blocks direct `/job/<id>` fetches with an interstitial error page**)" |
| `seek_adapter.py:312–315` | "The keyword/where query form is used rather than the `/<slug>-jobs/in-<slug>` path form: **the latter redirects to au.seek.com and scrapes an error page** (a root cause of discovery being stuck at persisted=0)" |
| `seek_adapter.py:342–349` | "No data island → Seek served an interstitial/error page… **likely blocked**" |
| `seek_adapter.py:135` | `"sourceUrl": f"https://www.seek.com.au/job/{record.get('id')}"` |
| `seek_adapter.py:43–48` | parses `window.SEEK_REDUX_DATA` island out of the search page |
| `seek_adapter.py:320–321` | `AETHER_SEEK_MAX_PAGES` default **10**, `AETHER_SEEK_MAX_JOBS` default **100** |
| `seek_adapter.py:21–29` | sole outbound call: `httpx.post(f"{firecrawl_url}/v1/scrape", json={"url": search_url, "formats": ["rawHtml"]})` |

**CONFIRMED, not inherited.** The system extracts `*/job/` content (the path closed to `anthropic-ai` by
name) and `/api/jobsearch/`-equivalent data out of an incidentally-permitted wrapper URL, at up to 100
listings per query, from an origin that returns 403s and interstitials to it.

### 2.7 Environment / credential state — read-only

```
TS=2026-07-31T17:01:18Z–17:01:28Z
aether-api: active, MainPID=3093413, 80 env vars
```
Env-var **names only** (values never read or printed) **[VERIFIED]**:

| Check | Result |
|---|---|
| `AETHER_ENABLE_SEEK` in `/proc/3093413/environ` | **count: 0 — NOT SET** |
| `AETHER_ENABLE_SEEK` in `.env` | **absent** |
| Seek-related keys present | `SEEK_BASE_URL` only (a base-URL string, not the enable flag) |
| `WEBSCRAPING*` in any repo `.env*` | **none** (`grep -rl` → no matches) |
| `WEBSCRAPING*` in running process | **absent** |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | **absent** from `.env` and process |
| Firecrawl keys present | `FIRECRAWL_API_URL`, `FIRECRAWL_API_KEY`, `FIRECRAWL_BASE_URL` |

IMDS user-data top-level keys **[VERIFIED 2026-07-31T17:01:28Z]**:
```
['abacus_api_key', 'abacusai_data', 'api_base_url', 'brave_search_api_url', 'databases',
 'firecrawl_api_url', 'github_connected', 'http_ingress_settings', 'llm_base_url',
 'personal_agent_computer_id', 'public_url_enabled', 'storage']
```
→ **no WebScraping.AI credential in IMDS either.**

**FINDING against v4 §0.6.** v4 §0.6 asserts "WebScraping.AI | `WEBSCRAPING_AI_API_KEY` in `.env`". That
is **false** — the credential exists in neither `.env` nor IMDS. Independent of the compliance ruling,
W-D as written is **not executable**. Per v4 §0.6's own rule this is a CONDITIONALLY-CLOSED service.

**Gate integrity confirmed [VERIFIED]:** `_COMPLIANCE_GATED` at `adapter_registry.py:37–39`;
`_COMPLIANT_ADAPTERS` built by exclusion at `:61–65`; `_flag_enabled` accepts `{1,true,yes,on}` at
`:68–69`; re-add only on truthy flag at `:72–79`; `ADAPTERS = build_live_registry()` at `:84`.

### 2.8 Counterfactual — live production sourcing, measured read-only

```
TS=2026-07-31T17:02:02Z   (SELECT only; no writes)
psql … -c 'SELECT source, count(*) FROM aether."Job" GROUP BY source ORDER BY 2 DESC;'
```
**[VERIFIED]**

| Source | Count |
|---|---|
| greenhouse | 21 |
| ashby | 17 |
| lever | 10 |
| remoteok | 3 |
| remotive | 1 |
| **adzuna** | **0** |
| **seek** | **0** |
| **TOTAL** | **52** |

`SELECT count(*) FROM aether."Job"` → **52**; `… WHERE source='seek'` → **0** **[VERIFIED]**.

**[INFERRED]** 52 jobs / 5 compliant sources — **up from 51** recorded in the prior ruling one day
earlier, and up ~73% from ADR-P6-SEEK's 30/5 Phase-6 baseline. Zero Seek rows. Compliant sourcing is
adequate and growing. **Adzuna contributes 0 of 52 purely for want of two credentials**
(`adapter_registry.py:49` — "licensed AU aggregator (env creds)"), confirming the predecessor's
identification of it as the highest-yield compliant AU lever requiring no code.

### 2.9 v4 §7.3 step 4 ("remove the Seek hardcode") — checked and refuted

**[VERIFIED 2026-07-31T17:02:45Z]**

- `source_availability()` at `adapter_registry.py:101–146`, computed **fresh at call time**; docstring:
  *"The single backend authority … the FE must never hardcode availability
  (ML-audit-seek-fe-hardcode-001)."*
- Served by `GET /scout/sources/availability` — `apps/api/app/routers/agents.py:2214–2224`
- Seek row returned: `available: False`, reason
  `"compliance-gated (ADR-P6-SEEK): ToS-prohibited scraping; enable only via AETHER_ENABLE_SEEK"`
  (`adapter_registry.py:128–136`)

**The "(unavailable)" label is backend-driven and truthful — not a hardcode.** v4 §7.3 step 4's premise
is false; removing the label would make the UI assert an availability that does not exist.
`ML-audit-seek-fe-hardcode-001` → **NOT-A-DEFECT**.

---

## 3. Decision trace

| # | Question | Answer | Basis |
|---|---|---|---|
| 1 | Has Seek's published position changed? | **No** — byte-identical robots.txt | §2.1 [VERIFIED] |
| 2 | Is `*/job/` still disallowed to `anthropic-ai` by name? | **Yes** | §2.1 [VERIFIED] |
| 3 | Is Seek actively blocking this system? | **Yes** — Cloudflare bot mgmt + 403s/interstitials in repo | §2.1, §2.6 [VERIFIED] |
| 4 | Is WebScraping.AI a licensed intermediary? | **No** — 0 supporting representations anywhere, incl. its own job-scraping page | §2.3 [VERIFIED] |
| 5 | Do its terms disclaim that role and prohibit contract-violating use? | **Yes, more explicitly than Firecrawl** — §4.4, §6.2(a), §6.3, §7.1(c), §7.4, §12.5, §13(c) | §2.4 [VERIFIED] |
| 6 | Does any vendor term bar this specific use? | **Yes — §6.6(h)**, continuing requests after indications of unavailability | §2.4, §2.6 [VERIFIED] |
| 7 | Does a second vendor change who obtains the data? | **No** — "at your direction", Aether's key, Aether persists and serves | §2.4, §2.6 [INFERRED] |
| 8 | Do the specified parameters aggravate? | **Yes** — `proxy=residential` is the vendor's documented 403/anti-bot bypass mode | §2.5 [VERIFIED+INFERRED] |
| 9 | Was this pre-empted by the prior ruling's revisit list? | **Yes, explicitly** — "a different crawling vendor", "proxy/UA rotation" both named NOT SUFFICIENT | prior ADR §10 [VERIFIED] |
| 10 | Does the credential even exist? | **No** — absent from `.env` and IMDS | §2.7 [VERIFIED] |
| 11 | Is there adequate compliant volume? | **Yes** — 52 jobs / 5 sources, growing | §2.8 [VERIFIED] |
| 12 | Is there an untapped compliant AU lever? | **Yes** — Adzuna, 0 rows, blocked on 2 credentials, no code | §2.8 [VERIFIED] |
| 13 | Any revisit condition (consent / reseller / position change / legal opinion) met? | **No, none** | §2.1, §2.7 [VERIFIED] |

**All thirteen resolve against enabling. Three are independently sufficient:** §2.3–2.4 (the licensed-
intermediary premise is false and contractually inverted), §2.4 §6.6(h) + §2.6 (the use breaches the new
vendor's own AUP), and §2.5 (the proposal specifies a documented block-evasion mode against a site
actively blocking this system).

**Material change from the prior ruling: NO.** The one genuinely new fact — WebScraping.AI — was
investigated on its merits with a real path to approval, and it **strengthens** the refusal rather than
weakening it.

---

## 4. Artifacts produced

| Path | Content |
|---|---|
| `/home/ubuntu/github_repos/aether-job-career-agent/docs/delivery/ADR-SEEK-V3.md` | Binding ruling — **REFUSED** (the file v4 §7.2 names) |
| `/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/gold-master-v3/services/seek-webscraping-adjudication.md` | This verification log |

## 5. Governance record

**Approval withheld.** The v4 §7.2 sign-off ("risk-officer approves before svc-integrator touches
`.env`") is **NOT GRANTED**. svc-integrator has no authority to add `AETHER_ENABLE_SEEK` or
`WEBSCRAPING_AI_API_KEY` for the Seek path. Downstream agents must not rely on v4 §7.1's
"licensed crawling intermediaries" framing.

**G-D disposition:** restated as a compliance gate that passes when Seek is verifiably OFF — full pass
criteria at `ADR-SEEK-V3.md` §8.

**Compliant alternative to fund instead:** Adzuna AU credentials
(`ADZUNA_APP_ID`/`ADZUNA_APP_KEY`) — adapter already live at `adapter_registry.py:49`, 0 of 52 rows,
zero new code. Human-gated operator item.

*No sub-agents spawned. Nothing modified, enabled, deployed, or pushed. User never consulted.*
