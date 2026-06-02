#!/usr/bin/env bash
#
# deploy.sh — everyday deploy for marcedit-web on libtools2.
#
# Run as the marcedit service user (typically via
# ``sudo -iu marcedit bash scripts/deploy.sh``). This script:
#
#   1. Pulls the latest code from origin/main.
#   2. Refreshes the venv with current requirements.txt.
#   3. Asks systemd (via the NOPASSWD sudoers rule) to restart
#      the marcedit-web service.
#   4. Polls the Streamlit healthcheck for 30s and exits non-zero
#      if the service doesn't come back up.
#
# DB migration is intentionally not a step here:
# ``marcedit_web.lib.db.init_schema()`` is idempotent and runs on
# first request.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

if [ "$(id -un)" != "marcedit" ]; then
    echo "ERROR: run as the marcedit user, e.g.:"
    echo "    sudo -iu marcedit bash $0"
    exit 1
fi

if [ ! -d .venv ]; then
    echo "ERROR: .venv missing — run scripts/install.sh first."
    exit 1
fi

echo "→ Pulling latest code..."
git pull origin main

echo "→ Refreshing venv..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "→ Restarting marcedit-web..."
sudo /bin/systemctl restart marcedit-web

echo "→ Waiting for healthcheck (up to 30s)..."
for i in {1..30}; do
    if curl -fs http://127.0.0.1:8501/marcedit-web/_stcore/health >/dev/null 2>&1; then
        echo "✓ Deploy complete (healthcheck OK)."
        exit 0
    fi
    sleep 1
done

echo "✗ Healthcheck did not respond within 30s. Check 'journalctl -u marcedit-web' for details."
exit 1
