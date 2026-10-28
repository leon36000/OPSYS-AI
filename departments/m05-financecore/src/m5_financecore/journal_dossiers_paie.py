"""Journal durable, chiffré et chaîné des dossiers de paie préparatoires (versions, revues, réouvertures, exports).

Réutilise le stockage métier existant (`opsys.stockage.maillons`, table `registres_maillons`, aucune migration)
et le coffre de clés du socle (`opsys.cles_chiffrement`, une clé AES-256-GCM par dossier). Le registre est
append-only : rien n'est jamais modifié ni supprimé, une correction est une nouvelle version, une réouverture
est un événement. L'enveloppe en clair ne contient que des empreintes et un identifiant de dossier opaque
(HMAC avec une clé d'index du coffre) ; entrées, montants, employé et notes sont chiffrés.

Intégrité vérifiée à CHAQUE lecture : chaîne de hash, empreinte du chiffré, MAC d'authentification de l'enveloppe,
déchiffrement, forme de l'événement et cohérence sémantique de la projection. Toute anomalie ferme la lecture
(`JournalCorrompu`) ; aucun résultat partiel n'est rendu.

Un événement VERSION ne contient jamais un montant « versé » : il fige des entrées déclarées, des références de
sources et un calcul PREPARATOIRE. Un cumul qui en découle reste un cumul simulé (voir `dossier_paie_preparatoire`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Connection

from opsys import cles_chiffrement, stockage
from opsys.stockage.maillons import EcritureConcurrente

from . import dossier_paie_preparatoire as dossier

DEPARTEMENT = "m05-financecore"
REGISTRE = "dossiers_paie_preparatoires"
PORTEE_CLE = "m05/dossiers-paie-preparatoires"
PORTEE_INDEX = "m05/dossiers-paie-index"
IDENTIFIANT_INDEX = "index-v1"
MAX_ENTREES = 20000
MAX_CHIFFRE_OCTETS = 262144
MAX_NOTE = 1000
_TYPES = ("VERSION", "REVUE", "REOUVERTURE", "EXPORT")
_TYPES_VERSION = ("CREATION", "CORRECTION", "REBASE")
_DECISIONS_REVUE = ("REVUE_COMPLETEE", "A_CORRIGER")
_HEX_64 = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[a-f0-9]{32}$")
_CHAMPS_ENVELOPPE = frozenset(
    {
        "schema",
        "id",
        "rang",
        "precedent_sha256",
        "dossier_id",
        "type",
        "nonce",
        "ciphertext",
        "cipher_sha256",
        "mutation_mac",
        "acteur_mac",
        "revision_attendue",
    }
)


def est_type_version(valeur: object) -> bool:
    return isinstance(valeur, str) and valeur in _TYPES_VERSION


def est_decision_revue(valeur: object) -> bool:
    return isinstance(valeur, str) and valeur in _DECISIONS_REVUE


class JournalErreur(ValueError):
    """Refus métier (CAS, rejeu en conflit, entrée invalide); `verdict` porte le code `REJ-DOSSIER-PAIE-*`."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.verdict = dossier.refus(code, detail)


class JournalCorrompu(JournalErreur):
    def __init__(self, detail: str) -> None:
        super().__init__("DONNEES-CORROMPUES", detail)


def _json(objet: Any) -> bytes:
    return dossier.canonique(objet).encode("utf-8")


def _aead() -> Any:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise JournalErreur("STOCKAGE-INDISPONIBLE", "chiffrement indisponible : écriture et lecture refusées") from exc
    return AESGCM


def _exiger_transaction(cnx: Connection) -> None:
    if stockage.connexion_courante() is not cnx:
        raise JournalErreur("STOCKAGE-INDISPONIBLE", "transaction de stockage courante requise")


def identifiant_dossier(
    cnx: Connection,
    employee_person_id: str,
    employeur_reference: str,
    annee: int,
    periode_annuelle: int,
    *,
    creer: bool,
) -> str | None:
    """Identifiant opaque et déterministe d'un dossier (employé × employeur × année × période).

    HMAC avec une clé d'index du coffre : un lecteur de la base ne peut pas deviner les dossiers d'un employé.
    `creer=False` ne crée jamais la clé d'index et rend None si elle n'existe pas encore.
    """
    _exiger_transaction(cnx)
    cle = cles_chiffrement.lire(cnx, PORTEE_INDEX, IDENTIFIANT_INDEX)
    if cle is None:
        if not creer:
            return None
        cle = cles_chiffrement.obtenir_ou_creer(cnx, PORTEE_INDEX, IDENTIFIANT_INDEX, "1970-01-01T00:00:00+00:00")
    donnees = _json(["opsys.dossier-paie/v1", employee_person_id, employeur_reference, annee, periode_annuelle])
    return hmac.new(cle, donnees, hashlib.sha256).hexdigest()[:32]


