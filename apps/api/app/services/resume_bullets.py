"""Résumé → discrete achievement bullets, and the achievement identity a Story
Bank entry is keyed on.

WHY THIS EXISTS (audited live on the production DB, 2026-08-02)
--------------------------------------------------------------
The owner's Story Bank held 43 live ``StoryEntry`` rows describing only ~10
distinct achievements — 33 near-duplicate re-tellings — while ~17 genuinely
distinct résumé achievements had no story at all, and two rows carried no
metric whatsoever. Sample of the duplication, all four of these are the SAME
résumé bullet:

    "JIRA Analytics Dashboard for Agile Insight Generation"
    "JIRA Analytics Dashboard for Sprint Velocity & LLM-Powered Retrospectives"
    "JIRA Analytics Dashboard for Agile Team Visibility"
    "Analytics Dashboard for Sprint Velocity & LLM-Retrospectives"

The extractor had no stable notion of *which achievement* a story is about. It
deduped on (a) an exact sha256 of the five STAR fields — one reworded word
defeats it — and (b) a fuzzy title+achievement Jaccard pair whose create-time
preset requires title Jaccard >= 0.70. Measured over all 903 pairs of the live
rows, same-achievement pairs have a MEDIAN title Jaccard of 0.333 and a 90th
percentile of 0.625: the live duplicates sit almost entirely BELOW the
threshold, which is exactly why they accumulated.

No threshold tweak fixes that, because paraphrase drift is unbounded. The fix
is to stop guessing from prose and anchor every story to the one thing that is
both stable and real: **the résumé bullet the story is drawn from**.

WHAT THIS MODULE PROVIDES
-------------------------
* :func:`extract_resume_bullets` — deterministic (no LLM) segmentation of the
  user's OWN résumé text into the achievement bullets it actually contains,
  each with a stable ``B<n>`` handle. The extractor prompt hands the model
  these bullets and requires each story to cite one by id, so the story's
  evidence is a real, addressable slice of the user's own résumé rather than
  an unverifiable claim about it.
* :func:`bullet_numbers` — the numeric tokens THAT bullet evidences. The old
  metric guard validated a story's numbers against the WHOLE résumé, so a
  war-room story could "evidence" the 92% that belongs to a different bullet
  entirely. Scoping the check to the cited bullet closes that hole.
* :func:`achievement_key` — the per-user identity of an achievement: a sha256
  over the bullet's normalized text. Two stories citing the same bullet share
  a key no matter how far their wording drifts, which turns dedup from a
  similarity heuristic into an exact lookup (and into a database uniqueness
  guarantee — see ``app.db.ensure_story_achievement_column``).
* :func:`claim_numbers` — the numbers a piece of GENERATED PROSE claims, on
  exactly the same reading of "a number" the bullet side uses, so the two
  sides of the comparison can never disagree about what a number is.
* :func:`resume_employers` / the ``employers`` key on every extracted bullet —
  WHICH EMPLOYER a bullet belongs to. The organisation guard used to be a
  substring test over the WHOLE résumé, so any employer the candidate ever had
  "evidenced" any bullet (live: an Independent-consulting project tagged
  ``Australian Taxation Office (ATO)``). Binding the check to the cited
  bullet's own section closes that (STORY-NARRATIVE-GROUNDING-2026-08-03).
* :func:`organisation_matches` — whether a claimed organisation IS one of
  those employers. An identity test over whole normalized names, never a
  containment test: matching a substring in either direction let "ANZ Stadium"
  claim the ANZ bullets and "Apple" claim "Apple Bank for Savings"
  (STORY-ORG-SUBSTRING-2026-08-03).

Nothing here invents content. Every bullet returned is a verbatim slice of the
user's own résumé (whitespace-normalized and de-hyphenated across the PDF line
breaks that split words such as ``"test- evidence"``), and every employer
returned is a line the résumé itself prints above a date range.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

#: A bullet marker sitting alone on its own line. Some PDF text extractions
#: (see ``app.services.resume_parser``) emit the glyph and its content on
#: separate lines, which makes this the cleanest record separator available.
_BULLET_SEPARATOR = re.compile(r"(?m)^[ \t]*[•●▪‣⁃*\-·]+[ \t]*$")

#: The same glyphs ANYWHERE in the text. Multi-column résumé layouts (the
#: operator's own bundled PDF is one) extract with the marker inline and the
#: side column interleaved between lines, so no own-line separator exists at
#: all. Verified: the own-line pattern finds 0 bullets in that layout while
#: this one finds all of them. Only unambiguous bullet glyphs are listed —
#: "-" and "*" occur inside ordinary prose and would shred it.
_INLINE_BULLET = re.compile(r"[•●▪‣⁃]")

#: Below this many bullets, the own-line split is assumed not to be the
#: document's real structure and the inline split is tried as well.
_SPARSE_SPLIT = 3

#: Section headings. A segment containing one is résumé chrome (contact block,
#: skills column, certifications list), never a single achievement.
_SECTION_HEADING = re.compile(
    r"\b(CONTACT INFO|CONTACT|EDUCATION|SKILLS|CERTIFICATIONS?|WORK EXPERIENCE|"
    r"EXPERIENCE|CAREER OBJECTIVE|OBJECTIVE|PROJECTS?|PROFESSIONAL SUMMARY|"
    r"SUMMARY|REFERENCES|HONORS|HONOURS|AWARDS|PUBLICATIONS|INTERESTS|"
    r"LANGUAGES|VOLUNTEER)\b"
)

#: Prose function words. A comma-separated skills column ("Enterprise
#: Architecture, Data Architecture, MLOps, CI/CD, DevOps, …") contains none of
#: these; a sentence describing an achievement always contains several. This
#: is what separates the two WITHOUT a hand-maintained skills blocklist.
_FUNCTION_WORD = re.compile(
    r"\b(the|to|a|an|of|for|with|that|through|by|from|into|across|"
    r"which|while|after|before|when)\b",
    re.IGNORECASE,
)

#: A word split across a PDF line break: "test- evidence" -> "test-evidence".
_SOFT_HYPHEN_BREAK = re.compile(r"(?<=[A-Za-z])-\s+(?=[a-z])")

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

#: A digit run NOT glued to a preceding letter OR digit — a measurement
#: rather than an identifier ("D3", "AC6-AC19", "log4j", ".NET"). The digit
#: exclusion matters: without it "AC19" still "quantified" a bullet via its
#: trailing 9, whose predecessor is a digit rather than the letter that
#: started the token. Same rule as ``story_extractor._NUMBER_RE``.
_STANDALONE_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d")

#: Magnitude suffixes a résumé writes numbers with ("10k+", "$5M", "2bn").
_MAGNITUDES = {"k": 1_000, "m": 1_000_000, "bn": 1_000_000_000, "b": 1_000_000_000}
_MAGNITUDE = re.compile(r"\s?(bn|[kmb])\b")

#: A parenthetical inside an organisation name. On the RÉSUMÉ side this is the
#: employer's own printed short form ("Australian Taxation Office (ATO)"); on
#: the CLAIM side it is not read as a name at all (see
#: :func:`_organisation_identities`).
_PARENTHETICAL = re.compile(r"\(([^)]*)\)")

#: Legal-form words a registered name ENDS with. A résumé prints "Microsoft
#: Inc." where a story writes "Microsoft"; both name one employer, and the
#: difference is a company-registration detail, not a different organisation.
_LEGAL_FORM_WORDS = frozenset({
    "pty", "ltd", "limited", "plc", "llc", "llp", "lp", "inc", "incorporated",
    "corp", "corporation", "company", "co", "gmbh", "ag", "nv", "bv", "sa",
    "sas", "srl", "spa", "pte", "oy", "ab", "kk", "kft", "sro",
})

#: Articles a name may lead with ("The Warehouse" / "Warehouse").
_LEADING_ARTICLES = frozenset({"the"})

#: Spelled-out small numbers a résumé uses in prose ("in under three hours").
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12",
}

#: A number a piece of GENERATED PROSE claims. Deliberately STRICTER than
#: :data:`_NUMBER` (which reads the évidence side): a digit run glued to a
#: preceding letter or digit is an identifier, not a claim — "p95_latency",
#: "D3 arcs", "AC6-AC19", "log4j" — and holding a story to evidencing "95"
#: because it wrote "P95" rejected real, fully-evidenced stories.
_CLAIM_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?")

#: Sentence boundary — terminal punctuation followed by whitespace. Used to
#: remove the ONE sentence carrying an unevidenced number without touching the
#: rest of a paragraph. "3.5 hours" is safe: its dot has no space after it.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

#: A month name as a résumé prints it ("Sept", "March", "Jun").
_MONTH = (
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
)
_DATE_POINT = rf"(?:{_MONTH}\s+)?(?:19|20)\d{{2}}"

#: A WHOLE LINE that is a date range — "March 2026 - Present",
#: "Sept 2017 - June 2025", "2017 - 2022". This is the one structural marker
#: that reliably survives PDF text extraction of a work-experience block, in
#: every layout observed (single- and multi-column). It must be the whole line:
#: a bullet whose own text contains "(2022 - 2025)" is prose, not a header.
_DATE_RANGE_LINE = re.compile(
    rf"{_DATE_POINT}\s*[-–—]+\s*(?:{_DATE_POINT}|present|current|now|date)\.?",
    re.IGNORECASE,
)

#: An employer line is a NAME, not a sentence. Anything longer than this is a
#: paragraph that happens to sit above a date and is not an employer.
_MAX_EMPLOYER_CHARS = 80

#: Segmentation gates. Deliberately shape-based (length / word count / prose
#: density), never keyword-based, so they generalise to any user's résumé.
_MIN_CHARS = 60
_MAX_CHARS = 1200
_MIN_WORDS = 10
_MIN_FUNCTION_WORDS = 2


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def canonicalize_bullet(text: str) -> str:
    """A bullet's display form: whitespace collapsed, PDF hyphenation repaired.

    This is the exact text handed to the model and stored as the story's
    evidence, so it must stay a verbatim (if re-whitespaced) slice of the
    user's own résumé — never a rewrite.
    """
    return _SOFT_HYPHEN_BREAK.sub("-", _normalize_whitespace(text))


def _is_achievement(text: str) -> bool:
    if _SECTION_HEADING.search(text):
        return False
    if not (_MIN_CHARS <= len(text) <= _MAX_CHARS):
        return False
    if len(text.split()) < _MIN_WORDS:
        return False
    return len(_FUNCTION_WORD.findall(text)) >= _MIN_FUNCTION_WORDS


def _segments(text: str) -> list[str]:
    """The résumé split into records, by whichever strategy fits the layout.

    Three are tried, best-first, because résumé PDFs do not extract uniformly:
    own-line bullet markers (cleanest), inline bullet glyphs (multi-column
    layouts), then paragraphs (no glyphs at all). The strategy that yields the
    most achievement bullets wins, so a document is never reduced to "no
    evidence" by a layout quirk.

    The NON-achievement segments are returned too, and they matter: they are
    where the job headers live, which is what binds each bullet to the employer
    that owns it.
    """

    def _kept(segments: list[str]) -> int:
        return sum(
            1 for s in (canonicalize_bullet(x) for x in segments) if _is_achievement(s)
        )

    own_line = _BULLET_SEPARATOR.split(text)
    best = own_line
    if _kept(own_line) < _SPARSE_SPLIT:
        inline = _INLINE_BULLET.split(text)
        if _kept(inline) > _kept(own_line):
            best = inline
    if _kept(best) == 0:
        best = re.split(r"\n\s*\n", text)
    return best


def _employer_headers(segment: str) -> list[str]:
    """The employer names this segment prints above a date range.

    A work-experience header block extracts as a small run of lines — role,
    employer, dates, location — so the employer is the last non-empty line
    BEFORE a line that is entirely a date range. Nothing is inferred: every
    string returned is a verbatim line of the user's own résumé.
    """
    lines = [line.strip() for line in (segment or "").splitlines()]
    found: list[str] = []
    for index, line in enumerate(lines):
        if not _DATE_RANGE_LINE.fullmatch(line):
            continue
        for previous in reversed(lines[:index]):
            if not previous:
                continue
            if (
                _DATE_RANGE_LINE.fullmatch(previous)
                or _SECTION_HEADING.search(previous)
                or len(previous) > _MAX_EMPLOYER_CHARS
            ):
                break
            found.append(previous)
            break
    return list(dict.fromkeys(found))


def resume_employers(resume_text: str) -> list[str]:
    """Every employer name the résumé prints above a date range, in order."""
    return list(
        dict.fromkeys(
            employer
            for segment in _segments(resume_text or "")
            for employer in _employer_headers(segment)
        )
    )


def extract_resume_bullets(resume_text: str) -> list[dict[str, Any]]:
    """The achievement bullets in ``resume_text``, in document order.

    Returns ``[{"id": "B1", "text": "<verbatim bullet>", "employers": [...]},
    ...]``. Ids are positional and therefore stable for a given résumé text,
    which is what lets the model cite one and lets the caller verify the
    citation.

    ``employers`` is the employer(s) whose header block most recently preceded
    this bullet — the candidates for "who the candidate worked for when they
    did this". It is a LIST, not a single name, because a multi-column PDF
    extracts several consecutive job headers before the bullet group they
    introduce (verified on the owner's own résumé: ANZ, ANZ, NAB and Microsoft
    all print before the nine bullets that follow). Naming one of them would be
    a guess; naming the set is exactly what the document supports, and it is
    still enormously tighter than "any word anywhere in the résumé", which is
    what the organisation guard used before. A layout that yields no header at
    all yields an empty list, and the caller degrades honestly.
    """
    text = resume_text or ""
    bullets: list[dict[str, Any]] = []
    pending: list[str] = []
    current: list[str] = []
    for segment in _segments(text):
        canonical = canonicalize_bullet(segment)
        if _is_achievement(canonical):
            if pending:
                current, pending = pending, []
            bullets.append(
                {
                    "id": f"B{len(bullets) + 1}",
                    "text": canonical,
                    "employers": list(current),
                }
            )
            continue
        headers = _employer_headers(segment)
        if headers:
            # Accumulate across consecutive non-achievement segments: the
            # header block and the bullets it introduces are often separated
            # by side-column chrome that splits into several segments.
            pending = list(dict.fromkeys(pending + headers))
    return bullets


def bullet_numbers(text: str) -> set[str]:
    """Numeric tokens evidenced by THIS bullet.

    Every value here is something the bullet ITSELF states — the set is the
    bullet's own claims written the several ways a writer may legitimately
    render them, never an inference, an estimate or a round-up:

    * thousands separators dropped ("$5,000" evidences "5000");
    * a decimal evidenced whole and split, so "3.5 hours" may be written
      "3.5", "3" or "5";
    * MAGNITUDE SUFFIXES expanded — a bullet saying "10k+ device concurrency"
      evidences "10000" (and "10,000" once separators are stripped), and "$5M"
      evidences "5000000". "10k" and "10,000" are the same claim in different
      notation; rejecting the second as fabricated was a FALSE POSITIVE
      (observed live: a real WebSocket story rejected for writing "10,000+");
    * SPELLED-OUT small numbers — "in under three hours" evidences "3". The
      résumé says three; a story writing "3 hours" has invented nothing.

    Both expansions only ever ADD renderings of numbers the bullet already
    states. A number the bullet does not state in ANY form is still rejected,
    which is the entire point of the check.
    """
    numbers: set[str] = set()

    def _add(value: str) -> None:
        plain = value.replace(",", "")
        numbers.add(plain)
        if "." in plain:
            numbers.add(plain.rstrip("0").rstrip("."))
            whole, _, frac = plain.partition(".")
            numbers.add(whole)
            numbers.add(frac)

    lowered = (text or "").lower()
    for match in _NUMBER.finditer(text or ""):
        _add(match.group())
        suffix = _MAGNITUDE.match(lowered[match.end():])
        if suffix:
            scaled = float(match.group().replace(",", "")) * _MAGNITUDES[
                suffix.group(1).lower()
            ]
            _add(f"{scaled:.0f}" if scaled == int(scaled) else str(scaled))
    for word, digit in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            numbers.add(digit)
    return {n for n in numbers if n}


def is_quantified(text: str) -> bool:
    """True when the bullet states a real quantity a story must carry.

    A digit glued to letters is an IDENTIFIER, not a measurement — "D3 event
    arcs", "AC6-AC19", "log4j", ".NET", "PI 47-48". Counting those as
    quantification made the extractor drop perfectly good stories for
    "carrying no metric" when their source bullet had no metric to carry
    (observed live: the D3 visualisation bullet). Only a digit run that does
    not begin immediately after a letter counts.
    """
    return bool(_STANDALONE_NUMBER.search(text or ""))


def claim_numbers(text: str) -> list[str]:
    """The numbers a piece of GENERATED PROSE claims, in order, normalized.

    Thousands separators are dropped so "10,000" and "10000" are the same
    claim — the same normalization :func:`bullet_numbers` applies to the
    evidence side, so the two sides can never disagree about notation.

    Duplicates are kept (the caller reports which sentence carried what), and
    identifiers are NOT claims: "P95", "D3", "AC6-AC19" and "log4j" carry no
    quantity, so the regex ignores a digit run that starts immediately after a
    letter or digit.
    """
    return [m.group().replace(",", "") for m in _CLAIM_NUMBER.finditer(text or "")]


def unevidenced_claims(text: str, evidenced: set[str]) -> list[str]:
    """Numbers ``text`` claims that ``evidenced`` does not support."""
    seen: dict[str, None] = {}
    for number in claim_numbers(text):
        if number not in evidenced:
            seen[number] = None
    return list(seen)


def strip_unevidenced_sentences(
    text: str, evidenced: set[str]
) -> tuple[str, list[str]]:
    """``text`` with every sentence carrying an unevidenced number REMOVED.

    Returns the surviving prose and the numbers that were removed with it.
    This only ever DELETES: no sentence is rewritten, no number is changed and
    nothing is added, so the survivor is still the model's own wording and is
    still entirely supported by ``evidenced``. A caller that finds the
    survivor too thin to be a usable story must reject the story — which is
    what the extractor does.
    """
    kept: list[str] = []
    removed: dict[str, None] = {}
    for sentence in _SENTENCE_BREAK.split(text or ""):
        offenders = unevidenced_claims(sentence, evidenced)
        if offenders:
            for number in offenders:
                removed[number] = None
            continue
        if sentence.strip():
            kept.append(sentence.strip())
    return " ".join(kept), list(removed)


def _name_tokens(name: str) -> tuple[str, ...]:
    """An organisation name as lowercase alphanumeric words, in order."""
    return tuple(re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split())


def _without_legal_form(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """``tokens`` with a leading article and a TRAILING legal form removed.

    Only the ends are touched, and only words that cannot change WHICH
    organisation is named: "Microsoft Pty Ltd" and "Microsoft" are one
    employer. A legal-form word in the MIDDLE of a name is part of the name
    ("Inc. Magazine", "Ltd Commodities") and is left alone.
    """
    trimmed = list(tokens)
    while trimmed and trimmed[0] in _LEADING_ARTICLES:
        trimmed.pop(0)
    while trimmed and trimmed[-1] in _LEGAL_FORM_WORDS:
        trimmed.pop()
    return tuple(trimmed)


def _organisation_identities(
    name: str, *, printed_short_forms: bool
) -> set[tuple[str, ...]]:
    """Every WHOLE name ``name`` gives for one organisation.

    Each identity is a complete token sequence, never a fragment of one, so
    comparing two names is an equality test and can never be satisfied by a
    collision inside a longer name.

    ``printed_short_forms`` is set only for a name read off the RÉSUMÉ: a
    résumé that prints ``Australian Taxation Office (ATO)`` is printing two
    complete names for its own employer, so the parenthetical is an alias.
    It is NOT set for a name a story CLAIMS, because a parenthetical there is
    routinely a region or a qualifier — reading "Deloitte (ANZ)" as naming
    "ANZ" would hand a bank's bullet to a consultancy.

    Nothing is inferred either way: an acronym the document never prints is
    not an alias, so "NAB" names "National Australia Bank" only when the
    résumé itself prints the "(NAB)".
    """
    text = name or ""
    variants = [text, _PARENTHETICAL.sub(" ", text)]
    if printed_short_forms:
        variants.extend(_PARENTHETICAL.findall(text))
    identities: set[tuple[str, ...]] = set()
    for variant in variants:
        tokens = _name_tokens(variant)
        if not tokens:
            continue
        identities.add(tokens)
        trimmed = _without_legal_form(tokens)
        if trimmed:
            identities.add(trimmed)
    return identities


def organisation_matches(organisation: str, employers: list[str]) -> bool:
    """True when ``organisation`` IS one of ``employers``.

    An IDENTITY test, not a containment test. The previous implementation
    matched ``wanted in known or known in wanted`` over the space-delimited
    name, which is still a substring test: any organisation whose name is a
    word-run INSIDE an employer's name ("Apple" against "Apple Bank for
    Savings"), or that CONTAINS one ("ANZ Stadium" against "ANZ"), passed.
    Measured on the owner's own résumé, that accepted a foreign employer for
    every one of its 21 bullets (STORY-ORG-SUBSTRING-2026-08-03).

    Names are now compared as whole normalized token sequences. The only
    things normalized away are things that do not change which organisation
    is named: case, punctuation, a leading article, a trailing legal form,
    and the employer's OWN printed short form (see
    :func:`_organisation_identities`).
    """
    wanted = _organisation_identities(organisation, printed_short_forms=False)
    if not wanted:
        return False
    return any(
        wanted & _organisation_identities(employer, printed_short_forms=True)
        for employer in employers
    )


def organisation_appears_in_text(organisation: str, text: str) -> bool:
    """True when ``text`` prints ``organisation`` as WHOLE WORDS.

    The last-resort check, for a résumé whose layout yields no employer
    header at all. It is word-bound rather than a raw substring scan, so
    "Taxation Offic" no longer "appears" in a résumé that says "Taxation
    Office". It says nothing about WHICH job the name belongs to — the caller
    uses it only when the document supports no better answer.
    """
    stream = f" {' '.join(_name_tokens(text))} "
    return any(
        f" {' '.join(tokens)} " in stream
        for tokens in _organisation_identities(organisation, printed_short_forms=False)
    )


def _identity_text(text: str) -> str:
    """Wording-stable identity of a bullet: lowercased alphanumerics only.

    Case, punctuation and whitespace drift between two renderings of the same
    résumé bullet must not create a second achievement; a genuinely different
    bullet must not collide. Digits are KEPT — "30 to 90 person-days" and
    "30 to 120 person-days" are different claims.
    """
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def achievement_key(user_id: str, bullet_text: str) -> str:
    """Per-user identity of the achievement ``bullet_text`` describes.

    Scoped by ``user_id`` so two users whose résumés share a boilerplate line
    can never collide into one row, and truncated to 32 hex chars (128 bits) —
    collision-free at any plausible Story Bank size while staying comfortably
    inside an index.
    """
    digest = hashlib.sha256(
        f"{user_id}\x1f{_identity_text(bullet_text)}".encode()
    ).hexdigest()
    return digest[:32]


def find_bullet(bullets: list[dict[str, Any]], bullet_id: Any) -> dict[str, Any] | None:
    """The bullet with ``bullet_id`` (case/whitespace tolerant), or ``None``."""
    wanted = str(bullet_id or "").strip().upper()
    if not wanted:
        return None
    for bullet in bullets:
        if str(bullet["id"]).upper() == wanted:
            return bullet
    return None
