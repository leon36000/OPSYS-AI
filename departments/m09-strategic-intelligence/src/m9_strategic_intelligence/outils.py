"""Capacités d'agent du département M9 Strategic Intelligence.

M9 v1 est un harnais déterministe pur (PRD §0/§3.1) : aucun Council d'agents, aucun contenu
délibératif — il agrège les snapshots que les autres modules lui rapportent dans un état
consolidé (Business State Graph) et signale les contradictions internes, sans jamais inventer
ni recommander. `m9_etat_consolide` compose ingestion → écriture au registre → construction de
l'état consolidé (contradictions comprises) en un seul appel.

PLAN T3.2 (M9.5, briefing du matin) : `m9_produire_briefing_matin` compose la file du
propriétaire (`opsys.approbations.file_proprietaire`), les alertes M8 déjà reçues par le bus
(`m8.alerte_proposee`, `_recevoir_alerte_proposee`) et les faits déjà consolidés par M9 en un
gabarit déterministe (`briefing_matin.assembler_briefing_matin`, module pur). Boucle M8 → M9 des
preuves (ADR-0009 §3) : M9 ne lit jamais le registre M8 directement, seulement le bus.

Registre de production (ADR-0009) : par défaut, `outils()` adosse le registre de snapshots au
stockage durable de l'instance (`opsys.stockage.maillons`, dans la transaction que
`Capacites.appeler` ouvre pour chaque appel d'outil) — même convention que
m8_analytics/outils.py. `registre.py` reste pur (aucun import `opsys`/SQLAlchemy) et ignore que
ses maillons survivent au redémarrage : c'est cet adaptateur, seul, qui fait le lien. Le
paramètre `registre_cible` est le point d'injection : les tests unitaires du département y
passent explicitement un `registre.RegistreSnapshots()` EN MÉMOIRE (aucune base montée), sans
toucher au comportement par défaut utilisé par `charger_outils()` en production. `alertes_cible`
suit le même patron pour le registre durable des alertes M8 reçues (T3.2).
"""

from __future__ import annotations

from typing import Any

from opsys import approbations, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Outil, depuis_couple

from . import briefing_matin, contrats, rapport_strategique, registre, validation
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
_MAINTENANT = {
    "type": "string",
    "description": "Instant de référence RFC 3339 (M9 n'a pas d'horloge) — jamais l'instant réel.",
}


def valider_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(validation.valider_snapshot(snapshot))


def valider_rapport_strategique(rapport: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(rapport_strategique.valider_rapport_strategique(rapport))


# ---------------------------------------------------------------------------
# Bus d'événements (ADR-0009 §3, PLAN T3.2) : consommateur de m8.alerte_proposee
# ---------------------------------------------------------------------------
def _recevoir_alerte_proposee(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m8.alerte_proposee` (ADR-0009 §3, PLAN T3.2) : enregistre au registre durable
    des alertes M8 reçues par M9 (`stockage.maillons("m09-strategic-intelligence", "alertes_m8")`,
    même table que celle relue par `m9_lire_alertes_m8`/`m9_produire_briefing_matin`) — préférence
    explicite du PLAN pour un événement publié plutôt qu'une lecture directe du registre M8.

    Idempotent par `evenement_id` (même patron que `m8_analytics.outils._recevoir_travaux_termines`
    pour `wct_id`) : une relivraison (relivraison de l'événement, ou `repartir()` rejoué) n'ajoute
    jamais un second maillon — no-op qui rend `deja_recue=True`.
    """
    alertes_cible = stockage.maillons("m09-strategic-intelligence", "alertes_m8")
    evenement_id = charge["evenement_id"]
    for existante in alertes_cible:
        if existante["evenement_id"] == evenement_id:
            return {"enregistree": False, "deja_recue": True, "evenement_id": evenement_id}
    alertes_cible.append(dict(charge))
    return {"enregistree": True, "deja_recue": False, "evenement_id": evenement_id}


def consommateurs() -> dict[str, Any]:
    """Types d'événements consommés par M9 (ADR-0009 §3) — voir `department.yaml:evenements.consomme`
    et `docs/architecture/DEPARTEMENTS.md` § Événements."""
    return {"m8.alerte_proposee": _recevoir_alerte_proposee}


def outils(
    registre_cible: registre.RegistreSnapshots | None = None,
    alertes_cible: Any = None,
) -> tuple[Outil, ...]:
    """Capacités exposées aux agents. Une instance de RegistreSnapshots par installation.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.RegistreSnapshots()` explicite
    (tests) reste en mémoire, jamais touché à la base.

    `alertes_cible` (T3.2) : même patron pour le registre durable des alertes M8 reçues — `None`
    (défaut) l'adosse à `opsys.stockage.maillons("m09-strategic-intelligence", "alertes_m8")` ;
    une `list` explicite (tests) reste en mémoire.
    """
    if registre_cible is None:
        registre_cible = registre.RegistreSnapshots(
            maillons=stockage.maillons("m09-strategic-intelligence", "snapshots")
        )
    if alertes_cible is None:
        alertes_cible = stockage.maillons("m09-strategic-intelligence", "alertes_m8")

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

    def lire_alertes_m8() -> list[dict[str, Any]]:
        """Alertes M8 déjà reçues (`m8.alerte_proposee`), sans filtre — relecture pure, n'ingère
        rien de nouveau (même esprit que `lire_etat_consolide`)."""
        return [dict(alerte) for alerte in alertes_cible]

    def produire_briefing_matin(maintenant: str) -> dict[str, Any]:
        """Assemble le briefing du matin pour `maintenant` (RFC 3339, fourni par l'appelant —
        jamais l'horloge, T3.2) : file du propriétaire (`opsys.approbations.file_proprietaire`,
        TOUS les départements installés), alertes M8 déjà reçues par le bus, faits déjà consolidés
        par M9 pour la veille — relecture pure des trois sources, aucune ingestion, aucune
        écriture (T0). `stockage.transaction()` réutilise la transaction déjà ouverte par
        `executer_atomique` (ADR-0009) ou en ouvre une nouvelle si appelée hors de tout outil
        (tests avec une base durable montée) : jamais une lecture sans transaction cohérente.
        """
        with stockage.transaction() as cnx:
            decisions = approbations.file_proprietaire(cnx, charger_departements())
        alertes = [dict(alerte) for alerte in alertes_cible]
        faits = registre_cible.lire()
        return briefing_matin.assembler_briefing_matin(maintenant, decisions, alertes, faits)

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
        Outil(
            nom="m9_lire_alertes_m8",
            description=(
                "Alertes de qualité proposées par M8 déjà reçues via le bus (m8.alerte_proposee), "
                "sans filtre — relecture pure du registre durable des alertes M9, n'ingère rien."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=lire_alertes_m8,
        ),
        Outil(
            nom="m9_produire_briefing_matin",
            description=(
                "Assemble le briefing du matin (décisions en attente de la file du propriétaire, "
                "alertes M8 du jour, faits du bus consolidés la veille, manques) pour un instant "
                "de référence fourni — relecture pure de trois sources déjà à jour, aucune "
                "ingestion, aucun chiffre ni texte inventé ; une section sans donnée est déclarée "
                "vide, jamais remplie."
            ),
            parametres={
                "type": "object",
                "properties": {"maintenant": _MAINTENANT},
                "required": ["maintenant"],
                "additionalProperties": False,
            },
            fonction=produire_briefing_matin,
        ),
    )
