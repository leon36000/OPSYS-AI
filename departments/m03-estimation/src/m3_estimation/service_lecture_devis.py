"""Lecture M3 éphémère uniquement sous portée Core M3/M4 autorisée."""

from opsys import service_lecture_m4

from . import service_attente_devis


def verifier(requete):
    """Vérifie les sources réelles et rend la charge et leur empreinte ; n'écrit rien."""
    if type(requete) is not service_lecture_m4._RequeteDevisM3:
        raise ValueError("requête de lecture M3 non qualifiée")
    return service_attente_devis._verifier_commun(requete)
