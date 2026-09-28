"""PLAN T0.13 — un lead v2 traverse M1 → M2 → M3 avec les mêmes codes de service.

M1 qualifie une demande de client (« gouttières »), M2 ingère le lead v2 et signe la readiness,
M3 estime avec le poste du barème du même service. Aucune copie locale n'intervient : le service
vient du profil d'entreprise de l'instance, lu par chaque département. Sans ce profil, la chaîne
s'arrête à M1 et dit quoi configurer ; un service retiré du profil en cours de route arrête M2.
Fixtures fictives (aucune donnée réelle)."""

from __future__ import annotations

import pytest
from m1_front_office import outils as m1
from m2_revenue_crm import outils as m2
from m3_estimation import estimation
from m3_estimation import registre as registre_m3

from opsys import taxonomie

ZONE = ["Laval", "Québec"]
PHOTOS = [{
    "photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
    "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True},
}]
SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1", "unite": "pi",
    "postes": {"gouttieres": {"cout_unitaire_min": 6.0, "cout_unitaire_max": 11.0}},
}
DEMANDE = "Bonjour, nos gouttières fuient à Laval, téléphone 450-555-0199. Merci."


@pytest.fixture(autouse=True)
def _departements_propres(declarer_services):
    declarer_services()
    m1.reinitialiser_registre()
    m2.reinitialiser_registre()
    yield
    m1.reinitialiser_registre()
    m2.reinitialiser_registre()


def _qualifier() -> dict:
    reponse = m1.traiter_demande_entrante(
        contenu_brut=DEMANDE, canal="texte", conversation_id="conv-e2e-1", signal_id="sig-e2e-1",
        horodatage="2026-09-28T09:00:00-04:00", zone_desservie=ZONE,
    )
    assert reponse["qualifie"] is True
    return reponse["lead"]


def _lead_pret_pour_m3(lead: dict) -> dict:
    """Ingestion M2, qualification par un humain, interaction, marqueur de readiness signé."""
    lead_id = lead["lead_id"]
    assert m2.ingerer_lead(lead, "2026-09-28T09:01:00-04:00")["accepte"] is True
    assert m2.transitionner_statut(
        lead_id, "qualifie", "2026-09-28T09:30:00-04:00", owner="Alice",
        prochaine_action={"description": "Appeler le client", "echeance": "2026-09-29T09:00:00-04:00"},
    )["accepte"] is True
    assert m2.enregistrer_interaction(lead_id, "Alice", "Appel de suivi", "2026-09-28T10:00:00-04:00")["accepte"]
    pret = m2.evaluer_readiness(lead_id, "2026-09-28T10:05:00-04:00")
    assert pret["accepte"] is True, pret
    return pret["resultat"]


def test_un_lead_de_gouttieres_traverse_m1_m2_m3_avec_le_meme_code():
    lead = _qualifier()
    assert lead["schema_version"] == 2 and lead["service"] == "gouttieres"
    marqueur = _lead_pret_pour_m3(lead)

    reponse = estimation.orchestrer_estimation(
        contrat=lead, marqueur=marqueur, photos=PHOTOS, seuils=SEUILS, bareme=BAREME,
        quantite=100, plancher_rentable=500, registre_cible=registre_m3.Registre(), graine=1,
    )
    assert reponse["accepte"] is True and reponse["etape"] == "complet", reponse
    intervalle = reponse["estimation"]["intervalle_confiance"]
    assert 600.0 <= intervalle["borne_basse"] <= intervalle["borne_haute"] <= 1100.0


def test_le_bareme_d_un_autre_service_ne_repond_pas_pour_les_gouttieres():
    lead = _qualifier()
    marqueur = _lead_pret_pour_m3(lead)
    bareme = {"version": "1", "unite": "pi",
              "postes": {"revetement": {"cout_unitaire_min": 1.0, "cout_unitaire_max": 2.0}}}
    reponse = estimation.orchestrer_estimation(
        contrat=lead, marqueur=marqueur, photos=PHOTOS, seuils=SEUILS, bareme=bareme,
        quantite=100, plancher_rentable=500, registre_cible=registre_m3.Registre(), graine=1,
    )
    assert reponse["accepte"] is False
    assert reponse["verdict"]["detail"] == "barème du service 'gouttieres' absent : à fournir"


def test_sans_profil_la_chaine_s_arrete_a_m1_et_dit_quoi_configurer():
    taxonomie.fichier_profil().unlink()
    with pytest.raises(ValueError) as exc:
        m1.traiter_demande_entrante(
            contenu_brut=DEMANDE, canal="texte", conversation_id="conv-e2e-2", signal_id="sig-e2e-2",
            horodatage="2026-09-28T09:00:00-04:00", zone_desservie=ZONE,
        )
    assert "entreprise.yaml" in str(exc.value)


def test_service_retire_du_profil_apres_l_ingestion_arrete_la_readiness_puis_m3(declarer_services):
    lead = _qualifier()
    marqueur = _lead_pret_pour_m3(lead)
    declarer_services("revetement")  # l'entreprise n'offre plus les gouttières
    assert m2.evaluer_readiness(lead["lead_id"], "2026-09-28T11:00:00-04:00")["accepte"] is False
    reponse = estimation.orchestrer_estimation(
        contrat=lead, marqueur=marqueur, photos=PHOTOS, seuils=SEUILS, bareme=BAREME,
        quantite=100, plancher_rentable=500, registre_cible=registre_m3.Registre(), graine=1,
    )
    assert reponse["accepte"] is False and reponse["etape"] == "validation"
    assert "REJ-SERVICE-INCONNU" in reponse["verdict"]["detail"]


def test_le_lead_v1_historique_traverse_toujours_m2_et_m3_sans_profil():
    """Compatibilité : un lead v1 déjà écrit ne dépend d'aucune configuration de services."""
    taxonomie.fichier_profil().unlink()
    lead = {
        "lead_id": "L-historique", "conversation_id": "conv-h", "type_travaux": "ravalement",
        "ville": "Laval", "canal": "texte", "contact": {"nom": "Client fictif"}, "urgence_declaree": False,
    }
    marqueur = _lead_pret_pour_m3(lead)
    bareme = {"version": "1", "unite": "pi",
              "postes": {"ravalement": {"cout_unitaire_min": 1.0, "cout_unitaire_max": 2.0}}}
    reponse = estimation.orchestrer_estimation(
        contrat=lead, marqueur=marqueur, photos=PHOTOS, seuils=SEUILS, bareme=bareme,
        quantite=100, plancher_rentable=50, registre_cible=registre_m3.Registre(), graine=1,
    )
    assert reponse["accepte"] is True and reponse["etape"] == "complet", reponse
