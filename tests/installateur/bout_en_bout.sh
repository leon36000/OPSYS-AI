#!/usr/bin/env bash
# tests/installateur/bout_en_bout.sh : preuve de l'installateur avec le VRAI core (PLAN T0.11), pour la CI, sur Linux
# (systemd --user) et sur macOS (launchd). Windows a son propre script : bout_en_bout.ps1.
#
# `tests/test_installateur_scripts.py` joue install.sh contre de fausses commandes ; ici tout est vrai : le core
# est construit, le moteur est installé par uv, la configuration passe `openclaw config validate`, le Gateway
# démarre et lance le moteur, le service utilisateur tourne, l'export est cohérent, et la désinstallation retire le
# logiciel sans perdre une donnée. Chaque constat faux arrête le script, avec quoi regarder. Aucune étape ne tolère
# l'échec, sauf l'absence de service utilisateur sur le poste (systemd --user, session graphique launchd), signalée
# en clair et refusée si OPSYS_SERVICE_REQUIS=1.
#
# Le core tourne sous son profil « opsys » (PLAN T0.11-b). Ses attentes sont écrites ICI, en dur, d'après le code du
# fork, et confrontées à ce que le vrai core et le moteur Python répondent :
#   - dossier d'état : ~/.openclaw-opsys (core/src/cli/profile-utils.ts, resolveProfileStateDir) ;
#   - Linux : service systemd utilisateur openclaw-gateway-opsys.service (core/src/daemon/constants.ts), distinct de
#     openclaw-gateway.service, celui du core d'origine ;
#   - macOS : LaunchAgent ai.openclaw.opsys, distinct de ai.openclaw.gateway. Le plist est écrit dans
#     ~/Library/LaunchAgents (0644, launchd l'exige) et ne porte AUCUN secret ; l'environnement du service est dans
#     <état du core>/service-env/<étiquette>.env (0600) ; le journal du service est ~/Library/Logs/openclaw/
#     (core/src/daemon/launchd-service-files.ts, restart-logs.ts). La désinstallation du service range le plist
#     dans ~/.Trash (core/src/daemon/launchd-install.ts).
# Ce script INSTALLE puis DÉSINSTALLE : il refuse de tourner sur un poste qui a déjà un état du core d'OPSYS ou son
# service (ne l'exécutez pas sur un poste réel ; la CI l'exécute sur une machine neuve).
#
# Différences macOS (BSD) prises en compte : `shasum -a 256` pour `sha256sum`, `stat -f '%Lp'` pour `stat -c '%a'`,
# bash 3.2 (ni tableau associatif, ni mapfile, ni tableau vide sous `set -u`), pas de journalctl.
#
# Sortie : sous GitHub Actions, chaque étape est un groupe repliable (::group::) ; un échec ferme le groupe, imprime la
# cause, la pose en annotation (::error::) et dans le résumé du job. Les valeurs secrètes de .env sont déclarées au
# masque de GitHub (::add-mask::) dès qu'elles existent : aucune n'est imprimée en clair.
#
# Usage (depuis la racine du dépôt, Node 24+, Python 3.11+, uv) : bash tests/installateur/bout_en_bout.sh
# Variables : OPSYS_TRAVAIL (dossier de travail, défaut : un dossier temporaire), OPSYS_SANS_SERVICE=1 (saute la
# phase du service), OPSYS_SERVICE_REQUIS=1 (l'absence de service utilisateur sur le poste est un échec),
# OPSYS_PORT_GATEWAY et OPSYS_PORT_MOTEUR (défauts 18789 et 8765, comme l'installateur).
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
TRAVAIL="${OPSYS_TRAVAIL:-$(mktemp -d)}"
mkdir -p "$TRAVAIL"

SYSTEME="$(uname -s)"
case "$SYSTEME" in
    Linux) SHA256=(sha256sum) ;;
    Darwin) SHA256=(shasum -a 256) ;;
    *)
        printf 'ÉCHEC : système non pris en charge (%s) : Linux et macOS ici, Windows par bout_en_bout.ps1\n' "$SYSTEME" >&2
        exit 1
        ;;
esac

