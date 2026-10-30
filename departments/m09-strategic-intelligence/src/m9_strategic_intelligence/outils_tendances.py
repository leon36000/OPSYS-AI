"""Outil M9.9 : tendance extrapolée d'un fait numérique capturé, calculée par le code, en lecture seule.

La projection vient de ``tendances.projeter`` (pur, déterministe, ``Decimal``) sur la chaîne vérifiée des captures
M9.1. Elle est étiquetée ``tendance_extrapolee`` : ce n'est la prévision d'aucun propriétaire et elle ne remplace jamais
la trésorerie détaillée de M5. Une lecture absente du catalogue, une chaîne invalide ou une sortie au-delà du budget
sont refusées, jamais tronquées.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import catalogue_producteurs, tendances
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def construire_outils(*, budget_sortie: int, captures_cible: Any = None) -> tuple[Outil, ...]:
    def projeter_tendance(
        lecture_id: str,
        chemin: str,
        connaissance: str,
        horizons: list[str] | None = None,
        saison_jours: int | None = None,
        arguments: dict[str, Any] | None = None,
        decimales: int = 2,
    ) -> dict[str, Any]:
        exiger_admin_strict()
        if lecture_id not in catalogue_producteurs.PAR_ID:
            raise _refus("REJ-TENDANCE-LECTURE", "lecture absente du catalogue des producteurs")
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        resultat = tendances.projeter(
            chaine,
            lecture_id=lecture_id,
            chemin=chemin,
            connaissance=connaissance,
            horizons=horizons if horizons is not None else ["7j", "30j"],
            saison_jours=saison_jours,
            arguments=arguments,
            decimales=decimales,
        )
        return borner({"accepte": True, **resultat}, budget_sortie)

    return (
        Outil(
            nom="m9_projeter_tendance",
            description=(
                "Extrapole, par le code (moyenne mobile, droite des moindres carrés, saisonnier naïf), un fait "
                "numérique capturé chez un producteur, avec chaque point cité et un intervalle approximatif. "
                "Tendance extrapolée, pas une prévision de propriétaire ; ne remplace jamais la trésorerie de M5. "
                "Refuse sous 6 points ou au-delà de la durée d'historique."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "lecture_id": {"type": "string", "description": "Lecture du catalogue des producteurs."},
                    "chemin": {
                        "type": "string",
                        "description": "Chemin d'UN fait numérique, ex. resultat.resultat.total (sans joker).",
                    },
                    "connaissance": _INSTANT,
                    "horizons": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(tendances.HORIZONS)},
                        "minItems": 1,
                        "maxItems": len(tendances.HORIZONS),
                        "uniqueItems": True,
                    },
                    "saison_jours": {"type": "integer", "minimum": 2, "maximum": 366},
                    "arguments": {
                        "type": "object",
                        "description": "Filtres de la lecture (hors argument de référence) qui définissent la série.",
                    },
                    "decimales": {"type": "integer", "minimum": 0, "maximum": 6},
                },
                "required": ["lecture_id", "chemin", "connaissance"],
                "additionalProperties": False,
            },
            fonction=projeter_tendance,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
