#!/usr/bin/env python3
"""Real-time runtime console log exposure for SDLC agents.

Streams the FULL runtime console output of every environment — application
stdout/stderr, uvicorn/Next.js logs, worker logs, systemd journal and guardian
reports — with no filtering or truncation, so an agent debugging a failure sees
exactly what the server saw.

  GET /                      index of streams
  GET /logs/<stream>         last N lines            (?tail=200)
  GET /logs/<stream>/follow  live stream (SSE)       (?tail=50)
  GET /health                liveness
  GET /guardian/<env>        latest guardian report (JSON)

Read-only by construction: it opens files 'rb' and shells out only to
`journalctl`. Bound to loopback; Traefik terminates TLS and authenticates.
"""
from __future__ import annotations
import json, os, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = 9400
STREAMS = {
    "prod-api":    "/var/log/aether-prod/api.log",
    "prod-web":    "/var/log/aether-prod/web.log",
    "prod-worker": "/var/log/aether-prod/worker.log",
    "dev-api":     "/var/log/aether-dev/api.log",
    "dev-web":     "/var/log/aether-dev/web.log",
    "test-api":    "/var/log/aether-test/api.log",
    "test-web":    "/var/log/aether-test/web.log",
    "guardian-prod": "/var/log/aether-guardian/prod.log",
    "guardian-dev":  "/var/log/aether-guardian/dev.log",
    "guardian-test": "/var/log/aether-guardian/test.log",
    "guardian-ci":   "/var/log/aether-guardian/ci.log",
}
JOURNAL_UNITS = {
    "journal-prod": ["aether-prod-api", "aether-prod-web", "aether-prod-worker"],
    "journal-dev":  ["aether-dev-api", "aether-dev-web"],
    "journal-test": ["aether-test-api", "aether-test-web"],
    "journal-ci":   ["actions.runner.Victordtesla24-aether-job-career-agent.hostinger-vps-srv1356245"],
}
INBOX = Path("/var/lib/aether-orchestrator")

def tail_file(path: str, n: int) -> str:
    p = Path(path)
    if not p.exists(): return f"[stream not yet created: {path}]\n"
    with p.open("rb") as f:
        f.seek(0, os.SEEK_END); end = f.tell()
        block, data, lines = 8192, b"", 0
        while end > 0 and lines <= n:
            step = min(block, end); end -= step
            f.seek(end); chunk = f.read(step)
            data = chunk + data; lines = data.count(b"\n")
        return b"\n".join(data.splitlines()[-n:]).decode("utf-8", "replace") + "\n"

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass          # do not pollute the streams we serve

    def _send(self, code, body: bytes, ctype="text/plain; charset=utf-8", stream=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        if stream:
            self.send_header("Connection", "keep-alive")
            self.end_headers()
        else:
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        n = int(q.get("tail", ["200"])[0])
        parts = [p for p in u.path.split("/") if p]

        if not parts:
            idx = {"streams": sorted(STREAMS) + sorted(JOURNAL_UNITS),
                   "manifest": "/manifest (json) | /briefing (markdown) — READ FIRST",
                   "usage": {"tail": "/logs/<stream>?tail=200",
                             "follow": "/logs/<stream>/follow  (SSE)",
                             "guardian": "/guardian/<prod|dev|test|ci>"},
                   "note": "full unfiltered runtime console output; no truncation of content"}
            return self._send(200, json.dumps(idx, indent=2).encode(), "application/json")

        if parts[0] == "manifest":
            f = Path("/etc/aether/environments.json")
            if f.exists(): return self._send(200, f.read_bytes(), "application/json")
            return self._send(503, b'{"error":"manifest not generated yet"}\n', "application/json")

        if parts[0] == "briefing":
            f = Path("/etc/aether/ENVIRONMENTS.md")
            if f.exists(): return self._send(200, f.read_bytes(), "text/markdown; charset=utf-8")
            return self._send(503, b"manifest not generated yet\n")

        if parts[0] == "health":
            return self._send(200, b'{"status":"ok"}\n', "application/json")

        if parts[0] == "guardian" and len(parts) == 2:
            f = INBOX / f"latest-{parts[1]}.json"
            if not f.exists(): return self._send(404, b'{"error":"no report yet"}\n', "application/json")
            return self._send(200, f.read_bytes(), "application/json")

        if parts[0] == "logs" and len(parts) >= 2:
            name = parts[1]
            follow = len(parts) > 2 and parts[2] == "follow"
            if name in JOURNAL_UNITS:
                cmd = ["journalctl", "-n", str(n), "--no-pager"] + sum((["-u", x] for x in JOURNAL_UNITS[name]), [])
                if follow: cmd.insert(1, "-f")
            elif name in STREAMS:
                if not follow:
                    return self._send(200, tail_file(STREAMS[name], n).encode())
                cmd = ["tail", "-n", str(n), "-F", STREAMS[name]]
            else:
                return self._send(404, b"unknown stream\n")

            if not follow:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
                return self._send(200, out.encode())

            self._send(200, b"", "text/event-stream", stream=True)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            try:
                for line in proc.stdout:
                    self.wfile.write(f"data: {line.rstrip()}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                proc.terminate()
            return
        self._send(404, b"not found\n")

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
