#!/usr/bin/env bash
# deploy/restore.sh — restauration d'une sauvegarde produite par deploy/backup.sh.
#
# DESTRUCTIF : remplace les bases Postgres (opsys, litellm) et les volumes de données courants.
# Confirmation explicite requise (--yes sinon invite interactive) — frontière humaine (AGENTS.md,
# suppressions/écrasements définitifs = T3).
#
# Usage : deploy/restore.sh --from DIR [--yes] [--autoriser-sans-empreintes]
#         deploy/restore.sh --latest [--yes]
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FROM=""
ASSUME_YES=0
AUTORISER_SANS_EMPREINTES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --from) FROM="$2"; shift 2 ;;
        --latest)
            FROM="$(find "${OPSYS_BACKUP_DIR:-$SCRIPT_DIR/backups}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n1)"
            shift
            ;;
        --yes) ASSUME_YES=1; shift ;;
        --autoriser-sans-empreintes) AUTORISER_SANS_EMPREINTES=1; shift ;;
        *) echo "argument inconnu : $1" >&2; exit 2 ;;
    esac
done

log()  { printf '[restore] %s\n' "$*"; }
warn() { printf '[restore] AVERTISSEMENT : %s\n' "$*" >&2; }
die()  {
    printf '[restore] ERREUR : %s\n' "$*" >&2
    if [ "${RESTORE_WRITING:-0}" -eq 1 ]; then
        warn "une écriture a déjà commencé; rollback automatique absent. Les services restent arrêtés. Corrigez la cause puis relancez --from avec une sauvegarde complète et vérifiée avant de redémarrer la pile."
    fi
    exit 1
}

[ -n "$FROM" ] || die "précisez --from DIR ou --latest."
[ -d "$FROM" ] || die "dossier de sauvegarde introuvable : $FROM"
[ -f "$FROM/MANIFEST.txt" ] || die "$FROM ne ressemble pas à une sauvegarde deploy/backup.sh (MANIFEST.txt absent)."
[ -f "$SCRIPT_DIR/.env" ] || die ".env introuvable."

# shellcheck disable=SC1091
set -a; . "$SCRIPT_DIR/.env"; set +a
MODE="${OPSYS_MODE_FOURNISSEUR:-natif}"
case "$MODE" in natif|litellm) ;; *) die "OPSYS_MODE_FOURNISSEUR invalide : $MODE" ;; esac
# Toute entrée d'intégrité impose la vérification : un lien/répertoire n'est pas une absence.
# Le format du manifeste n'est utilisable pour le dispatch qu'après cette frontière.
FORMAT="$(python3 -I -B - "$FROM" "$AUTORISER_SANS_EMPREINTES" <<'PY_INTEGRITE'
import hashlib, json, re, stat, sys
from pathlib import Path

dossier = Path(sys.argv[1])
limite = 64 * 1024

def regulier(chemin):
    information = chemin.lstat()
    taille = information.st_size
    if not stat.S_ISREG(information.st_mode):
        raise ValueError("fichier non régulier")
    return taille

def objet(paires):
    resultat = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError("clé JSON dupliquée")
        resultat[cle] = valeur
    return resultat

