#!/usr/bin/env bash
# deploy/backup.sh — sauvegarde des bases et volumes réellement utilisés par le profil.
#
# Usage : deploy/backup.sh [--out DIR] [--retention-days N]
# Rétention locale par défaut : 14 jours. Copie distante optionnelle si RESTIC_REPOSITORY est
# défini dans deploy/.env (voir docs/ops/EXPLOITATION.md — préférer un stockage S3-compatible
# hébergé au Canada, Loi 25).
set -euo pipefail
umask 077

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
# Refusé avant tout effet : find ignorait silencieusement une valeur invalide (|| true).
[[ "$RETENTION_DAYS" =~ ^[0-9]{1,5}$ ]] || {
    echo "--retention-days invalide : '$RETENTION_DAYS' (entier de 0 à 99999 jours requis)." >&2; exit 2; }

log()  { printf '[backup] %s\n' "$*"; }
warn() { printf '[backup] AVERTISSEMENT : %s\n' "$*" >&2; }
die()  { printf '[backup] ERREUR : %s\n' "$*" >&2; exit 1; }

[ -f "$SCRIPT_DIR/.env" ] || die ".env introuvable — copiez .env.example et exécutez install.sh d'abord."
# shellcheck disable=SC1091
set -a; . "$SCRIPT_DIR/.env"; set +a

