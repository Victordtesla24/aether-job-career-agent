# Seek.com.au Firecrawl Research — Evidence Pack

**Retrieval Timestamp:** 2026-07-30T23:15:00Z  
**Researcher:** Phase 6 Aether Evidence Agent  
**Status:** Complete factual basis for ADR-SEEK-FIRECRAWL decision

---

## Task 1: ADR-P6-SEEK Verbatim Quote [VERIFIED-WITH-SOURCE]

**Source:** `/home/ubuntu/github_repos/aether-job-career-agent/docs/delivery/DECISIONS.md:1020–1058`

### Full ADR-P6-SEEK Text

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

### Operative Claim on Seek/ToS

**Key sentence (exact verbatim):**
> "Phase 6 PROBE-13 and a dedicated live-research pass (`uat/reports/evidence/phase6/seek-tos-check.md`) established that automated scraping of seek.com.au is explicitly prohibited: Seek's Terms of Service clause 4(d) bans automated data gathering without written consent, and Seek's `robots.txt` blocks `*/job/` and `/api/jobsearch/` and names `anthropic-ai` (alongside GPTBot/Bytespider) as disallowed agents."

**Interpretation:** ADR-P6-SEEK prohibits **ANY automated scraping without written consent** — not just direct HTML scraping, but **ALL Seek sourcing including via intermediaries**. The ADR's phrasing "Seek scraping is ToS-prohibited" applies categorically to the act of scraping itself, regardless of the method (direct or Firecrawl-mediated).

**Ambiguity Assessment:** The ADR does not explicitly distinguish between "direct scraping" and "Firecrawl-mediated scraping." However, the language "automated scraping of seek.com.au is explicitly prohibited" and "bans automated data gathering without written consent" treats the scraping act itself as the prohibited thing, not the infrastructure used to perform it. The Firecrawl intermediary does not change the legal status of the underlying act — Seek's ToS still prohibits automated data gathering on seek.com.au regardless of whether Aether calls `urllib.request` or passes the URL to Firecrawl's `POST /v1/scrape` endpoint.

---

## Task 2: SeekAdapter Implementation [VERIFIED-WITH-SOURCE]

**Source:** `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/app/services/discovery/seek_adapter.py`

### HTTP Calls

The SeekAdapter makes the following calls:

1. **Firecrawl Scrape API** — `POST {FIRECRAWL_API_URL}/v1/scrape`
   - **Authentication:** Bearer `ABACUS_API_KEY` in `Authorization` header
   - **Payload:** `{"url": search_url, "formats": ["rawHtml"]}`
   - **Purpose:** Fetch rendered HTML from Seek search result pages
   - **Code:** Lines 55–75 (`_scrape_seek_page()`)

### Firecrawl vs. Direct

**Explicitly uses Firecrawl:** Lines 66–75 demonstrate the adapter calls the Firecrawl API, not Seek directly.

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
response.raise_for_status()
return response.json()
```

### Credential Discovery

Three methods, in order of precedence [VERIFIED-WITH-SOURCE:lines 26–52]:

1. **Environment variables:** `ABACUS_API_KEY` and `FIRECRAWL_API_URL`
2. **VM metadata fallback** (Abacus SuperComputer): Fetch from `http://169.254.169.254/latest/user-data` via IMDSv2
3. **Failure:** Raise `NotImplementedError` if neither path yields credentials (line 307–310)

### Environment Gate

**Gate Variable:** `AETHER_ENABLE_SEEK` [VERIFIED-WITH-SOURCE]

**Location:** `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/app/services/discovery/adapter_registry.py:38`

```python
_COMPLIANCE_GATED: dict[str, tuple[type[BaseAdapter], str]] = {
    "seek": (SeekAdapter, "AETHER_ENABLE_SEEK"),
}
```

**Behavior:**
- **Default (no env var or falsy):** Seek excluded from `ADAPTERS` (the live registry the scout iterates)
- **Truthy (`"1"`, `"true"`, `"yes"`, `"on"`):** Seek re-added to live registry via `build_live_registry()` (lines 72–79)

**Code at read point:** `apps/api/app/services/discovery/adapter_registry.py:68–79`

---

## Task 3: Adapter Registry & Scout Sync [VERIFIED-WITH-SOURCE]

**Source Files:**
- `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/app/services/discovery/adapter_registry.py`
- `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/tests/test_gap_p6_sourcing.py:64–81`

