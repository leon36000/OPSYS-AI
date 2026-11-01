"""Catalogue FERMÉ des refus typés de la couche voix/visage : `REJ-AVATAR-*` (registre et politique) et `REJ-VOIX-*`
(session voix). Un code hors de ce catalogue est une faute de programmation (`ValueError`), jamais un refus inventé à
la volée. Les détails disent quoi faire ; ils ne contiennent ni transcription, ni empreinte vocale, ni nom de locuteur.
La documentation (docs/architecture/AVATARS-VOIX.md, « Codes de refus ») suit cette liste ; les tests l'épinglent.
"""

from __future__ import annotations

from typing import Any

CODES_AVATAR: tuple[str, ...] = (
    # -- registre : écritures
    "REJ-AVATAR-ADMIN-REQUIS",
    "REJ-AVATAR-IDENTIFIANT-INVALIDE",
    "REJ-AVATAR-DECLARATION-INVALIDE",
    "REJ-AVATAR-CONFLIT-REVISION",
    "REJ-AVATAR-ENTREE-INCONNUE",
    "REJ-AVATAR-CONSENTEMENT-INCONNU",
    "REJ-AVATAR-CONSENTEMENT-DEJA-REVOQUE",
    "REJ-AVATAR-RUNTIME-INCONNU",
    "REJ-AVATAR-CANAL-INCONNU",
    # -- politique de disponibilité d'un canal (voix, audiovisuel)
    "REJ-AVATAR-CANAL-NON-REALISE",
    "REJ-AVATAR-ENTREE-ABSENTE",
    "REJ-AVATAR-RUNTIME-ABSENT",
    "REJ-AVATAR-RUNTIME-CAPACITE",
    "REJ-AVATAR-RUNTIME-INACTIF",
    "REJ-AVATAR-STT-INDISPONIBLE",
    "REJ-AVATAR-MANIFESTE-MODIFIE",
    "REJ-AVATAR-QUALIFICATION-ABSENTE",
    "REJ-AVATAR-QUALIFICATION-ECHEC",
    "REJ-AVATAR-QUALIFICATION-SIMULEE",
    "REJ-AVATAR-CONSENTEMENT-ABSENT",
    "REJ-AVATAR-CONSENTEMENT-REVOQUE",
    "REJ-AVATAR-CONSENTEMENT-EXPIRE",
    "REJ-AVATAR-CONSENTEMENT-PORTEE",
    "REJ-AVATAR-CONSENTEMENT-NON-ECRIT",
    "REJ-AVATAR-LICENCE-NON-CONFORME",
    "REJ-AVATAR-BIOMETRIE-NON-DECLAREE",
    "REJ-AVATAR-BIOMETRIE-DELAI",
    "REJ-AVATAR-ACTIF-NON-COMMERCIAL",
    "REJ-AVATAR-LANGUE",
)

CODES_VOIX: tuple[str, ...] = (
    # -- ouverture, quotas, paramètres
    "REJ-VOIX-CANAL-NON-DISPONIBLE",
    "REJ-VOIX-PARAMETRES-INVALIDES",
    "REJ-VOIX-BIOMETRIE-INTERDITE",
    "REJ-VOIX-QUOTA-SIMULTANE",
    "REJ-VOIX-QUOTA-JOUR",
    "REJ-VOIX-QUOTA-TOURS",
    "REJ-VOIX-QUOTA-ACTIONS",
    "REJ-VOIX-DUREE-MAX",
    # -- machine d'états
    "REJ-VOIX-TRANSITION-ILLEGALE",
    "REJ-VOIX-SESSION-TERMINEE",
    "REJ-VOIX-HORLOGE-INVALIDE",
    "REJ-VOIX-TEXTE-INVALIDE",
    # -- gouvernance : honnêteté, enregistrement, autorité
    "REJ-VOIX-DIVULGATION-REQUISE",
    "REJ-VOIX-ENREGISTREMENT-NON-CONSENTI",
    "REJ-VOIX-RETENTION-INVALIDE",
    "REJ-VOIX-AFFIRMATION-NON-FONDEE",
    "REJ-VOIX-ACTION-INCONNUE",
    "REJ-VOIX-ACTION-HORS-PERIMETRE",
    "REJ-VOIX-ACTION-ARGUMENTS-INVALIDES",
    "REJ-VOIX-AUTORITE-CONTOURNEE",
)

_CODES = frozenset(CODES_AVATAR) | frozenset(CODES_VOIX)


def verifier_code(code: str) -> str:
    if code not in _CODES:
        raise ValueError(f"code d'avatar hors catalogue : {code!r}")
    return code


class AvatarRefus(ValueError):
    """Refus typé : un code du catalogue, un détail sans donnée personnelle, un statut HTTP indicatif et, pour une
    politique qui rend plusieurs refus à la fois, la liste complète des codes."""

    def __init__(self, code: str, detail: str = "", statut_http: int = 409, codes: tuple[str, ...] = ()) -> None:
        self.code = verifier_code(code)
        self.detail = detail
        self.statut_http = statut_http
        self.codes = tuple(verifier_code(c) for c in (codes or (code,)))
        super().__init__(f"{code} : {detail}")

    def publique(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "refus": list(self.codes)}
