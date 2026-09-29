"""Lecture stratégique des preuves de M8 (PLAN T1.5-d ; DEFINITION-PRODUIT.md §6 « travaux
terminés » : « M9 — lecture stratégique via les preuves de M8 » ; flux des matériaux : « M8 mesure
la variance → M9 lit le risque »).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (``maintenant`` est fourni).
``assembler_lecture_strategique`` lit les alertes de MESURE que M8 a proposées sur le bus
(``m8.alerte_proposee`` : type ``MESURE-SEUIL-FRANCHI``, déjà reçues au registre d'alertes de M9)
et en tire un gabarit déterministe, sourcé, jamais une rédaction :

- chaque alerte devient une ``lecture`` qui CITE ses preuves : identifiant de la métrique de M8
  (``metric_id``), version de sa définition gouvernée, chantier, valeur, seuil, identifiant de
  l'événement d'origine — tels que M8 les a publiés, aucun chiffre recalculé ici (P2) ;
- ``preuves_m8`` liste les métriques citées ; ``par_metrique`` compte, par métrique, les alertes et
  les chantiers touchés (un décompte, jamais une note) ;
- l'action de chaque lecture est celle que M8 PROPOSE, relayée telle quelle : M9 n'en invente
  aucune, ne la décide pas et ne l'exécute pas. ``decision`` le dit : ``prise_par_m9`` est toujours
  faux, la décision revient au propriétaire (règle dure M9 : « aucune décision majeure sans
  validation de Nathan ») ;
- les rappels « seuil à configurer » sont des MANQUES, pas des risques : ils vont dans ``manques`` ;
- les alertes de qualité (donnée absente, périmée, hors plage) sont comptées, pas relues ici :
  ``m9_lire_alertes_m8`` les donne.

La réponse est bornée comme le briefing (``budget_caracteres``, la taille sérialisée que
``Capacites`` ne tronque pas) : ce qui ne tient pas est compté et se lit à partir d'un ``depart``.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

__all__ = ["assembler_lecture_strategique"]

# Copie locale des types d'alerte de M8 (catalogue m8.alerte_proposee) — jamais un import
# inter-département (DA-M9-04).
_TYPE_SEUIL_FRANCHI = "MESURE-SEUIL-FRANCHI"
_TYPE_SEUIL_A_CONFIGURER = "MESURE-SEUIL-A-CONFIGURER"
_CHAMPS_ALERTE = (
    "evenement_id", "metric_id", "type_alerte", "quoi", "a_qui", "pourquoi", "preuve", "source",
    "horodatage_reference",
)
_CHAMPS_PREUVE_FRANCHI = ("wct_id", "valeur", "unite", "sens", "seuil", "version_definition")
_DECIDEUR = "nathan_owner"


def _jour_de(horodatage: str) -> date:
    valeur = horodatage[:-1] + "+00:00" if horodatage.endswith("Z") else horodatage
    analyse = datetime.fromisoformat(valeur)
    if analyse.tzinfo is None:
        analyse = analyse.replace(tzinfo=UTC)
    return analyse.date()


def _taille(objet: Any) -> int:
    return len(json.dumps(objet, ensure_ascii=False))


def _valider_alerte(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"alertes_m8 : élément invalide, dict attendu, reçu {type(item).__name__}")
    manquants = [champ for champ in _CHAMPS_ALERTE if champ not in item]
    if manquants:
        raise ValueError(f"alertes_m8 : champ(s) manquant(s) {manquants} dans {item!r}")
    if item["type_alerte"] == _TYPE_SEUIL_FRANCHI:
        preuve = item["preuve"]
        absents = [c for c in _CHAMPS_PREUVE_FRANCHI if not isinstance(preuve, dict) or c not in preuve]
        if absents:
            raise ValueError(f"alertes_m8 : preuve incomplète pour {item['evenement_id']} : manque {absents}")
    return item


def _lecture(alerte: dict[str, Any]) -> dict[str, Any]:
    """Une alerte de mesure de M8, citée avec ses preuves ; jamais recalculée ni interprétée."""
    preuve = alerte["preuve"]
    return {
        "metric_id": alerte["metric_id"],
        "version_definition": preuve["version_definition"],
        "evenement_id": alerte["evenement_id"],
        "chantier": preuve["wct_id"],
        "valeur": preuve["valeur"],
        "unite": preuve["unite"],
        "sens": preuve["sens"],
        "seuil": preuve["seuil"],
        "regle": alerte["pourquoi"],
        "a_qui": alerte["a_qui"],
        "action_proposee_par_m8": alerte.get("action_proposee"),
        "source": alerte["source"],
        "statut_decision": "en_attente_du_proprietaire",
    }


def _par_metrique(alertes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groupes: dict[str, dict[str, Any]] = {}
    for alerte in alertes:
        groupe = groupes.setdefault(alerte["metric_id"], {"alertes": 0, "chantiers": set(), "a_qui": set()})
        groupe["alertes"] += 1
        groupe["chantiers"].add(alerte["preuve"]["wct_id"])
        groupe["a_qui"].add(alerte["a_qui"])
    return [
        {
            "metric_id": metric_id, "nb_alertes": g["alertes"], "nb_chantiers": len(g["chantiers"]),
            "a_qui": sorted(g["a_qui"]),
        }
        for metric_id, g in sorted(groupes.items())
    ]


def _resume(n_alertes: int, n_chantiers: int, metriques: list[str]) -> str:
    if n_alertes == 0:
        return "Aucune alerte de mesure de M8 dans la période : rien à lire."
    return (
        f"{n_alertes} alerte(s) de mesure proposée(s) par M8 sur {n_chantiers} chantier(s), "
        f"{len(metriques)} métrique(s) : {', '.join(metriques)}. "
        f"Aucune décision n'est prise par M9 : elle revient au propriétaire ({_DECIDEUR})."
    )


def assembler_lecture_strategique(
    maintenant: str,
    alertes_m8: list[dict[str, Any]],
    *,
    fenetre_alertes_jours: int = 0,
    depart: int = 0,
    budget_caracteres: int | None = None,
) -> dict[str, Any]:
    """Lecture stratégique des alertes de mesure de M8 reçues dans la fenêtre de jours qui se
    termine au jour de ``maintenant`` (0 : le jour même). Déterministe : lectures triées par
    métrique puis identifiant d'événement.

    ``depart`` (indice dans les lectures triées) et ``budget_caracteres`` bornent la page rendue ;
    ``affichage`` dit ce qui reste et où reprendre. Fail-closed : fenêtre ou ``depart`` invalides, un
    ``depart`` au-delà de la fin, une alerte sans ses champs, ou une seule lecture plus grosse que la
    borne (une page vide ne ferait pas progresser la lecture)."""
    fenetre_invalide = (
        isinstance(fenetre_alertes_jours, bool)
        or not isinstance(fenetre_alertes_jours, int)
        or fenetre_alertes_jours < 0
    )
    if fenetre_invalide:
        raise ValueError(f"fenetre_alertes_jours : entier positif ou nul attendu, reçu {fenetre_alertes_jours!r}")
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        raise ValueError(f"depart : entier positif ou nul attendu, reçu {depart!r}")
    if budget_caracteres is not None and (
        isinstance(budget_caracteres, bool) or not isinstance(budget_caracteres, int) or budget_caracteres < 1
    ):
        raise ValueError(f"budget_caracteres : entier strictement positif attendu, reçu {budget_caracteres!r}")

    jour = _jour_de(maintenant)
    debut = jour - timedelta(days=fenetre_alertes_jours)
    alertes = [_valider_alerte(item) for item in alertes_m8]
    alertes = [a for a in alertes if debut <= _jour_de(a["horodatage_reference"]) <= jour]

    franchies = sorted(
        (a for a in alertes if a["type_alerte"] == _TYPE_SEUIL_FRANCHI),
        key=lambda a: (a["metric_id"], a["evenement_id"]),
    )
    metriques_sans_seuil = sorted({a["metric_id"] for a in alertes if a["type_alerte"] == _TYPE_SEUIL_A_CONFIGURER})
    autres = [a for a in alertes if a["type_alerte"] not in (_TYPE_SEUIL_FRANCHI, _TYPE_SEUIL_A_CONFIGURER)]

    lectures = [_lecture(a) for a in franchies]
    total = len(lectures)
    if depart > total:
        raise ValueError(f"depart {depart} au-delà de la fin des lectures ({total})")
    preuves = sorted({a["metric_id"] for a in franchies})
    chantiers = {a["preuve"]["wct_id"] for a in franchies}

    def lecture_page(nombre: int, taille: int) -> dict[str, Any]:
        fin = depart + nombre
        reste = total - fin
        return {
            "type": "LECTURE_STRATEGIQUE_M8",
            "jour": jour.isoformat(),
            "periode": {"du": debut.isoformat(), "au": jour.isoformat()},
            "source": "m8.alerte_proposee (registre m09-strategic-intelligence/alertes_m8)",
            "resume": _resume(total, len(chantiers), preuves),
            "decision": {"prise_par_m9": False, "a_prendre_par": _DECIDEUR, "requise": total > 0},
            "preuves_m8": preuves,
            "par_metrique": _par_metrique(franchies),
            "manques": {
                "seuils_a_configurer": metriques_sans_seuil,
                "alertes_de_qualite_non_relues": len(autres),
            },
            "lectures": lectures[depart:fin],
            "affichage": {
                "borne_caracteres": budget_caracteres,
                "taille_caracteres": taille,
                "n_lectures": total,
                "depart": depart,
                "affichees": nombre,
                "reste": reste,
                "prochain_depart": fin if reste else None,
                "message": (
                    None if not reste else
                    (f"{reste} autres lectures non affichées : poursuivre avec depart={fin}." if reste > 1
                     else f"1 autre lecture non affichée : poursuivre avec depart={fin}.")
                ),
            },
        }

    nombre = total - depart
    if budget_caracteres is not None:
        nombre = 0
        while depart + nombre < total and _taille(lecture_page(nombre + 1, budget_caracteres)) <= budget_caracteres:
            nombre += 1
        if depart < total and nombre == 0:
            raise ValueError(f"une seule lecture dépasse la borne de {budget_caracteres} caractères")
        if _taille(lecture_page(nombre, budget_caracteres)) > budget_caracteres:
            raise ValueError(
                f"le squelette de la lecture dépasse à lui seul la borne de {budget_caracteres} caractères"
            )

    # `taille_caracteres` fait partie de ce qu'elle mesure : point fixe (seul le nombre de chiffres varie).
    taille = 0
    for _ in range(4):
        page = lecture_page(nombre, taille)
        mesuree = _taille(page)
        if mesuree == taille:
            return page
        taille = mesuree
    raise ValueError("la taille de la lecture ne se stabilise pas")
