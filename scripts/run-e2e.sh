#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
E2E_DIR="${REPO_ROOT}/tests/e2e"
K6_SCRIPT="${E2E_DIR}/k6/brand_smoke.js"
BRAND_SERVER="${REPO_ROOT}/Modules M/M7-marketing/src/brand/brand_server.py"
E2E_REQUIREMENTS_LOCK="${E2E_DIR}/requirements.lock"

# Aucun interpréteur système implicite : l'appelant (CI ou développeur) doit
# déclarer le Python dont l'environnement contient les dépendances verrouillées.
PYTHON_BIN="${PYTHON_BIN:-}"

# Variables partagées avec le trap EXIT/INT/TERM.
# Elles NE PEUVENT PAS être 'local' dans une fonction car le trap s'exécute
# après le retour de cette fonction (shell exit), ce qui provoquerait une
# erreur "unbound variable" sous 'set -u'.
SERVER_PID=""
SERVER_LOG=""

# ----------------------------------------------------------------------
# Nettoyage du serveur (idempotent, robuste sous set -u)
# ----------------------------------------------------------------------
arreter_serveur() {
  # Si aucun serveur n'a été lancé, rien à faire.
  if [ -z "${SERVER_PID:-}" ]; then
    return 0
  fi

  # Tenter un kill doux puis attendre jusqu'à ~5s.
  if kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    local waited=0
    while kill -0 "${SERVER_PID}" 2>/dev/null && (( waited < 50 )); do
      sleep 0.1
      waited=$((waited + 1))
    done
    # Si toujours vivant, forcer.
    kill -9 "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  SERVER_PID=""

  # Nettoyer le fichier temporaire de log.
  if [ -n "${SERVER_LOG:-}" ]; then
    rm -f "${SERVER_LOG}"
    SERVER_LOG=""
  fi
}

# Poser les pièges une fois pour toutes, avant toute exécution.
#
# EXIT ne fait que nettoyer : le script sort de lui-même, il n'y a rien à
# interrompre.
#
# INT et TERM doivent NETTOYER *PUIS SORTIR*. Un handler qui se contente de
# nettoyer laisse le script REPRENDRE là où il en était : mesuré, une
# interruption pendant la boucle d'attente du serveur tuait bien le serveur,
# puis la boucle continuait à le sonder jusqu'à son échéance de 30 s avant de
# rendre la main. Le signal était donc absorbé au lieu d'être honoré, et le
# script mettait 30 s à mourir de façon intermittente. Les codes 130 et 143
# sont les conventions POSIX (128 + numéro du signal).
trap arreter_serveur EXIT
trap 'arreter_serveur; exit 130' INT
trap 'arreter_serveur; exit 143' TERM

# ----------------------------------------------------------------------
# Fonctions utilitaires
# ----------------------------------------------------------------------
verifier_interpreteur() {
  if [ -z "${PYTHON_BIN}" ]; then
    echo "ERREUR: PYTHON_BIN est obligatoire (Python de l'environnement E2E préparé)." >&2
    echo "Exemple: PYTHON_BIN=.venv/bin/python bash scripts/run-e2e.sh e2e" >&2
    return 1
  fi
  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "ERREUR: interpréteur PYTHON_BIN introuvable: ${PYTHON_BIN}" >&2
    return 1
  fi
}

verifier_dependances_e2e() {
  local imports="$1"
  if ! "${PYTHON_BIN}" -c "import ${imports}" >/dev/null 2>&1; then
    echo "ERREUR: l'environnement ${PYTHON_BIN} ne contient pas les dépendances E2E (${imports})." >&2
    echo "Installez-les avec: ${PYTHON_BIN} -m pip install --require-hashes -r ${E2E_REQUIREMENTS_LOCK}" >&2
    return 1
  fi
}

run_python_e2e() {
  verifier_dependances_e2e "pytest, yaml" || return 1
  "${PYTHON_BIN}" -m pytest "${E2E_DIR}" -q
}

run_k6() {
  if ! command -v k6 >/dev/null 2>&1; then
    echo "SKIP: k6 absent"
    return 0
  fi
  verifier_dependances_e2e "yaml" || return 1

  local PORT BASE_URL
  PORT="$("${PYTHON_BIN}" - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
  BASE_URL="http://127.0.0.1:${PORT}"
  SERVER_LOG="$(mktemp)"

  "${PYTHON_BIN}" "${BRAND_SERVER}" "${PORT}" >"${SERVER_LOG}" 2>&1 </dev/null &
  SERVER_PID=$!

  local deadline
  deadline=$((SECONDS + 30))
  while true; do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS -m 5 --max-time 5 "${BASE_URL}/brand" >/dev/null 2>&1; then
        break
      fi
    else
      if "${PYTHON_BIN}" - <<PY >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("${BASE_URL}/brand", timeout=5)
PY
      then
        break
      fi
    fi
    if (( SECONDS >= deadline )); then
      echo "ERREUR: serveur non prêt après 30s" >&2
      echo "--- Contenu de ${SERVER_LOG} ---" >&2
      cat "${SERVER_LOG}" >&2
      arreter_serveur
      return 20
    fi
    sleep 0.1
  done

  export BASE_URL
  if ! k6 run "${K6_SCRIPT}"; then
    echo "--- Contenu de ${SERVER_LOG} ---" >&2
    cat "${SERVER_LOG}" >&2
    arreter_serveur
    return 20
  fi

  arreter_serveur
  return 0
}

main() {
  local mode
  mode="${1:-}"

  if ! verifier_interpreteur; then
    exit 10
  fi

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
