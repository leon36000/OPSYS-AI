#!/usr/bin/env bash
# install/install.sh : installe OPSYS (OPSYS-CORE + moteur métier) sur Linux ou macOS, en une commande.
#
#   git clone https://github.com/leon36000/OPSYS-AI && OPSYS-AI/install/install.sh
#   curl -fsSL <URL de ce script> | bash -s -- [options]      (une fois le script publié : décision humaine, T3)
#
# Ce que fait ce script, dans l'ordre. Chaque étape échoue franchement, avec quoi faire, et arrête tout.
#   1. vérifie les prérequis : Node aux versions du fork, uv (qui fournit Python 3.11+), git (installation à distance)
#   2. prépare le code : dépôt voisin ou OPSYS_SOURCE tel quel ; sinon clone de OPSYS_REPO_URL à OPSYS_REF
#   3. construit OPSYS-CORE (pnpm à la version que fixe core/package.json) et installe le moteur Python par uv
#   4. `opsys metier instance initialiser` : dossiers privés, base migrée, secrets dans <état du core>/.env (0600,
#      jamais régénérés, jamais affichés), configuration du core, superviseur du moteur et commande de sa CLI
#      (opsys/metier.json)
#   5. vérifie que le core lit bien son état où l'on vient de le préparer (`opsys config file`), `opsys config
#      validate`, puis service utilisateur du Gateway (`opsys gateway install` : systemd --user, launchd), qui
#      supervise le moteur ; attend que le Gateway et le moteur répondent
#
# Le core tourne sous son profil « opsys » (PLAN T0.11-b) : toute commande du core passe `--profile opsys`, jamais
# OPENCLAW_STATE_DIR, OPENCLAW_CONFIG_PATH ni OPENCLAW_HOME. Son état est alors le dossier canonique du profil
# (~/.opsys/core depuis T0.7 lot 3 ; avant, ~/.openclaw-opsys), le seul pour lequel le core accepte d'installer un
# service (core/src/config/paths.ts, isDefaultInstallIdentity), et le service porte un nom distinct de celui du core
# d'origine (Linux : openclaw-gateway-opsys ; macOS : ai.openclaw.opsys). `opsys metier instance dossier` donne ce
# dossier, `opsys metier instance fichier-config` la configuration qu'il porte (opsys.json, ou l'openclaw.json d'une
# installation antérieure, lu en place et jamais renommé). Une installation faite avec l'ancienne disposition
# ($OPSYS_HOME/core) ou dont l'état est resté dans ~/.openclaw-opsys est refusée avec la marche à suivre, jamais
# migrée en silence par ce script : le déplacement est celui de Doctor (opsys doctor --non-interactive), puis on
# relance ce script, qui réinstalle aussi le service vers le nouvel emplacement.
#
# Pourquoi construire depuis le dépôt et non installer une archive : aucune version n'est publiée (la publication est
# une décision humaine, T3), et le paquet npm `openclaw` est le logiciel d'origine, pas ce fork. Le code du core et
# celui du moteur (qui lit `departments/` dans le dépôt) doivent aussi venir du même commit.
#
# Relançable sans rien casser : c'est aussi la mise à jour. Un secret existant n'est jamais régénéré, les données de
# l'instance ne sont jamais touchées, le Gateway est redémarré.
#
# Options
#   --sans-service   n'installe pas le service (démarrage à la main : `opsys gateway run`)
#   --avec-ingestion-pdf / --sans-ingestion-pdf  choix conservé ; PDF natif Linux non-root, bwrap requis
#   --source CHEMIN  utilise ce dépôt tel quel, sans clone (comme OPSYS_SOURCE)
#   --ref REF        branche, étiquette ou commit à installer (comme OPSYS_REF ; défaut : main)
#   --aide
# Variables d'environnement
#   OPSYS_HOME       données de l'instance (base, paliers, profil d'entreprise), jamais supprimées par la désinstallation
#                    (défaut : ~/.opsys). L'état du core est ailleurs (voir plus haut), et lui non plus n'est jamais supprimé.
#   OPSYS_LOGICIEL   logiciel : clone, environnement Python, journal (défaut : ~/.local/share/opsys)
#   OPSYS_BIN        commandes `opsys` (le core), `openclaw` (son alias) et `opsys-metier` (le moteur métier ; `opsys metier
#                    <commande>` le lance depuis le core) (défaut : ~/.local/bin)
#   OPSYS_SOURCE, OPSYS_REPO_URL, OPSYS_REF     provenance du code (voir plus haut)
#   OPSYS_PORT_GATEWAY (défaut : 18789), OPSYS_PORT_MOTEUR (défaut : 8765)
#   OPSYS_EMBEDDINGS_URL, OPSYS_EMBEDDINGS_MODELE, OPSYS_EMBEDDINGS_CLE   service d'embeddings (gardés dans .env)
#   OPSYS_MODE_FOURNISSEUR  natif (défaut) ou litellm (compatibilité explicite)
#   OPSYS_PASSERELLE_URL   URL LiteLLM, utilisée seulement si OPSYS_MODE_FOURNISSEUR=litellm
#   OPSYS_VERBOSE=1  affiche aussi la sortie des étapes (elle va toujours au journal)
#   OPSYS_INGESTION_ENV_FILE  chemin absolu du fichier privé existant de clés AES (jamais lu par bash ni exporté au core)
#
# Code de sortie : 0 tout est prêt ; 1 une étape a échoué ; 3 installé mais il manque une décision (paliers de modèles,
# service d'embeddings) : le message dit quoi fournir, puis on relance la même commande.
#
# Tout le script est dans des fonctions, appelées à la dernière ligne : sous `curl | bash`, bash n'exécute rien avant
# d'avoir lu tout le texte, et aucune commande lancée ici ne peut avaler la suite du script sur l'entrée standard.
# Compatible bash 3.2 (macOS) : ni tableau associatif, ni mapfile.
set -euo pipefail

MARQUE='# OPSYS-INSTALLATEUR : fichier géré par install.sh, réécrit à chaque installation. Ne pas éditer.'
CODE_EN_ATTENTE=3
# Profil du core (recopié de instance.PROFIL_CORE ; tests/test_installateur_scripts.py vérifie l'accord) et variables
# qui sortiraient l'état du dossier canonique ou changeraient l'identité du service (instance.VARIABLES_ECARTEES).
PROFIL_CORE="opsys"
VARIABLES_ECARTEES=(OPENCLAW_STATE_DIR OPENCLAW_CONFIG_PATH OPENCLAW_HOME OPENCLAW_PROFILE OPENCLAW_LAUNCHD_LABEL
    OPENCLAW_SYSTEMD_UNIT OPENCLAW_WINDOWS_TASK_NAME)
NETTOYAGE=()
JOURNAL=""
FICHIER_MASQUE=""
PNPM=()
PNPM_DIR=""
SOURCE=""
SOURCE_GEREE=0
SOURCE_COMMIT="inconnu"
GENERATION=""
GENERATION_SQLITE_HELPER_SHA=""
PREPARER_GENERATION=0
PUBLIER_GENERATION=""
SERVICE_INSTALLE=0
NODE=""
VENV=""
VENV_PY=""
MOTEUR_PY=""
AVEC_SERVICE=1
EN_ATTENTE=0
PORT_GATEWAY=""
PORT_MOTEUR=""
DOSSIER_CORE=""
MODE_FOURNISSEUR="natif"
INGESTION_PDF=0
CHOIX_INGESTION_PDF=""
FICHIER_INGESTION=""
CONFIGURER_PDF=0

info() { printf '[opsys] %s\n' "$*"; }
avertir() { printf '[opsys] AVERTISSEMENT : %s\n' "$*" >&2; }
die() {
    printf '[opsys] ERREUR : %s\n' "$*" >&2
    exit 1
}

nettoyer() {
    local f
    for f in ${NETTOYAGE[@]+"${NETTOYAGE[@]}"}; do
        rm -rf "$f"
    done
}

