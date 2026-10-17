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

Mesure d'un chantier terminé (PLAN T1.5-d, `mesures_chantier.py`) : M8 reçoit quatre faits par le bus
(`m4.travaux_termines`, `m3.devis_accepte`, `m6.variance_chantier`, `m5.rentabilite_chantier`), les range dans
le registre `faits_chantier` (idempotent, un fait par clé) et mesure le chantier à CHAQUE arrivée (l'ordre de
livraison n'est pas garanti). Les métriques sont celles de `metrics/m8-metrics.v1.yaml` ; une entrée
absente donne « non calculable, manque X ». Un seuil franchi (`department.yaml`,
`configuration.seuils_alerte`) publie `m8.alerte_proposee` pour M9 ; sans seuil, un signal « seuil à
configurer ». `m8_lire_mesures_chantier` et `m8_performance_equipe` sont T0 et réservés au rôle
admin : marges et détail par technicien ne vont jamais à un employé.

Entonnoir commercial et vue exécutive (PLAN T4.19, `entonnoir.py`, `vue_executive.py`) : M8 reçoit aussi les faits de
M2 (`m2.client_associe`, `m2.lead_assigne`) et de M3 (`m3.devis_envoye`, `m3.devis_accepte`, `m3.devis_sans_reponse`),
les range dans le registre `faits_entonnoir` (idempotent, un fait par lead ou par devis) et mesure l'entonnoir au moment
de la lecture, jamais à l'arrivée : c'est un état du moment, pas un chantier. `m8_lire_vue_executive` (T0, admin) y
ajoute la marge réelle que M5 a publiée, le stock à commander que M6 met à la file du propriétaire et le cash libre.
M8 ne recalcule aucun montant de M5 ; un rôle d'appareil autre qu'`admin` est refusé dans le code, en plus de la portée
du core.

Cash libre (PLAN T4.19-b, `cash_libre.py`) : M5 publie le cash libre qu'il a constaté (`m5.cash_libre_constate`, à la
demande de l'admin) ; M8 le consomme, range chaque constat au registre `faits_cash_libre` (idempotent, un fait par
identifiant d'événement : la charge telle que M5 l'a publiée) et la vue exécutive montre le DERNIER (le plus grand
`sequence`), tel quel, avec son âge. L'âge se calcule avec l'argument facultatif `aujourd_hui` (AAAA-MM-JJ) : M8 n'a
pas d'horloge, il ne devine jamais la date ; sans lui, l'âge est « non calculable ». Aucun constat reçu : « manque ».

