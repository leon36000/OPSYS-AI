"""Tableau de bord OPSYS : vues et actions de pilotage, indépendantes du transport HTTP.

La console web (`opsys.console`) appelle ces fonctions ; les tests aussi, sans serveur. Chacune
passe par les modules du socle (départements, approbations, jetons, modèles, politiques) : aucune
règle n'est réécrite ici. Toute écriture est signée (`par`) et journalisée.

La connexion à la base de l'instance est fournie par l'appelant (`opsys.etat.session`, ADR-0009),
ce qui laisse la maîtrise des transactions et des fils d'exécution au transport.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from . import approbations, jetons, modeles
from .capacites import outils_executables
from .departements import PALIERS, Departement, dependances_manquantes
from .outils import Autonomie, Outil, vers_json
from .politiques import MODES, approbation_requise

logger = logging.getLogger("opsys.tableau_de_bord")

# Statuts de la table `approbations` (contrainte CHECK de opsys.etat ; un test garde l'alignement).
STATUTS = ("en_attente", "refusee", "executee", "echec")
DECISIONS = ("approuver", "refuser")
# Champs d'un palier retenus par opsys.modeles.valider_palier (un test garde l'alignement).
CHAMPS_PALIER = ("provider", "model", "base_url")


def _outils(dep: Departement) -> tuple[tuple[Outil, ...], str | None]:
    """Outils du département, ou l'erreur de chargement à afficher (le reste de la vue reste utile)."""
    try:
        return dep.charger_outils(), None
    except (ImportError, ValueError, TypeError) as exc:
        return (), f"{type(exc).__name__} : {exc}"


def modes_disponibles() -> list[dict[str, str]]:
    """Modes d'autonomie et premier niveau d'outil soumis à approbation dans chacun."""
    return [
        {"mode": mode, "approbation_des": next(a.value for a in Autonomie if approbation_requise(a, mode))}
        for mode in MODES
    ]


def vue_departements(
    cnx: Connection, departements: Mapping[str, Departement], jour: dt.date | None = None
) -> list[dict[str, Any]]:
    """Vue d'ensemble : manifeste, mode effectif, outils, budget consommé, dépendances manquantes."""
    manquantes = dependances_manquantes(departements)
    vues = []
    for dep in departements.values():
        mode = approbations.mode_effectif(cnx, dep.id, dep.mode)
        outils, erreur = _outils(dep)
        vues.append({
            "id": dep.id,
            "code": dep.code,
            "nom": dep.nom,
            "mission": dep.mission,
            "mode": mode,
            "mode_manifeste": dep.mode,
            "outils": [
                {"nom": o.nom, "description": o.description, "autonomie": o.autonomie.value,
                 "approbation_requise": approbation_requise(o.autonomie, mode)}
                for o in outils
            ],
            "erreur_outils": erreur,
            "skills": list(dep.skills),
            "planifications": vers_json(dep.planifications),
            "budget": vers_json(dep.budget),
            "consommation": jetons.etat_budget(cnx, dep.id, dep.budget, jour),
            "kpis": vers_json(dep.kpis),
            "modeles": dict(dep.modeles),
            "dependances": list(dep.dependances),
            "dependances_manquantes": manquantes.get(dep.id, []),
        })
    return vues


def changer_mode(
    cnx: Connection, departements: Mapping[str, Departement], ident: str, mode: str, par: str
) -> dict[str, str]:
    """Fixe le mode d'autonomie d'un département ; la signature est exigée par le socle."""
    if ident not in departements:
        raise KeyError(f"département inconnu : {ident}")
    approbations.fixer_mode(cnx, ident, mode, par)
    logger.info("mode de %s fixé à %s par %s", ident, mode, par)
    return {"departement": ident, "mode": approbations.mode_effectif(cnx, ident, departements[ident].mode),
            "par": par}


def nombre_en_attente(cnx: Connection, limite: int = 100) -> int:
    """Nombre de demandes en attente d'une décision humaine (plafonné à `limite`)."""
    return len(approbations.lister(cnx, "en_attente", limite))


def lister_approbations(
    cnx: Connection,
    departements: Mapping[str, Departement],
    statut: str | None = None,
    limite: int = 100,
) -> list[dict[str, Any]]:
    """Demandes d'approbation, filtrées par statut ; sans filtre, celles en attente passent d'abord.

    Chaque demande garde ses arguments exacts et reçoit, si l'outil est connu, son niveau
    d'autonomie et sa description : l'humain sait ce qu'il approuve.
    """
    if statut is not None and statut not in STATUTS:
        raise ValueError(f"statut inconnu {statut!r} (attendu : {', '.join(STATUTS)})")
    if statut is not None:
        demandes = approbations.lister(cnx, statut, limite)
    else:
        demandes = approbations.lister(cnx, "en_attente", limite) + [
            d for d in approbations.lister(cnx, None, limite) if d["statut"] != "en_attente"
        ]
    index = {o.nom: o for dep in departements.values() for o in _outils(dep)[0]}
    for demande in demandes:
        outil = index.get(demande["outil"])
        dep = departements.get(demande["departement"])
        demande["autonomie"] = outil.autonomie.value if outil else None
        demande["description_outil"] = outil.description if outil else None
        demande["departement_nom"] = dep.nom if dep else None
    return demandes


