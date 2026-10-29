"""Playbooks stratégiques M9.15 : six gabarits gouvernés, instanciés sur de vrais états, qui n'exécutent rien.

Module pur. Chaque gabarit (cash, baisse de leads, surcharge, météo, rupture, hausse de prix) dit : ce qui le DÉCLENCHE
(règles du radar de risques M9.12, ou déclaration de la personne quand aucun producteur ne mesure le signal), ses ÉTAPES
ordonnées (information, suivi interne ou action sensible), qui décide, et des critères de SUCCÈS et d'ARRÊT lisibles sur
les captures des propriétaires.

* ``instancier`` croise le gabarit avec le radar : DECLENCHE, NON_DECLENCHE, INCONNU (règles non évaluées) ou A_DECLARER
  (aucune mesure automatique : la personne déclare le déclencheur, nommé comme tel) ;
* une étape sensible (``conseil.ACTIONS_SENSIBLES``) reste ``VALIDATION_HUMAINE_REQUISE`` ; aucune étape n'autorise un
  effet (``effet_autorise`` faux) : l'exécution passe par l'orchestrateur et les approbations natives (M9.17) ;
* une cible chiffrée (marge à rétablir, nombre de leads) est celle de la personne, liée par ``liaisons`` ; sans elle, le
  critère est INCONNU, jamais une valeur par défaut ;
* ``evaluer_criteres`` lit la dernière capture complète de chaque lecture : SATISFAIT, NON_SATISFAIT ou INCONNU.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs
from . import conseil, criteres

VERSION = "2026-10-28.1"
OPERATEURS = criteres.OPERATEURS
TYPES_ETAPE = frozenset({"information", "suivi_interne", "action_sensible"})
_R = "resultat.resultat"


def _etape(id_, libelle, type_, *, depend_de=(), genre=None, port=None, qui="m9"):
    return {
        "id": id_,
        "libelle": libelle,
        "type": type_,
        "genre": genre,
        "depend_de": list(depend_de),
        "port": port,
        "qui": qui,
    }


def _critere(id_, libelle, lecture, chemin, operateur, cible=None, *, lier=False):
    return {
        "id": id_,
        "libelle": libelle,
        "lecture": lecture,
        "chemin": chemin,
        "operateur": operateur,
        "cible": cible,
        "cible_a_lier": lier,
    }


CATALOGUE: dict[str, dict] = {
    "cash": {
        "nom": "Tension de trésorerie",
        "declenche_par": ["cash_alerte_seuil", "cash_non_evaluable"],
        "etapes": [
            _etape(
                "lire_prevision",
                "Relire la prévision M5, ses réserves et les encaissements non comptés",
                "information",
                port="m5_prevoir_tresorerie",
                qui="m05-financecore",
            ),
            _etape(
                "completer_donnees",
                "Obtenir les données manquantes nommées par M5 (seuil, solde, flux)",
                "suivi_interne",
                depend_de=["lire_prevision"],
                qui="m05-financecore",
            ),
            _etape(
                "relancer_encaissements",
                "Préparer les relances des comptes à recevoir en retard",
                "suivi_interne",
                depend_de=["lire_prevision"],
                port="m5_lire_comptes_a_recevoir",
                qui="m05-financecore",
            ),
            _etape(
                "reporter_depense",
                "Décider de reporter une dépense planifiée",
                "action_sensible",
                depend_de=["lire_prevision"],
                genre="depense_reelle",
            ),
            _etape(
                "financement",
                "Évaluer un financement externe",
                "action_sensible",
                depend_de=["lire_prevision"],
                genre="dette",
            ),
        ],
        "succes": [
            _critere(
                "alerte_levee",
                "Plus d'alerte de seuil dans la prévision M5",
                "m5.prevision_tresorerie",
                f"{_R}.alerte.statut",
                "==",
                "AUCUNE",
            )
        ],
        "arret": [
            _critere(
                "prevision_non_calculable",
                "M5 ne peut plus calculer la prévision : arrêter et compléter les données",
                "m5.prevision_tresorerie",
                f"{_R}.calculable",
                "==",
                "false",
            )
        ],
        "limites": ["Aucun montant n'est calculé par M9 ; le seuil d'alerte est celui du propriétaire (M5)."],
    },
    "baisse_leads": {
        "nom": "Baisse du flux de leads",
        "declenche_par": [],
        "etapes": [
            _etape(
                "constater",
                "Constater la baisse dans l'entonnoir M8 et la période comparée",
                "information",
                port="m8_lire_vue_executive",
                qui="m08-analytics",
            ),
            _etape(
                "verifier_canaux",
                "Vérifier la performance des campagnes par canal",
                "information",
                depend_de=["constater"],
                port="m7_lire_performance_campagnes",
                qui="m07-marketing",
            ),
            _etape(
                "relancer_devis",
                "Relancer les devis restés sans réponse",
                "suivi_interne",
                depend_de=["constater"],
                port="m2_preparer_relance",
                qui="m02-revenue-crm",
            ),
            _etape(
                "budget",
                "Décider d'un budget marketing supplémentaire",
                "action_sensible",
                depend_de=["verifier_canaux"],
                genre="budget_marketing",
            ),
        ],
        "succes": [
            _critere(
                "leads_remontes",
                "Leads reçus au moins égaux à la cible de la personne",
                "m8.vue_executive",
                "resultat.entonnoir.mesures[*].valeur",
                ">=",
                None,
                lier=True,
            )
        ],
        "arret": [
            _critere(
                "lecture_m8_absente",
                "La vue exécutive M8 n'est plus lisible",
                "m8.vue_executive",
                "resultat.entonnoir.mesures[*].metric_id",
                "aucun",
            )
        ],
        "limites": ["Aucune règle automatique : M8 ne définit pas de période de comparaison ; déclencheur déclaré."],
    },
    "surcharge": {
        "nom": "Surcharge ou blocage des équipes",
        "declenche_par": ["capacite_incident_ouvert", "capacite_report_en_cours"],
        "etapes": [
            _etape(
                "lire_cedule",
                "Relire la cédule de la semaine et les incidents ouverts",
                "information",
                port="m4_lire_cedule_semaine",
                qui="m04-field-ops",
            ),
            _etape(
                "debloquer",
                "Traiter les incidents bloqués",
                "suivi_interne",
                depend_de=["lire_cedule"],
                port="m4_creer_demande_ecart",
                qui="m04-field-ops",
            ),
            _etape(
                "replanifier",
                "Replanifier les interventions touchées",
                "suivi_interne",
                depend_de=["lire_cedule"],
                port="m4_planifier_intervention",
                qui="m04-field-ops",
            ),
            _etape(
                "renfort",
                "Décider d'un renfort ou d'une embauche",
                "action_sensible",
                depend_de=["lire_cedule"],
                genre="embauche",
            ),
        ],
        "succes": [
            _critere(
                "plus_d_incident",
                "Plus aucun incident ouvert chez M4",
                "m4.retards_incidents",
                f"{_R}.incidents.liste[*]",
                "aucun",
            )
        ],
        "arret": [
            _critere(
                "arret_manuel_capacite",
                "Arrêter si la capacité d'équipe n'est plus connue ou si un incident reste bloqué au-delà de la durée "
                "que la personne fixe (aucun producteur ne mesure la charge)",
                "m4.retards_incidents",
                "",
                "manuel",
            )
        ],
        "limites": ["La capacité d'équipe n'est publiée par aucun propriétaire : aucune charge n'est estimée."],
    },
    "meteo": {
        "nom": "Reports pour la météo",
        "declenche_par": ["meteo_report_en_cours"],
        "etapes": [
            _etape(
                "lire_reports",
                "Relire les reports en cours et leur âge",
                "information",
                port="m4_lire_retards_incidents",
                qui="m04-field-ops",
            ),
            _etape(
                "prevision_meteo",
                "Relire la météo des interventions touchées",
                "information",
                depend_de=["lire_reports"],
                port="m4_lire_meteo_intervention",
                qui="m04-field-ops",
            ),
            _etape(
                "replanifier",
                "Replanifier aux prochaines fenêtres propices",
                "suivi_interne",
                depend_de=["prevision_meteo"],
                port="m4_planifier_intervention",
                qui="m04-field-ops",
            ),
            _etape(
                "informer_clients",
                "Informer les clients du report",
                "action_sensible",
                depend_de=["replanifier"],
                genre="contrat",
            ),
        ],
        "succes": [
            _critere(
                "plus_de_report_meteo",
                "Plus de report en cours pour ce motif",
                "m4.retards_incidents",
                f"{_R}.reports.liste[*].motif",
                "aucun",
            )
        ],
        "arret": [
            _critere(
                "meteo_inconnue",
                "Aucune prévision météo disponible (le fournisseur n'est pas configuré)",
                "m4.meteo_intervention",
                f"{_R}.creneaux[*].prevision.emise_le",
                "aucun",
            )
        ],
        "limites": [
            "La météo reste « inconnue » sans fournisseur configuré : le playbook le dit, sans inventer de prévision."
        ],
    },
    "rupture": {
        "nom": "Rupture ou manque de matériaux",
        "declenche_par": ["materiaux_reservation_incomplete"],
        "etapes": [
            _etape(
                "identifier",
                "Identifier les matériaux manquants et les devis touchés",
                "information",
                port="m6_lire_disponibilite",
                qui="m06-material-control",
            ),
            _etape(
                "mesurer_impact",
                "Propager l'impact aux chantiers, interventions et leads",
                "information",
                depend_de=["identifier"],
                port="m9_propager_impacts",
            ),
            _etape(
                "verifier_stock",
                "Vérifier le stock par emplacement et les commandes en cours",
                "suivi_interne",
                depend_de=["identifier"],
                port="m6_lire_disponibilite",
                qui="m06-material-control",
            ),
            _etape(
                "commander",
                "Décider d'un achat pour combler le manque",
                "action_sensible",
                depend_de=["verifier_stock"],
                genre="achat_majeur",
            ),
            _etape(
                "replanifier",
                "Replanifier les interventions si le délai l'exige",
                "suivi_interne",
                depend_de=["mesurer_impact"],
                port="m4_planifier_intervention",
                qui="m04-field-ops",
            ),
        ],
        "succes": [
            _critere(
                "reservations_pretes",
                "Toutes les réservations actives sont prêtes",
                "m6.disponibilite",
                f"{_R}.reservations_actives[*].statut",
                "==",
                "pret",
            )
        ],
        "arret": [
            _critere(
                "aucun_article_lu",
                "M6 ne lit plus aucun article : arrêter et vérifier la lecture",
                "m6.disponibilite",
                f"{_R}.articles[*]",
                "aucun",
            )
        ],
        "limites": ["M6 ne publie ni prix fournisseur ni délai : aucune date de réapprovisionnement n'est estimée."],
    },
    "hausse_prix": {
        "nom": "Hausse de prix des intrants",
        "declenche_par": [],
        "etapes": [
            _etape(
                "documenter",
                "Documenter la hausse par un document de veille accepté et relié",
                "information",
                port="m9_lire_veille",
            ),
            _etape(
                "mesurer_marge",
                "Relire les marges réelles des chantiers récents",
                "information",
                depend_de=["documenter"],
                port="m8_lire_mesures_chantier",
                qui="m08-analytics",
            ),
            _etape(
                "revoir_prix",
                "Décider d'une révision des prix de vente",
                "action_sensible",
                depend_de=["mesurer_marge"],
                genre="prix_global",
            ),
            _etape(
                "renegocier",
                "Décider d'un engagement avec un fournisseur",
                "action_sensible",
                depend_de=["documenter"],
                genre="contrat",
            ),
        ],
        "succes": [
            _critere(
                "marge_retablie",
                "Écart de marge au moins égal à la cible de la personne",
                "m8.mesures_chantier",
                "resultat.mesures[*].valeur",
                ">=",
                None,
                lier=True,
            )
        ],
        "arret": [
            _critere(
                "mesure_absente",
                "Les mesures M8 du chantier ne sont plus lisibles",
                "m8.mesures_chantier",
                "resultat.mesures[*].metric_id",
                "aucun",
            )
        ],
        "limites": [
            "Aucun producteur ne mesure les prix d'achat : déclencheur déclaré par la personne, appuyé par la veille."
        ],
    },
}
_LIMITES = (
    "Gabarits gouvernés : aucune étape n'est exécutée ni autorisée ; l'exécution passe par l'orchestrateur.",
    "Critères lus sur les captures des propriétaires ; une cible absente rend le critère INCONNU.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _verifier_catalogue() -> None:
    for id_, gabarit in CATALOGUE.items():
        etapes = {e["id"]: e for e in gabarit["etapes"]}
        for etape in etapes.values():
            if etape["type"] not in TYPES_ETAPE or (etape["type"] == "action_sensible") != (etape["genre"] is not None):
                raise ValueError(f"{id_}.{etape['id']} : type d'étape incohérent")
            if etape["genre"] is not None and etape["genre"] not in conseil.ACTIONS_SENSIBLES:
                raise ValueError(f"{id_}.{etape['id']} : genre sensible inconnu")
            if not set(etape["depend_de"]) <= set(etapes):
                raise ValueError(f"{id_}.{etape['id']} : dépendance inconnue")
        for critere in [*gabarit["succes"], *gabarit["arret"]]:
            if critere["operateur"] not in OPERATEURS or not critere["id"]:
                raise ValueError(f"{id_}.{critere['id']} : opérateur invalide")


_verifier_catalogue()


def declenchement(gabarit: Mapping, radar: Mapping | None) -> dict:
    regles = gabarit["declenche_par"]
    if not regles:
        return {
            "statut": "A_DECLARER",
            "raison": "aucun producteur ne mesure ce signal : à déclarer par la personne",
            "risques": [],
        }
    if radar is None:
        return {"statut": "INCONNU", "raison": "radar de risques non fourni", "risques": []}
    actifs = [r["risque_id"] for r in radar["risques"] if r["regle"] in regles and r["statut"] == "ACTIF"]
    a_reconfirmer = [
        r["risque_id"] for r in radar["risques"] if r["regle"] in regles and r["statut"] == "A_RECONFIRMER"
    ]
    non_evaluees = [n["regle"] for n in radar["regles_non_evaluees"] if n["regle"] in regles]
    if actifs:
        return {"statut": "DECLENCHE", "risques": actifs, "regles_non_evaluees": non_evaluees}
    if a_reconfirmer:
        return {
            "statut": "INCONNU",
            "raison": "signal présent mais source périmée : à reconfirmer",
            "risques": a_reconfirmer,
        }
    if non_evaluees:
        return {
            "statut": "INCONNU",
            "raison": "règles non évaluées : lecture absente, refusée ou partielle",
            "risques": [],
            "regles_non_evaluees": non_evaluees,
        }
    return {"statut": "NON_DECLENCHE", "risques": []}


def instancier(
    playbook_id: str,
    radar: Mapping | None,
    *,
    connaissance: str,
    declare_par_la_personne: bool = False,
    liaisons: Mapping[str, str] | None = None,
) -> dict:
    if type(playbook_id) is not str or playbook_id not in CATALOGUE:
        raise _refus("REJ-PLAYBOOK-INCONNU", f"playbook parmi {sorted(CATALOGUE)}")
    gabarit = CATALOGUE[playbook_id]
    liaisons = dict(liaisons or {})
    criteres_lies = {c["id"] for c in [*gabarit["succes"], *gabarit["arret"]]}
    if set(liaisons) - criteres_lies:
        raise _refus("REJ-PLAYBOOK-LIAISON", f"critères inconnus {sorted(set(liaisons) - criteres_lies)}")
    for id_, cible in liaisons.items():
        try:
            Decimal(cible)
        except (InvalidOperation, TypeError) as exc:
            raise _refus("REJ-PLAYBOOK-LIAISON", f"{id_} : cible décimale textuelle requise") from exc
    declenche = declenchement(gabarit, radar)
    if declenche["statut"] == "A_DECLARER" and declare_par_la_personne:
        declenche = {"statut": "DECLENCHE", "declare_par_la_personne": True, "risques": []}
    etapes = []
    for etape in gabarit["etapes"]:
        sensible = etape["type"] == "action_sensible"
        etapes.append(
            {
                **etape,
                "statut": "VALIDATION_HUMAINE_REQUISE" if sensible else "PROPOSABLE",
                "proprietaire_decision": conseil.ACTIONS_SENSIBLES[etape["genre"]] if sensible else etape["qui"],
                "effet_autorise": False,
            }
        )

    def lier(critere: dict) -> dict:
        cible = liaisons.get(critere["id"], critere["cible"])
        return {**critere, "cible": cible, "cible_declaree_par_la_personne": critere["id"] in liaisons}

    plan = {
        "type": "PLAYBOOK",
        "version": VERSION,
        "playbook": playbook_id,
        "nom": gabarit["nom"],
        "connaissance": connaissance,
        "declenchement": declenche,
        "etapes": etapes,
        "succes": [lier(c) for c in gabarit["succes"]],
        "arret": [lier(c) for c in gabarit["arret"]],
        "limites": [*gabarit["limites"], *_LIMITES],
    }
    plan["playbook_instance_id"] = hashlib.sha256(
        json.dumps(plan, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return plan


def evaluer_criteres(plan: Mapping, captures: Sequence[Mapping], *, connaissance: str) -> dict:
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    succes = [criteres.evaluer(c, connues, en_conflit) for c in plan["succes"]]
    arret = [criteres.evaluer(c, connues, en_conflit) for c in plan["arret"]]
    if any(c["statut"] == "SATISFAIT" for c in arret):
        verdict = "ARRET"
    elif succes and all(c["statut"] == "SATISFAIT" for c in succes):
        verdict = "SUCCES"
    elif any(c["statut"] == "INCONNU" for c in [*succes, *arret]):
        verdict = "INCONNU"
    else:
        verdict = "EN_COURS"
    return {
        "type": "EVALUATION_PLAYBOOK",
        "playbook": plan["playbook"],
        "playbook_instance_id": plan["playbook_instance_id"],
        "connaissance": connaissance,
        "verdict": verdict,
        "succes": succes,
        "arret": arret,
        "limites": list(_LIMITES),
    }
