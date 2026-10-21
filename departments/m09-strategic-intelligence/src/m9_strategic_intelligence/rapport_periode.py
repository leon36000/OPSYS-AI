"""Synthèse interne de période, sources M8 et suivis M9, sans effet terrain (M9.6, tranche « synthèse de période »).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge, aucune base. La période ``[debut, fin)`` est
fournie par l'appelant, avec fuseaux, et comparée en instants ; aucune semaine devinée, aucun jour calendaire.

Deux sources historisées seulement :

1. les compteurs du bilan existant (`bilan_suivis.bilan_suivis_decision`, appelé avec ``depart=0`` et le même
   budget) : seuls ``compteurs``, ``total`` et ``vue`` en sont recopiés, jamais recomptés, jamais ses lignes ;
   toute erreur du bilan (``REJ-BILAN-*``, ``REJ-SUIVI-CLOTURE-*``, ``REJ-BILAN-BORNE`` compris) est propagée ;
2. les alertes M8 déjà reçues dont ``horodatage_reference`` (instant du chantier, PAS de réception) tombe dans
   ``[debut, fin)``. Ce sont les alertes connues à la lecture : une alerte reçue plus tard, de référence dans la
   période, s'ajoute et change ``total`` et ``vue``. Aucun instantané historique n'est prétendu.

Toutes les alertes, hors période comprises, sont contrôlées AVANT le filtre : identifiant unique, instant lisible
à fuseau explicite (aucun repli UTC), preuve de même métrique. Le schéma complet du catalogue
(``m8.alerte_proposee``) est vérifié par l'adaptateur natif, pas ici. File du propriétaire, état consolidé et
snapshots ne sont jamais lus : ``manques`` le dit, sans rien prétendre exécuté ni vérifié sur le terrain.

``vue`` : empreinte des trois registres complets et des bornes reçues ; une reprise ``depart > 0`` exige la vue
courante. Taille de la réponse ENTIÈRE mesurée, ``manques`` compris, avant chaque alerte ajoutée : jamais de
troncature ; ce qui ne tient pas est compté dans ``reste`` et ``prochain_depart``.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from .bilan_suivis import bilan_suivis_decision
from .echeancier_suivis import _EMPREINTE, _instant, _taille
from .encodage import empreinte
from .lecture_alertes import ORDRE_ALERTES, _ordonner

__all__ = ["assembler_rapport_periode"]

_TYPE = "RAPPORT_PERIODE"
_MANQUES_PERMANENTS = (
    {
        "section": "decisions_en_attente_periode",
        "constat": "aucune source historisée de la file d'attente ; la file du propriétaire est un état courant, "
                   "non rapporté",
        "verifie": "NON_COUVERT : opsys.approbations.file_proprietaire non lue",
    },
    {
        "section": "faits_periode",
        "constat": "faits de snapshots non couverts par cette tranche",
        "verifie": "NON_COUVERT : registre snapshots non lu",
    },
    {
        "section": "reception_alertes",
        "constat": "instant de réception non disponible ; filtre sur l'instant de référence chantier. Alertes "
                   "connues à la lecture : une alerte reçue plus tard, de référence dans la période, s'ajoute et "
                   "change total et vue",
        "verifie": "NON_COUVERT : aucun instant de réception lu",
    },
)


def _nom(valeur: Any) -> str:
    """Identifiant cité dans un refus, borné : jamais le contenu de l'alerte."""
    return repr(valeur[:200] if isinstance(valeur, str) else type(valeur).__name__)


def _borne(valeur: Any, nom: str) -> datetime:
    """Borne ISO 8601 à fuseau explicite, contrôlée par le rapport avant tout appel au bilan."""
    if not isinstance(valeur, str):
        raise ValueError(f"REJ-RAPPORT-PERIODE : {nom} chaîne ISO 8601 avec fuseau explicite attendue")
    try:
        instant = _instant(valeur, nom)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"REJ-RAPPORT-PERIODE : {nom} illisible ou sans fuseau explicite") from exc
    if instant.utcoffset() is None:
        raise ValueError(f"REJ-RAPPORT-PERIODE : {nom} sans fuseau explicite")
    return instant


def _instants_alertes(alertes: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[datetime]:
    """Toutes les alertes, hors période comprises, avant tout filtre : refus nommé au premier écart."""
    vus: set[str] = set()
    instants: list[datetime] = []
    for rang, alerte in enumerate(alertes):
        if not isinstance(alerte, dict):
            raise ValueError(f"REJ-RAPPORT-ALERTE : alerte de rang {rang} non objet")
        evenement_id = alerte.get("evenement_id")
        if not isinstance(evenement_id, str) or not evenement_id:
            raise ValueError(f"REJ-RAPPORT-ALERTE : evenement_id absent ou vide au rang {rang}")
        if evenement_id in vus:
            raise ValueError(f"REJ-RAPPORT-ALERTE-DOUBLON : evenement_id {_nom(evenement_id)} reçu plusieurs fois")
        vus.add(evenement_id)
        metric_id, preuve = alerte.get("metric_id"), alerte.get("preuve")
        if not isinstance(metric_id, str) or not isinstance(preuve, dict) or preuve.get("metric_id") != metric_id:
            raise ValueError(
                f"REJ-RAPPORT-ALERTE-PREUVE : preuve de {_nom(evenement_id)} sans la métrique de l'alerte"
            )
        valeur = alerte.get("horodatage_reference")
        try:
            if not isinstance(valeur, str):
                raise TypeError(valeur)
            instant = _instant(valeur, "horodatage_reference")
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"REJ-RAPPORT-ALERTE-FUSEAU : horodatage_reference illisible ou sans fuseau explicite pour "
                f"{_nom(evenement_id)}, aucun repli UTC"
            ) from exc
        if instant.utcoffset() is None:
            raise ValueError(
                f"REJ-RAPPORT-ALERTE-FUSEAU : horodatage_reference sans fuseau explicite pour {_nom(evenement_id)}"
            )
        instants.append(instant)
    return instants


