#!/usr/bin/env bash
# deploy/install.sh — installation « clé en main » d'OPSYS sur un VPS neuf.
#
# Idempotent : peut être relancé sans danger (ne régénère jamais un secret déjà présent dans
# .env, `docker compose up -d` ne recrée que ce qui a changé). Cible : Ubuntu 22.04/24.04 ou
# Debian 12/13, 4 vCPU / 8-16 Go RAM, sans GPU.
#
# Usage : sudo bash deploy/install.sh
#
# C'est l'option serveur (Docker Compose). Pour un poste ou un serveur sans Docker, l'installateur une commande est
# `install/install.sh` (PLAN T0.11, docs/exploitation/INSTALLATION.md) : même enchaînement de mise en route (base migrée,
# `opsys-metier openclaw configurer`, bloc `gateway`, validation, Gateway), avec le moteur lancé par le superviseur du core.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log()  { printf '[install] %s\n' "$*"; }
warn() { printf '[install] AVERTISSEMENT : %s\n' "$*" >&2; }
die()  { printf '[install] ERREUR : %s\n' "$*" >&2; exit 1; }
CORE_READY=0
INSTALL_EN_ATTENTE=0
CODE_EN_ATTENTE=3

COMPOSE_PROFILE=""
compose() {
    if [ "$COMPOSE_PROFILE" = litellm ]; then
        docker compose --profile litellm --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    elif [ "$COMPOSE_PROFILE" = database ]; then
        docker compose --profile database --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    else
        docker compose --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    fi
}

# -- Vérifications préalables ---------------------------------------------------------------------

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        die "ce script doit être lancé en root (sudo bash deploy/install.sh)."
    fi
}

check_os() {
    [ -r /etc/os-release ] || die "/etc/os-release introuvable : OS non supporté."
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}-${VERSION_ID:-}" in
        ubuntu-22.04 | ubuntu-24.04 | debian-12 | debian-13)
            log "OS supporté : ${PRETTY_NAME:-$ID $VERSION_ID}"
            ;;
        *)
            warn "OS non explicitement validé (${PRETTY_NAME:-inconnu}) — cibles testées : Ubuntu 22.04/24.04, Debian 12/13. Poursuite."
            ;;
    esac
}

check_resources() {
    cpu="$(nproc)"
    mem_kb="$(awk '/MemTotal/{print $2}' /proc/meminfo)"
    mem_gb=$((mem_kb / 1024 / 1024))
    disk_gb="$(df --output=avail -BG "$SCRIPT_DIR" | tail -n1 | tr -dc '0-9')"
    log "ressources détectées : ${cpu} vCPU, ${mem_gb} Go RAM, ${disk_gb:-?} Go disponibles ici."
    [ "$cpu" -lt 4 ] && warn "moins de 4 vCPU (${cpu}) — cible recommandée : 4 vCPU."
    [ "$mem_gb" -lt 7 ] && warn "moins de 8 Go de RAM (${mem_gb} Go) — cible recommandée : 8-16 Go."
    if [ -n "${disk_gb:-}" ] && [ "$disk_gb" -lt 20 ]; then
        warn "moins de 20 Go disponibles (${disk_gb} Go) — images et volumes ont besoin d'espace."
    fi
    if command -v lspci >/dev/null 2>&1 && lspci 2>/dev/null | grep -qi 'nvidia\|amd/ati.*vga'; then
        warn "GPU détecté — non requis ni exploité par cette installation (profil ollama reste CPU-only)."
    fi
}

# -- Docker -----------------------------------------------------------------------------------------

install_docker() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        log "Docker + Compose déjà installés ($(docker --version))."
        return
    fi
    log "installation de Docker Engine depuis le dépôt apt officiel..."
    # shellcheck disable=SC1091
    . /etc/os-release
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    arch="$(dpkg --print-architecture)"
    codename="${VERSION_CODENAME:?VERSION_CODENAME absent de /etc/os-release}"
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
        "$arch" "$ID" "$codename" > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    log "Docker installé ($(docker --version))."
}