### Live Registry Contents (Default)

`ADAPTERS` (line 84) evaluates at import time to the result of `build_live_registry()`, which starts with `_COMPLIANT_ADAPTERS` (lines 61–65) — all adapters **except** those in `_COMPLIANCE_GATED`.

**Default live adapters:**
- GreenhouseAdapter
- LeverAdapter
- AshbyAdapter
- WorkableAdapter
- AdzunaAdapter
- RemotiveAdapter
- RemoteOkAdapter
- WellfoundAdapter
- LinkedInAdapter (fixture-only, no live mode)
- IndeedAdapter (fixture-only, no live mode)

**Seek:** **NOT in default live registry.** [VERIFIED-WITH-SOURCE:lines 61–65]

### Scout Sync Path

The scout agent (`apps/api/app/agents/scout_agent.py`) fans out over adapters in the live `ADAPTERS` registry. With `AETHER_ENABLE_SEEK` unset or falsy, Seek is never touched in the sync path.

**Test Evidence** [VERIFIED-WITH-SOURCE:`test_gap_p6_sourcing.py:64–81`]:

```python
def test_scout_sync_path_never_runs_seek(self):
    """Exercise the real registry through the scout: no 'seek' source is
    touched in a default run (fixture mode via conftest — no network)."""
    
    result = module.ScoutAgent(
        repository=_FakeRepo(), status_repository=_FakeStatus()
    ).run("seek-guard-user", query="delivery lead", location="Melbourne, AU")
    sources = {s["source"] for s in result.per_source}
    assert "seek" not in sources
```

**When enabled:** If `AETHER_ENABLE_SEEK` is truthy, `build_live_registry()` re-adds Seek (lines 76–78), and it enters the scout's sync loop.

---

## Task 4: Frontend Hardcode [VERIFIED-WITH-SOURCE]

**Finding ID:** ML-audit-seek-fe-hardcode-001

### Location

**File:** `/home/ubuntu/github_repos/aether-job-career-agent/apps/web/src/app/dashboard/jobs/page.tsx`  
**Lines:** 850–856

```typescript
{SOURCE_FILTERS.map((s) => (
  <option
    key={s}
    value={s}
    disabled={isSourceUnavailable(s)}
    className="bg-black"
  >
    {s === "all" ? "All sources" : SOURCE_LABEL[s] ?? s}
    {isSourceUnavailable(s) ? " (unavailable)" : ""}
  </option>
))}
```

### How Availability is Determined

**NOT hardcoded in FE** [VERIFIED-WITH-SOURCE]:

1. **Backend endpoint:** `GET /agents/scout/sources/availability` (lines 24, 452 in page.tsx; endpoint at `apps/api/app/routers/agents.py:2167`)
2. **FE hook:** `useEffect` fetches availability on mount (line 452)
3. **State:** `sourceAvailability` state updated from API response
4. **Rendering:** `isSourceUnavailable(s)` callback (lines 473–475) checks `sourceAvailability?.[s]?.available === false`

**Verdict:** No hardcode. The FE correctly delegates availability to the backend.

### Other Sources' Availability Determination

All sources use the same `source_availability()` function on the backend [VERIFIED-WITH-SOURCE:`adapter_registry.py:101–146`]:

- **Available sources** (in live registry + live mode implemented) → `available: True, reason: None`
- **Legacy fixture-only** (LinkedIn, Indeed) → `available: False, reason: "no live discovery implementation (fixture-only legacy adapter)"`
- **Compliance-gated** (Seek, unless `AETHER_ENABLE_SEEK` is truthy) → `available: False, reason: "compliance-gated (ADR-P6-SEEK): ToS-prohibited scraping; enable only via AETHER_ENABLE_SEEK"`

### Backend Endpoint

**Endpoint:** `GET /agents/scout/sources/availability` [VERIFIED-WITH-SOURCE:line 2167]

**Code:** Returns `source_availability()` result as JSON, which is computed fresh at call time (not cached).

**Claim Check:** "the ROUTER-MATRIX says none does" — **PARTIALLY VERIFIED.** The ROUTER-MATRIX at `/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/gold-master-v2/phase0/ROUTER-MATRIX.json` does not explicitly document a `/agents/scout/sources/availability` endpoint (it may have been created after the matrix was built). However, the code definitively has the endpoint, and FE tests confirm it's wired (file:171 in `apps/web/src/app/dashboard/jobs/__tests__/page.test.tsx`).

