"""Le fournisseur de secret de M7 : un secret ou un jeton d'accès sort du coffre le temps d'un appel, jamais avant.

`fournisseur_du_coffre(nom, usage, acteur)` rend un fournisseur (`() -> gestionnaire de contexte qui rend la
valeur`) qui
résout `nom` par `opsys.secrets_coffre.coffre.utiliser` : accès journalisé au coffre, valeur masquée de tout journal
tant
qu'elle est en mémoire, rien d'écrit nulle part. Le coffre REFUSE la résolution dans une transaction métier
(`COFFRE_TRANSACTION_METIER`) : un fournisseur ne s'ouvre donc que depuis un exécuteur hors transaction, jamais
depuis un
outil d'agent. Le fournisseur ne stocke rien : chaque appel redemande au coffre (une rotation ou une révocation prend
effet à l'appel suivant).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from opsys.secrets_coffre import coffre

FournisseurSecret = Callable[[], contextlib.AbstractContextManager[str]]


def fournisseur_du_coffre(nom: str, usage: str, acteur: str) -> FournisseurSecret:
    def ouvrir() -> contextlib.AbstractContextManager[str]:
        return coffre.utiliser(usage=usage, acteur=acteur, nom=nom)

    return ouvrir
