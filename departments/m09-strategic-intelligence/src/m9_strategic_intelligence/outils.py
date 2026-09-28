"""Capacités d'agent du département M9 Strategic Intelligence.

M9 v1 est un harnais déterministe pur (PRD §0/§3.1) : aucun Council d'agents, aucun contenu
délibératif — il agrège les snapshots que les autres modules lui rapportent dans un état
consolidé (Business State Graph) et signale les contradictions internes, sans jamais inventer
ni recommander. `m9_etat_consolide` compose ingestion → écriture au registre → construction de
l'état consolidé (contradictions comprises) en un seul appel.

Registre de production (ADR-0009) : par défaut, `outils()` adosse le registre de snapshots au
stockage durable de l'instance (`opsys.stockage.maillons`, dans la transaction que
`Capacites.appeler` ouvre pour chaque appel d'outil) — même convention que
m8_analytics/outils.py. `registre.py` reste pur (aucun import `opsys`/SQLAlchemy) et ignore que
ses maillons survivent au redémarrage : c'est cet adaptateur, seul, qui fait le lien. Le
paramètre `registre_cible` est le point d'injection : les tests unitaires du département y
passent explicitement un `registre.RegistreSnapshots()` EN MÉMOIRE (aucune base montée), sans
toucher au comportement par défaut utilisé par `charger_outils()` en production.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import contrats, rapport_strategique, registre, validation
from . import etat_consolide as etat_consolide_module

_SNAPSHOT = {
    "type": "object",
    "description": (
        "SnapshotModule {module_source, horodatage, valeurs} — réutilisé tel quel de "
        "m8_analytics (patron mesuré). valeurs est TOUJOURS du texte."
    ),
}
_RAPPORT_STRATEGIQUE = {
    "type": "object",
    "description": (
        f"dict portant EXACTEMENT les {len(contrats.CHAMPS_RAPPORT_STRATEGIQUE)} clés de "
        "CHAMPS_RAPPORT_STRATEGIQUE (structure seulement, v1 ne valide pas le contenu)."
    ),
}


def valider_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(validation.valider_snapshot(snapshot))


def valider_rapport_strategique(rapport: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(rapport_strategique.valider_rapport_strategique(rapport))


def outils(registre_cible: registre.RegistreSnapshots | None = None) -> tuple[Outil, ...]:
    """Capacités exposées aux agents. Une instance de RegistreSnapshots par installation.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.RegistreSnapshots()` explicite
    (tests) reste en mémoire, jamais touché à la base.
    """
    if registre_cible is None:
        registre_cible = registre.RegistreSnapshots(
            maillons=stockage.maillons("m09-strategic-intelligence", "snapshots")
        )

    def lire_etat_consolide() -> dict[str, Any]:
        """État consolidé courant par relecture pure du registre — n'ingère rien de nouveau."""
        return etat_consolide_module.construire_etat_consolide(registre_cible)

    def etat_consolide(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Chaîne complète : validation → écriture registre → état consolidé.

        Bloque avant d'écrire si le snapshot est structurellement refusé (etape="validation").
        L'état consolidé retourné porte toujours `contradictions` (même liste vide) : une
        contradiction interne n'est jamais résolue automatiquement, seulement nommée.
        """
        valide, verdict = validation.valider_snapshot(snapshot)
        if not valide:
            return {"etape": "validation", "accepte": False, "verdict": verdict}

        registre_cible.ajouter(snapshot)
        etat = etat_consolide_module.construire_etat_consolide(registre_cible)
        return {"etape": "complet", "accepte": True, "etat_consolide": etat}

    return (
        Outil(
            nom="m9_etat_consolide",
            description=(
                "Ingère un snapshot (validation puis écriture au registre) et reconstruit "
                "l'état consolidé de bout en bout — dernier fait connu par module (comparaison "
                "chronologique, fuseaux compris), contradictions internes détectées. Bloque "
                "avant d'écrire si le snapshot est structurellement refusé."
            ),
            parametres={
                "type": "object",
                "properties": {"snapshot": _SNAPSHOT},
                "required": ["snapshot"],
                "additionalProperties": False,
            },
            fonction=etat_consolide,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m9_lire_etat_consolide",
            description=(
                "Reconstruit l'état consolidé courant par relecture pure du registre, sans "
                "ingérer de nouveau snapshot."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=lire_etat_consolide,
        ),
        Outil(
            nom="m9_valider_snapshot",
            description=(
                "Valide la structure d'un SnapshotModule (module_source, horodatage, valeurs "
                "toujours en texte), sans l'écrire au registre."
            ),
            parametres={
                "type": "object",
                "properties": {"snapshot": _SNAPSHOT},
                "required": ["snapshot"],
                "additionalProperties": False,
            },
            fonction=valider_snapshot,
        ),
        Outil(
            nom="m9_valider_rapport_strategique",
            description=(
                "Valide qu'un rapport stratégique porte EXACTEMENT les 15 clés attendues "
                "(structure seulement, jamais la pertinence du contenu — v1 n'a pas de Council)."
            ),
            parametres={
                "type": "object",
                "properties": {"rapport": _RAPPORT_STRATEGIQUE},
                "required": ["rapport"],
                "additionalProperties": False,
            },
            fonction=valider_rapport_strategique,
        ),
    )
