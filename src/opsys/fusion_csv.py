"""Import durable et chiffré de relevés CSV pour les propositions préparatoires M5."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic as _monotonic
from typing import Any

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import OperationalError

from . import etat, identite, stockage
from .console import banque_metier
from .departements import Departement
from .stockage.schema import FUSION_COMMANDES, FUSION_LIGNES, FUSION_LOTS, FUSION_QUOTA

ENV_CLE = "OPSYS_INGESTION_CLE"
ENV_REFERENCE_CLE = "OPSYS_INGESTION_CLE_REFERENCE"
ENV_FICHIER_CLES = "OPSYS_INGESTION_ENV_FILE"
ENV_CLES_HISTORIQUES = "OPSYS_INGESTION_CLES_HISTORIQUES"
_FICHIER_CLES_MAX = 8192
TAILLE_SOURCE_MAX = 1_048_576
NB_LOTS_MAX = 64
QUOTA_CIPHER_MAX = 67_108_864
RESULTAT_CIPHER_MAX = 4_194_304
LIGNES_PAR_TRANCHE = 100
PREPARATION_MAX_TRANCHES = 20
PREPARATION_BUDGET_SECONDES = 8.0
PREPARATION_BUDGET_TRANCHE_SECONDES = 2.0
VERSION_FORMAT = 1
_CHAMPS_MAPPING = frozenset({"date", "montant", "reference_facture"})
FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]


class FusionErreur(ValueError):
    """Erreur métier bornée, sans donnée de cellule."""

    def __init__(self, code: str, detail: str, statut_http: int = 409):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.statut_http = statut_http

    def publique(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


def _maintenant() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _json(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(valeur: bytes | str) -> str:
    return hashlib.sha256(valeur.encode("utf-8") if isinstance(valeur, str) else valeur).hexdigest()


def _decoder_cle(valeur: str) -> bytes:
    try:
        cle = base64.b64decode(valeur.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError):
        cle = b""
    if len(cle) != 32:
        raise FusionErreur("CLE_INDISPONIBLE", "clé externe absente ou invalide; aucune donnée n'a été écrite", 503)
    return cle


def _reference_reservee(reference: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", reference) and (
        reference == ENV_CLE
        or re.fullmatch(r"OPSYS_(?:CLE_(?:INGESTION|PDF|CSV)|INGESTION_CLE)_[A-Z0-9_]+", reference)
    ))


def _erreur_fichier_cles() -> FusionErreur:
    return FusionErreur("FICHIER_CLES_INVALIDE", "fichier privé de clés d'ingestion invalide ou inaccessible", 503)


def _lire_fichier_cles() -> dict[str, str]:
    """Un seul loader, Linux opt-in, sans export env, cache ni mutation du fichier opérateur."""
    nom = os.environ.get(ENV_FICHIER_CLES, "")
    if not nom:
        return {}
    if sys.platform != "linux":
        raise _erreur_fichier_cles()
    descripteur = None
    try:
        chemin = Path(nom)
        if (not chemin.is_absolute() or "\n" in nom or "\r" in nom
                or chemin.resolve() != chemin or chemin.is_symlink()):
            raise _erreur_fichier_cles()
        # Import lazy : fusion_pdf dépend de ce module, mais le CSV n'exécute jamais bwrap.
        from .fusion_pdf import _geometrie_lecture_isolee

        usr, prefixes, worker, bibliotheques = _geometrie_lecture_isolee()
        racines = {usr, *prefixes, *(canonique for _, canonique, _ in bibliotheques)}
        if chemin == worker or any(chemin.is_relative_to(racine) or chemin.parent.is_relative_to(racine)
                                   for racine in racines):
            raise _erreur_fichier_cles()
        parent = chemin.parent.stat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise _erreur_fichier_cles()
        descripteur = os.open(chemin, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        avant = os.fstat(descripteur)
        if (not stat.S_ISREG(avant.st_mode) or avant.st_uid != os.geteuid()
                or stat.S_IMODE(avant.st_mode) != 0o600 or avant.st_size > _FICHIER_CLES_MAX):
            raise _erreur_fichier_cles()
        donnees = bytearray()
        while len(donnees) <= _FICHIER_CLES_MAX:
            morceau = os.read(descripteur, _FICHIER_CLES_MAX + 1 - len(donnees))
            if not morceau:
                break
            donnees.extend(morceau)
        apres = os.fstat(descripteur)
        courant = chemin.stat(follow_symlinks=False)
        parent_apres = chemin.parent.stat()
        attributs = ("st_dev", "st_ino", "st_uid", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(donnees) > _FICHIER_CLES_MAX
                or any(getattr(avant, a) != getattr(apres, a) or getattr(avant, a) != getattr(courant, a)
                       for a in attributs)
                or any(getattr(parent, a) != getattr(parent_apres, a)
                       for a in ("st_dev", "st_ino", "st_uid", "st_mode"))
                or chemin.resolve() != chemin):
            raise _erreur_fichier_cles()
        valeurs: dict[str, str] = {}
        for ligne in donnees.decode("utf-8").splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#"):
                continue
            cle, separateur, valeur = ligne.partition("=")
            if not separateur or cle in valeurs or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", cle):
                raise _erreur_fichier_cles()
            valeurs[cle] = valeur
        reference = valeurs.get(ENV_REFERENCE_CLE, ENV_CLE)
        historique = valeurs.get(ENV_CLES_HISTORIQUES, "").split(",") if valeurs.get(ENV_CLES_HISTORIQUES) else []
        references = [reference, *historique]
        if (len(references) > 16 or len(set(references)) != len(references)
                or not all(_reference_reservee(r) for r in references)
                or set(valeurs) - {ENV_REFERENCE_CLE, ENV_CLES_HISTORIQUES, *references}
                or any(not valeurs.get(r) for r in historique)):
            raise _erreur_fichier_cles()
        for r in references:
            if valeurs.get(r):
                _decoder_cle(valeurs[r])
        return valeurs
    except FileNotFoundError:
        if descripteur is not None:
            raise _erreur_fichier_cles() from None
        return {}  # Paramètre opérateur absent ; le gate vérifie encore le worker avant rc3.
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, FusionErreur):
            raise
        raise _erreur_fichier_cles() from None
    finally:
        if descripteur is not None:
            os.close(descripteur)


def _valeur_cle(reference: str) -> str:
    if not os.environ.get(ENV_FICHIER_CLES):
        return os.environ.get(reference, "")
    valeurs = _lire_fichier_cles()
    active = valeurs.get(ENV_REFERENCE_CLE, ENV_CLE)
    historiques = valeurs.get(ENV_CLES_HISTORIQUES, "").split(",") if valeurs.get(ENV_CLES_HISTORIQUES) else []
    if reference not in {active, *historiques} or not _reference_reservee(reference):
        raise _erreur_fichier_cles()
    valeur = valeurs.get(reference, "")
    if reference in os.environ and os.environ[reference] != valeur:
        raise FusionErreur("FICHIER_CLES_CONFLIT", "environnement et fichier privé d'ingestion en conflit", 503)
    return valeur


def _cle(reference: str = ENV_CLE) -> bytes:
    return _decoder_cle(_valeur_cle(reference))


def _reference_cle() -> str:
    if os.environ.get(ENV_FICHIER_CLES):
        reference = _lire_fichier_cles().get(ENV_REFERENCE_CLE, ENV_CLE)
        if ENV_REFERENCE_CLE in os.environ and os.environ[ENV_REFERENCE_CLE] != reference:
            raise FusionErreur("FICHIER_CLES_CONFLIT", "référence environnement et fichier privé en conflit", 503)
    else:
        reference = os.environ.get(ENV_REFERENCE_CLE, ENV_CLE)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", reference):
        raise FusionErreur("REFERENCE_CLE_INVALIDE", "référence externe de clé invalide", 503)
    return reference


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise FusionErreur(
            "CHIFFREMENT_INDISPONIBLE", "installer l'extra OPSYS ingestion pour chiffrer les lots", 503
        ) from exc
    return AESGCM


def _aad(lot_id: str, source_sha256: str, nature: str, version: int) -> bytes:
    if version != VERSION_FORMAT:
        raise FusionErreur("FORMAT_NON_SUPPORTE", "version de format de lot non prise en charge")
    return f"opsys-fusion-csv:v{version}:{lot_id}:{source_sha256}:{nature}".encode("ascii")


def _chiffrer(
    cle: bytes, lot_id: str, source_sha256: str, nature: str, contenu: bytes,
    version: int = VERSION_FORMAT,
) -> tuple[str, str, int]:
    nonce = secrets.token_bytes(12)
    chiffre = _aesgcm()(cle).encrypt(nonce, contenu, _aad(lot_id, source_sha256, nature, version))
    return base64.b64encode(nonce).decode("ascii"), base64.b64encode(chiffre).decode("ascii"), len(chiffre)


def _dechiffrer(cle: bytes, lot: Mapping[str, Any], nature: str, nonce: str, chiffre: str) -> bytes:
    aad = _aad(lot["lot_id"], lot["source_sha256"], nature, lot["version_format"])
    try:
        aesgcm = _aesgcm()
        from cryptography.exceptions import InvalidTag
    except FusionErreur:
        raise
    except ImportError as exc:
        raise FusionErreur("CHIFFREMENT_INDISPONIBLE", "primitive de déchiffrement indisponible", 503) from exc
    try:
        clair = aesgcm(cle).decrypt(
            base64.b64decode(nonce, validate=True), base64.b64decode(chiffre, validate=True),
            aad,
        )
    except (InvalidTag, ValueError, TypeError) as exc:
        raise FusionErreur("CIPHER_INVALIDE", "source ou résultat chiffré corrompu; lecture refusée") from exc
    return clair


def _dictionnaire(row: Any) -> dict[str, Any]:
    return dict(row._mapping if hasattr(row, "_mapping") else row)


def _exiger_personne(cnx: Connection, acteur: str):
    personne = identite.personne_active(cnx, acteur)
    if personne is None or not personne.roles.intersection({"nathan_owner", "admin"}):
        raise PermissionError("administrateur actif requis")
    return personne


def _isoler_transaction(cnx: Connection) -> None:
    if cnx.dialect.name != "sqlite":
        raise FusionErreur(
            "STOCKAGE_NON_QUALIFIE", "Fusion opérationnelle est qualifiée SQLite seulement", 503
        )


def _est_verrou_occupe(exc: OperationalError) -> bool:
    origine = getattr(exc, "orig", None)
    code = getattr(origine, "sqlite_errorcode", None)
    message = str(origine).lower()
    verrou = code is not None and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    marqueurs = ("database is locked", "database is busy", "table is locked")
    return verrou or any(fragment in message for fragment in marqueurs)


def _erreur_verrou(exc: OperationalError) -> FusionErreur:
    if _est_verrou_occupe(exc):
        return FusionErreur("STOCKAGE_OCCUPE", "stockage temporairement occupé; rechargez le lot", 503)
    raise exc


def _snapshot():
    from m5_financecore import facturation
    from m5_financecore import registre as registre_m5

    _, snapshot = banque_metier._lire_factures(registre_m5, facturation)
    if snapshot.get("total_complet") is not True:
        raise FusionErreur("VUE_FACTURES_INDISPONIBLE", "vue complète des créances M5 indisponible")
    return snapshot


def _snapshot_ident(snapshot: Mapping[str, Any]) -> str:
    return _hash(_json({"version": snapshot["version"], "empreinte": snapshot["empreinte"]}))


def _verifier_snapshot(lot: Mapping[str, Any]) -> bool:
    courant = _snapshot()
    return courant["version"] == lot["snapshot_version"] and courant["empreinte"] == lot["snapshot_empreinte"]


def _provenance(cnx: Connection, lot: Mapping[str, Any], *, statut: str) -> None:
    from m10_memoire import provenance_documentaire

    registre_m10 = stockage.maillons("m10-memoire", "documents")
    precedente = provenance_documentaire.lire(registre_m10, lot["lot_id"])
    document = {
        "type_entree": "provenance_documentaire",
        "genre": "m5.releve_bancaire_csv",
        "lot_id": lot["lot_id"],
        "reference_locale": f"opsys-ingestion://m05-financecore/lots/{lot['lot_id']}",
        "source_sha256": lot["source_sha256"],
        "classe": "FINANCIAL",
        "auteur": lot["acteur"],
        "snapshot_version": lot["snapshot_version"],
        "snapshot_empreinte": lot["snapshot_empreinte"],
        "compte_interne_id": lot["compte_interne_id"],
        "total_lignes": lot["total_lignes"] or 0,
        "nombre_propositions": lot["nombre_propositions"],
        "revision": 1 if precedente is None else precedente["revision"] + 1,
        "statut": statut,
        "horodatage": lot["modifie_le"],
    }
    provenance_documentaire.enregistrer(registre_m10, document)


def _maj_snapshot_obsolete(cnx: Connection, lot: dict[str, Any], acteur: str) -> dict[str, Any]:
    if lot["statut"] == "SNAPSHOT_OBSOLETE":
        return lot
    lot["statut"] = "SNAPSHOT_OBSOLETE"
    lot["revision"] += 1
    lot["modifie_le"] = _maintenant()
    cnx.execute(update(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot["lot_id"]).values(
        statut=lot["statut"], revision=lot["revision"], modifie_le=lot["modifie_le"],
    ))
    _provenance(cnx, lot, statut=lot["statut"])
    etat.journaliser(cnx, acteur, "console.fusion_csv.snapshot_obsolete", lot["lot_id"], {
        "source_sha256": lot["source_sha256"], "snapshot_version": lot["snapshot_version"],
        "snapshot_empreinte": lot["snapshot_empreinte"], "revision": lot["revision"],
    })
    return lot


def _vue_lot(lot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lot_id": lot["lot_id"], "source_sha256": lot["source_sha256"], "source_octets": lot["source_octets"],
        "compte_interne_id": lot["compte_interne_id"], "devise": lot["devise"],
        "snapshot_version": lot["snapshot_version"], "snapshot_empreinte": lot["snapshot_empreinte"],
        "statut": lot["statut"], "revision": lot["revision"], "curseur": lot["curseur"],
        "total_lignes": lot["total_lignes"], "nombre_propositions": lot["nombre_propositions"],
        "verdict": json.loads(lot["verdict"]) if lot["verdict"] else None,
        "cree_le": lot["cree_le"], "modifie_le": lot["modifie_le"], "classe": "FINANCIAL",
    }


def creer(
    cnx_factory: FabriqueConnexion, deps: Mapping[str, Departement], acteur: str, *, mutation_id: str,
    compte_interne_id: str, devise: str, mapping_colonnes: Mapping[str, str], csv_octets: bytes,
) -> dict[str, Any]:
    if not isinstance(mutation_id, str) or not mutation_id.strip() or len(mutation_id) > 128:
        raise FusionErreur("MUTATION_INVALIDE", "mutation_id invalide", 400)
    if not isinstance(compte_interne_id, str) or not compte_interne_id.strip() or len(compte_interne_id) > 64:
        raise FusionErreur("COMPTE_INVALIDE", "compte interne invalide", 400)
    if devise != "CAD":
        raise FusionErreur("DEVISE_NON_CAD", "seuls les relevés CAD sont pris en charge", 400)
    if (not isinstance(mapping_colonnes, Mapping) or set(mapping_colonnes) != _CHAMPS_MAPPING
            or any(not isinstance(value, str) or not value or len(value) > 128 for value in mapping_colonnes.values())
            or len(set(mapping_colonnes.values())) != 3):
        raise FusionErreur("MAPPING_INVALIDE", "mapping explicite des trois colonnes requis", 400)
    if not isinstance(csv_octets, bytes) or not csv_octets or len(csv_octets) > TAILLE_SOURCE_MAX:
        raise FusionErreur("SOURCE_TROP_GROSSE", "source CSV vide ou supérieure à 1 Mio", 413)
    try:
        csv_octets.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise FusionErreur("CSV_UTF8_INVALIDE", "la source doit être un CSV UTF-8", 400) from exc
    if not isinstance(acteur, str) or not acteur:
        raise PermissionError("administrateur actif requis")

    mapping = dict(mapping_colonnes)
    source_sha = _hash(csv_octets)
    empreinte_requete = _hash(_json({
        "compte_interne_id": compte_interne_id, "devise": devise, "mapping_colonnes": mapping,
        "source_sha256": source_sha,
    }))
    lot_id = str(uuid.uuid4())
    with cnx_factory() as cnx:
        _isoler_transaction(cnx)
        personne = _exiger_personne(cnx, acteur)
        comptes = banque_metier.comptes_configures(deps)
        if compte_interne_id not in comptes:
            raise FusionErreur("COMPTE_NON_CONFIGURE", "compte interne absent de l'allowlist")
        # Ce verrou rend atomicité mutation/dédup et admission quota en PostgreSQL.
        cnx.execute(select(FUSION_QUOTA).where(FUSION_QUOTA.c.id == 1).with_for_update()).one()
        snapshot = _snapshot()
        dedup = _hash(_json({
            "requete": empreinte_requete, "snapshot_version": snapshot["version"],
            "snapshot_empreinte": snapshot["empreinte"],
        }))
        mutation = mutation_id.strip()
        commande = cnx.execute(select(FUSION_COMMANDES).where(
            (FUSION_COMMANDES.c.acteur == personne.identifiant) & (FUSION_COMMANDES.c.mutation_id == mutation)
        )).one_or_none()
        if commande is not None:
            if commande.empreinte_requete != empreinte_requete:
                raise FusionErreur("CONFLIT_MUTATION", "mutation déjà utilisée avec un contenu différent")
            lot_row = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == commande.lot_id)).one()
            lot = _dictionnaire(lot_row)
            if not _verifier_snapshot(lot):
                lot = _maj_snapshot_obsolete(cnx, lot, acteur)
            _exiger_personne(cnx, acteur)
            return _vue_lot(lot)
        existant = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.cle_deduplication == dedup)).one_or_none()
        if existant is not None:
            _cle(_reference_cle())
            _aesgcm()
            lot = _dictionnaire(existant)
            cnx.execute(insert(FUSION_COMMANDES).values(
                acteur=personne.identifiant, mutation_id=mutation, empreinte_requete=empreinte_requete,
                lot_id=lot["lot_id"], cree_le=_maintenant(),
            ))
            etat.journaliser(cnx, personne.identifiant, "console.fusion_csv.dedup", lot["lot_id"], {
                "source_sha256": source_sha, "snapshot_empreinte": snapshot["empreinte"],
                "mutation_id": mutation, "revision": lot["revision"],
            })
            _exiger_personne(cnx, acteur)
            return _vue_lot(lot)

        # La clé et la primitive sont vérifiées avant toute mutation en base.
        reference_cle = _reference_cle()
        cle = _cle(reference_cle)
        _aesgcm()
        nonce, source_cipher, source_cipher_octets = _chiffrer(cle, lot_id, source_sha, "source", csv_octets)
        reservation = cnx.execute(
            update(FUSION_QUOTA)
            .where(
                (FUSION_QUOTA.c.id == 1) & (FUSION_QUOTA.c.lots < NB_LOTS_MAX)
                & (FUSION_QUOTA.c.octets_cipher + source_cipher_octets <= QUOTA_CIPHER_MAX)
            )
            .values(lots=FUSION_QUOTA.c.lots + 1, octets_cipher=FUSION_QUOTA.c.octets_cipher + source_cipher_octets)
        )
        if reservation.rowcount != 1:
            raise FusionErreur("QUOTA_ATTEINT", "quota d'ingestion atteint; aucun lot n'a été créé")
        maintenant = _maintenant()
        cnx.execute(insert(FUSION_LOTS).values(
            lot_id=lot_id, acteur=personne.identifiant, mutation_id=mutation,
            empreinte_requete=empreinte_requete, cle_deduplication=dedup,
            compte_interne_id=compte_interne_id, devise=devise, mapping_colonnes=_json(mapping),
            source_sha256=source_sha, source_octets=len(csv_octets), source_nonce=nonce,
            source_cipher=source_cipher, source_cipher_octets=source_cipher_octets,
            resultat_nonce=None, resultat_cipher=None, resultat_cipher_octets=0,
            cle_reference=reference_cle, version_format=VERSION_FORMAT,
            snapshot_version=snapshot["version"], snapshot_empreinte=snapshot["empreinte"],
            statut="RECU", revision=1, curseur=0, total_lignes=None, nombre_propositions=0,
            verdict=None, cree_le=maintenant, modifie_le=maintenant,
        ))
        cnx.execute(insert(FUSION_COMMANDES).values(
            acteur=personne.identifiant, mutation_id=mutation, empreinte_requete=empreinte_requete,
            lot_id=lot_id, cree_le=maintenant,
        ))
        etat.journaliser(cnx, personne.identifiant, "console.fusion_csv.cree", lot_id, {
            "source_sha256": source_sha, "snapshot_empreinte": snapshot["empreinte"],
            "source_octets": len(csv_octets), "compte_interne_id": compte_interne_id,
            "mutation_id": mutation,
        })
        personne = _exiger_personne(cnx, acteur)
        if not _verifier_snapshot({
            "snapshot_version": snapshot["version"], "snapshot_empreinte": snapshot["empreinte"],
        }):
            raise FusionErreur("SNAPSHOT_FACTURES_PERIME", "snapshot de factures a changé pendant la création")
        return _vue_lot({
            "lot_id": lot_id, "acteur": personne.identifiant, "source_sha256": source_sha,
            "source_octets": len(csv_octets), "compte_interne_id": compte_interne_id, "devise": devise,
            "snapshot_version": snapshot["version"], "snapshot_empreinte": snapshot["empreinte"],
            "statut": "RECU", "revision": 1, "curseur": 0, "total_lignes": None,
            "nombre_propositions": 0, "verdict": None, "cree_le": maintenant, "modifie_le": maintenant,
        })


def _retourner_valide(cnx: Connection, acteur: str, lot: Mapping[str, Any]) -> dict[str, Any]:
    _exiger_personne(cnx, acteur)
    if not _verifier_snapshot(lot):
        return _vue_lot(_maj_snapshot_obsolete(cnx, dict(lot), acteur))
    _exiger_personne(cnx, acteur)
    return _vue_lot(lot)


def traiter(cnx_factory: FabriqueConnexion, acteur: str, lot_id: str, revision_attendue: int) -> dict[str, Any]:
    if type(revision_attendue) is not int or revision_attendue < 1:
        raise FusionErreur("REVISION_INVALIDE", "revision_attendue invalide", 400)
    with cnx_factory() as cnx:
        _isoler_transaction(cnx)
        _exiger_personne(cnx, acteur)
        row = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot_id).with_for_update()).one_or_none()
        if row is None:
            raise FusionErreur("LOT_INCONNU", "lot inconnu", 404)
        lot = _dictionnaire(row)
        if lot["revision"] != revision_attendue:
            raise FusionErreur("CONFLIT_REVISION", "le lot a changé; rechargez son état")
        if lot["statut"] == "SNAPSHOT_OBSOLETE":
            _exiger_personne(cnx, acteur)
            return _vue_lot(lot)
        if not _verifier_snapshot(lot):
            _exiger_personne(cnx, acteur)
            return _vue_lot(_maj_snapshot_obsolete(cnx, lot, acteur))
        if lot["statut"] in {"REFUSE", "PROPOSITIONS", "AUCUNE_PROPOSITION"}:
            return _retourner_valide(cnx, acteur, lot)

        cle = _cle(lot["cle_reference"])
        if lot["resultat_cipher"] is None:
            source = _dechiffrer(cle, lot, "source", lot["source_nonce"], lot["source_cipher"])
            if len(source) != lot["source_octets"] or _hash(source) != lot["source_sha256"]:
                raise FusionErreur("SOURCE_CORROMPUE", "source corrompue; aucun résultat n'a été produit")
            from m5_financecore import reconciliation_bancaire_csv

            resultat, verdict = reconciliation_bancaire_csv.previsualiser_releve_csv(
                source, compte_interne_id=lot["compte_interne_id"], devise=lot["devise"],
                mapping_colonnes=json.loads(lot["mapping_colonnes"]), snapshot_factures=_snapshot(),
            )
            _exiger_personne(cnx, acteur)
            if not _verifier_snapshot(lot):
                return _vue_lot(_maj_snapshot_obsolete(cnx, lot, acteur))
            if verdict is not None or not isinstance(resultat, Mapping):
                lot.update(statut="REFUSE", revision=lot["revision"] + 1, verdict=_json(
                    {"code": verdict.get("code", "REJ-M53"), "detail": verdict.get("detail", "CSV refusé")}
                ), modifie_le=_maintenant(), total_lignes=0)
                cnx.execute(update(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot_id).values(
                    statut=lot["statut"], revision=lot["revision"], verdict=lot["verdict"],
                    modifie_le=lot["modifie_le"], total_lignes=0,
                ))
                _provenance(cnx, lot, statut=lot["statut"])
                etat.journaliser(cnx, acteur, "console.fusion_csv.refuse", lot_id, {
                    "source_sha256": lot["source_sha256"], "revision": lot["revision"],
                })
                return _retourner_valide(cnx, acteur, lot)
            contenu_resultat = _json(resultat).encode("utf-8")
            if len(contenu_resultat) > RESULTAT_CIPHER_MAX:
                raise FusionErreur("RESULTAT_TROP_GROS", "résultat normalisé supérieur au plafond sécurisé")
            nonce_resultat, cipher_resultat, octets_resultat = _chiffrer(
                cle, lot_id, lot["source_sha256"], "resultat", contenu_resultat, lot["version_format"]
            )
            reserve = cnx.execute(update(FUSION_QUOTA).where(
                (FUSION_QUOTA.c.id == 1)
                & (FUSION_QUOTA.c.octets_cipher + octets_resultat <= QUOTA_CIPHER_MAX)
            ).values(octets_cipher=FUSION_QUOTA.c.octets_cipher + octets_resultat))
            if reserve.rowcount != 1:
                raise FusionErreur("QUOTA_ATTEINT", "quota chiffré atteint; résultat non enregistré")
            lot["resultat_nonce"] = nonce_resultat
            lot["resultat_cipher"] = cipher_resultat
            lot["resultat_cipher_octets"] = octets_resultat
            lot["total_lignes"] = len(resultat["lignes"])
            lot["nombre_propositions"] = len(resultat["propositions"])
            lot["verdict"] = None
            if not resultat["lignes"]:
                raise FusionErreur("RESULTAT_INVALIDE", "le parseur a produit un résultat vide")
        else:
            clair = _dechiffrer(cle, lot, "resultat", lot["resultat_nonce"], lot["resultat_cipher"])
            resultat = json.loads(clair)
            _exiger_personne(cnx, acteur)
            if not isinstance(resultat, dict) or not isinstance(resultat.get("lignes"), list):
                raise FusionErreur("RESULTAT_CORROMPU", "résultat chiffré mal formé; reprise refusée")
        if lot["statut"] in {"REFUSE", "PROPOSITIONS", "AUCUNE_PROPOSITION"}:
            return _retourner_valide(cnx, acteur, lot)
        propositions = {item["ligne"] for item in resultat["propositions"]}
        lignes = resultat["lignes"]
        debut = lot["curseur"]
        tranche = lignes[debut:debut + LIGNES_PAR_TRANCHE]
        prepared = []
        bytes_ajoutes = 0
        for item in tranche:
            numero = item["numero"]
            nonce, cipher, cipher_octets = _chiffrer(
                cle, lot_id, lot["source_sha256"], f"ligne:{numero}", _json(item).encode("utf-8"),
                lot["version_format"],
            )
            prepared.append((numero, nonce, cipher, cipher_octets, numero in propositions))
            bytes_ajoutes += cipher_octets
        # Le résultat complet a déjà été chiffré et inclus dans le quota lors de cette transaction.
        if bytes_ajoutes:
            reservation = cnx.execute(update(FUSION_QUOTA).where(
                (FUSION_QUOTA.c.id == 1)
                & (FUSION_QUOTA.c.octets_cipher + bytes_ajoutes <= QUOTA_CIPHER_MAX)
            ).values(octets_cipher=FUSION_QUOTA.c.octets_cipher + bytes_ajoutes))
            if reservation.rowcount != 1:
                raise FusionErreur("QUOTA_ATTEINT", "quota chiffré atteint; tranche non enregistrée")
        for numero, nonce, cipher, cipher_octets, est_proposition in prepared:
            cnx.execute(insert(FUSION_LIGNES).values(
                lot_id=lot_id, numero=numero, nonce=nonce, cipher=cipher,
                cipher_octets=cipher_octets, est_proposition=est_proposition,
            ))
        count_propositions = lot["nombre_propositions"]
        curseur = debut + len(tranche)
        terminal = curseur >= lot["total_lignes"]
        statut = ("PROPOSITIONS" if count_propositions else "AUCUNE_PROPOSITION") if terminal else "EN_COURS"
        revision = lot["revision"] + 1
        modifie_le = _maintenant()
        maj = cnx.execute(update(FUSION_LOTS).where(
            (FUSION_LOTS.c.lot_id == lot_id) & (FUSION_LOTS.c.revision == lot["revision"])
        ).values(
            statut=statut, revision=revision, curseur=curseur, modifie_le=modifie_le,
            resultat_nonce=lot["resultat_nonce"], resultat_cipher=lot["resultat_cipher"],
            resultat_cipher_octets=lot["resultat_cipher_octets"], total_lignes=lot["total_lignes"],
            nombre_propositions=count_propositions,
        ))
        if maj.rowcount != 1:
            raise FusionErreur("CONFLIT_REVISION", "le lot a changé; rechargez son état")
        lot.update(statut=statut, revision=revision, curseur=curseur, modifie_le=modifie_le)
        etat.journaliser(cnx, acteur, "console.fusion_csv.tranche", lot_id, {
            "source_sha256": lot["source_sha256"], "debut": debut, "fin": curseur,
            "total_lignes": lot["total_lignes"], "nombre_propositions": count_propositions,
            "revision": revision, "statut": statut,
        })
        _exiger_personne(cnx, acteur)
        if not _verifier_snapshot(lot):
            return _vue_lot(_maj_snapshot_obsolete(cnx, lot, acteur))
        if terminal:
            _provenance(cnx, lot, statut=statut)
        return _retourner_valide(cnx, acteur, lot)


def _resume_preparation(
    cnx_factory: FabriqueConnexion, acteur: str, lot_id: str, revision_attendue: int,
) -> dict[str, Any]:
    """Projection sans cellules ni données comptables; CAS et snapshot sont relus en transaction."""
    with cnx_factory() as cnx:
        _isoler_transaction(cnx)
        _exiger_personne(cnx, acteur)
        row = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot_id).with_for_update()).one_or_none()
        if row is None:
            raise FusionErreur("LOT_INCONNU", "lot inconnu", 404)
        lot = _dictionnaire(row)
        if lot["revision"] != revision_attendue:
            raise FusionErreur("CONFLIT_REVISION", "le lot a changé; rechargez son état")
        if lot["statut"] != "SNAPSHOT_OBSOLETE" and not _verifier_snapshot(lot):
            lot = _maj_snapshot_obsolete(cnx, lot, acteur)
        _exiger_personne(cnx, acteur)
        if lot["statut"] != "SNAPSHOT_OBSOLETE" and not _verifier_snapshot(lot):
            lot = _maj_snapshot_obsolete(cnx, lot, acteur)
        _exiger_personne(cnx, acteur)
        return {
            "lot_id": lot["lot_id"], "statut": lot["statut"], "revision": lot["revision"],
            "curseur": lot["curseur"], "total_lignes": lot["total_lignes"],
            "nombre_propositions": 0 if lot["statut"] == "SNAPSHOT_OBSOLETE" else lot["nombre_propositions"],
        }


def relire_resume_preparation(
    cnx_factory: FabriqueConnexion, acteur: str, lot_id: str, revision_attendue: int,
) -> dict[str, Any]:
    """Revalidation de sortie sans déchiffrement, avec classification sûre des verrous SQLite."""
    try:
        return _resume_preparation(cnx_factory, acteur, lot_id, revision_attendue)
    except OperationalError as exc:
        erreur = _erreur_verrou(exc)
        if erreur is not exc:
            raise erreur from exc
        raise


def preparer(
    cnx_factory: FabriqueConnexion, acteur: str, lot_id: str, revision_attendue: int,
    stop_event: threading.Event,
) -> dict[str, Any]:
    """Enchaîne jusqu'à vingt transactions existantes; arrêts temporels coopératifs aux frontières."""
    if type(revision_attendue) is not int or revision_attendue < 1:
        raise FusionErreur("REVISION_INVALIDE", "revision_attendue invalide", 400)
    debut = _monotonic()
    executees = 0
    raison = "PLAFOND_ATTEINT"
    try:
        courant = _resume_preparation(cnx_factory, acteur, lot_id, revision_attendue)
        if courant["statut"] in {"SNAPSHOT_OBSOLETE", "REFUSE", "PROPOSITIONS", "AUCUNE_PROPOSITION"}:
            raison = "TERMINAL"
        else:
            revision = revision_attendue
            while executees < PREPARATION_MAX_TRANCHES:
                if stop_event.is_set():
                    raison = "ARRET_DEMANDE"
                    break
                if _monotonic() - debut >= PREPARATION_BUDGET_SECONDES:
                    raison = "BUDGET_TOTAL"
                    break
                tranche_debut = _monotonic()
                avant_curseur, avant_revision = courant["curseur"], courant["revision"]
                prochain = traiter(cnx_factory, acteur, lot_id, revision)
                executees += 1
                revision = prochain["revision"]
                if stop_event.is_set():
                    raison = "ARRET_DEMANDE"
                    break
                courant = _resume_preparation(cnx_factory, acteur, lot_id, prochain["revision"])
                revision = courant["revision"]
                if courant["statut"] in {"SNAPSHOT_OBSOLETE", "REFUSE", "PROPOSITIONS", "AUCUNE_PROPOSITION"}:
                    raison = "TERMINAL"
                    break
                if courant["curseur"] <= avant_curseur or courant["revision"] <= avant_revision:
                    raise FusionErreur(
                        "PREPARATION_SANS_PROGRESSION", "la tranche n'a pas fait progresser le lot; rechargez-le"
                    )
                if _monotonic() - tranche_debut >= PREPARATION_BUDGET_TRANCHE_SECONDES:
                    raison = "BUDGET_TRANCHE"
                    break
                if _monotonic() - debut >= PREPARATION_BUDGET_SECONDES:
                    raison = "BUDGET_TOTAL"
                    break
            courant = _resume_preparation(cnx_factory, acteur, lot_id, revision)
        return {
            "lot": courant,
            "preparation": {
                "tranches_executees": executees, "limite_tranches": PREPARATION_MAX_TRANCHES,
                "duree_ms": max(0, int((_monotonic() - debut) * 1000)), "arret": raison,
            },
        }
    except OperationalError as exc:
        erreur = _erreur_verrou(exc)
        if erreur is not exc:
            raise erreur from exc
        raise


