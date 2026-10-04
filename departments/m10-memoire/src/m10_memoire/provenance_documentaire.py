"""Contrat privé M10 pour la provenance de documents métier sans affaire artificielle."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from datetime import datetime

from .registre import Registre

CHAMPS = frozenset({
    "type_entree", "genre", "lot_id", "reference_locale", "source_sha256", "classe", "auteur",
    "snapshot_version", "snapshot_empreinte", "compte_interne_id", "total_lignes", "nombre_propositions",
    "revision", "statut", "horodatage",
})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOT = re.compile(r"[0-9a-f-]{36}\Z")
_STATUTS = frozenset({"PROPOSITIONS", "AUCUNE_PROPOSITION", "REFUSE", "SNAPSHOT_OBSOLETE"})


def valider(document: object) -> dict:
    if not isinstance(document, Mapping) or set(document) != CHAMPS:
        raise ValueError("provenance documentaire invalide")
    resultat = dict(document)
    if (resultat["type_entree"] != "provenance_documentaire"
            or resultat["genre"] != "m5.releve_bancaire_csv"
            or resultat["classe"] != "FINANCIAL"):
        raise ValueError("type ou classe de provenance documentaire invalide")
    if not isinstance(resultat["lot_id"], str) or not _LOT.fullmatch(resultat["lot_id"]):
        raise ValueError("identifiant de lot invalide")
    if not isinstance(resultat["source_sha256"], str) or not _SHA256.fullmatch(resultat["source_sha256"]):
        raise ValueError("empreinte source invalide")
    if not isinstance(resultat["reference_locale"], str) or resultat["reference_locale"] != (
        f"opsys-ingestion://m05-financecore/lots/{resultat['lot_id']}"
    ):
        raise ValueError("référence locale invalide")
    if (not isinstance(resultat["auteur"], str) or not resultat["auteur"] or len(resultat["auteur"]) > 64
            or not isinstance(resultat["compte_interne_id"], str) or not resultat["compte_interne_id"]
            or len(resultat["compte_interne_id"]) > 64):
        raise ValueError("provenance acteur ou compte invalide")
    if type(resultat["snapshot_version"]) is not int or resultat["snapshot_version"] < 0:
        raise ValueError("version de snapshot invalide")
    if type(resultat["revision"]) is not int or resultat["revision"] < 1:
        raise ValueError("révision de provenance invalide")
    if resultat["snapshot_empreinte"] is not None and (
        not isinstance(resultat["snapshot_empreinte"], str) or not _SHA256.fullmatch(resultat["snapshot_empreinte"])
    ):
        raise ValueError("empreinte de snapshot invalide")
    for field in ("total_lignes", "nombre_propositions"):
        if type(resultat[field]) is not int or not 0 <= resultat[field] <= 2_000:
            raise ValueError("compteurs de provenance invalides")
    if resultat["nombre_propositions"] > resultat["total_lignes"]:
        raise ValueError("nombre de propositions incohérent")
    if resultat["statut"] not in _STATUTS:
        raise ValueError("état de provenance invalide")
    if not isinstance(resultat["horodatage"], str):
        raise ValueError("horodatage de provenance invalide")
    try:
        horodatage = datetime.fromisoformat(resultat["horodatage"])
    except ValueError as exc:
        raise ValueError("horodatage de provenance invalide") from exc
    if horodatage.tzinfo is None or horodatage.utcoffset() is None:
        raise ValueError("horodatage de provenance sans fuseau")
    return resultat


def enregistrer(maillons, document: Mapping) -> dict:
    """Append idempotent, append-only et protégé par le rang attendu du store."""
    source = valider(document)
    chaine = Registre(maillons=list(maillons))
    valide, _ = chaine.valider_chaine()
    if not valide:
        raise ValueError("chaîne M10 documentaire invalide")
    historiques = [item for item in chaine.lire() if item.get("lot_id") == source["lot_id"]]
    existant = next((item for item in historiques if item.get("revision") == source["revision"]), None)
    if existant is not None:
        if {key: value for key, value in existant.items() if key not in {"ligne_id", "precedent_ligne_id"}} != source:
            raise ValueError("provenance documentaire déjà liée à un contenu différent")
        return copy.deepcopy(existant)
    if historiques and source["revision"] != max(item["revision"] for item in historiques) + 1:
        raise ValueError("révision de provenance non consécutive")
    if not historiques and source["revision"] != 1:
        raise ValueError("première révision de provenance invalide")
    candidat = Registre(maillons=chaine.lire())
    candidat.ajouter(source)
    maillon = candidat.lire()[-1]
    maillons.append(maillon, rang_attendu=len(maillons))
    return maillon


def lire(maillons, lot_id: str) -> dict | None:
    chaine = Registre(maillons=list(maillons))
    valide, _ = chaine.valider_chaine()
    if not valide:
        raise ValueError("chaîne M10 documentaire invalide")
    historiques = [item for item in chaine.lire() if item.get("lot_id") == lot_id]
    if not historiques:
        return None
    item = max(historiques, key=lambda entry: entry["revision"])
    return valider({key: value for key, value in item.items() if key not in {"ligne_id", "precedent_ligne_id"}})
