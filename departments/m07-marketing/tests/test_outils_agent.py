"""Capacités d'agent de M7 : contrat des outils et chaînes composées de bout en bout."""

from __future__ import annotations

from pathlib import Path

import pytest

from m7_marketing import outils
from m7_marketing.content import approval as content_approval

from opsys.departements import lire_manifeste
from opsys.outils import executer

_M7_ROOT = Path(__file__).resolve().parent.parent

BRAND = {
    "name": "Toitures Boréales Fictive Inc.",
    "tagline": "Rénovation extérieure au Québec, sans surprise",
    "tone": "professionnel, factuel, français d'abord",
    "colors": ["#1a1a1a", "#ffffff"],
    "langue": "fr",
}


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(_M7_ROOT)
    noms = [o.nom for o in dep.charger_outils()]
    assert all(nom.startswith("m7_") for nom in noms)
    assert len(noms) == len(set(noms)), "outils en double"
    assert "m7_calculer_roi" in noms
    assert "m7_publier_post_social" in noms


# ---------------------------------------------------------------------------
# m7_lire_profil_marque — T0
# ---------------------------------------------------------------------------
class TestLireProfilMarque:
    def test_nominal(self):
        resultat = outils.lire_profil_marque(BRAND)
        assert resultat["accepte"] is True
        assert resultat["resultat"]["name"] == BRAND["name"]

    def test_refus_champ_manquant(self):
        incomplet = {k: v for k, v in BRAND.items() if k != "name"}
        resultat = outils.lire_profil_marque(incomplet)
        assert resultat["accepte"] is False
        assert resultat["verdict"]["champ"] == "name"


