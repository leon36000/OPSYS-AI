"""Lecture de la mesure par contenu, pour le propriétaire (PLAN T4.17-e ; DEFINITION-PRODUIT.md §7 M8.6 « tableau de
bord exécutif » et M8.7 « tableaux de bord par département » pour M7, §9.5 profil admin).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. ``outils.py``, seul point de contact avec le
socle, lit les registres puis appelle ``assembler``. Une réponse, quatre parties, chacune dit d'où vient son chiffre
:

1. ``metriques`` — les six métriques gouvernées de ``contenus.py`` (version de définition et propriétaire de
   chacune), avec le total sur tous les contenus et les décomptes qui l'expliquent (leads sans clé, clé inconnue,
   clé ambiguë...) ;
2. ``sources`` — les événements reçus et leur fraîcheur : M8 n'a pas d'horloge, il dit jusqu'où vont ses faits ;
3. ``contenus`` — une ligne par contenu exporté (clé, canal, chantier, comment il se mesure, leads, devis envoyés et
   acceptés), le plus utile d'abord, PAR PAGES (``affichage``) ;
4. ``manques`` — ce qui manque et de qui, une fois, dédoublonné : jamais un zéro à la place d'une donnée absente. Les
   impressions et les clics n'ont aucune source aujourd'hui : ils sont là comme manque, jamais comme nombre.

BORNE : la réponse d'un outil est tronquée par ``Capacites`` au-delà de la limite du socle. Les contenus tiennent page
par page, sous cette limite (``mesures_chantier.page_bornee``) : ce qui n'y tient pas est repris à ``prochain_depart``,
jamais perdu ni coupé au milieu. Fail-closed : un squelette qui dépasse à lui seul la borne est une erreur, jamais une
réponse coupée.
"""

from __future__ import annotations

from typing import Any

from . import contenus, mesures_chantier

_PORTEE = (
    "Tous les faits reçus par M8, sans fenêtre de période. Un contenu existe parce que M7 en a exporté le paquet ; un "
    "lead lui est attribué par la clé utm_content que M1 a reçue, égalité stricte. "
    "Impressions et clics : aucune source."
)


def _ajouter_manques(manques: list[dict[str, str]], nouveaux: list[dict[str, str]]) -> None:
    """Ajoute chaque manque UNE fois : « aucun contenu exporté reçu » vaut pour quatre métriques et ne se répète pas."""
    for manque in nouveaux:
        if manque not in manques:
            manques.append(dict(manque))


def _ligne_mesure(mesure: dict[str, Any], manques: list[dict[str, str]]) -> dict[str, Any]:
    ligne: dict[str, Any] = {
        "metric_id": mesure["metric_id"], "nom": mesure["nom"], "valeur": mesure["valeur"], "unite": mesure["unite"],
        "statut": mesure["statut"], "proprietaire": mesure["proprietaire"],
        "version_definition": mesure["version_definition"],
    }
    if mesure["statut"] == contenus.STATUT_NON_CALCULABLE:
        _ajouter_manques(manques, mesure["manque"])
        ligne["manque"] = list(dict.fromkeys(manque["champ"] for manque in mesure["manque"]))
    elif mesure["entrees"]:
        ligne["entrees"] = mesure["entrees"]
    return ligne


def assembler(situation: dict[str, Any], depart: int, budget_caracteres: int | None = None) -> dict[str, Any]:
    """La lecture des contenus : ``situation`` est celle de ``contenus.situation``. ``depart`` est le rang de la
    première ligne de contenu rendue (0 = début), ``budget_caracteres`` la borne de la réponse (``None`` : tout
    d'un coup). Lecture pure : rien n'est écrit, rien n'est publié."""
    manques: list[dict[str, str]] = []
    metriques = [_ligne_mesure(mesure, manques) for mesure in situation["mesures"]]
    lignes = situation["lignes"]

    def construire(page: list[dict[str, Any]], prochain_depart: int | None) -> dict[str, Any]:
        reste = len(lignes) - depart - len(page)
        message = f"{reste} contenu(s) non affiché(s) : poursuivre avec depart={prochain_depart}."
        return {
            "vue": "contenus",
            "portee": _PORTEE,
            "metriques": metriques,
            "sources": situation["sources"],
            "contenus": page,
            "affichage": {
                "n_contenus": len(lignes), "depart": depart, "affiches": len(page), "reste": reste,
                "prochain_depart": prochain_depart, "message": message if reste else None,
            },
            "manques": manques,
        }

    return mesures_chantier.page_bornee(lignes, depart, budget_caracteres, construire)


__all__ = ["assembler"]
