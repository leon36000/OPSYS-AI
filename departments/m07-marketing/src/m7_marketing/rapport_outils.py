"""Lecture du rapport marketing hebdomadaire (M7-RAPPORT-HEBDO) et tâches internes dans « À voir ».

Le rapport n'est PAS composé par un outil d'agent : le planificateur durable (exécuteur `m7.rapport-hebdo`, inactif
par défaut,
ombre d'abord) lit les mesures de M8 et le dossier de M7, compose, enregistre une fois par semaine, crée les tâches et
annonce
les observations de mémoire. Cet outil ne fait que le LIRE (T0, agent seulement, aucun droit d'appareil). Comme il
porte des
montants (marge constatée par M5), la lecture par un appareil est réservée à l'admin confirmé en base.

La réponse tient sous la borne de 6 000 caractères du socle : la vue d'ensemble retire des recommandations ENTIÈRES (les
moins prioritaires) plutôt que de couper un texte ; une section se lit seule (`section`).
"""

from __future__ import annotations

import json
from typing import Any

from opsys.outils import Outil

from .rapport_hebdo import service
from .usine import service as usine_service

BUDGET_SORTIE = 5400
SECTIONS = (
    "leads_par_canal",
    "cout_par_lead",
    "conversion",
    "roi",
    "croissance_engagement",
    "contenus",
    "calendrier",
    "reputation",
    "plan_croissance",
    "mesures_m8",
)
ACTION_TACHE = "faire la tâche ou la classer : rien ne s'exécute seul, ni publication ni dépense"


def lire_rapport_hebdomadaire(semaine: str | None = None, section: str | None = None) -> dict[str, Any]:
    """Le rapport hebdomadaire de la semaine `semaine` (lundi AAAA-MM-JJ), ou le plus récent. Lecture pure."""
    refus = usine_service._refus_lecture_admin()  # noqa: SLF001 — même garde que la lecture des contenus
    if refus is not None:
        return {"accepte": False, "verdict": refus}
    if section is not None and section not in SECTIONS:
        raise ValueError(f"section : {', '.join(SECTIONS)}")
    lu = service.lire(semaine)
    if lu["statut"] != "rapport":
        return {
            **lu,
            "lecture": "Aucun rapport enregistré pour cette semaine : le planificateur ne l'a pas encore composé "
            "(exécuteur inactif ou en ombre), ou la semaine n'est pas terminée. Rien n'est inventé.",
        }
    rapport = lu["rapport"]
    if section is not None:
        return {"statut": "section", "semaine": lu["semaine"], "section": section, "contenu": rapport[section]}
    recs = [
        {
            "id": r["id"],
            "priorite": r["priorite"],
            "action": r["action"],
            "hypothese": r["hypothese"],
            "sources": [f"{s['type']}:{s['ref']}" for s in r["sources"]],
            "tache": r["tache"],
        }
        for r in rapport["recommandations"]
    ]
    vue = {
        "statut": "rapport",
        "semaine": rapport["semaine"],
        "cree_le": lu["cree_le"],
        "empreinte": rapport["empreinte"],
        "sources": rapport["sources"],
        "synthese": {
            nom: rapport[nom].get("statut")
            for nom in SECTIONS
            if nom in rapport and isinstance(rapport[nom], dict) and "statut" in rapport[nom]
        },
        "donnees_manquantes": [m[:200] for m in rapport["donnees_manquantes"][:6]],
        "recommandations": recs,
        "recommandations_omises": 0,
        "lecture": "Une section se lit avec `section`. Chaque recommandation cite ses sources ou se dit hypothèse.",
    }
    while len(json.dumps(vue, ensure_ascii=False)) > BUDGET_SORTIE and vue["recommandations"]:
        vue["recommandations"].pop()
        vue["recommandations_omises"] += 1
    return vue


def taches_attentes() -> list[dict[str, Any]]:
    """Les tâches internes de niveau bas de la dernière semaine, pour « À voir » (forme `CHAMPS_ATTENTE`)."""
    return [
        {
            "type": "tache_marketing",
            "id": t["tache_id"],
            "resume": t["resume"],
            "niveau": t["niveau"],
            "depuis": t["cree_le"],
            "action_proposee": ACTION_TACHE,
        }
        for t in service.taches_courantes()
    ]


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m7_lire_rapport_hebdomadaire",
            description=(
                "Lit le rapport marketing hebdomadaire déjà composé par le planificateur (leads par canal, coût par "
                "lead tel "
                "que M8 le donne, conversion, ROI honnête sans ratio inventé, croissance et engagement, meilleurs et "
                "pires "
                "contenus, calendrier, avis, plan de croissance organique) et ses recommandations priorisées, "
                "chacune liée à "
                "une donnée ou marquée hypothèse. Sans `semaine` : le plus récent. `section` lit une section "
                "entière. Aucun "
                "rapport enregistré : le dit, n'invente rien. Lecture pure ; ne publie, ne dépense ni n'envoie rien."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "semaine": {
                        "type": "string",
                        "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                        "description": "le lundi de la semaine (AAAA-MM-JJ)",
                    },
                    "section": {"type": "string", "enum": list(SECTIONS)},
                },
                "additionalProperties": False,
            },
            fonction=lire_rapport_hebdomadaire,
        ),
    )
