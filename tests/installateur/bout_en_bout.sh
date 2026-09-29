#!/usr/bin/env bash
# tests/installateur/bout_en_bout.sh : preuve de l'installateur avec le VRAI core (PLAN T0.11), pour la CI.
#
# `tests/test_installateur_scripts.py` joue install.sh contre de fausses commandes ; ici tout est vrai : le core
# est construit, le moteur est installé par uv, la configuration passe `openclaw config validate`, le Gateway
# démarre et lance le moteur, le service utilisateur (systemd --user) tourne, l'export est cohérent, et la
# désinstallation retire le logiciel sans perdre une donnée. Chaque constat faux arrête le script, avec quoi
# regarder. Aucune étape ne tolère l'échec, sauf l'absence de systemd --user sur le poste, signalée en clair.
#
# Le core tourne sous son profil « opsys » (PLAN T0.11-b). Ses attentes sont écrites ICI, en dur, d'après le code du
# fork, et confrontées à ce que le vrai core et le moteur Python répondent :
#   - dossier d'état : ~/.openclaw-opsys (core/src/cli/profile-utils.ts, resolveProfileStateDir) ;
#   - service systemd utilisateur : openclaw-gateway-opsys.service (core/src/daemon/constants.ts), distinct de
#     openclaw-gateway.service, celui du core d'origine.
# Ce script INSTALLE puis DÉSINSTALLE : il refuse de tourner sur un poste qui a déjà un état du core d'OPSYS ou son
# service (ne l'exécutez pas sur un poste réel ; la CI l'exécute sur une machine neuve).
#
# Usage (depuis la racine du dépôt, Node 24+, Python 3.11+, uv) : bash tests/installateur/bout_en_bout.sh
# Variables : OPSYS_TRAVAIL (dossier de travail, défaut : un dossier temporaire), OPSYS_SANS_SERVICE=1 (saute la
# phase du service).
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
TRAVAIL="${OPSYS_TRAVAIL:-$(mktemp -d)}"
mkdir -p "$TRAVAIL"

export OPSYS_HOME="$TRAVAIL/instance"
export OPSYS_LOGICIEL="$TRAVAIL/logiciel"
export OPSYS_BIN="$TRAVAIL/commandes"
export OPSYS_SOURCE="$RACINE"
export PATH="$OPSYS_BIN:$PATH"
export HOME="${HOME:?}"
PORT_GATEWAY=18789
PORT_MOTEUR=8765
ETAT_CORE="$HOME/.openclaw-opsys"
UNITE_ATTENDUE="openclaw-gateway-opsys.service"
UNITE_DU_CORE_D_ORIGINE="openclaw-gateway.service"
GATEWAY_PID=""
CONSTATS=()

# Les décisions que l'installateur n'invente pas : un palier de modèles, un service d'embeddings et une passerelle
# de modèles. Aucun n'existe en CI : ce sont des adresses fermées, seul le démarrage est éprouvé.
export OPSYS_EMBEDDINGS_URL="http://127.0.0.1:9/v1"
export OPSYS_EMBEDDINGS_MODELE="bge-m3"
export OPSYS_PASSERELLE_URL="http://127.0.0.1:9/v1"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

etape() { printf '\n== %s\n' "$*"; }
constat() {
    CONSTATS+=("$1")
    printf 'OK  %s\n' "$1"
}
echec() {
    printf 'ÉCHEC : %s\n' "$*" >&2
    exit 1
}

arreter_gateway() {
    if [ -n "$GATEWAY_PID" ] && kill -0 "$GATEWAY_PID" 2>/dev/null; then
        kill -TERM "$GATEWAY_PID" 2>/dev/null || true
        wait "$GATEWAY_PID" 2>/dev/null || true
    fi
    GATEWAY_PID=""
}
trap arreter_gateway EXIT

code_http() { curl -sS --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "$@" 2>/dev/null || printf '000'; }

attendre_http() { # url, délai (s), libellé
    local ecoule=0
    while [ "$ecoule" -lt "$2" ]; do
        if [ "$(code_http "$1")" = "200" ]; then return 0; fi
        if [ -n "$GATEWAY_PID" ] && ! kill -0 "$GATEWAY_PID" 2>/dev/null; then
            echec "$3 : le Gateway s'est arrêté avant de répondre (voir $TRAVAIL/gateway-premier-plan.log)"
        fi
        sleep 2
        ecoule=$((ecoule + 2))
    done
    echec "$3 : pas de réponse 200 sur $1 après $2 s"
}