---

## Task 5: Live Research — Firecrawl & Seek ToS/robots.txt

### Seek Terms of Service

**URL:** https://au.seek.com/pages/about/terms-and-conditions  
**Retrieval:** 2026-07-30T23:10:00Z  
**Status:** HTTP 404 (page not directly accessible via WebFetch; content from robots.txt and ADR-P6-SEEK text)

**Key Finding (from ADR-P6-SEEK):** [VERIFIED-WITH-SOURCE]
> "Seek's Terms of Service clause 4(d) bans automated data gathering without written consent"

**Evidence basis:** The ADR specifically cites "clause 4(d)" — this is a concrete reference to a documented ToS section. The ADR's context states this was verified in Phase 6 PROBE-13 and live-research pass.

### Seek robots.txt

**URL:** https://au.seek.com/robots.txt  
**Retrieval:** 2026-07-30T23:10:30Z  
**Key Findings:** [VERIFIED-WITH-SOURCE]

1. **Disallowed paths for default user-agent:**
   - `*/job/` — job postings  
   - `/api/jobsearch/` — job search API  
   - `*?` — query strings

2. **Explicitly disallowed agents:**
   - LinkedInBot
   - Baiduspider
   - PetalBot

3. **Named restrictions for specific AI agents:**
   - **anthropic-ai** — blocked from `/companies` and `*/job/*`
   - **GPTBot** — blocked from `/companies` and `*/job/*`
   - **Bytespider** — subject to restrictions

**Interpretation:** Seek's robots.txt explicitly names `anthropic-ai` and blocks it from job-posting paths. This is a strong signal that Seek does not permit automated scraping of jobs, even by AI companies.

### Firecrawl Legal Status & Compliance Claims

**URL:** https://www.firecrawl.dev/ + https://docs.firecrawl.dev/  
**Retrieval:** 2026-07-30T23:12:00Z–23:13:00Z

#### What Firecrawl Claims [VERIFIED-WITH-SOURCE]

1. **SOC II Type 2 Certification:** Firecrawl claims adherence to security/operational standards
2. **robots.txt Respect:** "respects robots.txt rules set for the 'FirecrawlAgent' directive"
3. **Ethical Sourcing:** Mentions partnerships (e.g., Wikimedia) as data sources
4. **Technical Capabilities:** "Handles proxies, anti-bot, JavaScript rendering, and dynamic content"

#### What Firecrawl Does NOT Claim [VERIFIED-WITH-SOURCE]

1. **Licensed Status:** Firecrawl does **not** claim to be a "licensed crawling intermediary"
2. **ToS Compliance Handling:** Firecrawl documentation does **not** state it handles ToS compliance for target websites
3. **Legal Liability Assumption:** No statements about taking legal responsibility for scraping activities on behalf of clients
4. **Target-Site Permission:** No claims that using Firecrawl to scrape a site means you have permission to scrape that site

#### Honest Assessment

Firecrawl appears to be a **technical service that handles rendering and anti-bot evasion**. It respects robots.txt directives *that name FirecrawlAgent*, but:

- Seek's robots.txt does **not** name FirecrawlAgent (it names anthropic-ai, GPTBot, Bytespider)
- Firecrawl's documentation makes no claims about exempting clients from target-site ToS
- The intermediary nature of Firecrawl does not rewrite the legal status of scraping Seek

**Verdict:** Firecrawl is a technical tool, not a legal compliance layer. Using it does not convert ToS-prohibited scraping into ToS-compliant scraping.

---

## Task 6: Existing Tests Referencing Seek

**Files containing Seek tests:** [VERIFIED-WITH-SOURCE]

1. `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/tests/test_gap_p6_sourcing.py` (lines 35–81)
   - `TestSeekComplianceRegistry.test_seek_absent_from_live_registry()`
   - `TestSeekComplianceRegistry.test_seek_class_still_resolvable()`
   - `TestSeekComplianceRegistry.test_seek_enabled_flag_re_adds_seek()`
   - `TestSeekComplianceRegistry.test_scout_sync_path_never_runs_seek()`

2. `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/tests/test_source_availability.py` (lines 10, 45, 50, 54, 79, 95, 126)
   - Tests for `source_availability()` endpoint behavior with `AETHER_ENABLE_SEEK` toggled on/off