Mesure par contenu (PLAN T4.17-e, `contenus.py`, `vue_contenus.py`) : M8 reçoit `m7.contenu_exporte` (les contenus
qui existent, avec leur clé `utm_content`) et `m1.lead_qualifie` (le lead et la clé qu'il portait), les range au
registre `faits_contenus` (idempotent, un fait par contenu ou par lead ; jamais un contact, une ville ni un texte)
et compte, à la lecture, les leads puis les devis (faits de l'entonnoir) par contenu. `m8_lire_mesures_contenus`
(T0, admin) rend les métriques gouvernées de `metrics/m8-contenus.v1.yaml`, une ligne par contenu, par pages sous
la limite du socle. Impressions et clics : aucune source, « non calculable » et jamais un zéro.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

from opsys import approbations, contexte, evenements, identite, jetons, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import (
    alertes,
    cash_libre,
    contenus,
    entonnoir,
    mesures_chantier,
    provenance_m5,
    qualite,
    rapports,
    registre,
    registre_metriques,
    semantique,
    validation,
    vue_contenus,
    vue_executive,
    xmr,
)
from . import dictionnaire as dictionnaire_module
from . import digest as digest_module
from . import encodage as encodage_module

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
_ALERTE = {
    "type": "object",
    "description": "AlerteProposee {type_alerte, quoi, a_qui, pourquoi, preuve, source} (alertes.proposer_action).",
}
_COMPOSANTES = {
    "type": ["object", "null"],
    "description": (
        "T3.1-suite : {metric_id_composante: coefficient signé} pour un contrôle de cohérence "
        "optionnel (ex. {\"m5_revenu_cad\": 1.0, \"m5_cout_cad\": -1.0} pour une marge). Chaque "
        "valeur de composante est re-dérivée par M8 depuis le registre, jamais transmise brute. "
        "Fourni seulement avec tolerance_coherence, jamais l'un sans l'autre."
    ),
}
_TOLERANCE_COHERENCE = {
    "type": ["number", "null"],
    "description": "Écart absolu accepté entre la valeur observée et la somme pondérée de composantes.",
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


def produire_digest_quotidien(
    signaux: list[dict[str, Any]], alertes_proposees: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return digest_module.produire_digest_quotidien(signaux, alertes_proposees)


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


# ---------------------------------------------------------------------------
# Mesure d'un chantier terminé (PLAN T1.5-d) : faits reçus, mesures, seuils, alertes
# ---------------------------------------------------------------------------
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
_NOM_REGISTRE_FAITS = "faits_chantier"
_NOM_REGISTRE_ENTONNOIR = "faits_entonnoir"
_NOM_REGISTRE_CONTENUS = "faits_contenus"
_NOM_REGISTRE_CASH_LIBRE = "faits_cash_libre"
_M6 = "m06-material-control"
# `Capacites._tronquer` mesure `{"ok": true, "resultat": ...}` : 25 caractères d'enveloppe, plus une marge.
# Sous ce budget (la limite de sortie du socle moins cette réserve), une réponse n'est jamais tronquée.
BUDGET_SORTIE = jetons.LIMITE_SORTIE_DEFAUT - 100
_ROLE_ADMIN = identite.Role.ADMIN.value


def _configuration() -> dict[str, Any]:
    """`department.yaml/configuration` (même source que M6 pour ses seuils : le manifeste, que
    l'admin peut éditer sans toucher au code). Absente : dictionnaire vide, jamais un défaut."""
    donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    configuration = donnees.get("configuration")
    return configuration if isinstance(configuration, dict) else {}


def _seuils_alerte() -> dict[str, Any]:
    """Seuils d'alerte configurés, `{metric_id: {sens, valeur}}` ; vide tant qu'aucun n'est fixé
    (fail-closed : `mesures_chantier.evaluer_seuils` répond alors « seuil à configurer »)."""
    seuils = _configuration().get("seuils_alerte")
    return seuils if isinstance(seuils, dict) else {}


def _seuils_entonnoir() -> dict[str, Any]:
    """Seuils de l'entonnoir configurés, `{metric_id: {sens, valeur}}` ; vide tant qu'aucun n'est fixé (GATE
    NATHAN : `entonnoir.evaluer_seuils` répond alors « seuil à configurer », jamais une valeur par défaut)."""
    seuils = _configuration().get("seuils_entonnoir")
    return seuils if isinstance(seuils, dict) else {}


def _chantiers_minimum() -> Any:
    """Nombre minimal de chantiers mesurés pour qu'un écart par technicien soit dit suffisant ;
    `None` tant qu'il n'est pas configuré (jamais un minimum supposé)."""
    equipe = _configuration().get("performance_equipe")
    return equipe.get("chantiers_minimum") if isinstance(equipe, dict) else None


def _admin_authentifie() -> bool:
    """Vrai seulement pour un appel d'appareil dont l'identité authentifiée est celle d'une
    personne active portant encore le rôle `admin` (revérifiée en base, comme M3 pour sa vue par
    rôle). Sans identité (agent, console, test) ou avec un autre rôle : faux, donc aucun détail
    nominatif — fail-closed."""
    appelante = contexte.identite_appelante()
    if appelante is None or appelante.role != _ROLE_ADMIN:
        return False
    cnx = stockage.connexion_courante()
    if cnx is None:
        return False
    personne = identite.personne_active(cnx, appelante.personne)
    return personne is not None and appelante.role in personne.roles


def _exiger_admin_pour_appareil() -> None:
    """Refuse, AVANT toute lecture, tout appel d'appareil qui n'est pas celui d'un `admin` authentifié : le socle
    n'applique pas `Outil.roles_appareil` à un outil de lecture (T0) hors du core, et la vue exécutive porte marges,
    stock et carnet de toute l'entreprise (§8.16 : un employé ne voit ni marges, ni finances globales). Sans identité
    d'appareil (un agent, la console : la voie des agents), rien à refuser ici ; avec une identité, le rôle du jeton
    est REVÉRIFIÉ en base (personne active, rôle encore porté), jamais cru sur parole : hors transaction, refus."""
    if contexte.identite_appelante() is None:
        return
    if not _admin_authentifie():
        raise ValueError(
            "REJ-IDENTITE-APPAREIL-INVALIDE : la vue exécutive est réservée à l'admin authentifié "
            "(personne active portant encore le rôle admin) ; aucun autre rôle d'appareil n'y a accès"
        )


def _lire_attentes_m6() -> tuple[list[dict[str, Any]] | None, str | None]:
    """Ce que M6 met à la file du propriétaire (`attentes()`, PLAN T1.5-d) : `(attentes, None)`, ou `(None, raison)`
    quand M6 ne peut pas être lu. C'est le mécanisme du socle (`approbations.attentes_departements`, celui de M9), pas
    un import de M6 : M8 ne connaît ni son registre, ni ses seuils, ni ses quantités. Seul M6 est appelé. Dans la
    transaction de l'outil seulement."""
    cnx = stockage.connexion_courante()
    if cnx is None:
        return None, "aucune base jointe : les attentes de M6 ne se lisent que dans la transaction d'un outil"
    m6 = charger_departements().get(_M6)
    if m6 is None:
        return None, f"{_M6} n'est pas installé sur cette instance"
    attentes, illisibles = approbations.attentes_departements(cnx, {_M6: m6})
    if illisibles:
        return None, f"les attentes de {_M6} n'ont pas pu être lues (voir le journal du moteur)"
    return attentes, None


def _ajouter_fait_si_nouveau(faits_cible: Any, fait: dict[str, Any], cles: tuple[str, ...]) -> bool:
    """Ajoute `fait` au registre s'il n'y figure pas déjà (mêmes valeurs pour `cles`, même type) :
    une relivraison de l'événement ou un rejeu de `repartir()` n'ajoute jamais un second maillon."""
    for existant in faits_cible:
        if existant.get("type_entree") == fait["type_entree"] and all(
            existant.get(cle) == fait.get(cle) for cle in cles
        ):
            return False
    faits_cible.append(fait)
    return True


def _situation_chantier(wct_id: str, faits_cible: Any) -> dict[str, Any] | None:
    """Mesures, situation face aux seuils et alertes à publier d'un chantier, d'après les faits
    reçus jusqu'ici ; `None` si le chantier est inconnu (aucun `m4.travaux_termines` reçu).
    Lecture pure : ne publie rien."""
    faits = mesures_chantier.assembler_faits(wct_id, list(faits_cible))
    if faits is None:
        return None
    definitions = mesures_chantier.charger_definitions()
    mesures = mesures_chantier.mesurer_chantier(faits, definitions)
    evaluations = mesures_chantier.evaluer_seuils(mesures, _seuils_alerte())
    charges = mesures_chantier.charges_alertes(
        wct_id, mesures, evaluations, definitions, faits["wct"]["horodatage_completion"]
    )
    return {"faits": faits, "mesures": mesures, "evaluations": evaluations, "charges": charges}


def _publier_charges_mesure(charges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Publie chaque alerte de mesure sur le bus (`m8.alerte_proposee`), dans la transaction du
    consommateur qui vient de les produire. L'identifiant est déterministe : republier la même
    alerte rejoue la première enveloppe publiée (`nouvelle` le dit). Un seuil ou un fait nouveau
    peut changer la remesure ; il ne réécrit pas la preuve de l'alerte déjà publiée."""
    publiees = []
    for charge in charges:
        nouvelle = not evenements.deja_publie(charge["evenement_id"])
        premiere = evenements.charge_publiee("m8.alerte_proposee", charge["evenement_id"])
        evenements.publier(
            "m8.alerte_proposee", _DEPARTEMENT, premiere if premiere is not None else charge,
            evenement_id=charge["evenement_id"],
        )
        publiees.append({
            "evenement_id": charge["evenement_id"], "type_alerte": charge["type_alerte"],
            "metric_id": charge["metric_id"], "nouvelle": nouvelle,
        })
    return publiees


def _mesurer_et_publier(wct_id: str, faits_cible: Any) -> dict[str, Any]:
    """Mesure le chantier avec les faits DÉJÀ reçus et publie ses alertes. Appelée à chaque fait
    (WCT, devis, variance) : l'ordre de livraison du bus n'est pas garanti, et une mesure devenue
    calculable ne doit jamais attendre un autre événement. Rend un petit résumé : ce qui est
    calculé, ce qui manque (et où), les seuils à configurer et les alertes."""
    situation = _situation_chantier(wct_id, faits_cible)
    if situation is None:
        return {
            "wct_id": wct_id, "mesure": False,
            "raison": "chantier inconnu : aucun m4.travaux_termines reçu pour ce wct_id",
        }
    mesures = situation["mesures"]
    return {
        "wct_id": wct_id,
        "mesure": True,
        "calculees": [m["metric_id"] for m in mesures if m["statut"] == mesures_chantier.STATUT_CALCULEE],
        "non_calculables": [
            {"metric_id": m["metric_id"], "manque": [manque["champ"] for manque in m["manque"]]}
            for m in mesures if m["statut"] == mesures_chantier.STATUT_NON_CALCULABLE
        ],
        "seuils_a_configurer": [
            e["metric_id"] for e in situation["evaluations"]
            if e["statut"] in (mesures_chantier.SEUIL_A_CONFIGURER, mesures_chantier.SEUIL_INVALIDE)
        ],
        "alertes": _publier_charges_mesure(situation["charges"]),
    }


def _copie_snapshots_valide(maillons) -> registre.RegistreSnapshots:
    """Une seule lecture native, validée avant calcul du prochain maillon."""
    try:
        copie = registre.RegistreSnapshots(maillons=registre.RegistreSnapshots(maillons).lire())
        valide, _ = copie.valider_chaine()
        valide = valide and all(
            type(maillon["index"]) is int and maillon["index"] == index
            for index, maillon in enumerate(copie.lire())
        )
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        valide = False
    if valide is not True:
        raise ValueError("REJ-SNAPSHOT-CHAINE-INVALIDE : vérifier le registre M8 avant ajout")
    return copie


def _ajouter_snapshot_durable(maillons, copie, snapshot):
    maillon, _ = copie.ajouter(snapshot)
    # Le stockage natif refuse le rang périmé et laisse la transaction annuler
    # l'appel. Le répartiteur conserve alors l'événement et peut le rejouer.
    maillons.append(maillon, rang_attendu=maillon["index"])


def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m4.travaux_termines` (ADR-0009 §3, DEPARTEMENTS.md « Événements ») : deux
    écritures indépendantes, chacune idempotente par `wct_id`, puis la mesure du chantier.

    1. Le registre des snapshots (production : adossé au stockage durable de l'instance, même
       table que `m8_rapport_metriques`) reçoit les faits mesurables du chantier terminé : durée
       réelle, type de travaux. Un maillon déjà enregistré pour ce wct_id (relivraison, ou
       `repartir()` rejoué) n'est jamais dupliqué (`deja_enregistre=True`). Aucun coût, aucune marge.
    2. Le registre `faits_chantier` reçoit le fait `wct` (technicien, devis lié, durée réelle),
       d'où M8 mesure le chantier (PLAN T1.5-d) : temps réel contre prévu, quand M3 a fourni la
       durée estimée du devis accepté, sinon « non calculable, manque duree_estimee_minutes ».
    """
    maillons = stockage.maillons(_DEPARTEMENT, "snapshots")
    registre_cible = _copie_snapshots_valide(maillons)
    wct_id = charge["wct_id"]
    deja_enregistre = any(
        maillon["module_source"] == _MODULE_SOURCE_TRAVAUX and maillon["valeurs"].get("m4_wct_id") == wct_id
        for maillon in registre_cible.lire()
    )
    if not deja_enregistre:
        _ajouter_snapshot_durable(maillons, registre_cible, {
            "module_source": _MODULE_SOURCE_TRAVAUX,
            "horodatage": charge["horodatage_completion"],
            "valeurs": _valeurs_travaux_termines(charge),
        })

    faits_cible = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FAITS)
    _ajouter_fait_si_nouveau(faits_cible, mesures_chantier.fait_wct(charge), ("wct_id",))

    resume: dict[str, Any] = {"enregistre": not deja_enregistre, "deja_enregistre": deja_enregistre, "wct_id": wct_id}
    if not deja_enregistre:
        resume["duree_reelle_minutes"] = charge["duree_reelle_minutes"]
        resume["type_travaux"] = charge.get("type_travaux")
    resume["mesures"] = _mesurer_et_publier(wct_id, faits_cible)
    return resume


def _recevoir_devis_accepte(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m3.devis_accepte` : le prévu du chantier (prix et coût arrêtés par M3, et la
    durée estimée si M3 la fournit). Le devis précède normalement le chantier, mais le bus ne le
    garantit pas : chaque chantier déjà terminé qui pointe vers ce devis est remesuré. Le même événement
    porte aussi le devis accepté de l'entonnoir (T4.19 : le prix total seulement, jamais le coût), rangé au
    registre `faits_entonnoir` : une seule fonction par type consommé."""
    devis_id = charge["devis_id"]
    faits_cible = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FAITS)
    enregistre = _ajouter_fait_si_nouveau(faits_cible, mesures_chantier.fait_devis(charge), ("devis_id",))
    chantiers = [
        _mesurer_et_publier(wct_id, faits_cible)
        for wct_id in mesures_chantier.wcts_du_devis(list(faits_cible), devis_id)
    ]
    dans_entonnoir = _ranger_fait_entonnoir(entonnoir.fait_devis_accepte(charge))
    return {
        "enregistre": enregistre, "deja_enregistre": not enregistre, "devis_id": devis_id, "chantiers": chantiers,
        "entonnoir": {"enregistre": dans_entonnoir, "deja_enregistre": not dans_entonnoir},
    }


def _recevoir_variance_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m6.variance_chantier` : le verdict d'écart de matériaux de M6, repris tel quel
    (M8 le mesure, ne le recalcule pas). M6 publie un événement par statut : chacun est enregistré
    une fois ; `evaluee` est terminal et l'emporte à la mesure."""
    wct_id = charge["wct_id"]
    faits_cible = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FAITS)
    enregistre = _ajouter_fait_si_nouveau(
        faits_cible, mesures_chantier.fait_variance(charge), ("wct_id", "statut_variance")
    )
    return {
        "enregistre": enregistre, "deja_enregistre": not enregistre, "wct_id": wct_id,
        "statut_variance": charge["statut_variance"], "mesures": _mesurer_et_publier(wct_id, faits_cible),
    }


def _recevoir_rentabilite_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m5.rentabilite_chantier` : la marge réelle du chantier, TELLE QUE M5 l'a chiffrée (M8 ne
    fait pas la comptabilité), rangée dans `faits_chantier` sous la forme que `mesures_chantier.py` attend
    (`fait_rentabilite`), puis le chantier est remesuré.

    Un fait par (`wct_id`, `sequence`) : une relivraison n'ajoute rien, et le fait de plus grand `sequence` est
    l'état courant, quel que soit l'ordre de livraison. Coût réel complet et facture connue : la marge réelle
    (et ses écarts) devient calculable. Sinon M5 n'en porte aucune (le catalogue le refuse) : la mesure reste
    « non calculable, manque marge_reelle_cad » avec les codes de ce que M5 n'a pas pu chiffrer. Les seuils
    restent ceux de `department.yaml` (vides par défaut : rappel « seuil à configurer », jamais une alerte
    inventée)."""
    wct_id = charge["wct_id"]
    faits_cible = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FAITS)
    enregistre = _ajouter_fait_si_nouveau(
        faits_cible, mesures_chantier.fait_rentabilite(charge), ("wct_id", "sequence")
    )
    return {
        "enregistre": enregistre, "deja_enregistre": not enregistre, "wct_id": wct_id,
        "sequence": charge["sequence"], "verdict": charge["verdict"],
        "mesures": _mesurer_et_publier(wct_id, faits_cible),
    }


def _ranger_fait_entonnoir(fait: dict[str, Any]) -> bool:
    """Range un fait de l'entonnoir au registre `faits_entonnoir` s'il n'y est pas déjà : un fait par lead ou par devis
    (`entonnoir.cles_unicite`). Une relivraison de l'événement, ou un rejeu du répartiteur, n'ajoute jamais un second
    fait. Rend vrai s'il vient d'être ajouté."""
    return _ajouter_fait_si_nouveau(
        stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_ENTONNOIR), fait, entonnoir.cles_unicite(fait["type_entree"])
    )


def _recevoir_fait_entonnoir(fait: dict[str, Any]) -> dict[str, Any]:
    """Range le fait et rend le petit résumé du reçu du bus : jamais un contact, un prix ou un nom, seulement
    l'identifiant du lead ou du devis et si le fait était déjà connu."""
    cle = entonnoir.cles_unicite(fait["type_entree"])[0]
    enregistre = _ranger_fait_entonnoir(fait)
    return {"enregistre": enregistre, "deja_enregistre": not enregistre, cle: fait[cle]}


def _recevoir_client_associe(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m2.client_associe` (PLAN T4.19) : le lead existe chez M2 depuis cet instant, ce qui fait l'arrivée
    d'où part le délai jusqu'à l'acceptation. Le `client_id` (empreinte du contact) n'est pas gardé."""
    return _recevoir_fait_entonnoir(entonnoir.fait_lead_recu(charge))


def _recevoir_lead_assigne(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m2.lead_assigne` (PLAN T4.19) : M2 a qualifié le lead. Le propriétaire du lead n'est pas gardé.

    Seul le rang 1 est une qualification. Un fait qui porte `rang` (2 ou plus, schéma du catalogue) est une
    RÉASSIGNATION (PLAN T1.4-m) : il est reçu et ignoré, même s'il arrive avant le rang 1 (lead qualifié avant
    T1.4-k2, réassigné, puis republié), pour que l'instant de qualification ne soit jamais celui d'une réassignation."""
    if "rang" in charge:
        return {"enregistre": False, "reassignation_ignoree": True, "lead_id": charge["lead_id"]}
    return _recevoir_fait_entonnoir(entonnoir.fait_lead_qualifie(charge))


def _recevoir_devis_envoye(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m3.devis_envoye` (PLAN T4.19) : le propriétaire a approuvé l'envoi (jamais un montant)."""
    return _recevoir_fait_entonnoir(entonnoir.fait_devis_envoye(charge))


def _recevoir_devis_sans_reponse(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m3.devis_sans_reponse` (PLAN T4.19) : le constat de M3, repris tel quel, sans recalculer son
    délai de relance ni sa date."""
    return _recevoir_fait_entonnoir(entonnoir.fait_devis_sans_reponse(charge))


def _ranger_fait_contenu(fait: dict[str, Any]) -> bool:
    """Range un fait de la mesure par contenu au registre `faits_contenus` s'il n'y est pas déjà : un fait par contenu
    ou par lead (`contenus.cles_unicite`). Une relivraison de l'événement, ou un rejeu du répartiteur, n'ajoute jamais
    un second fait. Rend vrai s'il vient d'être ajouté."""
    return _ajouter_fait_si_nouveau(
        stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CONTENUS), fait, contenus.cles_unicite(fait["type_entree"])
    )


def _recevoir_contenu_exporte(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m7.contenu_exporte` (PLAN T4.17-e) : ce contenu existe, avec sa clé de mesure, son chantier et son
    canal. Rien de personnel ne voyage dans cet événement, et rien de plus n'est gardé. Le résumé du reçu ne porte que
    l'identifiant du contenu et si le fait était déjà connu."""
    enregistre = _ranger_fait_contenu(contenus.fait_contenu_exporte(charge))
    return {"enregistre": enregistre, "deja_enregistre": not enregistre, "contenu_id": charge["contenu_id"]}


def _recevoir_lead_qualifie(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m1.lead_qualifie` (PLAN T4.17-e) : M1 a qualifié ce lead, avec la clé `utm_content` qu'il portait.
    La charge porte aussi le contact, la ville et le service du lead : M8 n'en garde rien (`contenus.fait_lead_m1`), et
    le résumé du reçu, que le bus range, ne porte que l'identifiant du lead et si une clé était présente."""
    fait = contenus.fait_lead_m1(charge)
    enregistre = _ranger_fait_contenu(fait)
    return {
        "enregistre": enregistre, "deja_enregistre": not enregistre, "lead_id": fait["lead_id"],
        "avec_utm_content": fait["utm_content"] is not None,
    }


def _recevoir_cash_libre_constate(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m5.cash_libre_constate` (PLAN T4.19-b) : le constat du cash libre, TEL QUE M5 l'a publié (M8 ne
    fait pas la comptabilité), rangé au registre `faits_cash_libre` (`cash_libre.fait_constat`). Un fait par identifiant
    d'événement : une relivraison, ou un rejeu du répartiteur, n'ajoute rien ; le DERNIER constat (le plus grand
    `sequence`) est celui que la vue montre, quel que soit l'ordre de livraison. Un constat « non calculable » est rangé
    comme les autres : M8 ne le remplace par aucun zéro.

    Le résumé du reçu, que le bus range, ne porte AUCUN montant : l'identifiant, le rang, le jour de référence et le
    statut seulement."""
    fait = cash_libre.fait_constat(charge)
    enregistre = _ajouter_fait_si_nouveau(
        stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CASH_LIBRE), fait, cash_libre.cles_unicite()
    )
    return {
        "enregistre": enregistre, "deja_enregistre": not enregistre, "evenement_id": charge["evenement_id"],
        "sequence": charge["sequence"], "date_reference": charge["date_reference"], "statut": charge["statut"],
    }


def consommateurs() -> dict[str, Any]:
    """Types d'événements consommés par M8 (ADR-0009 §3) — voir `department.yaml:evenements.consomme`
    et `docs/architecture/DEPARTEMENTS.md` § Événements."""
    return {
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m3.devis_accepte": _recevoir_devis_accepte,
        "m6.variance_chantier": _recevoir_variance_chantier,
        "m5.rentabilite_chantier": _recevoir_rentabilite_chantier,
        "m2.client_associe": _recevoir_client_associe,
        "m2.lead_assigne": _recevoir_lead_assigne,
        "m3.devis_envoye": _recevoir_devis_envoye,
        "m3.devis_sans_reponse": _recevoir_devis_sans_reponse,
        "m7.contenu_exporte": _recevoir_contenu_exporte,
        "m1.lead_qualifie": _recevoir_lead_qualifie,
        cash_libre.EVENEMENT: _recevoir_cash_libre_constate,
    }


# ---------------------------------------------------------------------------
# Bus d'événements (ADR-0009 §3, PLAN T3.2) : M9 a besoin des alertes proposées par M8 pour son
# briefing du matin. Plutôt qu'une lecture directe du registre M8 par M9 (refusée par PLAN T3.2 —
# préférer un événement), M8 publie chaque AlerteProposee sur le bus (m8.alerte_proposee) ; M9 la
# consomme de façon idempotente (m9_strategic_intelligence.outils._recevoir_alerte_proposee).
# ---------------------------------------------------------------------------
_DEPARTEMENT = "m08-analytics"

# T3.1-suite : le schéma du catalogue (src/opsys/evenements/catalogue/m8.alerte_proposee.json)
# fige encore `type_alerte` (enum) et `preuve` (oneOf) aux TROIS verdicts de T3.1 — l'étendre est
# hors périmètre de ce lot (catalogue d'événements touché seulement si nécessaire, ce qui n'est
# pas encore le cas : ces deux nouvelles alertes restent pleinement utiles sans le bus, via la
# réponse de l'outil et digest.py). Publier un `type_alerte` hors énuméré ferait échouer la
# validation JSON Schema de `evenements.publier` (ChargeInvalide) : cette liste blanche est donc
# un fail-closed VOLONTAIRE, pas un oubli — `test_alerte_doublon_nest_jamais_publiee_sur_le_bus_
# catalogue_non_etendu` (test_evenements_alerte_proposee.py) le verrouille.
_TYPES_ALERTE_SUR_BUS = frozenset({
    qualite.VERDICT_DONNEE_ABSENTE,
    qualite.VERDICT_DONNEE_INVALIDE,
    qualite.VERDICT_DONNEE_PERIMEE,
    qualite.VERDICT_HORS_PLAGE,
})


def _publier_alerte_proposee(metric_id: str, alerte: dict[str, Any], horodatage_reference: str) -> None:
    """Publie l'AlerteProposee sur le bus, DANS LA MÊME TRANSACTION que l'évaluation qui vient de
    la produire (`evenements.publier` ouvre un point de sauvegarde sur la transaction déjà ouverte
    par `executer_atomique`, jamais une transaction indépendante — même patron que
    `m4_field_ops.outils.completer_intervention` pour `m4.travaux_termines`).

    `evenement_id` déterministe (metric_id + type_alerte + horodatage_reference) : une
    réévaluation rejoue la première enveloppe publiée sous ce même id (ADR-0009 §3), même si
    la preuve courante a changé. La date complète fait partie de l'identifiant ; seule l'alerte
    de mesure « seuil à configurer » utilise une identité par jour.

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

    Gardé aussi par `_TYPES_ALERTE_SUR_BUS` (T3.1-suite) : un `type_alerte` absent de cette liste
    (doublon, incohérence) n'est jamais envoyé au bus — voir le commentaire au-dessus de la
    constante.
    """
    if stockage.connexion_courante() is None:
        return
    if alerte["type_alerte"] not in _TYPES_ALERTE_SUR_BUS:
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
    premiere = evenements.charge_publiee("m8.alerte_proposee", ident)
    evenements.publier(
        "m8.alerte_proposee", _DEPARTEMENT, premiere if premiere is not None else charge,
        evenement_id=ident,
    )


def outils(
    registre_cible: registre.RegistreSnapshots | None = None,
    definitions_cible: Any = None,
    faits_cible: Any = None,
    faits_entonnoir_cible: Any = None,
    faits_contenus_cible: Any = None,
    faits_cash_libre_cible: Any = None,
) -> tuple[Outil, ...]:
    """Capacités exposées aux agents. Une instance de RegistreSnapshots par installation.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.RegistreSnapshots()` explicite
    (tests) reste en mémoire, jamais touché à la base.

    `definitions_cible` (T3.1) : même patron pour le registre durable des définitions de
    métriques — `None` (défaut) l'adosse à `opsys.stockage.maillons("m08-analytics",
    "definitions_metriques")` ; une `list` explicite (tests) reste en mémoire.

    `faits_cible` (T1.5-d) : même patron pour le registre `faits_chantier` (faits reçus par le bus,
    lus par `m8_lire_mesures_chantier` et `m8_performance_equipe`) — `None` (défaut) l'adosse à
    `opsys.stockage.maillons("m08-analytics", "faits_chantier")`.

    `faits_entonnoir_cible` (T4.19) : même patron pour le registre `faits_entonnoir` (faits de M2 et de M3 reçus par
    le bus, lus par `m8_lire_vue_executive`) — `None` (défaut) l'adosse à
    `opsys.stockage.maillons("m08-analytics", "faits_entonnoir")`.

    `faits_contenus_cible` (T4.17-e) : même patron pour le registre `faits_contenus` (contenus exportés par M7 et leads
    de M1 reçus par le bus, lus par `m8_lire_mesures_contenus`) — `None` (défaut) l'adosse à
    `opsys.stockage.maillons("m08-analytics", "faits_contenus")`.

    `faits_cash_libre_cible` (T4.19-b) : même patron pour le registre `faits_cash_libre` (constats du cash libre publiés
    par M5, reçus par le bus, lus par `m8_lire_vue_executive`) — `None` (défaut) l'adosse à
    `opsys.stockage.maillons("m08-analytics", "faits_cash_libre")`.
    """
    if faits_cible is None:
        faits_cible = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FAITS)
    if faits_entonnoir_cible is None:
        faits_entonnoir_cible = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_ENTONNOIR)
    if faits_contenus_cible is None:
        faits_contenus_cible = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CONTENUS)
    if faits_cash_libre_cible is None:
        faits_cash_libre_cible = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CASH_LIBRE)
    maillons_snapshots = None
    if registre_cible is None:
        maillons_snapshots = stockage.maillons("m08-analytics", "snapshots")
        registre_cible = registre.RegistreSnapshots(maillons=maillons_snapshots)
    if definitions_cible is None:
        definitions_cible = stockage.maillons("m08-analytics", "definitions_metriques")

    def _candidats_numeriques(module_source: str, metric_id: str, vue=None) -> list[tuple[str, float]]:
        """Paires (horodatage, valeur) valides, ordre du registre, pour un module_source+metric_id.

        Même règle de conversion que semantique.deriver_metrique : une valeur qui ne convertit
        pas en float est exclue du compte, jamais une erreur ni une valeur inventée. Source
        commune à `_historique_numerique` (XmR, T3.1) et à la détection de doublons d'observation
        (T3.1-suite, `qualite.evaluer_unicite`) — un seul passage sur le registre, deux usages.
        """
        candidats: list[tuple[str, float]] = []
        for maillon in (registre_cible if vue is None else vue).lire():
            if maillon["module_source"] != module_source:
                continue
            if metric_id not in maillon["valeurs"]:
                continue
            try:
                valeur = float(maillon["valeurs"][metric_id])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(valeur):
                continue
            candidats.append((maillon["horodatage"], valeur))
        return candidats

    def _historique_numerique(module_source: str, metric_id: str, vue=None) -> list[float]:
        """Série chronologique (ordre du registre) des valeurs numériques d'un metric_id."""
        return [valeur for _, valeur in _candidats_numeriques(module_source, metric_id, vue)]

    def _resoudre_valeur_composante(metric_id_composante: str, horodatage_reference: str) -> float | None:
        """Valeur DÉRIVÉE d'une composante pour le contrôle de cohérence (T3.1-suite) — jamais une
        valeur fournie brute par l'appelant : résout la PROPRE définition enregistrée de cette
        composante dans le registre durable, puis la dérive contre CE MÊME registre de snapshots,
        exactement comme pour la métrique dérivée elle-même. `None` si la composante n'est pas
        enregistrée ou n'a encore aucune valeur — fail-closed mais SILENCIEUX : le contrôle de
        cohérence est alors simplement ignoré pour cet appel (voir `evaluer_qualite_metrique`),
        jamais une composante devinée ni une exception qui ferait perdre les autres alertes déjà
        trouvées pour la métrique dérivée.
        """
        definition_composante = registre_metriques.resoudre(metric_id_composante, definitions_cible)
        if definition_composante is None:
            return None
        return semantique.deriver_metrique(
            definition_composante["departement_proprietaire"], metric_id_composante,
            definition_composante, registre_cible, horodatage_reference,
        )["valeur"]

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

        if maillons_snapshots is not None:
            vue = _copie_snapshots_valide(maillons_snapshots)
            _ajouter_snapshot_durable(maillons_snapshots, vue, snapshot)
        else:
            registre_cible.ajouter(snapshot)
            vue = registre_cible

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
                module_source, metric_id, definition, vue, horodatage_reference
            )
            if valeur_metrique.get("derniere_valeur_invalide", False):
                return {
                    "etape": "semantique",
                    "accepte": False,
                    "verdict": f"REJ-QUALITE-DONNEE-INVALIDE:{metric_id}",
                }
            metriques.append(valeur_metrique)

            historique = _historique_numerique(module_source, metric_id, vue)
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

    def evaluer_qualite_metrique(
        metric_id: str,
        horodatage_reference: str,
        composantes: dict[str, float] | None = None,
        tolerance_coherence: float | None = None,
    ) -> dict[str, Any]:
        """Résout la définition enregistrée, dérive la valeur courante (sémantique.py, contre le
        même registre de snapshots que `rapport_metriques`), puis évalue présence, fraîcheur,
        plage et unicité — PUREMENT à partir de `horodatage_reference` fourni (qualite.py ne lit
        jamais l'horloge). Propose 0 à N alertes structurées (jamais exécutées, jamais un appel à
        un autre département) ; réponse compacte, aucun historique complet renvoyé.

        `composantes` (T3.1-suite, optionnel) déclenche EN PLUS un contrôle de cohérence entre
        séries : `{metric_id_composante: coefficient}`, où `coefficient` encode le signe attendu
        (ex. `-1.0` pour une composante soustraite, comme un coût dans une marge). Chaque valeur
        de composante est RE-DÉRIVÉE par M8 depuis sa propre définition enregistrée (jamais reçue
        brute de l'appelant — voir `_resoudre_valeur_composante`) ; une composante non enregistrée
        ou sans donnée fait simplement ignorer le contrôle de cohérence pour cet appel (silencieux,
        jamais une exception qui ferait perdre les autres alertes déjà trouvées). `tolerance_
        coherence` est alors REQUISE (fail-closed : jamais une tolérance devinée) — fournir l'un
        sans l'autre est un refus métier (`ValueError`).

        Chaque alerte proposée D'UN TYPE DÉJÀ CATALOGUÉ est aussi PUBLIÉE sur le bus
        (`m8.alerte_proposee`, PLAN T3.2, `_publier_alerte_proposee`) pour que M9 la consomme sans
        lire directement le registre M8 — seulement en production (garde
        `stockage.connexion_courante`) ; la réponse ci-dessous et l'autonomie T0 de cet outil
        restent inchangées, son niveau explicite N2 (tâche interne automatique) dit qu'il écrit.
        Les alertes de doublon et de cohérence (T3.1-suite) ne sont PAS encore publiées sur le bus
        (schéma du catalogue non étendu par ce lot, voir `_TYPES_ALERTE_SUR_BUS`) ; elles restent dans la
        réponse et alimentent le digest quotidien.
        """
        if (composantes is None) != (tolerance_coherence is None):
            raise ValueError(
                "composantes et tolerance_coherence doivent être fournis ensemble ou pas du "
                "tout : jamais une tolérance de cohérence devinée."
            )

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
        absence = qualite.evaluer_presence(
            metric_id, valeur_metrique["n"], valeur_metrique["valeur"],
            valeur_metrique.get("valeurs_invalides", 0),
        )
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

            horodatages = [
                horodatage
                for horodatage, _ in _candidats_numeriques(definition["departement_proprietaire"], metric_id)
            ]
            doublon = qualite.evaluer_unicite(metric_id, horodatages)
            if doublon is not None:
                alertes_proposees.append(alertes.proposer_action(doublon, definition))

            if composantes is not None:
                composantes_resolues: dict[str, dict[str, float]] = {}
                toutes_connues = True
                for metric_id_composante, coefficient in composantes.items():
                    valeur_composante = _resoudre_valeur_composante(metric_id_composante, horodatage_reference)
                    if valeur_composante is None:
                        toutes_connues = False
                        break
                    composantes_resolues[metric_id_composante] = {
                        "coefficient": coefficient, "valeur": valeur_composante,
                    }
                if toutes_connues:
                    incoherence = qualite.evaluer_coherence(
                        metric_id, valeur_metrique["valeur"], composantes_resolues, tolerance_coherence
                    )
                    if incoherence is not None:
                        alertes_proposees.append(alertes.proposer_action(incoherence, definition))

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

    def lister_definitions_metriques(limite: int, curseur: int = 0) -> dict[str, Any]:
        """Listage compact et paginé du registre durable des définitions (T3.1-suite) : voir
        `registre_metriques.lister` — jamais l'historique complet."""
        return registre_metriques.lister(definitions_cible, limite, curseur)

    def lire_mesures_chantier(wct_id: str) -> dict[str, Any]:
        """Mesures d'un chantier terminé d'après les faits déjà reçus (T1.5-d) : temps réel contre
        prévu, marge prévue contre réelle, écart de matériaux, chacune calculée, ou « non
        calculable » avec ce qui manque (`manque`, détaillé une fois dans `manques` : champ, source,
        raison — forme compacte, la réponse ne doit jamais être tronquée par `Capacites`). Lecture
        pure : ne publie aucune alerte. Le technicien n'y figure pas (détail nominatif :
        `m8_performance_equipe`, admin)."""
        situation = _situation_chantier(wct_id, faits_cible)
        if situation is None:
            return {"wct_id": wct_id, "trouve": False, "verdict": f"REJ-CHANTIER-INCONNU:{wct_id}"}
        wct = situation["faits"]["wct"]
        mesures, manques = mesures_chantier.compacter(situation["mesures"])
        return {
            "wct_id": wct_id,
            "trouve": True,
            "devis_id": wct.get("devis_id"),
            "horodatage_completion": wct["horodatage_completion"],
            "mesures": mesures,
            "manques": manques,
            "seuils": situation["evaluations"],
            "seuils_a_configurer": [
                e["metric_id"] for e in situation["evaluations"]
                if e["statut"] in (mesures_chantier.SEUIL_A_CONFIGURER, mesures_chantier.SEUIL_INVALIDE)
            ],
        }

    def performance_equipe(depart: int = 0) -> dict[str, Any]:
        """Écart de temps par technicien (T1.5-d), la plus petite métrique honnête : anonyme pour
        l'équipe, nominatif seulement pour l'admin authentifié, jamais classé, jamais une alerte.

        Le détail nominatif est BORNÉ sous la limite de sortie du socle : les techniciens, par
        identifiant, tiennent page par page (`depart`, `affichage.prochain_depart`), jamais tronqués."""
        resultat = mesures_chantier.performance_equipe(list(faits_cible), _chantiers_minimum())
        definition = mesures_chantier.charger_definitions()[mesures_chantier.METRIQUE_EQUIPE]
        nominatif = _admin_authentifie()
        socle: dict[str, Any] = {
            "metric_id": resultat["metric_id"],
            "unite": definition["unite"],
            "version_definition": encodage_module.empreinte(definition),
            "equipe": resultat["equipe"],
            "chantiers_minimum_a_configurer": resultat["chantiers_minimum_a_configurer"],
            "detail_nominatif": "inclus" if nominatif else "reserve_admin",
            "limites": [
                "Le technicien d'un chantier est celui du dernier pointage de départ (M4) : un chantier à "
                "plusieurs personnes est attribué à la dernière.",
                "Seuls les chantiers avec durée réelle et durée estimée (M3) sont mesurés ; les autres sont comptés.",
                "Indicateur non punitif : techniciens listés par identifiant, sans classement, sans alerte.",
            ],
        }
        if not nominatif:
            return socle
        techniciens = resultat["techniciens"]

        def construire(page: list[dict[str, Any]], prochain_depart: int | None) -> dict[str, Any]:
            reste = len(techniciens) - depart - len(page)
            message = f"{reste} technicien(s) non affiché(s) : poursuivre avec depart={prochain_depart}."
            return {
                **socle,
                "techniciens": page,
                "affichage": {
                    "n_techniciens": len(techniciens), "depart": depart, "affiches": len(page), "reste": reste,
                    "prochain_depart": prochain_depart, "message": message if reste else None,
                },
            }

        return mesures_chantier.page_bornee(techniciens, depart, BUDGET_SORTIE, construire)

    def lire_vue_executive(aujourd_hui: str | None = None) -> dict[str, Any]:
        """La vue exécutive du propriétaire (T4.19, M8.6) : l'entonnoir mesuré par le code d'après les faits de M2 et
        de M3, la marge réelle que M5 a publiée, le stock à commander que M6 met à la file du propriétaire, et le cash
        libre : le DERNIER constat que M5 a publié (T4.19-b), tel quel, avec son âge, ou « manque » si M5 n'en a publié
        aucun. Lecture pure (T0) : rien n'est écrit, rien n'est publié, et aucun montant de M5 n'est recalculé. Un
        appareil qui n'est pas celui d'un admin authentifié est refusé ICI, avant toute lecture ; la réponse est bornée
        sous la limite du socle, ce qui n'y tient pas est compté.

        `aujourd_hui` (AAAA-MM-JJ, facultatif) ne sert qu'à dire l'âge du constat du cash libre : M8 n'a pas d'horloge
        et ne devine jamais la date. Absent : l'âge est « non calculable ». Illisible : refus nommé
        (`REJ-VUE-AUJOURD-HUI-INVALIDE`), avant toute lecture. Il n'élargit ni ne restreint rien d'autre."""
        _exiger_admin_pour_appareil()
        jour = cash_libre.lire_aujourd_hui(aujourd_hui)
        faits_chantier = list(faits_cible)
        situation = entonnoir.situation(
            list(faits_entonnoir_cible), faits_chantier, entonnoir.charger_definitions(), _seuils_entonnoir()
        )
        attentes_m6, raison_m6 = _lire_attentes_m6()
        return vue_executive.assembler(
            situation, faits_chantier, attentes_m6, raison_m6, budget_caracteres=BUDGET_SORTIE,
            faits_cash_libre=list(faits_cash_libre_cible), aujourd_hui=jour,
        )

    def lire_mesures_contenus(depart: int = 0) -> dict[str, Any]:
        """La mesure par contenu (T4.17-e) : quels contenus de M7 amènent des leads, puis des devis. Les métriques sont
        celles de `metrics/m8-contenus.v1.yaml`, calculées par le code d'après les faits reçus (contenus exportés, leads
        de M1, devis de l'entonnoir) ; chaque contenu a sa ligne. Une donnée absente est « non calculable, manque X »,
        jamais un zéro ; les impressions et les clics n'ont aucune source. Lecture pure (T0) : rien n'est écrit, rien
        n'est publié. Un appareil qui n'est pas celui d'un admin authentifié est refusé ICI, avant toute lecture ; les
        contenus tiennent page par page sous la limite du socle (`depart`, `affichage.prochain_depart`)."""
        _exiger_admin_pour_appareil()
        situation = contenus.situation(
            list(faits_contenus_cible), list(faits_entonnoir_cible), contenus.charger_definitions()
        )
        return vue_contenus.assembler(situation, depart, BUDGET_SORTIE)

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
                "calculés (signaux actifs seulement, jamais DONNEES_INSUFFISANTES) et d'alertes "
                "de qualité déjà proposées (T3.1-suite) — sourcées, dédupliquées par contenu "
                "exact ; une journée sans alerte le dit explicitement (resume_alertes)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signaux": {"type": "array", "items": _SIGNAL},
                    "alertes_proposees": {"type": ["array", "null"], "items": _ALERTE},
                },
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
                "âge vs fraîcheur attendue, plage, doublon d'observation, et cohérence avec ses "
                "composantes si fournies), à partir d'un horodatage de référence fourni — jamais "
                "l'horloge interne — et propose une alerte structurée (quoi/à qui/pourquoi/preuve) "
                "par problème détecté. Ne l'exécute jamais et n'agit sur aucun autre département ; "
                "publie sur le bus (m8.alerte_proposee) chaque alerte d'un type déjà catalogué "
                "(absence, péremption, hors plage) pour que d'autres départements (M9) la "
                "consomment sans lire le registre M8 — les alertes de doublon et de cohérence "
                "restent dans la réponse (catalogue non encore étendu)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "metric_id": {"type": "string"},
                    "horodatage_reference": {
                        "type": "string",
                        "description": "Instant de référence pour la fraîcheur (M8 n'a pas d'horloge).",
                    },
                    "composantes": _COMPOSANTES,
                    "tolerance_coherence": _TOLERANCE_COHERENCE,
                },
                "required": ["metric_id", "horodatage_reference"],
                "additionalProperties": False,
            },
            fonction=evaluer_qualite_metrique,
            # T0 automatique, mais N2 explicite : la publication d'une alerte est une tâche interne
            # (ADR-0009 §4), jamais une lecture pure ; le serveur MCP l'annonce donc comme écriture.
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m8_lister_definitions_metriques",
            description=(
                "Listage compact et paginé du registre durable des définitions surveillées par "
                "M8 : identifiant, département propriétaire, unité, fraîcheur attendue et numéro "
                "de version — une ligne par métrique (dernière version seulement), jamais "
                "l'historique complet."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "limite": {
                        "type": "integer",
                        "description": "Nombre maximal de définitions retournées (strictement positif).",
                    },
                    "curseur": {
                        "type": "integer",
                        "description": "Décalage de pagination, 0 = première page (défaut : 0).",
                    },
                },
                "required": ["limite"],
                "additionalProperties": False,
            },
            fonction=lister_definitions_metriques,
        ),
        Outil(
            nom="m8_lire_mesures_chantier",
            description=(
                "Mesures d'un chantier terminé, d'après les faits déjà reçus par le bus : écart de durée "
                "(réel M4 contre estimé M3), marge prévue (M3) et réelle (M5), plus grand écart de "
                "matériaux (M6). Chaque mesure est calculée par le code avec la version de sa définition, "
                "ou « non calculable » avec ce qui manque et de qui — jamais une valeur inventée. Dit aussi "
                "où un seuil d'alerte reste à configurer. Lecture pure, aucune alerte publiée. Réservé à "
                "l'admin : marges et coûts ne vont pas à un employé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {"type": "string", "description": "Identifiant du WCT (m4.travaux_termines)."},
                },
                "required": ["wct_id"],
                "additionalProperties": False,
            },
            fonction=lire_mesures_chantier,
            roles_appareil=frozenset({_ROLE_ADMIN}),
        ),
        Outil(
            nom="m8_performance_equipe",
            description=(
                "Écart de temps réel contre prévu de l'équipe sur les chantiers mesurés, et par technicien "
                "SEULEMENT pour l'admin authentifié (sinon `detail_nominatif: reserve_admin`). Techniciens "
                "listés par identifiant, sans classement ni alerte : indicateur non punitif. Dit le nombre "
                "de chantiers mesurés et de ceux sans temps prévu ; le minimum d'échantillon vient de la "
                "configuration, sinon `suffisant` reste nul. Le détail nominatif est borné : `depart` reprend "
                "à `affichage.prochain_depart` s'il y a plus de techniciens que la limite de sortie n'en laisse tenir."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "depart": {
                        "type": "integer",
                        "description": "Indice du premier technicien rendu (0 = début) ; reprendre à prochain_depart.",
                    },
                },
                "additionalProperties": False,
            },
            fonction=performance_equipe,
            roles_appareil=frozenset({_ROLE_ADMIN}),
        ),
        Outil(
            nom="m8_lire_vue_executive",
            description=(
                "Vue exécutive du propriétaire, lecture pure : l'entonnoir commercial (leads reçus et qualifiés, "
                "devis envoyés, acceptés et sans réponse, taux d'acceptation, délai lead-acceptation, carnet signé) "
                "mesuré par le code d'après les faits de M2 et de M3, avec la version et le propriétaire de chaque "
                "définition ; la marge réelle des chantiers telle que M5 l'a publiée ; le stock à commander tel que "
                "M6 le publie ; le cash libre : le dernier constat de M5, tel quel, avec son âge (aujourd_hui, "
                "AAAA-MM-JJ, facultatif : M8 n'a pas d'horloge), ou « manque » si M5 n'en a publié aucun. Une donnée "
                "absente est « non calculable, manque X », jamais un zéro ; aucun montant de M5 n'est recalculé. "
                "Réservé à l'admin."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "aujourd_hui": {
                        "type": ["string", "null"],
                        "description": (
                            "Jour de l'appelant, AAAA-MM-JJ : sert seulement à dire l'âge du constat du cash libre. "
                            "Absent : l'âge est « non calculable » (jamais deviné)."
                        ),
                    },
                },
                "additionalProperties": False,
            },
            fonction=lire_vue_executive,
            # §9.5 (profil admin) : « tableau de bord exécutif, alertes et wallboard » (M8). Marges, stock et carnet de
            # toute l'entreprise : ni l'employé ni le vendeur (§8.16, §9.2, §9.4) ; refusé aussi dans le code.
            roles_appareil=frozenset({_ROLE_ADMIN}),
        ),
        Outil(
            nom="m8_lire_mesures_contenus",
            description=(
                "Mesure par contenu, lecture pure : leads, devis envoyés et acceptés que chaque contenu exporté "
                "par M7 a amenés, par sa clé utm_content (leads de M1, devis de M3), avec la version et le "
                "propriétaire de chaque définition. Un lead sans clé n'est attribué à aucun contenu. Impressions "
                "et clics : aucune source, « non calculable », jamais un zéro. Par pages de contenus (`depart`). "
                "Réservé à l'admin."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "depart": {
                        "type": "integer",
                        "description": "Indice du premier contenu rendu (0 = début) ; reprendre à prochain_depart.",
                    },
                },
                "additionalProperties": False,
            },
            fonction=lire_mesures_contenus,
            # §9.5 (profil admin) : « tableau de bord exécutif » (M8) et « tableau de bord marketing » (M7, §7 M7
            # mobile) : le propriétaire lit ce que ses contenus rapportent. Ni l'employé ni le vendeur (§9.4 : « ses
            # ventes » seulement) ; refusé aussi dans le code.
            roles_appareil=frozenset({_ROLE_ADMIN}),
        ),
        Outil(
            nom="m8_lire_provenance_m5_appareil",
            description=(
                "Diagnostic borné des publications M5 existantes et de leur réception M8, sans effet financier."
            ),
            parametres={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "perimetre": {"type": "string", "enum": ["cash_global", "rentabilite_wct"]},
                    "wct_id": {"type": ["string", "null"], "minLength": 1, "maxLength": 256},
                    "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["perimetre", "wct_id", "decalage", "limite"],
            },
            fonction=lire_provenance_m5_appareil,
            roles_appareil=frozenset({_ROLE_ADMIN}),
            portee_contexte="globale",
        ),
    )


def autoriser_provenance_m5_appareil(arguments: Any, *, cnx: Any) -> dict[str, Any]:
    """Admet le corps et l'admin SQL courant avant toute copie métier ; aucune autorité dans le corps."""
    a = provenance_m5.valider_arguments(arguments)
    acteur = contexte.identite_appelante()
    if (acteur is None or acteur.source != "appareil" or acteur.role != _ROLE_ADMIN
            or cnx is None or stockage.connexion_courante() is not cnx):
        raise provenance_m5.Refus("IDENTITE-INVALIDE")
    personne = identite.personne_active(cnx, acteur.personne)
    if personne is None or _ROLE_ADMIN not in personne.roles:
        raise provenance_m5.Refus("IDENTITE-INVALIDE")
    return a


def lire_provenance_m5_appareil(perimetre: str, wct_id: str | None, decalage: int, limite: int) -> dict:
    """Façade transactionnelle ; les copies Socle sont adaptées explicitement au domaine pur."""
    try:
        cnx = stockage.connexion_courante()
        arguments = autoriser_provenance_m5_appareil(
            {"perimetre": perimetre, "wct_id": wct_id, "decalage": decalage, "limite": limite}, cnx=cnx
        )
        return depuis_couple((_copier_diagnostic_provenance_m5(cnx, arguments), None))
    except provenance_m5.Refus as refus:
        return depuis_couple((None, refus.verdict))


def _copier_diagnostic_provenance_m5(cnx: Any, arguments: dict) -> dict:
    # Imports locaux : API Socle seule, connexion canonique ; aucun chargement de factory M5/M8.
    from opsys.evenements.bus import (
        BudgetProvenanceDepasse,
        RegistreProvenanceInvalide,
        copier_cohorte_provenance_m5_m8,
    )
    from opsys.evenements.schemas import erreurs_charge

    rent = arguments["perimetre"] == "rentabilite_wct"
    type_evenement = "m5.rentabilite_chantier" if rent else "m5.cash_libre_constate"
    registre_cible = "faits_chantier" if rent else "faits_cash_libre"
    try:
        bus, registre_copie = copier_cohorte_provenance_m5_m8(cnx, type_evenement=type_evenement)
    except BudgetProvenanceDepasse:
        raise provenance_m5.Refus("BUDGET-SOURCE-DEPASSE") from None
    except RegistreProvenanceInvalide:
        raise provenance_m5.Refus("REGISTRE-INVALIDE") from None
    except ValueError:
        raise provenance_m5.Refus("SOURCE-INVALIDE") from None
    publications = [{"evenement_id": p.evenement_id, "type_evenement": p.type_evenement,
                     "producteur": p.producteur, "charge": p.charge, "cree_le": p.cree_le}
                    for p in bus.publications]
    recus = [{"evenement_id": r.evenement_id, "consommateur": r.consommateur, "statut": r.statut,
              "tentatives": r.tentatives, "prochaine_tentative": r.prochaine_tentative,
              "resultat": r.resultat} for r in bus.recus]
    maillons = []
    for m in registre_copie.lignes:
        d = m.cree_le
        maillons.append({"rang": m.rang, "cree_le": None if d is None else d.isoformat(),
                         "fuseau": "inconnu" if d is None else
                         "non_persiste" if d.utcoffset() is None else "present", "maillon": m.maillon})
    for p in publications:
        provenance_m5.valider_json(p)
        if type(p["charge"]) is not dict or erreurs_charge(type_evenement, p["charge"]):
            raise provenance_m5.Refus("SOURCE-INVALIDE")
    sources = [
        {"table": "evenements_sortants", "departement": None, "registre": None,
         "lignes": len(publications), "empreinte_snapshot_calculee": bus.empreinte_publications_calculee},
        {"table": "evenements_recus", "departement": None, "registre": None,
         "lignes": len(recus), "empreinte_snapshot_calculee": bus.empreinte_recus_calculee},
        {"table": "registres_maillons", "departement": "m08-analytics", "registre": registre_cible,
         "lignes": len(maillons), "empreinte_snapshot_calculee": registre_copie.empreinte_snapshot_calculee},
    ]
    borne = contexte.limite_sortie()
    return provenance_m5.produire(publications, recus, maillons, sources, arguments,
                                 budget_sortie=min(5400, borne) if borne is not None else 5400)
