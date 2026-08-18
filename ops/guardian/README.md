# Environment operations

These files run the VPS environments and were previously host-only, which meant
the rollback and maintenance logic could not be reviewed, diffed or tested by
anyone. They are now version-controlled here and deployed to `/opt/aether-guardian`
by `install.sh`.

| file | role |
|---|---|
| `guardian.py` | per-environment autonomous guardian (health, hygiene, git, integrity, branches) |
| `deploy_env.sh` | deploy one environment from a pinned commit, smoke-test, roll back on failure |
| `manifest.py` | regenerate `/etc/aether/ENVIRONMENTS.md` + `environments.json` from live state |
| `logstream.py` | real-time runtime console log service for SDLC agents (127.0.0.1:9400) |
| `install.sh` | copy to `/opt`, reload systemd |