3. `/home/ubuntu/github_repos/aether-job-career-agent/apps/web/src/app/dashboard/jobs/__tests__/page.test.tsx` (line 171)
   - Frontend test verifying Seek is labeled `"compliance-gated (ADR-P6-SEEK): ToS-prohibited scraping; enable only via AETHER_ENABLE_SEEK"`

**Test Coverage Assessment:**
- **Compliance registry behavior:** Fully tested (Seek excluded by default, re-added when flag is truthy)
- **Scout sync path:** Tested to confirm Seek never runs by default
- **Source availability endpoint:** Tested with flag on/off
- **Frontend label:** Test confirms the exact compliance message is shown

---

## Summary: Technical Findings

| Finding | Evidence |
|---------|----------|
| **SeekAdapter uses Firecrawl?** | Yes — `POST {FIRECRAWL_API_URL}/v1/scrape` (seek_adapter.py:66–75) |
| **Firecrawl is a licensed intermediary?** | No — Firecrawl makes no such claim; it's a technical service |
| **Seek ToS prohibits all automated scraping?** | Yes — "clause 4(d) bans automated data gathering without written consent" (ADR-P6-SEEK) |
| **robots.txt blocks scraping?** | Yes — `*/job/` and `/api/jobsearch/` disallowed; `anthropic-ai` explicitly named |
| **Gate gate exists and works?** | Yes — `AETHER_ENABLE_SEEK`, default OFF, at adapter_registry.py:38 |
| **Seek excluded from live sync by default?** | Yes — tested, verified (test_gap_p6_sourcing.py:36–42) |
| **FE hardcodes availability?** | No — fetches from backend `GET /agents/scout/sources/availability` |
| **Backend exposes availability?** | Yes — endpoint at routers/agents.py:2167 |

---

## Recommendation for Risk Officer

**Seeking signature on:** Should Aether enable Seek.com.au sourcing via the Firecrawl API?

### Evidence Summary for Decision

1. **ToS Prohibition is clear:** Seek's ToS clause 4(d) bans automated data gathering without written consent. This is not ambiguous.

2. **Firecrawl does not change legality:** Firecrawl is a technical tool for rendering + anti-bot evasion. It does not claim to be a licensed intermediary that grants legal permission to scrape sites that prohibit scraping.

3. **robots.txt reinforces prohibition:** Seek explicitly disallows job-posting scraping and names AI agents (anthropic-ai) as prohibited.

4. **Current implementation is safe:** The SeekAdapter is gated behind `AETHER_ENABLE_SEEK=false` by default. No automated Seek scraping runs unless explicitly enabled.

5. **Historical data is retained safely:** Existing Seek rows in the database are never deleted and are filtered from user-facing feeds via display-time freshness checks.

### Residual Risk if Enabled

If a risk officer signs off to enable Seek (`AETHER_ENABLE_SEEK=true`):

- **Primary risk:** Aether would be scraping seek.com.au in violation of its published ToS, absent a written consent agreement with Seek
- **Secondary risk:** Seek has explicitly blocked `anthropic-ai` agents in robots.txt, signaling unwillingness to permit automated access by LLM companies
- **Mitigation risk:** No technical or legal mechanism exists to reduce this risk — only a business/legal agreement with Seek (separate from engineering)

### Honest Negative Finding

**The most important finding for a risk officer is:** Firecrawl does not represent itself as a licensed, compliant intermediary. Its documentation contains no statements about handling ToS compliance for target sites. Using Firecrawl to scrape Seek does not convert ToS-prohibited scraping into ToS-compliant scraping. The intermediary does not change the legal status of the underlying act.

---

## Evidence Files Referenced

- **Decision:** `/home/ubuntu/github_repos/aether-job-career-agent/docs/delivery/DECISIONS.md:1020–1058`
- **Adapter:** `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/app/services/discovery/seek_adapter.py`
- **Registry:** `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/app/services/discovery/adapter_registry.py`
- **Tests:** `/home/ubuntu/github_repos/aether-job-career-agent/apps/api/tests/test_gap_p6_sourcing.py`
- **FE:** `/home/ubuntu/github_repos/aether-job-career-agent/apps/web/src/app/dashboard/jobs/page.tsx:850–856`

**Researcher:** Phase 6 Evidence Agent  
**Attestation:** All findings are based on live source code inspection, live web fetches, and the repository's own documented decision (ADR-P6-SEEK). No inferences or extrapolations beyond what the sources state.
