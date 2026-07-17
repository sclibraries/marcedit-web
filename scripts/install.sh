#!/usr/bin/env bash
#
# install.sh — one-time per-host setup for marcedit-web.
#
# Run as the marcedit service user, AFTER ITS has done the four
# root operations (see docs/its-setup.md):
#
#   1. Created the marcedit system user.
#   2. Dropped /etc/sudoers.d/marcedit.
#   3. Dropped the private app and worker units in /etc/systemd/system/.
#   4. Added the Apache <Location> block to the libtools2 vhost.
#
# This script is idempotent — safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

if [ "$(id -un)" != "marcedit" ]; then
    echo "ERROR: run as the marcedit user, e.g.:"
    echo "    sudo -iu marcedit bash $0"
    exit 1
fi

if ! command -v python3.9 >/dev/null; then
    echo "ERROR: python3.9 not found on PATH. ITS should have already installed it."
    exit 1
fi

if [ ! -d .venv ]; then
    echo "→ Creating venv with $(python3.9 --version)..."
    python3.9 -m venv .venv
else
    echo "✓ .venv already exists."
fi

echo "→ Installing dependencies..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "→ Ensuring data directories exist..."
mkdir -p data/audit data/tasks data/uploads data/operations

if [ ! -f .env ]; then
    echo "ℹ No .env found. Copy .env.example to .env and fill in production values:"
    echo "    cp .env.example .env && vi .env"
fi

if [ ! -f .streamlit/secrets.toml ]; then
    echo "ℹ No .streamlit/secrets.toml found. Copy the template if you want Google OAuth:"
    echo "    cp .streamlit/secrets.toml.example .streamlit/secrets.toml && vi .streamlit/secrets.toml"
fi

echo
echo "✓ Install complete."
echo
echo "To install and start the services (one-time, requires root):"
echo "    sudo install -m 0644 deploy/marcedit-web-private.service /etc/systemd/system/"
echo "    sudo install -m 0644 deploy/marcedit-web-worker.service /etc/systemd/system/"
echo "    sudo /bin/systemctl daemon-reload"
echo "    sudo /bin/systemctl enable --now marcedit-web-private"
echo "    sudo /bin/systemctl enable --now marcedit-web-worker"
echo
echo "Then verify with:"
echo "    sudo /bin/systemctl status marcedit-web-private marcedit-web-worker"
echo "    curl -fs http://127.0.0.1:8501/marcedit-web/_stcore/health"
echo "    .venv/bin/python -m marcedit_web.ops.worker --check"
