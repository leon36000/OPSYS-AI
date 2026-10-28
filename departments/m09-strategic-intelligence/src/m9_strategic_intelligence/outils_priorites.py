"""Outil de priorisation M9.11 : classe des pistes déclarées et propose une allocation de jours-personnes.

Lecture seule : ne crée aucune tâche, n'affecte personne. La capacité, si elle est utilisée, est soit un FAIT CITÉ du
dossier stratégique (adresse exacte, valeur décimale ; le sens « jours-personnes » est alors l'affirmation de
l'appelant, inscrite dans ``source_capacite``), soit une HYPOTHÈSE DÉCLARÉE par la personne, nommée comme telle
(aucun producteur n'expose aujourd'hui de capacité d'équipe). Sans l'un ni l'autre, le classement est rendu
sans allocation.
"""

from __future__ import annotations

import re
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import dossier_strategique, priorisation
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
_FAIT_DECIMAL = re.compile(r"\d{1,9}(\.\d{1,2})?")
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def construire_outils(*, budget_sortie: int, captures_cible: Any = None) -> tuple[Outil, ...]:
    def captures() -> list[dict]:
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        return chaine

    def prioriser(
        candidats: list[dict[str, Any]],
        reference: str,
        connaissance: str | None = None,
        capacite_fait: str | None = None,
        capacite_declaree: str | None = None,
    ) -> dict[str, Any]:
        exiger_admin_strict()
        capacite = None
        source = capacite_fait
        if capacite_fait is not None and capacite_declaree is not None:
            raise _refus("REJ-PRIORITE-CAPACITE", "capacité : un fait cité OU une hypothèse déclarée, pas les deux")
        if capacite_declaree is not None:
            capacite, source = capacite_declaree, priorisation.SOURCE_HYPOTHESE
        if capacite_fait is not None:
            faits = dossier_strategique.construire(
                captures(),
                question="Priorités",
                domaines=["strategie"],
                reference=reference,
                connaissance=connaissance or reference,
            )["faits"]
            texte = faits.get(capacite_fait) if type(capacite_fait) is str else None
            if texte is None:
                raise _refus("REJ-PRIORITE-CAPACITE", "capacité : adresse absente des faits citables du dossier")
            if not _FAIT_DECIMAL.fullmatch(texte):
                raise _refus("REJ-PRIORITE-CAPACITE", "capacité : le fait cité n'est pas un décimal de jours-personnes")
            capacite = texte
        resultat = priorisation.allouer(candidats, capacite=capacite, source_capacite=source)
        return borner({"accepte": True, **resultat}, budget_sortie)

    return (
        Outil(
            nom="m9_prioriser_options",
            description=(
                "Classe des pistes déclarées (impact, urgence, confiance de 1 à 5) selon une politique versionnée dont "
                "chaque rang se refait à la main, nomme les conflits sans les arbitrer et, si la capacité est un fait "
                "cité du dossier ou une hypothèse déclarée, propose une allocation de jours-personnes sans "
                "affecter personne."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "candidats": {
                        "type": "array",
                        "items": {"type": "object"},
                        "minItems": 1,
                        "maxItems": priorisation.MAX_CANDIDATS,
                    },
                    "reference": _INSTANT,
                    "connaissance": _INSTANT,
                    "capacite_fait": {"type": "string", "minLength": 1, "maxLength": 256},
                    "capacite_declaree": {"type": "string", "minLength": 1, "maxLength": 12},
                },
                "required": ["candidats", "reference"],
                "additionalProperties": False,
            },
            fonction=prioriser,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
