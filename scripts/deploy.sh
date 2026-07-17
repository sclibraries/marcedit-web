#!/usr/bin/env bash
#
# deploy.sh — everyday deploy for marcedit-web on libtools2.
#
# Run as the marcedit service user (typically via
# ``sudo -iu marcedit bash scripts/deploy.sh``). This script:
#
#   1. Stops the durable worker so old code cannot write during migration.
#   2. Pulls code and refreshes the venv.
#   3. Restarts the private app and verifies HTTP plus database readiness.
#   4. Starts the worker and requires a fresh database heartbeat.

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

deployment_failed() {
    status=$?
    trap - ERR
    sudo /bin/systemctl stop marcedit-web-worker >/dev/null 2>&1 || true
    echo "✗ Deploy failed; the queue worker has been left stopped so queued work remains recoverable."
    echo "  Inspect both units: journalctl -u marcedit-web-private -u marcedit-web-worker"
    exit "$status"
}
trap deployment_failed ERR

echo "→ Stopping durable operation worker..."
sudo /bin/systemctl stop marcedit-web-worker

echo "→ Waiting for the previous worker heartbeat to expire..."
previous_heartbeat_stale=0
for i in {1..20}; do
    if ! .venv/bin/python -m marcedit_web.ops.worker --check >/dev/null 2>&1; then
        previous_heartbeat_stale=1
        break
    fi
    sleep 1
done
if [ "$previous_heartbeat_stale" -ne 1 ]; then
    echo "✗ Previous worker heartbeat remained fresh after the service stopped."
    false
fi

echo "→ Pulling latest code..."
git pull origin main

echo "→ Refreshing venv..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "→ Restarting private application..."
sudo /bin/systemctl restart marcedit-web-private

echo "→ Waiting for application healthcheck (up to 30s)..."
app_ready=0
for i in {1..30}; do
    if curl -fs http://127.0.0.1:8501/marcedit-web/_stcore/health >/dev/null 2>&1; then
        app_ready=1
        break
    fi
    sleep 1
done
if [ "$app_ready" -ne 1 ]; then
    echo "✗ Private application healthcheck did not respond within 30s."
    false
fi

echo "→ Verifying database schema and write readiness..."
.venv/bin/python -m marcedit_web.ops.health

echo "→ Starting durable operation worker..."
sudo /bin/systemctl start marcedit-web-worker

echo "→ Waiting for a fresh worker heartbeat (up to 30s)..."
worker_ready=0
for i in {1..30}; do
    if .venv/bin/python -m marcedit_web.ops.worker --check >/dev/null 2>&1; then
        worker_ready=1
        break
    fi
    sleep 1
done
if [ "$worker_ready" -ne 1 ]; then
    echo "✗ Durable operation worker did not publish a fresh heartbeat within 30s."
    false
fi

trap - ERR
echo "✓ Deploy complete (application ready; worker heartbeat fresh)."
