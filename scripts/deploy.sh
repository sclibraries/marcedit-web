#!/usr/bin/env bash
#
# deploy.sh — lineage-driven hotfix deploy for the existing marcedit service.
#
# Gate 0 is deliberately explicit. Capture the production runtime first, then
# provide that JSON plus the approved release branch and backup destination:
#
#   .venv/bin/python scripts/capture_task_194_runtime_lineage.py --output /tmp/lineage.json
#   bash scripts/deploy.sh --lineage /tmp/lineage.json \
#       --branch release-hotfix --release-sha APPROVED_SHA \
#       --backup-dir /var/backups/marcedit-web/DATE
#
# The branch must already be checked out at the captured SHA before the pull.
# The approved release SHA is checked immediately after the pull, before any
# dependency, database, or service action.
#
# Add --dry-run to print the exact commands without changing code, dependencies,
# the database, or the service. The Python entry point refuses incomplete or
# ambiguous lineage and supplies the captured unit name to systemctl; this
# wrapper never guesses a production unit or starts a worker.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$SCRIPT_DIR"

if [ "$(id -un)" != "marcedit" ]; then
    echo "ERROR: run as the marcedit user, e.g.:"
    echo "    sudo -iu marcedit bash $0 --lineage FILE --branch BRANCH --release-sha SHA --backup-dir DIR"
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "ERROR: .venv/bin/python missing — run scripts/install.sh first."
    exit 1
fi

if [ "$#" -eq 0 ]; then
    echo "ERROR: --lineage, --branch, --release-sha, and --backup-dir are required."
    echo "Run with --dry-run first to inspect the lineage-driven commands."
    exit 2
fi

exec .venv/bin/python -m marcedit_web.ops.deploy --root "$SCRIPT_DIR" "$@"
