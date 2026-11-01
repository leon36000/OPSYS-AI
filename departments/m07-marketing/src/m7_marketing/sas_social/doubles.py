"""Adaptateurs de TEST des réseaux : ils respectent le port `AdaptateurReseau`, ne parlent à aucun réseau et ne lisent
aucune clé réelle. Ce sont des doubles : le sas qui « publie » avec eux n'a rien publié nulle part.

Le double modélise une plateforme qui NE DÉDUPLIQUE PAS (c'est le cas réel de la plupart des API de publication) :
si le sas
envoie deux fois, il y a deux publications. Les doublons qu'un test cherche sont donc ceux du sas, jamais masqués par le
double. Les pannes sont injectées par un scénario : avant l'envoi (rien n'est publié), après l'envoi (publié mais la
réponse est perdue : le cas redouté), ou définitives. Le jeton d'accès vient du fournisseur de secret (le coffre) le
temps
d'un appel ; le double le compare, ne le garde pas et ne l'écrit nulle part.

Module sans entrée-sortie : aucun module réseau n'est importé.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from . import reseaux
from .reseaux import (
    ErreurReseau,
    RequetePublication,
    ResultatPublication,
)

OK = "ok"
PANNE_AVANT_ENVOI = "panne_avant_envoi"
PANNE_APRES_ENVOI = "panne_apres_envoi"
PANNE_DEFINITIVE = "panne_definitive"
# Le double n'a pas d'horloge : l'instant qu'il déclare est fixe (le journal du sas porte le sien).
PUBLIE_LE_DOUBLE = "2026-01-01T00:00:00Z"
SCENARIOS = (OK, PANNE_AVANT_ENVOI, PANNE_APRES_ENVOI, PANNE_DEFINITIVE)


class AdaptateurDouble(reseaux.DeclarationReseau):
    """Base commune : `LIMITES` est déclarée par la classe de déclaration du réseau, jamais ici."""

    def __init__(self, *, scenario: Iterable[str] = (), jeton_attendu: str | None = None) -> None:
        self._scenario: Iterator[str] = iter(scenario)
        self._jeton_attendu = jeton_attendu
        self._numero = itertools.count(1)
        self.appels = 0
        self.publiees: list[dict[str, Any]] = []

    def _prochain(self) -> str:
        return next(self._scenario, OK)

    def _controler_jeton(self, jeton_acces: str) -> None:
        if self._jeton_attendu is not None and jeton_acces != self._jeton_attendu:
            raise ErreurReseau("REJ-RESEAU-JETON-REFUSE", "jeton refusé par le service", transitoire=False)

    def publier(self, requete: RequetePublication, jeton_acces: str) -> ResultatPublication:
        self.appels += 1
        self._controler_jeton(jeton_acces)
        issue = self._prochain()
        if issue == PANNE_AVANT_ENVOI:
            raise ErreurReseau("REJ-RESEAU-INDISPONIBLE", "service indisponible (avant l'envoi)", transitoire=True)
        if issue == PANNE_DEFINITIVE:
            raise ErreurReseau("REJ-RESEAU-CONTENU-REFUSE", "le service refuse ce contenu", transitoire=False)
        identifiant = f"{self.LIMITES.reseau}-{next(self._numero):06d}"
        resultat = ResultatPublication(
            id_externe=identifiant,
            url=f"https://{self.LIMITES.reseau}.example/p/{identifiant}",
            publie_le=PUBLIE_LE_DOUBLE,
        )
        self.publiees.append({"requete": requete, "resultat": resultat})
        if issue == PANNE_APRES_ENVOI:
            raise ErreurReseau(
                "REJ-RESEAU-DELAI-DEPASSE",
                "délai dépassé après l'envoi : le résultat est inconnu",
                transitoire=True,
                incertain=True,
            )
        return resultat

    def retrouver(self, requete: RequetePublication, depuis: str, jeton_acces: str) -> ResultatPublication | None:
        self._controler_jeton(jeton_acces)
        for trace in self.publiees:
            vue = trace["requete"]
            if (vue.compte, vue.texte, vue.titre, vue.empreinte) == (
                requete.compte,
                requete.texte,
                requete.titre,
                requete.empreinte,
            ):
                return trace["resultat"]
        return None


class DoubleGBP(AdaptateurDouble, reseaux.DeclarationGBP):
    pass


class DoubleFacebook(AdaptateurDouble, reseaux.DeclarationFacebook):
    pass


class DoubleInstagram(AdaptateurDouble, reseaux.DeclarationInstagram):
    pass


class DoubleLinkedIn(AdaptateurDouble, reseaux.DeclarationLinkedIn):
    pass


class DoubleYouTube(AdaptateurDouble, reseaux.DeclarationYouTube):
    pass


class DoubleTikTok(AdaptateurDouble, reseaux.DeclarationTikTok):
    pass


DOUBLES: Mapping[str, type[AdaptateurDouble]] = {
    classe.LIMITES.reseau: classe
    for classe in (DoubleGBP, DoubleFacebook, DoubleInstagram, DoubleLinkedIn, DoubleYouTube, DoubleTikTok)
}
