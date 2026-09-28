#!/bin/sh
# deploy/entrypoint.sh — point d'entrée du conteneur "opsys".
#
# Un seul conteneur, trois responsabilités (architecture demandée par l'Orchestrateur) :
#   1. synchronisation idempotente de la config LiteLLM (`opsys passerelle config`), des agents
#      OpenClaw (`opsys passerelle cles` + `opsys openclaw configurer`) et de la consommation
#      mesurée par LiteLLM (`opsys passerelle synchroniser`, alimente budgets/alertes OPSYS) —
#      rejouée périodiquement pour absorber une configuration de modèles faite après coup dans la
#      console, sans jamais redémarrer le conteneur ;
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
LITELLM_URL="${LITELLM_URL:-http://litellm:4000}"
OPSYS_MCP_PORT="${OPSYS_MCP_PORT:-8765}"
SYNC_INTERVAL="${OPSYS_SYNC_INTERVAL_SECONDS:-300}"
SYNC_JOURS="${OPSYS_SYNC_JOURS:-1}"

mkdir -p "$OPENCLAW_CONFIG_DIR" "$LITELLM_CONFIG_DIR"

log() { echo "[opsys-init] $*"; }
warn() { echo "[opsys-init] $*" >&2; }

# -- (1a) Config LiteLLM depuis les paliers OPSYS ------------------------------------------------
# Pur calcul + écriture fichier (aucun appel réseau) : ne dépend pas de LiteLLM déjà démarré, donc
# sûr à lancer avant lui. C'est la raison d'être de l'ordre postgres -> opsys -> litellm ci-dessous
# dans docker-compose.yml : LiteLLM lit ce fichier à SON démarrage.
sync_litellm_config() {
    if opsys passerelle config --sortie "$LITELLM_CONFIG_DIR/config.yaml"; then
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

sync_openclaw() {
    if ! litellm_joignable; then
        warn "LiteLLM pas encore joignable sur $LITELLM_URL — clés et config OpenClaw reportées au prochain cycle."
        return 0
    fi
    if opsys passerelle cles --url "$LITELLM_URL"; then
        log "clés virtuelles LiteLLM synchronisées pour tous les départements."
    else
        warn "au moins une clé virtuelle LiteLLM n'a PAS pu être enregistrée (détail ci-dessus) — nouvel essai au prochain cycle."
    fi
    if opsys openclaw configurer --config-dir "$OPENCLAW_CONFIG_DIR"; then
        log "configuration des agents OpenClaw synchronisée dans $OPENCLAW_CONFIG_DIR/opsys/."
    else
        warn "configuration des agents OpenClaw NON générée — configurez les modèles dans la console OPSYS, puis le prochain cycle (${SYNC_INTERVAL}s) reprendra automatiquement."
    fi
}

# -- (1c) Consommation LiteLLM -> budgets/alertes OPSYS ------------------------------------------
# Recopie la dépense/les jetons mesurés par LiteLLM (tag = id de département) dans l'état OPSYS
# (SQLite, $OPSYS_HOME) : c'est ce qui alimente les budgets et les alertes de la console quand le
# Core est OpenClaw. Idempotent (valeurs absolues par jour/département/modèle) ; exige aussi
# LiteLLM déjà debout.
sync_usage() {
    if ! litellm_joignable; then
        warn "LiteLLM pas encore joignable sur $LITELLM_URL — synchronisation de la consommation reportée au prochain cycle."
        return 0
    fi
    if opsys passerelle synchroniser --url "$LITELLM_URL" --jours "$SYNC_JOURS"; then
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

# Premier passage synchrone, avant que le conteneur ne soit annoncé "healthy" : garantit que le
# fichier de config LiteLLM existe dès que possible pour le service `litellm` qui en dépend, et que
# le schéma de la mémoire est en place avant le premier appel d'outil.
sync_litellm_config
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
        sync_litellm_config
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
