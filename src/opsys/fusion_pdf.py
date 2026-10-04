"""Préparation PDF native locale : provenance paginée, sources/résultats chiffrés.

Linux/bubblewrap et SQLite uniquement. Aucun montant interprété, registre M5 ou
mémoire générale alimenté. Le quota PDF est distinct du compartiment CSV.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import sysconfig
import uuid
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from time import monotonic
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.exc import OperationalError

from . import etat, fusion_csv, identite, stockage
from .stockage.schema import FUSION_PDF_COMMANDES, FUSION_PDF_LOTS, FUSION_PDF_QUOTA

FusionPDFErreur = fusion_csv.FusionErreur
FabriqueConnexion = fusion_csv.FabriqueConnexion
SOURCE_MAX = 1_048_576
PAGES_MAX = 20
TEXTE_MAX = 262_144
SORTIE_MAX = 524_288
STDERR_MAX = 8_192
NB_LOTS_MAX = 16
QUOTA_CIPHER_MAX = 16_777_216
WALL_SECONDES = 15.0
EXTRACTEUR = "pypdf-6.19.0/pdf-natif-1"
CONFIGURATION = (
    "pdf-natif-1;linux-bwrap;source=1048576;pages=20;decoded-page=2097152;"
    "decoded-total=8388608;text=262144;stdout=524288;as=536870912;cpu=10;wall=15"
)
CONFIGURATION_SHA256 = hashlib.sha256(CONFIGURATION.encode()).hexdigest()
_CHEMIN_WORKER = Path(__file__).with_name("fusion_pdf_worker.py")
_SOURCE_AAD = "pdf-natif-1:source"
_RESULTAT_AAD = "pdf-natif-1:resultat"
_TEMPORAIRES = frozenset({
    "PDF_ISOLATION_INDISPONIBLE", "PDF_LIMITES_INDISPONIBLES", "PDF_DEPENDANCE_INDISPONIBLE",
    "PDF_TIMEOUT", "PDF_SORTIE_EXCESSIVE", "PDF_PROTOCOLE_INVALIDE", "PDF_RESULTAT_INVALIDE",
})
_REFUS = frozenset({
    "PDF_CHIFFRE", "PDF_ACTIF", "PDF_PAGES_BORNEES", "PDF_CONTENU_BORNE", "PDF_IMAGE_OU_MIXTE",
    "PDF_AMBIGU", "PDF_SANS_TEXTE", "PDF_TEXTE_BORNE", "PDF_SOURCE_BORNEE", "PDF_MEMOIRE_BORNEE",
    "PDF_MALFORME", "PDF_AVERTISSEMENT", "PDF_SORTIE_BORNEE",
})


def _erreur(code: str, statut: int = 409) -> FusionPDFErreur:
    return FusionPDFErreur(code, "opération PDF refusée ou temporairement indisponible", statut)


@contextmanager
def _transaction(fabrique: FabriqueConnexion, acteur: str):
    if sys.platform != "linux":
        raise _erreur("PDF_ISOLATION_INDISPONIBLE", 503)
    if not identite.identifiant_valide(acteur):
        raise _erreur("ACTEUR_INVALIDE", 400)
    if stockage.connexion_courante() is not None:
        raise _erreur("PDF_TRANSACTION_IMBRIQUEE")
    try:
        with fabrique() as cnx:
            fusion_csv._isoler_transaction(cnx)
            # La fabrique doit ouvrir une vraie transaction du stockage courant.
            if stockage.connexion_courante() is not cnx:
                raise _erreur("PDF_TRANSACTION_NON_QUALIFIEE")
            fusion_csv._exiger_personne(cnx, acteur)
            yield cnx
            fusion_csv._exiger_personne(cnx, acteur)
    except OperationalError as exc:
        raise fusion_csv._erreur_verrou(exc) from exc


def _lot(cnx, lot_id: str) -> dict[str, Any]:
    try:
        valide = isinstance(lot_id, str) and str(uuid.UUID(lot_id)) == lot_id
    except ValueError:
        valide = False
    if not valide:
        raise _erreur("LOT_INCONNU", 404)
    row = cnx.execute(select(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id)).mappings().one_or_none()
    if row is None:
        raise _erreur("LOT_INCONNU", 404)
    return dict(row)


def _compatible(lot: Mapping[str, Any]) -> None:
    if (
        lot["version_format"] != 1 or lot["extracteur"] != EXTRACTEUR
        or lot["configuration_sha256"] != CONFIGURATION_SHA256
        or lot["type_source"] != "pdf_natif" or lot["classe"] != "FINANCIAL"
    ):
        raise _erreur("PDF_VERSION_INCOMPATIBLE")


def _vue(lot: Mapping[str, Any]) -> dict[str, Any]:
    return {cle: lot[cle] for cle in (
        "lot_id", "acteur", "type_source", "classe", "source_sha256", "source_octets", "extracteur",
        "configuration_sha256", "statut", "revision", "total_pages", "code", "cree_le", "modifie_le",
    )}


def _journal(cnx, acteur: str, lot: Mapping[str, Any]) -> None:
    etat.journaliser(cnx, acteur, "fusion.pdf." + lot["statut"].lower(), lot["lot_id"], {
        cle: lot[cle] for cle in ("source_sha256", "extracteur", "revision", "statut", "total_pages", "code")
    })


def _clair(lot: Mapping[str, Any], nature: str) -> bytes:
    prefixe = "source" if nature == _SOURCE_AAD else "resultat"
    octets = lot[prefixe + "_cipher_octets"]
    plafond = SOURCE_MAX + 16 if prefixe == "source" else SORTIE_MAX + 16
    chiffre, nonce = lot[prefixe + "_cipher"], lot[prefixe + "_nonce"]
    if (
        type(octets) is not int or not 16 < octets <= plafond or not isinstance(chiffre, str)
        or len(chiffre) != 4 * ((octets + 2) // 3) or not isinstance(nonce, str) or len(nonce) != 16
    ):
        raise _erreur("CIPHER_INVALIDE")
    clair = fusion_csv._dechiffrer(fusion_csv._cle(lot["cle_reference"]), lot, nature, nonce, chiffre)
    if len(clair) + 16 != octets:
        raise _erreur("CIPHER_INVALIDE")
    return clair


def _source(lot: Mapping[str, Any]) -> bytes:
    source = _clair(lot, _SOURCE_AAD)
    if len(source) != lot["source_octets"] or hashlib.sha256(source).hexdigest() != lot["source_sha256"]:
        raise _erreur("SOURCE_CORROMPUE")
    return source


def _objet_json(contenu: bytes) -> Any:
    def sans_doublons(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError("doublon JSON")
            resultat[cle] = valeur
        return resultat
    try:
        return json.loads(contenu, object_pairs_hook=sans_doublons)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise _erreur("PDF_PROTOCOLE_INVALIDE") from exc


def _valider_resultat(resultat: Any, source_sha: str) -> dict[str, Any]:
    invalide = _erreur("PDF_RESULTAT_INVALIDE")
    if (
        not isinstance(resultat, dict)
        or set(resultat) != {"schema_version", "source_sha256", "extracteur", "configuration_sha256", "pages"}
        or type(resultat["schema_version"]) is not int or resultat["schema_version"] != 1
        or resultat["source_sha256"] != source_sha or resultat["extracteur"] != EXTRACTEUR
        or resultat["configuration_sha256"] != CONFIGURATION_SHA256
        or not isinstance(resultat["pages"], list) or not 1 <= len(resultat["pages"]) <= PAGES_MAX
    ):
        raise invalide
    taille = 0
    for numero, page in enumerate(resultat["pages"], 1):
        if (
            not isinstance(page, dict) or set(page) != {"numero", "fragments"}
            or type(page["numero"]) is not int or page["numero"] != numero
            or not isinstance(page["fragments"], list) or len(page["fragments"]) != 1
        ):
            raise invalide
        fragment = page["fragments"][0]
        if (
            not isinstance(fragment, dict) or set(fragment) != {"id", "texte", "sha256"}
            or fragment["id"] != f"p{numero}-f1" or not isinstance(fragment["texte"], str)
            or not fragment["texte"].strip() or "\ufffd" in fragment["texte"]
            or any(ord(c) < 32 and c not in "\n\r\t" for c in fragment["texte"])
        ):
            raise invalide
        try:
            texte = fragment["texte"].encode("utf-8")
        except UnicodeEncodeError as exc:
            raise invalide from exc
        taille += len(texte)
        if taille > TEXTE_MAX or hashlib.sha256(texte).hexdigest() != fragment["sha256"]:
            raise invalide
    return resultat


def _resultat(lot: Mapping[str, Any]) -> dict[str, Any]:
    resultat = _valider_resultat(_objet_json(_clair(lot, _RESULTAT_AAD)), lot["source_sha256"])
    if len(resultat["pages"]) != lot["total_pages"]:
        raise _erreur("PDF_RESULTAT_INVALIDE")
    return resultat


def creer(fabrique: FabriqueConnexion, acteur: str, *, mutation_id: str, pdf_octets: bytes) -> dict[str, Any]:
    if not identite.identifiant_valide(acteur):
        raise _erreur("ACTEUR_INVALIDE", 400)
    if not isinstance(mutation_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", mutation_id):
        raise _erreur("MUTATION_INVALIDE", 400)
    if type(pdf_octets) is not bytes or not 1 <= len(pdf_octets) <= SOURCE_MAX or not pdf_octets.startswith(b"%PDF-"):
        raise _erreur("PDF_SOURCE_INVALIDE", 400)
    source_sha = hashlib.sha256(pdf_octets).hexdigest()
    empreinte = hashlib.sha256(f"{acteur}:{source_sha}:{EXTRACTEUR}:{CONFIGURATION_SHA256}".encode()).hexdigest()
    with _transaction(fabrique, acteur) as cnx:
        commande = cnx.execute(select(FUSION_PDF_COMMANDES).where(
            (FUSION_PDF_COMMANDES.c.acteur == acteur) & (FUSION_PDF_COMMANDES.c.mutation_id == mutation_id)
        )).mappings().one_or_none()
        if commande is not None:
            if commande["empreinte_requete"] != empreinte:
                raise _erreur("CONFLIT_MUTATION")
            lot = _lot(cnx, commande["lot_id"])
            _compatible(lot)
            fusion_csv._cle(lot["cle_reference"])
            return _vue(lot)
        existant = cnx.execute(select(FUSION_PDF_LOTS).where(
            FUSION_PDF_LOTS.c.cle_deduplication == empreinte
        )).mappings().one_or_none()
        maintenant = fusion_csv._maintenant()
        if existant is not None:
            lot = dict(existant)
            _compatible(lot)
            fusion_csv._cle(lot["cle_reference"])
        else:
            reference = fusion_csv._reference_cle()
            lot_id = str(uuid.uuid4())
            nonce, chiffre, octets = fusion_csv._chiffrer(
                fusion_csv._cle(reference), lot_id, source_sha, _SOURCE_AAD, pdf_octets,
            )
            reserve = cnx.execute(update(FUSION_PDF_QUOTA).where(
                (FUSION_PDF_QUOTA.c.id == 1) & (FUSION_PDF_QUOTA.c.lots < NB_LOTS_MAX)
                & (FUSION_PDF_QUOTA.c.octets_cipher + octets <= QUOTA_CIPHER_MAX)
            ).values(lots=FUSION_PDF_QUOTA.c.lots + 1, octets_cipher=FUSION_PDF_QUOTA.c.octets_cipher + octets))
            if reserve.rowcount != 1:
                raise _erreur("PDF_QUOTA_ATTEINT")
            lot = {
                "lot_id": lot_id, "acteur": acteur, "mutation_id": mutation_id, "empreinte_requete": empreinte,
                "cle_deduplication": empreinte, "type_source": "pdf_natif", "classe": "FINANCIAL",
                "extracteur": EXTRACTEUR, "configuration_sha256": CONFIGURATION_SHA256,
                "source_sha256": source_sha, "source_octets": len(pdf_octets), "source_nonce": nonce,
                "source_cipher": chiffre, "source_cipher_octets": octets, "resultat_nonce": None,
                "resultat_cipher": None, "resultat_cipher_octets": 0, "cle_reference": reference,
                "version_format": 1, "statut": "RECU", "revision": 1, "total_pages": 0, "code": None,
                "cree_le": maintenant, "modifie_le": maintenant,
            }
            cnx.execute(insert(FUSION_PDF_LOTS).values(**lot))
            _journal(cnx, acteur, lot)
        cnx.execute(insert(FUSION_PDF_COMMANDES).values(
            acteur=acteur, mutation_id=mutation_id, empreinte_requete=empreinte,
            lot_id=lot["lot_id"], cree_le=maintenant,
        ))
        return _vue(lot)


def _geometrie_lecture_isolee() -> tuple[Path, frozenset[Path], Path, tuple[tuple[Path, Path, bool], ...]]:
    """Sources RO du worker : géométrie pure, sans bwrap, parser ni exécution."""
    usr = Path("/usr").resolve(strict=True)
    prefixes = frozenset({Path(sys.prefix).resolve(strict=True), Path(sys.base_prefix).resolve(strict=True)})
    worker = _CHEMIN_WORKER.resolve()
    bibliotheques = []
    for nom in ("lib", "lib64"):
        dossier = Path("/" + nom)
        if dossier.exists():
            bibliotheques.append((dossier, dossier.resolve(), dossier.is_symlink()))
    return usr, prefixes, worker, tuple(bibliotheques)


def _commande_isolee() -> list[str]:
    bwrap = shutil.which("bwrap")
    if sys.platform != "linux" or bwrap is None:
        raise _erreur("PDF_ISOLATION_INDISPONIBLE", 503)
    try:
        usr, prefixes, worker, bibliotheques = _geometrie_lecture_isolee()
        interpreteur = Path(sys.executable)
        cible = interpreteur.resolve(strict=True)
        stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _erreur("PDF_ISOLATION_INDISPONIBLE", 503) from exc
    base = Path(sys.base_prefix)
    venv = Path(sys.prefix)
    interdits = {Path(p) for p in (
        "/", "/workspace", "/home", "/tmp", "/var", "/opt", "/dev", "/proc", "/etc", "/root", "/run", "/sys",
    )} | {Path.home().resolve()}
    if (
        usr != Path("/usr") or not interpreteur.is_absolute() or not worker.is_file()
        or any(not p.is_dir() or p in interdits for p in prefixes)
        or base not in prefixes or venv not in prefixes or not stdlib.is_relative_to(base)
        or (venv != base and not (venv / "pyvenv.cfg").is_file())
        or not any(cible.is_relative_to(p) for p in prefixes | {usr})
        or not any(interpreteur.is_relative_to(p) for p in prefixes | {usr})
    ):
        raise _erreur("PDF_ISOLATION_INDISPONIBLE", 503)
    commande = [
        str(Path(bwrap).resolve()), "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
        "--ro-bind", "/usr", "/usr",
    ]
    for dossier in sorted(prefixes):
        if not dossier.is_relative_to(usr):
            commande.extend(["--ro-bind", str(dossier), str(dossier)])
    for dossier, canonique, est_lien in bibliotheques:
        if est_lien and canonique.is_relative_to(usr):
            commande.extend(["--symlink", str(canonique.relative_to(Path("/"))), str(dossier)])
        elif canonique == dossier:
            commande.extend(["--ro-bind", str(dossier), str(dossier)])
        else:
            raise _erreur("PDF_ISOLATION_INDISPONIBLE", 503)
    commande.extend([
        "--ro-bind", str(worker), "/worker.py", "--proc", "/proc", "--dev", "/dev",
        "--tmpfs", "/tmp", "--chdir", "/tmp", str(interpreteur), "-I", "/worker.py",
    ])
    return commande


def _executer_borne(commande: list[str], source: bytes) -> bytes:
    fin = monotonic() + WALL_SECONDES
    try:
        processus = subprocess.Popen(
            commande, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, env={}, close_fds=True, start_new_session=True,
        )
    except OSError as exc:
        raise _erreur("PDF_ISOLATION_INDISPONIBLE", 503) from exc
    selecteur = None
    sortie, erreurs = bytearray(), bytearray()
    curseur = 0
    try:
        selecteur = selectors.DefaultSelector()
        for canal, evenement, nature in (
            (processus.stdin, selectors.EVENT_WRITE, "entree"),
            (processus.stdout, selectors.EVENT_READ, "sortie"),
            (processus.stderr, selectors.EVENT_READ, "erreurs"),
        ):
            os.set_blocking(canal.fileno(), False)
            selecteur.register(canal, evenement, nature)
        while selecteur.get_map():
            reste = fin - monotonic()
            if reste <= 0:
                raise _erreur("PDF_TIMEOUT", 503)
            for cle, _ in selecteur.select(min(reste, 0.1)):
                canal = cle.fileobj
                if cle.data == "entree":
                    try:
                        curseur += os.write(canal.fileno(), source[curseur:curseur + 65_536])
                    except BrokenPipeError:
                        curseur = len(source)
                    except BlockingIOError:
                        continue
                    if curseur == len(source):
                        selecteur.unregister(canal)
                        canal.close()
                else:
                    try:
                        donnees = os.read(canal.fileno(), 65_536)
                    except BlockingIOError:
                        continue
                    if not donnees:
                        selecteur.unregister(canal)
                        canal.close()
                        continue
                    tampon = sortie if cle.data == "sortie" else erreurs
                    tampon.extend(donnees)
                    plafond = SORTIE_MAX if cle.data == "sortie" else STDERR_MAX
                    if len(tampon) > plafond:
                        raise _erreur("PDF_SORTIE_EXCESSIVE", 503)
        try:
            code = processus.wait(timeout=max(0.001, fin - monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise _erreur("PDF_TIMEOUT", 503) from exc
        if code != 0:
            raise _erreur("PDF_ISOLATION_INDISPONIBLE", 503)
        if erreurs:
            raise _erreur("PDF_PROTOCOLE_INVALIDE", 503)
        return bytes(sortie)
    except OSError as exc:
        raise _erreur("PDF_ISOLATION_INDISPONIBLE", 503) from exc
    finally:
        if selecteur is not None:
            selecteur.close()
        if processus.poll() is None:
            with suppress(OSError):
                os.killpg(processus.pid, signal.SIGKILL)
            with suppress(ProcessLookupError):
                processus.kill()
        processus.wait()
        for canal in (processus.stdin, processus.stdout, processus.stderr):
            canal.close()


def _extraire_isole(source: bytes) -> dict[str, Any]:
    reponse = _objet_json(_executer_borne(_commande_isolee(), source))
    if not isinstance(reponse, dict) or type(reponse.get("ok")) is not bool:
        raise _erreur("PDF_PROTOCOLE_INVALIDE", 503)
    if reponse["ok"]:
        if set(reponse) != {"ok", "resultat"}:
            raise _erreur("PDF_PROTOCOLE_INVALIDE", 503)
        _valider_resultat(reponse["resultat"], hashlib.sha256(source).hexdigest())
    elif (
        set(reponse) != {"ok", "code"} or not isinstance(reponse["code"], str)
        or reponse["code"] not in _REFUS | _TEMPORAIRES
    ):
        raise _erreur("PDF_PROTOCOLE_INVALIDE", 503)
    return reponse


def preparer(fabrique: FabriqueConnexion, acteur: str, lot_id: str, revision_attendue: int) -> dict[str, Any]:
    if type(revision_attendue) is not int or revision_attendue < 1:
        raise _erreur("REVISION_INVALIDE", 400)
    with _transaction(fabrique, acteur) as cnx:
        lot = _lot(cnx, lot_id)
        _compatible(lot)
        if lot["revision"] != revision_attendue:
            raise _erreur("CONFLIT_REVISION")
        if lot["statut"] == "EXTRAIT_PREPARATOIRE":
            _resultat(lot)  # Reprise du résultat authentifié, sans parser de nouveau.
            return _vue(lot)
        if lot["statut"] == "REFUSE":
            return _vue(lot)
        source = _source(lot)
    # Aucune connexion / transaction SQLite n'est conservée pendant le worker.
    try:
        reponse = _extraire_isole(source)
    except FusionPDFErreur as exc:
        if exc.code not in _TEMPORAIRES:
            raise
        reponse = {"ok": False, "code": exc.code}
    with _transaction(fabrique, acteur) as cnx:
        courant = _lot(cnx, lot_id)
        _compatible(courant)
        if (
            courant["revision"] != revision_attendue or courant["source_sha256"] != lot["source_sha256"]
            or courant["source_nonce"] != lot["source_nonce"] or courant["source_cipher"] != lot["source_cipher"]
        ):
            raise _erreur("CONFLIT_REVISION")
        _source(courant)  # Intégrité et clé revalidées après le travail isolé.
        valeurs: dict[str, Any] = {
            "revision": revision_attendue + 1, "modifie_le": fusion_csv._maintenant(), "total_pages": 0,
            "resultat_nonce": None, "resultat_cipher": None, "resultat_cipher_octets": 0,
        }
        if reponse["ok"]:
            resultat = _valider_resultat(reponse["resultat"], lot["source_sha256"])
            contenu = fusion_csv._json(resultat).encode("utf-8")
            if len(contenu) > SORTIE_MAX:
                raise _erreur("PDF_RESULTAT_INVALIDE")
            nonce, chiffre, octets = fusion_csv._chiffrer(
                fusion_csv._cle(courant["cle_reference"]), lot_id, lot["source_sha256"], _RESULTAT_AAD, contenu,
            )
            reserve = cnx.execute(update(FUSION_PDF_QUOTA).where(
                (FUSION_PDF_QUOTA.c.id == 1) & (FUSION_PDF_QUOTA.c.octets_cipher + octets <= QUOTA_CIPHER_MAX)
            ).values(octets_cipher=FUSION_PDF_QUOTA.c.octets_cipher + octets))
            if reserve.rowcount != 1:
                raise _erreur("PDF_QUOTA_ATTEINT")
            valeurs.update(
                statut="EXTRAIT_PREPARATOIRE", code=None, total_pages=len(resultat["pages"]),
                resultat_nonce=nonce, resultat_cipher=chiffre, resultat_cipher_octets=octets,
            )
        else:
            valeurs.update(
                statut="ERREUR_REPRENABLE" if reponse["code"] in _TEMPORAIRES else "REFUSE", code=reponse["code"],
            )
        ecrit = cnx.execute(update(FUSION_PDF_LOTS).where(
            (FUSION_PDF_LOTS.c.lot_id == lot_id) & (FUSION_PDF_LOTS.c.revision == revision_attendue)
            & (FUSION_PDF_LOTS.c.source_sha256 == lot["source_sha256"])
        ).values(**valeurs))
        if ecrit.rowcount != 1:
            raise _erreur("CONFLIT_REVISION")
        courant.update(valeurs)
        _journal(cnx, acteur, courant)
        return _vue(courant)


def lire(fabrique: FabriqueConnexion, acteur: str, lot_id: str) -> dict[str, Any]:
    with _transaction(fabrique, acteur) as cnx:
        return _vue(_lot(cnx, lot_id))


def lire_resultat(fabrique: FabriqueConnexion, acteur: str, lot_id: str) -> dict[str, Any]:
    """Lecture privée admin : texte préparatoire seulement, aucune écriture métier."""
    with _transaction(fabrique, acteur) as cnx:
        lot = _lot(cnx, lot_id)
        _compatible(lot)
        if lot["statut"] != "EXTRAIT_PREPARATOIRE":
            raise _erreur("PDF_RESULTAT_INDISPONIBLE")
        return _resultat(lot)


def lister(fabrique: FabriqueConnexion, acteur: str, *, limite: int = 16) -> list[dict[str, Any]]:
    if type(limite) is not int or not 1 <= limite <= NB_LOTS_MAX:
        raise _erreur("LIMITE_INVALIDE", 400)
    with _transaction(fabrique, acteur) as cnx:
        rows = cnx.execute(select(FUSION_PDF_LOTS).order_by(FUSION_PDF_LOTS.c.cree_le.desc()).limit(limite))
        return [_vue(row._mapping) for row in rows]