def decider_approbation(
    cnx: Connection,
    departements: Mapping[str, Departement],
    ident: str,
    decision: str,
    identifiant: str,
    motif: str = "",
    attestation: Mapping[str, Any] | None = None,
    *,
    role: str | None = None,
    appareil: str | None = None,
) -> dict[str, Any]:
    """Approuve (exécute l'outil avec les arguments enregistrés) ou refuse une demande, signée par
    `identifiant` (une personne active, ADR-0009 §5 — voir `opsys.approbations.decider`).

    Un refus ne charge aucun outil : il reste possible même si le code d'un département est cassé.

    `role` et `appareil` (T1.4-f) : le rôle sous lequel signer et l'appareil d'où vient la décision, tels
    que `approbations.decider` les documente. La console et la CLI ne les passent pas ; l'app du
    propriétaire (`opsys.approbations_appareil`) les passe : c'est le même chemin, une trace de plus.
    """
    if decision not in DECISIONS:
        raise ValueError(f"décision inconnue {decision!r} (attendu : approuver ou refuser)")
    approuver = decision == "approuver"
    index: dict[str, Outil] = {}
    if approuver:
        index = outils_executables(departements, lambda: contextlib.nullcontext(cnx))
    resultat = approbations.decider(cnx, ident, approuver, identifiant, index, departements, motif, attestation,
                                    role=role, appareil=appareil)
    logger.info("demande %s : %s par %s", ident, resultat["statut"], identifiant)
    return resultat


def file_proprietaire(
    cnx: Connection, departements: Mapping[str, Departement], limite: int = 100
) -> list[dict[str, Any]]:
    """Demandes d'approbation en attente du socle, plus les attentes déclarées par les départements
    (ADR-0009 §5, PLAN T1.3-a §6) : voir `opsys.approbations.file_proprietaire`."""
    return approbations.file_proprietaire(cnx, departements, limite)


def budgets(
    cnx: Connection, departements: Mapping[str, Departement], jour: dt.date | None = None
) -> list[dict[str, Any]]:
    """Consommation jour/mois face au budget, pour chaque département."""
    return [
        {**jetons.etat_budget(cnx, dep.id, dep.budget, jour), "code": dep.code, "nom": dep.nom,
         "alerte_pct": dep.budget.alerte_pct}
        for dep in departements.values()
    ]


def lire_paliers(departements: Mapping[str, Departement], chemin: Path | None = None) -> dict[str, Any]:
    """Configuration des paliers, les usages des départements qui en dépendent et les manquants."""
    configures = modeles.charger_paliers(chemin)
    requis: dict[str, list[dict[str, str]]] = {palier: [] for palier in PALIERS}
    for dep in departements.values():
        for usage, palier in dep.modeles.items():
            requis[palier].append({"departement": dep.id, "code": dep.code, "usage": usage})
    return {
        "fichier": str(chemin or modeles.fichier_paliers()),
        "paliers": [
            {"nom": palier, "configuration": configures.get(palier), "requis_par": requis[palier]}
            for palier in PALIERS
        ],
        "manquants": [palier for palier in PALIERS if requis[palier] and palier not in configures],
    }


def ecrire_palier(nom: str, configuration: Any, par: str, chemin: Path | None = None) -> dict[str, Any]:
    """Associe un palier à un fournisseur et un modèle, après validation par `opsys.modeles`.

    Les champs texte sont épurés de leurs espaces ; un champ vide vaut absent (formulaire web).
    Un champ inconnu est refusé : le socle l'ignorerait, et une faute de frappe passerait inaperçue.
    """
    if not isinstance(par, str) or not par.strip():
        raise ValueError("la modification d'un palier doit être signée (par)")
    if not isinstance(configuration, Mapping):
        raise ValueError(f"palier {nom} : configuration objet attendue")
    inconnus = sorted(str(cle) for cle in configuration if cle not in CHAMPS_PALIER)
    if inconnus:
        raise ValueError(f"palier {nom} : champ inconnu {', '.join(inconnus)} (attendu : {', '.join(CHAMPS_PALIER)})")
    propre = {
        cle: valeur.strip() if isinstance(valeur, str) else valeur
        for cle, valeur in configuration.items()
        if valeur is not None and not (isinstance(valeur, str) and not valeur.strip())
    }
    paliers = modeles.charger_paliers(chemin)
    paliers[nom] = modeles.valider_palier(nom, propre)
    fichier = modeles.enregistrer_paliers(paliers, chemin, par=par)
    logger.info("palier %s → %s / %s par %s", nom, paliers[nom]["provider"], paliers[nom]["model"], par)
    return {"palier": nom, "configuration": paliers[nom], "par": par, "fichier": str(fichier)}