def _enveloppes() -> list[dict[str, Any]]:
    registre = stockage.maillons(DEPARTEMENT, REGISTRE)
    if len(registre) > MAX_ENTREES:
        raise JournalErreur("STOCKAGE-INDISPONIBLE", "registre trop volumineux : revue requise")
    return list(registre)


def _mac_mutation(
    cle: bytes,
    *,
    mutation_id: str,
    acteur: str,
    dossier_id: str,
    type_evt: str,
    version_attendue: int,
    requete_sha256: str,
    rang: int,
) -> str:
    return hmac.new(
        cle,
        _json(
            {
                "mutation_id": mutation_id,
                "acteur": acteur,
                "dossier_id": dossier_id,
                "type": type_evt,
                "version_attendue": version_attendue,
                "requete_sha256": requete_sha256,
                "revision_attendue": rang,
            }
        ),
        hashlib.sha256,
    ).hexdigest()


def _verifier_forme_evenement(ligne: Mapping[str, Any], env: Mapping[str, Any]) -> None:
    type_evt = ligne.get("type")
    commun = {"type", "dossier_id", "acteur", "horodatage", "version_attendue", "requete_sha256"}
    if type_evt not in _TYPES or ligne.get("dossier_id") != env["dossier_id"] or type_evt != env["type"]:
        raise JournalCorrompu("événement incohérent avec son enveloppe")
    attendus = {
        "VERSION": commun | {"numero", "parent", "type_version", "motif", "hash_version", "version"},
        "REVUE": commun | {"numero", "hash_version", "decision", "note"},
        "REOUVERTURE": commun | {"depuis_numero", "hash_version", "motif"},
        "EXPORT": commun | {"numero", "hash_version", "format", "empreinte_export"},
    }[type_evt]
    if set(ligne) != attendus:
        raise JournalCorrompu("champs d'événement inattendus")
    if not isinstance(ligne["acteur"], str) or not ligne["acteur"] or not isinstance(ligne["horodatage"], str):
        raise JournalCorrompu("acteur ou horodatage invalide")
    if type(ligne["version_attendue"]) is not int or ligne["version_attendue"] < 0:
        raise JournalCorrompu("version attendue invalide")
    if not isinstance(ligne["requete_sha256"], str) or not _HEX_64.fullmatch(ligne["requete_sha256"]):
        raise JournalCorrompu("empreinte de requête invalide")
    if type_evt == "VERSION":
        version = ligne["version"]
        if (
            type(ligne["numero"]) is not int
            or ligne["numero"] < 1
            or ligne["type_version"] not in _TYPES_VERSION
            or not isinstance(ligne["motif"], str)
            or len(ligne["motif"]) > MAX_NOTE
            or not isinstance(version, Mapping)
            or version.get("schema") != dossier.SCHEMA_VERSION
            or ligne["hash_version"] != dossier.empreinte(version)
            or version.get("numero") != ligne["numero"]
            or version.get("dossier_id") != ligne["dossier_id"]
            or ligne["parent"] != (None if ligne["numero"] == 1 else ligne["numero"] - 1)
        ):
            raise JournalCorrompu("version figée incohérente avec son empreinte")
    elif type_evt == "REVUE":
        if (
            type(ligne["numero"]) is not int
            or ligne["decision"] not in _DECISIONS_REVUE
            or not isinstance(ligne["note"], str)
            or len(ligne["note"]) > MAX_NOTE
            or not isinstance(ligne["hash_version"], str)
            or not _HEX_64.fullmatch(ligne["hash_version"])
        ):
            raise JournalCorrompu("revue invalide")
    elif type_evt == "REOUVERTURE":
        if (
            type(ligne["depuis_numero"]) is not int
            or not isinstance(ligne["motif"], str)
            or not isinstance(ligne["hash_version"], str)
            or not _HEX_64.fullmatch(ligne["hash_version"])
        ):
            raise JournalCorrompu("réouverture invalide")
    elif (
        type(ligne["numero"]) is not int
        or not isinstance(ligne["format"], str)
        or not isinstance(ligne["empreinte_export"], str)
        or not _HEX_64.fullmatch(ligne["empreinte_export"])
    ):
        raise JournalCorrompu("export invalide")


