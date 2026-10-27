"""Portée par outil des rôles d'appareil, sur les départements RÉELS (PLAN T1.4-j).

La table de `docs/architecture/ROLES.md` est épinglée ici en entier pour `employee`, `seller` et
`admin` : élargir la portée d'un rôle exige de modifier la déclaration de l'outil (`Outil.
roles_appareil`), ce fichier et ROLES.md ensemble, donc de le faire exprès en relecture. Les
mécanismes (fermé par défaut, T3 jamais projeté, `opsys-metier verifier`) sont testés sur des départements
fictifs dans `tests/test_openclaw_roles.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from agents_base_qa import provisionner_base_qa

from opsys import appareils, cli, modeles, openclaw
from opsys.departements import charger_departements, tous_les_outils, verifier_portees

FICTIF = True  # aucune donnée réelle ici : des noms d'outils et un dossier de configuration jetable

# §9.3 (profil employé) : le chantier du jour, les transitions, le pointage, les preuves (dépôt de
# fichiers), la complétion, la déclaration des matériaux, et (T1.4-k, POLITIQUE-geolocalisation §4) le
# consentement GPS de SA personne. Rien qui lise les données des autres ni qui approuve : chaque outil
# ouvert à l'employé qui porte une identité ou une intervention la lie à la personne authentifiée
# (tests/test_acces_par_intervention.py).
EMPLOYE = frozenset({
    "m4_completer_intervention", "m4_creer_demande_ecart", "m4_definir_consentement_gps",
    "m4_demarrer_route", "m4_deposer_fichier", "m4_etat_fichier", "m4_lister_interventions", "m4_pointer",
    "m4_signaler_report", "m4_statut_intervention", "m6_declarer_materiaux_utilises",
    "m6_lire_contexte_materiaux_appareil", "m6_declarer_materiaux_avec_preuves_appareil",
    # M7 : enregistrer un consentement de référence et importer/lire les avis non privés;
    # les plaintes privées et les décisions/exports/publications restent fermés à ce rôle.
    "m7_enregistrer_consentement_reference", "m7_importer_avis_manuel", "m7_lister_inbox_reputation",
})

# §9.4 (profil vendeur) : ses leads, le Client 360, les soumissions de ses leads (M2, M3). Aucun outil
# M4, M5, M6, M7, M8, M9 ni M10 : ni finances, ni prix fournisseurs, ni coûts réels.
VENDEUR = frozenset({
    "m2_enregistrer_interaction", "m2_evaluer_readiness", "m2_lister_leads", "m2_obtenir_client_360",
    "m2_suggerer_prochaine_action", "m2_transitionner_statut", "m2_trouver_client_de_lead",
    # relances autorisées (§9.4, T4.9) : SES relances, le consentement qu'il a recueilli, une relance préparée
    "m2_lister_relances", "m2_preparer_relance", "m2_enregistrer_consentement_contact",
    "m3_generer_soumission_brouillon", "m3_lire_devis", "m3_lister_devis", "m3_qualifier_photos",
    "m3_demander_envoi_devis",  # DEMANDE l'envoi d'un devis (N4, T4.7) : le propriétaire décide dans la file
})

# §9.5 (profil admin / propriétaire) : ce que fait l'employé et le vendeur, plus ce que le propriétaire
# ou son gestionnaire décide ou consulte depuis son téléphone.
ADMIN_SEUL = frozenset({
    "m1_produire_digest", "m1_importer_appel_manuellement",
    "m1_lire_transfert", "m1_clore_transfert",  # transferts à un humain : lire, clore en personne (T4.5)
    "m1_lister_rappels_appareil", "m1_prendre_en_charge_rappel_appareil",
    "m2_arbitrer_doublon", "m2_detecter_doublons", "m2_produire_digest", "m2_signaler_doublon",
    # réassigner un lead (décision humaine) et republier le fait de propriété d'avant T1.4-k2 (T1.4-m)
    "m2_reassigner_lead", "m2_republier_assignations",
    "m2_corriger_contact_client", "m2_lister_historique_contact_client",
    "m2_reconcilier_memoire_contact_client",  # correction humaine et lectures privées CRM-04
    "m3_lister_devis_lead_admin",  # inventaire par lead, distinct du lecteur vendeur
    # Calibration du temps M3 : lecture/évaluation, candidate inactive et demandes de décision N4.
    "m3_evaluer_calibration_cohortes", "m3_proposer_calibration_temps", "m3_evaluer_candidate_calibration",
    "m3_activer_candidate_calibration", "m3_rollback_candidate_calibration",
    "m3_auditer_couverture_apprentissage", "m3_lire_apprentissage_chantier",  # lectures admin confirmées
    "m4_appliquer_cedule", "m4_confirmer_localisation", "m4_lire_position_gps", "m4_lister_pending_review",
    "m4_produire_brouillon_temps", "m4_produire_digest", "m4_proposer_cedule", "m4_proposer_localisation",
    "m4_resoudre_demande", "m4_resoudre_revue_completion", "m4_verifier_preparation",  # préparation (T4.10-b)
    # Dossier courant/historique N0 et création P N4 ; exécution signée par le propriétaire sous D distinct.
    "m4_lire_dossier_revue_completion_appareil", "m4_resoudre_revue_completion_sources",
    "m4_lire_faits_calibration_m3",  # preuve M4 vérifiée consommée par la calibration de M3
    "m4_verifier_meteo_creneau",  # la météo d'un plan de cédule : dispatch de l'admin (T4.13)
    "m4_lire_meteo_intervention",  # la météo du créneau d'une intervention, sans plan_id : dispatch (T4.27-a)
    "m4_lire_retards_incidents",  # les reports en cours et les incidents ouverts : dispatch de l'admin (T4.27-a)
    # Sources horaires individuelles : aperçu et validation courante privés, aucun accès employé/vendeur.
    "m4_previsualiser_heures_regulieres", "m4_lire_heures_regulieres_validees",
    "m4_volumetrie_pending_review",
    "m4_confirmer_dates_cedule", "m4_lire_calendrier_plan", "m4_lire_cedule_semaine",
    "m4_lire_journal_quotidien",  # transport console admin; garde interne refuse MCP/appareil/agent
    "m4_lire_composition_journaliere_console",  # même transport privé, aucune autorité de compte ajoutée
    "m5_etat_tresorerie", "m5_lister_attentes_facturation",
    "m5_lire_rentabilite_chantier", "m5_lire_comptes_a_recevoir",  # coût réel, marge, créances (T1.5-d)
    "m5_lister_comptes_a_payer", "m5_saisir_facture_fournisseur",  # comptes à payer, saisie par un humain (T4.15)
    # T4.15-c : facture sans PO (N3), correction et annulation d'une facture saisie (N4 : l'appel de l'admin attend le
    # propriétaire ou la finance ; par la voie directe, la PERSONNE doit porter nathan_owner ou finance)
    "m5_saisir_facture_sans_po", "m5_corriger_facture_fournisseur", "m5_annuler_facture_fournisseur",
    "m5_lire_echeances_fiscales",  # calendrier fiscal vivant, TPS/TVQ (T4.16)
    "m5_lire_calendrier_obligations",  # échéances avec origine et fraîcheur, lecture admin seulement (T4.16)
    # Déclarations préparatoires séparées : lecture pure et annotation interne DEVICE, sans flux financiers.
    "m5_lire_obligations_preparees_appareil", "m5_enregistrer_obligation_preparee_appareil",
    "m5_prevoir_tresorerie",  # prévision de trésorerie des flux connus et datés, lecture pure (T4.16-d)
    "m5_preparer_decision_capital",  # comparaison financière indicative, sans commande ni paiement
    "m5_preparer_dossier_decision_cfo",  # dossier préparatoire de direction, lecture pure des sources M5
    # Contrat privé CAD : écritures humaines N4 et lecteur courant, sans élargir le droit d'agent CFO.
    "m5_enregistrer_contrat_horaire", "m5_revoquer_contrat_horaire", "m5_lire_contrat_horaire",
    # le cash libre constaté et publié au bus pour M8 : écriture interne (T1, N3), l'admin qui voit les coûts
    "m5_constater_cash_libre",
    "m6_annuler_po", "m6_approuver_po", "m6_evaluer_variance_chantier", "m6_produire_digest",
    "m6_receptionner_commande", "m6_soumettre_comptage",
    # réservation, emplacements, disponibilité : l'admin seulement (T4.14) ; jamais l'employé ni le vendeur
    "m6_reserver_materiel", "m6_liberer_reservation", "m6_transferer_stock", "m6_lire_disponibilite",
    "m6_lister_wct_pertes_appareil", "m6_lire_pertes_alertes_wct_appareil",
    "m6_lire_reapprovisionnement_appareil", "m6_lire_preuves_pertes_wct_appareil",
    # Classement humain des six causes : annotation N3, lecteurs N0, admin DEVICE seulement.
    "m6_lister_variances_classables_wct_appareil", "m6_classer_cause_variance_appareil",
    "m6_lire_historique_classement_variance_appareil",
    "m6_enregistrer_note_commande", "m6_lire_note_commande", "m6_lister_notes_commande",
    "m7_lister_file_approbation", "m7_lister_demandes_avis",  # avis à relire avant d'écrire au client (T1.5-d)
    "m7_approuver_budget_campagne", "m7_configurer_profil_marque",  # décisions propriétaires Brand/Growth
    "m7_decider_creneau_calendrier", "m7_decider_reponse_avis",  # décisions propriétaires avant tout export
    "m7_exporter_creneau_manuel", "m7_exporter_reponse_avis_manuel", "m7_lister_calendrier",
    "m7_lire_performance_campagnes",  # lecture des conversions et marges attribuées, admin seulement
    # usine à contenu (T4.17) : le propriétaire lit, décide, prend le paquet à publier, enregistre un retrait
    "m7_lister_contenus_chantier", "m7_decider_contenu", "m7_exporter_paquet_manuel",
    "m7_enregistrer_retrait_consentement_marketing",
    "m8_lire_mesures_chantier", "m8_performance_equipe",
    "m8_lire_vue_executive",  # tableau de bord exécutif : entonnoir, marge de M5, stock de M6 (T4.19)
    "m8_lire_mesures_contenus",  # ce que chaque contenu de M7 amène : leads et devis par utm_content (T4.17-e)
    "m8_lire_provenance_m5_appareil",  # diagnostic N0 DEVICE, publications/receipts M5, sans calcul financier
    "m9_decider_demande_approbation", "m9_lire_alertes_m8", "m9_lire_etat_consolide", "m9_lire_suite_briefing",
    "m9_lister_demandes_approbation", "m9_produire_briefing_matin", "m9_produire_lecture_strategique",
    "m9_preparer_dossier_direction",  # dossier préparatoire sourcé T0/N0, admin seulement
    "m9_diagnostiquer_dossier_direction",  # dossier serveur et diagnostic temporel T0/N0, admin seulement
    # Suivi interne : lectures N0 et ouverture N3 sous SA demande dédiée signée par le propriétaire.
    "m9_preparer_suivi_decision", "m9_ouvrir_suivi_decision", "m9_lire_suivi_decision",
    "m9_preparer_cloture_suivi_decision", "m9_clore_suivi_decision", "m9_lister_suivis_decision",
    "m9_bilan_suivis_decision", "m9_rapport_periode", "m9_observations_chantier_periode",
    "m9_rapport_activite_periode",
    "m9_auditer_affirmations_conseil",  # citations structurées, lecture T0/N0 admin seulement
    "m10_arbitrer_revision", "m10_paquet_contexte_affaire", "m10_statut_decision", "m10_statut_revision",
    "m10_lister_signaux", "m10_lister_references", "m10_lire_revision", "m10_prendre_en_compte_signal",
    "m10_clore_signal", "m10_lier_session_affaire",
    # Lecture DEVICE distincte du contexte privé Core : admin actuel, agent=None, sans artefact.
    "m10_lire_paquet_affaire_appareil", "m10_rechercher_affaire_appareil",
    # Mutations documentaires nommées : admin DEVICE courant, N3 et affaire autorisée.
    "m10_deposer_version_document_appareil", "m10_activer_version_document_appareil",
    "m10_retirer_document_appareil",
    # Lectures documentaires T0/N0 : admin DEVICE courant, aucune intention.
    "m10_lister_documents_affaire_appareil", "m10_lire_version_document_affaire_appareil",
})
# Le lecteur paginé M3 est réservé au vendeur courant : l'admin ne choisit pas un vendeur
# par argument et ne reçoit pas ce tool. Le lecteur de chantier et le diagnostic sont admin.
ADMIN = (EMPLOYE | VENDEUR | ADMIN_SEUL) - {"m3_lister_devis"}

# Outils de l'usine à contenu (T4.17) : jamais l'employé ni le vendeur (le contenu du propriétaire, ses décisions,
# le retrait d'un consentement) ; `m7_proposer_contenus_chantier` et `m7_lire_matiere_chantier` sont ceux de l'agent
# seulement (aucun appareil : le brouillon naît du bus, la matière sert le modèle qui rédige).
USINE_A_CONTENU_ADMIN = frozenset({
    "m7_lister_contenus_chantier", "m7_decider_contenu", "m7_exporter_paquet_manuel",
    "m7_enregistrer_retrait_consentement_marketing",
})
USINE_A_CONTENU_AGENT = frozenset({"m7_proposer_contenus_chantier", "m7_lire_matiere_chantier"})

# Les autres outils M7 sont admin seulement. Les avis importés par un employé restent limités aux avis
# non privés (test M7 de l'inbox durable); aucune décision, aucun export ni publication n'est ouvert.
MARKETING_ADMIN_SEUL = frozenset({
    "m7_approuver_budget_campagne", "m7_configurer_profil_marque", "m7_decider_creneau_calendrier",
    "m7_decider_reponse_avis", "m7_exporter_creneau_manuel", "m7_exporter_reponse_avis_manuel",
    "m7_lister_calendrier", "m7_lire_performance_campagnes",
})

# Outils qu'AUCUN appareil ne peut appeler, avec la raison. Ils restent appelables par les agents
# (serveur MCP du département), sauf le brut régulier qui exige le propriétaire via console.
FERMES_A_TOUS = {
    "m4_lire_outbox": "WCT complets : positions GPS et identités de tous les techniciens ; outil des modules aval",
    "m6_consommer_materiaux": "prend encore un WCT fourni par l'appelant (remplacé par m6_declarer_materiaux_utilises)",
    "m4_planifier_intervention": "cédule calculée par l'agent, avec un marqueur de readiness signé par M2",
    "m4_annuler_intervention": "décision de répartition, pas dans §9.5",
    "m4_notifier_client_completion": "message au client (N4), étape de la cascade §6",
    "m3_estimer_projet": "le barème et le plancher rentable viendraient de l'appelant",
    "m3_creer_devis": "le coût de chaque ligne et le taux de marge viendraient de l'appelant",
    "m3_lire_ecarts_estime_reel": "durées et coûts réels : boucle de calibration, agents seulement",
    "m6_enregistrer_prix": "livre de prix : coût fournisseur officiel",
    "m6_enregistrer_fournisseur": "le courriel de commande d'un fournisseur redirige les PO",
    "m6_enregistrer_besoins_prevus": "le prévu vient du devis accepté (m3.devis_accepte), pas d'un téléphone",
    "m6_marquer_po_envoye": "engagement externe (N4) : passe par la file d'approbation",
    "m5_creer_facture_brouillon": "étape de la cascade §6 (M5), pas une action de téléphone",
    "m5_envoyer_facture": "engagement client (N4) : passe par la file d'approbation",
    "m5_preparer_brut_regulier": "propriétaire confirmé via console seulement ; aucun jeton d'appareil ni agent",
    "m1_transferer": "jugement de l'agent dans la session d'un client (N2) ; l'employé qui signale : à faire",
    "m1_escalader_plainte": "jugement de l'agent dans la session d'un client (N2) ; les règles l'ouvrent déjà",
    "m2_ingerer_lead": "ingestion du contrat M1 -> M2, pas une saisie de téléphone",
    "m2_marquer_chantier_termine": "écrit par la cascade « travaux terminés » (auteur system:m4)",
    "m8_rapport_metriques": "ingère un snapshot fourni par l'appelant dans le registre de vérité chiffrée",
    "m9_etat_consolide": "ingère un snapshot fourni par l'appelant dans le registre consolidé",
    "m7_auditer_seo_site": "prend un chemin de dossier du serveur",
    "m7_calculer_roi": "prend des chemins de fichiers du serveur",
    "m10_affaire_de_la_session": "lien session -> affaire : lu par le moteur de contexte du core seulement",
}


@pytest.fixture(scope="module")
def departements_reels():
    return charger_departements()


@pytest.fixture(scope="module")
def roles_reels(departements_reels):
    return openclaw.roles_outils(departements_reels)


def test_table_de_l_employe_epinglee(roles_reels):
    assert set(roles_reels["employee"]) == EMPLOYE


def test_table_du_vendeur_epinglee(roles_reels):
    assert set(roles_reels["seller"]) == VENDEUR


def test_table_de_l_admin_epinglee(roles_reels):
    assert set(roles_reels["admin"]) == ADMIN


def test_les_compteurs_ecrits_dans_roles_md_suivent_les_manifestes(departements_reels, roles_reels):
    """« N outils sur M sont déclarés » et « ### `role` (K outils) » de ROLES.md suivent les manifestes. Deux
    intégrations qui ajoutent chacune un outil écrivent la MÊME ligne : git les fusionne sans conflit et laisse un
    compte faux (arrivé avec T4.19 et T4.16-d). Ce test le voit."""
    texte = (Path(__file__).resolve().parents[1] / "docs" / "architecture" / "ROLES.md").read_text(encoding="utf-8")
    index = tous_les_outils(departements_reels.values())
    declares = sum(1 for _dep, outil in index.values() if outil.roles_appareil)
    entete = re.search(r"(\d+) outils sur (\d+) sont déclarés\.", texte)
    assert entete is not None, "ROLES.md : la phrase « N outils sur M sont déclarés. » a disparu"
    assert (int(entete.group(1)), int(entete.group(2))) == (declares, len(index))
    for role, outils in roles_reels.items():
        titre = re.search(rf"^### `{role}` \((\d+) outils\)", texte, re.MULTILINE)
        assert titre is not None, f"ROLES.md : pas de section « ### `{role}` (K outils) »"
        assert int(titre.group(1)) == len(outils), role


@pytest.mark.parametrize(("nom", "autonomie", "niveau"), [
    ("m9_preparer_suivi_decision", "T0", "N0"),
    ("m9_ouvrir_suivi_decision", "T1", "N3"),
    ("m9_lire_suivi_decision", "T0", "N0"),
    ("m9_lister_suivis_decision", "T0", "N0"),
    ("m9_bilan_suivis_decision", "T0", "N0"),
    ("m9_rapport_periode", "T0", "N0"),
    ("m9_observations_chantier_periode", "T0", "N0"),
    ("m9_rapport_activite_periode", "T0", "N0"),
    ("m9_auditer_affirmations_conseil", "T0", "N0"),
    ("m9_preparer_cloture_suivi_decision", "T0", "N0"),
    ("m9_clore_suivi_decision", "T1", "N3"),
])
def test_suivi_m9_projete_admin_aux_niveaux_prevus(departements_reels, roles_reels, nom, autonomie, niveau):
    outil = tous_les_outils(departements_reels.values())[nom][1]
    assert outil.roles_appareil == frozenset({"admin"})
    assert outil.autonomie.value == autonomie and outil.niveau_effectif.value == niveau
    assert nom in roles_reels["admin"]
    assert nom not in roles_reels["employee"] and nom not in roles_reels["seller"]


@pytest.mark.parametrize(("nom", "autonomie", "niveau"), [
    ("m6_lister_variances_classables_wct_appareil", "T0", "N0"),
    ("m6_classer_cause_variance_appareil", "T1", "N3"),
    ("m6_lire_historique_classement_variance_appareil", "T0", "N0"),
])
def test_classement_variance_humain_reste_admin_et_annotation_interne(
    departements_reels, roles_reels, nom, autonomie, niveau,
):
    index = tous_les_outils(departements_reels.values())
    assert nom in index, "les trois outils réels doivent être enregistrés avant leur projection"
    outil = index[nom][1]
    assert outil.roles_appareil == frozenset({"admin"})
    assert nom in roles_reels["admin"]
    assert nom not in roles_reels["employee"] and nom not in roles_reels["seller"]
    assert outil.autonomie.value == autonomie and outil.niveau_effectif.value == niveau
    assert not outil.frontiere_humaine
    if autonomie == "T1":
        assert outil.portee_contexte == "affaire"
        assert outil.cible_contexte == ("selection", "wct_id")
        assert outil.identite_contexte == "wct"


def test_l_usine_a_contenu_est_au_proprietaire_et_l_agent_seul_ecrit_les_brouillons(roles_reels, departements_reels):
    assert set(roles_reels["admin"]) >= USINE_A_CONTENU_ADMIN
    for role in ("employee", "seller"):
        assert not (USINE_A_CONTENU_ADMIN | USINE_A_CONTENU_AGENT) & set(roles_reels[role])
    assert not USINE_A_CONTENU_AGENT & set(roles_reels["admin"])
    index = tous_les_outils(departements_reels.values())
    assert set(index) >= (USINE_A_CONTENU_ADMIN | USINE_A_CONTENU_AGENT)
    assert not index["m7_decider_contenu"][1].frontiere_humaine  # N3 : la validation au départ suffit au propriétaire


def test_employe_ne_recoit_ni_actions_marketing_admin_ni_publication(roles_reels, departements_reels):
    index = tous_les_outils(departements_reels.values())
    assert set(roles_reels["admin"]) >= MARKETING_ADMIN_SEUL
    for role in ("employee", "seller"):
        assert not MARKETING_ADMIN_SEUL & set(roles_reels[role])
    assert "m7_publier_post_social" in index
    assert index["m7_publier_post_social"][1].frontiere_humaine
    for _role, outils in roles_reels.items():
        assert "m7_publier_post_social" not in outils
    # Les seuls accès employé à l'inbox sont l'import manuel et une liste qui masque les avis privés.
    assert {outil for outil in roles_reels["employee"] if outil.startswith("m7_")} == {
        "m7_enregistrer_consentement_reference", "m7_importer_avis_manuel", "m7_lister_inbox_reputation",
    }


def test_les_trois_roles_d_appareil_sont_les_seules_cles(roles_reels):
    assert set(roles_reels) == appareils.ROLES_APPAREIL == {"employee", "seller", "admin"}


@pytest.mark.parametrize("outil", ["m4_lire_outbox", "m6_approuver_po"])
def test_outils_qui_lisent_ou_approuvent_pour_les_autres_absents_de_l_employe(roles_reels, outil):
    """Le défaut corrigé : avant T1.4-j, `employee` recevait tout M4 et M6 hors T3."""
    assert outil not in roles_reels["employee"]
    assert outil not in roles_reels["seller"]


@pytest.mark.parametrize("outil", [
    "m4_lire_outbox", "m4_lire_position_gps", "m4_resoudre_demande",
    "m4_resoudre_revue_completion", "m4_lister_pending_review", "m4_produire_brouillon_temps",
    "m4_produire_digest", "m6_approuver_po", "m6_annuler_po", "m6_consommer_materiaux",
    "m6_receptionner_commande", "m6_soumettre_comptage", "m6_produire_digest", "m5_etat_tresorerie",
    "m3_lire_devis", "m2_transitionner_statut", "m10_paquet_contexte_affaire",
    "m10_lire_paquet_affaire_appareil", "m10_rechercher_affaire_appareil",
    "m4_confirmer_localisation", "m4_proposer_localisation",  # l'adresse d'un client : jamais l'employé (T4.1-a)
    "m4_proposer_cedule", "m4_appliquer_cedule",  # la cédule par tournées : dispatch de l'admin (T4.1-d)
    "m4_verifier_preparation",  # l'état d'un chantier de client : dispatch de l'admin (T4.10-b)
    "m4_verifier_meteo_creneau",  # les créneaux d'un plan (chantiers de clients) : dispatch de l'admin (T4.13)
    "m4_lire_meteo_intervention",  # le créneau d'un chantier de client : dispatch de l'admin (T4.27-a)
    "m4_lire_retards_incidents",  # les reports et les incidents de tous : dispatch de l'admin (T4.27-a)
    "m6_reserver_materiel", "m6_liberer_reservation",  # réservation par chantier (T4.14)
    "m6_transferer_stock", "m6_lire_disponibilite", "m6_lister_wct_pertes_appareil",
    "m6_lire_pertes_alertes_wct_appareil", "m6_lire_reapprovisionnement_appareil",  # lectures admin M6
])
def test_l_employe_ne_lit_ni_n_approuve_rien_des_autres(roles_reels, outil):
    assert outil not in roles_reels["employee"]


@pytest.mark.parametrize("outil", [
    "m5_etat_tresorerie", "m5_lister_attentes_facturation", "m6_approuver_po", "m6_receptionner_commande",
    "m6_produire_digest", "m6_lire_contexte_materiaux_appareil", "m6_enregistrer_prix",
    "m3_lire_ecarts_estime_reel", "m3_creer_devis",
    "m3_estimer_projet", "m4_lire_outbox", "m9_produire_briefing_matin", "m8_rapport_metriques",
    "m4_confirmer_localisation", "m4_proposer_localisation", "m4_proposer_cedule", "m4_appliquer_cedule",
    "m4_verifier_preparation", "m4_verifier_meteo_creneau", "m6_reserver_materiel", "m6_liberer_reservation",
    "m6_transferer_stock", "m6_lire_disponibilite", "m6_lister_wct_pertes_appareil",
    "m6_lire_pertes_alertes_wct_appareil", "m6_lire_reapprovisionnement_appareil",
    "m4_lire_meteo_intervention", "m4_lire_retards_incidents",
])
def test_le_vendeur_n_a_ni_finances_ni_couts_du_proprietaire(roles_reels, outil):
    assert outil not in roles_reels["seller"]


@pytest.mark.parametrize(("outil", "raison"), sorted(FERMES_A_TOUS.items()))
def test_outils_fermes_a_tous_les_appareils_admin_compris(departements_reels, roles_reels, outil, raison):
    index = tous_les_outils(departements_reels.values())
    assert outil in index, f"{outil} n'existe plus : retirer l'entrée ({raison})"
    for role, outils in roles_reels.items():
        assert outil not in outils, f"{outil} ({raison}) ne doit pas être dans {role}"


def test_aucun_outil_t3_ni_n5_dans_aucun_role(departements_reels, roles_reels):
    index = tous_les_outils(departements_reels.values())
    frontieres = {nom for nom, (_dep, outil) in index.items() if outil.frontiere_humaine}
    # Les cinq frontières humaines réelles existent bien (le test ne passe pas à vide).
    assert {"m3_marquer_devis_accepte", "m4_purger_retention_gps", "m5_enregistrer_mouvement",
            "m5_enregistrer_paiement_facture", "m7_publier_post_social"} <= frontieres
    for role, outils in roles_reels.items():
        assert not frontieres & set(outils), f"{role} contient {sorted(frontieres & set(outils))}"


def test_un_outil_sans_declaration_n_est_dans_aucun_role(departements_reels, roles_reels):
    """Fermé par défaut, vérifié sur tous les outils réels : la table n'est rien d'autre que les
    déclarations, dans les deux sens."""
    index = tous_les_outils(departements_reels.values())
    assert index
    dans_un_role = {role: set(outils) for role, outils in roles_reels.items()}
    for nom, (_dep, outil) in index.items():
        for role in appareils.ROLES_APPAREIL:
            attendu = role in outil.roles_appareil and not outil.frontiere_humaine
            assert (nom in dans_un_role[role]) == attendu, (nom, role)


def test_les_declarations_reelles_passent_opsys_verifier(departements_reels):
    assert verifier_portees(departements_reels) == []


def test_opsys_openclaw_configurer_ecrit_le_fragment_roles_json_reel(
    session, departements_reels, tmp_path, monkeypatch, capsys
):
    """La commande réelle, sur les départements réels : `roles.json` est `roles_outils`, sans T3."""
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", "http://embeddings-test:11434/v1")
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "bge-m3")
    modeles.enregistrer_paliers({
        "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
        "fort": {"provider": "anthropic", "model": "claude-sonnet-5"},
        "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
    })
    provisionner_base_qa(session, departements_reels)
    config = tmp_path / "oc"

    assert cli.main(["openclaw", "configurer", "--config-dir", str(config)]) == 0

    capsys.readouterr()
    fragment = json.loads((config / "opsys" / "roles.json").read_text(encoding="utf-8"))
    assert set(fragment) == {"roles", "serveurs"}
    roles = fragment["roles"]
    assert set(roles) == {"employee", "seller", "admin"}
    assert set(roles["employee"]) == EMPLOYE
    assert set(roles["seller"]) == VENDEUR
    assert set(roles["admin"]) == ADMIN
    for outil in ("m4_lire_outbox", "m6_approuver_po", "m4_lire_position_gps"):
        assert outil not in roles["employee"]
    tout = {nom for outils in roles.values() for nom in outils}
    assert not tout & {"m3_marquer_devis_accepte", "m4_purger_retention_gps", "m5_enregistrer_mouvement",
                       "m5_enregistrer_paiement_facture", "m7_publier_post_social"}

    # T1.4-c6 : chaque outil d'un rôle porte son serveur, et ce serveur est déclaré dans `mcp.json`.
    serveurs = fragment["serveurs"]
    assert set(serveurs) == tout
    declares = json.loads((config / "opsys" / "mcp.json").read_text(encoding="utf-8"))["servers"]
    for outil, serveur in serveurs.items():
        assert serveur == f"opsys_{outil.split('_', 1)[0]}", outil
        assert serveur in declares, (outil, serveur)


# -- Le nom que l'app envoie est celui du moteur (T1.4-c6) --------------------------------------

@pytest.mark.parametrize("nom, autonomie, niveau", [
    ("m1_lister_rappels_appareil", "T0", "N0"),
    ("m1_prendre_en_charge_rappel_appareil", "T1", "N2"),
])
def test_rappels_importes_device_admin_sans_ouvrir_writer_console(departements_reels, nom, autonomie, niveau):
    index = tous_les_outils(departements_reels.values())
    _, outil = index[nom]
    assert outil.autonomie.value == autonomie and outil.niveau_effectif.value == niveau
    assert outil.roles_appareil == frozenset({"admin"})
    assert index["m1_consigner_suivi_rappel"][1].roles_appareil == frozenset()
    if niveau == "N2":
        assert set(outil.parametres["properties"]) == {"transfert_id", "snapshot_attendu"}
        assert outil.parametres["additionalProperties"] is False
        assert outil.portee_contexte is None  # Un transfert n'est pas une affaire M10 inventée.

RACINE = Path(__file__).resolve().parents[1]
NOM_D_OUTIL = re.compile(r'"(m\d+_[a-z0-9_]+)"')


def _noms_d_outils_de_l_app() -> set[str]:
    """Chaque littéral `"mN_..."` des sources de l'app (hors tests) : les appels `/tools/invoke`."""
    noms: set[str] = set()
    for dossier in (RACINE / "mobile" / "src", RACINE / "mobile" / "app"):
        for chemin in sorted(dossier.rglob("*")):
            if chemin.suffix not in {".ts", ".tsx"} or ".test." in chemin.name:
                continue
            noms.update(NOM_D_OUTIL.findall(chemin.read_text(encoding="utf-8")))
    return noms


def test_les_noms_d_outils_de_l_app_sont_des_outils_du_moteur_que_le_core_sait_appeler(departements_reels):
    """Un seul nom de l'app au moteur : le nom NU. Celui que l'app envoie existe dans un
    département, est permis à au moins un rôle et a son serveur dans `roles.json`. Un nom fautif
    (faute de frappe, préfixe de serveur `opsys_m4__`) serait sinon un 404 ou un 403 en production."""
    index = tous_les_outils(departements_reels.values())
    serveurs = openclaw.serveurs_outils(departements_reels)
    de_l_app = _noms_d_outils_de_l_app()

    # Le test ne passe pas à vide : les outils des écrans connus y sont.
    assert {"m4_pointer", "m4_lister_interventions", "m9_decider_demande_approbation"} <= de_l_app
    for nom in sorted(de_l_app):
        assert nom in index, f"l'app appelle {nom}, qui n'est l'outil d'aucun département"
        assert nom in serveurs, f"l'app appelle {nom}, qu'aucun rôle d'appareil ne peut appeler"
