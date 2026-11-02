"""Cadence par défaut des constats planifiés : dérivée de la fraîcheur du catalogue de M8, jamais d'une constante.

Module PUR pour le calcul (ADR-0009 : aucune horloge, aucun import d'``opsys``) ; seule ``cadence_par_defaut`` lit des
fichiers de M8 (le catalogue et le ``department.yaml`` de M8, où le propriétaire déclare ses fenêtres et ses cadences).

Le problème : un constat (M5, M7, M4, M2, M6, M1) alimente des mesures de M8 qui deviennent PÉRIMÉES au-delà de leur
fenêtre de fraîcheur (``fraicheur_mesures.fenetre_effective`` : ``max(fenetre_s, cadence_s)`` du catalogue, remplacée
par ce que le propriétaire a déclaré). Un constat planifié doit donc repasser AVANT que la plus stricte de ces fenêtres
ne soit échue, et une panne passagère ne doit pas la périmer :

* la fenêtre d'un constat est la plus STRICTE des fenêtres des mesures qu'il alimente (une seule source, plusieurs
  mesures : la plus exigeante commande) ;
* le constat passe ``PASSAGES_PAR_FENETRE`` fois par fenêtre : un passage manqué (panne, redémarrage, bail repris)
  laisse encore un passage avant la péremption. Ce nombre est une marge de sécurité de l'ingénierie (pas un rythme
  d'affaires), testée : à 1, une panne d'un seul passage périmerait la mesure.

Le résultat est un DÉFAUT : l'administrateur peut régler l'intervalle à l'activation (borné par le planificateur) ;
une fenêtre ou une cadence que le propriétaire a déclarée change le défaut, sans redémarrage du code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import catalogue_mesures, fraicheur_mesures

PASSAGES_PAR_FENETRE = 2
REJ_MESURE_INCONNUE = "REJ-CADENCE-MESURE-INCONNUE"
REJ_AUCUNE_FENETRE = "REJ-CADENCE-AUCUNE-FENETRE"
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"


def calculer(
    metric_ids: list[str] | tuple[str, ...],
    catalogue: dict[str, Any],
    fenetres_proprietaire: dict[str, int] | None = None,
    cadences_proprietaire: dict[str, int] | None = None,
) -> dict[str, Any]:
    """``{fenetre_s, intervalle_s, mesure_limitante, passages_par_fenetre, fenetres}`` pour les mesures données.

    La fenêtre de chaque mesure est celle du PRODUCTEUR (catalogue, cadence, déclaration du propriétaire) : la fenêtre
    du département source ou de l'appelant ne la resserre jamais ici, elle dépend d'une lecture. Une mesure inconnue
    du catalogue est un refus nommé (une faute de frappe du manifeste d'un département ne passe pas en silence) ; une
    mesure terminale (sans fenêtre) ne commande rien, et si TOUTES le sont, il n'y a pas de cadence à dériver."""
    entrees = catalogue_mesures.par_identifiant(catalogue)
    inconnues = sorted(m for m in metric_ids if m not in entrees)
    if inconnues:
        raise ValueError(f"{REJ_MESURE_INCONNUE} : mesure(s) absente(s) du catalogue de M8 : {inconnues}")
    fenetres: dict[str, int] = {}
    for metric_id in metric_ids:
        secondes = fraicheur_mesures.fenetre_effective(
            entrees[metric_id], fenetres_proprietaire or {}, None, None, cadences_proprietaire
        )["secondes"]
        if secondes is not None:
            fenetres[metric_id] = secondes
    if not fenetres:
        raise ValueError(f"{REJ_AUCUNE_FENETRE} : aucune des mesures {sorted(metric_ids)} n'a de fenêtre de fraîcheur")
    limitante = min(fenetres, key=lambda m: (fenetres[m], m))
    fenetre = fenetres[limitante]
    return {
        "fenetre_s": fenetre,
        "intervalle_s": max(1, fenetre // PASSAGES_PAR_FENETRE),
        "mesure_limitante": limitante,
        "passages_par_fenetre": PASSAGES_PAR_FENETRE,
        "fenetres": dict(sorted(fenetres.items())),
    }


def _configuration_proprietaire() -> dict[str, Any]:
    donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    configuration = donnees.get("configuration")
    return configuration if isinstance(configuration, dict) else {}


def cadence_par_defaut(metric_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """``calculer`` sur le catalogue livré et la configuration que le propriétaire a déclarée dans le manifeste de M8
    (``configuration.fraicheur_mesures_s`` et ``configuration.cadences_mesures_s``, vides à la livraison). Une valeur
    invalide est REFUSÉE par ``fraicheur_mesures.lire_configuration`` (donc ignorée ici, comme dans la lecture des
    mesures) : la cadence suit exactement la fenêtre que la lecture appliquerait."""
    catalogue = catalogue_mesures.charger()
    configuration = _configuration_proprietaire()
    fenetres = fraicheur_mesures.lire_configuration(configuration.get(fraicheur_mesures.CLE_CONFIGURATION), catalogue)
    cadences = fraicheur_mesures.lire_configuration(configuration.get(fraicheur_mesures.CLE_CADENCES), catalogue)
    return calculer(metric_ids, catalogue, fenetres["fenetres"], cadences["fenetres"])


__all__ = ["PASSAGES_PAR_FENETRE", "REJ_AUCUNE_FENETRE", "REJ_MESURE_INCONNUE", "cadence_par_defaut", "calculer"]
