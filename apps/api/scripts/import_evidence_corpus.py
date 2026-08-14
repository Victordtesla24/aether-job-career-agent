#!/usr/bin/env python3
"""Import a U2c-0 evidence-corpus snapshot into the app's data layer (U2b).

The corpus (``uat/reports/evidence/agents-uplift/u2c-0/corpus.json``) is a
provenance-tagged snapshot of ONE user's real evidence — their immutable
baseline résumé, their portfolio site and their public GitHub repos. It is an
import INPUT, not a store: the rows live in ``EvidenceCorpusItem`` keyed by
user, so the tailoring guard reads the corpus of the user it is tailoring for
and never the operator's.

Usage::

    python scripts/import_evidence_corpus.py --user <userId> --file corpus.json
    python scripts/import_evidence_corpus.py --user <userId> --file corpus.json \\
        --replace-sources baseline,portfolio

``--replace-sources`` drops that user's existing items for the named sources
first, which is what a scheduled refresh does so retracted evidence stops being
citable. Without it the import is a pure idempotent upsert on each item's own
id. Nothing is fabricated: only the items present in the file are written.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.evidence_corpus import import_corpus_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, help="target userId")
    parser.add_argument("--file", required=True, help="path to corpus.json")
    parser.add_argument(
        "--replace-sources",
        default="",
        help="comma-separated sources to clear before import (e.g. baseline,portfolio)",
    )
    args = parser.parse_args()

    sources = [s.strip() for s in args.replace_sources.split(",") if s.strip()]
    written = import_corpus_file(args.user, args.file, replace_sources=sources)
    print(f"imported {written} evidence items for user {args.user} from {args.file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