export OPSYS_HOME="$TRAVAIL/instance"
export OPSYS_LOGICIEL="$TRAVAIL/logiciel"
export OPSYS_BIN="$TRAVAIL/commandes"
export OPSYS_SOURCE="$RACINE"
export PATH="$OPSYS_BIN:$PATH"
export HOME="${HOME:?}"
PORT_GATEWAY="${OPSYS_PORT_GATEWAY:-18789}"
PORT_MOTEUR="${OPSYS_PORT_MOTEUR:-8765}"
export OPSYS_PORT_GATEWAY="$PORT_GATEWAY" OPSYS_PORT_MOTEUR="$PORT_MOTEUR"
ETAT_CORE="$HOME/.openclaw-opsys"
UNITE_ATTENDUE="openclaw-gateway-opsys.service"
UNITE_DU_CORE_D_ORIGINE="openclaw-gateway.service"
ETIQUETTE_ATTENDUE="ai.openclaw.opsys"
ETIQUETTE_DU_CORE_D_ORIGINE="ai.openclaw.gateway"
PLIST="$HOME/Library/LaunchAgents/$ETIQUETTE_ATTENDUE.plist"
PLIST_DU_CORE_D_ORIGINE="$HOME/Library/LaunchAgents/$ETIQUETTE_DU_CORE_D_ORIGINE.plist"
FICHIER_ENV_LAUNCHD="$ETAT_CORE/service-env/$ETIQUETTE_ATTENDUE.env"
GATEWAY_PID=""
CONSTATS=()
ETAPE_COURANTE="préparation"
GROUPE_OUVERT=0

# Les décisions que l'installateur n'invente pas : un palier de modèles, un service d'embeddings et une passerelle
# de modèles. Aucun n'existe en CI : ce sont des adresses fermées, seul le démarrage est éprouvé.
export OPSYS_EMBEDDINGS_URL="http://127.0.0.1:9/v1"
export OPSYS_EMBEDDINGS_MODELE="bge-m3"
export OPSYS_PASSERELLE_URL="http://127.0.0.1:9/v1"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

fin_groupe() {
    if [ "$GROUPE_OUVERT" = "1" ]; then
        echo "::endgroup::"
        GROUPE_OUVERT=0
    fi
}
etape() {
    ETAPE_COURANTE="$*"
    if [ -n "${GITHUB_ACTIONS:-}" ]; then
        fin_groupe
        printf '::group::%s\n' "$*"
        GROUPE_OUVERT=1
    fi
    printf '\n== %s\n' "$*"
}
constat() {
    CONSTATS+=("$1")
    printf 'OK  %s\n' "$1"
}
# Un échec ferme le groupe ouvert (sinon la cause serait repliée), imprime la cause, la pose en annotation et dans le
# résumé du job, puis arrête. Les secrets de .env, s'ils existent déjà, sont d'abord déclarés au masque de GitHub.
echec() {
    local message="$*" numero annotation
    if [ -f "$ETAT_CORE/.env" ]; then masquer_les_secrets || true; fi
    fin_groupe
    printf 'ÉCHEC : %s\n' "$message" >&2
    if [ -n "${GITHUB_ACTIONS:-}" ]; then
        numero="${ETAPE_COURANTE%%.*}"
        annotation="${message//\%/%25}"
        annotation="${annotation//$'\r'/%0D}"
        annotation="${annotation//$'\n'/%0A}"
        printf '::error title=Installateur %s - étape %s::%s\n' "$SYSTEME" "$numero" "$annotation"
    fi
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
        printf '### Installateur (%s) : ÉCHEC à l'"'"'étape « %s »\n\n%s\n' "$SYSTEME" "$ETAPE_COURANTE" "$message" >>"$GITHUB_STEP_SUMMARY"
    fi
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

# Le code HTTP, ou 000 si rien ne répond (curl écrit déjà 000 par -w quand la connexion échoue).
code_http() {
    local code
    code="$(curl -sS --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "$@" 2>/dev/null)" || true
    printf '%s' "${code:-000}"
}

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

# Attend qu'une adresse cesse de répondre 200 (arrêt d'un service : launchd et systemd rendent la main avant la fin du
# processus, qui draine ses connexions).
attendre_arret() { # url, délai (s), libellé
    local ecoule=0
    while [ "$(code_http "$1")" = "200" ]; do
        [ "$ecoule" -lt "$2" ] || echec "$3 : $1 répond encore $2 s après l'arrêt (processus orphelin ?)"
        sleep 2
        ecoule=$((ecoule + 2))
    done
}

mode_de() { # chemin -> mode octal (600, 700...) ; `stat` de BSD (macOS) et de GNU (Linux) ne s'écrivent pas pareil
    case "$SYSTEME" in
        Darwin) stat -f '%Lp' "$1" ;;
        *) stat -c '%a' "$1" ;;
    esac
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