usage() {
    printf '%s\n' \
        "install.sh : installe OPSYS (OPSYS-CORE + moteur métier) sur Linux ou macOS." \
        "" \
        "Options : --sans-service   --source CHEMIN   --ref REF   --aide" \
        "  --preparer-generation : prépare seulement une génération privée, sans publication ni instance" \
        "  --publier-generation CHEMIN : publie le runtime d’une instance déjà initialisée, Gateway hors ligne ; --source Core construit local requis" \
        "  --avec-ingestion-pdf / --sans-ingestion-pdf (choix persistant, défaut désactivé)" \
        "Variables : OPSYS_HOME, OPSYS_LOGICIEL, OPSYS_BIN, OPSYS_SOURCE, OPSYS_REPO_URL, OPSYS_REF," \
        "  OPSYS_PORT_GATEWAY, OPSYS_PORT_MOTEUR, OPSYS_EMBEDDINGS_URL, OPSYS_EMBEDDINGS_MODELE," \
        "  OPSYS_EMBEDDINGS_CLE, OPSYS_MODE_FOURNISSEUR, OPSYS_PASSERELLE_URL, OPSYS_VERBOSE" \
        "  OPSYS_INGESTION_ENV_FILE : chemin seul, fichier opérateur 0600 dans un dossier 0700" \
        "Code de sortie : 0 prêt, 1 échec d'une étape, 3 installé mais il manque une décision." \
        "Détail complet : docs/exploitation/INSTALLATION.md et l'en-tête de ce script."
}

# -- Journal et masquage des secrets ---------------------------------------------------------------------------------
# La sortie de chaque étape va au journal ; tout ce qui ressemble à la valeur d'un secret de .env y est remplacé par ***
# avant d'être écrit ou affiché. Aucune étape n'imprime un secret : ceci est la seconde barrière.
preparer_masque() {
    local env_file="$DOSSIER_CORE/.env"
    [ -n "$DOSSIER_CORE" ] && [ -f "$env_file" ] || return 0
    if [ -z "$FICHIER_MASQUE" ]; then
        FICHIER_MASQUE="$(mktemp "${TMPDIR:-/tmp}/opsys-masque.XXXXXX")"
        NETTOYAGE+=("$FICHIER_MASQUE")
        chmod 600 "$FICHIER_MASQUE"
    fi
    awk 'BEGIN { FS = "=" }
        /^[[:space:]]*#/ { next }
        {
            nom = $1
            sub(/^[[:space:]]*(export[[:space:]]+)?/, "", nom)
            if (nom !~ /(JETON|TOKEN|_CLE|SECRET|PASSWORD)/) next
            valeur = substr($0, index($0, "=") + 1)
            if (length(valeur) >= 12 && valeur ~ "^[A-Za-z0-9._:/@%+=,~-]+$") print "s#" valeur "#***#g"
        }' "$env_file" >"$FICHIER_MASQUE"
}

filtrer_secrets() {
    if [ -n "$FICHIER_MASQUE" ] && [ -s "$FICHIER_MASQUE" ]; then
        LC_ALL=C sed -f "$FICHIER_MASQUE"
    else
        cat
    fi
}

ouvrir_journal() {
    mkdir -p "$OPSYS_LOGICIEL/journaux"
    chmod 700 "$OPSYS_LOGICIEL/journaux"
    JOURNAL="$OPSYS_LOGICIEL/journaux/installation.log"
    (umask 077 && : >"$JOURNAL")
    preparer_masque
}

# etape "libellé" commande [arguments...] : la commande s'exécute sans entrée standard, sortie au journal (masquée).
# Si elle échoue : fin du journal, puis arrêt, avec CONSEIL si l'appelant l'a fourni.
etape() {
    local libelle="$1" statut=0
    shift
    info "$libelle..."
    printf '\n== %s\n' "$libelle" >>"$JOURNAL"
    if [ "${OPSYS_VERBOSE:-0}" = "1" ]; then
        "$@" </dev/null 2>&1 | filtrer_secrets | tee -a "$JOURNAL" || statut="${PIPESTATUS[0]}"
    else
        "$@" </dev/null 2>&1 | filtrer_secrets >>"$JOURNAL" || statut="${PIPESTATUS[0]}"
    fi
    if [ "$statut" -ne 0 ]; then
        [ "${OPSYS_VERBOSE:-0}" = "1" ] || tail -n 40 "$JOURNAL" >&2
        die "$libelle : échec (code $statut). Journal complet : $JOURNAL. ${CONSEIL:-}"
    fi
}

# -- Configuration -----------------------------------------------------------------------------------------------------
# Lit un fichier KEY=VALUE sans jamais l'évaluer : ne pose dans ENR_<CLE> que les clés connues.
lire_enregistrement() {
    local fichier="$1" cle valeur
    [ -f "$fichier" ] || return 0
    while IFS='=' read -r cle valeur || [ -n "$cle" ]; do
        case "$cle" in
            PORT_GATEWAY | PORT_MOTEUR | DOSSIER_CORE | OPSYS_HOME | OPSYS_BIN | INGESTION_PDF | INGESTION_ENV_FILE)
                printf -v "ENR_$cle" '%s' "$valeur" ;;
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

verifier_port() {
    case "$2" in
        '' | *[!0-9]*) die "$1 : '$2' n'est pas un numéro de port." ;;
        *) if [ "$2" -lt 1 ] || [ "$2" -gt 65535 ]; then die "$1 : $2 n'est pas un port (1 à 65535)."; fi ;;
    esac
}

