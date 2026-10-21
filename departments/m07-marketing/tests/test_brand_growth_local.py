"""Parcours intégrés des registres durables Brand, Growth et marketing local."""

from __future__ import annotations

from m7_marketing import outils
from m7_marketing.content import validation

from opsys import contexte, identite, stockage

BRAND = {
    "name": "Synergy Toitures (fictif)",
    "tagline": "Rénover sans surprise",
    "tone": "factuel et chaleureux",
    "colors": ["#111111", "#ffffff"],
    "langue": "fr",
}


def test_m7_registres_e2e(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys"))
    stockage.liberer()
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "proprio.fictif", "Propriétaire fictif", "mot-de-passe-fictif-123", ["admin", "nathan_owner"]
        )

    with stockage.transaction(), contexte.appele_par_appareil(contexte.IdentiteAppelante("proprio.fictif", "admin")):
        assert outils.configurer_profil_marque(BRAND, "2026-09-30T12:00:00+00:00")["statut"] == "configure"
        profil = outils.lire_profil_marque_courant()
        assert profil["profil"] == BRAND and profil["revision"] == 1
        contenu = outils.proposer_contenu_canonique(
            "google_aio",
            "post_social",
            {"titre": "Gouttières avant l'automne", "description": "Inspection et installation."},
            "2026-09-30T12:00:00+00:00",
        )
        assert contenu["approval_status"] == "PROPOSE"
        assert contenu["brand_revision"] == 1
        assert "Synergy Toitures" in str(contenu)
        assert validation.validate_content_item(contenu)

    observation = outils.enregistrer_observation_growth(
        "obs-2026-09",
        "clics",
        28.0,
        "clic",
        "2026-09-01",
        "2026-09-30",
        "google",
        "automne",
        "export analytique manuel",
        "rapport:septembre-2026",
        0.8,
    )
    assert observation["statut"] == "enregistre"
    assert (
        outils.enregistrer_observation_growth(
            "obs-2026-09",
            "clics",
            28.0,
            "clic",
            "2026-09-01",
            "2026-09-30",
            "google",
            "automne",
            "export analytique manuel",
            "rapport:septembre-2026",
            0.8,
        )["statut"]
        == "deja_enregistre"
    )
    assert (
        outils.enregistrer_observation_growth(
            "obs-2026-09",
            "clics",
            29.0,
            "clic",
            "2026-09-01",
            "2026-09-30",
            "google",
            "automne",
            "rapport:septembre-2026",
            "rapport:septembre-2026",
            0.8,
        )["statut"]
        == "conflit"
    )
    plan = outils.generer_plan_growth_30j("2026-10-01")
    assert plan["recommandations"][0]["observations_source"] == ["obs-2026-09"]
    assert plan["recommandations"][0]["donnees_manquantes"]
    assert "ROI calculé" in plan["limites"][-1]

    sans_consentement = outils.proposer_campagne_locale(
        "ref-2026",
        "reference",
        "Référence",
        "2026-10-01",
        "2026-10-31",
        0,
        "https://synergy.example/",
        "site",
        "referral",
        lead_ref="lead-42",
    )
    assert sans_consentement["statut"] == "consentement_requis"
    with stockage.transaction(), contexte.appele_par_appareil(contexte.IdentiteAppelante("proprio.fictif", "admin")):
        assert (
            outils.enregistrer_consentement_reference(
                "consent-42",
                "client-42",
                "Accepte une prise de contact",
                "formulaire:42",
                "2026-09-30T12:00:00+00:00",
            )["statut"]
            == "consentement_enregistre"
        )
    campagne = outils.proposer_campagne_locale(
        "ref-2026",
        "reference",
        "Référence",
        "2026-10-01",
        "2026-10-31",
        250,
        "https://synergy.example/",
        "site",
        "referral",
        lead_ref="lead-42",
        consentement_id="consent-42",
    )
    assert campagne["statut"] == "brouillon_propose"
    assert "utm_campaign=workflow-ref-2026-reference-2026" in campagne["campagne"]["lien_utm"]
    assert campagne["campagne"]["lead_statut"] == "CRM_non_verifie"
    with stockage.transaction(), contexte.appele_par_appareil(contexte.IdentiteAppelante("proprio.fictif", "admin")):
        assert outils.approuver_budget_campagne("ref-2026", 1, 250)["statut"] == "budget_approuve"
        assert outils.approuver_budget_campagne("ref-2026", 1, 250)["statut"] == "deja_tranche"
    suivi = outils.lire_campagne_locale("ref-2026")
    assert suivi["approbation_budget"]["par"] == "proprio.fictif"
    assert suivi["crm_statut"] == "CRM_non_verifie"

    # Les trois registres et leurs décisions survivent à la fermeture/réouverture des adaptateurs.
    stockage.liberer()
    assert outils.lire_profil_marque_courant()["revision"] == 1
    assert outils.lire_campagne_locale("ref-2026")["approbation_budget"]["plafond_cad"] == 250
    stockage.liberer()
