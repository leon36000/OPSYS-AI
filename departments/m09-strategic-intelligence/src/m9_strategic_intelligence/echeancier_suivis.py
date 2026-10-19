"""Projection pure bornée des suivis internes encore ouverts (M9.16, échéancier).

Aucune horloge, identité, base ni exécution d'action ici : la référence horaire est fournie
explicitement par l'appelant, avec fuseau. Un suivi listé reste un plan approuvé : ni l'exécution
d'une action terrain, ni une cause, une fraîcheur ou une couverture n'en sont déduites.

ORDRE, stable et total : ``echeance`` croissante comparée en instant (fuseaux compris, jamais
alphabétiquement), puis ``suivi_id`` croissant. Tous les plans et toutes les clôtures sont validés
AVANT d'écarter les suivis clos : un doublon, une clôture orpheline, ambiguë ou incohérente refuse
la lecture au lieu de masquer la corruption.

La ``vue`` est l'empreinte de tous les plans, de toutes les clôtures et de la référence : une reprise
``depart > 0`` exige la vue courante, et tout changement l'invalide, même à total égal. C'est une
empreinte d'état, pas une continuité transactionnelle entre deux requêtes.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from typing import Any

from .encodage import empreinte
from .suivi_decisions import STATUT_CLOTURE, projeter, texte, trouver_cloture

__all__ = ["ORDRE_SUIVIS", "lister_suivis_decision"]

ORDRE_SUIVIS = "echeance croissante (instant, fuseaux compris), puis suivi_id croissant"
_EMPREINTE = re.compile(r"[0-9a-f]{64}")


def _taille(resultat: dict[str, Any]) -> int:
    """Taille sérialisée mesurée comme `suivi_decisions.borner`, jamais estimée."""
    return len(json.dumps(resultat, ensure_ascii=False, allow_nan=False))


def _instant(valeur: Any, champ: str) -> datetime:
    """Instant ISO avec fuseau explicite ; date seule, heure naïve ou texte illisible : refus."""
    texte(valeur, champ, 64)
    try:
        instant = datetime.fromisoformat(valeur)
    except ValueError as exc:
        raise ValueError(f"REJ-ECHEANCIER-INSTANT : {champ} ISO avec fuseau explicite requis") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(f"REJ-ECHEANCIER-INSTANT : {champ} ISO avec fuseau explicite requis")
    return instant


def _valider_plans(suivis: list[dict[str, Any]]) -> dict[str, datetime]:
    """Tous les plans, clos ou non : schéma, statut, identifiant unique, échéance lisible."""
    instants: dict[str, datetime] = {}
    for plan in suivis:
        if (
            not isinstance(plan, dict)
            or type(plan.get("schema")) is not int
            or plan["schema"] != 1
            or plan.get("statut") != "planifiee"
        ):
            raise ValueError("REJ-ECHEANCIER-PLAN : plan de schéma 1 au statut planifiee requis")
        suivi_id = texte(plan.get("suivi_id"), "suivi_id", 1024)
        if suivi_id in instants:
            raise ValueError("REJ-ECHEANCIER-PLAN-DOUBLE : plusieurs plans pour ce suivi, aucun n'est choisi")
        texte(plan.get("action"), "action", 1000)
        texte(plan.get("responsable_id"), "responsable_id", 64)
        if not isinstance(plan.get("source"), dict) or not isinstance(plan.get("decision"), dict):
            raise ValueError("REJ-ECHEANCIER-PLAN : preuve source et décision du plan requises")
        instants[suivi_id] = _instant(plan.get("echeance"), "echeance")
    return instants


def _valider_clotures(clotures: list[dict[str, Any]], instants: dict[str, datetime]) -> None:
    """Chaque clôture : schéma, statut de revue humaine, plan existant. Doublon et empreinte : projeter."""
    for cloture in clotures:
        if (
            not isinstance(cloture, dict)
            or type(cloture.get("schema")) is not int
            or cloture["schema"] != 1
            or cloture.get("statut") != STATUT_CLOTURE
        ):
            raise ValueError("REJ-ECHEANCIER-CLOTURE : clôture de schéma 1 par revue humaine requise")
        suivi_id = cloture.get("suivi_id")
        if not isinstance(suivi_id, str) or suivi_id not in instants:
            raise ValueError("REJ-ECHEANCIER-CLOTURE-ORPHELINE : clôture sans plan conservé")


def lister_suivis_decision(
    suivis: list[dict[str, Any]],
    clotures: list[dict[str, Any]],
    horodatage_reference: str,
    depart: int = 0,
    vue_attendue: str | None = None,
    *,
    budget_caracteres: int,
) -> dict[str, Any]:
    """Une page des suivis encore ouverts, dans l'ordre de ``ORDRE_SUIVIS``, à partir de ``depart``,
    autant de lignes complètes que ``budget_caracteres`` en laisse tenir (taille sérialisée mesurée).

    Chaque ligne porte le plan d'origine complet, son empreinte et ``statut_echeance`` : ``EN_RETARD``
    (échéance avant la référence), ``A_ECHEANCE`` (même instant) ou ``A_VENIR``. ``depart == total``
    rend une page vide terminale, elle aussi sous la borne. Les entrées ne sont jamais modifiées."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        raise ValueError(f"REJ-ECHEANCIER-ARGUMENT : depart entier supérieur ou égal à 0 attendu, reçu {depart!r}")
    if isinstance(budget_caracteres, bool) or not isinstance(budget_caracteres, int) or budget_caracteres < 1:
        raise ValueError("REJ-ECHEANCIER-ARGUMENT : budget_caracteres entier strictement positif attendu")
    if vue_attendue is not None and (not isinstance(vue_attendue, str) or not _EMPREINTE.fullmatch(vue_attendue)):
        raise ValueError("REJ-ECHEANCIER-ARGUMENT : vue_attendue empreinte hexadécimale de 64 caractères attendue")
    if depart > 0 and vue_attendue is None:
        raise ValueError("REJ-ECHEANCIER-VUE : vue_attendue de la page précédente requise pour depart > 0")
    reference = _instant(horodatage_reference, "horodatage_reference")
    if not isinstance(suivis, (list, tuple)) or not isinstance(clotures, (list, tuple)):
        raise ValueError("REJ-ECHEANCIER-ARGUMENT : listes de plans et de clôtures attendues")

    instants = _valider_plans(suivis)
    _valider_clotures(clotures, instants)
    ouverts = [plan for plan in suivis if "cloture" not in projeter(plan, trouver_cloture(clotures, plan["suivi_id"]))]
    vue = empreinte(
        {
            "type": "SUIVIS_DECISION_OUVERTS",
            "horodatage_reference": horodatage_reference,
            "suivis": list(suivis),
            "clotures": list(clotures),
        }
    )
    if vue_attendue is not None and vue_attendue != vue:
        raise ValueError("REJ-ECHEANCIER-VUE-PERIMEE : plans, clôtures ou référence ont changé ; reprendre à depart=0")

    ouverts.sort(key=lambda plan: (instants[plan["suivi_id"]], plan["suivi_id"]))
    total = len(ouverts)
    if depart > total:
        raise ValueError(f"REJ-ECHEANCIER-ARGUMENT : depart {depart} au-delà de la fin ({total} suivi(s) ouvert(s))")

    def statut(plan: dict[str, Any]) -> str:
        instant = instants[plan["suivi_id"]]
        return "EN_RETARD" if instant < reference else "A_ECHEANCE" if instant == reference else "A_VENIR"

    lignes = [
        {"suivi": copy.deepcopy(plan), "empreinte_suivi": empreinte(plan), "statut_echeance": statut(plan)}
        for plan in ouverts
    ]

    def page(nombre: int) -> dict[str, Any]:
        fin = depart + nombre
        reste = total - fin
        return {
            "type": "SUIVIS_DECISION_OUVERTS",
            "horodatage_reference": horodatage_reference,
            "vue": vue,
            "total": total,
            "depart": depart,
            "affichees": nombre,
            "reste": reste,
            "prochain_depart": fin if reste else None,
            "suivis": lignes[depart:fin],
        }

    nombre = 0
    while depart + nombre < total and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if depart < total and nombre == 0:
        raise ValueError(
            f"REJ-ECHEANCIER-BORNE : le suivi {ouverts[depart]['suivi_id']} dépasse à lui seul la borne de "
            f"{budget_caracteres} caractères, aucune troncature autorisée"
        )
    resultat = page(nombre)
    if _taille(resultat) > budget_caracteres:
        raise ValueError(f"REJ-ECHEANCIER-BORNE : page vide au-delà de la borne de {budget_caracteres} caractères")
    return resultat
