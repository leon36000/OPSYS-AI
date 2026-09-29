#!/usr/bin/env bash
# tests/installateur/diagnostic.sh : ce que la CI imprime après un échec de bout_en_bout.sh (Linux et macOS).
#
# Ce script ne fait rien d'autre que lire : il n'installe, ne démarre ni ne supprime rien, et il ne s'arrête jamais sur
# une commande en échec (un diagnostic partiel vaut mieux que pas de diagnostic).
#
# Aucun secret : les valeurs secrètes de <état du core>/.env (jetons, clés) sont d'abord déclarées au masque de GitHub
# (::add-mask::), puis remplacées par *** dans tout ce qui est imprimé, même hors de GitHub. Le contenu de .env n'est
# jamais imprimé, ni celui de fichiers qui portent des secrets : seulement des noms et des modes.
#
# Sortie : un groupe repliable (::group::) par sujet sous GitHub Actions, des titres « == sujet » ailleurs.
# Variables : OPSYS_TRAVAIL (dossier de travail de bout_en_bout.sh), OPSYS_LOGICIEL (défaut : <travail>/logiciel),
# OPSYS_PORT_GATEWAY, OPSYS_PORT_MOTEUR (défauts 18789 et 8765), HOME.
set -uo pipefail

SYSTEME="$(uname -s)"
TRAVAIL="${OPSYS_TRAVAIL:-}"
LOGICIEL="${OPSYS_LOGICIEL:-${TRAVAIL:+$TRAVAIL/logiciel}}"
ETAT_CORE="${HOME:-/nonexistent}/.openclaw-opsys"
PORT_GATEWAY="${OPSYS_PORT_GATEWAY:-18789}"
PORT_MOTEUR="${OPSYS_PORT_MOTEUR:-8765}"
LIGNES="${OPSYS_DIAGNOSTIC_LIGNES:-300}"
FILTRE=""
trap '[ -z "$FILTRE" ] || rm -f "$FILTRE"' EXIT

valeurs_secretes() {
    [ -f "$ETAT_CORE/.env" ] || return 0
    sed -n -E 's/^[[:space:]]*(export[[:space:]]+)?[A-Z0-9_]*(JETON|TOKEN|_CLE|SECRET|PASSWORD)[A-Z0-9_]*=(.{12,})$/\3/p' \
        "$ETAT_CORE/.env"
}

# Masque GitHub pour toutes les valeurs, et un script sed pour celles dont les caractères sont sûrs dans une
# expression régulière (les secrets de l'installateur : hexadécimal, sk-opsys-...).
preparer_masque() {
    local valeur
    FILTRE="$(mktemp "${TMPDIR:-/tmp}/opsys-diagnostic.XXXXXX")"
    chmod 600 "$FILTRE"
    while IFS= read -r valeur; do
        [ -n "$valeur" ] || continue
        echo "::add-mask::$valeur"
        case "$valeur" in
            *[!A-Za-z0-9._:/@%+=,~-]*) ;;
            *) printf 's#%s#***#g\n' "$valeur" >>"$FILTRE" ;;
        esac
    done < <(valeurs_secretes)
}

filtrer() {
    if [ -s "$FILTRE" ]; then LC_ALL=C sed -f "$FILTRE"; else cat; fi
}

sujet() {
    if [ -n "${GITHUB_ACTIONS:-}" ]; then printf '::group::%s\n' "$1"; else printf '\n== %s\n' "$1"; fi
}
fin_sujet() {
    if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::endgroup::"; fi
}

fin_du_fichier() { # fichier
    sujet "$1"
    tail -n "$LIGNES" "$1" 2>&1 | filtrer
    fin_sujet
}

# Les fichiers d'un dossier, sans leur contenu : mode et chemin.
noms_et_modes() { # dossier, profondeur
    case "$SYSTEME" in
        Darwin) find "$1" -maxdepth "$2" -exec stat -f '%Lp %N' {} + 2>&1 ;;
        *) find "$1" -maxdepth "$2" -printf '%m %p\n' 2>&1 ;;
    esac | head -n 100
}

preparer_masque

if [ -n "$TRAVAIL" ]; then
    for journal in "$TRAVAIL"/*.log "$TRAVAIL"/*.err "$TRAVAIL"/launchctl-*.txt; do
        [ -f "$journal" ] && fin_du_fichier "$journal"
    done
fi
if [ -n "$LOGICIEL" ]; then
    for journal in "$LOGICIEL"/journaux/*.log; do
        [ -f "$journal" ] && fin_du_fichier "$journal"
    done
fi

case "$SYSTEME" in
    Darwin)
        sujet "launchd : ai.openclaw.opsys (launchctl print)"
        launchctl print "gui/$(id -u)/ai.openclaw.opsys" 2>&1 | head -n 60 | filtrer
        fin_sujet
        sujet "launchd : services openclaw chargés"
        launchctl list 2>&1 | grep -i openclaw | filtrer
        fin_sujet
        sujet "LaunchAgents et journaux (noms et modes seulement)"
        noms_et_modes "$HOME/Library/LaunchAgents" 1
        noms_et_modes "$HOME/Library/Logs/openclaw" 1
        fin_sujet
        for journal in "$HOME"/Library/Logs/openclaw/*.log /tmp/openclaw/*.log; do
            [ -f "$journal" ] && fin_du_fichier "$journal"
        done
        ;;
    *)
        sujet "journal systemd de l'utilisateur"
        XDG_RUNTIME_DIR="/run/user/$(id -u)" journalctl --user --no-pager -n 200 2>&1 | filtrer
        fin_sujet
        sujet "unités systemd utilisateur (noms et modes seulement)"
        noms_et_modes "$HOME/.config/systemd/user" 1
        fin_sujet
        ;;
esac

# L'état du core : les noms et les modes seulement, jamais le contenu (.env : secrets en clair).
sujet "état du core ($ETAT_CORE : noms et modes seulement)"
noms_et_modes "$ETAT_CORE" 3
fin_sujet

sujet "santé du Gateway et du moteur"
for url in "http://127.0.0.1:$PORT_GATEWAY/startupz" "http://127.0.0.1:$PORT_MOTEUR/sante"; do
    printf '%s -> %s\n' "$url" "$(curl -sS --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "$url" 2>&1)"
done
fin_sujet

sujet "processus node et python (noms seulement)"
# pgrep n'affiche pas les mêmes colonnes sous BSD et sous GNU : on filtre la sortie de ps.
# shellcheck disable=SC2009
ps -Ao pid,ppid,etime,comm 2>&1 | grep -E 'PID|node|python|uv' | head -n 30
fin_sujet
exit 0
