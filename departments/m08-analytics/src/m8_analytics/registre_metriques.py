"""Registre DURABLE des définitions de métriques que M8 surveille activement (T3.1,
docs/departements/M8-audit.md §2 : « grain et permissions absents du schéma DefinitionMetrique »
— ce registre porte deux des champs opérationnels que l'audit signale comme manquants,
``departement_proprietaire`` et ``fraicheur_attendue_jours``, plus les ``regles_qualite``).

Distinct de deux autres registres du paquet, à ne pas confondre :
- ``dictionnaire.py`` compile À LA VOLÉE les ``metrics/*.yaml`` publiés par les modules — c'est ce
  qu'un module DÉCLARE pouvoir fournir, recompilé à chaque appel, jamais persisté.
- ``registre.py`` (``RegistreSnapshots``) stocke les VALEURS mesurées au fil du temps.
- CE module stocke ce que M8 a choisi de SURVEILLER : à qui appartient une métrique, quelle
  fraîcheur en attendre, quelles règles de qualité lui appliquer — la configuration de la
  surveillance, pas les faits eux-mêmes.

Module PUR (ADR-0009) : aucun import d'``opsys``. ``maillons_cible`` est injecté par l'appelant
(liste Python en mémoire pour les tests, ``opsys.stockage.maillons(...)`` en production — adossé
par ``outils.py``, seul, même patron que ``registre.RegistreSnapshots``) : ce module ignore où
vivent ses maillons.

Registre APPEND-ONLY et VERSIONNÉ (jamais un UPDATE en place, même limite structurelle que
``RegistreSnapshots``) : ``enregistrer_definition`` ajoute une nouvelle version quand le contenu
change, et ne fait RIEN quand la dernière version connue pour ce ``metric_id`` est déjà identique
— c'est ce qui rend l'opération idempotente (rejouer le même enregistrement, par exemple à
chaque déploiement d'un module, ne fait jamais grossir le registre). ``resoudre`` renvoie
toujours la DERNIÈRE version connue ; l'historique complet reste disponible via
``maillons_cible`` pour qui veut le lire directement — un progrès mesuré sur le constat de
l'audit (« version = un hash de contenu, jamais un historique de versions »).

``lister`` (T3.1-suite) offre un troisième mode de lecture, compact et paginé : une ligne par
``metric_id`` (jamais par version), pour un outil T0 qui ne doit jamais renvoyer l'historique
complet d'un coup.
"""

from __future__ import annotations

import copy
from typing import Any

from . import contrats, dictionnaire

# Identifiants de département connus (AGENTS.md « Arborescence », docs/architecture/DEPARTEMENTS.md)
# — allow-list technique (préfixée `_`, pas un énuméré de domaine à classer, même raison que
# dictionnaire.py::_DEVISES_AUTORISEES) : un `departement_proprietaire` hors de cette liste est
# presque toujours une faute de frappe, jamais une valeur à deviner ou à accepter en silence.
_DEPARTEMENTS_CONNUS = frozenset({
    "m01-front-office",
    "m02-revenue-crm",
    "m03-estimation",
    "m04-field-ops",
    "m05-financecore",
    "m06-material-control",
    "m07-marketing",
    "m08-analytics",
    "m09-strategic-intelligence",
    "m10-memoire",
})


def _nombre_valide(valeur: Any) -> bool:
    return not isinstance(valeur, bool) and isinstance(valeur, (int, float))


def _regles_qualite_valides(regles: Any) -> bool:
    if not isinstance(regles, dict) or set(regles.keys()) != contrats.CHAMPS_REGLES_QUALITE:
        return False
    plage_min, plage_max = regles["plage_min"], regles["plage_max"]
    if any(borne is not None and not _nombre_valide(borne) for borne in (plage_min, plage_max)):
        return False
    return not (plage_min is not None and plage_max is not None and plage_min > plage_max)


def _verdict_definition_invalide(definition: Any) -> str | None:
    """``None`` si ``definition`` respecte le contrat et peut être enregistrée, un verdict nommé
    sinon — jamais une correction silencieuse d'un champ manquant ou mal typé."""
    if not isinstance(definition, dict) or set(definition.keys()) != contrats.CHAMPS_DEFINITION_REGISTRE:
        return "REJ-DEFINITION-STRUCTURE-INVALIDE"

    metric_id = definition["metric_id"]
    if not isinstance(metric_id, str) or not metric_id:
        return "REJ-DEFINITION-STRUCTURE-INVALIDE"

    source = definition["source"]
    if not isinstance(source, str) or not source:
        return "REJ-DEFINITION-STRUCTURE-INVALIDE"

    departement = definition["departement_proprietaire"]
    if departement not in _DEPARTEMENTS_CONNUS:
        return f"REJ-DEFINITION-DEPARTEMENT-INCONNU:{departement!r}"

    unite = definition["unite"]
    if not isinstance(unite, str) or not unite:
        return "REJ-DEFINITION-STRUCTURE-INVALIDE"
    devise_refusee = dictionnaire.devise_non_autorisee(unite)
    if devise_refusee is not None:
        return f"REJ-DEFINITION-DEVISE-NON-AUTORISEE:{devise_refusee}"

    fraicheur_attendue = definition["fraicheur_attendue_jours"]
    if not _nombre_valide(fraicheur_attendue) or fraicheur_attendue <= 0:
        return "REJ-DEFINITION-FRAICHEUR-ATTENDUE-INVALIDE"

    if not _regles_qualite_valides(definition["regles_qualite"]):
        return "REJ-DEFINITION-REGLES-QUALITE-INVALIDES"

    return None