create_deploy_user() {
    if id -u opsys-deploy >/dev/null 2>&1; then
        log "utilisateur dédié 'opsys-deploy' déjà présent."
    else
        log "création de l'utilisateur dédié 'opsys-deploy' (groupe docker, sans mot de passe direct)..."
        useradd --create-home --shell /bin/bash opsys-deploy
        usermod -aG docker opsys-deploy
        log "utilisateur créé — utilisez 'sudo -u opsys-deploy -i' ou une clé SSH dédiée pour les opérations courantes."
    fi
}

# -- Secrets (.env) -----------------------------------------------------------------------------

gen_secret() {
    # $1 = longueur finale souhaitée (alphanumérique uniquement).
    local longueur="${1:-32}"
    openssl rand -base64 $((longueur * 3)) | tr -dc 'A-Za-z0-9' | cut -c"1-${longueur}"
}

ensure_env() {
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        log "création de .env depuis .env.example..."
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    fi
    local var value
    env_value() { grep -m1 "^$1=" "$SCRIPT_DIR/.env" | cut -d= -f2- || true; }
    set_if_placeholder() {
        var="$1"; value="$2"
        if grep -qE "^${var}=" "$SCRIPT_DIR/.env"; then
            if grep -qE "^${var}=changeme" "$SCRIPT_DIR/.env" || grep -qE "^${var}=\$" "$SCRIPT_DIR/.env"; then
                sed -i "s|^${var}=.*|${var}=${value}|" "$SCRIPT_DIR/.env"
            fi
        else
            printf '%s=%s\n' "$var" "$value" >> "$SCRIPT_DIR/.env"
        fi
    }
    set_if_placeholder OPSYS_MCP_JETON "$(gen_secret 40)"
    set_if_placeholder OPSYS_CONTEXT_MCP_JETON "$(gen_secret 40)"
    set_if_placeholder OPENCLAW_GATEWAY_TOKEN "$(gen_secret 40)"
    set_if_placeholder OPSYS_MODE_FOURNISSEUR "natif"
    set_if_placeholder OPSYS_PASSERELLE_URL ""
    set_if_placeholder OPSYS_DATABASE_URL ""
    # Pas de mot de passe partagé pour la console (ADR-0009 §5) : OPSYS_CONSOLE_SECRET signe
    # seulement les sessions ; chaque personne se connecte avec son propre mot de passe, créé par
    # `opsys-metier personnes creer` (voir print_summary ci-dessous).
    set_if_placeholder OPSYS_CONSOLE_SECRET "$(gen_secret 44)"
    local mode database_url
    mode="$(env_value OPSYS_MODE_FOURNISSEUR)"
    case "$mode" in
        natif) COMPOSE_PROFILE="" ;;
        litellm)
            COMPOSE_PROFILE="litellm"
            set_if_placeholder LITELLM_MASTER_KEY "sk-$(gen_secret 40)"
            set_if_placeholder POSTGRES_OPSYS_PASSWORD "$(gen_secret 32)"
            set_if_placeholder POSTGRES_LITELLM_PASSWORD "$(gen_secret 32)"
            if [ -z "$(env_value OPSYS_PASSERELLE_URL)" ]; then
                set_if_placeholder OPSYS_PASSERELLE_URL "http://litellm:4000"
            fi
            for i in 1 2 3 4 5 6 7 8 9 10; do
                set_if_placeholder "OPSYS_CLE_M${i}" "sk-opsys-m${i}-$(gen_secret 28)"
            done
            ;;
        *) die "OPSYS_MODE_FOURNISSEUR doit valoir natif ou litellm." ;;
    esac
    database_url="$(env_value OPSYS_DATABASE_URL)"
    if [ "$COMPOSE_PROFILE" != litellm ] && [[ "$database_url" =~ ^postgres(ql)?:// ]]; then
        COMPOSE_PROFILE="database"
    fi
    chmod 600 "$SCRIPT_DIR/.env"
    log ".env prêt (chmod 600, secrets manquants générés — les autres inchangés)."
}

# -- Pare-feu et durcissement ---------------------------------------------------------------------

setup_firewall() {
    if ! command -v ufw >/dev/null 2>&1; then
        log "installation de ufw..."
        apt-get install -y ufw
    fi
    log "configuration ufw (deny in / allow 22,80,443)..."
    ufw --force default deny incoming
    ufw --force default allow outgoing
    ufw allow 22/tcp comment 'SSH'
    ufw allow 80/tcp comment 'OPSYS HTTP (redirige HTTPS)'
    ufw allow 443/tcp comment 'OPSYS HTTPS'
    ufw --force enable
}

setup_fail2ban() {
    if ! command -v fail2ban-server >/dev/null 2>&1; then
        log "installation de fail2ban..."
        apt-get install -y fail2ban
    fi
    log "installation du filtre/jail fail2ban de la console OPSYS (docs/ops/EXPLOITATION.md, § Sécurité)..."
    install -m 0644 "$SCRIPT_DIR/fail2ban/opsys-console.filter.conf" /etc/fail2ban/filter.d/opsys-console.conf
    install -m 0644 "$SCRIPT_DIR/fail2ban/opsys-console.jail.conf" /etc/fail2ban/jail.d/opsys-console.conf
    systemctl enable --now fail2ban
    systemctl reload fail2ban 2>/dev/null || true
    log "fail2ban actif : jails sshd et opsys-console (contrôle : fail2ban-client status opsys-console)."
}

# -- Démarrage par étapes (voir deploy/entrypoint.sh pour le détail de l'ordre) -------------------

wait_healthy() {
    local svc="$1" tries=0 max="${2:-60}" cid status
    while [ "$tries" -lt "$max" ]; do
        cid="$(compose ps -q "$svc" 2>/dev/null || true)"
        if [ -n "$cid" ]; then
            status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo "")"
            [ "$status" = "healthy" ] && { log "$svc en bonne santé."; return 0; }
        fi
        tries=$((tries + 1))
        sleep 5
    done
    warn "$svc n'est pas devenu 'healthy' après $((max * 5))s (voir : docker compose -f deploy/docker-compose.yml logs $svc)."
    return 1
}

