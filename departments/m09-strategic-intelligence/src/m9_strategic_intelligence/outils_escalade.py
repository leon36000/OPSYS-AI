"""Outils de l'escalade interne des risques critiques (M9.12) : avis, tâche, mémoire — jamais un message externe.

``m9_escalader_risques_critiques`` (T1 / N2, admin authentifié, aucun droit d'appareil) relit le radar à l'instant
fourni
(captures déjà reçues, seuils DÉCLARÉS par la direction) et, pour chaque risque ACTIF de gravité CRITIQUE, ajoute :

1. un avis au registre chaîné ``avis_risques`` ;
2. une tâche (plan M9, résultat clé manuel) — non doublée si une tâche de la même règle et du même sujet est ouverte ;
3. l'évènement ``m9.fait_strategique`` (genre ``risque``) que M10 mémorise.

Tout est INTERNE et append-only : l'outil n'a aucun port vers un courriel, un SMS ou une publication, ne demande aucune
approbation et n'appelle aucun autre département. Rejouer le même jour n'ajoute rien (avis déterministe par règle,
sujet et jour). L'outil n'est branché à aucun planificateur : l'automatisation sous un acteur système attend une
décision de la direction. ``m9_lire_avis_risques`` (T0 / N0) relit les avis.
"""

from __future__ import annotations

from typing import Any

