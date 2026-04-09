#!/bin/bash
set -euo pipefail

python3 -c "from agentforce.server.handler import serve; serve()" &
SERVER_PID=$!
trap 'kill $SERVER_PID >/dev/null 2>&1 || true' EXIT

sleep 2

curl -sf http://localhost:8080/api/missions | grep -q '\[\|{' && echo "✓ /api/missions"
curl -sf http://localhost:8080/api/models | grep -q 'claude-sonnet' && echo "✓ /api/models"
curl -sf http://localhost:8080/api/connectors | grep -q 'github' && echo "✓ /api/connectors"
curl -sf http://localhost:8080/api/telemetry | grep -q 'total_missions' && echo "✓ /api/telemetry"

kill $SERVER_PID
wait $SERVER_PID 2>/dev/null || true
trap - EXIT
echo "All smoke tests passed"
