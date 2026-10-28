"""Outil M9.9 : prévisions consolidées des propriétaires, versions et âge, en lecture seule."""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import previsions
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def construire_outils(*, budget_sortie: int, captures_cible: Any = None) -> tuple[Outil, ...]:
    def consolidees(connaissance: str, perime_apres_jours: int | None = None, max_versions: int = 3) -> dict[str, Any]:
        exiger_admin_strict()
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise ValueError(f"REJ-CAPTURE-CHAINE-INVALIDE : registre des captures invalide ({raison})")
        resultat = previsions.consolider(
            chaine, connaissance=connaissance, perime_apres_jours=perime_apres_jours, max_versions=max_versions
        )
        return borner({"accepte": True, **resultat}, budget_sortie)

    return (
        Outil(
            nom="m9_previsions_consolidees",
            description=(
                "Présente les prévisions publiées par leurs propriétaires (trésorerie M5) avec versions, âge, réserves "
                "et faits citables ; leads, capacité et matériaux restent « aucune prévision produite ». M9 ne prévoit "
                "rien et ne calcule aucun montant."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "connaissance": _INSTANT,
                    "perime_apres_jours": {"type": "integer", "minimum": 0, "maximum": 3650},
                    "max_versions": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["connaissance"],
                "additionalProperties": False,
            },
            fonction=consolidees,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
