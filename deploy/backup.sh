#!/usr/bin/env bash
# deploy/backup.sh — sauvegarde des deux bases Postgres (opsys, litellm) et des volumes de
# données (état OPSYS, config OpenClaw/agents, config LiteLLM, certificats Caddy). N'inclut PAS
# le cache Valkey (jetable, jamais une source de vérité).
#
# Usage : deploy/backup.sh [--out DIR] [--retention-days N]
# Rétention locale par défaut : 14 jours. Copie distante optionnelle si RESTIC_REPOSITORY est
# défini dans deploy/.env (voir docs/ops/EXPLOITATION.md — préférer un stockage S3-compatible
# hébergé au Canada, Loi 25).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OUT_DIR="${OPSYS_BACKUP_DIR:-$SCRIPT_DIR/backups}"
RETENTION_DAYS=14

while [ $# -gt 0 ]; do
    case "$1" in
        --out) OUT_DIR="$2"; shift 2 ;;
        --retention-days) RETENTION_DAYS="$2"; shift 2 ;;
        *) echo "argument inconnu : $1" >&2; exit 2 ;;
    esac
done

log()  { printf '[backup] %s\n' "$*"; }
warn() { printf '[backup] AVERTISSEMENT : %s\n' "$*" >&2; }
die()  { printf '[backup] ERREUR : %s\n' "$*" >&2; exit 1; }

[ -f "$SCRIPT_DIR/.env" ] || die ".env introuvable — copiez .env.example et exécutez install.sh d'abord."
# shellcheck disable=SC1091
set -a; . "$SCRIPT_DIR/.env"; set +a

compose() { docker compose --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT_DIR/$STAMP"
mkdir -p "$DEST"
log "sauvegarde $STAMP -> $DEST"

FAIL=0

# -- Bases Postgres (dump SQL clair, compressé) ----------------------------------------------------
dump_db() {
    local db="$1" file="$DEST/postgres-${1}.sql.gz"
    if compose exec -T postgres pg_dump -U opsys -d "$db" | gzip -9 > "$file"; then
        log "pg_dump $db -> $file ($(du -h "$file" | cut -f1))"
    else
        warn "pg_dump $db a échoué."
        rm -f "$file"
        FAIL=1
    fi
}
dump_db opsys
dump_db litellm

# -- Volumes de données (archives tar.gz depuis leur point de montage réel) ------------------------
archive_volume() {
    local volume="$1" file="$DEST/volume-${1}.tar.gz" mountpoint
    mountpoint="$(docker volume inspect -f '{{.Mountpoint}}' "$volume" 2>/dev/null || true)"
    if [ -z "$mountpoint" ] || [ ! -d "$mountpoint" ]; then
        warn "volume $volume introuvable — ignoré."
        return
    fi
    if tar -C "$mountpoint" -czf "$file" .; then
        log "volume $volume -> $file ($(du -h "$file" | cut -f1))"
    else
        warn "archivage du volume $volume a échoué."
        rm -f "$file"
        FAIL=1
    fi
}
# Préfixées par le nom du projet compose (dossier deploy/ par défaut : "deploy").
PROJECT="$(basename "$SCRIPT_DIR")"
archive_volume "${PROJECT}_opsys_data"
archive_volume "${PROJECT}_openclaw_config"
archive_volume "${PROJECT}_openclaw_auth_secrets"
archive_volume "${PROJECT}_litellm_config"
archive_volume "${PROJECT}_caddy_data"

echo "$STAMP" > "$DEST/MANIFEST.txt"
{
    echo "bases: opsys litellm"
    echo "volumes: opsys_data openclaw_config openclaw_auth_secrets litellm_config caddy_data"
    echo "genere_le: $(date -u -Iseconds)"
} >> "$DEST/MANIFEST.txt"

# -- Rétention locale ---------------------------------------------------------------------------
log "purge des sauvegardes locales de plus de ${RETENTION_DAYS} jours dans $OUT_DIR..."
find "$OUT_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" -print -exec rm -rf {} \; || true

# -- Copie distante optionnelle (restic) ---------------------------------------------------------
if [ -n "${RESTIC_REPOSITORY:-}" ]; then
    if command -v restic >/dev/null 2>&1; then
        log "copie restic vers ${RESTIC_REPOSITORY}..."
        export RESTIC_REPOSITORY RESTIC_PASSWORD
        if restic snapshots >/dev/null 2>&1 || restic init; then
            if restic backup "$DEST" --tag opsys --tag "$STAMP"; then
                log "restic backup OK."
                restic forget --tag opsys --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune \
                    || warn "restic forget/prune a échoué (snapshot conservé quand même)."
            else
                warn "restic backup a échoué — la copie locale reste disponible dans $DEST."
                FAIL=1
            fi
        else
            warn "impossible d'initialiser/joindre le dépôt restic — copie locale seule."
            FAIL=1
        fi
    else
        warn "RESTIC_REPOSITORY défini mais la commande 'restic' est absente — copie locale seule."
    fi
else
    log "RESTIC_REPOSITORY non défini — sauvegarde locale uniquement (voir deploy/.env.example)."
fi

if [ "$FAIL" -eq 0 ]; then
    log "PREUVE : sauvegarde $STAMP complète et sans erreur -> $DEST"
    exit 0
else
    warn "sauvegarde $STAMP terminée AVEC erreurs — voir les avertissements ci-dessus."
    exit 1
fi
