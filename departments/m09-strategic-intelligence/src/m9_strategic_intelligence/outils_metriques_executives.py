"""Outil M9.3 : les indicateurs exécutifs, leur définition officielle et leur lignage cité.

Lecture seule. L'outil relie les dix-sept indicateurs de direction à la définition que M8 ou leur propriétaire en
donne, dit lesquels n'ont AUCUNE définition officielle, et cite les faits des captures complètes sans rien calculer. Un
registre de captures altéré est refusé ; sans capture du registre M8, les métriques M8 sont nommées
``REGISTRE_NON_CAPTURE`` (jamais supposées enregistrées).
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import metriques_executives
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def construire_outils(*, budget_sortie: int, captures_cible: Any = None) -> tuple[Outil, ...]:
    def indicateurs(connaissance: str, depart: int = 0) -> dict[str, Any]:
        exiger_admin_strict()
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        if cs.instant(connaissance) is None:
            raise _refus("REJ-INDICATEURS-INSTANT", "instant RFC 3339 à fuseau explicite requis")
        resultat = metriques_executives.lignage(chaine, connaissance=connaissance)
        lignes = resultat["indicateurs"]
        if type(depart) is not int or not 0 <= depart <= len(lignes):
            raise _refus("REJ-INDICATEURS-DEPART", "départ entre 0 et le nombre d'indicateurs requis ; reprendre à 0")
        entete = {
            "accepte": True,
            "type": resultat["type"],
            "version": resultat["version"],
            "connaissance": connaissance,
            "registre_m8_capture": resultat["registre_m8_capture"],
            "par_statut": resultat["par_statut"],
            "total": len(lignes),
            "lignage_id": resultat["lignage_id"],
            "limites": resultat["limites"],
        }
        marge = budget_sortie - len(cs.canonique(entete)) - 400
        page: list[dict] = []
        for ligne in lignes[depart:]:
            if len(cs.canonique(page + [ligne])) > marge:
                break
            page.append(ligne)
        if lignes[depart:] and not page:
            raise _refus("REJ-TISSU-BORNE", "un indicateur dépasse la borne de sortie")
        suivant = depart + len(page)
        return borner(
            {
                **entete,
                "indicateurs": page,
                "depart": depart,
                "prochain_depart": suivant if suivant < len(lignes) else None,
            },
            budget_sortie,
        )

    return (
        Outil(
            nom="m9_indicateurs_executifs",
            description=(
                "Relie les indicateurs de direction (revenu, marges, cash libre, pipeline, conversion, rentabilité, "
                "ROI, coût par lead, capacité, stocks, satisfaction, risque) à leur définition officielle chez M8 ou "
                "leur propriétaire, nomme ceux sans définition, cite les faits des captures complètes, ne calcule rien."
            ),
            parametres={
                "type": "object",
                "properties": {"connaissance": _INSTANT, "depart": {"type": "integer", "minimum": 0}},
                "required": ["connaissance"],
                "additionalProperties": False,
            },
            fonction=indicateurs,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