valeurs_secretes() {
    sed -n -E 's/^[[:space:]]*(export[[:space:]]+)?[A-Z0-9_]*(JETON|TOKEN|_CLE|SECRET|PASSWORD)[A-Z0-9_]*=(.{12,})$/\3/p' \
        "$ETAT_CORE/.env"
}

masquer_les_secrets() {
    local valeur
    while IFS= read -r valeur; do
        [ -n "$valeur" ] && echo "::add-mask::$valeur"
    done < <(valeurs_secretes)
}

exiger_sans_secret() { # libellé, fichiers...
    local libelle="$1" valeur fichier
    shift
    while IFS= read -r valeur; do
        for fichier in "$@"; do
            if grep -qF -- "$valeur" "$fichier" 2>/dev/null; then
                echec "$libelle : un secret de .env apparaît dans $fichier"
            fi
        done
    done < <(valeurs_secretes)
}

empreinte() { sha256sum "$@" | awk '{print $1}'; }

# Un secret écrit hors de l'instance (définition du service, fichier d'environnement du service) n'est lisible que par
# son propriétaire : aucun bit de groupe ni d'autres.
exiger_secrets_prives_au_repos() { # dossiers...
    local valeur fichier mode
    while IFS= read -r valeur; do
        while IFS= read -r fichier; do
            mode="$(stat -c '%a' "$fichier")"
            case "$mode" in
                *00) ;;
                *) echec "$fichier contient un secret de .env et son mode est $mode (0600 attendu)" ;;
            esac
        done < <(grep -rlF -- "$valeur" "$@" 2>/dev/null || true)
    done < <(valeurs_secretes)
}

# Les fichiers que l'installateur écrit ou garde : secrets, configuration du core, fragments OPSYS, réglages. Pas l'état
# que le Gateway écrit lui-même (sessions, espaces de travail des agents).
empreinte_des_fichiers_geres() {
    {
        printf '%s\0' "$ETAT_CORE/.env" "$ETAT_CORE/openclaw.json" "$OPSYS_HOME/paliers.yaml"
        find "$ETAT_CORE/opsys" -maxdepth 1 -name '*.json' -print0
    } | sort -z | xargs -0 sha256sum | sha256sum
}

installer() { # journal de sortie, options...
    local sortie="$1"
    shift
    if ! bash "$RACINE/install/install.sh" "$@" >"$sortie" 2>&1; then
        cat "$sortie"
        echec "install.sh a échoué (code non nul)"
    fi
    masquer_les_secrets
    exiger_sans_secret "sortie de l'installateur" "$sortie" "$OPSYS_LOGICIEL/journaux/installation.log"
}

# -- 0. Le poste ---------------------------------------------------------------------------------------------------------
etape "0. Poste : ni état du core d'OPSYS ni son service ne doivent déjà exister (ce script installe puis désinstalle)"
[ ! -e "$ETAT_CORE" ] ||
    echec "$ETAT_CORE existe déjà : ce script installe puis désinstalle, il ne s'exécute pas sur un poste qui porte une instance OPSYS. Déplacez ce dossier, ou prenez un poste neuf."
if command -v systemctl >/dev/null 2>&1 && [ -n "$(systemctl --user list-unit-files --no-legend "$UNITE_ATTENDUE" 2>/dev/null || true)" ]; then
    echec "le service $UNITE_ATTENDUE existe déjà sur ce poste : ce script ne s'exécute pas sur un poste qui porte une instance OPSYS."
fi
constat "poste neuf : aucun état du core d'OPSYS ($ETAT_CORE) ni service $UNITE_ATTENDUE"

etape "0 bis. Décision préalable : un palier de modèles (comme après une restauration ou un premier réglage)"
mkdir -p "$OPSYS_HOME"
chmod 700 "$OPSYS_HOME"
printf 'paliers:\n  standard: {provider: anthropic, model: claude-sonnet-5}\n' >"$OPSYS_HOME/paliers.yaml"