def enregistrer_definition(definition: dict[str, Any], maillons_cible: Any) -> dict[str, Any]:
    """Enregistre ``definition`` (``contrats.CHAMPS_DEFINITION_REGISTRE``) si elle est valide.

    Idempotent : si la DERNIÈRE version connue pour ce ``metric_id`` est déjà identique,
    n'ajoute rien (``deja_a_jour=True``) — rejouer le même enregistrement, à répétition ou
    entrelacé avec d'autres métriques, ne fait jamais grossir le registre. Une définition dont
    seul le contenu a changé (ex. ``fraicheur_attendue_jours`` révisée) ajoute une NOUVELLE
    version plutôt que d'écraser l'ancienne (append-only).
    """
    verdict = _verdict_definition_invalide(definition)
    if verdict is not None:
        return {"enregistree": False, "deja_a_jour": False, "verdict": verdict}

    normalisee = {cle: definition[cle] for cle in contrats.CHAMPS_DEFINITION_REGISTRE}
    normalisee["regles_qualite"] = dict(normalisee["regles_qualite"])

    for maillon in reversed(list(maillons_cible)):
        if maillon["metric_id"] != normalisee["metric_id"]:
            continue
        if maillon == normalisee:
            return {"enregistree": True, "deja_a_jour": True, "verdict": None}
        break  # dernière version connue différente : nouvelle version à ajouter, jamais un écrasement.

    maillons_cible.append(copy.deepcopy(normalisee))
    return {"enregistree": True, "deja_a_jour": False, "verdict": None}


def resoudre(metric_id: str, maillons_cible: Any) -> dict[str, Any] | None:
    """Dernière définition connue pour ``metric_id``, ou ``None`` si jamais enregistrée —
    fail-closed : jamais une définition par défaut inventée."""
    derniere: dict[str, Any] | None = None
    for maillon in maillons_cible:
        if maillon["metric_id"] == metric_id:
            derniere = maillon
    return copy.deepcopy(derniere) if derniere is not None else None


def lister(maillons_cible: Any, limite: int, curseur: int = 0) -> dict[str, Any]:
    """Listage compact et PAGINÉ du registre (T3.1-suite) : une ligne PAR ``metric_id`` connu —
    identifiant, département propriétaire, unité, fraîcheur attendue et numéro de version — la
    DERNIÈRE définition seulement, jamais une ligne par version et jamais l'historique complet
    (celui-ci reste disponible en lisant ``maillons_cible`` directement, sa seule source de
    vérité). ``version`` est le nombre d'enregistrements successifs vus pour ce ``metric_id``
    dans ``maillons_cible`` — dérivé de l'append-only lui-même, jamais un compteur stocké à part
    qui pourrait diverger.

    Ordre déterministe : trié par ``metric_id``. L'ordre d'arrivée dans ``maillons_cible`` dépend
    du backend (liste Python en mémoire ou ``opsys.stockage.MaillonsDurables``) et n'est donc pas
    une base de pagination stable d'un appel à l'autre.

    Fail-closed sur la pagination elle-même : ``limite`` doit être strictement positive (une
    page vide silencieuse masquerait un appel mal formé, jamais un défaut interne comme
    ``n_minimal`` dans ``xmr.py``) ; ``curseur`` doit être positif ou nul.
    """
    if limite <= 0:
        raise ValueError(f"limite doit être strictement positive, reçu {limite!r}")
    if curseur < 0:
        raise ValueError(f"curseur doit être positif ou nul, reçu {curseur!r}")

    dernieres_par_metrique: dict[str, dict[str, Any]] = {}
    nb_versions: dict[str, int] = {}
    for maillon in maillons_cible:
        metric_id = maillon["metric_id"]
        nb_versions[metric_id] = nb_versions.get(metric_id, 0) + 1
        dernieres_par_metrique[metric_id] = maillon

    lignes = [
        {
            "metric_id": metric_id,
            "departement_proprietaire": derniere["departement_proprietaire"],
            "unite": derniere["unite"],
            "fraicheur_attendue_jours": derniere["fraicheur_attendue_jours"],
            "version": nb_versions[metric_id],
        }
        for metric_id, derniere in sorted(dernieres_par_metrique.items())
    ]

    total = len(lignes)
    page = lignes[curseur:curseur + limite]
    fin_page = curseur + len(page)
    curseur_suivant = fin_page if fin_page < total else None

    return {
        "definitions": page,
        "total": total,
        "curseur": curseur,
        "curseur_suivant": curseur_suivant,
    }