def assembler_rapport_periode(
    suivis: list[dict[str, Any]],
    clotures: list[dict[str, Any]],
    alertes: list[dict[str, Any]],
    debut: str,
    fin: str,
    depart: int = 0,
    vue_attendue: str | None = None,
    *,
    budget_caracteres: int,
) -> dict[str, Any]:
    """Une page de ``RAPPORT_PERIODE`` pour ``[debut, fin)`` : compteurs du bilan existant et alertes M8 de
    référence dans la période, dans l'ordre de ``ORDRE_ALERTES`` à partir de ``depart``, autant d'alertes
    complètes que ``budget_caracteres`` en laisse tenir. ``debut``/``fin`` sont rendus tels que reçus. Les
    entrées ne sont jamais modifiées ; les alertes rendues sont les originales, inchangées."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        raise ValueError(f"REJ-RAPPORT-ARGUMENT : depart entier supérieur ou égal à 0 attendu, reçu {depart!r}")
    if isinstance(budget_caracteres, bool) or not isinstance(budget_caracteres, int) or budget_caracteres < 1:
        raise ValueError("REJ-RAPPORT-ARGUMENT : budget_caracteres entier strictement positif attendu")
    if vue_attendue is not None and (not isinstance(vue_attendue, str) or not _EMPREINTE.fullmatch(vue_attendue)):
        raise ValueError("REJ-RAPPORT-ARGUMENT : vue_attendue empreinte hexadécimale de 64 caractères attendue")
    if depart > 0 and vue_attendue is None:
        raise ValueError("REJ-RAPPORT-VUE : vue_attendue de la page précédente requise pour depart > 0")
    borne_debut = _borne(debut, "debut")
    borne_fin = _borne(fin, "fin")
    if not borne_debut < borne_fin:
        raise ValueError("REJ-RAPPORT-PERIODE : debut strictement antérieur à fin requis (instants comparés)")
    if not isinstance(alertes, (list, tuple)):
        raise ValueError("REJ-RAPPORT-ARGUMENT : liste des alertes M8 reçues attendue")

    instants = _instants_alertes(alertes)
    # Bilan existant tel quel, page 0, même budget : ses erreurs, REJ-BILAN-BORNE compris, ne sont jamais masquées.
    bilan = bilan_suivis_decision(suivis, clotures, debut, fin, 0, None, budget_caracteres=budget_caracteres)
    vue = empreinte({"type": _TYPE, "debut": debut, "fin": fin, "suivis": list(suivis),
                     "clotures": list(clotures), "alertes": list(alertes)})
    if vue_attendue is not None and vue_attendue != vue:
        raise ValueError(
            "REJ-RAPPORT-VUE-PERIMEE : plans, clôtures, alertes ou bornes ont changé ; reprendre à depart=0"
        )

    retenues = copy.deepcopy(_ordonner(
        [alerte for alerte, instant in zip(alertes, instants, strict=True) if borne_debut <= instant < borne_fin]
    ))
    total = len(retenues)
    if depart > total:
        raise ValueError(f"REJ-RAPPORT-ARGUMENT : depart {depart} au-delà de la fin ({total} alerte(s))")
    suivis_periode = {"compteurs": dict(bilan["compteurs"]), "total": bilan["total"], "vue_bilan": bilan["vue"]}
    manques = [dict(manque) for manque in _MANQUES_PERMANENTS]
    if not total:
        manques.append({"section": "alertes_periode",
                        "constat": "aucune alerte M8 d'instant de référence dans [debut, fin)",
                        "verifie": "VIDE : aucune alerte reçue retenue par le filtre de période"})
    if not bilan["total"]:
        manques.append({"section": "suivis",
                        "constat": "aucun suivi ouvert, clos ou encore ouvert dans la période selon le bilan existant",
                        "verifie": "VIDE : total du bilan de suivis égal à 0"})

    def page(nombre: int) -> dict[str, Any]:
        dernier = depart + nombre
        reste = total - dernier
        return {
            "type": _TYPE,
            "debut": debut,
            "fin": fin,
            "vue": vue,
            "suivis": suivis_periode,
            "alertes_periode": {
                "total": total,
                "depart": depart,
                "affichees": nombre,
                "reste": reste,
                "prochain_depart": dernier if reste else None,
                "ordre": ORDRE_ALERTES,
                "alertes": retenues[depart:dernier],
            },
            "manques": manques,
            "statut": "NON_VALIDE",
            "actualite_metier": "NON_EVALUEE",
            "rapport_complet": False,
        }

    if _taille(page(0)) > budget_caracteres:
        raise ValueError(
            f"REJ-RAPPORT-BORNE : squelette et manques au-delà de la borne de {budget_caracteres} caractères"
        )
    nombre = 0
    while depart + nombre < total and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if depart < total and nombre == 0:
        raise ValueError(
            f"REJ-RAPPORT-BORNE : l'alerte {_nom(retenues[depart]['evenement_id'])} dépasse à elle seule la borne "
            f"de {budget_caracteres} caractères, aucune troncature autorisée"
        )
    return page(nombre)
