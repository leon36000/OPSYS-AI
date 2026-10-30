"""Outil M9.10 : cadrer une question de décision (type, lectures, manques, validation humaine, brouillon d'approbation).

Lecture seule. L'outil classe la question, évalue la couverture des lectures de producteurs nécessaires et rend ce
que la personne doit déclarer ; il ne décide rien, ne soumet aucune approbation et n'écrit rien. Un registre de
captures altéré est refusé.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import decision_cadrage
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def construire_outils(*, budget_sortie: int, captures_cible: Any = None) -> tuple[Outil, ...]:
    def cadrer(
        question: str, reference: str, connaissance: str | None = None, perime_apres_jours: int | None = None
    ) -> dict[str, Any]:
        exiger_admin_strict()
        if cs.instant(reference) is None or (connaissance is not None and cs.instant(connaissance) is None):
            raise _refus("REJ-DECISION-INSTANT", "instants RFC 3339 à fuseau explicite requis")
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        cadrage = decision_cadrage.cadrer(
            question,
            chaine,
            reference=reference,
            connaissance=connaissance if connaissance is not None else reference,
            perime_apres_jours=perime_apres_jours,
        )
        return borner({"accepte": True, **cadrage}, budget_sortie)

    return (
        Outil(
            nom="m9_cadrer_decision",
            description=(
                "Cadre une question de direction (budget publicitaire, embauche, achat, prix, service, ville, dépenses,"
                " "
                "équipement, marketing, équipe) : type reconnu ou refus nommé, lectures nécessaires et couverture, "
                "manques, validation humaine applicable, critères proposés, scénarios et playbooks à examiner, "
                "brouillon "
                "d'approbation non soumis. Ne décide ni ne chiffre rien."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "maxLength": 500},
                    "reference": _INSTANT,
                    "connaissance": _INSTANT,
                    "perime_apres_jours": {"type": "integer", "minimum": 1, "maximum": 3650},
                },
                "required": ["question", "reference"],
                "additionalProperties": False,
            },
            fonction=cadrer,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
