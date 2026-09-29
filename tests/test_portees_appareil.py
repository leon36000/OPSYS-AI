"""Portée par outil des rôles d'appareil, sur les départements RÉELS (PLAN T1.4-j).

La table de `docs/architecture/ROLES.md` est épinglée ici en entier pour `employee`, `seller` et
`admin` : élargir la portée d'un rôle exige de modifier la déclaration de l'outil (`Outil.
roles_appareil`), ce fichier et ROLES.md ensemble, donc de le faire exprès en relecture. Les
mécanismes (fermé par défaut, T3 jamais projeté, `opsys verifier`) sont testés sur des départements
fictifs dans `tests/test_openclaw_roles.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

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
})

# §9.4 (profil vendeur) : ses leads, le Client 360, les soumissions de ses leads (M2, M3). Aucun outil
# M4, M5, M6, M7, M8, M9 ni M10 : ni finances, ni prix fournisseurs, ni coûts réels.
VENDEUR = frozenset({
    "m2_enregistrer_interaction", "m2_evaluer_readiness", "m2_obtenir_client_360",
    "m2_suggerer_prochaine_action", "m2_transitionner_statut", "m2_trouver_client_de_lead",
    "m3_generer_soumission_brouillon", "m3_lire_devis", "m3_qualifier_photos",
})

# §9.5 (profil admin / propriétaire) : ce que fait l'employé et le vendeur, plus ce que le propriétaire
# ou son gestionnaire décide ou consulte depuis son téléphone.
ADMIN_SEUL = frozenset({
    "m1_produire_digest",
    "m2_arbitrer_doublon", "m2_detecter_doublons", "m2_produire_digest", "m2_signaler_doublon",
    "m4_appliquer_cedule", "m4_confirmer_localisation", "m4_lire_position_gps", "m4_lister_pending_review",
    "m4_produire_brouillon_temps", "m4_produire_digest", "m4_proposer_cedule", "m4_proposer_localisation",
    "m4_resoudre_demande", "m4_resoudre_revue_completion", "m4_volumetrie_pending_review",
    "m5_etat_tresorerie", "m5_lister_attentes_facturation",
    "m5_lire_rentabilite_chantier", "m5_lire_comptes_a_recevoir",  # coût réel, marge, créances (T1.5-d)
    "m6_annuler_po", "m6_approuver_po", "m6_evaluer_variance_chantier", "m6_produire_digest",
    "m6_receptionner_commande", "m6_soumettre_comptage",
    "m7_lister_file_approbation",
    "m9_decider_demande_approbation", "m9_lire_alertes_m8", "m9_lire_etat_consolide",
    "m9_lister_demandes_approbation", "m9_produire_briefing_matin",
    "m10_arbitrer_revision", "m10_paquet_contexte_affaire", "m10_statut_decision", "m10_statut_revision",
})
ADMIN = EMPLOYE | VENDEUR | ADMIN_SEUL

# Outils qu'AUCUN appareil ne peut appeler, avec la raison. Ils restent appelables par les agents
# (serveur MCP du département) : seule la voie du jeton d'appareil les refuse.
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
    "m2_ingerer_lead": "ingestion du contrat M1 -> M2, pas une saisie de téléphone",
    "m2_marquer_chantier_termine": "écrit par la cascade « travaux terminés » (auteur system:m4)",
    "m8_rapport_metriques": "ingère un snapshot fourni par l'appelant dans le registre de vérité chiffrée",
    "m9_etat_consolide": "ingère un snapshot fourni par l'appelant dans le registre consolidé",
    "m7_auditer_seo_site": "prend un chemin de dossier du serveur",
    "m7_calculer_roi": "prend des chemins de fichiers du serveur",
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
    "m4_confirmer_localisation", "m4_proposer_localisation",  # l'adresse d'un client : jamais l'employé (T4.1-a)
    "m4_proposer_cedule", "m4_appliquer_cedule",  # la cédule par tournées : dispatch de l'admin (T4.1-d)
])
def test_l_employe_ne_lit_ni_n_approuve_rien_des_autres(roles_reels, outil):
    assert outil not in roles_reels["employee"]


@pytest.mark.parametrize("outil", [
    "m5_etat_tresorerie", "m5_lister_attentes_facturation", "m6_approuver_po", "m6_receptionner_commande",
    "m6_produire_digest", "m6_enregistrer_prix", "m3_lire_ecarts_estime_reel", "m3_creer_devis",
    "m3_estimer_projet", "m4_lire_outbox", "m9_produire_briefing_matin", "m8_rapport_metriques",
    "m4_confirmer_localisation", "m4_proposer_localisation", "m4_proposer_cedule", "m4_appliquer_cedule",
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


def test_opsys_openclaw_configurer_ecrit_le_fragment_roles_json_reel(tmp_path, monkeypatch, capsys):
    """La commande réelle, sur les départements réels : `roles.json` est `roles_outils`, sans T3."""
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", "http://embeddings-test:11434/v1")
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "bge-m3")
    modeles.enregistrer_paliers({
        "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
        "fort": {"provider": "anthropic", "model": "claude-sonnet-5"},
        "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
    })
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
