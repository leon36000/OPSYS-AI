"""Outil de l'interpréteur « et si… » M9.8 : proposer des chocs du catalogue à partir d'une question en français.

Adaptateur seul (la logique est dans ``question_scenario``). Lecture pure : aucune capture lue, rien d'écrit, aucun
calcul de scénario. Les propositions complètes s'évaluent ensuite par ``m9_evaluer_scenarios`` avec des bases citées.
Admin strict ; la question est une donnée bornée, jamais une instruction.
"""

from __future__ import annotations

from typing import Any

from opsys.outils import Autonomie, Niveau, Outil

from . import question_scenario
from .outils_tissu import borner, exiger_admin_strict


def construire_outils(*, budget_sortie: int) -> tuple[Outil, ...]:
    def interpreter(question: str) -> dict[str, Any]:
        exiger_admin_strict()
        return borner({"accepte": True, **question_scenario.interpreter(question)}, budget_sortie)

    return (
        Outil(
            nom="m9_interpreter_question_scenario",
            description=(
                "Interprète une question « et si… » en propositions de chocs du catalogue de scénarios (paramètres "
                "dits seulement ; un paramètre non dit est à fournir, jamais deviné) ; n'évalue rien : l'évaluation "
                "passe par m9_evaluer_scenarios avec des bases citées."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "minLength": 1, "maxLength": question_scenario.MAX_QUESTION}
                },
                "required": ["question"],
                "additionalProperties": False,
            },
            fonction=interpreter,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
