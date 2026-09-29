"""Audit « non-oubli » (PLAN T3.3, règle 1 de la fiche source — « toute tâche laisse une trace »).

Vérifie, PAR LE CODE, que chaque fait important ATTENDU a bien sa trace dans le registre
Événements, et que les deux registres n'ont subi aucune altération silencieuse (chaîne de hash,
``registre.valider_chaine`` — déjà éprouvé, jamais branché sur un audit avant PLAN T3.3). La liste
``identifiants_attendus`` est fournie par l'appelant : ce module est pur, il n'a aucune vue sur le
bus d'événements (``opsys.evenements``) pour deviner tout seul ce qui aurait dû arriver — deviner
serait l'inverse du fail-closed (AGENTS.md : « une donnée manquante produit un verdict qui dit quoi
demander, jamais une valeur par défaut inventée »).

Produit une liste COMPACTE des oublis ; ``total_attendus == 0`` est un rapport honnête (rien n'a
été vérifié), jamais un « tout va bien » implicite.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from . import classification

REJ_AUDIT_TYPE_INCONNU = "REJ-AUDIT-TYPE-INCONNU"
REJ_AUDIT_TRACE_ABSENTE = "REJ-AUDIT-TRACE-ABSENTE"

_TYPES_EVENEMENT_AUDITES = (classification.TYPE_WCT, classification.TYPE_VARIANCE, classification.TYPE_RENTABILITE)


def _presents(registre_evenements: Any) -> set[tuple[str, str]]:
    presents: set[tuple[str, str]] = set()
    for maillon in registre_evenements.lire():
        type_evenement = classification.type_evenement(maillon)
        if type_evenement is None:
            continue
        identifiant = classification.identifiant(maillon)
        if identifiant is not None:
            presents.add((type_evenement, identifiant))
    return presents


def auditer_non_oubli(
    identifiants_attendus: Iterable[Mapping[str, str]],
    registre_evenements: Any,
    registre_affaires: Any,
) -> dict[str, Any]:
    """``identifiants_attendus`` : séquence de ``{"type_evenement": ..., "identifiant": ...}``.

    Rend un rapport COMPLET (intégrité des deux chaînes + oublis), jamais une simple valeur
    booléenne : un « tout est beau » silencieux serait indiscernable d'un audit qui n'a rien
    vérifié.
    """
    identifiants_attendus = list(identifiants_attendus)
    chaine_evenements_intacte, _ = registre_evenements.valider_chaine()
    chaine_affaires_intacte, _ = registre_affaires.valider_chaine()
    presents = _presents(registre_evenements)

    oublis: list[dict[str, str]] = []
    for entree in identifiants_attendus:
        type_evenement = entree.get("type_evenement")
        identifiant = entree.get("identifiant")
        if type_evenement not in _TYPES_EVENEMENT_AUDITES:
            oublis.append(
                {"type_evenement": type_evenement, "identifiant": identifiant, "verdict": REJ_AUDIT_TYPE_INCONNU}
            )
        elif (type_evenement, identifiant) not in presents:
            oublis.append(
                {"type_evenement": type_evenement, "identifiant": identifiant, "verdict": REJ_AUDIT_TRACE_ABSENTE}
            )

    return {
        "chaine_evenements_intacte": chaine_evenements_intacte,
        "chaine_affaires_intacte": chaine_affaires_intacte,
        "total_attendus": len(identifiants_attendus),
        "nb_oublis": len(oublis),
        "oublis": oublis,
    }
