"""ATS scoring engine — deterministic 0-100 resume/JD fit score (P2-S03).

Components (weights):
- ``keyword_match``     (40%) — TF-IDF keyword extraction from the JD; the
  score is the coverage of those keywords in the resume.
- ``semantic_similarity`` (40%) — GMV4-ats-001: a genuine embedding-model
  cosine similarity, resolved through THREE paths in strict priority order
  (see :meth:`ATSEngine._semantic_similarity_detailed`):
    1. LOCAL — sentence-transformers ``all-MiniLM-L6-v2`` loaded from the
       on-disk model cache (``MODEL_CACHE_DIR``). No network I/O at scoring
       time.
    2. HF INFERENCE API — used only when the local model is unavailable AND
       ``HF_TOKEN`` is set; calls the hosted sentence-similarity endpoint.
    3. HONEST DEGRADATION — when neither path is available, the engine
       raises :class:`SemanticScoringUnavailableError` rather than silently
       substituting a token-overlap approximation dressed up as a semantic
       score. :meth:`ATSEngine.score` catches this and marks
       ``ATSScore.semantic_path == "degraded"`` so callers/the UI can be
       truthful about it — it NEVER returns the old token-overlap number
       labelled as a semantic score.
  ``ATSScore.semantic_path`` records which path actually produced the
  number: ``"local"``, ``"hf_api"``, or ``"degraded"``.
- ``experience_gap``    (20%) — years-of-experience parsed from both texts
  with a simple regex; 100 means the resume meets/exceeds the requirement.

``overall = 0.4*keyword_match + 0.4*semantic_similarity + 0.2*experience_gap``
clamped to [0, 100]. Scores below the review threshold (60) set
``requires_review=True`` so a human gates low-fit applications.
"""
from __future__ import annotations

import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

_logger = logging.getLogger(__name__)

#: Local cache dir for embedding models — never download during scoring.
MODEL_CACHE_DIR = os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", "/tmp/aether_models")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

#: HF Inference API endpoint for the same model (§5.2 secondary path). The
#: request shape is fixed by spec: {"inputs": {"source_sentence", "sentences"}}.
_HF_API_URL = (
    "https://api-inference.huggingface.co/models/"
    "sentence-transformers/all-MiniLM-L6-v2"
)
_HF_API_TIMEOUT_SECONDS = 15.0

#: Neutral placeholder used ONLY for the ``semantic_similarity`` (0-100)
#: field when scoring is genuinely unavailable (``semantic_path ==
#: "degraded"``). It is not a measurement — callers/UI MUST check
#: ``semantic_path`` before presenting this number as a real score; it is
#: deliberately never equal to what the removed token-overlap fallback would
#: have silently produced (§5.2 HONEST DEGRADATION).
_DEGRADED_SEMANTIC_SCORE = 50.0

#: Overall score below which a human must review the match.
REVIEW_THRESHOLD = 60.0

_WEIGHT_KEYWORD = 0.4
_WEIGHT_SEMANTIC = 0.4
_WEIGHT_EXPERIENCE = 0.2

#: Max number of JD keywords considered for the coverage score.
_MAX_KEYWORDS = 40

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-]*")
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)

