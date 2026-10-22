"""Provisionnement explicite des profils durables des agents départementaux.

Le générateur ne crée ni profil, ni plafond, ni autorité. Les budgets initiaux proviennent
des manifestes; les limites d'exécution et les plafonds entreprise sont des choix opérateur.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, select

from . import admission_agents, agents
from .departements import Departement
from .stockage.schema import AGENTS_POLITIQUE_ENTREPRISE

# Capacités historiques partagées sous le serveur du département. Leur admission
# de profil ne remplace jamais leurs contrôles propres de portée/mémoire/approbation.
OUTILS_PARTAGES_RUNTIME = frozenset({
    "opsys_lire_artefact", "opsys_etat_budget", "opsys_demandes_approbation",
    "opsys_memoire_rechercher", "opsys_memoire_ajouter", "opsys_memoire_oublier",
})


def identifiant(departement_id: str) -> str:
    return f"base-{departement_id}"


def est_base(profil: Mapping[str, Any]) -> bool:
    """L'origine et l'identifiant exacts doivent concorder; un préfixe seul ne suffit pas."""
    departement = profil.get("departement")
    return isinstance(departement, str) and profil.get("id") == identifiant(departement)


def agent_core_id(profil: Mapping[str, Any]) -> str:
    """Même identité pour export, déclenchement et retrait; le profil reste le propriétaire SQL."""
    if not isinstance(profil.get("id"), str) or not isinstance(profil.get("departement"), str):
        raise ValueError("identité de profil et département requis")
    return profil["departement"] if est_base(profil) else f"opsys-agent-{profil['id']}"


def lire(cnx: Connection, departements: Mapping[str, Departement]) -> dict[str, dict[str, Any]]:
    """Exige des profils réels, actifs, de la bonne origine, et une politique entreprise."""
    profils: dict[str, dict[str, Any]] = {}
    for dep in departements.values():
        profil = agents.obtenir(cnx, identifiant(dep.id), inclure_supprime=True)
        if (profil is None or not profil["actif"] or profil["supprime"]
                or profil["departement"] != dep.id):
            raise ValueError(
                f"profils de base : {dep.id} sans profil actif compatible; "
                "provisionner explicitement avec `opsys-metier agents-base provisionner`"
            )
        specification = {cle: profil[cle] for cle in (
            "id", "departement", "responsabilite", "palier_modele", "outils", "budget_jour", "budget_mois",
            "limite_tours", "limite_reessais", "limite_concurrence", "declencheurs",
        )}
        agents._specification(departements, specification)
        profils[dep.id] = profil
    if cnx.execute(select(AGENTS_POLITIQUE_ENTREPRISE.c.id)).first() is None:
        raise ValueError("profils de base : plafonds entreprise non configurés")
    return profils


def provisionner(
    cnx: Connection, departements: Mapping[str, Departement], *, par: str,
    limite_tours: int, limite_reessais: int, limite_concurrence: int,
    budget_entreprise_jour: int, budget_entreprise_mois: int,
) -> dict[str, dict[str, Any]]:
    """Crée les profils manquants en transaction; ne réactive ou ne réécrit jamais l'existant.

    Les mutations individuelles portent des clés stables. Une reprise conserve révisions,
    usage et modifications administrateur; un profil désactivé exige sa réactivation explicite.
    L'appelant doit posséder une transaction d'écriture et authentifier l'opérateur humain.
    """
    agents._admin_actif(cnx, par)
    # Valider toutes les spécifications avant de créer la première ligne.
    specifications = []
    for dep in departements.values():
        spec = {
            "id": identifiant(dep.id), "departement": dep.id, "responsabilite": dep.mission,
            "palier_modele": dep.modeles["defaut"], "outils": [o.nom for o in dep.charger_outils()],
            "budget_jour": dep.budget.tokens_jour, "budget_mois": dep.budget.tokens_mois,
            "limite_tours": limite_tours, "limite_reessais": limite_reessais,
            "limite_concurrence": limite_concurrence, "declencheurs": [{"type": "manuel"}],
        }
        agents._specification(departements, spec)
        specifications.append(spec)
    politique = cnx.execute(select(AGENTS_POLITIQUE_ENTREPRISE)).mappings().first()
    if politique is None:
        admission_agents.configurer_plafonds_entreprise(
            cnx, budget_entreprise_jour, budget_entreprise_mois, par=par, revision_attendue=0
        )
    elif (politique["budget_jour"], politique["budget_mois"]) != (
        budget_entreprise_jour, budget_entreprise_mois
    ):
        raise ValueError("plafonds entreprise existants différents : modifier explicitement leur révision en console")
    for spec in specifications:
        existant = agents.obtenir(cnx, spec["id"], inclure_supprime=True)
        if existant is not None:
            if (existant["departement"] != spec["departement"] or existant["supprime"]
                    or not existant["actif"]):
                raise ValueError(f"profil de base existant incompatible : {spec['id']}; intervention admin explicite")
            continue
        profil = agents.creer(cnx, departements, spec, par=par, mutation_id=f"base-create:{spec['id']}")
        agents.definir_actif(cnx, profil["id"], departements, True, par=par,
                            mutation_id=f"base-enable:{spec['id']}", revision_attendue=profil["revision"])
    return lire(cnx, departements)
