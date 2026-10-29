"""Playbooks stratégiques M9.15 : dix-sept gabarits gouvernés, instanciés sur de vrais états, qui n'exécutent rien.

Module pur. Chaque gabarit (cash, baisse ou afflux de leads, surcharge, météo, rupture, hausse de prix, plaintes,
conversion, rendement marketing, saisons, embauche, équipement, expansion, nouveau service, avis clients) dit :
ce qui le DÉCLENCHE (règles du radar de risques M9.12, ou déclaration de la personne quand aucun producteur ne mesure
le signal), ses ÉTAPES ordonnées (information, suivi interne ou action sensible), qui décide, des critères de SUCCÈS
et d'ARRÊT lisibles sur les captures des propriétaires, les DONNÉES requises (lectures de ``catalogue_producteurs``),
les DÉPARTEMENTS touchés, les RISQUES, si une APPROBATION humaine est requise (dérivé : vrai dès qu'une étape est
sensible) et le PLAN DE RETOUR (comment arrêter ou défaire). ``verifier_catalogue`` refuse au chargement tout gabarit
incomplet ou incohérent.

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
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs
from . import catalogue_producteurs, conseil, criteres, risques

VERSION = "2026-10-28.1"
OPERATEURS = criteres.OPERATEURS
TYPES_ETAPE = frozenset({"information", "suivi_interne", "action_sensible"})
_R = "resultat.resultat"
CHAMPS = ("nom", "declenche_par", "etapes", "succes", "arret", "limites", "donnees_requises", "departements", "risques",
          "plan_retour")  # fmt: skip
_CODE_DEPARTEMENT = re.compile(r"m(0[1-9]|10)")


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
        "donnees_requises": ["m5.prevision_tresorerie", "m5.comptes_a_recevoir"],
        "departements": ["m05", "m09"],
        "risques": [
            "Reporter une dépense peut retarder un chantier déjà promis au client.",
            "Un financement externe crée une dette : décision humaine seulement.",
        ],
        "plan_retour": (
            "Aucune étape n'agit seule : arrêter le playbook laisse l'état inchangé ; une relance préparée et non "
            "envoyée s'abandonne ; une dépense reportée se replanifie avec M5."
        ),
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
        "donnees_requises": ["m8.vue_executive", "m7.performance_campagnes", "m2.relances"],
        "departements": ["m02", "m07", "m08", "m09"],
        "risques": [
            "Augmenter le budget sans canal identifié peut payer des leads non qualifiés.",
            "Des relances trop fréquentes peuvent irriter des clients (consentement, Loi 25).",
        ],
        "plan_retour": (
            "Un budget supplémentaire se ramène au budget antérieur par une nouvelle décision M7 ; les relances "
            "préparées et non envoyées s'abandonnent ; arrêter le playbook ne change aucun lead."
        ),
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
        "donnees_requises": ["m4.retards_incidents", "m4.cedule_semaine"],
        "departements": ["m04", "m09"],
        "risques": [
            "Replanifier en cascade peut décaler des chantiers promis à d'autres clients.",
            "Un renfort ou une embauche crée un coût fixe : décision humaine seulement.",
        ],
        "plan_retour": (
            "Une replanification se défait par une nouvelle planification M4 ; une demande d'écart se résout ou "
            "s'annule chez M4 ; aucun renfort n'est engagé sans décision de Nathan."
        ),
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
        "donnees_requises": ["m4.retards_incidents", "m4.meteo_intervention"],
        "departements": ["m04", "m09"],
        "risques": [
            "Une prévision peut changer : une fenêtre propice choisie trop tôt peut se refermer.",
            "Informer un client engage l'entreprise sur une nouvelle date : décision humaine seulement.",
        ],
        "plan_retour": (
            "Une intervention replanifiée se replanifie à nouveau chez M4 ; aucun client n'est informé sans "
            "validation ; arrêter le playbook laisse les reports tels quels."
        ),
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
        "donnees_requises": ["m6.disponibilite", "m4.cedule_semaine"],
        "departements": ["m04", "m06", "m09"],
        "risques": [
            "Commander dans l'urgence peut coûter plus cher ou immobiliser du stock inutile.",
            "Replanifier sans délai fournisseur connu peut déplacer le problème au lendemain.",
        ],
        "plan_retour": (
            "Un bon de commande en brouillon s'annule chez M6 ; une réservation se libère chez M6 ; une "
            "intervention replanifiée se replanifie chez M4 ; aucun achat n'est engagé sans validation."
        ),
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
        "donnees_requises": ["m8.mesures_chantier", "m3.ecarts"],
        "departements": ["m03", "m08", "m09"],
        "risques": [
            "Une hausse des prix de vente peut faire baisser la conversion des devis.",
            "Un engagement fournisseur à long terme fige un prix qui peut redescendre.",
        ],
        "plan_retour": (
            "Une révision de prix se ramène à la grille antérieure par une nouvelle décision ; un engagement "
            "fournisseur non signé s'abandonne ; arrêter le playbook ne change aucun devis."
        ),
    },
    "trop_de_leads": {
        "nom": "Afflux de leads au-delà de la capacité de suivi",
        "declenche_par": [],
        "etapes": [
            _etape(
                "constater",
                "Constater le volume de leads par statut",
                "information",
                port="m2_lister_leads",
                qui="m02-revenue-crm",
            ),
            _etape(
                "verifier_capacite",
                "Relire la cédule pour situer la capacité d'estimation et de pose",
                "information",
                port="m4_lire_cedule_semaine",
                qui="m04-field-ops",
            ),
            _etape(
                "prioriser",
                "Prioriser les leads selon l'urgence déclarée et la prochaine action suggérée",
                "suivi_interne",
                depend_de=["constater"],
                port="m2_suggerer_prochaine_action",
                qui="m02-revenue-crm",
            ),
            _etape(
                "reassigner",
                "Répartir les leads en attente entre les vendeurs",
                "suivi_interne",
                depend_de=["prioriser"],
                port="m2_reassigner_lead",
                qui="m02-revenue-crm",
            ),
            _etape(
                "ralentir_campagnes",
                "Décider de réduire ou suspendre le budget des campagnes payantes",
                "action_sensible",
                depend_de=["constater"],
                genre="budget_marketing",
            ),
            _etape(
                "renfort",
                "Décider d'un renfort ou d'une embauche",
                "action_sensible",
                depend_de=["verifier_capacite"],
                genre="embauche",
            ),
        ],
        "succes": [
            _critere(
                "leads_resorbes",
                "Total de leads lus (filtre de la capture) au plus égal à la cible de la personne",
                "m2.leads",
                f"{_R}.total",
                "<=",
                None,
                lier=True,
            )
        ],
        "arret": [
            _critere(
                "aucun_lead_lu",
                "M2 ne rend plus aucun lead : arrêter et vérifier la lecture",
                "m2.leads",
                f"{_R}.leads[*]",
                "aucun",
            )
        ],
        "limites": ["Aucun producteur ne mesure le délai de premier contact : déclencheur déclaré par la personne."],
        "donnees_requises": ["m2.leads", "m4.cedule_semaine"],
        "departements": ["m02", "m04", "m09"],
        "risques": [
            "Ralentir les campagnes trop tôt peut créer un creux de leads le mois suivant.",
            "Un lead urgent non rappelé peut être perdu au profit d'un concurrent.",
        ],
        "plan_retour": (
            "Le budget de campagne antérieur se rétablit par une nouvelle décision M7 ; une réassignation se défait "
            "par une nouvelle réassignation M2 ; arrêter le playbook ne change aucun lead."
        ),
    },
    "risque_plaintes": {
        "nom": "Risque de plaintes clients",
        "declenche_par": [],
        "etapes": [
            _etape(
                "lire_incidents",
                "Relire les incidents et reports en cours chez M4",
                "information",
                port="m4_lire_retards_incidents",
                qui="m04-field-ops",
            ),
            _etape(
                "lire_qualite",
                "Relire les mesures des chantiers touchés (écarts de marge, reprises)",
                "information",
                port="m8_lire_mesures_chantier",
                qui="m08-analytics",
            ),
            _etape(
                "escalader",
                "Escalader chaque plainte reçue au propriétaire du dossier",
                "suivi_interne",
                depend_de=["lire_incidents"],
                port="m1_escalader_plainte",
                qui="m01-front-office",
            ),
            _etape(
                "engagement_client",
                "Décider d'un engagement envers le client (reprise, nouvelle date)",
                "action_sensible",
                depend_de=["escalader"],
                genre="contrat",
            ),
            _etape(
                "geste_commercial",
                "Décider d'un geste commercial ou d'une reprise de travaux à nos frais",
                "action_sensible",
                depend_de=["lire_qualite"],
                genre="depense_reelle",
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
                "arret_manuel_plainte",
                "Arrêter si la personne juge la plainte réglée ou portée en litige (aucun producteur ne mesure les "
                "plaintes)",
                "m4.retards_incidents",
                "",
                "manuel",
            )
        ],
        "limites": ["Aucun producteur capturé ne compte les plaintes : déclencheur déclaré par la personne."],
        "donnees_requises": ["m4.retards_incidents", "m8.mesures_chantier"],
        "departements": ["m01", "m04", "m08", "m09"],
        "risques": [
            "Une promesse faite au client sans capacité confirmée peut créer une seconde plainte.",
            "Un geste commercial crée un précédent pour d'autres clients.",
        ],
        "plan_retour": (
            "Une escalade se clôt chez M1 ; aucun engagement ni geste n'existe sans validation de Nathan ; "
            "arrêter le playbook laisse les incidents M4 tels quels."
        ),
    },
    "conversion_devis_faible": {
        "nom": "Conversion des devis faible",
        "declenche_par": [],
        "etapes": [
            _etape(
                "devis_sans_reponse",
                "Lister les devis restés sans réponse",
                "information",
                port="m3_detecter_devis_sans_reponse",
                qui="m03-estimation",
            ),
            _etape(
                "ecarts",
                "Relire les écarts estimé-réel des chantiers récents",
                "information",
                port="m3_lire_ecarts_estime_reel",
                qui="m03-estimation",
            ),
            _etape(
                "relancer",
                "Préparer les relances des devis sans réponse",
                "suivi_interne",
                depend_de=["devis_sans_reponse"],
                port="m2_preparer_relance",
                qui="m02-revenue-crm",
            ),
            _etape(
                "revoir_prix",
                "Décider d'une révision de la grille de prix",
                "action_sensible",
                depend_de=["ecarts"],
                genre="prix_global",
            ),
        ],
        "succes": [
            _critere(
                "conversion_cible",
                "Mesures de l'entonnoir au moins égales à la cible de la personne",
                "m8.vue_executive",
                "resultat.entonnoir.mesures[*].valeur",
                ">=",
                None,
                lier=True,
            )
        ],
        "arret": [
            _critere(
                "vue_absente",
                "La vue exécutive M8 n'est plus lisible",
                "m8.vue_executive",
                "resultat.entonnoir.mesures[*].metric_id",
                "aucun",
            )
        ],
        "limites": [
            "M9 ne calcule aucun taux de conversion : la mesure est celle de M8, la cible celle de la personne."
        ],
        "donnees_requises": ["m8.vue_executive", "m3.ecarts"],
        "departements": ["m02", "m03", "m08", "m09"],
        "risques": [
            "Baisser les prix pour convertir peut effacer la marge des chantiers.",
            "Relancer trop souvent peut nuire à l'image auprès des clients.",
        ],
        "plan_retour": (
            "Les relances non envoyées s'abandonnent ; une révision de prix se ramène à la grille antérieure par une "
            "nouvelle décision ; arrêter le playbook ne change aucun devis."
        ),
    },
    "roi_marketing_faible": {
        "nom": "Rendement marketing faible",
        "declenche_par": [],
        "etapes": [
            _etape(
                "lire_performance",
                "Relire la performance des campagnes sur la période",
                "information",
                port="m7_lire_performance_campagnes",
                qui="m07-marketing",
            ),
            _etape(
                "lire_couts",
                "Obtenir de M5 les coûts marketing affectés à la période",
                "information",
                qui="m05-financecore",
            ),
            _etape(
                "faire_calculer_roi",
                "Faire calculer le rendement par canal par M7 (M9 ne calcule aucun ROI)",
                "suivi_interne",
                depend_de=["lire_performance", "lire_couts"],
                port="m7_calculer_roi",
                qui="m07-marketing",
            ),
            _etape(
                "reallouer",
                "Décider de réallouer ou réduire le budget marketing",
                "action_sensible",
                depend_de=["faire_calculer_roi"],
                genre="budget_marketing",
            ),
        ],
        "succes": [
            _critere(
                "roi_juge",
                "La personne juge le rendement rétabli sur le calcul de M7",
                "m7.performance_campagnes",
                "",
                "manuel",
            )
        ],
        "arret": [
            _critere(
                "arret_manuel_marketing",
                "Arrêter si M7 ne peut plus rapprocher coûts et leads (sources non branchées)",
                "m7.performance_campagnes",
                "",
                "manuel",
            )
        ],
        "limites": ["Aucun ROI n'est calculé par M9 ; aucun coût publicitaire n'est publié dans les captures."],
        "donnees_requises": ["m7.performance_campagnes"],
        "departements": ["m05", "m07", "m09"],
        "risques": [
            "Couper un canal trop tôt peut supprimer des leads qui convertissent tard.",
            "Une attribution incomplète peut accuser le mauvais canal.",
        ],
        "plan_retour": (
            "Le budget antérieur se rétablit par une nouvelle décision M7 ; arrêter le playbook ne change aucune "
            "campagne."
        ),
    },
    "debut_de_saison": {
        "nom": "Préparation du début de saison",
        "declenche_par": [],
        "etapes": [
            _etape(
                "lire_cedule",
                "Relire la cédule des premières semaines",
                "information",
                port="m4_lire_cedule_semaine",
                qui="m04-field-ops",
            ),
            _etape(
                "verifier_stock",
                "Vérifier les matériaux disponibles et réservés",
                "information",
                port="m6_lire_disponibilite",
                qui="m06-material-control",
            ),
            _etape(
                "lire_tresorerie",
                "Relire la prévision de trésorerie M5 du début de saison",
                "information",
                port="m5_prevoir_tresorerie",
                qui="m05-financecore",
            ),
            _etape(
                "campagne",
                "Préparer la campagne saisonnière",
                "suivi_interne",
                port="m7_planifier_campagne_saisonniere",
                qui="m07-marketing",
            ),
            _etape(
                "commander_stock",
                "Décider des achats de matériaux de début de saison",
                "action_sensible",
                depend_de=["verifier_stock", "lire_tresorerie"],
                genre="achat_majeur",
            ),
            _etape(
                "embaucher_saisonniers",
                "Décider de l'embauche de saisonniers",
                "action_sensible",
                depend_de=["lire_cedule", "lire_tresorerie"],
                genre="embauche",
            ),
            _etape(
                "budget_saison",
                "Décider du budget de la campagne saisonnière",
                "action_sensible",
                depend_de=["campagne"],
                genre="budget_marketing",
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
                "prevision_non_calculable",
                "M5 ne peut plus calculer la prévision : arrêter et compléter les données",
                "m5.prevision_tresorerie",
                f"{_R}.calculable",
                "==",
                "false",
            )
        ],
        "limites": ["M9 n'a pas d'horloge : le début de saison est déclaré par la personne."],
        "donnees_requises": ["m4.cedule_semaine", "m6.disponibilite", "m5.prevision_tresorerie"],
        "departements": ["m04", "m05", "m06", "m07", "m09"],
        "risques": [
            "Commander trop tôt immobilise du cash avant les premiers encaissements.",
            "Embaucher avant que la cédule soit confirmée crée un coût sans chantier.",
        ],
        "plan_retour": (
            "Les bons de commande en brouillon s'annulent chez M6 ; la campagne non publiée s'abandonne chez M7 ; "
            "aucune embauche ni achat n'existe sans validation de Nathan."
        ),
    },
    "reserve_fin_de_saison": {
        "nom": "Réserve de fin de saison",
        "declenche_par": [],
        "etapes": [
            _etape(
                "lire_prevision",
                "Relire la prévision M5 couvrant la saison morte",
                "information",
                port="m5_prevoir_tresorerie",
                qui="m05-financecore",
            ),
            _etape(
                "lire_recevoir",
                "Relire les comptes à recevoir encore ouverts",
                "information",
                port="m5_lire_comptes_a_recevoir",
                qui="m05-financecore",
            ),
            _etape(
                "encaisser",
                "Préparer les relances des factures ouvertes avant la saison morte",
                "suivi_interne",
                depend_de=["lire_recevoir"],
                port="m5_lire_comptes_a_recevoir",
                qui="m05-financecore",
            ),
            _etape(
                "reporter_depenses",
                "Décider de reporter des dépenses à la prochaine saison",
                "action_sensible",
                depend_de=["lire_prevision"],
                genre="depense_reelle",
            ),
            _etape(
                "marge_de_credit",
                "Évaluer une marge de crédit pour la saison morte",
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
        "limites": ["Le montant de la réserve est celui de la personne ou de M5 : M9 n'en calcule aucun."],
        "donnees_requises": ["m5.prevision_tresorerie", "m5.comptes_a_recevoir"],
        "departements": ["m05", "m09"],
        "risques": [
            "Reporter une dépense d'entretien peut coûter plus cher au printemps.",
            "Une marge de crédit crée une dette et des frais : décision humaine seulement.",
        ],
        "plan_retour": (
            "Une dépense reportée se replanifie avec M5 ; une marge de crédit non signée s'abandonne ; arrêter le "
            "playbook laisse la prévision M5 inchangée."
        ),
    },
    "embauche": {
        "nom": "Embauche",
        "declenche_par": [],
        "etapes": [
            _etape(
                "lire_charge",
                "Relire la cédule des semaines à venir",
                "information",
                port="m4_lire_cedule_semaine",
                qui="m04-field-ops",
            ),
            _etape(
                "lire_incidents",
                "Relire les incidents et reports liés au manque de personnel",
                "information",
                port="m4_lire_retards_incidents",
                qui="m04-field-ops",
            ),
            _etape(
                "faire_calculer_masse_salariale",
                "Faire projeter par M5 l'effet de la masse salariale sur la trésorerie",
                "information",
                port="m5_prevoir_tresorerie",
                qui="m05-financecore",
            ),
            _etape(
                "decider_embauche",
                "Décider de l'embauche (poste, rémunération, date)",
                "action_sensible",
                depend_de=["lire_charge", "lire_incidents", "faire_calculer_masse_salariale"],
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
                "alerte_tresorerie",
                "La prévision M5 est en alerte de seuil : suspendre et revoir avec M5",
                "m5.prevision_tresorerie",
                f"{_R}.alerte.statut",
                "==",
                "ALERTE",
            )
        ],
        "limites": ["Aucune capacité d'équipe ni masse salariale n'est calculée par M9."],
        "donnees_requises": ["m4.cedule_semaine", "m4.retards_incidents", "m5.prevision_tresorerie"],
        "departements": ["m04", "m05", "m09"],
        "risques": [
            "Coût fixe durable si la demande baisse après l'embauche.",
            "Obligations du droit du travail : contrat et conditions relèvent de Nathan.",
        ],
        "plan_retour": (
            "Avant signature, abandonner la décision ne crée aucun engagement ; après signature, la fin d'emploi "
            "suit le droit du travail et relève de Nathan, hors de M9."
        ),
    },
    "achat_equipement": {
        "nom": "Achat d'équipement",
        "declenche_par": [],
        "etapes": [
            _etape(
                "documenter_besoin",
                "Documenter le besoin par les incidents et reports en cours",
                "information",
                port="m4_lire_retards_incidents",
                qui="m04-field-ops",
            ),
            _etape(
                "lire_tresorerie",
                "Relire la prévision de trésorerie M5",
                "information",
                port="m5_prevoir_tresorerie",
                qui="m05-financecore",
            ),
            _etape(
                "dossier_capital",
                "Préparer le dossier de décision d'investissement chez M5",
                "suivi_interne",
                depend_de=["documenter_besoin", "lire_tresorerie"],
                port="m5_preparer_decision_capital",
                qui="m05-financecore",
            ),
            _etape(
                "acheter",
                "Décider de l'achat",
                "action_sensible",
                depend_de=["dossier_capital"],
                genre="achat_majeur",
            ),
            _etape(
                "financer",
                "Décider d'un financement de l'équipement",
                "action_sensible",
                depend_de=["dossier_capital"],
                genre="dette",
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
                "alerte_tresorerie",
                "La prévision M5 est en alerte de seuil : suspendre l'achat",
                "m5.prevision_tresorerie",
                f"{_R}.alerte.statut",
                "==",
                "ALERTE",
            )
        ],
        "limites": ["Aucun rendement ni amortissement n'est calculé par M9 : le dossier est celui de M5."],
        "donnees_requises": ["m4.retards_incidents", "m5.prevision_tresorerie"],
        "departements": ["m04", "m05", "m09"],
        "risques": [
            "Un équipement sous-utilisé immobilise du cash.",
            "Un financement crée une dette : décision humaine seulement.",
        ],
        "plan_retour": (
            "Avant achat, abandonner le dossier M5 ne crée aucun engagement ; après achat, la revente relève de "
            "Nathan, hors de M9."
        ),
    },
    "expansion_ville": {
        "nom": "Expansion dans une nouvelle ville",
        "declenche_par": [],
        "etapes": [
            _etape(
                "demande_locale",
                "Relire les leads reçus de la ville visée (recherche M2)",
                "information",
                port="m2_lister_leads",
                qui="m02-revenue-crm",
            ),
            _etape(
                "concurrence",
                "Analyser la concurrence locale",
                "information",
                port="m7_analyser_concurrents",
                qui="m07-marketing",
            ),
            _etape(
                "lire_tresorerie",
                "Relire la prévision de trésorerie M5",
                "information",
                port="m5_prevoir_tresorerie",
                qui="m05-financecore",
            ),
            _etape(
                "campagne_locale",
                "Préparer une campagne locale d'essai",
                "suivi_interne",
                depend_de=["demande_locale", "concurrence"],
                port="m7_proposer_campagne_locale",
                qui="m07-marketing",
            ),
            _etape(
                "investir",
                "Décider de l'investissement d'ouverture",
                "action_sensible",
                depend_de=["lire_tresorerie", "campagne_locale"],
                genre="depense_reelle",
            ),
            _etape(
                "bail",
                "Décider d'un bail ou d'un engagement local",
                "action_sensible",
                depend_de=["investir"],
                genre="contrat",
            ),
            _etape(
                "conformite_locale",
                "Valider licences, assurances et obligations locales",
                "action_sensible",
                depend_de=["investir"],
                genre="decision_fiscale_ou_legale",
            ),
        ],
        "succes": [
            _critere(
                "leads_ville",
                "Total de leads lus (recherche de la ville) au moins égal à la cible de la personne",
                "m2.leads",
                f"{_R}.total",
                ">=",
                None,
                lier=True,
            )
        ],
        "arret": [
            _critere(
                "alerte_tresorerie",
                "La prévision M5 est en alerte de seuil : suspendre l'expansion",
                "m5.prevision_tresorerie",
                f"{_R}.alerte.statut",
                "==",
                "ALERTE",
            )
        ],
        "limites": ["Aucune donnée de marché n'est publiée par un producteur : aucune demande locale n'est estimée."],
        "donnees_requises": ["m2.leads", "m5.prevision_tresorerie"],
        "departements": ["m02", "m05", "m07", "m09"],
        "risques": [
            "Disperser les équipes sur deux territoires peut allonger les délais partout.",
            "Un bail local engage l'entreprise sur plusieurs années.",
        ],
        "plan_retour": (
            "La campagne d'essai non publiée s'abandonne chez M7 ; aucun investissement, bail ni démarche légale "
            "n'existe sans validation de Nathan ; arrêter le playbook ne change aucun lead."
        ),
    },
    "nouveau_service": {
        "nom": "Lancement d'un nouveau service",
        "declenche_par": [],
        "etapes": [
            _etape(
                "documenter",
                "Documenter la demande par un document de veille accepté et relié",
                "information",
                port="m9_lire_veille",
            ),
            _etape(
                "modele_soumission",
                "Préparer un modèle de soumission pour le service chez M3",
                "suivi_interne",
                depend_de=["documenter"],
                port="m3_lister_modeles_soumission",
                qui="m03-estimation",
            ),
            _etape(
                "fournisseurs",
                "Relire les fournisseurs des matériaux du service",
                "information",
                depend_de=["documenter"],
                port="m6_lister_fournisseurs",
                qui="m06-material-control",
            ),
            _etape(
                "fixer_prix",
                "Décider de la grille de prix du service",
                "action_sensible",
                depend_de=["modele_soumission"],
                genre="prix_global",
            ),
            _etape(
                "conformite",
                "Valider licences, assurances et garanties du service",
                "action_sensible",
                depend_de=["documenter"],
                genre="decision_fiscale_ou_legale",
            ),
            _etape(
                "investir",
                "Décider de l'investissement de lancement",
                "action_sensible",
                depend_de=["fixer_prix", "conformite"],
                genre="depense_reelle",
            ),
        ],
        "succes": [
            _critere(
                "marge_service",
                "Mesures des chantiers du service au moins égales à la cible de la personne",
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
        "limites": ["Aucune demande ni marge du service n'est estimée par M9 : mesures M8, cible de la personne."],
        "donnees_requises": ["m8.mesures_chantier"],
        "departements": ["m03", "m06", "m08", "m09"],
        "risques": [
            "Une compétence nouvelle mal maîtrisée peut générer des reprises et des plaintes.",
            "Un prix fixé sans historique peut être sous la marge réelle.",
        ],
        "plan_retour": (
            "Un modèle de soumission non utilisé se retire chez M3 ; aucun prix, investissement ni engagement légal "
            "n'existe sans validation de Nathan ; arrêter le playbook ne change aucun devis."
        ),
    },
    "relance_avis_clients": {
        "nom": "Relance des avis clients",
        "declenche_par": [],
        "etapes": [
            _etape(
                "chantiers_termines",
                "Relire les interventions complétées",
                "information",
                port="m4_lister_interventions",
                qui="m04-field-ops",
            ),
            _etape(
                "demandes_existantes",
                "Relire les demandes d'avis déjà faites",
                "information",
                port="m7_lister_demandes_avis",
                qui="m07-marketing",
            ),
            _etape(
                "preparer_demandes",
                "Préparer les demandes d'avis ; leur envoi passe par la file d'approbation M7, hors du playbook",
                "suivi_interne",
                depend_de=["chantiers_termines", "demandes_existantes"],
                port="m7_lister_file_approbation",
                qui="m07-marketing",
            ),
        ],
        "succes": [
            _critere(
                "avis_juges",
                "La personne juge le nombre d'avis reçus suffisant (aucun producteur capturé ne compte les avis)",
                "m4.interventions",
                "",
                "manuel",
            )
        ],
        "arret": [
            _critere(
                "consentement_retire",
                "Arrêter dès qu'un client refuse ou retire son consentement (Loi 25)",
                "m4.interventions",
                "",
                "manuel",
            )
        ],
        "limites": ["Aucun message n'est envoyé par le playbook : l'envoi reste dans la file d'approbation de M7."],
        "donnees_requises": ["m4.interventions"],
        "departements": ["m04", "m07", "m09"],
        "risques": [
            "Solliciter un client sans consentement contrevient à la Loi 25 et à la LCAP.",
            "Relancer un client insatisfait peut produire un avis négatif public.",
        ],
        "plan_retour": (
            "Les demandes préparées et non approuvées se retirent de la file M7 ; aucune demande n'est envoyée par "
            "le playbook."
        ),
    },
}
_LIMITES = (
    "Gabarits gouvernés : aucune étape n'est exécutée ni autorisée ; l'exécution passe par l'orchestrateur.",
    "Critères lus sur les captures des propriétaires ; une cible absente rend le critère INCONNU.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _code(nom: str) -> str:
    """``m05-financecore`` → ``m05`` ; ``m9`` → ``m09`` ; ``m4_lire_cedule_semaine`` → ``m04``."""
    numero = re.match(r"m(\d{1,2})", nom)
    if numero is None:
        raise ValueError(f"{nom} : département illisible")
    return f"m{int(numero.group(1)):02d}"


def verifier_catalogue(catalogue: Mapping[str, Mapping]) -> dict[str, dict]:
    """Valide chaque gabarit et rend le catalogue avec ``approbation_requise`` DÉRIVÉ ; refus nommé au premier écart."""
    regles = {regle.id for regle in risques.REGLES}
    verifie: dict[str, dict] = {}
    for id_, gabarit in catalogue.items():
        manquants = [champ for champ in CHAMPS if champ not in gabarit]
        if manquants:
            raise _refus("REJ-PLAYBOOK-GABARIT", f"{id_} : champs manquants {manquants}")
        if not isinstance(gabarit["plan_retour"], str) or not gabarit["plan_retour"].strip():
            raise _refus("REJ-PLAYBOOK-GABARIT", f"{id_} : plan de retour requis")
        if not gabarit["risques"] or not all(isinstance(r, str) and r.strip() for r in gabarit["risques"]):
            raise _refus("REJ-PLAYBOOK-GABARIT", f"{id_} : risques nommés requis")
        if not set(gabarit["declenche_par"]) <= regles:
            raise _refus("REJ-PLAYBOOK-GABARIT", f"{id_} : règle de déclenchement inconnue du radar")
        donnees = gabarit["donnees_requises"]
        if not donnees or len(set(donnees)) != len(donnees) or not set(donnees) <= set(catalogue_producteurs.PAR_ID):
            raise _refus("REJ-PLAYBOOK-GABARIT", f"{id_} : données requises absentes, en double ou hors catalogue")
        departements = gabarit["departements"]
        if not all(isinstance(d, str) and _CODE_DEPARTEMENT.fullmatch(d) for d in departements) or list(
            departements
        ) != sorted(set(departements)):
            raise _refus("REJ-PLAYBOOK-GABARIT", f"{id_} : départements m01…m10 triés et uniques requis")
        etapes = {e["id"]: e for e in gabarit["etapes"]}
        touches = {_code(catalogue_producteurs.PAR_ID[d].departement) for d in donnees}
        for etape in etapes.values():
            if etape["type"] not in TYPES_ETAPE or (etape["type"] == "action_sensible") != (etape["genre"] is not None):
                raise ValueError(f"{id_}.{etape['id']} : type d'étape incohérent")
            if etape["genre"] is not None and etape["genre"] not in conseil.ACTIONS_SENSIBLES:
                raise ValueError(f"{id_}.{etape['id']} : genre sensible inconnu")
            if not set(etape["depend_de"]) <= set(etapes):
                raise ValueError(f"{id_}.{etape['id']} : dépendance inconnue")
            touches.add(_code(etape["qui"]))
            if etape["port"] is not None:
                touches.add(_code(etape["port"]))
        if not touches <= set(departements):
            raise _refus(
                "REJ-PLAYBOOK-GABARIT", f"{id_} : départements non déclarés {sorted(touches - set(departements))}"
            )
        for critere in [*gabarit["succes"], *gabarit["arret"]]:
            if critere["operateur"] not in OPERATEURS or not critere["id"]:
                raise ValueError(f"{id_}.{critere['id']} : opérateur invalide")
            if critere["lecture"] not in donnees:
                raise _refus("REJ-PLAYBOOK-GABARIT", f"{id_}.{critere['id']} : lecture absente des données requises")
        approbation = any(e["type"] == "action_sensible" for e in etapes.values())
        if "approbation_requise" in gabarit and gabarit["approbation_requise"] is not approbation:
            raise _refus("REJ-PLAYBOOK-GABARIT", f"{id_} : approbation_requise contredit les étapes sensibles")
        verifie[id_] = {**gabarit, "approbation_requise": approbation}
    return verifie


CATALOGUE = verifier_catalogue(CATALOGUE)


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
        "donnees_requises": list(gabarit["donnees_requises"]),
        "departements": list(gabarit["departements"]),
        "risques": list(gabarit["risques"]),
        "approbation_requise": gabarit["approbation_requise"],
        "plan_retour": gabarit["plan_retour"],
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
