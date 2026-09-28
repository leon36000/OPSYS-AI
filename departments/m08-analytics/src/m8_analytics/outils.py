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

Même patron pour le registre DURABLE des définitions de métriques (T3.1, `registre_metriques.py`)
: `definitions_cible` est le second point d'injection (`opsys.stockage.maillons("m08-analytics",
"definitions_metriques")` par défaut, une liste en mémoire dans les tests), utilisé par
`m8_enregistrer_definition_metrique`, `m8_resoudre_definition_metrique` et
`m8_evaluer_qualite_metrique`.
"""

from __future__ import annotations

from typing import Any

from opsys import evenements, stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import alertes, qualite, rapports, registre, registre_metriques, semantique, validation, xmr
from . import dictionnaire as dictionnaire_module
from . import digest as digest_module

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
_DEFINITION_REGISTRE = {
    "type": "object",
    "description": (
        "DefinitionMetriqueRegistre {metric_id, departement_proprietaire, unite (validée "
        "contre le dictionnaire ISO 4217), source, fraicheur_attendue_jours, "
        "regles_qualite: {plage_min, plage_max}} (T3.1)."
    ),
}


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


# ---------------------------------------------------------------------------
# Bus d'événements (ADR-0009 §3, PLAN T3.2) : M9 a besoin des alertes proposées par M8 pour son
# briefing du matin. Plutôt qu'une lecture directe du registre M8 par M9 (refusée par PLAN T3.2 —
# préférer un événement), M8 publie chaque AlerteProposee sur le bus (m8.alerte_proposee) ; M9 la
# consomme de façon idempotente (m9_strategic_intelligence.outils._recevoir_alerte_proposee).
# ---------------------------------------------------------------------------
_DEPARTEMENT = "m08-analytics"


def _publier_alerte_proposee(metric_id: str, alerte: dict[str, Any], horodatage_reference: str) -> None:
    """Publie l'AlerteProposee sur le bus, DANS LA MÊME TRANSACTION que l'évaluation qui vient de
    la produire (`evenements.publier` ouvre un point de sauvegarde sur la transaction déjà ouverte
    par `executer_atomique`, jamais une transaction indépendante — même patron que
    `m4_field_ops.outils.completer_intervention` pour `m4.travaux_termines`).

    `evenement_id` déterministe (metric_id + type_alerte + horodatage_reference) : une
    réévaluation identique republie le même id, donc un no-op de l'outbox (ADR-0009 §3) — jamais
    un doublon pour la même alerte le même jour de référence.

    Gardé par `stockage.connexion_courante() is not None` (même garde que
    `m4_field_ops.outils.completer_intervention` et `m6_material_control.outils.
    _registre_de_l_appel`) : seule la production (appel enveloppé par `executer_atomique`/
    `Capacites.appeler`) publie ; les tests unitaires de ce fichier, qui appellent
    `m8_evaluer_qualite_metrique` via `opsys.outils.executer` (sans transaction), ne touchent
    jamais la base — publier quand même y ouvrirait une transaction hors de propos pour une
    alerte qui n'existe que dans un dict Python local, jamais dans `evenements_sortants`. Ceci ne
    change ni la réponse ni l'autonomie T0 de `m8_evaluer_qualite_metrique` (elle n'exécute
    toujours rien et n'appelle toujours aucun autre département — elle publie un FAIT, comme le
    fait déjà M6 pour `m6.variance_chantier` depuis un outil T1) ;
    `test_paliers_t3_1_coherents_avec_departements_md` verrouille ce choix.
    """
    if stockage.connexion_courante() is None:
        return
    ident = f"m8-alerte-{metric_id}-{alerte['type_alerte']}-{horodatage_reference}"
    charge = {
        "evenement_id": ident,
        "metric_id": metric_id,
        "type_alerte": alerte["type_alerte"],
        "quoi": alerte["quoi"],
        "a_qui": alerte["a_qui"],
        "pourquoi": alerte["pourquoi"],
        "preuve": alerte["preuve"],
        "source": alerte["source"],
        "horodatage_reference": horodatage_reference,
    }
    evenements.publier("m8.alerte_proposee", _DEPARTEMENT, charge, evenement_id=ident)


def outils(
    registre_cible: registre.RegistreSnapshots | None = None,
    definitions_cible: Any = None,
) -> tuple[Outil, ...]:
    """Capacités exposées aux agents. Une instance de RegistreSnapshots par installation.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.RegistreSnapshots()` explicite
    (tests) reste en mémoire, jamais touché à la base.

    `definitions_cible` (T3.1) : même patron pour le registre durable des définitions de
    métriques — `None` (défaut) l'adosse à `opsys.stockage.maillons("m08-analytics",
    "definitions_metriques")` ; une `list` explicite (tests) reste en mémoire.
    """
    if registre_cible is None:
        registre_cible = registre.RegistreSnapshots(maillons=stockage.maillons("m08-analytics", "snapshots"))
    if definitions_cible is None:
        definitions_cible = stockage.maillons("m08-analytics", "definitions_metriques")

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

    def enregistrer_definition_metrique(definition: dict[str, Any]) -> dict[str, Any]:
        return registre_metriques.enregistrer_definition(definition, definitions_cible)

    def resoudre_definition_metrique(metric_id: str) -> dict[str, Any]:
        definition = registre_metriques.resoudre(metric_id, definitions_cible)
        if definition is None:
            return {
                "trouvee": False,
                "verdict": f"REJ-DEFINITION-METRIQUE-INCONNUE:{metric_id}",
                "definition": None,
            }
        return {"trouvee": True, "verdict": None, "definition": definition}

    def evaluer_qualite_metrique(metric_id: str, horodatage_reference: str) -> dict[str, Any]:
        """Résout la définition enregistrée, dérive la valeur courante (sémantique.py, contre le
        même registre de snapshots que `rapport_metriques`), puis évalue présence, fraîcheur et
        plage — PUREMENT à partir de `horodatage_reference` fourni (qualite.py ne lit jamais
        l'horloge). Propose 0 à 2 alertes structurées (jamais exécutées, jamais un appel à un
        autre département) ; réponse compacte, aucun historique complet renvoyé.

        Chaque alerte proposée est aussi PUBLIÉE sur le bus (`m8.alerte_proposee`, PLAN T3.2,
        `_publier_alerte_proposee`) pour que M9 la consomme sans lire directement le registre M8
        — seulement en production (garde `stockage.connexion_courante`) ; la réponse ci-dessous et
        l'autonomie T0 de cet outil restent inchangées (voir `_publier_alerte_proposee`).
        """
        definition = registre_metriques.resoudre(metric_id, definitions_cible)
        if definition is None:
            return {
                "metric_id": metric_id,
                "definition_trouvee": False,
                "verdict": f"REJ-DEFINITION-METRIQUE-INCONNUE:{metric_id}",
                "alertes_proposees": [],
            }

        valeur_metrique = semantique.deriver_metrique(
            definition["departement_proprietaire"], metric_id, definition, registre_cible, horodatage_reference
        )

        alertes_proposees: list[dict[str, Any]] = []
        absence = qualite.evaluer_presence(metric_id, valeur_metrique["n"], valeur_metrique["valeur"])
        if absence is not None:
            alertes_proposees.append(alertes.proposer_action(absence, definition))
        else:
            perimee = qualite.evaluer_fraicheur(
                metric_id, valeur_metrique["fraicheur"], definition["fraicheur_attendue_jours"]
            )
            if perimee is not None:
                alertes_proposees.append(alertes.proposer_action(perimee, definition))

            regles = definition["regles_qualite"]
            hors_plage = qualite.evaluer_plage(
                metric_id, valeur_metrique["valeur"], regles["plage_min"], regles["plage_max"]
            )
            if hors_plage is not None:
                alertes_proposees.append(alertes.proposer_action(hors_plage, definition))

        for alerte in alertes_proposees:
            _publier_alerte_proposee(metric_id, alerte, horodatage_reference)

        return {
            "metric_id": metric_id,
            "definition_trouvee": True,
            "verdict": None,
            "n": valeur_metrique["n"],
            "valeur": valeur_metrique["valeur"],
            "fraicheur_jours": valeur_metrique["fraicheur"],
            "alertes_proposees": alertes_proposees,
        }

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
        Outil(
            nom="m8_enregistrer_definition_metrique",
            description=(
                "Enregistre (idempotent) une définition dans le registre durable des métriques "
                "surveillées par M8 : département propriétaire, unité validée contre le "
                "dictionnaire (garde ISO 4217), source, fraîcheur attendue, règles de qualité. "
                "Rejoue le même enregistrement sans faire grossir le registre ; refuse nommément "
                "une structure invalide, un département inconnu ou une devise non CAD."
            ),
            parametres={
                "type": "object",
                "properties": {"definition": _DEFINITION_REGISTRE},
                "required": ["definition"],
                "additionalProperties": False,
            },
            fonction=enregistrer_definition_metrique,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m8_resoudre_definition_metrique",
            description=(
                "Dernière définition connue pour un metric_id dans le registre durable, ou un "
                "verdict nommé si aucune n'a jamais été enregistrée."
            ),
            parametres={
                "type": "object",
                "properties": {"metric_id": {"type": "string"}},
                "required": ["metric_id"],
                "additionalProperties": False,
            },
            fonction=resoudre_definition_metrique,
        ),
        Outil(
            nom="m8_evaluer_qualite_metrique",
            description=(
                "Évalue la qualité et la fraîcheur d'une métrique déjà enregistrée (présence, "
                "âge vs fraîcheur attendue, plage), à partir d'un horodatage de référence fourni "
                "— jamais l'horloge interne — et propose une alerte structurée "
                "(quoi/à qui/pourquoi/preuve) par problème détecté. Ne l'exécute jamais et n'agit "
                "sur aucun autre département ; publie chaque alerte sur le bus (m8.alerte_proposee) "
                "pour que d'autres départements (M9) la consomment sans lire le registre M8."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "metric_id": {"type": "string"},
                    "horodatage_reference": {
                        "type": "string",
                        "description": "Instant de référence pour la fraîcheur (M8 n'a pas d'horloge).",
                    },
                },
                "required": ["metric_id", "horodatage_reference"],
                "additionalProperties": False,
            },
            fonction=evaluer_qualite_metrique,
        ),
    )
