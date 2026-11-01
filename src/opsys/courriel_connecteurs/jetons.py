"""Jetons OAuth d'un compte : un `JeuJetons` qui ne s'affiche jamais, et le stockage dans le coffre de secrets.

Les jetons (accès, rafraîchissement) ne vivent QUE dans le coffre `opsys.secrets_coffre` (AES-256-GCM en enveloppe,
clé maîtresse hors base) : jamais en clair en base, en journal ni dans une erreur. La base du compte ne garde que le
NOM du secret (`courriel.<compte>.g<génération>`) ; un nom révoqué n'est jamais réutilisé (règle du coffre), donc une
reconnexion après révocation passe à la génération suivante.

Le coffre exige un administrateur actif pour définir, tourner ou révoquer un secret : l'`acteur` fourni est relu en base
à chaque opération. Si cette personne n'est plus administratrice, l'opération est refusée (`REJ-COURRIEL-COFFRE-REFUSE`)
et le compte passe en « reconnexion requise » : aucun contournement du coffre.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any, Protocol

from sqlalchemy import Connection

from ..secrets_coffre import coffre, masquage
from ..secrets_coffre.erreurs import CoffreErreur
from .erreurs import ErreurCourriel

FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]
USAGE_COFFRE = "courriel:synchronisation"
SERVICES_COFFRE = {"gmail": "google", "graph": "microsoft", "imap": "autre"}


@dataclasses.dataclass(frozen=True)
class JeuJetons:
    """Jetons d'un compte. `refresh_token` est absent pour un mot de passe d'application (IMAP)."""

    access_token: str = dataclasses.field(repr=False)
    refresh_token: str | None = dataclasses.field(default=None, repr=False)
    expire_epoch: int = 0
    portees: frozenset[str] = frozenset()

    def __repr__(self) -> str:
        return f"JeuJetons(expire_epoch={self.expire_epoch}, portees={sorted(self.portees)})"

    __str__ = __repr__

    def vers_json(self) -> str:
        return json.dumps({"a": self.access_token, "r": self.refresh_token, "e": self.expire_epoch,
                           "p": sorted(self.portees)}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def depuis_json(cls, brut: str) -> JeuJetons:
        try:
            donnees = json.loads(brut)
            access, refresh, expire = donnees["a"], donnees["r"], donnees["e"]
            portees = frozenset(donnees["p"])
            if (not isinstance(access, str) or not access or (refresh is not None and not isinstance(refresh, str))
                    or type(expire) is not int or not all(isinstance(p, str) for p in portees)):
                raise ValueError("forme")
        except (ValueError, KeyError, TypeError):
            raise ErreurCourriel("REJ-COURRIEL-COFFRE-INDISPONIBLE", "contenu du secret de jetons illisible",
                                 503) from None
        return cls(access, refresh, expire, portees)

    def valeurs_secretes(self) -> tuple[str, ...]:
        return tuple(v for v in (self.access_token, self.refresh_token) if v)


@contextlib.contextmanager
def masquer_pendant(jeu: JeuJetons) -> Iterator[None]:
    """Tant que les jetons sont en mémoire, tout journal et tout détail d'erreur les remplace par `•••`."""
    masquage.installer()
    valeurs = jeu.valeurs_secretes()
    for valeur in valeurs:
        masquage.enregistrer(valeur)
    try:
        yield
    finally:
        for valeur in valeurs:
            masquage.oublier(valeur)


class StockageJetons(Protocol):
    def lire(self, nom_secret: str) -> JeuJetons: ...

    def ecrire(self, nom_secret: str, jeu: JeuJetons, *, service: str) -> None: ...

    def revoquer(self, nom_secret: str) -> None: ...


class StockageJetonsCoffre:
    """Adaptateur de production sur `opsys.secrets_coffre.coffre` (aucune valeur ne sort du serveur)."""

    def __init__(self, fabrique: FabriqueConnexion, *, acteur: str, cle: Any = None) -> None:
        self._fabrique, self._acteur, self._cle = fabrique, acteur, cle

    @staticmethod
    def _traduire(exc: CoffreErreur) -> ErreurCourriel:
        if exc.code in {"COFFRE_ADMIN_REQUIS", "COFFRE_SECRET_REVOQUE"}:
            return ErreurCourriel("REJ-COURRIEL-COFFRE-REFUSE", f"coffre : {exc.code}", 403)
        return ErreurCourriel("REJ-COURRIEL-COFFRE-INDISPONIBLE", f"coffre : {exc.code}", 503)

    def lire(self, nom_secret: str) -> JeuJetons:
        try:
            with coffre.utiliser(nom=nom_secret, usage=USAGE_COFFRE, acteur=f"courriel:{self._acteur}"[:80],
                                 cle=self._cle, fabrique=self._fabrique) as brut:
                return JeuJetons.depuis_json(brut)
        except CoffreErreur as exc:
            raise self._traduire(exc) from None

    def ecrire(self, nom_secret: str, jeu: JeuJetons, *, service: str) -> None:
        valeur = jeu.vers_json()
        try:
            with self._fabrique() as cnx:
                try:
                    coffre.metadonnees(cnx, nom_secret)
                    existe = True
                except CoffreErreur as exc:
                    if exc.code != "COFFRE_SECRET_INCONNU":
                        raise
                    existe = False
                if existe:
                    coffre.rotation(cnx, acteur=self._acteur, nom=nom_secret, valeur=valeur, cle=self._cle)
                else:
                    coffre.definir(cnx, acteur=self._acteur, nom=nom_secret, service=service, valeur=valeur,
                                   cle=self._cle)
        except CoffreErreur as exc:
            raise self._traduire(exc) from None

    def revoquer(self, nom_secret: str) -> None:
        try:
            with self._fabrique() as cnx:
                coffre.revoquer(cnx, acteur=self._acteur, nom=nom_secret)
        except CoffreErreur as exc:
            raise self._traduire(exc) from None
