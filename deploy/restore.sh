#!/usr/bin/env bash
# deploy/restore.sh — restauration d'une sauvegarde produite par deploy/backup.sh.
#
# DESTRUCTIF : remplace les bases Postgres (opsys, litellm) et les volumes de données courants.
# Confirmation explicite requise (--yes sinon invite interactive) — frontière humaine (AGENTS.md,
# suppressions/écrasements définitifs = T3).
#
# Usage : deploy/restore.sh --from DIR [--yes]
#         deploy/restore.sh --latest [--yes]
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FROM=""
ASSUME_YES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --from) FROM="$2"; shift 2 ;;
        --latest)
            FROM="$(find "${OPSYS_BACKUP_DIR:-$SCRIPT_DIR/backups}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n1)"
            shift
            ;;
        --yes) ASSUME_YES=1; shift ;;
        *) echo "argument inconnu : $1" >&2; exit 2 ;;
    esac
done

log()  { printf '[restore] %s\n' "$*"; }
warn() { printf '[restore] AVERTISSEMENT : %s\n' "$*" >&2; }
die()  { printf '[restore] ERREUR : %s\n' "$*" >&2; exit 1; }

[ -n "$FROM" ] || die "précisez --from DIR ou --latest."
[ -d "$FROM" ] || die "dossier de sauvegarde introuvable : $FROM"
[ -f "$FROM/MANIFEST.txt" ] || die "$FROM ne ressemble pas à une sauvegarde deploy/backup.sh (MANIFEST.txt absent)."
[ -f "$SCRIPT_DIR/.env" ] || die ".env introuvable."

# shellcheck disable=SC1091
set -a; . "$SCRIPT_DIR/.env"; set +a
compose() { docker compose --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"; }
PROJECT="$(basename "$SCRIPT_DIR")"

log "sauvegarde source : $FROM"
cat "$FROM/MANIFEST.txt"

if [ "$ASSUME_YES" -ne 1 ]; then
    printf '\nCeci va ÉCRASER les bases opsys/litellm et les volumes de données courants. Continuer ? [taper OUI] '
    read -r reponse
    [ "$reponse" = "OUI" ] || die "restauration annulée."
fi

log "arrêt des services applicatifs (postgres reste debout pour la restauration SQL)..."
compose stop opsys litellm openclaw-gateway caddy 2>/dev/null || true

# -- Bases Postgres -------------------------------------------------------------------------------
restore_db() {
    local db="$1" file="$FROM/postgres-${1}.sql.gz"
    [ -f "$file" ] || { warn "$file absent — base $db non restaurée."; return; }
    log "restauration de la base $db depuis $file..."
    compose exec -T postgres psql -v ON_ERROR_STOP=1 -U opsys -d postgres \
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${db}' AND pid <> pg_backend_pid();" \
        || true
    compose exec -T postgres psql -v ON_ERROR_STOP=1 -U opsys -d postgres -c "DROP DATABASE IF EXISTS ${db};"
    if [ "$db" = "litellm" ]; then
        compose exec -T postgres psql -v ON_ERROR_STOP=1 -U opsys -d postgres -c "CREATE DATABASE ${db} OWNER litellm;"
    else
        compose exec -T postgres psql -v ON_ERROR_STOP=1 -U opsys -d postgres -c "CREATE DATABASE ${db} OWNER opsys;"
    fi
    gunzip -c "$file" | compose exec -T postgres psql -v ON_ERROR_STOP=1 -U opsys -d "$db"
    log "base $db restaurée."
}
restore_db opsys
restore_db litellm

# -- Volumes ----------------------------------------------------------------------------------------
restore_volume() {
    local volume="${PROJECT}_$1" file="$FROM/volume-$1.tar.gz" mountpoint
    [ -f "$file" ] || { warn "$file absent — volume $1 non restauré."; return; }
    docker volume create "$volume" >/dev/null
    mountpoint="$(docker volume inspect -f '{{.Mountpoint}}' "$volume")"
    log "restauration du volume $1 depuis $file..."
    find "$mountpoint" -mindepth 1 -maxdepth 1 -exec rm -rf {} \;
    tar -C "$mountpoint" -xzf "$file"
    log "volume $1 restauré."
}
restore_volume opsys_data
restore_volume openclaw_config
restore_volume openclaw_auth_secrets
restore_volume litellm_config
restore_volume caddy_data

log "redémarrage des services..."
compose up -d

log "PREUVE : restauration depuis $FROM terminée. Vérifiez : docker compose -f deploy/docker-compose.yml ps"
