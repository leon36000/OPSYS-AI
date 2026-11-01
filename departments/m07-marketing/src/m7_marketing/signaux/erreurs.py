"""Catalogue FERMÉ des refus des connecteurs de données propres de M7 (`REJ-SIGNAUX-*`) et l'erreur typée.

Un code hors de ce catalogue est une faute de programmation (`ValueError`). Le détail dit quoi faire ; il ne contient
jamais un jeton, un secret, un en-tête d'autorisation ni un morceau de la réponse du fournisseur (le corps d'une
réponse n'est JAMAIS recopié dans un message) : tout détail est masqué par `opsys.secrets_coffre.masquage` avant
d'être gardé. `reprenable` dit si la même opération peut être retentée plus tard SANS nouvelle décision humaine (panne
temporaire, limite de débit) ; `reessayer_apres_s` vient de l'en-tête `Retry-After` du fournisseur ou du limiteur local.
"""

from __future__ import annotations

from typing import Any

from opsys.secrets_coffre import masquage

CODES_SIGNAUX: tuple[str, ...] = (
    # -- arguments, comptes, secrets
    "REJ-SIGNAUX-ARGUMENT-INVALIDE",
    "REJ-SIGNAUX-SOURCE-INCONNUE",
    "REJ-SIGNAUX-COMPTE-INCONNU",
    "REJ-SIGNAUX-COMPTE-INACTIF",
    "REJ-SIGNAUX-COMPTE-EXISTANT",
    "REJ-SIGNAUX-COMPTE-DESACTIVE",
    "REJ-SIGNAUX-SECRET-REF",
    "REJ-SIGNAUX-COFFRE-INDISPONIBLE",
    "REJ-SIGNAUX-JOURNAL-ALTERE",
    # -- transport et frontières de lecture
    "REJ-SIGNAUX-TRANSPORT-NON-BRANCHE",
    "REJ-SIGNAUX-HOTE-NON-PERMIS",
    "REJ-SIGNAUX-ECRITURE-INTERDITE",
    # -- appels au fournisseur
    "REJ-SIGNAUX-AUTH-REFUSEE",
    "REJ-SIGNAUX-PERMISSION-REFUSEE",
    "REJ-SIGNAUX-LIMITE-DEBIT",
    "REJ-SIGNAUX-QUOTA-LOCAL",
    "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE",
    "REJ-SIGNAUX-RESEAU",
    "REJ-SIGNAUX-REQUETE-INVALIDE",
    "REJ-SIGNAUX-INTROUVABLE",
    "REJ-SIGNAUX-REPONSE-INVALIDE",
    "REJ-SIGNAUX-REPONSE-TROP-GROSSE",
    "REJ-SIGNAUX-CURSEUR-INVALIDE",
    "REJ-SIGNAUX-FENETRE-INVALIDE",
    # -- faits, registre, ingestion
    "REJ-SIGNAUX-FAIT-INVALIDE",
    "REJ-SIGNAUX-FAIT-CONFLIT",
    "REJ-SIGNAUX-REGISTRE-INVALIDE",
    "REJ-SIGNAUX-REGISTRE-PLEIN",
    "REJ-SIGNAUX-DEVISE-NON-CAD",
    "REJ-SIGNAUX-ARRET-DEMANDE",
    "REJ-SIGNAUX-IMPORT-INVALIDE",
    "REJ-SIGNAUX-IMPORT-TROP-GROS",
)
_CODES = frozenset(CODES_SIGNAUX)
_DETAIL_MAX = 300


class ErreurSignaux(Exception):
    """Refus typé : un code du catalogue, un détail masqué sans contenu du fournisseur, un statut HTTP indicatif."""

    def __init__(
        self,
        code: str,
        detail: str = "",
        statut_http: int = 409,
        *,
        reprenable: bool = False,
        reessayer_apres_s: int | None = None,
    ) -> None:
        if code not in _CODES:
            raise ValueError(f"code de connecteur de signaux hors catalogue : {code!r}")
        detail = masquage.masquer_texte(detail)[:_DETAIL_MAX]
        super().__init__(f"{code} : {detail}")
        self.code, self.detail, self.statut_http = code, detail, statut_http
        self.reprenable, self.reessayer_apres_s = reprenable, reessayer_apres_s

    def publique(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "reprenable": self.reprenable,
            "reessayer_apres_s": self.reessayer_apres_s,
        }


def refus(code: str, detail: str = "", statut_http: int = 409, **options: Any) -> ErreurSignaux:
    return ErreurSignaux(code, detail, statut_http, **options)


__all__ = ["CODES_SIGNAUX", "ErreurSignaux", "refus"]