analyser_arguments() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --sans-service) AVEC_SERVICE=0 ;;
            --avec-ingestion-pdf | --sans-ingestion-pdf)
                local choix=0
                if [ "$1" = "--avec-ingestion-pdf" ]; then choix=1; fi
                [ -z "$CHOIX_INGESTION_PDF" ] || [ "$CHOIX_INGESTION_PDF" = "$choix" ] ||
                    die "options PDF contradictoires : choisissez --avec-ingestion-pdf ou --sans-ingestion-pdf."
                CHOIX_INGESTION_PDF="$choix"
                ;;
            --source)
                [ "$#" -ge 2 ] || die "--source demande un chemin."
                OPSYS_SOURCE="$2"
                shift
                ;;
            --ref)
                [ "$#" -ge 2 ] || die "--ref demande une référence."
                OPSYS_REF="$2"
                shift
                ;;
            --preparer-generation)
                PREPARER_GENERATION=1
                ;;
            --publier-generation)
                [ "$#" -ge 2 ] || die "--publier-generation exige le chemin d’une génération préparée."
                PUBLIER_GENERATION="$2"
                shift
                ;;
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
    OPSYS_HOME="${OPSYS_HOME:-$HOME/.opsys}"
    OPSYS_LOGICIEL="${OPSYS_LOGICIEL:-${XDG_DATA_HOME:-$HOME/.local/share}/opsys}"
    OPSYS_BIN="${OPSYS_BIN:-$HOME/.local/bin}"
    chemin_absolu OPSYS_HOME "$OPSYS_HOME"
    chemin_absolu OPSYS_LOGICIEL "$OPSYS_LOGICIEL"
    chemin_absolu OPSYS_BIN "$OPSYS_BIN"
    if [ -n "$OPSYS_SOURCE" ]; then
        chemin_absolu OPSYS_SOURCE "$OPSYS_SOURCE"
    fi
    VENV="$OPSYS_LOGICIEL/venv"
    VENV_PY="$VENV/bin/python"
    MOTEUR_PY="$VENV_PY"

    # Ports : la variable, sinon la valeur de la dernière installation, sinon la valeur par défaut du logiciel.
    # Le dossier d'état du core noté par la dernière installation ne sert qu'à masquer ses secrets dès l'ouverture du
    # journal ; il est redéterminé (par le moteur Python) avant toute écriture.
    local ENR_PORT_GATEWAY="" ENR_PORT_MOTEUR="" ENR_DOSSIER_CORE="" ENR_INGESTION_PDF="" ENR_INGESTION_ENV_FILE=""
    lire_enregistrement "$OPSYS_LOGICIEL/installation.env"
    DOSSIER_CORE="$ENR_DOSSIER_CORE"
    PORT_GATEWAY="${OPSYS_PORT_GATEWAY:-$ENR_PORT_GATEWAY}"
    PORT_MOTEUR="${OPSYS_PORT_MOTEUR:-$ENR_PORT_MOTEUR}"
    if [ -n "$PORT_GATEWAY" ]; then verifier_port OPSYS_PORT_GATEWAY "$PORT_GATEWAY"; fi
    if [ -n "$PORT_MOTEUR" ]; then verifier_port OPSYS_PORT_MOTEUR "$PORT_MOTEUR"; fi
    case "$ENR_INGESTION_PDF" in '' | 0 | 1) ;; *) die "choix PDF enregistré invalide : installation interrompue." ;; esac
    INGESTION_PDF="${CHOIX_INGESTION_PDF:-${ENR_INGESTION_PDF:-0}}"
    FICHIER_INGESTION="${OPSYS_INGESTION_ENV_FILE:-$ENR_INGESTION_ENV_FILE}"
    if [ "$INGESTION_PDF" -eq 1 ] || [ -n "$CHOIX_INGESTION_PDF" ] || [ "$ENR_INGESTION_PDF" = 1 ]; then
        CONFIGURER_PDF=1
    fi
    if [ "$CHOIX_INGESTION_PDF" = 0 ]; then
        FICHIER_INGESTION=""  # Désactivation du raccord, jamais suppression du fichier opérateur.
    elif [ "$INGESTION_PDF" -eq 0 ] && [ -n "$FICHIER_INGESTION" ]; then
        die "un chemin de clés seul n'active pas PDF : choisissez explicitement --avec-ingestion-pdf."
    fi
    if [ -n "$FICHIER_INGESTION" ]; then
        case "$FICHIER_INGESTION" in
            /*) ;;
            *) die "OPSYS_INGESTION_ENV_FILE doit être un chemin absolu ; valeur non affichée." ;;
        esac
        case "$FICHIER_INGESTION" in
            *$'\n'* | *$'\r'*) die "chemin de clés invalide ; valeur non affichée." ;;
        esac
    fi
    unset OPSYS_INGESTION_ENV_FILE  # Seul le moteur recevra le chemin ; aucune clé n'est chargée ici.
}

# -- 1. Prérequis --------------------------------------------------------------------------------------------------------
verifier_prerequis() {
    if [ "$INGESTION_PDF" -eq 1 ]; then
        [ "$(uname -s)" = Linux ] || die "PDF natif exige Linux ; aucune isolation de remplacement n'est utilisée."
        [ "$(id -u)" -ne 0 ] || die "PDF natif exige un compte non-root ; relancez avec ce compte."
        command -v bwrap >/dev/null 2>&1 || die "PDF natif exige bubblewrap (bwrap), à installer avec votre gestionnaire de paquets."
        local nom
        while IFS= read -r nom; do
            case "$nom" in
                OPSYS_INGESTION_CLE_REFERENCE | OPSYS_INGESTION_CLES_HISTORIQUES) ;;
                OPSYS_INGESTION_CLE | OPSYS_INGESTION_CLE_* | OPSYS_CLE_INGESTION_* | OPSYS_CLE_PDF_* | OPSYS_CLE_CSV_*)
                    [ -z "${!nom}" ] || die "clé d'ingestion dans l'environnement global refusée : utilisez le fichier privé, sans exporter ses clés."
                    ;;
            esac
        done < <(compgen -e)
    fi
    case "$(uname -s)" in
        Linux | Darwin) ;;
        *) die "système non pris en charge ($(uname -s)) : Linux et macOS ici, Windows par install/install.ps1." ;;
    esac
    if [ "$(id -u)" -eq 0 ]; then
        avertir "lancé en root : le service du Gateway est un service utilisateur, installé pour ce compte seulement."
    fi
    command -v node >/dev/null 2>&1 ||
        die "Node.js est introuvable. Installez Node 24.16+ ou 26.1+ (https://nodejs.org/), puis relancez cette commande."
    command -v uv >/dev/null 2>&1 ||
        die "uv est introuvable (il installe le moteur Python 3.11+). Installez-le : curl -LsSf https://astral.sh/uv/install.sh | sh (ou https://docs.astral.sh/uv/), puis relancez."
    command -v curl >/dev/null 2>&1 || die "curl est introuvable (sondes de santé). Installez-le avec le gestionnaire de paquets du système."
    command -v docker >/dev/null 2>&1 ||
        die "Docker CLI est introuvable. Installez Docker Engine ou Docker Desktop avec le moteur Linux, puis relancez."
    local systeme_docker
    if ! systeme_docker="$(docker info --format '{{.OSType}}' 2>/dev/null)"; then
        die "daemon Docker inaccessible. Démarrez Docker et vérifiez que votre compte peut exécuter 'docker info', puis relancez; aucun droit ni groupe ne sera modifié par OPSYS."
    fi
    [ "$systeme_docker" = "linux" ] ||
        die "le daemon Docker doit utiliser des conteneurs Linux (docker info a retourné '$systeme_docker'). Basculez Docker Desktop en mode Linux, puis relancez."
    NODE="$(command -v node)"
}

preparer_image_sandbox() {
    local image="openclaw-sandbox:bookworm-slim" script="$SOURCE/core/scripts/sandbox-setup.sh"
    if docker image inspect "$image" >/dev/null 2>&1; then
        info "Image sandbox existante réutilisée : $image"
        return 0
    fi
    [ -f "$script" ] || die "le code source ne contient pas le constructeur d'image sandbox attendu : $script. Vérifiez OPSYS_SOURCE."
    CONSEIL="L'image absente est construite depuis le Dockerfile OPSYS (base Debian épinglée); vérifiez le réseau du daemon Docker vers son registre et l'espace disque, puis relancez. OPSYS ne tire aucun tag d'image arbitraire." \
        etape "Construction de l'image sandbox $image" env OPENCLAW_SANDBOX_IMAGE="$image" bash "$script"
    docker image inspect "$image" >/dev/null 2>&1 ||
        die "le build s'est terminé mais l'image sandbox $image reste absente; aucun Gateway ne sera démarré."
}

verifier_mode_fournisseur() {
    local mode="${OPSYS_MODE_FOURNISSEUR:-natif}"
    case "$mode" in
        natif)
            [ -z "${OPSYS_PASSERELLE_URL:-}" ] ||
                die "OPSYS_PASSERELLE_URL seul n'active pas LiteLLM : choisissez explicitement OPSYS_MODE_FOURNISSEUR=litellm."
            ;;
        litellm)
            [ -n "${OPSYS_PASSERELLE_URL:-}" ] ||
                die "le mode litellm exige OPSYS_PASSERELLE_URL ; aucun service externe n'est installé par ce script."
            ;;
        *) die "OPSYS_MODE_FOURNISSEUR doit valoir natif ou litellm." ;;
    esac
}

# Il n'y a plus de garde « ne jamais écraser le service d'une autre installation d'OpenClaw » : sous le profil « opsys »,
# le service porte un nom qui n'est pas celui du core d'origine (core/src/daemon/constants.ts : openclaw-gateway-opsys,
# ai.openclaw.opsys, « OpenClaw Gateway (opsys) »), et `gateway install --force` ne remplace que le service de son profil.

# Le contrôle qui fait foi est celui du fork lui-même (core/node-version.mjs), lu une fois le code en place.
verifier_version_node() {
    local version
    version="$(node -v)"
    OPSYS_NODE_VERSION_MJS="$SOURCE/core/node-version.mjs" node --input-type=module -e '
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.env.OPSYS_NODE_VERSION_MJS).href);
process.exit(m.isSupportedOpenClawNodeVersion(process.versions.node) ? 0 : 1);
' </dev/null >/dev/null 2>&1 ||
        die "Node $version n'est pas pris en charge par ce core : il faut Node 24.16+ (24.x) ou 26.1+. Changez de Node (nvm, https://nodejs.org/), puis relancez."
}

# -- 2. Le code --------------------------------------------------------------------------------------------------------
detecter_depot_voisin() {
    local src="${BASH_SOURCE[0]:-}" dir
    [ -n "$src" ] && [ -f "$src" ] || return 1
    dir="$(cd "$(dirname "$src")/.." 2>/dev/null && pwd -P)" || return 1
    [ -f "$dir/core/openclaw.mjs" ] && [ -f "$dir/pyproject.toml" ] || return 1
    printf '%s\n' "$dir"
}

git_installation() {
    GIT_TERMINAL_PROMPT=0 git "$@"
}

resoudre_ref() {
    local depot="$1" ref="$2" commit candidat
    for candidat in "origin/$ref" "refs/tags/$ref" "$ref"; do
        if commit="$(git -C "$depot" rev-parse --verify --quiet "$candidat^{commit}")"; then
            printf '%s\n' "$commit"
            return 0
        fi
    done
    return 1
}

cloner_ou_mettre_a_jour() {
    local depot="$OPSYS_LOGICIEL/source" temporaire commit
    command -v git >/dev/null 2>&1 || die "git est introuvable (nécessaire pour télécharger OPSYS). Installez-le, ou clonez le dépôt vous-même et lancez install/install.sh depuis ce dépôt."
    if [ -d "$depot/.git" ]; then
        [ -z "$(git -C "$depot" status --porcelain)" ] ||
            die "$depot a des modifications locales : rien n'est mis à jour. Annulez-les (git -C '$depot' status) ou installez depuis votre propre dépôt (OPSYS_SOURCE)."
        etape "Récupération de $OPSYS_REF" git_installation -C "$depot" fetch --tags --prune origin
    else
        [ ! -e "$depot" ] || die "$depot existe mais n'est pas un dépôt git : déplacez-le, puis relancez."
        temporaire="$depot.installation-$$"
        NETTOYAGE+=("$temporaire")
        etape "Téléchargement d'OPSYS ($OPSYS_REPO_URL)" git_installation clone --filter=blob:none "$OPSYS_REPO_URL" "$temporaire"
        mv "$temporaire" "$depot"
    fi
    commit="$(resoudre_ref "$depot" "$OPSYS_REF")" || die "la référence '$OPSYS_REF' est introuvable dans $OPSYS_REPO_URL (branche, étiquette ou commit)."
    etape "Positionnement sur $OPSYS_REF (${commit:0:12})" git_installation -C "$depot" checkout --quiet --detach "$commit"
    SOURCE="$depot"
    SOURCE_GEREE=1
}

preparer_source() {
    if [ -n "$OPSYS_SOURCE" ]; then
        if [ ! -f "$OPSYS_SOURCE/core/openclaw.mjs" ] || [ ! -f "$OPSYS_SOURCE/pyproject.toml" ]; then
            die "$OPSYS_SOURCE n'est pas un dépôt OPSYS (core/openclaw.mjs et pyproject.toml attendus)."
        fi
        SOURCE="$(cd "$OPSYS_SOURCE" && pwd -P)"
    elif SOURCE="$(detecter_depot_voisin)"; then
        info "dépôt détecté : $SOURCE (utilisé tel quel)"
    else
        SOURCE=""
        cloner_ou_mettre_a_jour
    fi
    SOURCE_COMMIT="$(git -C "$SOURCE" rev-parse HEAD 2>/dev/null || printf 'inconnu')"
}

# Préparation seule : le dépôt reçu n'est jamais checkout/synchronisé/construit.
# Les chemins du venv éditable restent définitifs dès sa création, sans déplacement ultérieur.
# Aucun pointeur courant, fichier d'instance, lanceur opérateur ou service n'est publié ici.
preparer_generation() {
    local origine racine modes etat
    origine="${OPSYS_SOURCE:-}"
    if [ -z "$origine" ]; then
        origine="$(detecter_depot_voisin)" || die "la préparation exige --source vers un dépôt OPSYS local."
    fi
    origine="$(cd "$origine" && pwd -P)" || die "source de génération inaccessible."
    if [ ! -f "$origine/core/openclaw.mjs" ] || [ ! -f "$origine/pyproject.toml" ] ||
        [ ! -d "$origine/departments" ]; then
        die "source de génération OPSYS incomplète."
    fi
    SOURCE_COMMIT="$(git -C "$origine" rev-parse --verify 'HEAD^{commit}')" ||
        die "la préparation exige un commit local vérifiable."
    etat="$(GIT_OPTIONAL_LOCKS=0 git -C "$origine" status --porcelain --untracked-files=normal)" ||
        die "état du dépôt reçu impossible à vérifier."
    [ -z "$etat" ] ||
        die "source modifiée : préparer depuis un commit propre, sans mutation du dépôt reçu."
    modes="$(git -C "$origine" ls-tree -r "$SOURCE_COMMIT")" || die "inventaire Source impossible."
    if grep -Eq '^(120000|160000) ' <<< "$modes"; then
        die "source avec lien symbolique ou sous-module : ressource extérieure non figée, préparation refusée."
    fi
    racine="$OPSYS_LOGICIEL/generations"
    if [ -L "$racine" ] || [ -L "$OPSYS_LOGICIEL" ]; then
        die "racine de générations symbolique refusée."
    fi
    mkdir -p "$racine"
    racine="$(cd "$racine" && pwd -P)"
    GENERATION="$(mktemp -d "$racine/generation-XXXXXXXXXX")" || die "réservation de génération impossible."
    chmod 700 "$GENERATION"
    SOURCE="$GENERATION/source"
    mkdir "$SOURCE"
    # git archive matérialise des fichiers distincts ; aucun cp -l, worktree partagé ou dépôt mutable lié.
    git -C "$origine" archive --format=tar "$SOURCE_COMMIT" | tar -xf - -C "$SOURCE" ||
        die "copie indépendante du commit impossible ; génération incomplète conservée."
    SOURCE_GEREE=0
    VENV="$GENERATION/venv"
    VENV_PY="$VENV/bin/python"
    MOTEUR_PY="$VENV_PY"
    UV_LINK_MODE=copy installer_moteur
    preparer_sqlite_privee
    # Les symlinks d'interpréteur du venv restent une dépendance système explicitement non qualifiée.
    # chmod ne suit aucun symlink : en particulier, aucun binaire Python extérieur n'est modifié.
    find "$GENERATION" -mindepth 1 -type f -exec chmod a-w {} + || die "gel des fichiers impossible."
    find "$GENERATION" -mindepth 1 -type d -exec chmod a-w {} + || die "gel des répertoires impossible."
    "$VENV_PY" -I -S -c '
import hashlib, json, os, stat, subprocess, sys
from pathlib import Path
generation, source, venv, python, commit, sqlite_helper, origin = sys.argv[1:]
# archive peut appliquer export-ignore/export-subst : aucun fichier suivi ne doit
# disparaître ou changer silencieusement, hors helper dont la provenance est explicite.
inventory = subprocess.run(["git", "-C", origin, "ls-tree", "-rz", commit],
                           check=True, stdout=subprocess.PIPE).stdout
for record in inventory.split(b"\0"):
    if not record:
        continue
    header, relative = record.split(b"\t", 1)
    mode, kind, expected = header.split()
    target = Path(source) / os.fsdecode(relative)
    info = target.lstat()
    if kind != b"blob" or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("fichier Source absent, lié ou non régulier")
    if relative == b"install/sqlite_runtime.py" and sqlite_helper:
        continue
    digest = hashlib.new("sha1" if len(expected) == 40 else "sha256")
    digest.update(b"blob " + str(info.st_size).encode() + b"\0")
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    if digest.hexdigest().encode() != expected:
        raise ValueError("fichier Source différent du commit déclaré")
manifest = {"state": "prepared", "publication": "not-published", "generation": generation,
            "source": source, "venv": venv, "python": python, "commit": commit,
            "system_python_dependency": "not-qualified", "core_build": "not-prepared",
            "sqlite_helper_overlay_sha256": sqlite_helper or None}
# Le nom accepté devient visible seulement après écriture complète et fsync réussis.
# Un fichier pending éventuel conserve le diagnostic sans annoncer prepared.
pending = Path(generation) / ".generation.json.pending"
with pending.open("x") as stream:
    json.dump(manifest, stream, sort_keys=True)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
os.replace(pending, Path(generation) / "generation.json")
' "$GENERATION" "$SOURCE" "$VENV" "$MOTEUR_PY" "$SOURCE_COMMIT" "$GENERATION_SQLITE_HELPER_SHA" "$origine" ||
        die "finalisation de la génération impossible ; aucun pointeur publié."
    if ! chmod 400 "$GENERATION/generation.json" || ! chmod 500 "$GENERATION"; then
        rm -f "$GENERATION/generation.json"
        die "gel final impossible ; génération incomplète, aucun pointeur publié."
    fi
    info "génération préparée sans publication : $GENERATION"
}

# -- 3. Le core et le moteur -----------------------------------------------------------------------------------------------
publier_generation() {
    [ "$PREPARER_GENERATION" -eq 0 ] || die "préparer et publier sont deux opérations distinctes."
    chemin_absolu "génération préparée" "$PUBLIER_GENERATION"
    [ -n "$OPSYS_SOURCE" ] || die "la publication exige --source vers un Core local déjà construit."
    SOURCE="$(cd "$OPSYS_SOURCE" && pwd -P)" || die "Core local inaccessible."
    [ -f "$SOURCE/core/openclaw.mjs" ] || die "point d’entrée du Core local absent."
    command -v node >/dev/null 2>&1 || die "Node est requis pour le propriétaire de publication du Core."
    # Le Core garde l’autorité jusqu’à la restauration/nettoyage joints. Aucun Python direct ni repli ici.
    etape "Publication du runtime de l’instance existante sous propriétaire Gateway" \
        noyau metier instance publier-generation --generation "$PUBLIER_GENERATION" --logiciel "$OPSYS_LOGICIEL"
}

version_pnpm_du_core() {
    sed -n 's/.*"packageManager"[[:space:]]*:[[:space:]]*"pnpm@\([^"+]*\)[^"]*".*/\1/p' "$SOURCE/core/package.json" | head -n 1
}

