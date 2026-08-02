"""W-CLEAN — run the user-visible fixture-marker audit against a live database.

Read-only. Exits 1 when any marker is found, so it can gate a deploy.

Usage (from ``apps/api``)::

    DATABASE_URL='postgresql://…' python3 scripts/audit_fixture_markers.py
    python3 scripts/audit_fixture_markers.py --schema aether --json out.json

With no ``DATABASE_URL`` in the environment the repo-root ``.env`` is read, the
same way ``scripts/seed_demo.py`` does for a standalone run.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|(.*))$")


def _load_root_env_into_environ() -> None:
    root_env = Path(__file__).resolve().parents[3] / ".env"
    if not root_env.exists():
        return
    for line in root_env.read_text().splitlines():
        match = _ENV_LINE.match(line.strip())
        if match and match.group(1) not in os.environ:
            os.environ[match.group(1)] = next(
                g for g in match.groups()[1:] if g is not None
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="aether")
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        _load_root_env_into_environ()

    import psycopg2

    from app.db import get_database_url
    from app.services.fixture_marker_audit import findings_to_json, scan_connection

    dsn = get_database_url()
    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    try:
        findings = scan_connection(connection, schema=args.schema)
    finally:
        connection.close()

    if args.json_path:
        Path(args.json_path).write_text(findings_to_json(findings), encoding="utf-8")

    for finding in findings:
        print(
            f"{finding.table}.{finding.column}"
            f"{('/' + finding.path) if finding.path else ''}"
            f" [{finding.marker}] id={finding.row_id}\n    {finding.match!r}"
            f"\n    …{finding.context}…"
        )
    print(f"\n{len(findings)} fixture marker(s) in user-visible columns "
          f"of schema {args.schema!r}.")
    for key, count in Counter(
        (f.table, f.column, f.marker) for f in findings
    ).most_common():
        print(f"  {key[0]}.{key[1]} [{key[2]}]: {count}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
