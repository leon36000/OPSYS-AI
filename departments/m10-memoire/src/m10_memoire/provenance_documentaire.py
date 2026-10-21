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
CHAMPS_PDF = frozenset({
    "type_entree", "genre", "lot_id", "reference_locale", "source_sha256", "classe", "auteur",
    "acteur_transition", "extracteur", "configuration_sha256", "source_revision", "revision", "statut",
    "total_pages", "code", "horodatage",
})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOT = re.compile(r"[0-9a-f-]{36}\Z")
_LOT_PDF = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_STATUTS = frozenset({"PROPOSITIONS", "AUCUNE_PROPOSITION", "REFUSE", "SNAPSHOT_OBSOLETE"})
_STATUTS_PDF = frozenset({"RECU", "EXTRAIT_PREPARATOIRE", "REFUSE", "ERREUR_REPRENABLE"})
_REFUS_PDF = frozenset({
    "PDF_CHIFFRE", "PDF_ACTIF", "PDF_PAGES_BORNEES", "PDF_CONTENU_BORNE", "PDF_IMAGE_OU_MIXTE",
    "PDF_AMBIGU", "PDF_SANS_TEXTE", "PDF_TEXTE_BORNE", "PDF_SOURCE_BORNEE", "PDF_MEMOIRE_BORNEE",
    "PDF_MALFORME", "PDF_AVERTISSEMENT", "PDF_SORTIE_BORNEE",
})
_TEMPORAIRES_PDF = frozenset({
    "PDF_ISOLATION_INDISPONIBLE", "PDF_LIMITES_INDISPONIBLES", "PDF_DEPENDANCE_INDISPONIBLE",
    "PDF_TIMEOUT", "PDF_SORTIE_EXCESSIVE", "PDF_PROTOCOLE_INVALIDE", "PDF_RESULTAT_INVALIDE",
})
_ACTEUR = re.compile(r"[a-z][a-z0-9_.-]{1,63}\Z")
_EXTRACTEUR_PDF = re.compile(r"pypdf-[0-9]+\.[0-9]+\.[0-9]+/pdf-natif-[1-9][0-9]*\Z")


def valider(document: object) -> dict:
    if not isinstance(document, Mapping):
        raise ValueError("provenance documentaire invalide")
    if document.get("genre") == "m5.releve_bancaire_csv":
        return _valider_csv(document)
    if document.get("genre") == "m5.document_pdf_natif":
        return _valider_pdf(document)
    raise ValueError("provenance documentaire invalide")


def _valider_csv(document: Mapping) -> dict:
    if set(document) != CHAMPS:
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


def _valider_pdf(document: Mapping) -> dict:
    if set(document) != CHAMPS_PDF:
        raise ValueError("provenance PDF invalide")
    resultat = dict(document)
    lot_id = resultat["lot_id"]
    if (resultat["type_entree"] != "provenance_documentaire" or resultat["classe"] != "FINANCIAL"
            or not isinstance(lot_id, str) or not _LOT_PDF.fullmatch(lot_id)):
        raise ValueError("identité de provenance PDF invalide")
    if (resultat["reference_locale"] != f"opsys-ingestion://m05-financecore/pdf/lots/{lot_id}"
            or not isinstance(resultat["source_sha256"], str)
            or not _SHA256.fullmatch(resultat["source_sha256"])):
        raise ValueError("référence ou empreinte PDF invalide")
    for field in ("auteur", "acteur_transition"):
        if not isinstance(resultat[field], str) or not _ACTEUR.fullmatch(resultat[field]):
            raise ValueError("acteur de provenance PDF invalide")
    if (not isinstance(resultat["extracteur"], str) or len(resultat["extracteur"]) > 64
            or not _EXTRACTEUR_PDF.fullmatch(resultat["extracteur"])
            or not isinstance(resultat["configuration_sha256"], str)
            or not _SHA256.fullmatch(resultat["configuration_sha256"])):
        raise ValueError("configuration PDF invalide")
    for field in ("source_revision", "revision"):
        if type(resultat[field]) is not int or not 1 <= resultat[field] <= 2_147_483_647:
            raise ValueError("révision PDF invalide")
    statut, code = resultat["statut"], resultat["code"]
    pages = resultat["total_pages"]
    if (not isinstance(statut, str) or statut not in _STATUTS_PDF
            or (code is not None and not isinstance(code, str))
            or type(pages) is not int or not 0 <= pages <= 20):
        raise ValueError("état PDF invalide")
    if statut == "EXTRAIT_PREPARATOIRE":
        if pages < 1 or code is not None:
            raise ValueError("extrait PDF incohérent")
    elif statut == "RECU":
        if pages != 0 or code is not None:
            raise ValueError("PDF reçu incohérent")
    elif statut == "REFUSE":
        if pages != 0 or code not in _REFUS_PDF:
            raise ValueError("refus PDF incohérent")
    elif pages != 0 or code not in _TEMPORAIRES_PDF:
        raise ValueError("erreur PDF reprenable incohérente")
    horodatage = resultat["horodatage"]
    if not isinstance(horodatage, str):
        raise ValueError("horodatage PDF invalide")
    try:
        instant = datetime.fromisoformat(horodatage)
    except ValueError as exc:
        raise ValueError("horodatage PDF invalide") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("horodatage PDF sans fuseau")
    return resultat


def enregistrer(maillons, document: Mapping) -> dict:
    """Append idempotent, append-only et protégé par le rang attendu du store."""
    source = valider(document)
    chaine = Registre(maillons=list(maillons))
    valide, _ = chaine.valider_chaine()
    if not valide:
        raise ValueError("chaîne M10 documentaire invalide")
    historiques = [item for item in chaine.lire() if item.get("lot_id") == source["lot_id"]]
    if any(item.get("genre") != source["genre"] for item in historiques):
        raise ValueError("collision de genre de provenance documentaire")
    existant = next((item for item in historiques if item.get("revision") == source["revision"]), None)
    if existant is not None:
        if {key: value for key, value in existant.items() if key not in {"ligne_id", "precedent_ligne_id"}} != source:
            raise ValueError("provenance documentaire déjà liée à un contenu différent")
        return copy.deepcopy(existant)
    if historiques and source["revision"] != max(item["revision"] for item in historiques) + 1:
        raise ValueError("révision de provenance non consécutive")
    if source["genre"] == "m5.document_pdf_natif" and historiques:
        precedente = max(historiques, key=lambda item: item["revision"])
        immuables = (
            "type_entree", "genre", "lot_id", "reference_locale", "source_sha256", "classe", "auteur",
            "extracteur", "configuration_sha256",
        )
        if (any(precedente.get(cle) != source[cle] for cle in immuables)
                or source["source_revision"] != precedente["source_revision"] + 1):
            raise ValueError("source ou version PDF a changé")
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
    if len({item.get("genre") for item in historiques}) != 1:
        raise ValueError("collision de genre de provenance documentaire")
    item = max(historiques, key=lambda entry: entry["revision"])
    return valider({key: value for key, value in item.items() if key not in {"ligne_id", "precedent_ligne_id"}})
