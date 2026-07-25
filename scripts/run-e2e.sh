#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
E2E_DIR="${REPO_ROOT}/tests/e2e"
K6_SCRIPT="${E2E_DIR}/k6/brand_smoke.js"
BRAND_SERVER="${REPO_ROOT}/Modules M/M7-marketing/src/brand/brand_server.py"

run_python_e2e() {
  python3 -m pytest "${E2E_DIR}" -q
}

run_k6() {
  if ! command -v k6 >/dev/null 2>&1; then
    echo "SKIP: k6 absent"
    return 0
  fi

  local PORT BASE_URL SERVER_PID SERVER_LOG
  PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
  BASE_URL="http://127.0.0.1:${PORT}"
  SERVER_LOG="$(mktemp)"

  python3 "${BRAND_SERVER}" "${PORT}" >"${SERVER_LOG}" 2>&1 </dev/null &
  SERVER_PID=$!

  cleanup() {
    if kill -0 "${SERVER_PID}" 2>/dev/null; then
      kill "${SERVER_PID}" 2>/dev/null || true
      local waited=0
      while kill -0 "${SERVER_PID}" 2>/dev/null && (( waited < 50 )); do
        sleep 0.1
        waited=$((waited + 1))
      done
      kill -9 "${SERVER_PID}" 2>/dev/null || true
      wait "${SERVER_PID}" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT INT TERM

  local deadline
  deadline=$((SECONDS + 30))
  while true; do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS -m 5 --max-time 5 "${BASE_URL}/brand" >/dev/null 2>&1; then
        break
      fi
    else
      if python3 - <<PY >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("${BASE_URL}/brand", timeout=5)
PY
      then
        break
      fi
    fi
    if (( SECONDS >= deadline )); then
      echo "ERREUR: serveur non prêt après 30s" >&2
      return 20
    fi
    sleep 0.1
  done

  export BASE_URL
  if ! k6 run "${K6_SCRIPT}"; then
    return 20
  fi
  return 0
}

main() {
  local mode
  mode="${1:-}"

  case "${mode}" in
    e2e)
      if ! run_python_e2e; then
        exit 10
      fi
      ;;
    load)
      if ! run_k6; then
        exit 20
      fi
      ;;
    "")
      if ! run_python_e2e; then
        exit 10
      fi
      if ! run_k6; then
        exit 20
      fi
      ;;
    *)
      echo "Usage: $0 [e2e|load]" >&2
      exit 1
      ;;
  esac
}

main "$@"