empreinte() { "${SHA256[@]}" "$@" | awk '{print $1}'; }

# Un secret écrit hors de l'instance (définition du service, fichier d'environnement du service) n'est lisible que par
# son propriétaire : aucun bit de groupe ni d'autres.
exiger_secrets_prives_au_repos() { # dossiers...
    local valeur fichier mode
    while IFS= read -r valeur; do
        while IFS= read -r fichier; do
            mode="$(mode_de "$fichier")"
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
    } | xargs -0 "${SHA256[@]}" | sort | "${SHA256[@]}"
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

# -- Les fonctions du service utilisateur (phase 5) -----------------------------------------------------------------------
# Linux : systemd --user. Le bus utilisateur existe s'il y a une session (ou loginctl enable-linger).
service_disponible_systemd() {
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

# macOS : launchd. `gateway install` amorce le LaunchAgent dans le domaine gui/<uid> (core/src/daemon/launchd-runtime.ts,
# resolveLaunchAgentGuiDomain) : il faut la session graphique de l'utilisateur.
service_disponible_launchd() {
    command -v launchctl >/dev/null 2>&1 || return 1
    launchctl print "gui/$(id -u)" >"$TRAVAIL/launchctl-domaine.txt" 2>&1
}

service_disponible() {
    case "$SYSTEME" in
        Darwin) service_disponible_launchd ;;
        *) service_disponible_systemd ;;
    esac
}

verifier_service_systemd() {
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
}

# Lit le plist par plistlib (bibliothèque standard de Python, aucun outil macOS requis) : Label, ProgramArguments,
# RunAtLoad et journal du service (StandardOutPath). Écrit le journal sur la sortie standard.
lire_plist() { # plist, étiquette attendue
    python3 - "$1" "$2" <<'PYTHON'
import plistlib
import sys

with open(sys.argv[1], "rb") as fichier:
    plist = plistlib.load(fichier)
if plist.get("Label") != sys.argv[2]:
    sys.exit("Label %r au lieu de %r" % (plist.get("Label"), sys.argv[2]))
if not plist.get("ProgramArguments"):
    sys.exit("ProgramArguments absent ou vide")
if plist.get("RunAtLoad") is not True:
    sys.exit("RunAtLoad n'est pas vrai : le service ne démarrerait pas à l'ouverture de session")
print(plist.get("StandardOutPath", ""))
PYTHON
}