#: English stopwords + recruiting boilerplate that says nothing about fit.
_STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could did do does for from had has
    have he her his how i if in into is it its me my not of on or our she so
    than that the their them then there these they this those to was we were
    what when where which who will with would you your
    ability able across additional all also any applicant applicants apply
    are aspects backed based being benefits best both bring bringing build
    building candidate candidates career company culture day dedicated
    degree environment etc excellent experience experienced familiar
    familiarity great grow growing help highly ideal ideally including join
    knowledge like looking love new offer opportunities opportunity per plus
    position preferred proven range red required requirements responsibilities
    role salary seeking skills solid stack strong success successful suitable
    team teams the understanding us via want we well work working world years
    accommodation accommodations disability disabilities veteran veterans
    gender orientation sexual religion religious ethnicity nationality marital
    pregnancy harassment discrimination diversity inclusion inclusive belonging
    regardless
    """.split()
)

#: A single maximal run of digits — used to spot machine-gibberish tokens.
_DIGIT_RUN_RE = re.compile(r"\d+")


def _is_noise_token(token: str) -> bool:
    """Structural non-skill garbage that must never surface as a skill (MV-job-discovery-001).

    Live postings leak URL/domain fragments and machine gibberish (e.g.
    anti-scrape honeypot codes) verbatim into their text; neither is a plausible
    skill:

    * URL / multi-segment domain fragments — ``cdn.openai.com`` (2+ dots) or a
      token carrying a ``http``/``www`` marker. Real tech keeps a single dot
      (``node.js``, ``asp.net``), so it is preserved.
    * Machine gibberish — real skills carry at most a short version suffix with
      one digit group (``python3``, ``log4j``, ``oauth2``, ``i18n``) or, rarely,
      two in a compact token (``log4j2``). An encoded token (base64 honeypot
      ``rmja4ljeymi44ljex``) betrays itself with three+ digit runs, or two runs
      inside a long (>= 12 char) token — never a real skill.
    """
    if token.count(".") >= 2 or "www" in token or "http" in token:
        return True
    digit_runs = len(_DIGIT_RUN_RE.findall(token))
    if digit_runs >= 3 or (digit_runs >= 2 and len(token) >= 12):
        return True
    return False


@dataclass(frozen=True)
class ATSScore:
    """Deterministic breakdown of a resume-vs-JD ATS evaluation."""

    overall: float
    keyword_match: float
    semantic_similarity: float
    #: Experience component score: 100 = requirement met, 0 = fully unmet.
    experience_gap: float
    matched_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    requires_review: bool = True
    #: Which path actually produced ``semantic_similarity``: "local"
    #: (sentence-transformers), "hf_api" (HF Inference API), or "degraded"
    #: (neither available — ``semantic_similarity`` is a neutral placeholder,
    #: NOT a real measurement; see GMV4-ats-001). The REAL ``ATSEngine.score``
    #: below ALWAYS sets this explicitly to one of those three values — it
    #: never relies on the default. ``"untracked"`` is a DISTINCT sentinel
    #: reserved for callers/test doubles that construct an ``ATSScore``
    #: without tracking provenance at all (this dimension is out of scope for
    #: them) — never conflated with ``"degraded"`` (round-3 note: this used
    #: to default to bare ``None``, which is a weaker signal than a named
    #: string on a ``str`` field).
    #:
    #: GMV4-ats-002 round 3: consumers MUST use a WHITELIST, not a blacklist —
    #: trust the score only when ``semantic_path in ("local", "hf_api")``.
    #: Treat "degraded", "untracked", any unrecognised/future value, and a
    #: field that is simply absent from a payload as equally NOT a genuine
    #: measurement. A blacklist (``== "degraded"``) fails OPEN on exactly the
    #: values this sentinel exists to catch. The one deliberate exception is
    #: ``tailoring_loop.py``'s own per-iteration convergence check, which
    #: intentionally keeps the narrower ``== "degraded"`` test — see its
    #: comment for why.
    semantic_path: str = "untracked"


class SemanticScoringUnavailableError(Exception):
    """Raised when neither the local embedding model nor the HF Inference API
    can produce a genuine semantic-similarity score (GMV4-ats-001, §5.2).

    Callers MUST NOT catch this and silently substitute a token-overlap (or
    any other) approximation dressed up as a semantic score. The honest
    response is to mark the result degraded — see ``ATSEngine.score``, which
    sets ``ATSScore.semantic_path = "degraded"`` on this exception.
    """


@dataclass(frozen=True)
class _SemanticSimilarityResult:
    """A genuine semantic-similarity measurement with provenance.

    ``value`` is cosine similarity (local) or the HF Inference API's
    sentence-similarity score, clamped to [0, 1]. ``path`` is ``"local"`` or
    ``"hf_api"`` — never ``"degraded"``; a degraded condition raises
    :class:`SemanticScoringUnavailableError` instead of constructing one of
    these, so a placeholder value can never be mistaken for a measurement.
    """

    value: float
    path: str


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _content_tokens(text: str) -> list[str]:
    """Lowercased tokens with stopwords/boilerplate/garbage removed (order kept).

    ``_TOKEN_RE`` requires a LEADING LETTER, so inside a number-with-unit it
    starts matching at the unit and produces a fragment of that number rather
    than a word: ``"10k+ users"`` yields ``k+``, ``"$1.5M+"`` yields ``m+``.
    Those fragments used to survive every downstream filter — ``len("k+") == 2``
    clears the length floor, they are not stopwords, and :func:`_is_noise_token`
    only recognises URL/gibberish shapes — so ``k+`` was treated as a genuine JD
    keyword by every consumer of this function. It reached the user in
    ``ATSScore.missing_keywords``, and, worse, ``resume_tailor._validate``'s ATS
    non-regression floor rejected an otherwise-clean rewrite for "dropping the
    JD keyword ``k+``" that the original bullet only ever contained as part of
    "10k+ device concurrency". A single such fragment was enough to reject the
    last surviving rewrite in a batch, leaving ``changes == 0`` and turning the
    whole tailoring feature into a silent no-op.

    A match that begins immediately after a DIGIT is therefore dropped: it is a
    unit suffix on a number, never a word. Real skills are unaffected because
    they never start mid-number — ``s3``, ``ec2``, ``c#``, ``c++``, ``log4j2``,
    ``i18n``, ``node.js`` and ``covid-19`` all match from their own first letter
    with a non-digit (or nothing) in front of them. This is the same class
    ``c3d79f0`` fixed one layer downstream in ``clean_gap_keywords``; the root
    was here.
    """
    return [
        token
        for token, _start, _end in _iter_tokens(text)
        if len(token) >= 2 and token not in _STOPWORDS and not _is_noise_token(token)
    ]


def _iter_tokens(text: str) -> list[tuple[str, int, int]]:
    """Every normalised token with its ``[start, end)`` offsets in ``text``.

    The single tokenization used by BOTH :func:`_content_tokens` (which then
    drops stopwords/noise) and :func:`_geographic_tokens` (which needs the
    offsets to tell WHERE in the posting a token occurred). Keeping one
    tokenizer is load-bearing: the geography filter matches its output against
    ``_content_tokens`` output by string equality, so any drift in
    normalisation would silently stop the filter matching anything.
    """
    tokens: list[tuple[str, int, int]] = []
    for match in _TOKEN_RE.finditer(text):
        start = match.start()
        if start > 0 and text[start - 1].isdigit():
            # Unit fragment of a number ("10k+" -> "k+"), not a word.
            continue
        tokens.append((match.group(0).lower().rstrip(".,-"), start, match.end()))
    return tokens


# -- ATS-KW-001: a place is not a skill --------------------------------------
#
# ``_extract_keywords`` used to take the JD's top-TF-IDF content tokens as the
# REQUIRED-KEYWORD set with no notion of what kind of word each one was, so the
# posting's own geography ("Senior Backend Engineer — Sydney.") was scored as a
# skill the résumé had to restate. Measured 2026-08-04 on the suite's own
# JD_PYTHON/RESUME_MATCHING pair: "sydney" was the SOLE miss, docking
# ``keyword_match`` 100 -> 94.44. Every posting carries a location, so every
# candidate was docked on every posting, and the user-facing gap list told them
# to write a city name into their résumé — the keyword-stuffing this product
# exists to refuse.
#
# Location fit is NOT dropped by this: it is already scored SEPARATELY and
# EARLIER by ``app.services.discovery.relevance.location_score`` /
# ``is_applicable``, a hard gate every posting passes before it can be ATS
# scored at all. Counting it again inside ``keyword_match`` was double-counting
# on top of being wrong, so no replacement signal is added here.
#
# THE RULE (see :func:`_geographic_tokens`): a token is treated as geography
# iff EVERY one of its occurrences in the posting falls inside a detected
# geographic span. That "every occurrence" clause is what keeps the vocabulary
# below from over-matching: a term that is both a place and a real technology
# ("Phoenix", "Ontario", "Java") keeps its keyword status as soon as it also
# appears somewhere that is NOT geographic — e.g. in a skills list.

#: Place names strong enough to mark geography on their own: countries and
#: their demonyms, states/provinces, regions, and cities big enough that the
#: name is overwhelmingly the place. DELIBERATE OMISSIONS (precision over
#: recall): city names that are also well-known technology names — "phoenix",
#: "aurora", "sierra", "ventura", "monterey", "catalina", "hudson", "atlas",
#: "athena" — are NOT listed. They are still caught when the posting states
#: them geographically ("Location: Phoenix, AZ"), via the label/carrier spans
#: below, and are never dropped when they appear in a skills list. "english"
#: is omitted for the same reason: it is a language competency here, not a
#: nationality.
_GEO_STRONG_TOKENS = frozenset(
    """
    afghanistan albania algeria andorra angola argentina argentine argentinian armenia
    australia australian austria austrian azerbaijan bahamas bahrain bangladesh barbados
    belarus belgium belgian belize benin bhutan bolivia bosnia botswana brazil brazilian
    brunei bulgaria burundi cambodia cameroon canada canadian chile chilean china chinese
    colombia colombian congo croatia croatian cuba cuban cyprus czechia czech denmark danish
    djibouti dominica ecuador egypt egyptian eritrea estonia estonian ethiopia fiji finland
    finnish france french gabon gambia germany german ghana greece greek guatemala guinea
    guyana haiti honduras hungary hungarian iceland india indian indonesia indonesian iran
    iraq ireland irish israel israeli italy italian jamaica japan japanese kazakhstan kenya
    kosovo kuwait kyrgyzstan laos latvia lebanon lesotho liberia libya liechtenstein
    lithuania luxembourg madagascar malawi malaysia malaysian maldives mali malta mauritania
    mauritius mexico mexican moldova monaco mongolia montenegro morocco mozambique myanmar
    namibia nepal netherlands dutch nicaragua nigeria norway norwegian oman pakistan
    pakistani palau palestine panama paraguay peru philippines filipino poland polish
    portugal portuguese qatar romania romanian russia russian rwanda samoa senegal serbia
    serbian seychelles singapore singaporean slovakia slovenia somalia spain spanish sudan
    suriname sweden swedish switzerland swiss syria taiwan tajikistan tanzania thailand thai
    togo tonga tunisia turkey turkiye turkmenistan uganda ukraine ukrainian uruguay
    uzbekistan vanuatu venezuela vietnam vietnamese yemen zambia zimbabwe
    europe european asia asian africa african americas emea apac anz latam oceania nordics
    benelux scandinavia scandinavian caribbean britain british england scotland wales
    queensland tasmania victoria
    sydney melbourne brisbane perth adelaide canberra hobart darwin newcastle wollongong
    geelong ballarat bendigo townsville cairns toowoomba launceston mackay rockhampton
    bunbury bundaberg wagga albury tamworth dubbo mildura shepparton warrnambool gladstone
    gosford maitland parramatta chatswood docklands southbank cremorne collingwood abbotsford
    hawthorn camberwell dandenong footscray fitzroy carlton prahran malvern ringwood
    frankston armadale burwood
    auckland wellington christchurch dunedin tauranga queenstown napier zealand
    london manchester birmingham leeds glasgow edinburgh bristol liverpool sheffield cardiff
    belfast dublin cork paris lyon marseille berlin munich hamburg frankfurt cologne
    stuttgart amsterdam rotterdam brussels antwerp zurich geneva bern vienna prague warsaw
    krakow budapest bucharest sofia athens lisbon porto madrid barcelona valencia seville
    milan rome turin naples florence copenhagen stockholm gothenburg oslo helsinki tallinn
    riga vilnius reykjavik
    dubai doha riyadh jeddah manama muscat cairo nairobi lagos accra johannesburg pretoria
    durban casablanca istanbul ankara tehran karachi lahore islamabad mumbai delhi bangalore
    bengaluru hyderabad chennai kolkata pune ahmedabad noida gurgaon gurugram colombo dhaka
    kathmandu bangkok hanoi jakarta surabaya manila cebu taipei seoul busan tokyo osaka kyoto
    nagoya yokohama fukuoka sapporo beijing shanghai shenzhen guangzhou hangzhou chengdu
    wuhan tianjin
    toronto vancouver montreal calgary ottawa edmonton winnipeg halifax mississauga
    saskatchewan manitoba alberta newfoundland
    seattle portland denver austin dallas houston atlanta miami orlando tampa boston chicago
    philadelphia pittsburgh detroit minneapolis nashville charlotte raleigh columbus
    cincinnati cleveland indianapolis milwaukee omaha tucson albuquerque sacramento oakland
    berkeley fresno anaheim honolulu anchorage
    alabama alaska arizona arkansas california colorado connecticut delaware florida georgia
    hawaii idaho illinois indiana iowa kansas kentucky louisiana maryland massachusetts
    michigan minnesota mississippi missouri montana nebraska nevada ohio oklahoma oregon
    pennsylvania tennessee texas utah vermont virginia wisconsin wyoming
    """.split()
)

#: Multi-token place names, matched as whitespace-separated phrases so that
#: "New South Wales" or "San Francisco" are recognised without putting the
#: hopelessly generic "new"/"san"/"south" into the single-token set above.
_GEO_PHRASES = frozenset(
    tuple(phrase.split())
    for phrase in """
    new south wales|south australia|western australia|northern territory|
    australian capital territory|gold coast|sunshine coast|central coast|hunter valley|
    byron bay|alice springs|port macquarie|coffs harbour|surfers paradise|north sydney|
    st leonards|macquarie park|glen waverley|mount waverley|box hill|moonee ponds|
    new zealand|hong kong|sri lanka|saudi arabia|south africa|south korea|north korea|
    united arab emirates|new caledonia|papua new guinea|costa rica|el salvador|
    dominican republic|puerto rico|czech republic|bosnia and herzegovina|
    united kingdom|great britain|northern ireland|isle of man|
    united states|north america|south america|central america|latin america|middle east|
    asia pacific|south east asia|southeast asia|new york|san francisco|los angeles|
    san diego|san jose|santa clara|santa monica|palo alto|mountain view|menlo park|
    silicon valley|salt lake city|las vegas|san antonio|fort worth|st louis|new orleans|
    kansas city|washington dc|district of columbia|
    new jersey|new hampshire|new mexico|north carolina|south carolina|north dakota|
    south dakota|rhode island|west virginia|
    british columbia|nova scotia|new brunswick|prince edward island|
    kuala lumpur|ho chi minh|new delhi|tel aviv|abu dhabi|cape town|buenos aires|
    sao paulo|rio de janeiro|mexico city|panama city
    """.split("|")
    if phrase.split()
)
_GEO_PHRASE_MAX_TOKENS = max(len(phrase) for phrase in _GEO_PHRASES)

#: Region/state/country ABBREVIATIONS. These are far too ambiguous to mark
#: geography on their own — "MS" is Microsoft, "CA" a certificate authority,
#: "SA" a company suffix, "ACT" an ordinary English verb — so they count ONLY
#: when they sit inside a detected geographic span, or immediately beside a
#: confirmed place in a chain ("Melbourne, VIC, Australia", "Sydney NSW").
_GEO_WEAK_TOKENS = frozenset(
    """
    nsw vic qld wa sa tas nt act aus nz uk usa eu apj anzac
    al ak az ar ca co ct de fl ga hi id il ia ks ky md mi mn ms mo mt ne nv nh nj nm ny
    nc nd oh ok pa ri sc sd tn tx ut vt va wv wi wy dc
    qc bc ab mb sk ns nb nl pe
    """.split()
)

#: Where a captured location value ends. Deliberately does NOT stop at
#: determiners, so "our office in the Melbourne CBD" still yields a value.
_GEO_VALUE_STOP_RE = re.compile(
    r"[.;:!?\n()\[\]]|(?<=\s)[-–—](?=\s)"
    r"|\b(?:and|or|with|using|plus|including|for|as|who|which|that)\b",
    re.IGNORECASE,
)
_GEO_VALUE_MAX_CHARS = 80

#: An explicit location LABEL — the "Location: Melbourne" line every job board
#: emits. Requires a real separator, so the word "location" in prose ("this
#: location is our flagship") never opens a span.
#:
#: TWO forms, because the JD text the engine actually receives in production is
#: ``job_evidence_text`` = ``title + " " + description + " " + requirements`` —
#: one long line with no newline after the title. A ``^``-anchored label would
#: therefore never fire on the real production shape, only on the multi-line
#: postings used in tests. Measured 2026-08-04 on an Adzuna-shaped row: the
#: label "Location: Phoenix, AZ" sat mid-line and was missed entirely.
_GEO_LABEL_WORDS = (
    r"(?:job[ \t]+|work[ \t]+|office[ \t]+|primary[ \t]+)?"
    r"(?:locations?|offices?|based|city|cities|region|state|country|workplace|worksite)"
)
#: At the start of a line, a colon OR a dash introduces the value.
_GEO_LABEL_LINE_RE = re.compile(
    rf"^[ \t]*{_GEO_LABEL_WORDS}[ \t]*[:\-–—][ \t]*",
    re.IGNORECASE | re.MULTILINE,
)
#: Mid-line, only a COLON counts. A dash is ordinary punctuation there ("the
#: office - a converted warehouse - is...") and would open a span over prose.
#: ``\b`` keeps "Relocation:" from matching as "location:".
_GEO_LABEL_INLINE_RE = re.compile(rf"\b{_GEO_LABEL_WORDS}[ \t]*:[ \t]*", re.IGNORECASE)

#: Prose phrases that can only introduce a PLACE. Each one is a closed lexical
#: carrier, not a guess about the word that follows it.
_GEO_CARRIER_RES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:based|located|situated|headquartered)\s+(?:in|at|out\s+of)\s+",
        r"\b(?:relocat\w+|commut\w+|travel|move)\s+to\s+",
        r"\b(?:offices?|roles?|positions?|teams?|hubs?|sites?)\s+(?:is\s+|are\s+)?in\s+",
        r"\bwork(?:ing)?\s+(?:from|out\s+of)\s+",
        r"\b(?:onsite|on-site|in-office|hybrid|presence)\s+in\s+",
        r"\b(?:live|living|reside|residing|resident)\s+in\s+",
    )
)

#: The vocabulary of STATING WHERE a job is. Unlike a place NAME, none of
#: these can be a skill in any context — no honest résumé bullet contains
#: "location" as an achievement — so they need no every-occurrence protection
#: and are dropped wherever they appear. Confirmed live in production: the bare
#: noun "location" ranked 25th of 40 required keywords on job
#: ced2ed2e5e5a46d9bfa04f625 and reached the user's gap list as a permanent,
#: unclosable miss (TAILORING-EFFICACY-PROBE.md §7).
#:
#: DELIBERATELY ABSENT, each because the word really can be a skill or a
#: legitimate value elsewhere: "office" (MS Office), "state" (state
#: management), "region" (an AWS region), and the work-mode words "remote" and
#: "hybrid" — "remote" is a real value of this product's own ``location``
#: column, so suppressing it is a separate question that needs its own finding
#: rather than a quiet ride-along here.
_GEO_NON_SKILL_WORDS = frozenset(
    """
    location locations located relocation relocations relocate relocating
    suburb suburbs postcode postcodes commute commuting commutable
    worksite worksites workplace workplaces headquartered headquarters
    """.split()
)

#: Separators that join the parts of one location chain ("Melbourne, VIC").
_GEO_CHAIN_SEP_RE = re.compile(r"[ \t]*[,/|][ \t]*|[ \t]+[-–—][ \t]+")
_GEO_CHAIN_WHITESPACE_RE = re.compile(r"[ \t]+")


def _is_strong_geo(token: str) -> bool:
    """True for a token the geographic vocabulary recognises on its own.

    Also resolves the hyphenated compound the tokenizer produces for the most
    common geographic adjective in job ads: ``_TOKEN_RE`` keeps the hyphen, so
    "Melbourne-based" arrives as ONE token and would otherwise miss the set.
    """
    if token in _GEO_STRONG_TOKENS:
        return True
    head = token.split("-", 1)[0]
    return len(head) >= 4 and head in _GEO_STRONG_TOKENS


def _separator_chains(tokens: list[tuple[str, int, int]], text: str) -> list[list[int]]:
    """Maximal runs of token indices joined only by chain separators.

    "Truganina, Melbourne, VIC are encouraged" yields ``[truganina, melbourne,
    vic]`` and then singletons — the space before "are" is not a separator, so
    the chain ends there.
    """
    chains: list[list[int]] = []
    current: list[int] = []
    for index, (_token, start, _end) in enumerate(tokens):
        if current and _GEO_CHAIN_SEP_RE.fullmatch(text[tokens[index - 1][2] : start]):
            current.append(index)
            continue
        if current:
            chains.append(current)
        current = [index]
    if current:
        chains.append(current)
    return chains


def _geo_value_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges of location values introduced by a label or carrier."""
    spans: list[tuple[int, int]] = []
    #: (span_start, value_start). For a LABEL the span reaches back over the
    #: label word itself: "Location" in "Location: Melbourne" is part of the
    #: posting's location statement, not a skill the résumé must contain, and
    #: it was being reported to users as a missing keyword. The every-occurrence
    #: rule still applies, so "location" used elsewhere in prose survives.
    #: A CARRIER's span starts after it — "commute"/"relocate" are ordinary
    #: verbs in the surrounding sentence, not part of the place name.
    starts = [(match.start(), match.end()) for match in _GEO_LABEL_LINE_RE.finditer(text)]
    starts.extend((match.start(), match.end()) for match in _GEO_LABEL_INLINE_RE.finditer(text))
    for carrier in _GEO_CARRIER_RES:
        starts.extend((match.end(), match.end()) for match in carrier.finditer(text))
    for span_start, value_start in starts:
        window = text[value_start : value_start + _GEO_VALUE_MAX_CHARS]
        stop = _GEO_VALUE_STOP_RE.search(window)
        end = value_start + (stop.start() if stop else len(window))
        if end > value_start:
            spans.append((span_start, end))
    return spans