from opsys import contexte, evenements, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import escalade_risques as esc
from . import plans as plans_module
from . import reglages_radar, risques
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_AVIS = "avis_risques"
REGISTRE_PLANS = "plans"
REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def construire_outils(
    *, budget_sortie: int, avis_cible: Any = None, plans_cible: Any = None, captures_cible: Any = None
) -> tuple[Outil, ...]:
    def registre(cible: Any, nom: str) -> Any:
        return cible if cible is not None else stockage.maillons(DEPARTEMENT, nom)

    def chaine_verifiee(cible: Any, nom: str, valider, code: str) -> list[dict]:
        liste = list(registre(cible, nom))
        ok, raison = valider(liste)
        if not ok:
            raise ValueError(f"{code} : registre {nom} invalide ({raison})")
        return liste

    def captures() -> list[dict]:
        return chaine_verifiee(captures_cible, REGISTRE_CAPTURES, cs.valider_chaine, "REJ-CAPTURE-CHAINE-INVALIDE")

    def personne() -> str:
        appelante = contexte.identite_appelante()
        return appelante.personne if appelante is not None else "inconnu"

    def tache_ouverte(chaine_plans: list[dict], suivi_ref: str) -> str | None:
        for plan_id, etat in sorted(plans_module.etat_plans(chaine_plans).items()):
            if (
                etat["annule"] is None
                and etat["versions"]
                and etat["versions"][-1]["plan"]["decision_ref"] == suivi_ref
            ):
                return plan_id
        return None

    def publier(maillon: dict) -> dict[str, Any]:
        charge = esc.evenement_memoire(maillon)
        premiere = evenements.charge_publiee(esc.TYPE_EVENEMENT, charge["evenement_id"])
        evenements.publier(
            esc.TYPE_EVENEMENT, DEPARTEMENT, premiere if premiere is not None else charge,
            evenement_id=charge["evenement_id"],
        )  # fmt: skip
        return {"evenement_id": charge["evenement_id"], "nouveau": premiere is None}

    def escalader(connaissance: str) -> dict[str, Any]:
        exiger_admin_strict()
        radar = risques.evaluer(captures(), connaissance=connaissance, **reglages_radar.lire())
        avis_chaine = chaine_verifiee(avis_cible, REGISTRE_AVIS, esc.valider_chaine, "REJ-AVIS-CHAINE-INVALIDE")
        plans_chaine = chaine_verifiee(
            plans_cible, REGISTRE_PLANS, plans_module.valider_chaine, "REJ-PLAN-CHAINE-INVALIDE"
        )
        critiques = esc.selection(radar)
        sorties = []
        for risque in critiques:
            ids = esc.identifiants(risque, connaissance)
            maillon = esc.avis(avis_chaine, risque, radar, connaissance=connaissance, par=personne())
            nouveau = maillon is not None
            if nouveau:
                registre(avis_cible, REGISTRE_AVIS).append(maillon, rang_attendu=len(avis_chaine))
                avis_chaine.append(maillon)
            else:
                maillon = next(m for m in avis_chaine if m["avis_id"] == ids["avis_id"])
            tache_id = tache_ouverte(plans_chaine, ids["suivi_ref"])
            tache_nouvelle = tache_id is None
            if tache_nouvelle:
                plan = esc.tache(risque, connaissance=connaissance)
                depot = plans_module.enregistrer(plans_chaine, plan, {}, recu_a=connaissance, par=personne())
                registre(plans_cible, REGISTRE_PLANS).append(depot, rang_attendu=len(plans_chaine))
                plans_chaine.append(depot)
                tache_id = plan["plan_id"]
            memoire = publier(maillon)
            sorties.append({
                "regle": risque["regle"], "sujet": risque["sujet"], "domaine": risque["domaine"],
                "gravite": risque["gravite"], "raison": risque["raison"],
                "avis_id": maillon["avis_id"], "avis_nouveau": nouveau,
                "tache_id": tache_id, "tache_nouvelle": tache_nouvelle, "memoire": memoire,
            })  # fmt: skip
        return borner(
            {
                "accepte": True,
                "type": "ESCALADE_RISQUES_CRITIQUES",
                "connaissance": connaissance,
                "radar_id": radar["radar_id"],
                "critiques_trouves": len(critiques),
                "escalades": sorties,
                "canaux": list(esc.CANAUX),
                "externe": False,
                "regles_non_evaluees": len(radar["regles_non_evaluees"]),
                "escalade_par_depassement": radar["escalade"],
                "limites": [
                    *esc._LIMITES,
                    "Un risque inconnu (règle non évaluée) n'est pas escaladé : il n'est pas un risque établi.",
                ],
            },
            budget_sortie,
        )

    def lire(depart: int = 0) -> dict[str, Any]:
        exiger_admin_strict()
        chaine = chaine_verifiee(avis_cible, REGISTRE_AVIS, esc.valider_chaine, "REJ-AVIS-CHAINE-INVALIDE")
        if type(depart) is not int or not 0 <= depart <= len(chaine):
            raise ValueError("REJ-AVIS-DEPART : départ entre 0 et le nombre d'avis requis ; reprendre à 0")
        return borner({"accepte": True, **esc.vue(chaine, depart=depart, limite=5)}, budget_sortie)

    return (
        Outil(
            nom="m9_escalader_risques_critiques",
            description=(
                "Escalade INTERNE des risques critiques du radar à l'instant fourni : pour chaque risque actif de "
                "gravité CRITIQUE, un avis (registre chaîné), une tâche pour la direction (plan M9, résultat clé "
                "manuel) et une trace pour la mémoire de M10 (m9.fait_strategique). Aucun message externe, aucune "
                "approbation, aucune action ; rejouer le même jour n'ajoute rien. Admin authentifié seulement."
            ),
            parametres={
                "type": "object",
                "properties": {"connaissance": _INSTANT},
                "required": ["connaissance"],
                "additionalProperties": False,
            },
            fonction=escalader,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m9_lire_avis_risques",
            description="Relit les avis internes de risques critiques (du plus récent au plus ancien, par pages de "
            "cinq) : règle, sujet, raison, mesure, tâche liée. Lecture seule ; admin authentifié.",
            parametres={
                "type": "object",
                "properties": {"depart": {"type": "integer", "minimum": 0}},
                "additionalProperties": False,
            },
            fonction=lire,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset(),
        ),
    )
