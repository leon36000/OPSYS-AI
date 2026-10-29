"""Outils de plans et OKR M9.16 : déposer ou réviser, annuler, noter un suivi, lire. Rien d'exécuté, rien de fabriqué.

Un plan cite ses sources par adresse de fait du dossier stratégique : la valeur citée est figée au dépôt et comparée
plus
tard à la dernière capture. Un suivi est une note de personne, jamais un effet réalisé. Admin authentifié seulement.
"""

from __future__ import annotations

from typing import Any

from opsys import contexte, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import dossier_strategique, plans
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_PLANS = "plans"
REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}
_ID = {"type": "string", "minLength": 1, "maxLength": 128}
_JOUR = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$", "description": "Jour civil AAAA-MM-JJ."}


def construire_outils(*, budget_sortie: int, plans_cible: Any = None, captures_cible: Any = None) -> tuple[Outil, ...]:
    def registre() -> Any:
        return plans_cible if plans_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_PLANS)

    def chaine() -> list[dict]:
        liste = list(registre())
        ok, raison = plans.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-PLAN-CHAINE-INVALIDE : registre des plans invalide ({raison})")
        return liste

    def captures() -> list[dict]:
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        liste = list(source)
        ok, raison = cs.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-CAPTURE-CHAINE-INVALIDE : registre des captures invalide ({raison})")
        return liste

    def personne() -> str:
        appelante = contexte.identite_appelante()
        return appelante.personne if appelante is not None else "inconnu"

    def enregistrer_plan(
        plan: dict[str, Any], reference: str, horodatage: str, motif_revision: str | None = None
    ) -> dict[str, Any]:
        exiger_admin_strict()
        liste = chaine()
        faits = dossier_strategique.construire(
            captures(), question="Plan", domaines=["strategie"], reference=reference, connaissance=horodatage
        )["faits"]
        maillon = plans.enregistrer(
            liste, plan, faits, recu_a=horodatage, par=personne(), motif_revision=motif_revision
        )
        registre().append(maillon, rang_attendu=len(liste))
        return {
            "accepte": True,
            "plan_id": maillon["plan_id"],
            "version": maillon["version"],
            "revision": maillon["version"] > 1,
        }

    def annuler_plan(plan_id: str, motif: str, horodatage: str) -> dict[str, Any]:
        exiger_admin_strict()
        liste = chaine()
        maillon = plans.annuler(liste, plan_id, motif, recu_a=horodatage, par=personne())
        registre().append(maillon, rang_attendu=len(liste))
        return {"accepte": True, "plan_id": plan_id, "annule": True}

    def suivre(plan_id: str, resultat_id: str, note: str, horodatage: str) -> dict[str, Any]:
        exiger_admin_strict()
        liste = chaine()
        maillon = plans.noter_suivi(liste, plan_id, resultat_id, note, recu_a=horodatage, par=personne())
        registre().append(maillon, rang_attendu=len(liste))
        return {"accepte": True, "plan_id": plan_id, "resultat_id": resultat_id, "effet_realise": False}

    def lire(connaissance: str, jour: str, plan_id: str | None = None) -> dict[str, Any]:
        exiger_admin_strict()
        projection = plans.vue(chaine(), captures(), connaissance=connaissance, jour=jour)
        if plan_id is not None:
            projection["plans"] = [p for p in projection["plans"] if p["plan_id"] == plan_id]
        return borner({"accepte": True, **projection}, budget_sortie)

    def outil(nom, description, proprietes, requis, fonction, *, ecriture=False):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=Autonomie.T1 if ecriture else Autonomie.T0,
            niveau=Niveau.N2 if ecriture else Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        )

    return (
        outil(
            "m9_enregistrer_plan",
            "Dépose (version 1) ou révise (version n+1, motif obligatoire) un plan : objectif, porteur, échéance, "
            "résultats clés mesurables ou manuels, sources citées par adresse de fait. Une révision ajoute une "
            "version, elle n'écrase rien ; un plan annulé ne se rouvre pas.",
            {
                "plan": {"type": "object"},
                "reference": _INSTANT,
                "horodatage": _INSTANT,
                "motif_revision": {"type": "string", "maxLength": 300},
            },
            ["plan", "reference", "horodatage"],
            enregistrer_plan,
            ecriture=True,
        ),
        outil(
            "m9_annuler_plan",
            "Annule un plan avec son motif ; l'historique reste.",
            {"plan_id": _ID, "motif": {"type": "string", "minLength": 1, "maxLength": 300}, "horodatage": _INSTANT},
            ["plan_id", "motif", "horodatage"],
            annuler_plan,
            ecriture=True,
        ),
        outil(
            "m9_noter_suivi_plan",
            "Note un suivi sur un résultat clé : déclaration de la personne, jamais un effet réalisé.",
            {
                "plan_id": _ID,
                "resultat_id": _ID,
                "note": {"type": "string", "minLength": 1, "maxLength": 500},
                "horodatage": _INSTANT,
            },
            ["plan_id", "resultat_id", "note", "horodatage"],
            suivre,
            ecriture=True,
        ),
        outil(
            "m9_lire_plans",
            "Plans à un instant : version courante et historique, retard calculé du jour donné, résultats clés "
            "mesurés chez leurs propriétaires, sources changées depuis le dépôt.",
            {"connaissance": _INSTANT, "jour": _JOUR, "plan_id": _ID},
            ["connaissance", "jour"],
            lire,
        ),
    )
