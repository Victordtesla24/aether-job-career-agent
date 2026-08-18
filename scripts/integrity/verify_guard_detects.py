#!/usr/bin/env python3
"""Regression proof: the integrity guard must FLAG a known-bad corpus.

A guard that passes a clean tree proves nothing on its own — it may simply be
blind. This stages the negative corpus into a scratch repo, runs the real guard
against it, and fails if the guard does not report a violation for each case.
Run in CI alongside the guard itself.
"""
import shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "scripts/integrity/negative_corpus"
GUARD = ROOT / "scripts/integrity/integrity_guard.py"

# case file -> the rule that must fire
CASES = {"violations.py": "R1", "skips.spec.ts": "R7",
         "bad.env.fixture": "R3", "bad-workflow.yml.fixture": "R7"}

def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="guard-negative-"))
    (tmp / "scripts/integrity").mkdir(parents=True)
    (tmp / "apps/api/app").mkdir(parents=True)
    (tmp / "apps/web/src").mkdir(parents=True)
    (tmp / ".github/workflows").mkdir(parents=True)
    shutil.copy(GUARD, tmp / "scripts/integrity/integrity_guard.py")
    (tmp / "scripts/integrity/waivers.txt").write_text("")
    shutil.copy(CORPUS / "violations.py", tmp / "apps/api/app/violations.py")
    shutil.copy(CORPUS / "skips.spec.ts", tmp / "apps/web/src/skips.spec_notest.ts")
    shutil.copy(CORPUS / "bad.env.fixture", tmp / ".env")
    shutil.copy(CORPUS / "bad-workflow.yml.fixture", tmp / ".github/workflows/bad.yml")

    r = subprocess.run([sys.executable, str(tmp / "scripts/integrity/integrity_guard.py")],
                       capture_output=True, text=True, cwd=tmp)
    out = r.stdout
    missing = [rule for rule in sorted(set(CASES.values())) if f"\n{rule}:" not in out]
    print(out)
    if r.returncode == 0:
        print("REGRESSION: the guard PASSED a corpus of deliberate violations — it is blind.")
        return 1
    if missing:
        print(f"REGRESSION: the guard did not fire these rules on the corpus: {missing}")
        return 1
    print(f"OK — guard detected every corpus rule ({sorted(set(CASES.values()))}) and exited {r.returncode}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