def _geographic_tokens(job_description: str) -> frozenset[str]:
    """Tokens in ``job_description`` that are the POSTING'S GEOGRAPHY (ATS-KW-001).

    A token qualifies only when EVERY occurrence of it in the posting sits
    inside a geographic span. Spans come from three independent signals:

    1. an explicit location label line (``Location: Docklands``);
    2. a closed set of prose carriers that can only introduce a place
       ("based in X", "relocate to X", "our office in X");
    3. a match in the geographic vocabulary above, then expanded across chain
       separators so the ambiguous parts of a multi-part location join it
       ("Melbourne, VIC, Australia" — ``vic`` alone would never qualify).

    The "every occurrence" rule is the whole safety argument. Signals 1 and 2
    are evidence about a POSITION in the text, not about a word, so a term that
    is both a place and a technology keeps its keyword status the moment it
    also appears outside every span — which is exactly what a skills list is.
    """
    tokens = _iter_tokens(job_description)
    if not tokens:
        return frozenset()

    # Signal 0 — the vocabulary of stating where. Never a skill anywhere, so
    # marked at every occurrence without needing positional evidence.
    marked: set[int] = {
        index
        for index, (token, _s, _e) in enumerate(tokens)
        if token in _GEO_NON_SKILL_WORDS
    }

    # Signals 1 + 2 — everything inside a labelled/carried location value.
    # Containment is tested on the token's START offset only: ``_TOKEN_RE``
    # absorbs a trailing "." into the token ("AZ." -> end past the sentence
    # stop), so requiring the whole token to fit inside the value would miss
    # every location that ends its sentence — which is most of them.
    value_spans = _geo_value_spans(job_description)
    if value_spans:
        for index, (_token, start, _end) in enumerate(tokens):
            if any(lo <= start < hi for lo, hi in value_spans):
                marked.add(index)

    # Signal 3a — multi-token place names, longest phrase first.
    seeds: set[int] = set()
    for index in range(len(tokens)):
        for length in range(min(_GEO_PHRASE_MAX_TOKENS, len(tokens) - index), 1, -1):
            window = tokens[index : index + length]
            if tuple(part for part, _s, _e in window) not in _GEO_PHRASES:
                continue
            gaps = [
                job_description[window[i][2] : window[i + 1][1]] for i in range(length - 1)
            ]
            if all(_GEO_CHAIN_WHITESPACE_RE.fullmatch(gap) for gap in gaps):
                seeds.update(range(index, index + length))
                break

    # Signal 3b — single-token place names.
    seeds.update(index for index, (token, _s, _e) in enumerate(tokens) if _is_strong_geo(token))

    # Signal 3c — chain expansion, so the parts of a multi-part location that
    # are not recognisable on their own ("Truganina", "VIC") join the part that
    # is. A region abbreviation next to a confirmed place reads as geography
    # across a comma OR plain whitespace ("Adelaide, SA", "Sydney NSW") — that
    # adjacency is the only thing that makes it readable as geography at all.
    weak = {index for index, (token, _s, _e) in enumerate(tokens) if token in _GEO_WEAK_TOKENS}
    for index in sorted(weak - seeds):
        for neighbour in (index - 1, index + 1):
            if not 0 <= neighbour < len(tokens) or neighbour not in seeds:
                continue
            low, high = min(index, neighbour), max(index, neighbour)
            gap = job_description[tokens[low][2] : tokens[high][1]]
            if _GEO_CHAIN_SEP_RE.fullmatch(gap) or _GEO_CHAIN_WHITESPACE_RE.fullmatch(gap):
                seeds.add(index)
                break

    # The rest of a location chain joins only when THAT chain already holds two
    # confirmed geographic elements. Requiring two, and counting them per chain
    # rather than per document, is what stops a comma-separated list that
    # merely happens to contain a place name from being walked to its end: in
    # "our type system: Georgia, Helvetica and Inter" the chain holds exactly
    # one confirmed element, so "Helvetica" never joins.
    for chain in _separator_chains(tokens, job_description):
        if len(chain) > 1 and sum(1 for index in chain if index in seeds) >= 2:
            seeds.update(chain)
    marked |= seeds

    total: Counter[str] = Counter()
    geographic: Counter[str] = Counter()
    for index, (token, _s, _e) in enumerate(tokens):
        total[token] += 1
        if index in marked:
            geographic[token] += 1
    return frozenset(token for token, count in total.items() if geographic[token] == count)


