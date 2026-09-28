"""Capacités d'agent du département M8 Analytics.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est réécrite.
`m8_rapport_metriques` compose la chaîne complète (validation → écriture au registre →
couche sémantique → XmR → rapport) en un seul appel, ce qui évite à l'agent plusieurs
allers-retours et garantit l'ordre des contrôles : aucun signal XmR n'est jamais calculé sur
un snapshot refusé, et aucune dérivation n'a lieu pour un metric_id non déclaré.

Registre de production (ADR-0009) : par défaut, `outils()` adosse le registre de snapshots au
stockage durable de l'instance (`opsys.stockage.maillons`, dans la transaction que
`Capacites.appeler` ouvre pour chaque appel d'outil) — `registre.py` reste pur (aucun import
`opsys`/SQLAlchemy) et ignore que ses maillons survivent au redémarrage : c'est cet adaptateur,
seul, qui fait le lien. Le paramètre `registre_cible` est le point d'injection : les tests
unitaires du département y passent explicitement un `registre.RegistreSnapshots()` EN MÉMOIRE
(aucune base montée), sans toucher au comportement par défaut utilisé par `charger_outils()` en
production.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import dictionnaire as dictionnaire_module
from . import digest as digest_module
from . import rapports, registre, semantique, validation, xmr

_SNAPSHOT = {
    "type": "object",
    "description": (
        "SnapshotModule {module_source, horodatage, valeurs}. valeurs est TOUJOURS du "
        "texte (PRD §5.2) : la conversion numérique n'a lieu que dans la couche sémantique."
    ),
}
_DICTIONNAIRE = {
    "type": "object",
    "description": (
        "Dictionnaire canonique compilé par m8_compiler_dictionnaire : "
        "{module_source: {metric_id: DefinitionMetrique}}."
    ),
}
_METRIQUE = {
    "type": "object",
    "description": "ValeurMetrique {metric_id, valeur, version_definition, fraicheur, n}.",
}
_SIGNAL = {
    "type": "object",
    "description": (
        "SignalXmR {metric_id, type_signal, valeur_observee, limite_naturelle_haute, "
        "limite_naturelle_basse, n}."
    ),
}
_ROLE = {"type": ["string", "null"]}
_METRIC_IDS_AUTORISES = {"type": ["array", "null"], "items": {"type": "string"}}


def compiler_dictionnaire(racine_modules: str) -> dict[str, Any]:
    dico, erreurs = dictionnaire_module.compiler_dictionnaire(racine_modules)
    return {"dictionnaire": dico, "erreurs": erreurs}


def valider_snapshot(snapshot: dict[str, Any], dictionnaire: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(validation.valider_snapshot(snapshot, dictionnaire))


def detecter_signal_xmr(
    metric_id: str, valeurs_historiques: list[float], n_minimal: int
) -> dict[str, Any]:
    return {"signal": xmr.detecter_signal(metric_id, valeurs_historiques, n_minimal)}


def construire_rapport(
    metriques: list[dict[str, Any]],
    signaux: list[dict[str, Any]],
    role: str | None = None,
    metric_ids_autorises: list[str] | None = None,
) -> dict[str, Any]:
    return rapports.construire_rapport(metriques, signaux, role, metric_ids_autorises)


def produire_digest_quotidien(signaux: list[dict[str, Any]]) -> dict[str, Any]:
    return digest_module.produire_digest_quotidien(signaux)


# ---------------------------------------------------------------------------
# Bus d'événements (ADR-0009 §3, PLAN T1.2-c) : consommateur de m4.travaux_termines
# ---------------------------------------------------------------------------
_MODULE_SOURCE_TRAVAUX = "m04-field-ops"


def _valeurs_travaux_termines(charge: dict[str, Any]) -> dict[str, str]:
    """Faits mesurables du WCT, en texte (SnapshotModule, PRD §5.2) : durée réelle, et type de
    travaux s'il est présent. Jamais un coût ni une marge — M8 ne les reçoit pas dans cet
    événement (mission department.yaml ; DEFINITION-PRODUIT.md §7 M8 : « M8 ne fait pas la
    comptabilité »)."""
    valeurs = {
        "m4_wct_id": charge["wct_id"],
        "m4_intervention_id": charge["intervention_id"],
        "m4_duree_reelle_minutes": str(charge["duree_reelle_minutes"]),
    }
    type_travaux = charge.get("type_travaux")
    if type_travaux is not None:
        valeurs["m4_type_travaux"] = type_travaux
    return valeurs


def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m4.travaux_termines` (ADR-0009 §3, DEPARTEMENTS.md « Événements ») :
    enregistre au registre des snapshots (production : adossé au stockage durable de l'instance,
    même table que `m8_rapport_metriques`) les faits mesurables du chantier terminé.

    Idempotent par `wct_id` : un maillon déjà enregistré pour ce wct_id (relivraison de
    l'événement, ou `repartir()` rejoué) n'est jamais dupliqué — no-op qui rend
    `deja_enregistre=True`.
    """
    registre_cible = registre.RegistreSnapshots(maillons=stockage.maillons("m08-analytics", "snapshots"))
    wct_id = charge["wct_id"]
    for maillon in registre_cible.lire():
        deja_source_m4 = maillon["module_source"] == _MODULE_SOURCE_TRAVAUX
        if deja_source_m4 and maillon["valeurs"].get("m4_wct_id") == wct_id:
            return {"enregistre": False, "deja_enregistre": True, "wct_id": wct_id}

    valeurs = _valeurs_travaux_termines(charge)
    registre_cible.ajouter({
        "module_source": _MODULE_SOURCE_TRAVAUX,
        "horodatage": charge["horodatage_completion"],
        "valeurs": valeurs,
    })
    return {
        "enregistre": True,
        "deja_enregistre": False,
        "wct_id": wct_id,
        "duree_reelle_minutes": charge["duree_reelle_minutes"],
        "type_travaux": charge.get("type_travaux"),
    }


