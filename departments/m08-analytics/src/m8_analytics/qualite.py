"""Évaluation de qualité et de fraîcheur d'une métrique (T3.1, DEFINITION-PRODUIT.md §7 M8.4/M8.5).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. Les fonctions ci-dessous ne
lisent JAMAIS le temps elles-mêmes — la fraîcheur qu'elles comparent (``fraicheur_jours``) est
TOUJOURS un nombre déjà calculé par l'appelant à partir d'un horodatage de référence explicite
(même discipline que ``semantique.py::deriver_metrique(horodatage_reference=...)``, dont la
sortie ``fraicheur`` est la source attendue de ce paramètre — voir ``outils.py`` pour la
composition). C'est ce qui rend ce module « purement calculé à partir d'un maintenant fourni,
jamais l'horloge implicite » : il n'y a ici ni ``datetime.now()`` ni aucune arithmétique de
dates, seulement des comparaisons de nombres déjà connus.

Fail-closed : une donnée absente (``n == 0`` ou ``valeur is None``) n'est JAMAIS remplacée par un
zéro ou une moyenne devinée — ``evaluer_presence`` renvoie un verdict nommé qui dit quoi
demander. Une valeur périmée, hors plage, en double ou incohérente avec ses composantes devient
une évaluation renvoyée à l'appelant (jamais un silence) ; ``alertes.py`` la transforme ensuite
en action PROPOSÉE, jamais exécutée.

Chaque fonction renvoie ``None`` quand il n'y a rien à signaler (même patron que
``xmr.py::detecter_signal``), ou un dict avec un ``verdict`` nommé sinon.

T3.1-suite (docs/programme/PLAN.md) ajoute deux familles « au-delà de la plage » :
``evaluer_unicite`` (doublons d'observation pour une même métrique) et ``evaluer_coherence``
(une métrique dérivée qui ne concorde pas avec ses composantes, elles-mêmes déjà dérivées —
jamais une valeur de composante fournie brute par l'appelant, voir ``outils.py``).
"""

from __future__ import annotations

import math
from typing import Any

VERDICT_DONNEE_ABSENTE = "REJ-QUALITE-DONNEE-ABSENTE"
VERDICT_DONNEE_INVALIDE = "REJ-QUALITE-DONNEE-INVALIDE"
VERDICT_DONNEE_PERIMEE = "REJ-QUALITE-DONNEE-PERIMEE"
VERDICT_HORS_PLAGE = "REJ-QUALITE-HORS-PLAGE"
VERDICT_DOUBLON = "REJ-QUALITE-DOUBLON"
VERDICT_INCOHERENT = "REJ-QUALITE-INCOHERENCE"


def evaluer_presence(
    metric_id: str, n: int, valeur: float | None, valeurs_invalides: int = 0,
) -> dict[str, Any] | None:
    """``VERDICT_DONNEE_ABSENTE`` si aucune valeur n'a pu être dérivée (``n == 0`` ou
    ``valeur is None`` — les deux sont toujours cohérents en sortie de
    ``semantique.deriver_metrique``, le second contrôle reste une garde défensive), sinon
    ``None``. Ne dit jamais pourquoi la donnée manque (ce n'est pas une cause) : seulement le
    fait, pour que l'appelant (``alertes.py``) sache quoi demander et à qui."""
    if valeur is not None and not math.isfinite(valeur):
        valeurs_invalides = max(valeurs_invalides, 1)
    if valeurs_invalides:
        return {
            "metric_id": metric_id,
            "verdict": VERDICT_DONNEE_INVALIDE,
            "n": n,
            "valeurs_invalides": valeurs_invalides,
        }
    if n == 0 or valeur is None:
        resultat = {"metric_id": metric_id, "verdict": VERDICT_DONNEE_ABSENTE, "n": n}
        return resultat
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


def evaluer_unicite(metric_id: str, horodatages: list[str]) -> dict[str, Any] | None:
    """``VERDICT_DOUBLON`` si au moins un horodatage apparaît plus d'une fois dans
    ``horodatages`` — la liste des horodatages de TOUTES les observations numériques valides déjà
    trouvées pour ce ``metric_id`` (même filtre que ``semantique.deriver_metrique`` : une valeur
    non convertible en nombre est déjà exclue par l'appelant avant d'arriver ici).

    Deux maillons distincts du registre qui prétendent au MÊME instant pour la MÊME métrique sont
    une anomalie de qualité — que leurs valeurs concordent ou non, et peu importe laquelle
    ``semantique.deriver_metrique`` choisit d'afficher (la plus récemment écrite) : ce choix
    masque l'ambiguïté que cette fonction signale explicitement, jamais en silence.

    Aucun horodatage, ou tous distincts : rien à signaler, ``None`` (même patron que
    ``evaluer_presence``/``evaluer_plage``)."""
    occurrences: dict[str, int] = {}
    for horodatage in horodatages:
        occurrences[horodatage] = occurrences.get(horodatage, 0) + 1
    doublons = {horodatage: n for horodatage, n in occurrences.items() if n > 1}
    if not doublons:
        return None
    return {
        "metric_id": metric_id,
        "verdict": VERDICT_DOUBLON,
        "horodatages_doublons": dict(sorted(doublons.items())),
        "n_observations": len(horodatages),
    }


def evaluer_coherence(
    metric_id: str,
    valeur: float,
    composantes: dict[str, dict[str, float]],
    tolerance: float,
) -> dict[str, Any] | None:
    """``VERDICT_INCOHERENT`` si ``valeur`` (la métrique DÉRIVÉE, déjà dérivée par le même
    mécanisme que les autres contrôles de ce module) s'écarte de plus de ``tolerance`` de la
    somme pondérée de ``composantes`` — ``{metric_id_composante: {"coefficient": ..., "valeur":
    ...}}``, où ``coefficient`` encode le signe attendu dans la formule (ex. ``-1.0`` pour une
    composante soustraite, comme un coût dans un calcul de marge) et ``valeur`` est la valeur
    DÉJÀ dérivée de cette composante par le même registre (``outils.py`` la résout via
    ``semantique.deriver_metrique``, jamais une valeur transmise brute par l'appelant — sans
    quoi un agent pourrait « inventer » la valeur d'une composante).

    ``tolerance`` est TOUJOURS fournie par l'appelant (jamais un défaut interne, même discipline
    que ``fraicheur_attendue_jours`` ou ``n_minimal`` de ``xmr.py``) : une tolérance de calcul
    (arrondi, unité) diffère d'une métrique à l'autre, M8 ne peut pas la deviner. Limite
    inclusive, même convention que ``evaluer_fraicheur`` : un écart exactement égal à la
    tolérance n'est pas encore une incohérence, seul un dépassement STRICT l'est.

    ``composantes`` vide : la somme attendue est 0 — un choix assumé de l'appelant (ex. une
    métrique censée être nulle), pas une absence de données (``evaluer_presence`` couvre déjà ce
    cas pour la métrique dérivée elle-même)."""
    valeur_attendue = sum(detail["coefficient"] * detail["valeur"] for detail in composantes.values())
    ecart = valeur - valeur_attendue
    if abs(ecart) <= tolerance:
        return None
    return {
        "metric_id": metric_id,
        "verdict": VERDICT_INCOHERENT,
        "valeur": valeur,
        "valeur_attendue": valeur_attendue,
        "ecart": ecart,
        "tolerance": tolerance,
        "composantes": {cle: dict(detail) for cle, detail in composantes.items()},
    }
