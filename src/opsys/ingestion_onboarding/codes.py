"""Catalogue FERMÉ des codes de l'ingestion d'onboarding (`REJ-ING-*`) et l'erreur typée du socle.

Un code hors de ce catalogue est une faute de programmation (`ValueError`), jamais un refus inventé à la volée. Les
détails disent quoi faire ; ils ne contiennent jamais le contenu d'un document (ni montant, ni nom de client) : ce sont
les payloads chiffrés qui le portent. La documentation (docs/architecture/INGESTION-ONBOARDING.md, « Codes ») suit
cette liste ; `tests/test_ingestion_onboarding_depot.py` l'épingle.
"""

from __future__ import annotations

from typing import Any

CODES_ING: tuple[str, ...] = (
    # -- dépôt : nom, fichier, type, archive
    "REJ-ING-NOM-INVALIDE",
    "REJ-ING-DOSSIER-INVALIDE",
    "REJ-ING-FICHIER-ABSENT",
    "REJ-ING-FICHIER-TROP-GROS",
    "REJ-ING-FICHIER-VIDE",
    "REJ-ING-TYPE-NON-ACCEPTE",
    "REJ-ING-TYPE-INCOHERENT",
    "REJ-ING-ZIP-ILLISIBLE",
    "REJ-ING-ZIP-TRAVERSEE",
    "REJ-ING-ZIP-LIEN",
    "REJ-ING-ZIP-BOMBE",
    "REJ-ING-ZIP-NOM-REPETE",
    "REJ-ING-ZIP-CHIFFRE",
    "REJ-ING-ZIP-IMBRIQUE",
    "REJ-ING-LOT-VIDE",
    # -- lot : mutation, quotas, clé
    "REJ-ING-MUTATION-INVALIDE",
    "REJ-ING-MUTATION-CONFLIT",
    "REJ-ING-QUOTA-LOTS",
    "REJ-ING-QUOTA-DOCUMENTS",
    "REJ-ING-QUOTA-OCTETS",
    "REJ-ING-CLE-INDISPONIBLE",
    "REJ-ING-CHIFFREMENT-INDISPONIBLE",
    "REJ-ING-CONTENU-CORROMPU",
    "REJ-ING-LOT-INCONNU",
    "REJ-ING-ACTEUR-INVALIDE",
    "REJ-ING-ARGUMENT-INVALIDE",
    # -- étapes du pipeline
    "REJ-ING-TEXTE-ILLISIBLE",
    "REJ-ING-PDF-REFUSE",
    "REJ-ING-ISOLATION-INDISPONIBLE",
    "REJ-ING-OCR-INDISPONIBLE",
    "REJ-ING-OCR-REFUSE",
    "REJ-ING-IMAGE-NON-TRAITEE",
    "REJ-ING-TABLEAU-ILLISIBLE",
    "REJ-ING-CLASSE-INCONNUE",
    "REJ-ING-CLASSE-NON-PEUPLEE",
    "REJ-ING-FOURNISSEUR-REFUSE",
    "REJ-ING-EXTRACTEUR-NON-RACCORDE",
    "REJ-ING-EXTRACTION-INVALIDE",
    "REJ-ING-PROFIL-INVALIDE",
    "REJ-ING-FILE-MORTE",
    # -- correspondants d'une boîte courriel (genre « courriel_contact », `contacts_courriel`)
    "REJ-ING-COURRIEL-AUTOMATISE",
    "REJ-ING-COURRIEL-ADRESSE-INVALIDE",
    "REJ-ING-COURRIEL-SANS-NOM",
    "REJ-ING-COURRIEL-TROP-DE-LIGNES",
    "REJ-ING-COURRIEL-ENTETE-INTROUVABLE",
    # -- brouillons et décision humaine
    "REJ-ING-BROUILLON-INCONNU",
    "REJ-ING-BROUILLON-GENRE",
    "REJ-ING-BROUILLON-REVISION",
    "REJ-ING-BROUILLON-A-VERIFIER",
    "REJ-ING-BROUILLON-DEJA-DECIDE",
    "REJ-ING-DECISION-INVALIDE",
    "REJ-ING-MOTIF-REQUIS",
)
_CODES = frozenset(CODES_ING)


def construire_verdict(code: str, detail: str = "", **complements: Any) -> dict[str, Any]:
    if code not in _CODES:
        raise ValueError(f"code d'ingestion hors catalogue : {code!r}")
    return {"code": code, "detail": detail, **complements}


class IngestionErreur(ValueError):
    """Refus typé du socle : un code du catalogue, un détail sans contenu de document, un statut HTTP indicatif."""

    def __init__(self, code: str, detail: str = "", statut_http: int = 409, **complements: Any) -> None:
        self.verdict = construire_verdict(code, detail, **complements)
        super().__init__(f"{code} : {detail}")
        self.code, self.detail, self.statut_http = code, detail, statut_http

    def publique(self) -> dict[str, Any]:
        return dict(self.verdict)


class EchecEtape(Exception):
    """Une étape du pipeline n'aboutit pas : `reprenable` (panne temporaire : isolation, délai) ou définitive (le
    document lui-même est refusé ou non traité, avec son code)."""

    def __init__(self, code: str, detail: str = "", *, reprenable: bool = False) -> None:
        construire_verdict(code, detail)
        super().__init__(f"{code} : {detail}")
        self.code, self.detail, self.reprenable = code, detail, reprenable


__all__ = ["CODES_ING", "EchecEtape", "IngestionErreur", "construire_verdict"]
