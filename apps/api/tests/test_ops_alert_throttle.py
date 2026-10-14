"""D-ALERT-2 — the operator alert email is throttled, so a crash loop cannot spend the shared Resend quota.

``scripts/ops_alert.sh`` is fired by systemd's ``OnFailure=`` once per failed start. On 2026-10-13 a unit restarting every
~6 s turned that into 215 emails in four hours and the application's own welcome email was then rejected with
``daily_quota_exceeded``. These tests run the REAL script in a sandbox (a throw-away copy of the repository layout, a fake
``curl`` on PATH that records what would have been sent, a private state directory and a controlled clock) and pin:

* the first alert for a unit is sent; repeats inside the interval are only counted;
* the next email says how many were suppressed (the "N suppressed since" line);
* units are throttled independently, the daily cap is global across units and resets with the UTC day;
* a failed send is retried only after the back-off and does not spend the daily cap;
* an unwritable state directory falls back to a private temp directory; with no state at all the alert is still sent;
* corrupt state, missing keys and invalid settings never make the script fail (exit status is always 0);
* concurrent calls cannot both send, and the API key never appears on a command line.

The three crash-looping unit files must also end a loop (``StartLimit*`` in ``[Unit]``, ``RestartSec=10``).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ops_alert.sh"
UNITS = ("aether-api", "aether-web", "aether-worker")
# 2026-10-14T10:00:00Z: far from midnight so +hours never crosses the UTC day unless a test means it to.
T0 = int(datetime(2026, 10, 14, 10, 0, 0, tzinfo=UTC).timestamp())
DAY = 86_400

# Fake curl: records the request body and whether the API key travelled in argv or in the -K config file,
# then answers with the HTTP status found in $STUB_CODE_FILE (default 200).
_CURL_STUB = r"""#!/usr/bin/env bash
payload="" cfg="" prev=""
for arg in "$@"; do
  [[ "$prev" == "-d" ]] && payload="$arg"
  [[ "$prev" == "-K" ]] && cfg="$arg"
  prev="$arg"
done
key_in_argv=0; [[ "$*" == *"$STUB_KEY"* ]] && key_in_argv=1
key_in_cfg=0;  [[ -n "$cfg" ]] && grep -q "$STUB_KEY" "$cfg" 2>/dev/null && key_in_cfg=1
code=200; [[ -r "$STUB_CODE_FILE" ]] && code="$(cat "$STUB_CODE_FILE")"
[[ -n "${STUB_SLEEP:-}" ]] && sleep "$STUB_SLEEP"
python3 - "$STUB_LOG" "$key_in_argv" "$key_in_cfg" "$code" "$payload" <<'PY'
import json, sys
log, in_argv, in_cfg, code, payload = sys.argv[1:6]
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"key_in_argv": in_argv == "1", "key_in_cfg": in_cfg == "1", "code": code,
                         "payload": json.loads(payload) if payload else None}) + "\n")