try:
    manifeste = dossier / "MANIFEST.txt"
    if regulier(manifeste) > limite:
        raise ValueError("manifeste trop grand")
    with manifeste.open("rb") as source:
        brut = source.read(limite + 1)
    if not brut or len(brut) > limite:
        raise ValueError("manifeste vide ou trop grand")
    lignes = brut.decode("utf-8").splitlines()
    version = lignes[0]
    integrite = dossier / "INTEGRITE.json"
    try:
        integrite.lstat()
    except FileNotFoundError:
        if version == "format=opsys-backup/4":
            raise ValueError("INTEGRITE.json requis pour v4")
        if version.startswith("format=") and version not in {
            "format=opsys-backup/2", "format=opsys-backup/3"
        }:
            raise ValueError("format de sauvegarde inconnu")
        if sys.argv[2] != "1":
            raise ValueError("archive historique : --autoriser-sans-empreintes requis")
        print("[restore] AVERTISSEMENT : archive historique sans empreintes ; contrôle structurel seulement.",
              file=sys.stderr)
    else:
        if regulier(integrite) > limite:
            raise ValueError("métadonnées trop grandes")
        with integrite.open("rb") as source:
            contenu = source.read(limite + 1)
        if len(contenu) > limite:
            raise ValueError("métadonnées trop grandes")
        document = json.loads(contenu, object_pairs_hook=objet)
        if (type(document) is not dict or set(document) != {"format", "fichiers"}
                or document["format"] != "opsys-backup-integrity/1"
                or type(document["fichiers"]) is not dict):
            raise ValueError("schéma invalide")
        if version != "format=opsys-backup/4":
            raise ValueError("format incompatible avec INTEGRITE.json")
        archives = [ligne[len("archive="):] for ligne in lignes if ligne.startswith("archive=")]
        if (len(archives) != len(set(archives))
                or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", nom) for nom in archives)
                or "MANIFEST.txt" in archives):
            raise ValueError("liste des archives invalide")
        if set(document["fichiers"]) != {"MANIFEST.txt", *archives}:
            raise ValueError("inventaire des empreintes discordant")
        for nom, reference in document["fichiers"].items():
            if (type(reference) is not dict or set(reference) != {"sha256", "octets"}
                    or type(reference["octets"]) is not int or reference["octets"] < 0
                    or type(reference["sha256"]) is not str
                    or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])):
                raise ValueError("référence d'empreinte invalide")
            chemin = dossier / nom
            if regulier(chemin) != reference["octets"]:
                raise ValueError("taille discordante : " + nom)
            empreinte = hashlib.sha256()
            with chemin.open("rb") as source:
                while morceau := source.read(1024 * 1024):
                    empreinte.update(morceau)
            if empreinte.hexdigest() != reference["sha256"]:
                raise ValueError("empreinte discordante : " + nom)
    print(version)
except (OSError, ValueError, IndexError) as erreur:
    raise SystemExit("intégrité de sauvegarde refusée : " + str(erreur))
PY_INTEGRITE
)" || die "aucun service arrêté, aucune donnée restaurée."
COMPOSE=(docker compose)
if [ "$MODE" = litellm ]; then
    COMPOSE+=(--profile litellm)
elif [[ "$FORMAT" != "format=opsys-backup/3" && "$FORMAT" != "format=opsys-backup/4" ]] || grep -Fqx 'required=postgres:opsys' "$FROM/MANIFEST.txt" || \
    grep -Fqx 'required=postgres:litellm' "$FROM/MANIFEST.txt"; then
    COMPOSE+=(--profile database)
fi
COMPOSE+=(--env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml")
compose() { "${COMPOSE[@]}" "$@"; }
VOLUME_TOOL_IMAGE="${OPSYS_BACKUP_IMAGE:-opsys:local}"

volume_name() {
    local logical="$1" configuration nom
    local profils=()
    # Résoudre les archives historiques sans démarrer le profil fournisseur correspondant.
    case "$logical" in
        postgres_data) profils+=(--profile database) ;;
        litellm_config) profils+=(--profile litellm) ;;
    esac
    configuration="$(compose "${profils[@]}" config --format json)" || die "impossible de résoudre les volumes Compose."
    nom="$(printf '%s' "$configuration" | python3 -c '
import json, sys
modele = json.load(sys.stdin)
cle = sys.argv[1]
volume = modele.get("volumes", {}).get(cle)
if not isinstance(volume, dict):
    raise SystemExit(1)
print(volume.get("name") or "{}_{}".format(modele.get("name"), cle))
' "$logical")" || die "volume Compose $logical introuvable dans la configuration effective."
    [ -n "$nom" ] || die "nom Docker vide pour le volume Compose $logical."
    printf '%s' "$nom"
}