start_core() {
    log "construction des images OPSYS et du fork Core local..."
    compose build opsys openclaw-gateway
    if [ "$COMPOSE_PROFILE" = litellm ]; then
        log "démarrage du profil compatibilité (PostgreSQL, Valkey, LiteLLM)..."
        compose up -d postgres valkey
        wait_healthy postgres || die "postgres n'a pas démarré correctement."
        wait_healthy valkey || die "valkey n'a pas démarré correctement."
        compose up -d opsys litellm
        wait_healthy litellm || warn "LiteLLM pas encore healthy; le gateway restera bloqué jusqu'à readiness."
    elif [ "$COMPOSE_PROFILE" = database ]; then
        log "démarrage du profil PostgreSQL demandé pour OPSYS..."
        compose up -d postgres
        wait_healthy postgres || die "postgres n'a pas démarré correctement."
        compose up -d opsys
    else
        log "démarrage natif OPSYS (SQLite, sans PostgreSQL ni LiteLLM)..."
        compose up -d opsys
    fi
    if wait_healthy opsys 12; then
        CORE_READY=1
        log "migrations, paliers, secrets et console sont prêts."
    else
        CORE_READY=0
        local readiness_rc=0
        compose exec -T opsys python3 /opt/opsys/deploy/readiness.py || readiness_rc=$?
        if [ "$readiness_rc" -eq "$CODE_EN_ATTENTE" ]; then
            INSTALL_EN_ATTENTE=1
            warn "configuration opérateur absente (paliers, embeddings ou secrets); console vérifiée par readiness, gateway suspendu. Après configuration, exécutez : docker compose -f deploy/docker-compose.yml up -d openclaw-gateway"
        else
            die "opsys n'est pas healthy (diagnostic readiness : $readiness_rc); vérifiez les logs et les services avant de relancer."
        fi
    fi
}