@lru_cache(maxsize=1)
def _load_embedding_model():
    """Return a cached sentence-transformers model, or None.

    The model is used only when the package is installed AND the weights are
    already on disk — scoring must never trigger a download (CI/offline).
    ``local_files_only=True`` is load-bearing for that guarantee: without it,
    sentence-transformers still makes a Hub freshness-check network call on
    construction even when every file is already cached (GMV4-ats-001).
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    cache = os.environ.get("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_DIR)
    try:
        cache_populated = os.path.isdir(cache) and bool(os.listdir(cache))
    except OSError as exc:
        # GMV4-ats-002: a cache dir that exists but cannot be listed
        # (permission error, transient FS/NFS issue, a remove-between-
        # isdir-and-listdir race) must degrade honestly, not raise into
        # warm_up_semantic_model's "never raises into startup" contract.
        _logger.warning("ATS embedding cache dir %s could not be listed: %s", cache, exc)
        cache_populated = False
    if not cache_populated:
        return None
    try:
        return SentenceTransformer(EMBEDDING_MODEL, cache_folder=cache, local_files_only=True)
    except Exception:  # pragma: no cover — corrupted cache etc.
        return None


def warm_up_semantic_model() -> str:
    """App-startup warm-up (§5.2 step 2): prime the local embedding-model
    cache and report which semantic-scoring path is ACTUALLY active.

    Attempts to load/cache ``all-MiniLM-L6-v2`` via sentence-transformers
    (which downloads into ``MODEL_CACHE_DIR`` only if not already cached —
    a no-op HTTP-wise once the weights are on disk). Never raises: a
    failed/slow/offline download must not crash the caller. Intended to run
    off the request path (see ``app.main``'s background-thread call) so it
    can never block application startup or the healthcheck.

    Returns the resolved active path — "local", "hf_api", or "degraded" —
    and logs it (at WARNING so operators cannot miss a degraded state),
    together with whether ``HF_TOKEN`` is configured (never its value).
    """
    try:
        from sentence_transformers import SentenceTransformer

        cache = os.environ.get("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_DIR)
        os.makedirs(cache, exist_ok=True)
        SentenceTransformer(EMBEDDING_MODEL, cache_folder=cache)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — best-effort warm-up only
        _logger.warning("ATS semantic model warm-up download failed: %s", exc)

    # The cache dir may have just been populated for the first time — drop
    # any earlier (possibly None) memoised result so the next real scoring
    # call re-resolves against the now-current disk state.
    _load_embedding_model.cache_clear()
    model = _load_embedding_model()
    if model is not None:
        path = "local"
    elif os.environ.get("HF_TOKEN", "").strip():
        path = "hf_api"
    else:
        path = "degraded"
    _logger.warning(
        "ATS semantic scoring active path=%s (HF_TOKEN=%s)",
        path,
        "<set>" if os.environ.get("HF_TOKEN", "").strip() else "<absent>",
    )
    return path


class ATSEngine:
    """Scores a resume against a job description. Stateless and deterministic."""

    def score(self, resume_text: str, job_description: str) -> ATSScore:
        keyword_match, matched, missing = self._keyword_match(resume_text, job_description)
        try:
            detailed = self._semantic_similarity_detailed(resume_text, job_description)
            semantic = _clamp(detailed.value * 100.0)
            semantic_path = detailed.path
        except SemanticScoringUnavailableError as exc:
            # HONEST DEGRADATION (§5.2 step 1): never silently substitute the
            # old token-overlap approximation. ``semantic_path="degraded"``
            # is the truthful signal the caller/UI must check before
            # presenting ``semantic_similarity`` as a real score.
            _logger.warning("ATS semantic scoring degraded: %s", exc)
            semantic = _DEGRADED_SEMANTIC_SCORE
            semantic_path = "degraded"
        if not _content_tokens(resume_text) or not _content_tokens(job_description):
            # NO EVIDENCE ON ONE SIDE -> there is no semantic overlap to
            # measure, and whatever the step above produced for it is an
            # artifact rather than a measurement. An embedding model still
            # returns a vector for an empty (or wholly-boilerplate) string, so
            # an EMPTY resume scored semantic_similarity 11.875 -> overall 4.75
            # while keyword_match and experience_gap were both a correct 0.
            # That figure propagated into
            # ``tailor_agent._compute_conversion_metrics`` as the
            # ``baselineATSScore`` divisor behind the user-facing
            # ``estimatedConversionLift``.
            #
            # This is the resume-side twin of the gate ``557739e`` added on the
            # job side ("an empty job description was scoring 74.63 — refuse to
            # score on no evidence"). 0.0 is the honest answer here, not a
            # placeholder: ``semantic_path`` is left exactly as the path above
            # resolved it, because "degraded" means "we could not measure" —
            # a different and weaker claim than "there is nothing to measure".
            semantic = 0.0
        experience = self._experience_score(resume_text, job_description)

        overall = _clamp(
            _WEIGHT_KEYWORD * keyword_match
            + _WEIGHT_SEMANTIC * semantic
            + _WEIGHT_EXPERIENCE * experience
        )
        return ATSScore(
            overall=round(overall, 2),
            keyword_match=round(keyword_match, 2),
            # Rounded to 4dp (not 2dp like the other components): a genuine
            # embedding cosine similarity is a precise real measurement, and
            # 2dp rounding can lose > 1e-3 of it (GMV4-ats-001 test E pins a
            # 1e-3 tolerance against the unrounded value) — 4dp keeps display
            # precision sane while never discarding meaningful signal.
            semantic_similarity=round(semantic, 4),
            experience_gap=round(experience, 2),
            matched_keywords=matched,
            missing_keywords=missing,
            requires_review=overall < REVIEW_THRESHOLD,
            semantic_path=semantic_path,
        )

    # -- components ----------------------------------------------------------

    def _keyword_match(
        self, resume_text: str, job_description: str
    ) -> tuple[float, list[str], list[str]]:
        """Coverage of the JD's TF-IDF-ranked keywords inside the resume."""
        keywords = self._extract_keywords(job_description)
        if not keywords:
            return 0.0, [], []
        resume_tokens = set(_content_tokens(resume_text))
        matched = [kw for kw in keywords if kw in resume_tokens]
        missing = [kw for kw in keywords if kw not in resume_tokens]
        return _clamp(100.0 * len(matched) / len(keywords)), matched, missing

    def _extract_keywords(self, job_description: str) -> list[str]:
        """Top JD terms ranked by TF-IDF weight (deterministic tie-break).

        The posting's own GEOGRAPHY is removed first (ATS-KW-001): a city is
        not a skill, so it must not sit in the required-keyword set, must not
        consume one of the ``_MAX_KEYWORDS`` slots, and must not appear in the
        ``missing_keywords`` gap list the user is shown. See
        :func:`_geographic_tokens` for how a place is told apart from a
        homonymous technology.
        """
        tokens = _content_tokens(job_description)
        if not tokens:
            return []
        geography = _geographic_tokens(job_description)
        if geography:
            remaining = [token for token in tokens if token not in geography]
            if remaining:
                tokens = remaining
            else:
                # Every content token read as geography. That is a posting with
                # no scorable skill content, not a licence to score against an
                # empty required-keyword set (which _keyword_match would report
                # as a flat 0.0 for every résumé alike). Keep the unfiltered
                # tokens and say so, rather than emit a silent 0.
                _logger.warning(
                    "ATS keyword extraction: every content token read as geography "
                    "(%d tokens); keeping the unfiltered set",
                    len(tokens),
                )
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            vectorizer = TfidfVectorizer(
                analyzer=lambda _: tokens, lowercase=False  # noqa: ARG005
            )
            matrix = vectorizer.fit_transform([job_description])
            weights = matrix.toarray()[0]
            terms = vectorizer.get_feature_names_out()
            ranked = sorted(zip(terms, weights), key=lambda tw: (-tw[1], tw[0]))
            return [term for term, _ in ranked[:_MAX_KEYWORDS]]
        except ImportError:  # pragma: no cover — sklearn is a hard dep, belt-and-braces
            seen: dict[str, None] = {}
            for token in tokens:
                seen.setdefault(token, None)
            return list(seen)[:_MAX_KEYWORDS]

    def _semantic_similarity(self, resume_text: str, job_description: str) -> float:
        """0-100 semantic-similarity score, built on
        :meth:`_semantic_similarity_detailed` (the single source of truth).

        Raises :class:`SemanticScoringUnavailableError` when neither a local
        nor HF-hosted embedding model is available. This method never
        substitutes a token-overlap approximation — a caller that needs an
        honest degraded fallback (like :meth:`score`) must catch this itself.
        """
        detailed = self._semantic_similarity_detailed(resume_text, job_description)
        return _clamp(detailed.value * 100.0)

    def _semantic_similarity_detailed(
        self, resume_text: str, job_description: str
    ) -> _SemanticSimilarityResult:
        """Genuine [0, 1] semantic similarity + which path produced it.

        Priority order (§5.2):
          1. LOCAL — ``_load_embedding_model()`` (sentence-transformers,
             already cached on disk; no network I/O).
          2. HF INFERENCE API — only when the local model is unavailable;
             requires ``HF_TOKEN`` in the environment.
        Raises :class:`SemanticScoringUnavailableError` when neither path can
        produce a genuine score — never returns a token-overlap number.
        """
        model = _load_embedding_model()
        if model is not None:
            embeddings = model.encode([resume_text, job_description], convert_to_numpy=True)
            a, b = embeddings[0], embeddings[1]
            denom = (a @ a) ** 0.5 * (b @ b) ** 0.5
            value = 0.0 if denom == 0 else float(a @ b) / float(denom)
            return _SemanticSimilarityResult(value=max(0.0, min(1.0, value)), path="local")

        values = self._call_hf_inference_api(job_description, [resume_text])
        return _SemanticSimilarityResult(value=values[0], path="hf_api")

    def _call_hf_inference_api(self, source_sentence: str, sentences: list[str]) -> list[float]:
        """POST to the HF Inference API sentence-similarity endpoint (§5.2).

        Payload shape is fixed by spec:
        ``{"inputs": {"source_sentence": ..., "sentences": [...]}}``.
        ``HF_TOKEN`` is read from the environment at call time (never
        hardcoded, never logged). Any missing token or non-2xx response
        raises :class:`SemanticScoringUnavailableError` — never falls
        through to a token-overlap approximation.
        """
        token = os.environ.get("HF_TOKEN", "").strip()
        if not token:
            raise SemanticScoringUnavailableError(
                "HF Inference API unavailable: HF_TOKEN=<absent>"
            )
        try:
            response = httpx.post(
                _HF_API_URL,
                json={"inputs": {"source_sentence": source_sentence, "sentences": sentences}},
                headers={"Authorization": f"Bearer {token}"},
                timeout=_HF_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SemanticScoringUnavailableError(
                f"HF Inference API returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SemanticScoringUnavailableError(
                f"HF Inference API request failed: {exc.__class__.__name__}: {exc}"
            ) from exc

        try:
            raw = response.json()
        except ValueError as exc:
            raise SemanticScoringUnavailableError(
                "HF Inference API returned a non-JSON response"
            ) from exc
        if not isinstance(raw, list) or not raw:
            raise SemanticScoringUnavailableError(
                f"HF Inference API returned an unexpected response shape: {raw!r}"
            )
        return [max(0.0, min(1.0, float(v))) for v in raw]

    def _experience_score(self, resume_text: str, job_description: str) -> float:
        """100 if the resume meets the JD's years requirement, pro-rated below."""
        required = self._max_years(job_description)
        if required is None or required == 0:
            return 100.0  # no explicit requirement — neutral
        have = self._max_years(resume_text)
        if have is None:
            return 0.0  # requirement stated, resume shows nothing
        if have >= required:
            return 100.0
        return _clamp(100.0 * have / required)

    @staticmethod
    def _max_years(text: str) -> int | None:
        matches = [int(m.group(1)) for m in _YEARS_RE.finditer(text)]
        return max(matches) if matches else None
