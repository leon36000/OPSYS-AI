"""Outil M9.4/M9.23 : réauditer les citations d'une session de conseil face aux captures les plus récentes.

Lecture seule. L'outil relit la session (registre chaîné vérifié) et les captures (registre chaîné vérifié) et dit, pour
chaque citation admise, si sa source a changé depuis ; il marque à revoir les inférences et la recommandation qui en
dépendent. Il ne corrige rien, ne décide rien et n'écrit rien.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import reaudit_conseil, sessions_conseil
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
REGISTRE_SESSIONS = "sessions_conseil"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def construire_outils(
    *, budget_sortie: int, captures_cible: Any = None, sessions_cible: Any = None
) -> tuple[Outil, ...]:
    def reauditer(session_id: str, connaissance: str) -> dict[str, Any]:
        exiger_admin_strict()
        captures = list(
            captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        )
        ok, raison = cs.valider_chaine(captures)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        evenements = list(
            sessions_cible if sessions_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_SESSIONS)
        )
        ok, raison = sessions_conseil.valider_chaine(evenements)
        if not ok:
            raise _refus("REJ-SESSION-CHAINE-INVALIDE", f"registre des sessions invalide ({raison})")
        resultat = reaudit_conseil.reauditer(evenements, captures, session_id=session_id, connaissance=connaissance)
        return borner({"accepte": True, **resultat}, budget_sortie)

    return (
        Outil(
            nom="m9_reauditer_conseil",
            description=(
                "Relit les citations admises d'une session de conseil et dit si leur source a changé depuis (capture "
                "plus récente de la même lecture, valeur différente ou fait absent) ; marque à revoir les inférences "
                "et la recommandation qui en dépendent. Ne corrige ni ne décide rien."
            ),
            parametres={
                "type": "object",
                "properties": {"session_id": {"type": "string", "maxLength": 64}, "connaissance": _INSTANT},
                "required": ["session_id", "connaissance"],
                "additionalProperties": False,
            },
            fonction=reauditer,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
