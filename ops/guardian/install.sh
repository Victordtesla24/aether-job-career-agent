#!/usr/bin/env bash
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
install -m 0755 "$D/guardian.py"   /opt/aether-guardian/guardian.py
install -m 0755 "$D/deploy_env.sh" /opt/aether-guardian/deploy_env.sh
install -m 0755 "$D/manifest.py"   /opt/aether-guardian/manifest.py
install -m 0755 "$D/logstream.py"  /opt/aether-logstream/logstream.py
systemctl daemon-reload
systemctl restart aether-logstream
echo "ops installed from $D"