version_pnpm_dans_core() {
    (cd "$SOURCE/core" && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 "$@" --version 2>/dev/null </dev/null) || true
}

preparer_pnpm() {
    local version dir
    version="$(version_pnpm_du_core)"
    [ -n "$version" ] || die "core/package.json ne fixe pas la version de pnpm (champ packageManager) : dépôt inattendu."
    if command -v pnpm >/dev/null 2>&1 && [ "$(version_pnpm_dans_core pnpm)" = "$version" ]; then
        PNPM=(pnpm)
        info "pnpm $version prêt (celui du système)"
        return 0
    fi
    dir="$(mktemp -d "${TMPDIR:-/tmp}/opsys-pnpm.XXXXXX")"
    NETTOYAGE+=("$dir")
    if command -v corepack >/dev/null 2>&1 &&
        COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack enable --install-directory "$dir" pnpm </dev/null >>"$JOURNAL" 2>&1 &&
        [ "$(version_pnpm_dans_core "$dir/pnpm")" = "$version" ]; then
        PNPM=("$dir/pnpm")
        PNPM_DIR="$dir"
        info "pnpm $version prêt (Corepack)"
        return 0
    fi
    if command -v npm >/dev/null 2>&1 &&
        npm install --global --prefix "$dir/npm" "pnpm@$version" </dev/null >>"$JOURNAL" 2>&1 &&
        [ "$(version_pnpm_dans_core "$dir/npm/bin/pnpm")" = "$version" ]; then
        PNPM=("$dir/npm/bin/pnpm")
        PNPM_DIR="$dir/npm/bin"
        info "pnpm $version prêt (npm)"
        return 0
    fi
    die "impossible de disposer de pnpm $version (celui que fixe core/package.json). Installez Corepack ou npm avec Node, puis relancez. Journal : $JOURNAL"
}