def _lire_verifier(cnx: Connection, enveloppes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Valide chaque enveloppe (chaîne, MAC, déchiffrement) et rend les événements en clair, ordonnés."""
    evenements: list[dict[str, Any]] = []
    ids_vus: set[str] = set()
    for rang, env in enumerate(enveloppes):
        if not isinstance(env, dict) or set(env) != _CHAMPS_ENVELOPPE:
            raise JournalCorrompu("enveloppe invalide")
        if (
            env["schema"] != 1
            or type(env["rang"]) is not int
            or env["rang"] != rang
            or env["revision_attendue"] != rang
        ):
            raise JournalCorrompu("séquence invalide")
        if not isinstance(env["id"], str) or not _ID.fullmatch(env["id"]) or env["id"] in ids_vus:
            raise JournalCorrompu("identifiant d'événement invalide ou dupliqué")
        ids_vus.add(env["id"])
        if not isinstance(env["dossier_id"], str) or not _ID.fullmatch(env["dossier_id"]) or env["type"] not in _TYPES:
            raise JournalCorrompu("dossier ou type invalide")
        precedent = hashlib.sha256(_json(enveloppes[rang - 1])).hexdigest() if rang else "0" * 64
        if env["precedent_sha256"] != precedent:
            raise JournalCorrompu("chaîne rompue")
        if not all(
            isinstance(env[k], str) and _HEX_64.fullmatch(env[k])
            for k in ("cipher_sha256", "mutation_mac", "acteur_mac")
        ):
            raise JournalCorrompu("empreintes d'enveloppe invalides")
        try:
            nonce, chiffre = bytes.fromhex(env["nonce"]), bytes.fromhex(env["ciphertext"])
        except (TypeError, ValueError) as exc:
            raise JournalCorrompu("chiffré illisible") from exc
        if len(nonce) != 12 or not 16 <= len(chiffre) <= MAX_CHIFFRE_OCTETS:
            raise JournalCorrompu("taille de chiffré invalide")
        if hashlib.sha256(chiffre).hexdigest() != env["cipher_sha256"]:
            raise JournalCorrompu("empreinte du chiffré invalide")
        cle = cles_chiffrement.lire(cnx, PORTEE_CLE, env["dossier_id"])
        if cle is None:
            raise JournalCorrompu("clé du dossier absente : dossier illisible")
        aad = _json(
            {
                "schema": 1,
                "id": env["id"],
                "rang": rang,
                "precedent_sha256": precedent,
                "dossier_id": env["dossier_id"],
                "type": env["type"],
                "mutation_mac": env["mutation_mac"],
                "acteur_mac": env["acteur_mac"],
            }
        )
        try:
            ligne = json.loads(_aead()(cle).decrypt(nonce, chiffre, aad).decode("utf-8"))
        except JournalErreur:
            raise
        except Exception as exc:
            raise JournalCorrompu("déchiffrement refusé : altération détectée") from exc
        if not isinstance(ligne, dict):
            raise JournalCorrompu("contenu invalide")
        _verifier_forme_evenement(ligne, env)
        attendu = _mac_mutation(
            cle,
            mutation_id=env["id"],
            acteur=ligne["acteur"],
            dossier_id=env["dossier_id"],
            type_evt=env["type"],
            version_attendue=ligne["version_attendue"],
            requete_sha256=ligne["requete_sha256"],
            rang=rang,
        )
        acteur_mac = hmac.new(cle, ligne["acteur"].encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(env["mutation_mac"], attendu) or not hmac.compare_digest(
            env["acteur_mac"], acteur_mac
        ):
            raise JournalCorrompu("authentification de l'enveloppe invalide")
        evenements.append({**ligne, "id": env["id"], "rang": rang})
    return evenements


def _projeter(evenements: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Projection par dossier; chaque règle sémantique violée ferme la lecture."""
    dossiers: dict[str, dict[str, Any]] = {}
    for evt in evenements:
        d = dossiers.setdefault(
            evt["dossier_id"],
            {
                "dossier_id": evt["dossier_id"],
                "versions": [],
                "revues": [],
                "reouvertures": [],
                "exports": [],
                "etat": "",
            },
        )
        courant = d["versions"][-1] if d["versions"] else None
        type_evt = evt["type"]
        if type_evt == "VERSION":
            if evt["numero"] != len(d["versions"]) + 1 or evt["version_attendue"] != len(d["versions"]):
                raise JournalCorrompu("numérotation de versions rompue")
            if courant is not None and courant["version"]["identite"] != evt["version"]["identite"]:
                raise JournalCorrompu("identité de dossier modifiée entre versions")
            d["versions"].append(
                {
                    "numero": evt["numero"],
                    "hash_version": evt["hash_version"],
                    "type_version": evt["type_version"],
                    "motif": evt["motif"],
                    "version": evt["version"],
                    "acteur": evt["acteur"],
                    "horodatage": evt["horodatage"],
                    "evenement_id": evt["id"],
                }
            )
            d["etat"] = "EN_PREPARATION"
            continue
        if courant is None:
            raise JournalCorrompu("événement sur un dossier sans version")
        if type_evt == "REVUE":
            if evt["numero"] != courant["numero"] or evt["hash_version"] != courant["hash_version"]:
                raise JournalCorrompu("revue liée à une autre version que la version courante")
            d["revues"].append(
                {
                    "numero": evt["numero"],
                    "hash_version": evt["hash_version"],
                    "decision": evt["decision"],
                    "note": evt["note"],
                    "acteur": evt["acteur"],
                    "horodatage": evt["horodatage"],
                    "evenement_id": evt["id"],
                }
            )
            d["etat"] = "REVUE_COMPLETEE" if evt["decision"] == "REVUE_COMPLETEE" else "A_CORRIGER"
        elif type_evt == "REOUVERTURE":
            if evt["depuis_numero"] != courant["numero"] or evt["hash_version"] != courant["hash_version"]:
                raise JournalCorrompu("réouverture d'une version non courante")
            d["reouvertures"].append(
                {
                    "depuis_numero": evt["depuis_numero"],
                    "motif": evt["motif"],
                    "acteur": evt["acteur"],
                    "horodatage": evt["horodatage"],
                    "evenement_id": evt["id"],
                }
            )
            d["etat"] = "ROUVERT"
        else:
            if evt["numero"] != courant["numero"] or evt["hash_version"] != courant["hash_version"]:
                raise JournalCorrompu("export d'une version non courante")
            d["exports"].append(
                {
                    "numero": evt["numero"],
                    "format": evt["format"],
                    "empreinte_export": evt["empreinte_export"],
                    "acteur": evt["acteur"],
                    "horodatage": evt["horodatage"],
                    "evenement_id": evt["id"],
                }
            )
    return dossiers


def lire_tout(cnx: Connection) -> dict[str, dict[str, Any]]:
    """Projection vérifiée de tous les dossiers (déchiffre le registre entier)."""
    _exiger_transaction(cnx)
    return _projeter(_lire_verifier(cnx, _enveloppes()))


def lire_dossier(cnx: Connection, dossier_id: str) -> dict[str, Any] | None:
    if not isinstance(dossier_id, str) or not _ID.fullmatch(dossier_id):
        return None
    return lire_tout(cnx).get(dossier_id)


def retrouver_mutation(cnx: Connection, mutation_id: str) -> dict[str, Any] | None:
    """Événement déjà écrit sous cet identifiant de mutation (après vérification complète), sinon None."""
    _exiger_transaction(cnx)
    evenements = _lire_verifier(cnx, _enveloppes())
    return next((evt for evt in evenements if evt["id"] == mutation_id), None)


def ajouter(
    cnx: Connection,
    *,
    dossier_id: str,
    type_evt: str,
    contenu: Mapping[str, Any],
    mutation_id: str,
    acteur: str,
    horodatage: str,
    version_attendue: int,
    requete_sha256: str,
    verifier_acteur: Callable[[Connection, str], None],
) -> dict[str, Any]:
    """Ajoute un événement chiffré si le CAS de version tient; rejeu exact → REJOUEE; sinon refus sans écriture.

    `contenu` = champs spécifiques du type (voir `_verifier_forme_evenement`). Réessaie jusqu'à 3 fois si SEUL le rang
    global a bougé (écriture d'un autre dossier) et que la version de CE dossier est inchangée.
    """
    _exiger_transaction(cnx)
    if type_evt not in _TYPES or not isinstance(mutation_id, str) or not _ID.fullmatch(mutation_id):
        raise JournalErreur("STRUCTURE-INVALIDE", "type d'événement ou identifiant de mutation invalide")
    if not isinstance(dossier_id, str) or not _ID.fullmatch(dossier_id):
        raise JournalErreur("STRUCTURE-INVALIDE", "identifiant de dossier invalide")
    if not isinstance(requete_sha256, str) or not _HEX_64.fullmatch(requete_sha256):
        raise JournalErreur("STRUCTURE-INVALIDE", "empreinte de requête invalide")
    if type(version_attendue) is not int or version_attendue < 0:
        raise JournalErreur("STRUCTURE-INVALIDE", "version attendue invalide")
    if not isinstance(acteur, str) or not acteur or len(acteur) > 128:
        raise JournalErreur("ACCES-REFUSE", "identité humaine absente")
    verifier_acteur(cnx, acteur)
    for tentative in range(3):
        enveloppes = _enveloppes()
        evenements = _lire_verifier(cnx, enveloppes)
        existant = next((e for e in evenements if e["id"] == mutation_id), None)
        if existant is not None:
            if (
                existant["dossier_id"] == dossier_id
                and existant["type"] == type_evt
                and existant["acteur"] == acteur
                and existant["version_attendue"] == version_attendue
                and existant["requete_sha256"] == requete_sha256
            ):
                return {"statut": "REJOUEE", "rang": existant["rang"], "evenement": existant}
            raise JournalErreur("MUTATION-CONFLIT", "identifiant de mutation déjà utilisé avec une autre requête")
        courant = _projeter(evenements).get(dossier_id)
        numero_courant = len(courant["versions"]) if courant else 0
        if numero_courant != version_attendue:
            raise JournalErreur(
                "VERSION-PERIMEE", f"version attendue {version_attendue}, version courante {numero_courant}"
            )
        if len(enveloppes) >= MAX_ENTREES:
            raise JournalErreur("STOCKAGE-INDISPONIBLE", "registre plein : revue requise")
        rang = len(enveloppes)
        cle = cles_chiffrement.obtenir_ou_creer(cnx, PORTEE_CLE, dossier_id, horodatage)
        mac = _mac_mutation(
            cle,
            mutation_id=mutation_id,
            acteur=acteur,
            dossier_id=dossier_id,
            type_evt=type_evt,
            version_attendue=version_attendue,
            requete_sha256=requete_sha256,
            rang=rang,
        )
        acteur_mac = hmac.new(cle, acteur.encode("utf-8"), hashlib.sha256).hexdigest()
        precedent = hashlib.sha256(_json(enveloppes[-1])).hexdigest() if enveloppes else "0" * 64
        ligne = {
            "type": type_evt,
            "dossier_id": dossier_id,
            "acteur": acteur,
            "horodatage": horodatage,
            "version_attendue": version_attendue,
            "requete_sha256": requete_sha256,
            **contenu,
        }
        _verifier_forme_evenement(json.loads(dossier.canonique(ligne)), {"dossier_id": dossier_id, "type": type_evt})
        aad = _json(
            {
                "schema": 1,
                "id": mutation_id,
                "rang": rang,
                "precedent_sha256": precedent,
                "dossier_id": dossier_id,
                "type": type_evt,
                "mutation_mac": mac,
                "acteur_mac": acteur_mac,
            }
        )
        clair = _json(ligne)
        # Nonce SIV : dérivé (HMAC) de l'identifiant, du rang ET du clair ; aucune source d'aléa dans le paquet, et un
        # même couple (clé, nonce) ne chiffre jamais deux clairs différents, même après un rollback et une reprise.
        nonce = hmac.new(
            cle, b"nonce-v1" + _json([mutation_id, rang, hashlib.sha256(clair).hexdigest()]), hashlib.sha256
        ).digest()[:12]
        chiffre = _aead()(cle).encrypt(nonce, clair, aad)
        if len(chiffre) > MAX_CHIFFRE_OCTETS:
            raise JournalErreur("DOSSIER-TROP-GROS", "événement au-delà de la borne de stockage")
        env = {
            "schema": 1,
            "id": mutation_id,
            "rang": rang,
            "precedent_sha256": precedent,
            "dossier_id": dossier_id,
            "type": type_evt,
            "nonce": nonce.hex(),
            "ciphertext": chiffre.hex(),
            "cipher_sha256": hashlib.sha256(chiffre).hexdigest(),
            "mutation_mac": mac,
            "acteur_mac": acteur_mac,
            "revision_attendue": rang,
        }
        verifier_acteur(cnx, acteur)  # revalidation juste avant l'écriture : autorité retirée → aucune écriture
        try:
            stockage.maillons(DEPARTEMENT, REGISTRE).append(env, rang_attendu=rang)
        except EcritureConcurrente:
            if tentative == 2:
                raise JournalErreur(
                    "VERSION-PERIMEE", "écriture concurrente persistante : relisez le dossier"
                ) from None
            continue
        return {"statut": "ECRITE", "rang": rang, "evenement": {**ligne, "id": mutation_id, "rang": rang}}
    raise JournalErreur("VERSION-PERIMEE", "écriture concurrente persistante : relisez le dossier")
