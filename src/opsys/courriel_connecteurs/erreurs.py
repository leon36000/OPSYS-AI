"""Catalogue FERMÉ des refus des connecteurs courriel (`REJ-COURRIEL-*`) et l'erreur typée.

Un code hors de ce catalogue est une faute de programmation (`ValueError`). Le détail dit quoi faire ; il ne contient
jamais un jeton, un secret, un en-tête d'autorisation ni un morceau de courriel (le corps d'une réponse du
fournisseur n'est jamais recopié) : tout détail est masqué par `opsys.secrets_coffre.masquage` avant d'être gardé.
`reprenable` dit si la même opération peut être retentée plus tard SANS nouvelle décision humaine (panne
temporaire, limite de débit) ; un envoi à l'issue incertaine n'est JAMAIS reprenable.
"""

from __future__ import annotations

from typing import Any

from ..secrets_coffre import masquage

CODES_COURRIEL: tuple[str, ...] = (
    # -- arguments, comptes, consentement
    "REJ-COURRIEL-ARGUMENT-INVALIDE",
    "REJ-COURRIEL-FOURNISSEUR-INCONNU",
    "REJ-COURRIEL-COMPTE-INCONNU",
    "REJ-COURRIEL-COMPTE-INACTIF",
    "REJ-COURRIEL-COMPTE-EXISTE",
    "REJ-COURRIEL-CONSENTEMENT-ABSENT",
    "REJ-COURRIEL-ADMIN-REQUIS",
    # -- cycle OAuth
    "REJ-COURRIEL-OAUTH-ETAT-INVALIDE",
    "REJ-COURRIEL-OAUTH-ETAT-EXPIRE",
    "REJ-COURRIEL-OAUTH-ETAT-REUTILISE",
    "REJ-COURRIEL-OAUTH-ECHANGE-REFUSE",
    "REJ-COURRIEL-OAUTH-CONFIGURATION",
    "REJ-COURRIEL-PORTEE-EXCESSIVE",
    "REJ-COURRIEL-PORTEE-INSUFFISANTE",
    "REJ-COURRIEL-REFRESH-ABSENT",
    "REJ-COURRIEL-JETON-REVOQUE",
    "REJ-COURRIEL-JETON-EXPIRE",
    "REJ-COURRIEL-COFFRE-INDISPONIBLE",
    "REJ-COURRIEL-COFFRE-REFUSE",
    # -- appels au fournisseur
    "REJ-COURRIEL-AUTH-REFUSEE",
    "REJ-COURRIEL-PERMISSION-REFUSEE",
    "REJ-COURRIEL-LIMITE-DEBIT",
    "REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE",
    "REJ-COURRIEL-RESEAU",
    "REJ-COURRIEL-REQUETE-INVALIDE",
    "REJ-COURRIEL-INTROUVABLE",
    "REJ-COURRIEL-REPONSE-INVALIDE",
    "REJ-COURRIEL-LIEN-NON-AUTORISE",
    "REJ-COURRIEL-CURSEUR-INVALIDE",
    "REJ-COURRIEL-CURSEUR-EXPIRE",
    "REJ-COURRIEL-IMAP-AUTH",
    "REJ-COURRIEL-IMAP-PROTOCOLE",
    # -- messages, isolation, ingestion
    "REJ-COURRIEL-MESSAGE-INVALIDE",
    "REJ-COURRIEL-MESSAGE-TROP-GROS",
    "REJ-COURRIEL-FILTRE-INDISPONIBLE",
    "REJ-COURRIEL-QUOTA-DEBIT",
    "REJ-COURRIEL-INGESTION-REFUSEE",
    # -- exports mbox
    "REJ-COURRIEL-MBOX-NOM-INVALIDE",
    "REJ-COURRIEL-MBOX-ABSENT",
    "REJ-COURRIEL-MBOX-TROP-GROS",
    "REJ-COURRIEL-MBOX-BOMBE",
    "REJ-COURRIEL-MBOX-FORMAT",
    # -- brouillons et envoi sous sas
    "REJ-COURRIEL-BROUILLON-INCONNU",
    "REJ-COURRIEL-BROUILLON-INVALIDE",
    "REJ-COURRIEL-BROUILLON-TROP-GROS",
    "REJ-COURRIEL-BROUILLON-GARDE-FOU",
    "REJ-COURRIEL-BROUILLON-ETAT",
    "REJ-COURRIEL-APPROBATION-ABSENTE",
    "REJ-COURRIEL-APPROBATION-INVALIDE",
    "REJ-COURRIEL-APPROBATION-NON-APPROUVEE",
    "REJ-COURRIEL-APPROBATION-REJOUEE",
    "REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE",
    "REJ-COURRIEL-ENVOI-ECHEC",
    "REJ-COURRIEL-ENVOI-INCERTAIN",
    "REJ-COURRIEL-ENVOI-NON-SUPPORTE",
)
_CODES = frozenset(CODES_COURRIEL)
_DETAIL_MAX = 300


class ErreurCourriel(Exception):
    """Refus typé : un code du catalogue, un détail masqué sans contenu de courriel, un statut HTTP indicatif."""

    def __init__(self, code: str, detail: str = "", statut_http: int = 409, *, reprenable: bool = False,
                 reessayer_apres_s: int | None = None) -> None:
        if code not in _CODES:
            raise ValueError(f"code de connecteur courriel hors catalogue : {code!r}")
        detail = masquage.masquer_texte(detail)[:_DETAIL_MAX]
        super().__init__(f"{code} : {detail}")
        self.code, self.detail, self.statut_http = code, detail, statut_http
        self.reprenable, self.reessayer_apres_s = reprenable, reessayer_apres_s

    def publique(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "reprenable": self.reprenable,
                "reessayer_apres_s": self.reessayer_apres_s}


def refus(code: str, detail: str = "", statut_http: int = 409, **options: Any) -> ErreurCourriel:
    return ErreurCourriel(code, detail, statut_http, **options)


__all__ = ["CODES_COURRIEL", "ErreurCourriel", "refus"]