pnpm_core() {
    (cd "$SOURCE/core" && CI=true COREPACK_ENABLE_DOWNLOAD_PROMPT=0 PATH="${PNPM_DIR:+$PNPM_DIR:}$PATH" "${PNPM[@]}" "$@")
}

# Toute commande du core passe par ici, sous son profil : `--profile` est l'option racine qui projette le dossier d'état
# et le fichier de configuration canoniques du profil (core/src/cli/profile.ts, applyCliProfileEnv) ; la seule variable
# OPENCLAW_PROFILE ne le fait pas. Les variables qui sortiraient l'état de ce dossier sont écartées : le core
# refuserait alors tout service (core/src/config/paths.ts, isDefaultInstallIdentity).
noyau() {
    local ecartees=() nom
    for nom in "${VARIABLES_ECARTEES[@]}"; do ecartees+=(-u "$nom"); done
    env "${ecartees[@]}" OPSYS_HOME="$OPSYS_HOME" node "$SOURCE/core/openclaw.mjs" --profile "$PROFIL_CORE" "$@"
}

construire_core() {
    CONSEIL="Vérifiez l'accès réseau (registre npm) et l'espace disque, puis relancez." \
        etape "Installation des dépendances du core (pnpm install)" pnpm_core install --frozen-lockfile
    CONSEIL="Le journal donne la cause ; relancez après correction." \
        etape "Construction du core (pnpm build, plusieurs minutes)" pnpm_core build
}

moteur_python_utilisable() {
    [ -x "$VENV_PY" ] && "$VENV_PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1
}

# Extras d'exécution du moteur (pyproject.toml) : sans eux, la cédule par tournées de M4 (PyVRP) et la soumission
# en PDF de M3 (ReportLab) échouent fermées. `postgres` et `console` restent à Docker Compose, `dev` aux contributeurs.
EXTRAS_MOTEUR="tournees,soumission"

installer_moteur() {
    local extra
    local extras=() base_extras=()
    IFS="," read -r -a base_extras <<< "$EXTRAS_MOTEUR"
    for extra in "${base_extras[@]}"; do extras+=(--extra "$extra"); done
    if [ "$INGESTION_PDF" -eq 1 ]; then extras+=(--extra ingestion-pdf); fi
    if ! moteur_python_utilisable; then
        CONSEIL="Il faut Python 3.11 ou plus : installez-le, ou laissez uv le télécharger (accès réseau)." \
            etape "Création de l'environnement Python (uv venv)" uv venv --clear --python '>=3.11' "$VENV"
    fi
    CONSEIL="Vérifiez l'accès réseau (PyPI), puis relancez." \
        etape "Synchronisation des dépendances selon uv.lock" env UV_PROJECT_ENVIRONMENT="$VENV" uv sync --locked \
            --project "$SOURCE" --python "$VENV_PY" --group build --no-dev "${extras[@]}" \
            --no-build-isolation --no-install-project
    CONSEIL="Vérifiez l'accès réseau (PyPI), puis relancez." \
        etape "Installation du moteur verrouillé" env UV_PROJECT_ENVIRONMENT="$VENV" uv sync --locked \
            --project "$SOURCE" --python "$VENV_PY" --group build --no-dev "${extras[@]}" \
            --no-build-isolation
}

# Le profil privé qualifié est facultatif et explicitement sélectionné. Le chemin retourné est ensuite
# le SEUL lanceur métier (installation, CLI autonome et deux commandes metier.json), jamais celui de Node.
# Une sélection déjà installée est revalidée et conservée lors de la mise à jour.
preparer_sqlite_privee() {
    local selection="$OPSYS_LOGICIEL/runtime/sqlite-privee"
    local library="${OPSYS_SQLITE_LIBRARY:-}"
    if [ -n "$GENERATION" ]; then
        if [ -z "$library" ] && [ -d "$selection" ]; then
            library="$selection/libsqlite3.so.0.8.6"
        fi
        selection="$GENERATION/runtime/sqlite-privee"
    fi
    if [ -z "$library" ] && [ ! -e "$selection" ] && [ ! -L "$selection" ]; then
        return 0
    fi
    if [ -n "$GENERATION" ]; then
        # Le helper livré par ce bundle est épinglé indépendamment du commit Source reçu.
        # Sa copie privée conserve cette provenance explicite dans la génération.
        local helper
        helper="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/sqlite_runtime.py" ||
            die "répertoire du helper SQLite inaccessible."
        GENERATION_SQLITE_HELPER_SHA=75de1b3dbcc96b02ab970187439ad8101e547eebac415bc535773b8f87df6e89
        if [ ! -f "$helper" ] || [ -L "$helper" ]; then
            die "helper SQLite qualifié absent du bundle."
        fi
        printf '%s  %s\n' "$GENERATION_SQLITE_HELPER_SHA" "$helper" | sha256sum --check --status ||
            die "helper SQLite différent du composant qualifié."
        cp "$helper" "$SOURCE/install/sqlite_runtime.py" || die "copie privée du helper SQLite impossible."
    fi
    local args=(--root "$selection" --python "$VENV_PY")
    if [ -n "$library" ]; then args+=(--library "$library"); fi
    MOTEUR_PY="$("$VENV_PY" -I -S "$SOURCE/install/sqlite_runtime.py" "${args[@]}")" ||
        die "profil SQLite privé refusé : aucun repli vers SQLite système."
    [ -x "$MOTEUR_PY" ] || die "lanceur SQLite privé indisponible."
}

# -- 4. L'instance -----------------------------------------------------------------------------------------------------------
moteur_opsys() {
    OPSYS_HOME="$OPSYS_HOME" "$MOTEUR_PY" -m opsys.cli "$@"
}

