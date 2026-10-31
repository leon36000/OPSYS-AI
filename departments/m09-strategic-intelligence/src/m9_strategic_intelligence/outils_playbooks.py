"""Outils des playbooks M9.15 : lister les gabarits, instancier et évaluer sur l'état réel (rien d'exécuté)."""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import playbooks, risques
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

    def lister(depart: int = 0) -> dict[str, Any]:
        exiger_admin_strict()
        fiches = [
            {
                "playbook": id_,
                "nom": gabarit["nom"],
                "declenche_par": gabarit["declenche_par"] or "declaration de la personne",
                "etapes": len(gabarit["etapes"]),
                "etapes_sensibles": sum(1 for e in gabarit["etapes"] if e["type"] == "action_sensible"),
                "approbation_requise": gabarit["approbation_requise"],
                "donnees_requises": gabarit["donnees_requises"],
                "departements": gabarit["departements"],
                "risques": gabarit["risques"],
                "plan_retour": gabarit["plan_retour"],
                "limites": gabarit["limites"],
            }
            for id_, gabarit in playbooks.CATALOGUE.items()
        ]
        if type(depart) is not int or not 0 <= depart <= len(fiches):
            raise ValueError("REJ-PLAYBOOK-DEPART : départ entre 0 et le nombre de playbooks requis ; reprendre à 0")
        entete = {"accepte": True, "version": playbooks.VERSION, "total": len(fiches)}
        marge = budget_sortie - len(cs.canonique(entete)) - 200
        page: list[dict] = []
        for fiche in fiches[depart:]:
            if len(cs.canonique(page + [fiche])) > marge:
                break
            page.append(fiche)
        if fiches[depart:] and not page:
            raise ValueError("REJ-TISSU-BORNE : une fiche de playbook dépasse la borne de sortie")
        suivant = depart + len(page)
        return borner(
            {
                **entete,
                "playbooks": page,
                "depart": depart,
                "prochain_depart": suivant if suivant < len(fiches) else None,
            },
            budget_sortie,
        )

    def evaluer(
        playbook_id: str,
        connaissance: str,
        perime_apres_jours: int | None = None,
        declare_par_la_personne: bool = False,
        liaisons: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        exiger_admin_strict()
        chaine = captures()
        radar = risques.evaluer(chaine, connaissance=connaissance, perime_apres_jours=perime_apres_jours)
        plan = playbooks.instancier(
            playbook_id,
            radar,
            connaissance=connaissance,
            declare_par_la_personne=declare_par_la_personne,
            liaisons=liaisons,
        )
        evaluation = playbooks.evaluer_criteres(plan, chaine, connaissance=connaissance)
        return borner(
            {"accepte": True, "radar_id": radar["radar_id"], "plan": plan, "evaluation": evaluation}, budget_sortie
        )

    return (
        Outil(
            nom="m9_lister_playbooks",
            description=(
                "Liste les gabarits de playbooks (cash, leads, surcharge, météo, rupture, prix, plaintes, conversion, "
                "marketing, saisons, embauche, équipement, expansion, service, avis) : données requises, départements, "
                "risques, approbation requise et plan de retour, par pages bornées (depart, prochain_depart)."
            ),
            parametres={
                "type": "object",
                "properties": {"depart": {"type": "integer", "minimum": 0}},
                "required": [],
                "additionalProperties": False,
            },
            fonction=lister,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_evaluer_playbook",
            description=(
                "Instancie un playbook sur l'état réel (déclencheur du radar ou déclaré par la personne), rend ses "
                "étapes gouvernées (sensibles = validation humaine, aucun effet autorisé) et lit ses critères de "
                "succès et d'arrêt "
                "sur les captures ; une cible absente rend le critère inconnu."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "playbook_id": {"type": "string", "enum": sorted(playbooks.CATALOGUE)},
                    "connaissance": _INSTANT,
                    "perime_apres_jours": {"type": "integer", "minimum": 0, "maximum": 3650},
                    "declare_par_la_personne": {"type": "boolean"},
                    "liaisons": {"type": "object", "additionalProperties": {"type": "string", "maxLength": 24}},
                },
                "required": ["playbook_id", "connaissance"],
                "additionalProperties": False,
            },
            fonction=evaluer,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
