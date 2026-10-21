"""Bilan historique borné des suivis internes M9 sur une période explicite (M9.6, bilan hebdomadaire).

Aucune horloge, identité, base ni exécution d'action ici : la période ``[debut, fin)`` est fournie par
l'appelant, avec fuseaux, et comparée en instants ; aucune borne de semaine n'est devinée. L'état rendu
est celui JUSTE AVANT ``fin`` : une ouverture à ``fin`` ou après est exclue ; une clôture à ``fin`` ou
après n'est pas encore advenue, le suivi reste ``ouvert_fin`` et cette clôture n'est pas rendue, même si
elle existe aujourd'hui. Seules des décisions humaines reçues sont relues : ni exécution d'une action
terrain, ni cause, amélioration, couverture ou fraîcheur n'en sont déduites.

Lignes retenues : ouverture dans la période, OU clôture dans la période, OU suivi ouvert juste avant
``fin``. ORDRE, stable et total : instant d'ouverture (``decision.decide_le`` du plan) croissant, puis
``suivi_id`` croissant.

Tous les plans et toutes les clôtures, y compris hors période, sont validés AVANT le filtre : schéma,
statut, champs, preuve, décision signée, liaisons d'identifiants, empreinte exacte du plan et
chronologie. Une corruption refuse la lecture au lieu d'être masquée. ``vue`` et pagination suivent
`echeancier_suivis` : empreinte des deux registres complets et des bornes ; une reprise ``depart > 0``
exige la vue courante.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from .echeancier_suivis import _EMPREINTE, _instant, _taille, _valider_clotures, _valider_plans
from .encodage import empreinte
from .suivi_decisions import preparer_cloture, preparer_source, texte

__all__ = ["ORDRE_BILAN", "bilan_suivis_decision"]

ORDRE_BILAN = "instant d'ouverture croissant (fuseaux compris), puis suivi_id croissant"
_TYPE = "BILAN_SUIVIS_DECISION"
_DRAPEAUX = {"ouverts_periode": "ouvert_dans_periode", "clotures_periode": "cloture_dans_periode",
             "ouverts_fin": "ouvert_fin"}


def _decision(porteur: dict[str, Any], quoi: str) -> tuple[str, datetime]:
    """Décision humaine signée : demande, décideur, rôle non vides et instant avec fuseau explicite."""
    decision = porteur.get("decision")
    if not isinstance(decision, dict):
        raise ValueError(f"REJ-BILAN-DECISION : décision du {quoi} requise")
    demande_id = texte(decision.get("demande_id"), "demande_id", 1024)
    texte(decision.get("decide_par"), "decide_par", 1024)
    texte(decision.get("decide_role"), "decide_role", 1024)
    return demande_id, _instant(decision.get("decide_le"), "decide_le")


def _valider(
    suivis: list[dict[str, Any]], clotures: list[dict[str, Any]],
) -> tuple[dict[str, datetime], dict[str, tuple[dict[str, Any], datetime]]]:
    """Tous les plans et toutes les clôtures, hors période compris : instants d'ouverture et clôtures liées."""
    _valider_clotures(clotures, _valider_plans(suivis))
    plans = {plan["suivi_id"]: plan for plan in suivis}
    ouvertures: dict[str, datetime] = {}
    demandes: set[str] = set()
    for suivi_id, plan in plans.items():
        demande_id, ouvertures[suivi_id] = _decision(plan, "plan")
        if demande_id != suivi_id:
            raise ValueError("REJ-BILAN-PLAN : la demande d'ouverture doit être le suivi lui-même")
        source = plan["source"]
        if preparer_source([source.get("alerte")], source.get("evenement_id")) != source:
            raise ValueError("REJ-BILAN-PLAN : preuve source du plan incohérente avec son alerte reçue")
        demandes.add(demande_id)
    fermetures: dict[str, tuple[dict[str, Any], datetime]] = {}
    for cloture in clotures:
        suivi_id = cloture["suivi_id"]
        if suivi_id in fermetures:
            raise ValueError("REJ-SUIVI-CLOTURE-AMBIGUE : plusieurs clôtures pour ce suivi, aucune n'est choisie")
        demande_id, instant = _decision(cloture, "clôture")
        if demande_id in demandes:
            raise ValueError("REJ-BILAN-CLOTURE : demande de clôture déjà portée par une autre décision")
        demandes.add(demande_id)
        texte(cloture.get("bilan"), "bilan", 2000)
        preuve = cloture.get("preuve")
        if not isinstance(preuve, dict):
            raise ValueError("REJ-BILAN-CLOTURE : preuve reçue de la clôture requise")
        # Même dérivation qu'à la clôture : empreinte exacte du plan, preuve de même métrique/chantier/définition.
        attendu = preparer_cloture(plans[suivi_id], None, [preuve.get("alerte")], preuve.get("evenement_id"))
        if attendu != {"empreinte_suivi": cloture.get("empreinte_suivi"), "preuve": preuve}:
            raise ValueError("REJ-SUIVI-CLOTURE-INCOHERENTE : la clôture ne correspond plus au plan conservé")
        if instant < ouvertures[suivi_id]:
            raise ValueError("REJ-BILAN-CHRONOLOGIE : clôture décidée avant l'ouverture du suivi")
        fermetures[suivi_id] = (cloture, instant)
    return ouvertures, fermetures


