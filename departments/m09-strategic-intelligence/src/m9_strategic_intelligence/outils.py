"""Capacités d'agent du département M9 Strategic Intelligence.

M9 v1 est un harnais déterministe pur (PRD §0/§3.1) : aucun Council d'agents, aucun contenu
délibératif — il agrège les snapshots que les autres modules lui rapportent dans un état
consolidé (Business State Graph) et signale les contradictions internes, sans jamais inventer
ni recommander. `m9_etat_consolide` compose ingestion → écriture au registre → construction de
l'état consolidé (contradictions comprises) en un seul appel.

Le registre est un singleton en mémoire du processus MCP de ce département — même convention
que m8_analytics/outils.py (un serveur MCP stdio par profil, cf.
docs/architecture/ARCHITECTURE.md) ; la persistance sur disque est hors périmètre v1.
"""

from __future__ import annotations

from typing import Any

from opsys.outils import Autonomie, Outil, depuis_couple

from . import contrats
from . import etat_consolide as etat_consolide_module
from . import rapport_strategique, registre, validation

_REGISTRE = registre.RegistreSnapshots()

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


def lire_etat_consolide() -> dict[str, Any]:
    """État consolidé courant par relecture pure du registre — n'ingère rien de nouveau."""
    return etat_consolide_module.construire_etat_consolide(_REGISTRE)


def etat_consolide(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Chaîne complète : validation → écriture registre → état consolidé.

    Bloque avant d'écrire si le snapshot est structurellement refusé (etape="validation").
    L'état consolidé retourné porte toujours `contradictions` (même liste vide) : une
    contradiction interne n'est jamais résolue automatiquement, seulement nommée.
    """
    valide, verdict = validation.valider_snapshot(snapshot)
    if not valide:
        return {"etape": "validation", "accepte": False, "verdict": verdict}

    _REGISTRE.ajouter(snapshot)
    etat = etat_consolide_module.construire_etat_consolide(_REGISTRE)
    return {"etape": "complet", "accepte": True, "etat_consolide": etat}


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
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
