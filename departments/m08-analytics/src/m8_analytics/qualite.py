"""Évaluation de qualité et de fraîcheur d'une métrique (T3.1, DEFINITION-PRODUIT.md §7 M8.4/M8.5).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. Les trois fonctions ci-dessous
ne lisent JAMAIS le temps elles-mêmes — la fraîcheur qu'elles comparent (``fraicheur_jours``) est
TOUJOURS un nombre déjà calculé par l'appelant à partir d'un horodatage de référence explicite
(même discipline que ``semantique.py::deriver_metrique(horodatage_reference=...)``, dont la
sortie ``fraicheur`` est la source attendue de ce paramètre — voir ``outils.py`` pour la
composition). C'est ce qui rend ce module « purement calculé à partir d'un maintenant fourni,
jamais l'horloge implicite » : il n'y a ici ni ``datetime.now()`` ni aucune arithmétique de
dates, seulement des comparaisons de nombres déjà connus.

Fail-closed : une donnée absente (``n == 0`` ou ``valeur is None``) n'est JAMAIS remplacée par un
zéro ou une moyenne devinée — ``evaluer_presence`` renvoie un verdict nommé qui dit quoi
demander. Une valeur périmée ou hors plage devient une évaluation renvoyée à l'appelant (jamais
un silence) ; ``alertes.py`` la transforme ensuite en action PROPOSÉE, jamais exécutée.

Chaque fonction renvoie ``None`` quand il n'y a rien à signaler (même patron que
``xmr.py::detecter_signal``), ou un dict avec un ``verdict`` nommé sinon.
"""

from __future__ import annotations

from typing import Any

VERDICT_DONNEE_ABSENTE = "REJ-QUALITE-DONNEE-ABSENTE"
VERDICT_DONNEE_PERIMEE = "REJ-QUALITE-DONNEE-PERIMEE"
VERDICT_HORS_PLAGE = "REJ-QUALITE-HORS-PLAGE"


def evaluer_presence(metric_id: str, n: int, valeur: float | None) -> dict[str, Any] | None:
    """``VERDICT_DONNEE_ABSENTE`` si aucune valeur n'a pu être dérivée (``n == 0`` ou
    ``valeur is None`` — les deux sont toujours cohérents en sortie de
    ``semantique.deriver_metrique``, le second contrôle reste une garde défensive), sinon
    ``None``. Ne dit jamais pourquoi la donnée manque (ce n'est pas une cause) : seulement le
    fait, pour que l'appelant (``alertes.py``) sache quoi demander et à qui."""
    if n == 0 or valeur is None:
        return {"metric_id": metric_id, "verdict": VERDICT_DONNEE_ABSENTE, "n": n}
    return None


def evaluer_fraicheur(
    metric_id: str, fraicheur_jours: float | None, fraicheur_attendue_jours: float
) -> dict[str, Any] | None:
    """``VERDICT_DONNEE_PERIMEE`` si ``fraicheur_jours`` (âge de la dernière valeur, en jours,
    DÉJÀ calculé par l'appelant contre un horodatage de référence explicite) dépasse
    ``fraicheur_attendue_jours`` (seuil du registre, jamais un défaut interne — fourni par
    l'appelant, même discipline que ``n_minimal`` dans xmr.py). ``fraicheur_jours is None``
    signifie qu'il n'y a aucune valeur : ``evaluer_presence`` l'a déjà signalé, jamais de
    doublon ici — retour ``None``."""
    if fraicheur_jours is None:
        return None
    if fraicheur_jours > fraicheur_attendue_jours:
        return {
            "metric_id": metric_id,
            "verdict": VERDICT_DONNEE_PERIMEE,
            "fraicheur_jours": fraicheur_jours,
            "fraicheur_attendue_jours": fraicheur_attendue_jours,
        }
    return None


def evaluer_plage(
    metric_id: str, valeur: float | None, plage_min: float | None, plage_max: float | None
) -> dict[str, Any] | None:
    """``VERDICT_HORS_PLAGE`` si ``valeur`` est en dehors de ``[plage_min, plage_max]`` (bornes
    optionnelles indépendantes : ``None`` d'un côté = pas de contrainte de ce côté). ``valeur is
    None`` : rien à évaluer, ``evaluer_presence`` a déjà signalé l'absence — retour ``None``."""
    if valeur is None:
        return None
    hors_borne_basse = plage_min is not None and valeur < plage_min
    hors_borne_haute = plage_max is not None and valeur > plage_max
    if not (hors_borne_basse or hors_borne_haute):
        return None
    return {
        "metric_id": metric_id,
        "verdict": VERDICT_HORS_PLAGE,
        "valeur": valeur,
        "plage_min": plage_min,
        "plage_max": plage_max,
    }