verifier_service_launchd() {
    local domaine cible journal contenu resume autre
    domaine="gui/$(id -u)"
    cible="$domaine/$ETIQUETTE_ATTENDUE"
    [ -f "$PLIST" ] || echec "le plist $PLIST n'existe pas après l'installation du service (étiquette du profil « opsys »)"
    [ ! -e "$PLIST_DU_CORE_D_ORIGINE" ] ||
        echec "le plist $PLIST_DU_CORE_D_ORIGINE, celui du core d'origine, existe : l'étiquette du service n'est pas distincte"
    if ! launchctl print "$cible" >"$TRAVAIL/launchctl-service.txt" 2>&1; then
        cat "$TRAVAIL/launchctl-service.txt"
        echec "launchd ne connaît pas $cible après l'installation du service"
    fi
    grep -Eq '^[[:space:]]*state = running$' "$TRAVAIL/launchctl-service.txt" ||
        echec "$cible n'est pas en cours d'exécution (launchctl print : $(grep -E '^[[:space:]]*(state|last exit code) =' "$TRAVAIL/launchctl-service.txt" | tr -s '[:space:]' ' '))"
    if ! journal="$(lire_plist "$PLIST" "$ETIQUETTE_ATTENDUE" 2>&1)"; then
        echec "le plist n'est pas celui attendu : $journal"
    fi
    # Le profil et le dossier d'état canoniques : le plist désigne le fichier d'environnement, qui porte le profil.
    contenu="$(cat "$PLIST" "$FICHIER_ENV_LAUNCHD" 2>/dev/null | tr -d '[:space:]')"
    case "$contenu" in
        *"$ETAT_CORE"*) ;;
        *) echec "ni le plist ni $FICHIER_ENV_LAUNCHD ne désignent le dossier d'état canonique du profil ($ETAT_CORE)" ;;
    esac
    case "$contenu" in
        *"OPENCLAW_PROFILE='opsys'"* | *"OPENCLAW_PROFILE=opsys"* | *"<key>OPENCLAW_PROFILE</key><string>opsys</string>"*) ;;
        *) echec "ni le plist ni $FICHIER_ENV_LAUNCHD ne portent le profil opsys" ;;
    esac
    case "$contenu" in
        *"$OPSYS_HOME/core"*) echec "le service désigne l'ancien état du core" ;;
        *) ;;
    esac
    [ "$(code_http "http://127.0.0.1:$PORT_MOTEUR/sante")" = "200" ] || echec "le moteur ne répond pas sous le service"
    # Aucun secret dans le plist (0644 : lisible par tous les comptes, launchd l'exige) ni dans les journaux du service.
    exiger_sans_secret "plist launchd" "$PLIST"
    if [ -n "$journal" ] && [ -f "$journal" ]; then
        cp "$journal" "$TRAVAIL/journal-service.log"
        exiger_sans_secret "journal du service" "$TRAVAIL/journal-service.log"
    else
        echec "le journal du service ($journal, StandardOutPath du plist) n'existe pas : le service n'a rien écrit ?"
    fi
    for autre in /tmp/openclaw/*.log; do
        [ -f "$autre" ] || continue
        exiger_sans_secret "journal du core ($autre)" "$autre"
    done
    exiger_secrets_prives_au_repos "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$ETAT_CORE/service-env"
    resume="$(grep -E '^[[:space:]]*pid = ' "$TRAVAIL/launchctl-service.txt" | head -n 1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    constat "le service $ETIQUETTE_ATTENDUE tourne dans launchd ($resume), le moteur qu'il supervise répond, aucun secret dans son plist ni ses journaux, aucun secret lisible par un autre compte hors de l'instance"
}

raison_service_indisponible() {
    if [ "$SYSTEME" = "Darwin" ]; then
        printf 'pas de domaine launchd gui/%s (session graphique absente ?) : %s' "$(id -u)" "$(cat "$TRAVAIL/launchctl-domaine.txt" 2>/dev/null || true)"
    else
        printf 'pas de bus systemd --user'
    fi
}

# Chargement pour les tests (tests/test_installateur_bout_en_bout.py) : les fonctions seules, sans jouer la preuve.
if [ "${OPSYS_BOUT_EN_BOUT_FONCTIONS_SEULEMENT:-0}" = "1" ]; then
    # shellcheck disable=SC2317
    return 0 2>/dev/null || exit 0
fi

# -- 0. Le poste ---------------------------------------------------------------------------------------------------------
etape "0. Poste : ni état du core d'OPSYS ni son service ne doivent déjà exister (ce script installe puis désinstalle)"
[ ! -e "$ETAT_CORE" ] ||
    echec "$ETAT_CORE existe déjà : ce script installe puis désinstalle, il ne s'exécute pas sur un poste qui porte une instance OPSYS. Déplacez ce dossier, ou prenez un poste neuf."
if [ "$SYSTEME" = "Darwin" ]; then
    NOM_SERVICE="$ETIQUETTE_ATTENDUE"
    [ ! -e "$PLIST" ] || echec "le plist $PLIST existe déjà sur ce poste : ce script ne s'exécute pas sur un poste qui porte une instance OPSYS."
    if command -v launchctl >/dev/null 2>&1 && launchctl print "gui/$(id -u)/$ETIQUETTE_ATTENDUE" >/dev/null 2>&1; then
        echec "le service $ETIQUETTE_ATTENDUE est déjà chargé dans launchd : ce script ne s'exécute pas sur un poste qui porte une instance OPSYS."
    fi
else
    NOM_SERVICE="$UNITE_ATTENDUE"
    if command -v systemctl >/dev/null 2>&1 && [ -n "$(systemctl --user list-unit-files --no-legend "$UNITE_ATTENDUE" 2>/dev/null || true)" ]; then
        echec "le service $UNITE_ATTENDUE existe déjà sur ce poste : ce script ne s'exécute pas sur un poste qui porte une instance OPSYS."
    fi
fi
constat "poste neuf ($SYSTEME) : aucun état du core d'OPSYS ($ETAT_CORE) ni service $NOM_SERVICE"

etape "0 bis. Décision préalable : un palier de modèles (comme après une restauration ou un premier réglage)"
mkdir -p "$OPSYS_HOME"
chmod 700 "$OPSYS_HOME"
printf 'paliers:\n  standard: {provider: anthropic, model: claude-sonnet-5}\n' >"$OPSYS_HOME/paliers.yaml"

# -- 1. Installation sans service ----------------------------------------------------------------------------------------
etape "1. Installation (sans service) : Node, pnpm, uv, construction du core, moteur, instance, configuration"
installer "$TRAVAIL/installation-1.log" --sans-service
if [ ! -x "$OPSYS_BIN/openclaw" ] || [ ! -x "$OPSYS_BIN/opsys" ]; then echec "les commandes openclaw et opsys ne sont pas installées"; fi
[ "$(mode_de "$ETAT_CORE/.env")" = "600" ] || echec ".env n'est pas en 0600"
[ "$(mode_de "$ETAT_CORE")" = "700" ] || echec "le dossier d'état du core n'est pas en 0700"
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
# Les ports de l'installation : sans eux, `initialiser` reviendrait aux ports par défaut et changerait la configuration.
if opsys instance initialiser --port-gateway "$PORT_GATEWAY" --port-moteur "$PORT_MOTEUR" >"$TRAVAIL/ancienne-disposition.json" 2>"$TRAVAIL/ancienne-disposition.err"; then
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
opsys instance initialiser --port-gateway "$PORT_GATEWAY" --port-moteur "$PORT_MOTEUR" >/dev/null
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
(cd "$TRAVAIL" && "${SHA256[@]}" -c export.tar.gz.sha256)
[ "$(mode_de "$TRAVAIL/export.tar.gz")" = "600" ] || echec "l'archive d'export n'est pas en 0600"
membres="$(tar -tzf "$TRAVAIL/export.tar.gz" | sort | tr '\n' ' ')"
[ "$membres" = "opsys-export/manifeste.json opsys-export/opsys.db opsys-export/paliers.yaml " ] ||
    echec "membres inattendus dans l'archive : $membres"
mkdir -p "$TRAVAIL/decompose"
tar -xzf "$TRAVAIL/export.tar.gz" -C "$TRAVAIL/decompose"
exiger_sans_secret "archive d'export" "$TRAVAIL"/decompose/opsys-export/*
grep -qF '"~/.openclaw-opsys/.env"' "$TRAVAIL/decompose/opsys-export/manifeste.json" ||
    echec "le manifeste ne nomme pas l'état du core (~/.openclaw-opsys) parmi les fichiers exclus"
! grep -qF "$HOME" "$TRAVAIL/decompose/opsys-export/manifeste.json" || echec "le manifeste porte le dossier personnel du poste"
constat "export : membres = liste blanche, SHA-256 vérifié (${SHA256[0]}), 0600, aucun secret de .env, état du core nommé parmi les exclus"
etat_avant_restauration="$(empreinte_des_fichiers_geres)"
OPSYS_HOME="$TRAVAIL/restaure" opsys instance restaurer "$TRAVAIL/export.tar.gz" >"$TRAVAIL/restauration.json"
OPSYS_HOME="$TRAVAIL/restaure" opsys base etat >"$TRAVAIL/restaure-etat.json"
grep -q '"revision"' "$TRAVAIL/restaure-etat.json" || echec "la base restaurée n'est pas lisible par opsys base etat"
[ ! -e "$TRAVAIL/restaure/core" ] || echec "la restauration a posé un dossier core (secrets) : elle ne doit restaurer que les données"
[ "$(empreinte_des_fichiers_geres)" = "$etat_avant_restauration" ] || echec "la restauration a touché l'état du core"
constat "restauration dans une instance neuve : base lisible, aucun secret ni état du Gateway restauré"

SERVICE_PROUVE="non"
etape "5. Service utilisateur ($NOM_SERVICE) : installation, démarrage, supervision du moteur"
if [ "${OPSYS_SANS_SERVICE:-0}" = "1" ]; then
    echo "::warning::phase du service sautée (OPSYS_SANS_SERVICE=1)"
    constat "service $NOM_SERVICE NON prouvé : phase sautée (OPSYS_SANS_SERVICE=1)"
elif service_disponible; then
    installer "$TRAVAIL/installation-3.log"
    case "$SYSTEME" in
        Darwin) verifier_service_launchd ;;
        *) verifier_service_systemd ;;
    esac
    SERVICE_PROUVE="oui"
elif [ "${OPSYS_SERVICE_REQUIS:-0}" = "1" ]; then
    echec "le service utilisateur est indisponible sur ce poste ($SYSTEME) et OPSYS_SERVICE_REQUIS=1 : $(raison_service_indisponible). Relancez avec sans_service=1 pour prouver le reste sans le service."
else
    if [ "$SYSTEME" = "Darwin" ]; then
        echo "::warning::launchd (gui/$(id -u)) est indisponible sur ce poste : le service n'est PAS prouvé ici (le Gateway l'a été au premier plan)"
        constat "service launchd NON prouvé : domaine gui/$(id -u) indisponible sur ce poste"
    else
        echo "::warning::systemd --user est indisponible sur ce poste : le service n'est PAS prouvé ici (le Gateway l'a été au premier plan)"
        constat "service systemd utilisateur NON prouvé : bus utilisateur indisponible sur ce poste"
    fi
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
(cd "$TRAVAIL" && "${SHA256[@]}" -c avant-desinstallation.tar.gz.sha256)
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
if ! python3 - "$OPSYS_HOME/opsys.db" <<'PYTHON'
import sqlite3, sys
connexion = sqlite3.connect(sys.argv[1])
assert connexion.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "base endommagée"
assert connexion.execute("SELECT count(*) FROM alembic_version").fetchone()[0] == 1, "base non migrée"
PYTHON
then
    echec "la base de données n'est pas intacte après la désinstallation (integrity_check ou alembic_version)"
fi
if [ "$SERVICE_PROUVE" = "oui" ]; then
    case "$SYSTEME" in
        Darwin)
            [ ! -e "$PLIST" ] || echec "le plist $PLIST est encore installé après la désinstallation"
            ! launchctl print "gui/$(id -u)/$ETIQUETTE_ATTENDUE" >/dev/null 2>&1 ||
                echec "$ETIQUETTE_ATTENDUE est encore chargé dans launchd après la désinstallation"
            ;;
        *)
            [ "$(systemctl --user list-unit-files --no-legend "$UNITE_ATTENDUE" | wc -l)" -eq 0 ] ||
                echec "l'unité du service est encore installée"
            ;;
    esac
    attendre_arret "http://127.0.0.1:$PORT_GATEWAY/startupz" 60 "le Gateway après la désinstallation"
    attendre_arret "http://127.0.0.1:$PORT_MOTEUR/sante" 60 "le moteur après la désinstallation"
fi
constat "désinstallation : service, logiciel et commandes retirés ; .env, configuration, réglages, base, état du core et ancien état mis de côté intacts ; export vérifié"
bash "$RACINE/install/uninstall.sh" >"$TRAVAIL/desinstallation-2.log" 2>&1 || echec "la désinstallation n'est pas relançable"
constat "la désinstallation est relançable"

# -- Résumé ---------------------------------------------------------------------------------------------------------------------------
etape "Tout est vrai"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        printf '### Installateur avec le vrai core (%s)\n\n' "$SYSTEME"
        printf -- '- %s\n' "${CONSTATS[@]}"
        printf '\nService utilisateur (%s) prouvé : **%s**\n' "$NOM_SERVICE" "$SERVICE_PROUVE"
    } >>"$GITHUB_STEP_SUMMARY"
fi
fin_groupe