# -- 1. Installation sans service ----------------------------------------------------------------------------------------
etape "1. Installation (sans service) : Node, pnpm, uv, construction du core, moteur, instance, configuration"
installer "$TRAVAIL/installation-1.log" --sans-service
if [ ! -x "$OPSYS_BIN/openclaw" ] || [ ! -x "$OPSYS_BIN/opsys" ]; then echec "les commandes openclaw et opsys ne sont pas installées"; fi
[ "$(stat -c '%a' "$ETAT_CORE/.env")" = "600" ] || echec ".env n'est pas en 0600"
[ "$(stat -c '%a' "$ETAT_CORE")" = "700" ] || echec "le dossier d'état du core n'est pas en 0700"
[ -f "$ETAT_CORE/opsys/metier.json" ] || echec "opsys/metier.json absent de $ETAT_CORE"
[ ! -e "$OPSYS_HOME/core" ] || echec "un dossier core est apparu sous OPSYS_HOME : l'état du core ne vit plus là (T0.11-b)"
if [ ! -f "$OPSYS_HOME/opsys.db" ] || [ ! -f "$OPSYS_HOME/paliers.yaml" ]; then echec "les données métier ne sont plus sous OPSYS_HOME"; fi
exiger_sans_secret "configuration du core" "$ETAT_CORE/openclaw.json" "$ETAT_CORE"/opsys/*.json
constat "installation terminée : état du core dans $ETAT_CORE (0700, .env en 0600), données dans OPSYS_HOME, aucun secret dans la configuration, la sortie ni le journal de l'installateur"

etape "1 bis. Le dossier d'état : le moteur Python, le core et les attentes écrites d'après le fork s'accordent"
[ "$(opsys instance dossier)" = "$ETAT_CORE" ] ||
    echec "opsys instance dossier répond '$(opsys instance dossier)' au lieu de $ETAT_CORE"
[ "$(openclaw config file | tail -n 1)" = "$ETAT_CORE/openclaw.json" ] ||
    echec "le core cherche sa configuration dans '$(openclaw config file | tail -n 1)' au lieu de $ETAT_CORE/openclaw.json"
polluee="$(OPENCLAW_STATE_DIR="$TRAVAIL/ailleurs" OPENCLAW_CONFIG_PATH="$TRAVAIL/ailleurs/openclaw.json" \
    OPENCLAW_HOME="$TRAVAIL/home-du-core" OPENCLAW_PROFILE=autre openclaw config file | tail -n 1)"
[ "$polluee" = "$ETAT_CORE/openclaw.json" ] ||
    echec "un environnement OPENCLAW_* a déplacé le core : il lit '$polluee' (la commande installée doit l'écarter)"
if [ -e "$TRAVAIL/ailleurs" ] || [ -e "$TRAVAIL/home-du-core" ]; then echec "un dossier a été créé d'après l'environnement de l'appelant"; fi
constat "opsys instance dossier, openclaw config file et l'attente écrite d'après le fork donnent tous $ETAT_CORE ; l'environnement de l'appelant n'y change rien"

etape "1 ter. Le core accepte la configuration générée"
openclaw config validate
constat "openclaw config validate accepte la configuration (dont \${OPSYS_MCP_JETON}, lue dans .env)"

etape "1 quater. Ancienne disposition (\$OPSYS_HOME/core) : signalée avec la marche à suivre, jamais migrée en silence"
mkdir -p "$OPSYS_HOME/core"
printf 'MARQUEUR=ancien-etat-fictif\n' >"$OPSYS_HOME/core/.env"
ancien_avant="$(empreinte "$OPSYS_HOME/core/.env")"
geres_avant="$(empreinte_des_fichiers_geres)"
if opsys instance initialiser >"$TRAVAIL/ancienne-disposition.json" 2>"$TRAVAIL/ancienne-disposition.err"; then
    echec "opsys instance initialiser a accepté l'ancienne disposition"
fi
grep -q "ancienne disposition détectée" "$TRAVAIL/ancienne-disposition.err" ||
    echec "l'ancienne disposition n'est pas signalée : $(cat "$TRAVAIL/ancienne-disposition.err")"
grep -qF "$OPSYS_HOME/core" "$TRAVAIL/ancienne-disposition.err" || echec "le message ne nomme pas l'ancien dossier"
grep -qF "$ETAT_CORE" "$TRAVAIL/ancienne-disposition.err" || echec "le message ne nomme pas le dossier d'état du core"
grep -q "Rien n'est migré en silence" "$TRAVAIL/ancienne-disposition.err" || echec "le message ne dit pas que rien n'est migré"
[ "$(empreinte "$OPSYS_HOME/core/.env")" = "$ancien_avant" ] || echec "l'ancien état a été modifié"
[ "$(empreinte_des_fichiers_geres)" = "$geres_avant" ] || echec "l'état du core a changé pendant le refus"
mv "$OPSYS_HOME/core" "$OPSYS_HOME/core.ancien" # la marche à suivre : repartir à neuf
opsys instance initialiser >/dev/null
[ "$(empreinte_des_fichiers_geres)" = "$geres_avant" ] || echec "la réinitialisation a changé un secret ou la configuration"
[ "$(empreinte "$OPSYS_HOME/core.ancien/.env")" = "$ancien_avant" ] || echec "l'ancien état mis de côté a été modifié"
constat "l'ancienne disposition est refusée avec la marche à suivre, sans rien modifier ; mise de côté, l'instance se réinitialise sans changer un secret"

# -- 2. Gateway au premier plan et moteur supervisé ---------------------------------------------------------------------------
etape "2. Gateway au premier plan : il lance le moteur (superviseur T0.10) avec le jeton de .env"
openclaw gateway run --bind loopback --port "$PORT_GATEWAY" >"$TRAVAIL/gateway-premier-plan.log" 2>&1 &
GATEWAY_PID=$!
attendre_http "http://127.0.0.1:$PORT_GATEWAY/startupz" 300 "Gateway"
attendre_http "http://127.0.0.1:$PORT_MOTEUR/sante" 240 "moteur"
constat "GET /startupz du Gateway et GET /sante du moteur : 200"
JETON="$(sed -n 's/^OPSYS_MCP_JETON=//p' "$ETAT_CORE/.env")"
[ "$(code_http "http://127.0.0.1:$PORT_MOTEUR/mcp")" = "401" ] || echec "le moteur accepte une requête sans jeton"
[ "$(code_http -H 'Authorization: Bearer jeton-faux-0123456789abcdef' "http://127.0.0.1:$PORT_MOTEUR/mcp")" = "401" ] ||
    echec "le moteur accepte un mauvais jeton"
code_avec_jeton="$(code_http -H "Authorization: Bearer $JETON" "http://127.0.0.1:$PORT_MOTEUR/mcp")"
case "$code_avec_jeton" in
    401 | 000) echec "le moteur supervisé refuse le jeton de .env (HTTP $code_avec_jeton) : le Gateway ne lui a pas donné celui de l'installation" ;;
    *) ;;
esac
constat "une seule authentification : le moteur lancé par le Gateway accepte le jeton de .env, refuse tout autre"
arreter_gateway
ecoule=0
while [ "$(code_http "http://127.0.0.1:$PORT_MOTEUR/sante")" = "200" ]; do
    [ "$ecoule" -lt 60 ] || echec "le moteur répond encore 60 s après l'arrêt du Gateway : processus orphelin"
    sleep 2
    ecoule=$((ecoule + 2))
done
constat "l'arrêt du Gateway arrête le moteur qu'il supervise"
exiger_sans_secret "journal du Gateway" "$TRAVAIL/gateway-premier-plan.log"
constat "aucun secret de .env dans le journal du Gateway (moteur compris)"

# -- 3. Idempotence -------------------------------------------------------------------------------------------------------------
etape "3. Relance : ni secret, ni configuration, ni donnée ne change"
avant="$(empreinte_des_fichiers_geres)"
installer "$TRAVAIL/installation-2.log" --sans-service
apres="$(empreinte_des_fichiers_geres)"
[ "$avant" = "$apres" ] || echec "la relance a modifié .env, la configuration ou les réglages de l'instance"
constat "relancer install.sh laisse .env, la configuration du core et les réglages identiques"

# -- 4. Export et restauration --------------------------------------------------------------------------------------------------
etape "4. Export : archive privée, empreinte SHA-256, sans secret ; restauration dans une instance neuve"
opsys instance exporter --sortie "$TRAVAIL/export.tar.gz" >"$TRAVAIL/export.json"
(cd "$TRAVAIL" && sha256sum -c export.tar.gz.sha256)
[ "$(stat -c '%a' "$TRAVAIL/export.tar.gz")" = "600" ] || echec "l'archive d'export n'est pas en 0600"
membres="$(tar -tzf "$TRAVAIL/export.tar.gz" | sort | tr '\n' ' ')"
[ "$membres" = "opsys-export/manifeste.json opsys-export/opsys.db opsys-export/paliers.yaml " ] ||
    echec "membres inattendus dans l'archive : $membres"
mkdir -p "$TRAVAIL/decompose"
tar -xzf "$TRAVAIL/export.tar.gz" -C "$TRAVAIL/decompose"
exiger_sans_secret "archive d'export" "$TRAVAIL"/decompose/opsys-export/*
grep -qF '"~/.openclaw-opsys/.env"' "$TRAVAIL/decompose/opsys-export/manifeste.json" ||
    echec "le manifeste ne nomme pas l'état du core (~/.openclaw-opsys) parmi les fichiers exclus"
! grep -qF "$HOME" "$TRAVAIL/decompose/opsys-export/manifeste.json" || echec "le manifeste porte le dossier personnel du poste"
constat "export : membres = liste blanche, SHA-256 vérifié par sha256sum, 0600, aucun secret de .env, état du core nommé parmi les exclus"
etat_avant_restauration="$(empreinte_des_fichiers_geres)"
OPSYS_HOME="$TRAVAIL/restaure" opsys instance restaurer "$TRAVAIL/export.tar.gz" >"$TRAVAIL/restauration.json"
OPSYS_HOME="$TRAVAIL/restaure" opsys base etat >"$TRAVAIL/restaure-etat.json"
grep -q '"revision"' "$TRAVAIL/restaure-etat.json" || echec "la base restaurée n'est pas lisible par opsys base etat"
[ ! -e "$TRAVAIL/restaure/core" ] || echec "la restauration a posé un dossier core (secrets) : elle ne doit restaurer que les données"
[ "$(empreinte_des_fichiers_geres)" = "$etat_avant_restauration" ] || echec "la restauration a touché l'état du core"
constat "restauration dans une instance neuve : base lisible, aucun secret ni état du Gateway restauré"

# -- 5. Service utilisateur ---------------------------------------------------------------------------------------------------------
service_disponible() {
    command -v systemctl >/dev/null 2>&1 || return 1
    sudo loginctl enable-linger "$(id -un)" >/dev/null 2>&1 || true
    XDG_RUNTIME_DIR="/run/user/$(id -u)"
    export XDG_RUNTIME_DIR
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    local essai=0
    while [ "$essai" -lt 30 ]; do
        if systemctl --user show-environment >/dev/null 2>&1; then return 0; fi
        sleep 1
        essai=$((essai + 1))
    done
    return 1
}

SERVICE_PROUVE="non"
etape "5. Service utilisateur (systemd --user) : installation, démarrage, supervision du moteur"
if [ "${OPSYS_SANS_SERVICE:-0}" = "1" ]; then
    echo "::warning::phase du service sautée (OPSYS_SANS_SERVICE=1)"
elif service_disponible; then
    installer "$TRAVAIL/installation-3.log"
    UNITE="$UNITE_ATTENDUE"
    [ "$(systemctl --user list-unit-files --no-legend "$UNITE" | awk 'NR==1 {print $1}')" = "$UNITE" ] ||
        echec "l'unité $UNITE n'existe pas après l'installation du service (nom du profil « opsys »)"
    [ "$(systemctl --user list-unit-files --no-legend "$UNITE_DU_CORE_D_ORIGINE" | wc -l)" -eq 0 ] ||
        echec "l'unité $UNITE_DU_CORE_D_ORIGINE, celle du core d'origine, existe : le nom du service n'est pas distinct"
    [ "$(systemctl --user is-active "$UNITE")" = "active" ] || echec "$UNITE n'est pas actif"
    grep -qF "$ETAT_CORE" "$HOME/.config/systemd/user/$UNITE" ||
        echec "l'unité ne désigne pas le dossier d'état canonique du profil ($ETAT_CORE)"
    grep -qF "OPENCLAW_PROFILE=opsys" "$HOME/.config/systemd/user/$UNITE" || echec "l'unité ne porte pas le profil opsys"
    ! grep -qF "$OPSYS_HOME/core" "$HOME/.config/systemd/user/$UNITE" || echec "l'unité désigne l'ancien état du core"
    [ "$(code_http "http://127.0.0.1:$PORT_MOTEUR/sante")" = "200" ] || echec "le moteur ne répond pas sous le service"
    journalctl --user -u "$UNITE" --no-pager >"$TRAVAIL/journal-service.log" 2>&1 || true
    exiger_sans_secret "journal du service" "$TRAVAIL/journal-service.log"
    exiger_sans_secret "unité systemd" "$HOME/.config/systemd/user/$UNITE"
    exiger_secrets_prives_au_repos "$HOME/.config" "$HOME/.local/share" "$HOME/.local/state"
    constat "le service $UNITE tourne, le moteur qu'il supervise répond, aucun secret dans son journal ni dans son unité, aucun secret lisible par un autre compte hors de l'instance"
    SERVICE_PROUVE="oui"
else
    echo "::warning::systemd --user est indisponible sur ce poste : le service n'est PAS prouvé ici (le Gateway l'a été au premier plan)"
    constat "service systemd utilisateur NON prouvé : bus utilisateur indisponible sur ce poste"
fi

# -- 6. Désinstallation sans perte de données -----------------------------------------------------------------------------------------
etape "6. Désinstallation avec export préalable : le logiciel part, les données restent"
env_avant="$(empreinte "$ETAT_CORE/.env")"
config_avant="$(empreinte "$ETAT_CORE/openclaw.json")"
geres_avant_desinstallation="$(empreinte_des_fichiers_geres)"
paliers_avant="$(empreinte "$OPSYS_HOME/paliers.yaml")"
if ! bash "$RACINE/install/uninstall.sh" --exporter-avant "$TRAVAIL/avant-desinstallation.tar.gz" >"$TRAVAIL/desinstallation.log" 2>&1; then
    cat "$TRAVAIL/desinstallation.log"
    echec "uninstall.sh a échoué"
fi
(cd "$TRAVAIL" && sha256sum -c avant-desinstallation.tar.gz.sha256)
if [ -e "$OPSYS_BIN/openclaw" ] || [ -e "$OPSYS_BIN/opsys" ]; then echec "les commandes sont encore là"; fi
[ ! -e "$OPSYS_LOGICIEL" ] || echec "le logiciel est encore là : $(ls -A "$OPSYS_LOGICIEL")"
[ -f "$RACINE/core/openclaw.mjs" ] || echec "le dépôt de l'utilisateur a été touché"
[ "$(empreinte "$ETAT_CORE/.env")" = "$env_avant" ] || echec ".env a changé pendant la désinstallation"
[ "$(empreinte "$ETAT_CORE/openclaw.json")" = "$config_avant" ] || echec "openclaw.json a changé pendant la désinstallation"
[ "$(empreinte_des_fichiers_geres)" = "$geres_avant_desinstallation" ] || echec "un fichier géré a changé pendant la désinstallation"
[ "$(empreinte "$OPSYS_HOME/core.ancien/.env")" = "$ancien_avant" ] || echec "l'ancien état mis de côté a changé pendant la désinstallation"
grep -q "État du core conservé : $ETAT_CORE" "$TRAVAIL/desinstallation.log" ||
    echec "la désinstallation ne dit pas où est l'état du core qu'elle conserve"
[ "$(empreinte "$OPSYS_HOME/paliers.yaml")" = "$paliers_avant" ] || echec "paliers.yaml a changé pendant la désinstallation"
python3 - "$OPSYS_HOME/opsys.db" <<'PYTHON'
import sqlite3, sys
connexion = sqlite3.connect(sys.argv[1])
assert connexion.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "base endommagée"
assert connexion.execute("SELECT count(*) FROM alembic_version").fetchone()[0] == 1, "base non migrée"
PYTHON
if [ "$SERVICE_PROUVE" = "oui" ]; then
    [ "$(systemctl --user list-unit-files --no-legend "$UNITE_ATTENDUE" | wc -l)" -eq 0 ] ||
        echec "l'unité du service est encore installée"
    [ "$(code_http "http://127.0.0.1:$PORT_GATEWAY/startupz")" != "200" ] || echec "le Gateway répond encore après la désinstallation"
    [ "$(code_http "http://127.0.0.1:$PORT_MOTEUR/sante")" != "200" ] || echec "le moteur répond encore après la désinstallation"
fi
constat "désinstallation : service, logiciel et commandes retirés ; .env, configuration, réglages, base, état du core et ancien état mis de côté intacts ; export vérifié"
bash "$RACINE/install/uninstall.sh" >"$TRAVAIL/desinstallation-2.log" 2>&1 || echec "la désinstallation n'est pas relançable"
constat "la désinstallation est relançable"

# -- Résumé ---------------------------------------------------------------------------------------------------------------------------
etape "Tout est vrai"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        printf '### Installateur avec le vrai core\n\n'
        printf -- '- %s\n' "${CONSTATS[@]}"
        printf '\nService systemd utilisateur prouvé : **%s**\n' "$SERVICE_PROUVE"
    } >>"$GITHUB_STEP_SUMMARY"
fi
