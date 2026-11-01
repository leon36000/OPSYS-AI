"""Le PORT de transport des connecteurs de lecture : ce qui sort et ce qui revient, rien de plus.

Aucun transport réel n'existe dans ce dépôt : `TransportNonBranche` est le seul transport par défaut et il REFUSE
(`REJ-SIGNAUX-TRANSPORT-NON-BRANCHE`). Un connecteur construit une `RequeteHttp` (méthode, URL SANS secret, paramètres,
corps JSON, et une `Authentification` à part), la confie au transport, et lit une `ReponseHttp` DÉJÀ DÉCODÉE (JSON). Le
transport ne suit aucune redirection (un connecteur ne suit jamais une URL tirée d'une réponse) et ne journalise ni
l'authentification ni les paramètres.

La valeur secrète (jeton OAuth, clé d'API) n'existe que dans `Authentification.valeur`, le temps d'un appel : son
`__repr__` la masque, `RequeteHttp.__repr__` aussi. Elle n'est jamais dans l'URL d'un journal, d'un fait ou d'une
erreur.

Module sans entrée-sortie : aucun module réseau n'est importé (un test le vérifie sur la source).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any, Protocol

from .erreurs import refus

METHODES = ("GET", "POST")
DELAI_DEFAUT_S = 30.0


@dataclasses.dataclass(frozen=True)
class Authentification:
    """Comment la valeur secrète accompagne la requête : `bearer` (en-tête Authorization), `en_tete` (en-tête nommé) ou
    `parametre` (paramètre de requête nommé : certaines API l'exigent ; le transport le traite comme un secret)."""

    schema: str
    valeur: str = dataclasses.field(repr=False)
    nom: str | None = None
    annexes: tuple[tuple[str, str], ...] = dataclasses.field(default=(), repr=False)

    def __post_init__(self) -> None:
        if self.schema not in ("bearer", "en_tete", "parametre") or not isinstance(self.valeur, str) or not self.valeur:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", "authentification invalide", 500)
        if self.schema != "bearer" and not self.nom:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", "authentification nommée sans nom", 500)

    def __repr__(self) -> str:
        return f"Authentification(schema={self.schema!r}, nom={self.nom!r}, valeur=•••)"


@dataclasses.dataclass(frozen=True)
class RequeteHttp:
    methode: str
    url: str
    params: Mapping[str, str] = dataclasses.field(default_factory=dict)
    corps: Mapping[str, Any] | None = None
    authentification: Authentification | None = dataclasses.field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.methode not in METHODES:
            raise refus(
                "REJ-SIGNAUX-ECRITURE-INTERDITE", f"méthode {self.methode!r} : GET ou POST de lecture seulement", 500
            )

    def __repr__(self) -> str:
        return f"RequeteHttp({self.methode} {self.url} params={sorted(self.params)} auth={self.authentification!r})"


@dataclasses.dataclass(frozen=True)
class ReponseHttp:
    statut: int
    corps: Any = None
    en_tetes: Mapping[str, str] = dataclasses.field(default_factory=dict)


class ErreurTransport(Exception):
    """Panne en dessous du HTTP : délai dépassé, connexion refusée, TLS. Le connecteur la traduit en
    `REJ-SIGNAUX-RESEAU` (reprenable) ; son message n'est jamais recopié."""

    def __init__(self, nature: str = "reseau") -> None:
        super().__init__(nature)
        self.nature = nature


class Transport(Protocol):
    def envoyer(self, requete: RequeteHttp, *, delai_s: float = DELAI_DEFAUT_S) -> ReponseHttp:
        """Envoie UNE requête de lecture et rend la réponse décodée. Ne suit pas les redirections."""


class TransportNonBranche:
    """Le transport par défaut : il n'y en a pas. Rien ne part, rien n'est lu."""

    def envoyer(self, requete: RequeteHttp, *, delai_s: float = DELAI_DEFAUT_S) -> ReponseHttp:
        raise refus(
            "REJ-SIGNAUX-TRANSPORT-NON-BRANCHE",
            "aucun transport réel n'est branché : la lecture chez le fournisseur n'a jamais été exercée",
            503,
        )


__all__ = ["Authentification", "ErreurTransport", "ReponseHttp", "RequeteHttp", "Transport", "TransportNonBranche"]
