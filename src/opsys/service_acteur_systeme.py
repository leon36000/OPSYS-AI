"""Acteur système `opsys-systeme` (D2) : l'identité de service du recalcul automatique du coût certifié.

Ce n'est PAS une session humaine simulée : aucune personne `opsys-systeme` n'existe en base, aucun cookie, aucun
rôle ; la console et le MCP ne peuvent ni le créer ni le présenter. Il n'existe que pendant une exécution du
réconciliateur (`contexte_reconciliateur`), dans le fil qui l'a ouvert, hors de toute requête HTTP/MCP, de toute
livraison du bus et de toute identité d'appel. Le recalcul certifié est un calcul interne réversible (règle
d'autonomie N0–N2) : son autorité est la paire de politiques `m4.recalculer_v3` + `m4.verifier_v3`, octroyée par un
admin depuis la console (D1) ; sans elles, l'acteur système ne peut rien.

Chaque exécution est journalisée : par le moteur (intention, attestation, audits `usage` avec l'acteur
`opsys-systeme`) quand elle publie, et par le réconciliateur (`cout_certifie_reconciliations`, journal Python).

Convention entre composants de confiance, pas une frontière contre du Python arbitraire dans le processus.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar

from . import contexte

IDENTIFIANT = "opsys-systeme"
_CLE = object()


class ActeurSysteme:
    """Jeton opaque, non copiable ni sérialisable, lié au fil et au contexte du réconciliateur qui l'a créé."""

    __slots__ = ("_thread", "_ferme")
    utilisateur = IDENTIFIANT

    def __init__(self, cle):
        if cle is not _CLE:
            raise PermissionError("acteur système réservé au réconciliateur")
        self._thread, self._ferme = threading.get_ident(), False

    def __copy__(self):
        raise PermissionError("copie interdite")

    def __deepcopy__(self, memo):
        raise PermissionError("copie interdite")

    def __reduce__(self):
        raise PermissionError("sérialisation interdite")

    def __repr__(self):
        return f"ActeurSysteme({IDENTIFIANT})"


_COURANT: ContextVar[ActeurSysteme | None] = ContextVar("opsys_acteur_systeme", default=None)


def _hors_requete():
    from .evenements.repartiteur import horodatage_livraison

    return (
        not contexte.appel_provient_du_mcp()
        and contexte.identite_appelante() is None
        and contexte.DEPARTEMENT_APPELANT.get() is None
        and contexte.attestation_appareil() is None
        and horodatage_livraison() is None
    )


@contextmanager
def contexte_reconciliateur():
    """Ouvre l'identité système pour UNE exécution du réconciliateur ; refusée depuis une requête HTTP/MCP, une
    identité d'appel ou une livraison du bus, et non réentrante."""
    if _COURANT.get() is not None or not _hors_requete():
        raise PermissionError("acteur système hors du contexte du réconciliateur")
    acteur = ActeurSysteme(_CLE)
    jeton = _COURANT.set(acteur)
    try:
        yield acteur
    finally:
        acteur._ferme = True
        _COURANT.reset(jeton)


def verifier(cnx, acteur):
    """Garde rejouée par le moteur à chaque vérification (comme `_admin` pour une session humaine)."""
    if (
        type(acteur) is not ActeurSysteme
        or acteur._ferme
        or _COURANT.get() is not acteur
        or acteur._thread != threading.get_ident()
        or not _hors_requete()
    ):
        raise PermissionError("acteur système hors du contexte du réconciliateur")
    if cnx.engine.dialect.name != "sqlite":
        raise PermissionError("acteur système qualifié pour SQLite seulement")


def est_acteur_systeme(valeur):
    return type(valeur) is ActeurSysteme
