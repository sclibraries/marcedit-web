#!/usr/bin/env bash
#
# preflight-check.sh — readiness check for marcedit-web on libtools2.
#
# Run by ITS during install. Reports pass/fail for each prerequisite
# without aborting on the first failure, so the full readiness picture
# comes back in one paste.
#
# Some checks require sudo (port binding via ss -p, sudo -u marcedit
# test for write perms). Run as root or via sudo if a check shows
# "permission denied".

set +e
SUMMARY_PASS=0
SUMMARY_FAIL=0
SUMMARY_INFO=0

pass() { echo "  ✓ $*";    SUMMARY_PASS=$((SUMMARY_PASS+1)); }
fail() { echo "  ✗ $*";    SUMMARY_FAIL=$((SUMMARY_FAIL+1)); }
info() { echo "  ℹ $*";    SUMMARY_INFO=$((SUMMARY_INFO+1)); }

env_value() {
    key="$1"
    awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

check_positive_setting() {
    key="$1"
    default="$2"
    value="$(env_value "$key")"
    if [ -z "$value" ]; then
        value="$default"
    fi
    case "$value" in
        0|*[!0-9]*) fail "$key must be a positive integer" ;;
        *) pass "$key is a positive integer" ;;
    esac
}

echo "=== marcedit-web preflight check ==="
echo

echo "[Python]"
if command -v python3.9 >/dev/null; then
    pass "python3.9 found: $(python3.9 --version 2>&1)"
else
    fail "python3.9 NOT installed (expected on libtools2)"
fi
echo

echo "[Apache modules]"
if ! command -v httpd >/dev/null; then
    fail "httpd not on PATH — cannot enumerate modules"
else
    for mod in proxy proxy_http proxy_wstunnel headers rewrite ssl shib; do
        if httpd -M 2>/dev/null | grep -qw "${mod}_module"; then
            pass "${mod}_module loaded"
        else
            fail "${mod}_module NOT loaded"
        fi
    done
fi
echo

echo "[Service user]"
if id marcedit >/dev/null 2>&1; then
    pass "marcedit user exists: $(id marcedit)"
else
    fail "marcedit user NOT present (ITS: useradd --system marcedit)"
fi
echo

echo "[Port 8501 binding]"
if ! command -v ss >/dev/null; then
    info "ss not on PATH — cannot check port binding"
else
    binding="$(ss -ltn 2>/dev/null | awk '$4 ~ /:8501$/ {print $4}')"
    if [ -n "$binding" ]; then
        if [[ "$binding" == 127.0.0.1:* ]] || [[ "$binding" == "[::1]:"* ]]; then
            pass "port 8501 bound on loopback only ($binding)"
        else
            fail "port 8501 bound on $binding (expected 127.0.0.1 only)"
        fi
    else
        info "port 8501 not yet bound (expected pre-deploy)"
    fi
fi
echo

echo "[Data directory]"
DATA_DIR=/var/www/html/marcedit-web/data
if [ -d "$DATA_DIR" ]; then
    if [ "$(id -un)" = "marcedit" ]; then
        if [ -w "$DATA_DIR" ]; then pass "$DATA_DIR writable by current user (marcedit)"
        else fail "$DATA_DIR NOT writable by marcedit"
        fi
    elif sudo -nu marcedit test -w "$DATA_DIR" 2>/dev/null; then
        pass "$DATA_DIR writable by marcedit"
    else
        info "$DATA_DIR exists but writability for marcedit could not be confirmed (try re-running as marcedit or root)"
    fi
else
    info "$DATA_DIR does not exist yet (will be created by install.sh)"
fi
echo

echo "[Attestation secret]"
ENV_FILE=/var/www/html/marcedit-web/.env
if [ -f "$ENV_FILE" ]; then
    secret="$(grep -E '^MARCEDIT_WEB_PROXY_SECRET=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
    if [ -z "$secret" ] || [ "$secret" = "REPLACE_WITH_SECRET" ]; then
        fail "MARCEDIT_WEB_PROXY_SECRET unset/placeholder in $ENV_FILE — header identity refused for everyone (fail-closed); legitimate catalogers will all show as anonymous"
    else
        pass "MARCEDIT_WEB_PROXY_SECRET is set in $ENV_FILE"
    fi
else
    info "$ENV_FILE not found yet (created from .env.example during install)"
fi
echo

echo "[Durable operation worker]"
WORKER_UNIT=/etc/systemd/system/marcedit-web-worker.service
if [ -f "$WORKER_UNIT" ]; then
    pass "$WORKER_UNIT is installed"
else
    fail "$WORKER_UNIT is missing"
fi

if [ -f "$ENV_FILE" ]; then
    OPERATIONS_ROOT="$(env_value MARCEDIT_WEB_OPERATIONS_ROOT)"
else
    OPERATIONS_ROOT=""
fi
if [ -z "$OPERATIONS_ROOT" ]; then
    OPERATIONS_ROOT="$DATA_DIR/operations"
fi
OPERATIONS_ROOT_ALLOWED=1
case "$OPERATIONS_ROOT" in
    "$DATA_DIR"|"$DATA_DIR"/*) ;;
    *)
        fail "$OPERATIONS_ROOT must be within $DATA_DIR for systemd/Compose write access"
        OPERATIONS_ROOT_ALLOWED=0
        ;;
esac
if [ "$OPERATIONS_ROOT_ALLOWED" -ne 1 ]; then
    :
elif [ ! -d "$OPERATIONS_ROOT" ]; then
    fail "$OPERATIONS_ROOT is missing (run scripts/install.sh before preflight)"
elif [ "$(id -un)" = "marcedit" ]; then
    if [ -w "$OPERATIONS_ROOT" ]; then
        pass "$OPERATIONS_ROOT writable by marcedit"
    else
        fail "$OPERATIONS_ROOT NOT writable by marcedit"
    fi
elif sudo -nu marcedit test -w "$OPERATIONS_ROOT" 2>/dev/null; then
    pass "$OPERATIONS_ROOT writable by marcedit"
else
    fail "$OPERATIONS_ROOT writability for marcedit could not be confirmed"
fi

if [ -f "$ENV_FILE" ]; then
    check_positive_setting MARCEDIT_WEB_QUEUE_CHUNK_RECORDS 5000
    check_positive_setting MARCEDIT_WEB_OPERATION_RETENTION_DAYS 30
else
    info "$ENV_FILE not found; queue integer settings cannot be verified"
fi
echo

echo "[Healthcheck]"
if curl -fs http://127.0.0.1:8501/marcedit-web/_stcore/health >/dev/null 2>&1; then
    pass "http://127.0.0.1:8501/marcedit-web/_stcore/health responds"
else
    info "healthcheck endpoint not reachable (expected pre-deploy)"
fi
echo

echo "=== summary: $SUMMARY_PASS pass / $SUMMARY_FAIL fail / $SUMMARY_INFO info ==="
if [ "$SUMMARY_FAIL" -gt 0 ]; then
    exit 1
fi
