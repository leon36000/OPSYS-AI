"""Outils des radars M9.12–13 : risques et occasions, en lecture seule, à partir des captures connues."""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import dossier_strategique, occasions, reglages_radar, risques
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def construire_outils(*, budget_sortie: int, captures_cible: Any = None) -> tuple[Outil, ...]:
    def captures() -> list[dict]:
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise ValueError(f"REJ-CAPTURE-CHAINE-INVALIDE : registre des captures invalide ({raison})")
        return chaine

    def radar_risques(connaissance: str, perime_apres_jours: int | None = None, depart: int = 0) -> dict[str, Any]:
        exiger_admin_strict()
        radar = risques.evaluer(
            captures(), connaissance=connaissance, perime_apres_jours=perime_apres_jours, **reglages_radar.lire()
        )
        liste, regles = radar["risques"], radar["regles_non_evaluees"]
        total = len(liste) + len(regles)
        if type(depart) is not int or not 0 <= depart <= total:
            raise ValueError("REJ-RADAR-DEPART : départ entre 0 et le nombre d'éléments requis ; reprendre à 0")
        # Une seule curseur sur les risques PUIS les règles non évaluées : la sortie d'un outil est bornée, et un radar
        # sans seuil déclaré compte plus de règles non évaluées que de risques.
        entete = {
            "accepte": True,
            "type": radar["type"],
            "version": radar["version"],
            "grille": radar["grille"],
            "connaissance": radar["connaissance"],
            "perime_apres_jours": radar["perime_apres_jours"],
            "perime_origine": radar["perime_origine"],
            "radar_id": radar["radar_id"],
            "total_risques": len(liste),
            "total_regles_non_evaluees": len(regles),
            "depart": depart,
        }
        if depart == 0:  # le contexte du radar : une fois, à la première page
            entete.update(
                {
                    k: radar[k]
                    for k in ("regles_evaluees", "seuils_declares", "escalade", "reglages_a_declarer", "limites")
                }
            )
        marge = budget_sortie - len(cs.canonique(entete)) - 400
        page_risques: list[dict] = []
        page_regles: list[dict] = []
        position = depart
        while position < total:
            if position < len(liste):
                candidat, cible = liste[position], page_risques
            else:
                candidat, cible = regles[position - len(liste)], page_regles
            if len(cs.canonique([*page_risques, *page_regles, candidat])) > marge:
                break
            cible.append(candidat)
            position += 1
        if position == depart and total > depart:
            raise ValueError("REJ-TISSU-BORNE : un élément du radar dépasse la borne de sortie")
        return borner(
            {
                **entete,
                "risques": page_risques,
                "regles_non_evaluees": page_regles,
                "prochain_depart": position if position < total else None,
            },
            budget_sortie,
        )

    def radar_occasions(
        reference: str, connaissance: str | None = None, occasions_declarees: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        exiger_admin_strict()
        chaine = captures()
        faits = dossier_strategique.construire(
            chaine,
            question="Occasions",
            domaines=["strategie"],
            reference=reference,
            connaissance=connaissance or reference,
        )["faits"]
        radar = occasions.evaluer(occasions_declarees or [], faits, chaine, connaissance=connaissance or reference)
        return borner({"accepte": True, **radar}, budget_sortie)

    def outil(nom, description, proprietes, requis, fonction):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        )

    return (
        outil(
            "m9_radar_risques",
            "Signale les risques déjà mesurés par les propriétaires (cash M5, matériaux M6, incidents M4, marge M8) : "
            "gravité d'une grille proposée non validée, preuves citées, faux positifs levés, sources périmées à "
            "reconfirmer, règles non évaluées nommées ; jamais de cause.",
            {
                "connaissance": _INSTANT,
                "perime_apres_jours": {"type": "integer", "minimum": 0, "maximum": 3650},
                "depart": {"type": "integer", "minimum": 0},
            },
            ["connaissance"],
            radar_risques,
        ),
        outil(
            "m9_radar_occasions",
            "Évalue des occasions déclarées (conditions, alternatives, coût et capacité cités) et les signaux mesurés "
            "(devis sans réponse M8) : sans coût ni capacité cités, une occasion reste une hypothèse ; aucun revenu, "
            "gain ni probabilité n'est produit ou accepté.",
            {
                "reference": _INSTANT,
                "connaissance": _INSTANT,
                "occasions_declarees": {
                    "type": "array",
                    "items": {"type": "object"},
                    "maxItems": occasions.MAX_OCCASIONS,
                },
            },
            ["reference"],
            radar_occasions,
        ),
    )