MODE="${OPSYS_MODE_FOURNISSEUR:-natif}"
case "$MODE" in natif|litellm) ;; *) echo "OPSYS_MODE_FOURNISSEUR invalide : $MODE" >&2; exit 2 ;; esac
DB_ACTIVE=0
if [ "$MODE" = litellm ] || [[ "${OPSYS_DATABASE_URL:-}" =~ ^postgres(ql)?:// ]]; then DB_ACTIVE=1; fi
OPSYS_DB_BACKEND=sqlite
if [[ "${OPSYS_DATABASE_URL:-}" =~ ^postgres(ql)?:// ]]; then OPSYS_DB_BACKEND=postgres; fi

compose() {
    if [ "$MODE" = litellm ]; then
        docker compose --profile litellm --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    elif [ "$DB_ACTIVE" -eq 1 ]; then
        docker compose --profile database --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    else
        docker compose --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    fi
}

# Une archive de SQLite/WAL et des volumes doit se faire sans écrivain concurrent.
# On reprend uniquement les services qui tournaient, sans créer/recréer de conteneur.
STOP_SECONDS="${OPSYS_BACKUP_STOP_TIMEOUT_SECONDS:-45}"
START_SECONDS="${OPSYS_BACKUP_START_TIMEOUT_SECONDS:-90}"
for secondes in "$STOP_SECONDS" "$START_SECONDS"; do
    [[ "$secondes" =~ ^[1-9][0-9]{0,2}$ ]] && [ "$secondes" -le 300 ] ||
        die "délais stop/start invalides (entiers de 1 à 300 secondes requis)."
done
command -v timeout >/dev/null 2>&1 || die "timeout (GNU coreutils) requis avant toute sauvegarde."
command -v flock >/dev/null 2>&1 || die "flock (util-linux) requis avant toute sauvegarde."
# Verrou commun même si deux appels choisissent des dossiers de sortie différents.
# Le script est seulement ouvert en lecture : aucun fichier de verrou n'est créé.
exec {BACKUP_LOCK_FD}<"$SCRIPT_DIR/backup.sh"
flock -n "$BACKUP_LOCK_FD" || die "une autre sauvegarde utilise déjà ce script; aucun arrêt effectué."

# Une commande interrompue ne prouve pas que le démon a terminé ses effets.
# Garde commune à toutes les sorties, conservée tant que la reprise n'est pas confirmée.
INTENTION_ARRET="$SCRIPT_DIR/.opsys-backup-intention.json"
INTENTION_NONCE=""
if [ -e "$INTENTION_ARRET" ] || [ -L "$INTENTION_ARRET" ]; then
    die "intention de quiescence inconnue conservée : $INTENTION_ARRET; assistance requise, aucun nouvel effet."
fi

intention_arret() {
    local action="$1"; shift
    python3 -I - "$action" "$INTENTION_ARRET" "$@" <<'PY_INTENTION'
import json, os, stat, sys, uuid
from pathlib import Path

action, nom, *arguments = sys.argv[1:]
chemin = Path(nom)
dossier = os.open(chemin.parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    if action == "creer":
        nonce = uuid.uuid4().hex
        donnees = {"version": 1, "type": "opsys-backup-quiescence", "nonce": nonce,
                   "destination": arguments[0], "services": arguments[1:]}
        fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fichier:
            json.dump(donnees, fichier, ensure_ascii=False)
            fichier.write("\n")
            fichier.flush()
            os.fsync(fichier.fileno())
        os.fsync(dossier)
        print(nonce)
    elif action == "effacer":
        fd = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            proprietaire = os.fstat(fd)
            if not stat.S_ISREG(proprietaire.st_mode) or proprietaire.st_uid != os.geteuid():
                raise SystemExit("intention sans propriétaire régulier")
            if stat.S_IMODE(proprietaire.st_mode) != 0o600:
                raise SystemExit("permissions de l'intention modifiées")
            brut = os.read(fd, 65537)
            if len(brut) > 65536:
                raise SystemExit("intention trop volumineuse")
            donnees = json.loads(brut)
            if (donnees.get("type") != "opsys-backup-quiescence" or donnees.get("version") != 1
                    or donnees.get("nonce") != arguments[0]):
                raise SystemExit("intention différente conservée")
            courant = os.stat(chemin, follow_symlinks=False)
            if (courant.st_dev, courant.st_ino) != (proprietaire.st_dev, proprietaire.st_ino):
                raise SystemExit("intention remplacée conservée")
            os.unlink(chemin)
            os.fsync(dossier)
        finally:
            os.close(fd)
    else:
        raise SystemExit("opération d'intention invalide")
finally:
    os.close(dossier)
PY_INTENTION
}

compose_borne() {
    local secondes="$1"; shift
    if [ "$MODE" = litellm ]; then
        timeout --kill-after=5s "${secondes}s" docker compose --profile litellm \
            --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    elif [ "$DB_ACTIVE" -eq 1 ]; then
        timeout --kill-after=5s "${secondes}s" docker compose --profile database \
            --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    else
        timeout --kill-after=5s "${secondes}s" docker compose \
            --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml" "$@"
    fi
}

observer_services() {
    local observation attente="${1:-0}" secondes="${2:-30}"
    [ "$secondes" -le 30 ] || secondes=30
    observation="$(compose_borne "$secondes" ps --all --format json)" || return 1
    printf '%s' "$observation" | python3 -c '
import json, sys
brut = sys.stdin.read()
try:
    lignes = json.loads(brut)
except json.JSONDecodeError:
    lignes = [json.loads(ligne) for ligne in brut.splitlines() if ligne.strip()]
if isinstance(lignes, dict):
    lignes = [lignes]
if not isinstance(lignes, list) or any(not isinstance(ligne, dict) for ligne in lignes):
    raise SystemExit(1)
for service in ("opsys", "openclaw-gateway", "caddy", "litellm", "postgres"):
    candidats = [ligne for ligne in lignes if ligne.get("Service") == service]
    if len(candidats) > 1:
        raise SystemExit(1)  # start(service) ne préserverait pas des répliques arrêtées
    if not candidats:
        print(service, "absent", "none")
        continue
    etat = candidats[0].get("State")
    sante = candidats[0].get("Health") or "none"
    santes_permises = ("none", "healthy", "starting") if sys.argv[1] == "1" else ("none", "healthy")
    if etat not in ("running", "exited", "created") or sante not in santes_permises:
        raise SystemExit(1)  # paused/restarting/dead/starting/unhealthy : reprise assistée
    print(service, etat, sante)
' "$attente"
}

A_REPRENDRE=()
REPRISE_NECESSAIRE=0
reprendre_services() {
    [ "$REPRISE_NECESSAIRE" -eq 1 ] || return 0
    REPRISE_NECESSAIRE=0  # une seule tentative, y compris si la reprise échoue
    log "reprise des seuls services initialement actifs : ${A_REPRENDRE[*]}"
    local limite=$((SECONDS + START_SECONDS)) observation service etat sante attendu reste pret
    # Compose start ne propose pas --wait. Ne pas utiliser up, qui recréerait des conteneurs.
    if ! compose_borne "$START_SECONDS" start "${A_REPRENDRE[@]}"; then
        warn "reprise en échec ou hors délai; archives conservées, reprise assistée requise."
        return 1
    fi
    while :; do
        reste=$((limite - SECONDS))
        [ "$reste" -gt 0 ] || { warn "reprise hors délai; archives conservées."; return 1; }
        observation="$(observer_services 1 "$reste")" || { warn "reprise non vérifiable; archives conservées."; return 1; }
        pret=1
        while read -r service etat sante; do
            for attendu in "${A_REPRENDRE[@]}"; do
                if [ "$service" = "$attendu" ]; then
                    [ "$etat" = running ] || { warn "reprise de $service non confirmée; archives conservées."; return 1; }
                    [ "$sante" != starting ] || pret=0
                fi
            done
        done <<< "$observation"
        [ "$((limite - SECONDS))" -gt 0 ] || { warn "reprise hors délai; archives conservées."; return 1; }
        if [ "$pret" -ne 0 ]; then
            intention_arret effacer "$INTENTION_NONCE" || {
                warn "reprise observée mais intention non réconciliée; assistance requise."
                return 1
            }
            return 0
        fi
        sleep 0.2
    done
}

fin_sauvegarde() {
    local code="$?"
    trap - EXIT INT TERM
    reprendre_services || code=1
    exit "$code"
}

quiescer_services() {
    local observation service etat sante attendu
    observation="$(observer_services)" || die "état des services ambigu, transitoire ou inaccessible; aucun arrêt effectué."
    while read -r service etat sante; do
        if [ "$service" = postgres ] && [ "$DB_ACTIVE" -eq 1 ]; then
            [ "$etat" = running ] || die "PostgreSQL requis mais arrêté/absent; aucun service n'a été démarré."
        elif [ "$etat" = running ]; then
            A_REPRENDRE+=("$service")
        fi
    done <<< "$observation"
    [ "${#A_REPRENDRE[@]}" -gt 0 ] || return 0
    INTENTION_NONCE="$(intention_arret creer "$DEST" "${A_REPRENDRE[@]}")" ||
        die "impossible de conserver l'intention avant arrêt; aucun stop effectué."
    trap fin_sauvegarde EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    log "arrêt borné des écrivains initialement actifs : ${A_REPRENDRE[*]}"
    if ! compose_borne "$STOP_SECONDS" stop --timeout "$STOP_SECONDS" "${A_REPRENDRE[@]}"; then
        die "résultat d'arrêt inconnu; intention conservée, aucune archive ni reprise automatique; assistance requise."
    fi
    # Seule la fin confirmée du STOP autorise la compensation, même après erreur d'archive.
    REPRISE_NECESSAIRE=1
    observation="$(observer_services)" || die "arrêt non vérifiable; aucune archive produite."
    while read -r service etat sante; do
        for attendu in "${A_REPRENDRE[@]}"; do
            [ "$service" != "$attendu" ] || [ "$etat" = exited ] ||
                die "écrivain $service encore actif/absent; aucune archive produite."
        done
    done <<< "$observation"
}

# L'image OPSYS locale fournit tar pour les profils natifs sans télécharger Postgres.
VOLUME_TOOL_IMAGE="${OPSYS_BACKUP_IMAGE:-opsys:local}"

volume_name() {
    local logical="$1" configuration nom
    local profils=()
    # config omet les volumes des services exclus par profil, même si leur ancien volume existe.
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

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT_DIR/$STAMP"
mkdir -p "$OUT_DIR" || die "impossible de créer le dossier de sauvegarde $OUT_DIR."
chmod 700 "$OUT_DIR" || die "impossible de protéger le dossier de sauvegarde $OUT_DIR."
mkdir -m 700 "$DEST" || die "le dossier de sauvegarde existe déjà ou ne peut pas être créé : $DEST."
chmod 700 "$DEST" || die "impossible de protéger le dossier de sauvegarde $DEST."
log "sauvegarde $STAMP -> $DEST"

FAIL=0
ARCHIVES=()
REQUIRED=()
OPTIONAL=()
quiescer_services

# -- Bases Postgres (dump SQL clair, compressé) ----------------------------------------------------
dump_db() {
    local db="$1" file="$DEST/postgres-${1}.sql.gz"
    REQUIRED+=("postgres:$db")
    if compose exec -T postgres pg_dump -U opsys -d "$db" | gzip -9 > "$file"; then
        chmod 600 "$file"
        log "pg_dump $db -> $file ($(du -h "$file" | cut -f1))"
        ARCHIVES+=("${file##*/}")
    else
        warn "pg_dump $db a échoué."
        rm -f "$file"
        FAIL=1
    fi
}
if [ "$DB_ACTIVE" -eq 1 ] && [[ "${OPSYS_DATABASE_URL:-}" =~ ^postgres(ql)?:// ]]; then dump_db opsys; fi
if [ "$MODE" = litellm ]; then dump_db litellm; fi

# -- Volumes de données (archives tar.gz depuis leur point de montage réel) ------------------------
archive_volume() {
    local logique="$1" volume file="$DEST/volume-${1}.tar.gz" required="${2:-required}"
    if [ "$required" = required ]; then REQUIRED+=("volume:$logique"); fi
    volume="$(volume_name "$logique")"
    if ! docker volume inspect "$volume" >/dev/null 2>&1; then
        if [ "$required" = required ]; then
            warn "volume $volume introuvable — sauvegarde incomplète."
            FAIL=1
        fi
        return
    fi
    if docker run --rm --user 0 --entrypoint sh -v "$volume:/volume:ro" "$VOLUME_TOOL_IMAGE" \
        -c 'tar -C /volume -czf - .' > "$file"; then
        chmod 600 "$file"
        log "volume $volume -> $file ($(du -h "$file" | cut -f1))"
        ARCHIVES+=("${file##*/}")
        if [ "$required" = optional ]; then OPTIONAL+=("volume:$logique"); fi
    else
        warn "archivage du volume $volume a échoué."
        rm -f "$file"
        FAIL=1
    fi
}
# Volumes permanents communs aux profils natif et compatibilité.
archive_volume opsys_data
archive_volume openclaw_config
archive_volume openclaw_auth_secrets
archive_volume caddy_data
archive_volume caddy_config

# La config LiteLLM reste sauvegardée lorsqu'elle existe déjà, même après un retour au profil natif.
if [ "$MODE" = litellm ]; then
    archive_volume litellm_config required
else
    archive_volume litellm_config optional
fi

# Un volume Postgres historique est conservé en mode natif SQLite seulement. Avec un backend
# PostgreSQL actif, le dump logique est la source de restauration; rejouer aussi l'archive physique
# après le dump écraserait cette base et pourrait restaurer une génération différente.
if [ "$MODE" != litellm ] && [ "$OPSYS_DB_BACKEND" != postgres ]; then
    archive_volume postgres_data optional
fi

{
    echo "format=opsys-backup/4"
    echo "stamp=$STAMP"
    echo "mode=$MODE"
    echo "database=$OPSYS_DB_BACKEND"
    for ressource in "${REQUIRED[@]}"; do echo "required=$ressource"; done
    for ressource in "${OPTIONAL[@]}"; do echo "optional=$ressource"; done
    for archive in "${ARCHIVES[@]}"; do echo "archive=$archive"; done
    echo "genere_le=$(date -u -Iseconds)"
    for logique in opsys_data openclaw_config openclaw_auth_secrets litellm_config caddy_data caddy_config postgres_data; do
        echo "volume_name.$logique=$(volume_name "$logique")"
    done
} > "$DEST/MANIFEST.txt"
chmod 600 "$DEST/MANIFEST.txt"
python3 -I -B - "$DEST" "${ARCHIVES[@]}" <<'PY_INTEGRITE'
import hashlib, json, os, sys
from pathlib import Path

dossier = Path(sys.argv[1])
fichiers = {}
for nom in ["MANIFEST.txt", *sys.argv[2:]]:
    empreinte = hashlib.sha256()
    taille = 0
    with (dossier / nom).open("rb") as source:
        while morceau := source.read(1024 * 1024):
            empreinte.update(morceau)
            taille += len(morceau)
    fichiers[nom] = {"sha256": empreinte.hexdigest(), "octets": taille}
fd = os.open(dossier / "INTEGRITE.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as sortie:
    json.dump({"format": "opsys-backup-integrity/1", "fichiers": fichiers}, sortie, sort_keys=True)
    sortie.write("\n")
PY_INTEGRITE
reprendre_services || die "sauvegarde conservée mais reprise des services non confirmée."

# -- Rétention locale ---------------------------------------------------------------------------
# --out peut contenir d'autres données : seule une sauvegarde OPSYS positivement identifiée est
# purgée. Tout doute (nom, lien, propriétaire, manifeste, format futur, fichier étranger) conserve.
log "purge des sauvegardes OPSYS identifiées de plus de ${RETENTION_DAYS} jours dans $OUT_DIR..."
if ! python3 -I -B - "$OUT_DIR" "$STAMP" "$RETENTION_DAYS" <<'PY_RETENTION'
import os, re, stat, sys, time

racine, actif, jours = sys.argv[1], sys.argv[2], int(sys.argv[3])
HORODATAGE = re.compile(r"[0-9]{8}T[0-9]{6}Z")
ARCHIVE = re.compile(r"(postgres-[A-Za-z0-9][A-Za-z0-9_.-]*\.sql\.gz|volume-[A-Za-z0-9][A-Za-z0-9_.-]*\.tar\.gz)")
FORMATS = {"format=opsys-backup/2", "format=opsys-backup/3", "format=opsys-backup/4"}
LIMITE = 65536
seuil = time.time() - (jours + 1) * 86400  # même borne que l'ancien find -mtime +N
erreurs = 0

def avertir(message):
    print("[backup] AVERTISSEMENT : " + message, file=sys.stderr)

def lire_manifeste(dossier_fd):
    fd = os.open("MANIFEST.txt", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dossier_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("manifeste non régulier")
        brut = b""
        while len(brut) <= LIMITE and (morceau := os.read(fd, LIMITE + 1 - len(brut))):
            brut += morceau
    finally:
        os.close(fd)
    if not brut or len(brut) > LIMITE:
        raise ValueError("manifeste vide ou trop grand")
    return brut.decode("utf-8").splitlines()

def refus(nom, dossier_fd, noms):
    """Motif de conservation, ou None si le dossier est une sauvegarde OPSYS v1 à v4 reconnue."""
    if os.fstat(dossier_fd).st_uid != os.geteuid():
        return "propriétaire différent"
    for entree in noms:
        if not stat.S_ISREG(os.stat(entree, dir_fd=dossier_fd, follow_symlinks=False).st_mode):
            return "entrée non régulière : " + entree
        if entree not in ("MANIFEST.txt", "INTEGRITE.json") and not ARCHIVE.fullmatch(entree):
            return "fichier étranger : " + entree
    if "MANIFEST.txt" not in noms:
        return "MANIFEST.txt absent"
    lignes = lire_manifeste(dossier_fd)
    entete = lignes[0] if lignes else ""
    archives = {entree for entree in noms if ARCHIVE.fullmatch(entree)}
    if entete == nom:  # format historique v1 : première ligne = horodatage du dossier
        return "INTEGRITE.json inattendu (v1)" if "INTEGRITE.json" in noms else None
    if entete not in FORMATS:
        return "format de sauvegarde inconnu ou non pris en charge"
    horodatages = [ligne[len("stamp="):] for ligne in lignes if ligne.startswith("stamp=")]
    if len(horodatages) > 1 or (horodatages and horodatages[0] != nom):
        return "horodatage du manifeste discordant"
    if entete == "format=opsys-backup/4" and (not horodatages or "INTEGRITE.json" not in noms):
        return "manifeste v4 incomplet"
    if entete != "format=opsys-backup/4" and "INTEGRITE.json" in noms:
        return "INTEGRITE.json inattendu avant v4"
    if not archives <= {ligne[len("archive="):] for ligne in lignes if ligne.startswith("archive=")}:
        return "archive non déclarée au manifeste"
    return None

def supprimer(nom, dossier_fd, identite, noms_identifies):
    # Ne jamais élargir la suppression aux fichiers apparus après l'identification.
    # Un fichier nouveau fait échouer rmdir, et reste intact dans le dossier conservé.
    for entree in noms_identifies:
        if not stat.S_ISREG(os.stat(entree, dir_fd=dossier_fd, follow_symlinks=False).st_mode):
            raise OSError("entrée apparue pendant la purge : " + entree)
        os.unlink(entree, dir_fd=dossier_fd)
    courant = os.stat(nom, dir_fd=racine_fd, follow_symlinks=False)
    if (courant.st_dev, courant.st_ino) != identite:
        raise OSError("dossier remplacé pendant la purge")
    os.rmdir(nom, dir_fd=racine_fd)

try:
    racine_fd = os.open(racine, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
except OSError as erreur:
    avertir(f"rétention ignorée, dossier {racine} non ouvrable sans suivre de lien : {erreur.strerror}")
    raise SystemExit(1)
try:
    for nom in sorted(os.listdir(racine_fd)):
        chemin = os.path.join(racine, nom)
        info = os.stat(nom, dir_fd=racine_fd, follow_symlinks=False)
        if nom == actif or info.st_mtime >= seuil:
            continue
        if not stat.S_ISDIR(info.st_mode) or not HORODATAGE.fullmatch(nom):
            avertir(f"rétention : {chemin} conservé (pas une sauvegarde OPSYS)")
            continue
        try:
            dossier_fd = os.open(nom, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=racine_fd)
        except OSError as erreur:
            avertir(f"rétention : {chemin} conservé (non ouvrable : {erreur.strerror})")
            continue
        try:
            ouvert = os.fstat(dossier_fd)
            identite = (ouvert.st_dev, ouvert.st_ino)
            try:
                noms_identifies = os.listdir(dossier_fd)
                motif = "dossier remplacé" if identite != (info.st_dev, info.st_ino) else refus(nom, dossier_fd, noms_identifies)
            except (OSError, ValueError) as erreur:
                motif = "lecture refusée : " + str(erreur)
            if motif:
                avertir(f"rétention : {chemin} conservé ({motif})")
                continue
            try:
                supprimer(nom, dossier_fd, identite, noms_identifies)
                print(f"[backup] sauvegarde expirée supprimée : {chemin}")
            except OSError as erreur:
                erreurs += 1
                avertir(f"rétention : suppression de {chemin} en échec ({erreur}); contenu restant conservé")
        finally:
            os.close(dossier_fd)
finally:
    os.close(racine_fd)
raise SystemExit(1 if erreurs else 0)
PY_RETENTION
then
    warn "rétention locale incomplète; les sauvegardes non purgées restent en place."
    FAIL=1
fi

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
        FAIL=1
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