# ---------------------------------------------------------------------------
# m7_calculer_roi — T0, outil composé de bout en bout (le correctif central de la mission)
# ---------------------------------------------------------------------------
class TestCalculerRoi:
    def test_nominal_canal_google_cout_reel_non_fabrique(self):
        """Preuve d'exécution réelle du correctif jointure canal->plateforme (R9 §1.1) :
        le canal 'google' obtient un cout_par_lead réel, jamais donnees_insuffisantes."""
        resultat = outils.calculer_roi(date_reference="2026-07-15")
        canaux = {c["canal"]: c for c in resultat["roi"]["par_canal"]}
        assert "google" in canaux
        assert "donnees_insuffisantes" not in canaux["google"]
        assert canaux["google"]["cout_par_lead"] > 0

    def test_reproductible(self):
        a = outils.calculer_roi(date_reference="2026-07-15")
        b = outils.calculer_roi(date_reference="2026-07-15")
        assert a == b

    def test_refus_fixture_sans_fictif(self, tmp_path):
        mauvais_matomo = tmp_path / "visites.yaml"
        mauvais_matomo.write_text("fictif: false\nvisites: []\n", encoding="utf-8")
        bon_crm = tmp_path / "leads.yaml"
        bon_crm.write_text("fictif: true\nleads: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="fictif"):
            outils.calculer_roi(
                date_reference="2026-07-15",
                chemin_matomo=str(mauvais_matomo),
                chemin_crm=str(bon_crm),
            )

    def test_executer_refuse_arguments_invalides(self):
        outil = next(o for o in outils.outils() if o.nom == "m7_calculer_roi")
        reponse = executer(outil, {"fenetre_jours": 30})  # date_reference manquant
        assert reponse["erreur"] == "arguments_invalides"


# ---------------------------------------------------------------------------
# m7_proposer_contenu — T1
# ---------------------------------------------------------------------------
class TestProposerContenu:
    @pytest.fixture(autouse=True)
    def _reset(self):
        content_approval.reset()
        yield
        content_approval.reset()

    def test_nominal_statut_propose(self):
        item = outils.proposer_contenu(
            brand=BRAND,
            surface="google_aio",
            type="post_social",
            sujet={"titre": "Toitures au printemps", "description": "Inspection post-hiver.", "mots_cles": ["toiture"]},
            timestamp="2026-07-25T00:00:00+00:00",
            acteur="orchestrateur",
        )
        assert item["approval_status"] == "PROPOSE"
        assert item["proposer"] == "orchestrateur"
        vus = outils.lister_file_approbation("PROPOSE")
        assert any(v["id"] == item["id"] for v in vus)

    def test_refus_surface_invalide(self):
        with pytest.raises(ValueError, match="surface invalide"):
            outils.proposer_contenu(
                brand=BRAND,
                surface="tiktok",
                type="post_social",
                sujet={"titre": "x", "description": "y"},
                timestamp="2026-07-25T00:00:00+00:00",
                acteur="orchestrateur",
            )


# ---------------------------------------------------------------------------
# m7_planifier_campagne_saisonniere — T1, outil composé
# ---------------------------------------------------------------------------
class TestPlanifierCampagneSaisonniere:
    @pytest.fixture(autouse=True)
    def _reset(self):
        content_approval.reset()
        yield
        content_approval.reset()

    # PLAN T4.3 : `campagne_saisonniere._charger_brand` réel est désormais fail-closed
    # (`brand.profil_client`) et refuse le gabarit par défaut non configuré (`profile.yaml`,
    # M7-audit.md §2.1) — cette classe teste la planification saisonnière via l'outil composé,
    # pas la configuration de marque (couverte par `tests/test_brand_profil_client.py`).
    @pytest.fixture(autouse=True)
    def _brand_client_test(self, monkeypatch):
        from m7_marketing.workflows import campagne_saisonniere

        brand_test = {
            "name": "TestCo",
            "tagline": "Tagline de test",
            "tone": "professionnel",
            "colors": ["#111111"],
            "langue": "fr",
        }
        monkeypatch.setattr(campagne_saisonniere, "_charger_brand", lambda: dict(brand_test))

    def test_nominal_juillet_haute_saison(self):
        plan = outils.planifier_campagne_saisonniere("2026-07-15T00:00:00+00:00")
        assert plan["compteurs"]["fenetres_actives"] == 1
        assert plan["fenetres_actives"][0]["id"] == "fw-haute-saison-estivale"
        for item in plan["items_proposes"]:
            assert item["content_item"]["approval_status"] == "PROPOSE"

    def test_aucune_fenetre_hors_saison(self):
        plan = outils.planifier_campagne_saisonniere("2026-05-15T00:00:00+00:00")
        assert plan["fenetres_actives"] == []
        assert plan["items_proposes"] == []


# ---------------------------------------------------------------------------
# m7_proposer_reponse_avis — T1 (litige prioritaire, jamais auto-publié)
# ---------------------------------------------------------------------------
class TestProposerReponseAvis:
    def test_litige_priorise_malgre_bonne_note(self):
        avis = {"id": "avis-x", "note": 5, "texte": "Service excellent mais j'ai dû faire une réclamation."}
        reponse = outils.proposer_reponse_avis(avis, BRAND)
        assert reponse["categorie"] == "litige"
        assert reponse["approval_status"] == "PROPOSE"
        assert BRAND["name"] in reponse["texte"]

    def test_refus_avis_sans_id(self):
        with pytest.raises(ValueError):
            outils.proposer_reponse_avis({"note": 5, "texte": "Top."}, BRAND)


# ---------------------------------------------------------------------------
# m7_calculer_metriques_reputation — T0, outil composé
# ---------------------------------------------------------------------------
def test_calculer_metriques_reputation_nominal():
    metriques = outils.calculer_metriques_reputation()
    assert metriques["m7_rep_total_avis"] > 0
    assert set(metriques["m7_rep_repartition_cats"]) == {"litige", "urgence", "eloge", "neutre"}
    assert 1.0 <= metriques["m7_rep_note_moyenne"] <= 5.0


# ---------------------------------------------------------------------------
# m7_generer_lien_utm — T0, outil composé (génère + valide)
# ---------------------------------------------------------------------------
class TestGenererLienUtm:
    def test_nominal_conforme(self):
        resultat = outils.generer_lien_utm(
            url_base="https://exemple-client.ca/services",
            source="google",
            medium="organique",
            campaign="fenetre-ete-2026",
        )
        assert resultat["conforme"] is True
        assert resultat["echecs"] == []
        assert "utm_source=google" in resultat["lien"]

    def test_refus_medium_hors_contrat(self):
        resultat = outils.generer_lien_utm(
            url_base="https://exemple-client.ca/services",
            source="google",
            medium="email-invalide",
            campaign="fenetre-ete-2026",
        )
        assert resultat["conforme"] is False
        assert any(e["regle"] == "U-03" for e in resultat["echecs"])


# ---------------------------------------------------------------------------
# m7_auditer_seo_site / m7_evaluer_aeo — T0
# ---------------------------------------------------------------------------
def test_auditer_seo_site_site_reel_ok():
    rapport = outils.auditer_seo_site()
    assert rapport["resume"]["regles_ko"] == 0


def test_evaluer_aeo_site_reel_localbusiness_trouve():
    """Vérifie l'effet du correctif G-15/A-08 (R9 §1.4) de bout en bout via l'outil agent."""
    rapport = outils.evaluer_aeo(timestamp="2026-07-25T00:00:00+00:00")
    a08 = next(v for v in rapport["surface_reports"]["perplexity"] if v["rule_id"] == "A-08")
    assert a08["measured_fact"] != "pas_de_localbusiness_jsonld"


# ---------------------------------------------------------------------------
# m7_analyser_concurrents — T0
# ---------------------------------------------------------------------------
def test_analyser_concurrents_nominal():
    rapport = outils.analyser_concurrents(slugs=["fort"], timestamp="2026-07-25T00:00:00+00:00")
    assert len(rapport["concurrents"]) == 1
    assert rapport["concurrents"][0]["slug"] == "fort"


# ---------------------------------------------------------------------------
# m7_publier_post_social — T3, frontière humaine (jamais d'écriture réelle)
# ---------------------------------------------------------------------------
class TestPublierPostSocial:
    def test_dry_run_par_defaut_jamais_publie(self):
        resultat = outils.publier_post_social(canal="gbp", texte="Chantier terminé à Québec.", niveau_validation=1)
        assert resultat["publie"] is False
        assert resultat["statut"] == "dry-run"

    def test_ecriture_reelle_toujours_non_autorisee(self):
        """D-010 : l'écriture réelle reste interdite tant que l'Approval Engine n'est pas
        branché — jamais une exception qui casse l'appel, toujours un verdict explicite."""
        resultat = outils.publier_post_social(
            canal="gbp",
            texte="Chantier terminé à Québec.",
            niveau_validation=1,
            adapter_config={"enabled": True, "dry_run": False},
        )
        assert resultat["publie"] is False
        assert resultat["statut"] == "non_autorise"

    def test_desactive_par_defaut_gate(self):
        resultat = outils.publier_post_social(
            canal="gbp", texte="Chantier terminé.", niveau_validation=1,
            adapter_config={"enabled": False},
        )
        assert resultat["statut"] == "desactive"

    def test_executer_via_le_contrat_outil(self):
        """Passe par executer() (comme le ferait le serveur MCP) : jamais d'exception non
        enveloppée même en cas de refus NotAutorise."""
        outil = next(o for o in outils.outils() if o.nom == "m7_publier_post_social")
        reponse = executer(outil, {
            "canal": "gbp", "texte": "Chantier terminé.", "niveau_validation": 1,
            "adapter_config": {"enabled": True, "dry_run": False},
        })
        assert reponse["ok"] is True
        assert reponse["resultat"]["statut"] == "non_autorise"