volume_archive() {
    local logical="$1" fichier="$FROM/volume-${1}.tar.gz" cle compte ligne source_nom
    if [ -f "$fichier" ]; then
        printf '%s' "$fichier"
        return 0
    fi

    cle="volume_name.$logical"
    compte="$(grep -Fc "$cle=" "$FROM/MANIFEST.txt" || true)"
    if [ "$compte" -gt 1 ]; then
        die "le manifeste définit plusieurs noms physiques pour le volume $logical."
    fi
    if [ "$compte" -eq 1 ]; then
        ligne="$(grep -F "$cle=" "$FROM/MANIFEST.txt")"
        source_nom="${ligne#*=}"
        [[ "$source_nom" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "nom physique invalide pour $logical dans le manifeste."
        fichier="$FROM/volume-${source_nom}.tar.gz"
        if [ -f "$fichier" ]; then
            printf '%s' "$fichier"
            return 0
        fi
        return 1
    fi

    # Les anciens manifests n'associaient pas les clés logiques aux volumes physiques. Leur ancien nom
    # préfixait le volume logique par le projet; n'accepter que l'unique correspondance exacte de suffixe.
    local candidats=("$FROM"/volume-*_"$logical".tar.gz)
    if [ "${#candidats[@]}" -gt 1 ]; then
        die "plusieurs anciennes archives correspondent au volume $logical; restauration ambiguë refusée."
    fi
    [ "${#candidats[@]}" -eq 1 ] || return 1
    printf '%s' "${candidats[0]}"
}

verifier_sauvegarde() {
    local fichier logique archive format ressource kind nom source_mode
    [ -s "$FROM/MANIFEST.txt" ] || die "manifeste vide : sauvegarde refusée."
    format="$(sed -n '1p' "$FROM/MANIFEST.txt")"
    if [[ "$format" == format=* ]] && [ "$format" != "format=opsys-backup/2" ] && \
        [ "$format" != "format=opsys-backup/3" ] && [ "$format" != "format=opsys-backup/4" ]; then
        die "format de sauvegarde inconnu : $format"
    fi
    if [[ "$format" = "format=opsys-backup/3" || "$format" = "format=opsys-backup/4" ]]; then
        [ "$(grep -c '^mode=' "$FROM/MANIFEST.txt")" -eq 1 ] || die "manifeste v3/v4 : mode absent ou dupliqué."
        source_mode="$(grep '^mode=' "$FROM/MANIFEST.txt" | cut -d= -f2- || true)"
        [ "$source_mode" = "$MODE" ] || die "profil source '$source_mode' différent du profil cible '$MODE'; restauration refusée."
        [ "$(grep -c '^database=' "$FROM/MANIFEST.txt")" -eq 1 ] || die "manifeste v3/v4 : backend de base absent ou dupliqué."
        source_database="$(grep '^database=' "$FROM/MANIFEST.txt" | cut -d= -f2- || true)"
        case "$source_database" in sqlite|postgres) ;; *) die "backend de base v3/v4 invalide." ;; esac
        target_database=sqlite
        if [[ "${OPSYS_DATABASE_URL:-}" =~ ^postgres(ql)?:// ]]; then target_database=postgres; fi
        [ "$source_database" = "$target_database" ] ||
            die "backend source '$source_database' différent du backend cible '$target_database'; restauration refusée."
        local expected=()
        expected+=("volume:opsys_data" "volume:openclaw_config" "volume:openclaw_auth_secrets" "volume:caddy_data" "volume:caddy_config")
        if [ "$MODE" = litellm ]; then
            expected+=("volume:litellm_config" "postgres:litellm")
        fi
        if [ "$source_database" = postgres ]; then expected+=("postgres:opsys"); fi
        local actual_sorted expected_sorted
        actual_sorted="$(grep '^required=' "$FROM/MANIFEST.txt" | sed 's/^required=//' | LC_ALL=C sort || true)"
        expected_sorted="$(printf '%s\n' "${expected[@]}" | LC_ALL=C sort)"
        [ "$actual_sorted" = "$expected_sorted" ] ||
            die "ressources requises v3/v4 incompatibles avec le mode/backend; restauration refusée avant arrêt des services."
        grep -q '^required=' "$FROM/MANIFEST.txt" || die "manifeste v3/v4 sans ressources requises."
        while IFS= read -r ressource; do
            resource="${ressource#required=}"
            kind="${resource%%:*}"; nom="${resource#*:}"
            case "$kind:$nom" in
                postgres:opsys|postgres:litellm)
                    fichier="$FROM/postgres-${nom}.sql.gz"
                    [ -s "$fichier" ] || die "archive requise absente ou vide : ${fichier##*/}. Rien n'a été modifié."
                    grep -Fqx "archive=${fichier##*/}" "$FROM/MANIFEST.txt" || die "${fichier##*/} absent de la liste des archives."
                    gzip -t "$fichier" || die "${fichier##*/} illisible ou incomplet. Rien n'a été modifié."
                    ;;
                volume:opsys_data|volume:openclaw_config|volume:openclaw_auth_secrets|volume:litellm_config|volume:caddy_data|volume:caddy_config|volume:postgres_data)
                    fichier="$(volume_archive "$nom")" || die "archive requise du volume $nom absente. Rien n'a été modifié."
                    [ -s "$fichier" ] || die "archive requise du volume $nom vide. Rien n'a été modifié."
                    grep -Fqx "archive=${fichier##*/}" "$FROM/MANIFEST.txt" || die "archive du volume $nom absente de la liste."
                    tar -tzf "$fichier" >/dev/null || die "archive du volume $nom illisible ou incomplète. Rien n'a été modifié."
                    ;;
                *) die "ressource requise invalide dans le manifeste : $resource" ;;
            esac
        done < <(grep '^required=' "$FROM/MANIFEST.txt")
        while IFS= read -r ressource; do
            resource="${ressource#optional=}"
            kind="${resource%%:*}"; nom="${resource#*:}"
            [ "$kind" = volume ] || die "ressource optionnelle invalide dans le manifeste : $resource"
            case "$nom" in litellm_config|postgres_data) ;; *) die "volume optionnel non reconnu : $nom" ;; esac
            if [ "$nom" = postgres_data ] && grep -q '^required=postgres:' "$FROM/MANIFEST.txt"; then
                die "restauration SQL logique et volume physique PostgreSQL incompatibles; rien n'a été modifié."
            fi
            fichier="$(volume_archive "$nom")" || die "archive du volume optionnel $nom déclarée mais absente. Rien n'a été modifié."
            [ -s "$fichier" ] || die "archive optionnelle du volume $nom vide. Rien n'a été modifié."
            grep -Fqx "archive=${fichier##*/}" "$FROM/MANIFEST.txt" || die "archive optionnelle du volume $nom absente de la liste."
            tar -tzf "$fichier" >/dev/null || die "archive optionnelle du volume $nom illisible ou incomplète. Rien n'a été modifié."
        done < <(grep '^optional=' "$FROM/MANIFEST.txt" || true)
        while IFS= read -r archive; do
            archive="${archive#archive=}"
            [[ "$archive" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "nom d'archive invalide dans le manifeste."
            [ -s "$FROM/$archive" ] || die "archive déclarée absente ou vide : $archive. Rien n'a été modifié."
        done < <(grep '^archive=' "$FROM/MANIFEST.txt")
        return
    fi
    for fichier in postgres-opsys.sql.gz postgres-litellm.sql.gz; do
        [ -s "$FROM/$fichier" ] || die "archive requise absente ou vide : $fichier. Rien n'a été modifié."
        if [ "$format" = "format=opsys-backup/2" ]; then
            grep -Fqx "archive=$fichier" "$FROM/MANIFEST.txt" || die "$fichier n'est pas déclaré dans le manifeste."
        fi
        gzip -t "$FROM/$fichier" || die "$fichier est illisible ou incomplet. Rien n'a été modifié."
    done
    for logique in opsys_data openclaw_config openclaw_auth_secrets litellm_config caddy_data; do
        fichier="$(volume_archive "$logique")" || die "archive requise du volume $logique absente. Rien n'a été modifié."
        [ -s "$fichier" ] || die "archive requise du volume $logique vide. Rien n'a été modifié."
        if [ "$format" = "format=opsys-backup/2" ]; then
            grep -Fqx "archive=${fichier##*/}" "$FROM/MANIFEST.txt" ||
                die "l'archive du volume $logique n'est pas déclarée dans le manifeste."
        fi
        tar -tzf "$fichier" >/dev/null || die "archive du volume $logique illisible ou incomplète. Rien n'a été modifié."
    done
}

log "sauvegarde source : $FROM"
sed -n '1,80p' "$FROM/MANIFEST.txt"
verifier_sauvegarde

if [ "$ASSUME_YES" -ne 1 ]; then
    printf '\nCeci va ÉCRASER les bases opsys/litellm et les volumes de données courants. Continuer ? [taper OUI] '
    read -r reponse
    [ "$reponse" = "OUI" ] || die "restauration annulée."
fi

log "arrêt des services applicatifs avant restauration..."
PGDATA_PHYSIQUE=0
if [[ "$FORMAT" = "format=opsys-backup/3" || "$FORMAT" = "format=opsys-backup/4" ]] && \
    grep -Eq '^(required|optional)=volume:postgres_data$' "$FROM/MANIFEST.txt"; then
    PGDATA_PHYSIQUE=1
    command -v timeout >/dev/null 2>&1 || die "timeout (GNU coreutils) requis avant restauration physique de PostgreSQL."
fi
SERVICES_A_ARRETER=(opsys openclaw-gateway caddy)
if [ "$MODE" = litellm ]; then
    SERVICES_A_ARRETER+=(litellm postgres)
elif [[ "$FORMAT" != "format=opsys-backup/3" && "$FORMAT" != "format=opsys-backup/4" ]] || grep -q '^required=postgres:' "$FROM/MANIFEST.txt" || \
    [ "$PGDATA_PHYSIQUE" -eq 1 ]; then
    SERVICES_A_ARRETER+=(postgres)
fi
if [ "$PGDATA_PHYSIQUE" -eq 1 ]; then
    timeout --kill-after=5s 45s "${COMPOSE[@]}" stop --timeout 45 "${SERVICES_A_ARRETER[@]}" ||
        die "impossible d'arrêter les services avant restauration physique de PostgreSQL; aucun fichier n'a été modifié."
    # Le retour de stop ne suffit pas : refuser PGDATA actif ou une observation ambiguë avant
    # toute écriture, y compris dans les autres volumes. Un conteneur absent est sans écrivain.
    observation="$(timeout --kill-after=5s 30s "${COMPOSE[@]}" ps --all --format json)" ||
        die "arrêt de PostgreSQL non confirmé; aucun fichier n'a été modifié."
    if ! printf '%s' "$observation" | python3 -c '
import json, sys
brut = sys.stdin.read()
if not brut.strip():
    raise SystemExit(1)
try:
    lignes = json.loads(brut)
except json.JSONDecodeError:
    lignes = [json.loads(ligne) for ligne in brut.splitlines() if ligne.strip()]
if isinstance(lignes, dict):
    lignes = [lignes]
if not isinstance(lignes, list) or any(
    not isinstance(ligne, dict) or not isinstance(ligne.get("Service"), str) or not ligne["Service"]
    for ligne in lignes
):
    raise SystemExit(1)
postgres = [ligne for ligne in lignes if ligne["Service"] == "postgres"]
if len(postgres) > 1 or (postgres and postgres[0].get("State") not in ("exited", "created")):
    raise SystemExit(1)
'; then
        die "arrêt de PostgreSQL non confirmé; aucun fichier n'a été modifié."
    fi
else
    compose stop "${SERVICES_A_ARRETER[@]}" || die "impossible d'arrêter les services avant restauration; aucun fichier n'a été modifié."
fi
RESTORE_WRITING=1
trap 'warn "échec inattendu après le début des écritures; rollback automatique absent, les services restent arrêtés. Restaurez une sauvegarde complète et vérifiée avec --from avant de redémarrer la pile."' ERR

restore_volume() {
    local logique="$1" volume file
    volume="$(volume_name "$logique")"
    file="$(volume_archive "$logique")" || die "archive du volume $logique absente — restauration interrompue."
    docker volume create "$volume" >/dev/null
    log "restauration du volume $logique depuis $file..."
    docker run --rm -i --user 0 --entrypoint sh -v "$volume:/volume" "$VOLUME_TOOL_IMAGE" \
        -c 'find /volume -mindepth 1 -maxdepth 1 -exec rm -rf {} + && tar -C /volume -xzf -' < "$file"
    log "volume $logique restauré."
}

# -- Bases Postgres -------------------------------------------------------------------------------
restore_db() {
    local db="$1" file="$FROM/postgres-${1}.sql.gz"
    [ -s "$file" ] || die "$file absent — restauration interrompue; aucun redémarrage automatique."
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
if [[ "$FORMAT" = "format=opsys-backup/3" || "$FORMAT" = "format=opsys-backup/4" ]]; then
    if grep -q '^required=postgres:' "$FROM/MANIFEST.txt"; then
        compose up -d --wait postgres
    fi
    for ressource in $(sed -n 's/^required=postgres://p' "$FROM/MANIFEST.txt"); do restore_db "$ressource"; done
    for ressource in $(sed -n 's/^required=volume://p' "$FROM/MANIFEST.txt"); do restore_volume "$ressource"; done
    for ressource in $(sed -n 's/^optional=volume://p' "$FROM/MANIFEST.txt"); do
        if volume_archive "$ressource" >/dev/null 2>&1; then restore_volume "$ressource"; fi
    done
else
    # Formats antérieurs : contrat conservé, deux dumps et les cinq volumes requis.
    # PostgreSQL a été arrêté avec les autres services : attendre sa santé avant tout SQL.
    compose up -d --wait postgres
    restore_db opsys
    restore_db litellm
    restore_volume opsys_data
    restore_volume openclaw_config
    restore_volume openclaw_auth_secrets
    restore_volume litellm_config
    restore_volume caddy_data
fi

log "redémarrage des services..."
compose up -d
RESTORE_WRITING=0
trap - ERR

log "PREUVE : restauration depuis $FROM terminée. Vérifiez : docker compose -f deploy/docker-compose.yml ps"