def lire(cnx_factory: FabriqueConnexion, acteur: str, lot_id: str) -> dict[str, Any]:
    with cnx_factory() as cnx:
        _isoler_transaction(cnx)
        _exiger_personne(cnx, acteur)
        row = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot_id).with_for_update()).one_or_none()
        if row is None:
            raise FusionErreur("LOT_INCONNU", "lot inconnu", 404)
        lot = _dictionnaire(row)
        if not _verifier_snapshot(lot):
            lot = _maj_snapshot_obsolete(cnx, lot, acteur)
        resultat = _vue_lot(lot)
        resultat["lignes"] = []
        if lot["statut"] != "SNAPSHOT_OBSOLETE":
            cle = _cle(lot["cle_reference"])
            rows = cnx.execute(select(FUSION_LIGNES).where(FUSION_LIGNES.c.lot_id == lot_id)
                               .order_by(FUSION_LIGNES.c.numero)).all()
            for row_ligne in rows:
                ligne = _dictionnaire(row_ligne)
                clair = _dechiffrer(cle, lot, f"ligne:{ligne['numero']}", ligne["nonce"], ligne["cipher"])
                resultat["lignes"].append(json.loads(clair))
        _exiger_personne(cnx, acteur)
        if not _verifier_snapshot(lot):
            lot = _maj_snapshot_obsolete(cnx, lot, acteur)
            resultat = _vue_lot(lot)
            resultat["lignes"] = []
        _exiger_personne(cnx, acteur)
        return resultat


