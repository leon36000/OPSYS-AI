"""Accès à un point d'accès de modèles : URL résolue et secret du coffre, le temps d'un appel.

Le secret est résolu CÔTÉ SERVEUR, au dernier moment, par `coffre.utiliser` (journal d'accès, masquage de la valeur dans
tous les journaux du processus), hors transaction métier — comme le test de connexion du registre. Il n'existe en clair
que dans le bloc `with`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection

from ..fournisseurs.modele import Fournisseur
from ..secrets_coffre import coffre
from ..secrets_coffre.erreurs import CoffreErreur
from . import codes, service
from .client import ClientOpenAI, Ouvrir
from .codes import ModelesErreur

FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]
ACTEUR_SYSTEME = "systeme:modeles"


def url_du_fournisseur(fabrique: FabriqueConnexion, fournisseur: Fournisseur) -> str:
    point = fournisseur.point_acces or ""
    if point.startswith("passerelle:"):
        with fabrique() as cnx:
            reglage = service.passerelle(cnx)
        if reglage is None:
            raise ModelesErreur(codes.PASSERELLE_ABSENTE, "la passerelle n'est pas configurée", 409)
        return reglage["url_base"]
    if point.startswith(("https://", "http://")):
        return point
    raise ModelesErreur(codes.NON_TESTABLE, f"{fournisseur.identifiant} : point d'accès non appelable par HTTP", 409)


@contextlib.contextmanager
def client_du_fournisseur(
    fabrique: FabriqueConnexion,
    fournisseur: Fournisseur,
    *,
    ouvrir: Ouvrir | None = None,
    delai_s: float = 8.0,
    dans_transaction: bool = False,
) -> Iterator[ClientOpenAI]:
    url = url_du_fournisseur(fabrique, fournisseur)
    if fournisseur.nom_secret is None:
        yield ClientOpenAI(url, None, delai_s=delai_s, ouvrir=ouvrir)
        return
    try:
        with coffre.utiliser(
            nom=fournisseur.nom_secret,
            usage=f"fournisseur:{fournisseur.identifiant}",
            acteur=ACTEUR_SYSTEME,
            fabrique=fabrique,
            dans_transaction=dans_transaction,
        ) as cle:
            yield ClientOpenAI(url, cle, delai_s=delai_s, ouvrir=ouvrir)
    except CoffreErreur as exc:
        raise ModelesErreur(codes.SECRET_INDISPONIBLE, f"secret indisponible ({exc.code})", 409) from None


@contextlib.contextmanager
def client_passerelle(
    fabrique: FabriqueConnexion, *, ouvrir: Ouvrir | None = None, delai_s: float = 8.0
) -> Iterator[tuple[ClientOpenAI, dict[str, Any]]]:
    """Client de la passerelle elle-même (clé du réglage `passerelle`) : test de connexion et découverte."""
    with fabrique() as cnx:
        reglage = service.passerelle(cnx)
    if reglage is None:
        raise ModelesErreur(codes.PASSERELLE_ABSENTE, "la passerelle n'est pas configurée", 409)
    try:
        with coffre.utiliser(
            nom=reglage["secret_cle"], usage="passerelle:administration", acteur=ACTEUR_SYSTEME, fabrique=fabrique
        ) as cle:
            yield ClientOpenAI(reglage["url_base"], cle, delai_s=delai_s, ouvrir=ouvrir), reglage
    except CoffreErreur as exc:
        raise ModelesErreur(codes.SECRET_INDISPONIBLE, f"secret indisponible ({exc.code})", 409) from None


@contextlib.contextmanager
def cle_maitre(fabrique: FabriqueConnexion) -> Iterator[str]:
    """Clé d'administration de la passerelle pour la CLI : le coffre d'abord (réglage `passerelle`), sinon
    `LITELLM_MASTER_KEY` du serveur (installations d'avant les rôles). Vide si aucune des deux : le client la
    refusera."""
    import os

    with fabrique() as cnx:
        reglage = service.passerelle(cnx)
    with contextlib.ExitStack() as pile:
        cle = ""
        if reglage is not None:
            try:
                cle = pile.enter_context(
                    coffre.utiliser(
                        nom=reglage["secret_cle"],
                        usage="passerelle:administration",
                        acteur=ACTEUR_SYSTEME,
                        fabrique=fabrique,
                    )
                )
            except CoffreErreur:
                cle = ""  # coffre illisible : retombe sur l'environnement du serveur, comme avant
        yield cle or os.environ.get("LITELLM_MASTER_KEY", "")