def consommateurs() -> dict[str, Any]:
    """Types d'événements consommés par M8 (ADR-0009 §3) — voir `department.yaml:evenements.consomme`
    et `docs/architecture/DEPARTEMENTS.md` § Événements."""
    return {"m4.travaux_termines": _recevoir_travaux_termines}


def outils(registre_cible: registre.RegistreSnapshots | None = None) -> tuple[Outil, ...]:
    """Capacités exposées aux agents. Une instance de RegistreSnapshots par installation.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.RegistreSnapshots()` explicite
    (tests) reste en mémoire, jamais touché à la base.
    """
    if registre_cible is None:
        registre_cible = registre.RegistreSnapshots(maillons=stockage.maillons("m08-analytics", "snapshots"))

    def _historique_numerique(module_source: str, metric_id: str) -> list[float]:
        """Série chronologique (ordre du registre) des valeurs numériques d'un metric_id.

        Même règle de conversion que semantique.deriver_metrique : une valeur qui ne convertit
        pas en float est exclue du compte, jamais une erreur ni une valeur inventée.
        """
        valeurs: list[float] = []
        for maillon in registre_cible.lire():
            if maillon["module_source"] != module_source:
                continue
            if metric_id not in maillon["valeurs"]:
                continue
            try:
                valeurs.append(float(maillon["valeurs"][metric_id]))
            except (TypeError, ValueError):
                continue
        return valeurs

    def rapport_metriques(
        dictionnaire: dict[str, Any],
        snapshot: dict[str, Any],
        metric_ids: list[str],
        horodatage_reference: str,
        n_minimal: int,
        role: str | None = None,
        metric_ids_autorises: list[str] | None = None,
    ) -> dict[str, Any]:
        """Chaîne complète : validation → écriture registre → sémantique → XmR → rapport.

        Bloque avant d'écrire si le snapshot est refusé (etape="validation") ; bloque avant de
        dériver une métrique si son metric_id n'est pas déclaré par module_source dans le
        dictionnaire fourni (etape="definition"). Un rôle fourni sans metric_ids_autorises est un
        refus métier (ValueError, fail-closed — voir rapports.construire_rapport).
        """
        valide, verdict = validation.valider_snapshot(snapshot, dictionnaire)
        if not valide:
            return {"etape": "validation", "accepte": False, "verdict": verdict}

        registre_cible.ajouter(snapshot)

        module_source = snapshot["module_source"]
        metriques_module = dictionnaire.get(module_source, {})
        metriques: list[dict[str, Any]] = []
        signaux: list[dict[str, Any]] = []
        for metric_id in metric_ids:
            definition = metriques_module.get(metric_id)
            if definition is None:
                return {
                    "etape": "definition",
                    "accepte": False,
                    "verdict": f"REJ-METRIC-ID-NON-DEFINI:{metric_id}",
                }
            valeur_metrique = semantique.deriver_metrique(
                module_source, metric_id, definition, registre_cible, horodatage_reference
            )
            metriques.append(valeur_metrique)

            historique = _historique_numerique(module_source, metric_id)
            signal = xmr.detecter_signal(metric_id, historique, n_minimal)
            if signal is not None:
                signaux.append(signal)

        rapport = rapports.construire_rapport(metriques, signaux, role, metric_ids_autorises)
        return {"etape": "complet", "accepte": True, "rapport": rapport}

    return (
        Outil(
            nom="m8_rapport_metriques",
            description=(
                "Ingère un snapshot (validation puis écriture au registre), dérive les "
                "métriques demandées avec provenance, détecte les signaux XmR et construit un "
                "rapport filtré par rôle — de bout en bout. Bloque avant d'écrire si le "
                "snapshot est refusé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "dictionnaire": _DICTIONNAIRE,
                    "snapshot": _SNAPSHOT,
                    "metric_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "metric_id à dériver et surveiller (XmR) pour ce module_source.",
                    },
                    "horodatage_reference": {
                        "type": "string",
                        "description": "Instant de référence pour la fraîcheur (M8 n'a pas d'horloge).",
                    },
                    "n_minimal": {
                        "type": "integer",
                        "description": "Taille d'échantillon minimale avant DONNEES_INSUFFISANTES (aucun défaut).",
                    },
                    "role": _ROLE,
                    "metric_ids_autorises": _METRIC_IDS_AUTORISES,
                },
                "required": [
                    "dictionnaire",
                    "snapshot",
                    "metric_ids",
                    "horodatage_reference",
                    "n_minimal",
                ],
                "additionalProperties": False,
            },
            fonction=rapport_metriques,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m8_compiler_dictionnaire",
            description=(
                "Compile le dictionnaire canonique de métriques à partir des metrics/*.yaml "
                "présents sous une racine de départements ; refuse nommément une devise "
                "monétaire non CAD."
            ),
            parametres={
                "type": "object",
                "properties": {"racine_modules": {"type": "string"}},
                "required": ["racine_modules"],
                "additionalProperties": False,
            },
            fonction=compiler_dictionnaire,
        ),
        Outil(
            nom="m8_valider_snapshot",
            description=(
                "Valide la structure d'un snapshot contre le dictionnaire canonique, sans "
                "l'écrire au registre."
            ),
            parametres={
                "type": "object",
                "properties": {"snapshot": _SNAPSHOT, "dictionnaire": _DICTIONNAIRE},
                "required": ["snapshot", "dictionnaire"],
                "additionalProperties": False,
            },
            fonction=valider_snapshot,
        ),
        Outil(
            nom="m8_detecter_signal_xmr",
            description=(
                "Détecte un signal XmR (limites naturelles) sur un historique de valeurs déjà "
                "dérivées pour un metric_id ; DONNEES_INSUFFISANTES sous n_minimal."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "metric_id": {"type": "string"},
                    "valeurs_historiques": {"type": "array", "items": {"type": "number"}},
                    "n_minimal": {"type": "integer"},
                },
                "required": ["metric_id", "valeurs_historiques", "n_minimal"],
                "additionalProperties": False,
            },
            fonction=detecter_signal_xmr,
        ),
        Outil(
            nom="m8_construire_rapport",
            description=(
                "Assemble un RapportAnalytique à partir de métriques et signaux déjà calculés, "
                "filtré par rôle si fourni. Un rôle sans metric_ids_autorises est refusé "
                "(fail-closed, jamais une vue complète devinée)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "metriques": {"type": "array", "items": _METRIQUE},
                    "signaux": {"type": "array", "items": _SIGNAL},
                    "role": _ROLE,
                    "metric_ids_autorises": _METRIC_IDS_AUTORISES,
                },
                "required": ["metriques", "signaux"],
                "additionalProperties": False,
            },
            fonction=construire_rapport,
        ),
        Outil(
            nom="m8_produire_digest_quotidien",
            description=(
                "Assemble le digest quotidien déterministe à partir de signaux XmR déjà "
                "calculés (signaux actifs seulement, jamais DONNEES_INSUFFISANTES)."
            ),
            parametres={
                "type": "object",
                "properties": {"signaux": {"type": "array", "items": _SIGNAL}},
                "required": ["signaux"],
                "additionalProperties": False,
            },
            fonction=produire_digest_quotidien,
        ),
    )
