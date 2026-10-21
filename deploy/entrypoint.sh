#!/bin/sh
# deploy/entrypoint.sh — point d'entrée du conteneur "opsys".
#
# Native provider configuration is the default. LiteLLM key/config/usage synchronization runs only
# after an explicit `OPSYS_MODE_FOURNISSEUR=litellm` choice.
#   1. regenerates model/provider configuration after operator changes in the console;
#   2. le serveur MCP OPSYS en HTTP streamable (`opsys-mcp --http`) ;
#   3. la console OPSYS (`opsys-console`).
#
# Fail-soft sur (1) : un cycle de synchronisation qui échoue (paliers non configurés, LiteLLM pas
# encore joignable) est journalisé clairement et réessayé au cycle suivant — jamais fatal. Le
# détail exact de ce qu'il faut valider sur un vrai VPS (impossible à exécuter depuis ce bac à
# sable) est documenté dans docs/ops/EXPLOITATION.md.
# Fail-fast sur (2)/(3) : si le serveur MCP ou la console meurent, le conteneur s'arrête pour
# laisser `restart: unless-stopped` le relancer proprement.
set -eu

OPENCLAW_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-/openclaw-config}"
LITELLM_CONFIG_DIR="${LITELLM_CONFIG_DIR:-/shared/litellm-config}"
MODE="${OPSYS_MODE_FOURNISSEUR:-natif}"
OPSYS_PASSERELLE_URL="${OPSYS_PASSERELLE_URL:-}"
OPSYS_MCP_PORT="${OPSYS_MCP_PORT:-8765}"
# Cette topologie lance elle-même le serveur opsys ci-dessous : accord exact, pas détection d’hôte.
MCP_ORIGIN="http://opsys:${OPSYS_MCP_PORT}"
if [ "$OPSYS_MCP_PORT" = 80 ]; then MCP_ORIGIN="http://opsys"; fi
SYNC_INTERVAL="${OPSYS_SYNC_INTERVAL_SECONDS:-300}"
SYNC_JOURS="${OPSYS_SYNC_JOURS:-1}"

case "$MODE" in
    natif) ;;
    litellm)
        case "$OPSYS_PASSERELLE_URL" in http://*|https://*) ;; *) echo "[opsys-init] URL explicite requise en mode litellm." >&2; exit 2 ;; esac
        LITELLM_URL="$OPSYS_PASSERELLE_URL"
        ;;
    *) echo "[opsys-init] OPSYS_MODE_FOURNISSEUR invalide : $MODE" >&2; exit 2 ;;
esac

# Lecture seule avant toute création/bootstrap/migration. Les volumes existants ne changent
# jamais de propriétaire en silence ; une archive UID10100 exige une reprise assistée.
if ! python3 "$(dirname "$0")/permissions.py"; then
    echo "[opsys-init] permissions serveur refusées; snapshot et reprise assistée des volumes requis." >&2
    exit 2
fi

log() { echo "[opsys-init] $*"; }
warn() { echo "[opsys-init] $*" >&2; }

# -- Configuration facultative de LiteLLM ------------------------------------------------------
sync_litellm_config() {
    if opsys-metier passerelle config --sortie "$LITELLM_CONFIG_DIR/config.yaml"; then
        log "config LiteLLM régénérée : $LITELLM_CONFIG_DIR/config.yaml"
    else
        warn "config LiteLLM NON régénérée — configurez au moins le palier 'standard' dans la console OPSYS (port ${OPSYS_CONSOLE_PORT:-8700}${OPSYS_CONSOLE_PREFIXE:-}), puis le prochain cycle (${SYNC_INTERVAL}s) reprendra automatiquement."
    fi
}

