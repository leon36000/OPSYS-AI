#!/usr/bin/env bash
# install/uninstall.sh : retire OPSYS (service, commandes, logiciel) sur Linux ou macOS SANS toucher aux données.
#
#   install/uninstall.sh [--exporter-avant ARCHIVE.tar.gz] [--simuler]
#
# Ce que fait ce script :
#   1. avec --exporter-avant : archive d'abord l'instance (`opsys instance exporter`, empreinte SHA-256 incluse) ; si
#      l'export échoue, RIEN n'est retiré ;
#   2. arrête et retire le service du Gateway (`openclaw gateway uninstall`), si l'installateur l'avait installé ;
#   3. retire les commandes `openclaw` et `opsys` de OPSYS_BIN (seulement celles que l'installateur a écrites) ;
#   4. retire le logiciel : environnement Python, journal, et le clone géré par l'installateur. Un dépôt à vous
#      (OPSYS_SOURCE, ou celui d'où vous avez lancé l'installateur) n'est jamais touché.
#
# Ce script ne supprime JAMAIS les données de l'instance ($OPSYS_HOME : base, réglages, secrets, état du Gateway).
# La suppression définitive est une décision humaine, hors de ce script (docs/exploitation/INSTALLATION.md).
# Il est relançable : retirer ce qui est déjà retiré ne fait rien.
#
# Variables : OPSYS_HOME, OPSYS_LOGICIEL, OPSYS_BIN (mêmes défauts que l'installateur ; à défaut, la dernière
# installation, lue dans $OPSYS_LOGICIEL/installation.env).
# Code de sortie : 0 fait ; 1 arrêté avant de retirer quoi que ce soit d'irréversible, avec quoi faire.
set -euo pipefail

MARQUE='# OPSYS-INSTALLATEUR : fichier géré par install.sh, réécrit à chaque installation. Ne pas éditer.'
SIMULER=0
ARCHIVE=""
ENR_OPSYS_HOME=""
ENR_OPSYS_BIN=""
ENR_SOURCE=""
ENR_SOURCE_GEREE="0"
ENR_SERVICE="0"

info() { printf '[opsys] %s\n' "$*"; }
avertir() { printf '[opsys] AVERTISSEMENT : %s\n' "$*" >&2; }
die() {
    printf '[opsys] ERREUR : %s\n' "$*" >&2
    exit 1
}

usage() {
    printf '%s\n' \
        "uninstall.sh : retire OPSYS sans supprimer les données de l'instance." \
        "" \
        "Options : --exporter-avant ARCHIVE.tar.gz   --simuler   --aide" \
        "Variables : OPSYS_HOME, OPSYS_LOGICIEL, OPSYS_BIN" \
        "Détail complet : docs/exploitation/INSTALLATION.md et l'en-tête de ce script."
}

# Lit un fichier KEY=VALUE sans jamais l'évaluer : ne pose dans ENR_<CLE> que les clés connues.
lire_enregistrement() {
    local fichier="$1" cle valeur
    [ -f "$fichier" ] || return 0
    while IFS='=' read -r cle valeur || [ -n "$cle" ]; do
        case "$cle" in
            SOURCE | SOURCE_GEREE | SERVICE | OPSYS_HOME | OPSYS_BIN) printf -v "ENR_$cle" '%s' "$valeur" ;;
            *) ;;
        esac
    done <"$fichier"
}