# Le dossier d'état du core est celui que le moteur Python calcule (instance.dossier_core : la règle du fork, une seule
# implémentation pour Linux, macOS et Windows). Le script ne le devine pas ; `verifier_dossier_du_core` le confronte
# ensuite à la réponse du core lui-même.
determiner_dossier_core() {
    local dossier
    dossier="$(moteur_opsys instance dossier </dev/null)" ||
        die "le dossier d'état du core est indéterminé (voir ci-dessus). HOME est-il défini ?"
    chemin_absolu "le dossier d'état du core" "$dossier"
    DOSSIER_CORE="$dossier"
    preparer_masque
}

initialiser_instance() {
    local args sortie erreurs code=0
    args=(instance initialiser --source "$SOURCE" --lanceur-python "$MOTEUR_PY")
    if [ -n "$PORT_GATEWAY" ]; then args+=(--port-gateway "$PORT_GATEWAY"); fi
    if [ -n "$PORT_MOTEUR" ]; then args+=(--port-moteur "$PORT_MOTEUR"); fi
    erreurs="$(mktemp "${TMPDIR:-/tmp}/opsys-erreurs.XXXXXX")"
    NETTOYAGE+=("$erreurs")
    info "Initialisation de l'instance ($OPSYS_HOME ; état du core : $DOSSIER_CORE)..."
    sortie="$(moteur_opsys "${args[@]}" 2>"$erreurs" </dev/null)" || code=$?
    preparer_masque
    { printf '\n== opsys metier instance initialiser (code %s)\n' "$code"; cat "$erreurs"; printf '%s\n' "$sortie"; } |
        filtrer_secrets >>"$JOURNAL"
    filtrer_secrets <"$erreurs" >&2
    case "$code" in
        0) ;;
        "$CODE_EN_ATTENTE") EN_ATTENTE=1 ;;
        *) die "l'initialisation de l'instance a échoué (code $code) : voir ci-dessus. Journal : $JOURNAL" ;;
    esac
    PORT_GATEWAY="$(printf '%s' "$sortie" | "$VENV_PY" -c 'import json, sys; print(json.load(sys.stdin)["port_gateway"])')"
    PORT_MOTEUR="$(printf '%s' "$sortie" | "$VENV_PY" -c 'import json, sys; print(json.load(sys.stdin)["port_moteur"])')"
    MODE_FOURNISSEUR="$(printf '%s' "$sortie" | "$VENV_PY" -c 'import json, sys; print(json.load(sys.stdin)["mode_fournisseur"])')"
}

# Métadonnée de chemin uniquement : jamais ouvrir le fichier de clés, ni inventer un metier.json.
# Le contrôle précède initialiser_instance, qui conserverait un env valide mais normaliserait un env mal typé.
metadonnees_ingestion_pdf() {
    [ "$CONFIGURER_PDF" -eq 1 ] || return 0
    "$VENV_PY" -c '
# opsys_pdf_metadata : mise à jour locale atomique du raccord, aucun loader de clés.
import json, os, stat, sys, tempfile
from pathlib import Path
phase, nom, actif, fichier, attente = sys.argv[1:]
chemin = Path(nom)
temporaire = None
try:
    try:
        avant = chemin.lstat()
    except FileNotFoundError:
        if phase == "check" or attente == "1":
            sys.exit(0)
        raise ValueError("configuration absente") from None
    if not stat.S_ISREG(avant.st_mode) or avant.st_uid != os.geteuid() or avant.st_size > 1048576:
        raise ValueError("configuration non régulière")
    brut = chemin.read_bytes()
    attributs = ("st_dev", "st_ino", "st_uid", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    def inchange():
        courant = chemin.lstat()
        return all(getattr(avant, a) == getattr(courant, a) for a in attributs) and chemin.read_bytes() == brut
    if not inchange():
        raise ValueError("configuration modifiée")
    config = json.loads(brut)
    env = config.get("env", {}) if isinstance(config, dict) else None
    if not isinstance(config, dict) or not isinstance(env, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()
    ):
        raise ValueError("structure invalide")
    if actif == "1" and any(
        k == "OPSYS_INGESTION_CLE" or k.startswith(("OPSYS_CLE_INGESTION_", "OPSYS_CLE_PDF_", "OPSYS_CLE_CSV_"))
        or (k.startswith("OPSYS_INGESTION_CLE_") and k != "OPSYS_INGESTION_CLE_REFERENCE")
        for k in env
    ):
        raise ValueError("clé globale refusée")
    if phase == "check":
        sys.exit(0)
    precedent = dict(env)
    if actif == "1" and fichier:
        env["OPSYS_INGESTION_ENV_FILE"] = fichier
    else:
        env.pop("OPSYS_INGESTION_ENV_FILE", None)
    if env == precedent:
        sys.exit(0)
    config["env"] = env
    contenu = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporaire = tempfile.mkstemp(prefix=".metier.json.pdf-", dir=chemin.parent)
    with os.fdopen(fd, "wb") as sortie:
        os.fchmod(sortie.fileno(), stat.S_IMODE(avant.st_mode))
        sortie.write(contenu)
        sortie.flush()
        os.fsync(sortie.fileno())
    if not inchange():
        raise ValueError("configuration modifiée")
    os.replace(temporaire, chemin)
    temporaire = None
    dossier_fd = os.open(chemin.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dossier_fd)
    finally:
        os.close(dossier_fd)
except Exception:
    print("raccord PDF refusé : configuration moteur invalide, modifiée ou écriture impossible; aucune valeur affichée", file=sys.stderr)
    sys.exit(1)
finally:
    if temporaire is not None:
        Path(temporaire).unlink(missing_ok=True)
' "$1" "$DOSSIER_CORE/opsys/metier.json" "$INGESTION_PDF" "$FICHIER_INGESTION" "$EN_ATTENTE" </dev/null ||
        die "configuration du raccord PDF refusée : voir le diagnostic sans valeur ci-dessus."
}

verifier_ingestion_pdf() {
    [ "$INGESTION_PDF" -eq 1 ] || return 0
    local code=0 statuts
    info "Vérification PDF native (SQLite, clé privée, worker isolé existant)..."
    OPSYS_HOME="$OPSYS_HOME" OPSYS_INGESTION_ENV_FILE="$FICHIER_INGESTION" \
        "$VENV_PY" "$SOURCE/deploy/readiness_pdf.py" --pdf-only </dev/null 2>&1 |
        filtrer_secrets | tee -a "$JOURNAL" || {
            statuts=("${PIPESTATUS[@]}")
            code="${statuts[0]}"
            if [ "${statuts[1]}" -ne 0 ] || [ "${statuts[2]}" -ne 0 ]; then code=1; fi
        }
    case "$code" in
        0) ;;
        "$CODE_EN_ATTENTE") EN_ATTENTE=1 ;;
        *) die "contrôle PDF natif en échec (code $code) : rien n'est démarré ; aucune isolation permissive n'est utilisée." ;;
    esac
}

# Le dossier que l'installateur a préparé doit être celui que le core lira : le core dit lui-même où est sa configuration
# (`opsys config file`). Le fichier attendu est celui que dit le moteur (`instance fichier-config` : opsys.json, ou
# l'openclaw.json qui existe déjà), lu après l'initialisation. Si la règle de profil du fork change, on s'arrête ici,
# avant de démarrer un Gateway qui ignorerait la configuration générée.
verifier_dossier_du_core() {
    local sortie="" erreurs annonce attendu code=0
    info "Vérification du dossier d'état du core (opsys config file)..."
    attendu="$(moteur_opsys instance fichier-config </dev/null)" ||
        die "le fichier de configuration du core est indéterminé (voir ci-dessus)."
    chemin_absolu "le fichier de configuration du core" "$attendu"
    erreurs="$(mktemp "${TMPDIR:-/tmp}/opsys-erreurs.XXXXXX")"
    NETTOYAGE+=("$erreurs")
    sortie="$(noyau config file 2>"$erreurs" </dev/null)" || code=$?
    { printf '\n== opsys config file (code %s)\n' "$code"; cat "$erreurs"; printf '%s\n' "$sortie"; } |
        filtrer_secrets >>"$JOURNAL"
    if [ "$code" -ne 0 ]; then
        filtrer_secrets <"$erreurs" >&2
        die "opsys config file a échoué (code $code). Journal complet : $JOURNAL"
    fi
    annonce="$(printf '%s\n' "$sortie" | awk 'NF { ligne = $0 } END { print ligne }')"
    [ "$annonce" = "$attendu" ] ||
        die "le core cherche sa configuration dans '$annonce', mais l'installateur a préparé '$attendu'. La règle du profil « $PROFIL_CORE » a changé dans le core (core/src/config/opsys-instance.ts) : rien n'est démarré. Journal : $JOURNAL"
}