# -- (1b) Clés virtuelles par département + config des agents OpenClaw --------------------------
# Ces deux étapes appellent l'API d'administration de LiteLLM (HTTP réel) : elles exigent LiteLLM
# déjà debout. On vérifie d'abord qu'il répond, sans jamais bloquer le démarrage des deux process
# longue durée plus bas.
litellm_joignable() {
    python3 - "$LITELLM_URL" <<'PY'
import sys
import urllib.request

base = sys.argv[1]
for chemin in ("/health/liveliness", "/"):
    try:
        urllib.request.urlopen(base + chemin, timeout=3)
        sys.exit(0)
    except urllib.error.HTTPError:
        sys.exit(0)  # une réponse HTTP (même 4xx) prouve que le process écoute
    except Exception:
        continue
sys.exit(1)
PY
}

bootstrap_serveur() {
    opsys-metier openclaw bootstrap-serveur --config-dir "$OPENCLAW_CONFIG_DIR" \
        --domaine "${OPSYS_DOMAINE:-localhost}"
}

sync_openclaw() {
    if ! bootstrap_serveur; then
        warn "racine serveur incompatible; aucun fragment régénéré. Reprise assistée requise."
        return 1
    fi
    if [ "$MODE" = litellm ]; then
        if litellm_joignable; then
            if opsys-metier passerelle cles --url "$LITELLM_URL"; then
                log "clés virtuelles LiteLLM synchronisées pour tous les départements."
            else
                warn "au moins une clé virtuelle LiteLLM n'a PAS pu être enregistrée (nouvel essai au prochain cycle)."
            fi
        else
            warn "LiteLLM pas encore joignable sur $LITELLM_URL — clés reportées au prochain cycle."
        fi
    fi
    if [ "$MODE" = litellm ]; then
        if opsys-metier openclaw configurer --config-dir "$OPENCLAW_CONFIG_DIR" --mode-fournisseur litellm \
            --url-mcp "${MCP_ORIGIN}/mcp" --autoriser-origine-http-mcp "$MCP_ORIGIN" \
            --url-passerelle "$LITELLM_URL"; then
            log "configuration LiteLLM d'OpenClaw synchronisée dans $OPENCLAW_CONFIG_DIR/opsys/."
        else
            warn "configuration d'OpenClaw non générée; vérifiez les paliers dans la console."
        fi
    else
        if opsys-metier openclaw configurer --config-dir "$OPENCLAW_CONFIG_DIR" --mode-fournisseur natif \
            --url-mcp "${MCP_ORIGIN}/mcp" --autoriser-origine-http-mcp "$MCP_ORIGIN"; then
            log "configuration native d'OpenClaw synchronisée dans $OPENCLAW_CONFIG_DIR/opsys/."
        else
            warn "configuration native non générée — configurez les paliers dans la console, puis nouvelle tentative dans ${SYNC_INTERVAL}s."
        fi
    fi
}

# -- (1c) Consommation LiteLLM -> budgets/alertes OPSYS ------------------------------------------
# Recopie la dépense/les jetons mesurés par LiteLLM (tag = id de département) dans l'état OPSYS
# (SQLite, $OPSYS_HOME) : c'est ce qui alimente les budgets et les alertes de la console quand le
# Core est OpenClaw. Idempotent (valeurs absolues par jour/département/modèle) ; exige aussi
# LiteLLM déjà debout.
sync_usage() {
    [ "$MODE" = litellm ] || return 0
    if ! litellm_joignable; then
        warn "LiteLLM pas encore joignable sur $LITELLM_URL — synchronisation de la consommation reportée au prochain cycle."
        return 0
    fi
    if opsys-metier passerelle synchroniser --url "$LITELLM_URL" --jours "$SYNC_JOURS"; then
        log "consommation LiteLLM synchronisée vers les budgets OPSYS."
    else
        warn "synchronisation de la consommation LiteLLM incomplète — nouvel essai au prochain cycle."
    fi
}