chemin_absolu() {
    case "$2" in
        /*) ;;
        *) die "$1 doit être un chemin absolu (reçu : $2)." ;;
    esac
}

analyser_arguments() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --exporter-avant)
                [ "$#" -ge 2 ] || die "--exporter-avant demande le chemin de l'archive."
                ARCHIVE="$2"
                shift
                ;;
            --simuler) SIMULER=1 ;;
            --aide | -h | --help)
                usage
                exit 0
                ;;
            *) die "option inconnue : $1 (voir --aide)." ;;
        esac
        shift
    done
}

resoudre_chemins() {
    : "${HOME:?HOME est indéfini}"
    OPSYS_LOGICIEL="${OPSYS_LOGICIEL:-${XDG_DATA_HOME:-$HOME/.local/share}/opsys}"
    chemin_absolu OPSYS_LOGICIEL "$OPSYS_LOGICIEL"
    lire_enregistrement "$OPSYS_LOGICIEL/installation.env"
    OPSYS_HOME="${OPSYS_HOME:-${ENR_OPSYS_HOME:-$HOME/.opsys}}"
    OPSYS_BIN="${OPSYS_BIN:-${ENR_OPSYS_BIN:-$HOME/.local/bin}}"
    chemin_absolu OPSYS_HOME "$OPSYS_HOME"
    chemin_absolu OPSYS_BIN "$OPSYS_BIN"
    VENV="$OPSYS_LOGICIEL/venv"
    VENV_PY="$VENV/bin/python"
}

# agir "ce que l'on fait" commande [arguments...] : en simulation, dit ce qui serait fait.
agir() {
    local libelle="$1"
    shift
    if [ "$SIMULER" -eq 1 ]; then
        info "[simulation] $libelle"
        return 0
    fi
    info "$libelle"
    "$@"
}

# Un dossier qui est ou contient les données de l'instance, la racine ou le dossier personnel ne se supprime jamais.
garde_dossier() {
    local dossier="${1%/}"
    case "$dossier" in
        '' | "$HOME" | "$OPSYS_HOME") die "refus de supprimer '$dossier' : c'est le dossier personnel ou celui des données. Rien n'a été retiré." ;;
        *) ;;
    esac
    case "$OPSYS_HOME/" in
        "$dossier"/*) die "refus de supprimer '$dossier' : il contient les données de l'instance ($OPSYS_HOME). Rien n'a été retiré." ;;
        *) ;;
    esac
}

supprimer_dossier() {
    local dossier="${1%/}"
    garde_dossier "$dossier"
    if [ -e "$dossier" ] || [ -L "$dossier" ]; then
        agir "suppression de $dossier" rm -rf -- "$dossier"
    fi
}

dossiers_du_logiciel() {
    printf '%s\n' "$VENV" "$OPSYS_LOGICIEL/journaux"
    if [ "$ENR_SOURCE_GEREE" = "1" ] && [ "$ENR_SOURCE" = "$OPSYS_LOGICIEL/source" ]; then
        printf '%s\n' "$OPSYS_LOGICIEL/source"
    fi
}

verifier_gardes() {
    local dossier
    while IFS= read -r dossier; do
        garde_dossier "$dossier"
    done < <(dossiers_du_logiciel)
}

exporter_avant() {
    [ -n "$ARCHIVE" ] || return 0
    [ -x "$VENV_PY" ] || die "l'export demandé est impossible : l'environnement Python ($VENV_PY) est introuvable. Rien n'a été retiré."
    [ -f "$OPSYS_HOME/opsys.db" ] || die "l'export demandé est impossible : aucune base dans $OPSYS_HOME. Rien n'a été retiré."
    case "$ARCHIVE" in
        /*) ;;
        *) ARCHIVE="$PWD/$ARCHIVE" ;;
    esac
    if [ "$SIMULER" -eq 1 ]; then
        info "[simulation] export de l'instance vers $ARCHIVE"
        return 0
    fi
    info "export de l'instance vers $ARCHIVE..."
    OPSYS_HOME="$OPSYS_HOME" "$VENV_PY" -m opsys.cli instance exporter --sortie "$ARCHIVE" --par "poste:desinstallation" >/dev/null </dev/null ||
        die "l'export a échoué : RIEN n'a été retiré. Corrigez la cause (message ci-dessus), puis relancez."
    if [ ! -f "$ARCHIVE" ] || [ ! -f "$ARCHIVE.sha256" ]; then
        die "l'export n'a pas produit l'archive et son empreinte : RIEN n'a été retiré."
    fi
    info "export terminé : $ARCHIVE (empreinte : $ARCHIVE.sha256). Protégez-le : il contient des renseignements personnels."
}

retirer_service() {
    [ "$ENR_SERVICE" = "1" ] || {
        info "aucun service installé par l'installateur : rien à arrêter."
        return 0
    }
    local coeur="$ENR_SOURCE/core/openclaw.mjs" etat="${OPENCLAW_STATE_DIR:-$OPSYS_HOME/core}"
    if [ ! -f "$coeur" ] || ! command -v node >/dev/null 2>&1; then
        die "le service est installé mais le core ($coeur) ou Node est introuvable : impossible de le retirer proprement. Arrêtez-le à la main (Linux : systemctl --user disable --now openclaw-gateway ; macOS : launchctl bootout gui/\$(id -u)/ai.openclaw.gateway), puis relancez. Rien n'a été retiré."
    fi
    agir "arrêt et retrait du service du Gateway" env OPSYS_HOME="$OPSYS_HOME" OPENCLAW_STATE_DIR="$etat" node "$coeur" gateway uninstall </dev/null ||
        die "le service n'a pas pu être retiré (message ci-dessus). Rien d'autre n'a été retiré : corrigez, puis relancez."
}

retirer_commandes() {
    local cible
    for cible in "$OPSYS_BIN/openclaw" "$OPSYS_BIN/opsys"; do
        if [ -e "$cible" ]; then
            if grep -qF "$MARQUE" "$cible" 2>/dev/null; then
                agir "suppression de la commande $cible" rm -f -- "$cible"
            else
                avertir "$cible n'a pas été installé par OPSYS : laissé en place."
            fi
        fi
    done
}

retirer_logiciel() {
    supprimer_dossier "$VENV"
    supprimer_dossier "$OPSYS_LOGICIEL/journaux"
    if [ "$ENR_SOURCE_GEREE" = "1" ] && [ "$ENR_SOURCE" = "$OPSYS_LOGICIEL/source" ]; then
        supprimer_dossier "$OPSYS_LOGICIEL/source"
    elif [ -n "$ENR_SOURCE" ]; then
        info "le dépôt $ENR_SOURCE n'est pas géré par l'installateur : laissé en place."
    fi
    if [ -f "$OPSYS_LOGICIEL/installation.env" ]; then
        agir "suppression de l'enregistrement de l'installation" rm -f -- "$OPSYS_LOGICIEL/installation.env"
    fi
    if [ "$SIMULER" -eq 0 ] && [ -d "$OPSYS_LOGICIEL" ]; then
        rmdir "$OPSYS_LOGICIEL" 2>/dev/null || avertir "$OPSYS_LOGICIEL contient encore des fichiers qui ne sont pas à l'installateur : laissé en place."
    fi
}

main() {
    analyser_arguments "$@"
    resoudre_chemins
    info "désinstallation d'OPSYS (données conservées : $OPSYS_HOME)"
    verifier_gardes
    exporter_avant
    retirer_service
    retirer_commandes
    retirer_logiciel
    printf '\n%s\n' "OPSYS est retiré."
    printf '  %s\n' "Données conservées : $OPSYS_HOME (base, réglages, secrets .env, état du Gateway)."
    if [ -z "$ARCHIVE" ]; then
        printf '  %s\n' "Aucun export demandé (--exporter-avant). Pour en faire un maintenant : réinstallez OPSYS, puis opsys instance exporter."
    fi
    printf '  %s\n' "Les supprimer définitivement est une décision humaine : voir docs/exploitation/INSTALLATION.md."
}

main "$@"
