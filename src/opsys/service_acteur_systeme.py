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
from .stockage.portabilite import DIALECTES_QUALIFIES

IDENTIFIANT = "opsys-systeme"
# Deux portées, jamais interchangeables : le moteur de recalcul n'accepte que `reconciliateur`, le planificateur des
# connecteurs (`opsys.connecteurs_planification`) que `planificateur`. Aucune des deux ne vaut une approbation humaine :
# l'acteur système n'exécute jamais une action N3 ou plus sans approbation consommée (voir CABLAGE-CONNECTEURS.md).
PORTEES = ("reconciliateur", "planificateur")
_CLE = object()


class ActeurSysteme:
    """Jeton opaque, non copiable ni sérialisable, lié au fil et au contexte du réconciliateur qui l'a créé."""

    __slots__ = ("_thread", "_ferme", "portee")
    utilisateur = IDENTIFIANT

    def __init__(self, cle, portee="reconciliateur"):
        if cle is not _CLE or portee not in PORTEES:
            raise PermissionError("acteur système réservé au réconciliateur et au planificateur")
        self._thread, self._ferme, self.portee = threading.get_ident(), False, portee

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


@contextmanager
def contexte_planificateur():
    """Ouvre l'identité système pour UN tour du planificateur des connecteurs ; mêmes refus que
    `contexte_reconciliateur` (requête HTTP/MCP, identité d'appel, livraison du bus, réentrance)."""
    if _COURANT.get() is not None or not _hors_requete():
        raise PermissionError("acteur système hors du contexte du planificateur")
    acteur = ActeurSysteme(_CLE, "planificateur")
    jeton = _COURANT.set(acteur)
    try:
        yield acteur
    finally:
        acteur._ferme = True
        _COURANT.reset(jeton)


def verifier_planificateur(acteur):
    """Garde du planificateur : l'acteur est celui du tour courant, de ce fil, de portée `planificateur`."""
    if (
        type(acteur) is not ActeurSysteme
        or acteur.portee != "planificateur"
        or acteur._ferme
        or _COURANT.get() is not acteur
        or acteur._thread != threading.get_ident()
        or not _hors_requete()
    ):
        raise PermissionError("acteur système hors du contexte du planificateur")


def planificateur_en_cours():
    """Vrai SEULEMENT pendant un tour du planificateur des connecteurs, dans le fil qui l'a ouvert : la même garde que
    `verifier_planificateur` (acteur courant, de portée `planificateur`, non fermé, hors requête HTTP/MCP, hors
    identité d'appel), rendue en booléen au lieu d'une exception. Un outil de département déclaré « constat planifié »
    s'en sert pour refuser un appelant qui n'est pas le planificateur (un agent par le MCP, la console, un appareil) :
    c'est l'identité système, jamais un argument de l'appelant, qui dit qui déclenche."""
    try:
        verifier_planificateur(_COURANT.get())
    except PermissionError:
        return False
    return True


def verifier(cnx, acteur):
    """Garde rejouée par le moteur à chaque vérification (comme `_admin` pour une session humaine)."""
    if (
        type(acteur) is not ActeurSysteme
        or acteur.portee != "reconciliateur"
        or acteur._ferme
        or _COURANT.get() is not acteur
        or acteur._thread != threading.get_ident()
        or not _hors_requete()
    ):
        raise PermissionError("acteur système hors du contexte du réconciliateur")
    if cnx.engine.dialect.name not in DIALECTES_QUALIFIES:
        raise PermissionError("acteur système qualifié pour SQLite et PostgreSQL seulement")


def est_acteur_systeme(valeur):
    return type(valeur) is ActeurSysteme
