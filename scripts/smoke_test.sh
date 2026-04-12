#!/bin/bash
set -euo pipefail

SMOKE_COMMAND="${AGENTFORCE_SMOKE_COMMAND:-python3 -m agentforce.cli.cli}"
SMOKE_PYTHON="${AGENTFORCE_SMOKE_PYTHON:-python3}"
SMOKE_HOST="${AGENTFORCE_SMOKE_HOST:-localhost}"
SMOKE_PORT="${AGENTFORCE_SMOKE_PORT:-}"

pick_port() {
  "${SMOKE_PYTHON}" - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

assert_json() {
  local path="$1"
  local expression="$2"
  local label="$3"

  curl -sf "${BASE_URL}${path}" | "${SMOKE_PYTHON}" -c "import json, sys; data = json.load(sys.stdin); assert ${expression}, data"
  echo "✓ ${label}"
}

if [[ -z "${SMOKE_PORT}" ]]; then
  SMOKE_PORT="$(pick_port)"
fi

BASE_URL="http://${SMOKE_HOST}:${SMOKE_PORT}"

sh -c "${SMOKE_COMMAND} serve --daemon --port ${SMOKE_PORT}" &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" >/dev/null 2>&1 || true' EXIT

READY=0
for _ in $(seq 1 50); do
  if curl -sf "${BASE_URL}/api/missions" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.2
done

if [[ "${READY}" -ne 1 ]]; then
  echo "AgentForce smoke test failed: dashboard did not become ready at ${BASE_URL}" >&2
  exit 1
fi

curl -sf "${BASE_URL}/" | grep -Eiq '<!doctype html|<html|id="root"' && echo "✓ /"
assert_json "/api/missions" "isinstance(data, list)" "/api/missions"
assert_json "/api/models" "isinstance(data, list) and len(data) > 0" "/api/models"
assert_json "/api/connectors" "isinstance(data, list) and len(data) > 0" "/api/connectors"
assert_json "/api/daemon/status" "isinstance(data, dict) and data.get('running') is True" "/api/daemon/status"

kill "${SERVER_PID}"
wait "${SERVER_PID}" 2>/dev/null || true
trap - EXIT
echo "All smoke tests passed"