def bilan_suivis_decision(
    suivis: list[dict[str, Any]],
    clotures: list[dict[str, Any]],
    debut: str,
    fin: str,
    depart: int = 0,
    vue_attendue: str | None = None,
    *,
    budget_caracteres: int,
) -> dict[str, Any]:
    """Une page du bilan de la période ``[debut, fin)``, dans l'ordre de ``ORDRE_BILAN``, à partir de
    ``depart``, autant de lignes complètes que ``budget_caracteres`` en laisse tenir (taille mesurée).

    Chaque ligne porte le plan d'origine complet, son empreinte, ``ouvert_dans_periode``,
    ``cloture_dans_periode``, ``ouvert_fin`` et, seulement si elle est décidée avant ``fin``, la clôture
    d'origine exacte. ``compteurs`` porte les totaux de toutes les lignes, identiques à chaque page.
    ``depart == total`` rend une page vide terminale, elle aussi sous la borne. Les entrées ne sont
    jamais modifiées."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        raise ValueError(f"REJ-BILAN-ARGUMENT : depart entier supérieur ou égal à 0 attendu, reçu {depart!r}")
    if isinstance(budget_caracteres, bool) or not isinstance(budget_caracteres, int) or budget_caracteres < 1:
        raise ValueError("REJ-BILAN-ARGUMENT : budget_caracteres entier strictement positif attendu")
    if vue_attendue is not None and (not isinstance(vue_attendue, str) or not _EMPREINTE.fullmatch(vue_attendue)):
        raise ValueError("REJ-BILAN-ARGUMENT : vue_attendue empreinte hexadécimale de 64 caractères attendue")
    if depart > 0 and vue_attendue is None:
        raise ValueError("REJ-BILAN-VUE : vue_attendue de la page précédente requise pour depart > 0")
    borne_debut = _instant(debut, "debut")
    borne_fin = _instant(fin, "fin")
    if not borne_debut < borne_fin:
        raise ValueError("REJ-BILAN-PERIODE : debut strictement antérieur à fin requis (instants comparés)")
    if not isinstance(suivis, (list, tuple)) or not isinstance(clotures, (list, tuple)):
        raise ValueError("REJ-BILAN-ARGUMENT : listes de plans et de clôtures attendues")

    ouvertures, fermetures = _valider(suivis, clotures)
    vue = empreinte({"type": _TYPE, "debut": debut, "fin": fin, "suivis": list(suivis), "clotures": list(clotures)})
    if vue_attendue is not None and vue_attendue != vue:
        raise ValueError("REJ-BILAN-VUE-PERIMEE : plans, clôtures ou bornes ont changé ; reprendre à depart=0")

    lignes: list[dict[str, Any]] = []
    for plan in sorted(suivis, key=lambda p: (ouvertures[p["suivi_id"]], p["suivi_id"])):
        ouverture = ouvertures[plan["suivi_id"]]
        if ouverture >= borne_fin:
            continue
        cloture, instant = fermetures.get(plan["suivi_id"], (None, None))
        # Une clôture à fin ou après n'est pas encore advenue juste avant fin : jamais rendue ici.
        close_avant_fin = cloture is not None and instant < borne_fin
        ligne = {
            "suivi": copy.deepcopy(plan),
            "empreinte_suivi": empreinte(plan),
            "ouvert_dans_periode": borne_debut <= ouverture,
            "cloture_dans_periode": close_avant_fin and borne_debut <= instant,
            "ouvert_fin": not close_avant_fin,
        }
        if not any(ligne[drapeau] for drapeau in _DRAPEAUX.values()):
            continue
        if close_avant_fin:
            ligne["cloture"] = copy.deepcopy(cloture)
        lignes.append(ligne)
    total = len(lignes)
    if depart > total:
        raise ValueError(f"REJ-BILAN-ARGUMENT : depart {depart} au-delà de la fin ({total} ligne(s))")
    compteurs = {compteur: sum(ligne[drapeau] for ligne in lignes) for compteur, drapeau in _DRAPEAUX.items()}

    def page(nombre: int) -> dict[str, Any]:
        dernier = depart + nombre
        reste = total - dernier
        return {
            "type": _TYPE,
            "debut": debut,
            "fin": fin,
            "vue": vue,
            "compteurs": dict(compteurs),
            "total": total,
            "depart": depart,
            "affichees": nombre,
            "reste": reste,
            "prochain_depart": dernier if reste else None,
            "suivis": lignes[depart:dernier],
        }

    nombre = 0
    while depart + nombre < total and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if depart < total and nombre == 0:
        raise ValueError(
            f"REJ-BILAN-BORNE : le suivi {lignes[depart]['suivi']['suivi_id']} dépasse à lui seul la borne de "
            f"{budget_caracteres} caractères, aucune troncature autorisée"
        )
    resultat = page(nombre)
    if _taille(resultat) > budget_caracteres:
        raise ValueError(f"REJ-BILAN-BORNE : page vide au-delà de la borne de {budget_caracteres} caractères")
    return resultat
