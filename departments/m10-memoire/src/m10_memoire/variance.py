"""Mémorisation d'un événement ``m6.variance_chantier`` au registre Événements (PLAN T3.3).

Compare les besoins prévus (M3/M6) au réel déclaré par le terrain pour un chantier — catalogue
socle stable, ``src/opsys/evenements/catalogue/m6.variance_chantier.json``. MÊME registre et MÊME
``type_entree`` que le Work Completion Trigger de M4 (``evenement_memorise``) : les deux sont des
événements opérationnels reçus du bus (ADR-0009 §3), distingués à la lecture par
``classification.py``. Contrairement au WCT, cet événement n'a pas de contrat M10 séparé à
vérifier : le catalogue socle (schéma JSON, ``additionalProperties: false``, neuf champs tous
requis même null) est la seule source de vérité — la charge reçue est mémorisée TELLE QUELLE, sans
re-validation métier ici.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

from typing import Any

_TYPE_ENTREE_EVENEMENT = "evenement_memorise"


def memoriser_variance(
    variance_recue: dict[str, Any], registre_cible: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Mémorise la variance reçue au registre donné ; rend ``(maillon, None)``.

    Patron ``(resultat, verdict)`` conservé pour cohérence avec ``wct.memoriser_wct``, même si ce
    module n'a aujourd'hui aucun chemin de refus (charge déjà validée par le catalogue socle avant
    livraison — voir docstring du module).
    """
    entree = {
        **variance_recue,
        "type_entree": _TYPE_ENTREE_EVENEMENT,
        "horodatage": variance_recue["horodatage_completion"],
    }
    ligne_id = registre_cible.ajouter(entree)

    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon, None

    raise RuntimeError("Maillon ajouté introuvable.")