PY
printf '%s' "$code"
"""


@dataclass
class Sandbox:
    root: Path
    script: Path
    state: Path
    tmp: Path
    log: Path
    code_file: Path
    key: str
    env: dict[str, str]

    def run(self, unit: str = "aether-web.service", now: int = T0, **overrides: object) -> subprocess.CompletedProcess[str]:
        env = {**self.env, "AETHER_ALERT_NOW": str(now)}
        env.update({k: str(v) for k, v in overrides.items()})
        bash = shutil.which("bash")
        assert bash is not None
        return subprocess.run([bash, str(self.script), unit], env=env, capture_output=True, text=True, timeout=120, check=False)

    def requests(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def sent(self) -> list[dict]:
        return [r for r in self.requests() if r["code"].startswith("2")]

    def set_http_code(self, code: int) -> None:
        self.code_file.write_text(str(code), encoding="utf-8")


@pytest.fixture()
def sandbox(tmp_path: Path) -> Sandbox:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    script = repo / "scripts" / "ops_alert.sh"
    shutil.copy2(SCRIPT, script)
    key = uuid.uuid4().hex + uuid.uuid4().hex
    # runtime-generated values: nothing credential-shaped is committed
    (repo / ".env").write_text(
        f"AETHER_EMAIL_API_KEY={key}\nAETHER_EMAIL_FROM=Aether <{uuid.uuid4().hex[:8]}@sender.invalid>\n", encoding="utf-8"
    )
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "curl"
    stub.write_text(_CURL_STUB, encoding="utf-8")
    stub.chmod(0o755)
    state, tmp = tmp_path / "state", tmp_path / "tmp"
    tmp.mkdir()
    log, code_file = tmp_path / "curl.log", tmp_path / "curl.code"
    env = {
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp),
        "AETHER_ALERT_STATE_DIR": str(state),
        "STUB_LOG": str(log),
        "STUB_CODE_FILE": str(code_file),
        "STUB_KEY": key,
    }
    return Sandbox(tmp_path, script, state, tmp, log, code_file, key, env)


def _text(request: dict) -> str:
    return str(request["payload"]["text"])


def test_first_alert_is_sent_with_the_key_only_in_the_curl_config(sandbox: Sandbox) -> None:
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    sent = sandbox.sent()
    assert len(sent) == 1
    assert sent[0]["payload"]["subject"] == "[Aether ALERT] unit aether-web.service failed on prod VM"
    assert sent[0]["payload"]["to"] == ["sarkar.vikram@gmail.com"]
    assert sent[0]["key_in_cfg"] is True, "the API key must reach curl through its -K config file"
    assert sent[0]["key_in_argv"] is False, "the API key must never be on a command line"
    assert sandbox.key not in result.stdout + result.stderr
    assert (sandbox.state / "unit-aether-web.service.state").is_file()


def test_repeats_inside_the_interval_are_counted_and_the_next_email_says_so(sandbox: Sandbox) -> None:
    assert sandbox.run(now=T0).returncode == 0
    second = sandbox.run(now=T0 + 6)
    third = sandbox.run(now=T0 + 12)
    assert second.returncode == 0 and third.returncode == 0
    assert len(sandbox.sent()) == 1, "a crash loop must not send an email per failure"
    assert "1 suppressed since the last email" in second.stderr
    assert "2 suppressed since the last email" in third.stderr
    later = sandbox.run(now=T0 + 3600 + 1)
    assert later.returncode == 0
    sent = sandbox.sent()
    assert len(sent) == 2
    assert "2 further alert(s) for this unit were suppressed since the last email" in _text(sent[1])
    assert "2026-10-14T10:00:06Z" in _text(sent[1]) and "2026-10-14T10:00:12Z" in _text(sent[1])


def test_the_interval_is_exactly_the_configured_minimum(sandbox: Sandbox) -> None:
    assert sandbox.run(now=T0, AETHER_ALERT_MIN_INTERVAL_SECS=600).returncode == 0
    sandbox.run(now=T0 + 599, AETHER_ALERT_MIN_INTERVAL_SECS=600)
    assert len(sandbox.sent()) == 1
    sandbox.run(now=T0 + 600, AETHER_ALERT_MIN_INTERVAL_SECS=600)
    assert len(sandbox.sent()) == 2


def test_units_are_throttled_independently(sandbox: Sandbox) -> None:
    sandbox.run(unit="aether-api.service", now=T0)
    sandbox.run(unit="aether-web.service", now=T0 + 1)
    sandbox.run(unit="aether-api.service", now=T0 + 2)
    subjects = [r["payload"]["subject"] for r in sandbox.sent()]
    assert subjects == [
        "[Aether ALERT] unit aether-api.service failed on prod VM",
        "[Aether ALERT] unit aether-web.service failed on prod VM",
    ]


def test_daily_cap_is_global_marks_the_last_email_and_resets_with_the_utc_day(sandbox: Sandbox) -> None:
    knobs = {"AETHER_ALERT_MIN_INTERVAL_SECS": 1, "AETHER_ALERT_DAILY_CAP": 3}
    for i in range(5):
        result = sandbox.run(unit=f"aether-unit{i}.service", now=T0 + 10 * i, **knobs)
        assert result.returncode == 0
    sent = sandbox.sent()
    assert len(sent) == 3, "units are different, so only the global cap can stop the 4th and 5th"
    assert "last alert email allowed today" in _text(sent[2])
    assert "last alert email allowed today" not in _text(sent[0])
    capped = sandbox.run(unit="aether-unit9.service", now=T0 + 100, **knobs)
    assert "daily cap of 3" in capped.stderr
    next_day = sandbox.run(unit="aether-unit0.service", now=T0 + DAY, **knobs)
    assert next_day.returncode == 0
    assert len(sandbox.sent()) == 4
    assert "further alert(s)" not in _text(sandbox.sent()[3]), "unit0 was never suppressed, so no suppression line"
    unit4 = sandbox.run(unit="aether-unit4.service", now=T0 + DAY + 20, **knobs)
    assert unit4.returncode == 0
    assert "1 further alert(s) for this unit were suppressed" in _text(sandbox.sent()[4]), "cap-suppressed alerts are reported the next day"


def test_a_failed_send_backs_off_and_does_not_spend_the_daily_cap(sandbox: Sandbox) -> None:
    sandbox.set_http_code(429)
    assert sandbox.run(now=T0).returncode == 0
    assert len(sandbox.requests()) == 1 and not sandbox.sent()
    sandbox.run(now=T0 + 60)
    assert len(sandbox.requests()) == 1, "no second attempt inside the retry back-off"
    sandbox.set_http_code(200)
    sandbox.run(now=T0 + 600)
    assert len(sandbox.sent()) == 1
    assert (sandbox.state / "day-2026-10-14.count").read_text(encoding="utf-8").strip() == "1"


def test_an_unwritable_state_directory_falls_back_to_a_private_temp_directory(sandbox: Sandbox) -> None:
    blocker = sandbox.root / "not-a-directory"
    blocker.write_text("file", encoding="utf-8")
    overrides = {"AETHER_ALERT_STATE_DIR": blocker / "state"}
    assert sandbox.run(now=T0, **overrides).returncode == 0
    second = sandbox.run(now=T0 + 6, **overrides)
    assert second.returncode == 0
    assert len(sandbox.sent()) == 1, "the fallback directory must carry the throttle state"
    assert (sandbox.tmp / f"aether-alert-{os.getuid()}").is_dir()


def test_with_no_usable_state_directory_the_alert_is_still_sent(sandbox: Sandbox) -> None:
    blocker = sandbox.root / "not-a-directory"
    blocker.write_text("file", encoding="utf-8")
    # the fallback candidate is occupied by a plain file, so neither candidate can serve as state directory
    (sandbox.tmp / f"aether-alert-{os.getuid()}").write_text("squatter", encoding="utf-8")
    overrides = {"AETHER_ALERT_STATE_DIR": blocker / "state"}
    first = sandbox.run(now=T0, **overrides)
    second = sandbox.run(now=T0 + 6, **overrides)
    assert first.returncode == 0 and second.returncode == 0
    assert len(sandbox.sent()) == 2, "without state the script cannot throttle, but it must not lose the alert"
    assert "no writable state directory" in second.stderr


def test_corrupt_state_is_ignored_and_never_fails_the_unit(sandbox: Sandbox) -> None:
    sandbox.state.mkdir()
    (sandbox.state / "unit-aether-web.service.state").write_text("next_allowed=banana suppressed=-3 \x00\xff\n", encoding="utf-8", errors="replace")
    (sandbox.state / "day-2026-10-14.count").write_text("lots\n", encoding="utf-8")
    result = sandbox.run(now=T0)
    assert result.returncode == 0, result.stderr
    assert len(sandbox.sent()) == 1


def test_invalid_settings_fall_back_to_the_defaults(sandbox: Sandbox) -> None:
    bad = {"AETHER_ALERT_MIN_INTERVAL_SECS": "soon", "AETHER_ALERT_DAILY_CAP": "-1", "AETHER_ALERT_RETRY_AFTER_FAILURE_SECS": "x"}
    assert sandbox.run(now=T0, **bad).returncode == 0
    assert sandbox.run(now=T0 + 600, **bad).returncode == 0
    assert len(sandbox.sent()) == 1, "default 3600 s interval applies"


def test_missing_keys_send_nothing_and_still_exit_zero(sandbox: Sandbox) -> None:
    (sandbox.root / "repo" / ".env").write_text("UNRELATED=1\n", encoding="utf-8")
    result = sandbox.run()
    assert result.returncode == 0
    assert "not configured" in result.stderr
    assert sandbox.requests() == []


def test_concurrent_calls_send_exactly_one_email(sandbox: Sandbox) -> None:
    assert shutil.which("flock"), "util-linux flock is required for the throttle to be exact under concurrency"
    env = {**sandbox.env, "AETHER_ALERT_NOW": str(T0), "STUB_SLEEP": "1"}
    bash = shutil.which("bash")
    assert bash is not None
    procs = [
        subprocess.Popen([bash, str(sandbox.script), "aether-web.service"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(4)
    ]
    deadline = time.monotonic() + 90
    for proc in procs:
        proc.communicate(timeout=max(1, deadline - time.monotonic()))
        assert proc.returncode == 0
    assert len(sandbox.sent()) == 1


@pytest.mark.parametrize("unit", UNITS)
def test_crash_looping_units_stop_after_five_starts_in_five_minutes(unit: str) -> None:
    text = (REPO_ROOT / "deploy" / f"{unit}.service").read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
        elif line and not line.startswith("#") and current:
            sections[current].append(line)
    assert "StartLimitIntervalSec=300" in sections["Unit"], "StartLimitIntervalSec belongs in [Unit] (ignored in [Service])"
    assert "StartLimitBurst=5" in sections["Unit"]
    assert "RestartSec=10" in sections["Service"]
    assert not any(entry.startswith("StartLimit") for entry in sections["Service"])