def lister(cnx_factory: FabriqueConnexion, acteur: str) -> list[dict[str, Any]]:
    with cnx_factory() as cnx:
        _isoler_transaction(cnx)
        _exiger_personne(cnx, acteur)
        lots = [_dictionnaire(row) for row in cnx.execute(
            select(FUSION_LOTS).order_by(FUSION_LOTS.c.cree_le.desc()).limit(NB_LOTS_MAX)
        ).all()]
        if not lots:
            _exiger_personne(cnx, acteur)
            return []
        snapshot = _snapshot()
        reponses = []
        for lot in lots:
            _exiger_personne(cnx, acteur)
            if (lot["snapshot_version"], lot["snapshot_empreinte"]) != (
                snapshot["version"], snapshot["empreinte"]
            ):
                lot = _maj_snapshot_obsolete(cnx, lot, acteur)
            reponses.append(_vue_lot(lot))
        _exiger_personne(cnx, acteur)
        return reponses


def lire_provenance(cnx_factory: FabriqueConnexion, acteur: str, lot_id: str) -> dict[str, Any]:
    from m10_memoire import provenance_documentaire

    with cnx_factory() as cnx:
        _isoler_transaction(cnx)
        _exiger_personne(cnx, acteur)
        row = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot_id).with_for_update()).one_or_none()
        if row is None:
            raise FusionErreur("LOT_INCONNU", "lot inconnu", 404)
        lot = _dictionnaire(row)
        if not _verifier_snapshot(lot):
            lot = _maj_snapshot_obsolete(cnx, lot, acteur)
        document = provenance_documentaire.lire(stockage.maillons("m10-memoire", "documents"), lot_id)
        _exiger_personne(cnx, acteur)
        if not _verifier_snapshot(lot):
            lot = _maj_snapshot_obsolete(cnx, lot, acteur)
            document = provenance_documentaire.lire(stockage.maillons("m10-memoire", "documents"), lot_id)
        _exiger_personne(cnx, acteur)
        if document is None:
            raise FusionErreur("PROVENANCE_ABSENTE", "provenance M10 absente", 404)
        return document