bootstrap_openclaw() {
    if [ "$COMPOSE_PROFILE" = litellm ]; then
        log "profil LiteLLM actif : config native compatible et clés virtuelles synchronisées par opsys."
    else
        log "mode natif : aucune passerelle externe n'est requise."
    fi

    log "validation de la racine serveur (mode local, authentification et CORS conservés)..."
    compose exec -T opsys sh -c \
        'exec opsys-metier openclaw bootstrap-serveur --config-dir "$OPENCLAW_CONFIG_DIR" --domaine "${OPSYS_DOMAINE:-localhost}"' \
        || die "bootstrap serveur refusé; préserver un snapshot et demander une récupération assistée."

    if [ "$CORE_READY" -eq 1 ]; then
        log "démarrage du gateway Core OPSYS construit depuis le fork..."
        compose up -d openclaw-gateway
        wait_healthy openclaw-gateway 40 || die "gateway pas healthy — consultez les logs du service local openclaw-gateway."
    else
        warn "gateway non lancé : readiness OPSYS est encore incomplète."
    fi
}

start_edge() {
    log "démarrage de Caddy; l'edge reste disponible même si les paliers attendent une configuration..."
    compose up -d caddy
    wait_healthy caddy || die "caddy pas 'healthy' — vérifiez : docker compose -f deploy/docker-compose.yml logs caddy."
}

print_summary() {
    local bilan="Installation OPSYS terminée."
    if [ "$INSTALL_EN_ATTENTE" -eq 1 ]; then
        bilan="Installation OPSYS en attente de configuration (code $CODE_EN_ATTENTE)."
    fi
    # shellcheck disable=SC1091
    set -a; . "$SCRIPT_DIR/.env"; set +a
    cat <<SUMMARY

============================================================================
${bilan}

  Control UI OpenClaw : https://${OPSYS_DOMAINE}/
  Console OPSYS        : https://console.${OPSYS_DOMAINE}/

  (Deux sous-domaines, deux enregistrements DNS distincts — voir INSTALLATION-VPS.md §1.)

  Secrets (deploy/.env, chmod 600) :
    - jeton Control UI    : OPENCLAW_GATEWAY_TOKEN

Prochaines étapes (docs/ops/INSTALLATION-VPS.md) :
  0. Amorçage (une seule fois, ADR-0009 §5 — la console n'a plus de mot de passe partagé) :
       docker compose -f deploy/docker-compose.yml exec opsys \\
         opsys-metier personnes creer nathan --nom "Nathan" --role nathan_owner
     (mot de passe demandé sans écho ; garder l'identifiant et le mot de passe en lieu sûr).
  1. Connectez-vous à la console OPSYS (https://console.${OPSYS_DOMAINE}/) avec cette personne et
     configurez au moins le palier de modèle "standard" (onglet Modèles), puis les départements à
     activer.
  2. Connectez-vous au Control UI OpenClaw (/) avec le jeton ci-dessus.
  3. En mode natif, configurez les fournisseurs et paliers depuis l'onglet Modèles.
     Déclarez aussi OPSYS_EMBEDDINGS_URL et OPSYS_EMBEDDINGS_MODELE pour la mémoire native;
     le backend local est opt-in, aucun modèle ni secret fournisseur n'est inventé.
     Si un palier exige une variable comme OPENAI_API_KEY, ajoutez sa valeur à deploy/.env
     (chmod 600), puis rechargez l'environnement du service :
       docker compose -f deploy/docker-compose.yml up -d --force-recreate opsys
     Quand le contrôle readiness devient healthy, démarrez le gateway :
       docker compose -f deploy/docker-compose.yml up -d openclaw-gateway
  4. Le mode LiteLLM est facultatif et doit être choisi explicitement dans OPSYS_MODE_FOURNISSEUR.
     Il utilise le profil \`litellm\` et les clés OPSYS_CLE_M1..M10.
  5. Si OPSYS_DOMAINE=localhost, le certificat est auto-signé (validation locale
     uniquement) : fixez un vrai domaine DNS avant tout accès distant réel.
============================================================================
SUMMARY
}

main() {
    require_root
    check_os
    check_resources
    install_docker
    create_deploy_user
    ensure_env
    setup_firewall
    setup_fail2ban
    start_core
    bootstrap_openclaw
    start_edge
    print_summary
    if [ "$INSTALL_EN_ATTENTE" -eq 1 ]; then
        exit "$CODE_EN_ATTENTE"
    fi
}

main "$@"