# -- Commandes `opsys` et `openclaw` (core), `opsys-metier` (moteur) ----------------------------------------------------------
# PLAN T0.7 lot 2 : `opsys` est la commande du core, `openclaw` son alias (le même fichier, écrit deux fois : aucun lien,
# donc rien de particulier sous macOS ou sur un volume sans liens) ; le moteur métier, qui s'appelait `opsys`, s'appelle
# `opsys-metier`, et `opsys metier <commande>` le lance depuis le core (core/src/cli/opsys-metier-cli.ts) à partir de
# `opsys/metier.json`. Ces trois fichiers portent la marque de l'installateur : les réécrire à chaque installation est
# permis, y compris l'ancien `opsys` (l'enveloppe du moteur d'avant le lot 2) ; tout autre fichier de ce nom est refusé.
ecrire_enveloppe() {
    local cible="$1" contenu="$2" temporaire
    if [ -e "$cible" ] && ! grep -qF "$MARQUE" "$cible" 2>/dev/null; then
        die "$cible existe déjà et n'a pas été installé par OPSYS : déplacez-le, ou choisissez un autre dossier (OPSYS_BIN=/autre/dossier)."
    fi
    mkdir -p "$(dirname "$cible")"
    temporaire="$(mktemp "$cible.XXXXXX")"
    NETTOYAGE+=("$temporaire")
    printf '%s\n' "$contenu" >"$temporaire"
    chmod 755 "$temporaire"
    mv "$temporaire" "$cible"
}

# Les chaînes entre apostrophes sont écrites telles quelles dans la commande installée : rien ne doit s'y étendre ici.
# shellcheck disable=SC2016
contenu_commande_core() {
    printf '%s\n' '#!/usr/bin/env bash' "$MARQUE"
    printf 'DEFAUT=%q\n' "$OPSYS_HOME"
    printf '%s\n' 'OPSYS_HOME="${OPSYS_HOME:-$DEFAUT}"' 'export OPSYS_HOME' \
        "# Le core d'OPSYS tourne sous son profil « $PROFIL_CORE » : son état est le dossier canonique du profil, jamais un autre." \
        "unset ${VARIABLES_ECARTEES[*]}"
    printf 'NODE=%q\n' "$NODE"
    printf '%s\n' '[ -x "$NODE" ] || { echo "opsys : Node est introuvable ($NODE) : relancez install.sh." >&2; exit 127; }'
    printf 'exec "$NODE" %q --profile %q "$@"\n' "$SOURCE/core/openclaw.mjs" "$PROFIL_CORE"
}

# shellcheck disable=SC2016
contenu_commande_moteur() {
    printf '%s\n' '#!/usr/bin/env bash' "$MARQUE"
    printf 'DEFAUT=%q\n' "$OPSYS_HOME"
    printf '%s\n' 'OPSYS_HOME="${OPSYS_HOME:-$DEFAUT}"' 'export OPSYS_HOME'
    printf 'PY=%q\n' "$MOTEUR_PY"
    printf 'DOSSIER_CORE=%q\n' "$DOSSIER_CORE"
    if [ "$INGESTION_PDF" -eq 1 ] && [ -n "$FICHIER_INGESTION" ]; then
        printf 'INGESTION_DEFAUT=%q\n' "$FICHIER_INGESTION"
        printf '%s\n' 'export OPSYS_INGESTION_ENV_FILE="${OPSYS_INGESTION_ENV_FILE:-$INGESTION_DEFAUT}"'
    fi
    printf '%s\n' \
        "# Réglages et secrets de l'instance (les mêmes que ceux du Gateway, dans l'état du core) : lus ligne à ligne, jamais évalués." \
        'ENV_FILE="$DOSSIER_CORE/.env"' \
        'if [ -r "$ENV_FILE" ]; then' \
        '    while IFS="=" read -r cle valeur || [ -n "$cle" ]; do' \
        '        case "$cle" in "" | "#"* | [0-9]* | *[!A-Za-z0-9_]*) continue ;; esac' \
        '        if [ -z "${!cle+x}" ]; then export "$cle=$valeur"; fi' \
        '    done <"$ENV_FILE"' \
        'fi' \
        '[ -x "$PY" ] || { echo "opsys-metier : environnement Python introuvable ($PY) : relancez install.sh." >&2; exit 127; }' \
        'exec "$PY" -m opsys.cli "$@"'
}

# Le fichier `opsys` que l'installateur avait écrit avant le lot 2 est l'enveloppe du moteur : elle exécute `-m opsys.cli`.
ancienne_commande_moteur_presente() {
    [ -f "$OPSYS_BIN/opsys" ] && grep -qF -- '-m opsys.cli' "$OPSYS_BIN/opsys" 2>/dev/null
}

installer_commandes() {
    local cible ancien=0
    # Tout est vérifié avant la première écriture : un fichier étranger ne laisse pas un jeu de commandes à moitié remplacé.
    for cible in "$OPSYS_BIN/opsys" "$OPSYS_BIN/openclaw" "$OPSYS_BIN/opsys-metier"; do
        if [ -e "$cible" ] && ! grep -qF "$MARQUE" "$cible" 2>/dev/null; then
            die "$cible existe déjà et n'a pas été installé par OPSYS : déplacez-le, ou choisissez un autre dossier (OPSYS_BIN=/autre/dossier)."
        fi
    done
    if ancienne_commande_moteur_presente; then ancien=1; fi
    ecrire_enveloppe "$OPSYS_BIN/opsys" "$(contenu_commande_core)"
    ecrire_enveloppe "$OPSYS_BIN/openclaw" "$(contenu_commande_core)"
    ecrire_enveloppe "$OPSYS_BIN/opsys-metier" "$(contenu_commande_moteur)"
    info "commandes installées : $OPSYS_BIN/opsys (core), $OPSYS_BIN/openclaw (alias du core) et $OPSYS_BIN/opsys-metier (moteur métier)"
    if [ "$ancien" -eq 1 ]; then
        info "« opsys » est maintenant la commande du core : l'ancienne commande du moteur est remplacée. Le moteur se lance par « opsys metier <commande> » (ou « opsys-metier <commande> »)."
    fi
}

# -- 5. Configuration valide, service, santé --------------------------------------------------------------------------------
attendre_http() {
    local url="$1" delai="$2" ecoule=0
    while [ "$ecoule" -lt "$delai" ]; do
        if curl -fsS --noproxy '*' --max-time 3 -o /dev/null "$url" </dev/null >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        ecoule=$((ecoule + 2))
    done
    return 1
}

# Où regarder quand le Gateway ne répond pas : le journal du service (journalctl sous Linux ; sous macOS, le fichier que
# le LaunchAgent écrit, core/src/daemon/restart-logs.ts, et l'état que launchd en donne).
indice_journaux() {
    case "$(uname -s)" in
        Linux) printf '%s' "journalctl --user -u openclaw-gateway-$PROFIL_CORE -n 100 ; opsys gateway status --deep" ;;
        Darwin) printf '%s' "tail -n 100 ~/Library/Logs/openclaw/gateway-$PROFIL_CORE.log ; launchctl print gui/$(id -u)/ai.openclaw.$PROFIL_CORE ; opsys gateway status --deep" ;;
        *) printf '%s' "opsys gateway status --deep ; opsys logs" ;;
    esac
}

installer_service() {
    CONSEIL="Si systemd --user (Linux) ou launchd (macOS) n'est pas disponible ici, relancez avec --sans-service et démarrez le Gateway à la main : opsys gateway run." \
        etape "Installation du service du Gateway (utilisateur)" noyau gateway install --force --port "$PORT_GATEWAY"
    info "attente du Gateway (port $PORT_GATEWAY) et du moteur (port $PORT_MOTEUR)..."
    attendre_http "http://127.0.0.1:$PORT_GATEWAY/startupz" 240 ||
        die "le Gateway ne répond pas sur le port $PORT_GATEWAY après 240 s. Voir : $(indice_journaux)"
    attendre_http "http://127.0.0.1:$PORT_MOTEUR/sante" 240 ||
        die "le moteur ne répond pas sur le port $PORT_MOTEUR après 240 s (le Gateway le lance). Voir : $(indice_journaux)"
    SERVICE_INSTALLE=1
    info "Gateway et moteur répondent."
}