# -- (1d) Mémoire d'entreprise (PostgreSQL + pgvector, docs/memory/RAG-PREMIUM.md) ---------------
# `migrer` applique le schéma idempotent sous verrou consultatif ; `purger` efface les fragments
# échus (Loi 25, art. 23) ; `completer` vectorise les fragments restés en plein texte après une
# panne du service d'embeddings. Fail-soft : une mémoire indisponible n'empêche ni le MCP ni la
# console de démarrer, ses outils répondent alors une erreur explicite à l'agent.
PURGE_INTERVAL="${OPSYS_PURGE_INTERVAL_SECONDS:-86400}"

memoire_migrer() {
    if python3 -m opsys.memoire migrer; then
        log "schéma de la mémoire d'entreprise appliqué."
    else
        warn "migration de la mémoire d'entreprise en échec (détail ci-dessus) — nouvel essai dans ${SYNC_INTERVAL}s."
        return 1
    fi
}

memoire_entretien() {
    if python3 -m opsys.memoire purger; then
        log "purge des fragments échus effectuée (rétention Loi 25)."
    else
        warn "purge de la mémoire en échec — nouvel essai dans ${PURGE_INTERVAL}s."
    fi
    if [ -n "${OPSYS_EMBEDDINGS_URL:-}" ]; then
        if python3 -m opsys.memoire completer; then
            log "rattrapage des embeddings effectué."
        else
            warn "rattrapage des embeddings en échec — nouvel essai dans ${PURGE_INTERVAL}s."
        fi
    fi
}

# Refus d'une racine distante/ancienne/incohérente avant migration ou génération.
if ! bootstrap_serveur; then
    warn "bootstrap serveur refusé; arrêt sans réparation de la racine existante."
    exit 2
fi

# Migre la base choisie avant d'ouvrir MCP/console. Par défaut c'est SQLite dans le volume opsys_data;
# OPSYS_DATABASE_URL permet explicitement d'utiliser PostgreSQL.
if ! opsys-metier base migrer; then
    warn "migration du stockage OPSYS impossible; arrêt pour éviter de servir un état partiel."
    exit 1
fi
if [ "$MODE" = litellm ]; then sync_litellm_config; fi
sync_openclaw
sync_usage

memoire_loop_pid=""
if [ -n "${OPSYS_DATABASE_URL:-}" ]; then
    memoire_migrer && memoire_prete=1 || memoire_prete=0
    (
        if [ "$memoire_prete" = 0 ]; then
            until { sleep "$SYNC_INTERVAL"; memoire_migrer; }; do :; done
        fi
        while true; do
            memoire_entretien
            sleep "$PURGE_INTERVAL"
        done
    ) &
    memoire_loop_pid=$!
else
    warn "OPSYS_DATABASE_URL absente — mémoire d'entreprise désactivée (outils opsys_memoire_* en erreur explicite)."
fi

# Rejeux périodiques en arrière-plan — idempotents, chaque passage régénère la même sortie.
(
    while true; do
        sleep "$SYNC_INTERVAL"
        if [ "$MODE" = litellm ]; then sync_litellm_config; fi
        sync_openclaw
        sync_usage
    done
) &
sync_loop_pid=$!

# -- (2) et (3) : les deux process longue durée du conteneur -------------------------------------
opsys-mcp --http --hote 0.0.0.0 --port "$OPSYS_MCP_PORT" &
mcp_pid=$!

opsys-console &
console_pid=$!

term() {
    kill -TERM "$sync_loop_pid" ${memoire_loop_pid:+"$memoire_loop_pid"} "$mcp_pid" "$console_pid" 2>/dev/null || true
}
trap term TERM INT

# Le conteneur vit tant que le MCP ET la console vivent tous les deux ; le premier des deux à
# mourir fait sortir le conteneur (`restart: unless-stopped` le relance).
while kill -0 "$mcp_pid" 2>/dev/null && kill -0 "$console_pid" 2>/dev/null; do
    sleep 1
done

warn "un processus longue durée s'est arrêté — arrêt du conteneur pour relance par restart:unless-stopped."
term
wait
exit 1