ecrire_enregistrement() {
    local fichier="$OPSYS_LOGICIEL/installation.env" temporaire
    temporaire="$fichier.tmp.$$"
    NETTOYAGE+=("$temporaire")
    {
        printf 'OPSYS_HOME=%s\n' "$OPSYS_HOME"
        printf 'OPSYS_BIN=%s\n' "$OPSYS_BIN"
        printf 'PROFIL_CORE=%s\n' "$PROFIL_CORE"
        printf 'DOSSIER_CORE=%s\n' "$DOSSIER_CORE"
        printf 'SOURCE=%s\n' "$SOURCE"
        printf 'SOURCE_GEREE=%s\n' "$SOURCE_GEREE"
        printf 'SOURCE_COMMIT=%s\n' "$SOURCE_COMMIT"
        printf 'PORT_GATEWAY=%s\n' "$PORT_GATEWAY"
        printf 'PORT_MOTEUR=%s\n' "$PORT_MOTEUR"
        printf 'SERVICE=%s\n' "$SERVICE_INSTALLE"
        printf 'INGESTION_PDF=%s\n' "$INGESTION_PDF"
        printf 'INGESTION_ENV_FILE=%s\n' "$FICHIER_INGESTION"
        printf 'INSTALLE_LE=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } >"$temporaire"
    mv "$temporaire" "$fichier"
}

avertir_si_bin_hors_path() {
    case ":$PATH:" in
        *":$OPSYS_BIN:"*) ;;
        *) avertir "$OPSYS_BIN n'est pas dans votre PATH. Ajoutez à votre profil : export PATH=\"$OPSYS_BIN:\$PATH\"" ;;
    esac
}

# Un autre `opsys` que celui d'OPSYS passe-t-il avant lui dans le PATH ? Typiquement l'ancien moteur Python installé par
# `pip install`, `pipx` ou `uv tool install` (son point d'entrée s'appelait `opsys`) : `opsys metier ...` y serait refusé
# et le core ne serait pas atteint. La commande n'est jamais lancée : seul son chemin est dit, avec quoi faire.
avertir_si_opsys_masque() {
    local premier
    premier="$(command -v opsys 2>/dev/null || true)"
    if [ -z "$premier" ] || [ "$premier" = "$OPSYS_BIN/opsys" ]; then
        return 0
    fi
    avertir "la commande « opsys » de votre PATH est $premier, pas celle qu'OPSYS vient d'installer ($OPSYS_BIN/opsys). Si c'est l'ancien moteur Python (pip, pipx, uv tool), retirez-le (pip uninstall opsys-ai ; pipx uninstall opsys-ai ; uv tool uninstall opsys-ai) ou mettez $OPSYS_BIN en tête du PATH. Rien n'a été modifié."
}

afficher_bilan() {
    printf '\n'
    if [ "$EN_ATTENTE" -eq 1 ]; then
        printf '%s\n' "OPSYS est installé, mais l'instance n'est pas prête : il manque les décisions listées ci-dessus."
        printf '%s\n' "Ce n'est pas une erreur d'installation. Fournissez-les, puis relancez la même commande (rien n'est refait inutilement)."
    else
        printf '%s\n' "OPSYS est installé."
    fi
    printf '  %-22s %s\n' "Données de l'instance" "$OPSYS_HOME  (jamais supprimées par la désinstallation)"
    printf '  %-22s %s\n' "État du core" "$DOSSIER_CORE  (profil $PROFIL_CORE ; jamais supprimé par la désinstallation)"
    printf '  %-22s %s\n' "Réglages et secrets" "$DOSSIER_CORE/.env  (0600 : ne jamais partager ni versionner)"
    printf '  %-22s %s\n' "Logiciel" "$OPSYS_LOGICIEL  (commit ${SOURCE_COMMIT:0:12})"
    printf '  %-22s %s\n' "Commandes" "$OPSYS_BIN/opsys (core ; alias openclaw), $OPSYS_BIN/opsys-metier (moteur : opsys metier <commande>)"
    if [ "$INGESTION_PDF" -eq 1 ]; then
        printf '  %-22s %s\n' "Ingestion PDF" "option native activée ; contrôle isolé ci-dessus ; fichier de clés jamais copié"
    else
        printf '  %-22s %s\n' "Ingestion PDF" "désactivée ; activation explicite : --avec-ingestion-pdf"
    fi
    if [ "$EN_ATTENTE" -eq 0 ]; then
        printf '  %-22s %s\n' "Gateway" "http://127.0.0.1:$PORT_GATEWAY  (moteur : 127.0.0.1:$PORT_MOTEUR)"
        if [ "$MODE_FOURNISSEUR" = "natif" ]; then
            printf '  %-22s %s\n' "Fournisseurs de modèles" "natifs OpenClaw, selon $OPSYS_HOME/paliers.yaml (aucun service LiteLLM requis)"
        else
            printf '  %-22s %s\n' "Fournisseurs de modèles" "LiteLLM de compatibilité, explicitement sélectionné"
        fi
        printf '  %-22s %s\n' "LiteLLM optionnel" "aucun service externe n'est installé par cet installateur"
        if [ "$SERVICE_INSTALLE" -eq 1 ]; then
            printf '  %-22s %s\n' "Service" "installé (utilisateur, profil $PROFIL_CORE) ; état : opsys gateway status"
        else
            printf '  %-22s %s\n' "Service" "non installé (--sans-service) ; démarrage : opsys gateway run"
        fi
        printf '\nProchaines étapes :\n'
        printf '  1. Créer le propriétaire : opsys metier personnes creer <identifiant> --nom "<Nom>" --role nathan_owner\n'
        printf '%s\n' "  2. Appairer l'app mobile : opsys qr, puis opsys devices approve <demande>"
        printf '  3. Sauvegarder : opsys metier instance exporter --sortie <fichier.tar.gz>\n'
    fi
    printf '  Journal de cette installation : %s\n' "$JOURNAL"
}

main() {
    OPSYS_SOURCE="${OPSYS_SOURCE:-}"
    OPSYS_REPO_URL="${OPSYS_REPO_URL:-https://github.com/leon36000/OPSYS-AI.git}"
    OPSYS_REF="${OPSYS_REF:-main}"
    trap nettoyer EXIT
    trap 'printf "[opsys] interrompu.\n" >&2; exit 130' INT
    trap 'printf "[opsys] terminé par un signal.\n" >&2; exit 143' TERM

    analyser_arguments "$@"
    if [ -n "$PUBLIER_GENERATION" ]; then
        resoudre_chemins
        ouvrir_journal
        publier_generation
        return 0
    fi
    if [ "$PREPARER_GENERATION" -eq 1 ]; then
        resoudre_chemins
        ouvrir_journal
        preparer_generation
        return 0
    fi
    verifier_mode_fournisseur
    resoudre_chemins
    verifier_prerequis
    ouvrir_journal
    info "OPSYS : installation (journal : $JOURNAL)"
    preparer_source
    verifier_version_node
    preparer_pnpm
    construire_core
    preparer_image_sandbox
    installer_moteur
    preparer_sqlite_privee
    determiner_dossier_core
    metadonnees_ingestion_pdf check
    initialiser_instance
    verifier_ingestion_pdf
    metadonnees_ingestion_pdf write
    etape "Vérification du core (opsys --version)" noyau --version
    verifier_dossier_du_core
    installer_commandes
    if [ "$EN_ATTENTE" -eq 0 ]; then
        etape "Validation de la configuration par le core (opsys config validate)" noyau config validate
        if [ "$AVEC_SERVICE" -eq 1 ]; then
            installer_service
        fi
    fi
    ecrire_enregistrement
    avertir_si_bin_hors_path
    avertir_si_opsys_masque
    afficher_bilan
    if [ "$EN_ATTENTE" -eq 1 ]; then
        exit "$CODE_EN_ATTENTE"
    fi
}

main "$@"
