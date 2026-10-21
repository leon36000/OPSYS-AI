import inspect
from pathlib import Path

import pytest
import yaml
from m7_marketing.content import (
    approval,  # (S006 gate)
    factory,  # (content factory M7-S006)
)
from m7_marketing.utm import utm_engine
from m7_marketing.workflows import campagne_saisonniere  # (workflow S008)

_M7 = Path(__file__).resolve().parents[2]

CONTRAT = _M7 / "contracts" / "utm-convention.v1.yaml"

# Aucun domaine par défaut codé en dur dans utm_engine (bug corrigé, R9 §item 8) : les tests
# d'intégration fournissent explicitement l'URL du site (identité de l'entreprise / profil de
# marque), jamais un fallback implicite vers un domaine en particulier.
URL_BASE_TEST = "https://exemple-client-m7.ca/"


class TestIntegrationS006:
    def test_item_s006_reel(self):
        # Charger le profil de marque réel
        profile_path = _M7 / "src" / "m7_marketing" / "brand" / "profile.yaml"
        brand = yaml.safe_load(profile_path.read_text(encoding="utf-8"))

        # Construire un content item via la factory
        item = factory.build_content_item(
            brand,
            surface="google_aio",
            type="page_seo",
            sujet={"titre": "Plomberie résidentielle à Montréal",
                   "description": "Services de plomberie résidentielle pour les propriétaires de la région "
                                  "de Montréal.",
                   "mots_cles": ["plomberie", "montreal"]},
            timestamp="2026-07-26T00:00:00+00:00",
        )

        lien = utm_engine.utm_pour_content_item(item, url_base=URL_BASE_TEST)
        verdicts = utm_engine.valider_lien_utm(lien)

        fails = [v for v in verdicts if v[1] == "fail"]
        assert len(fails) == 0, (
            f"Lien UTM d'intégration S006 a échoué : {fails}\n"
            f"Lien complet : {lien}\n"
            f"Tous les verdicts : {verdicts}"
        )

    def test_item_s006_campaign_bien_forme(self):
        profile_path = _M7 / "src" / "m7_marketing" / "brand" / "profile.yaml"
        brand = yaml.safe_load(profile_path.read_text(encoding="utf-8"))

        item = factory.build_content_item(
            brand,
            surface="perplexity",
            type="article_blog",
            sujet={"titre": "Isolation thermique des combles",
                   "description": "Guide factuel sur l'isolation thermique des combles en climat québécois.",
                   "mots_cles": ["isolation", "combles"]},
            timestamp="2026-07-26T00:00:00+00:00",
        )

        lien = utm_engine.utm_pour_content_item(item, url_base=URL_BASE_TEST)
        assert "utm_campaign=contenu-" in lien
        assert "utm_source=perplexity" in lien
        assert "utm_medium=organique" in lien

    def test_item_s006_sans_timestamp_rejete(self):
        profile_path = _M7 / "src" / "m7_marketing" / "brand" / "profile.yaml"
        brand = yaml.safe_load(profile_path.read_text(encoding="utf-8"))

        item = factory.build_content_item(
            brand,
            surface="google_aio",
            type="page_seo",
            sujet={"titre": "Plomberie résidentielle locale",
                   "description": "Description factuelle suffisante pour la validation du contrat de contenu v1.",
                   "mots_cles": ["plomberie"]},
            timestamp="2026-07-26T00:00:00+00:00",
        )
        item = dict(item)
        item.pop("timestamp")

        with pytest.raises(ValueError):
            utm_engine.utm_pour_content_item(item, url_base=URL_BASE_TEST)


class TestIntegrationS008:
    # PLAN T4.3 : `campagne_saisonniere._charger_brand` réel est désormais fail-closed
    # (`brand.profil_client`) et refuse le gabarit par défaut non configuré (`profile.yaml`,
    # M7-audit.md §2.1) — cette classe teste l'intégration UTM<->workflow, pas la configuration
    # de marque (couverte par `tests/test_brand_profil_client.py`).
    @pytest.fixture(autouse=True)
    def _brand_client_test(self, monkeypatch):
        brand_test = {
            "name": "TestCo",
            "tagline": "Tagline de test",
            "tone": "professionnel",
            "colors": ["#111111"],
            "langue": "fr",
        }
        monkeypatch.setattr(campagne_saisonniere, "_charger_brand", lambda: dict(brand_test))

    def test_fenetre_s008_reelle(self):
        approval.reset()
        plan = campagne_saisonniere.planifier_campagne_saisonniere(
            "2026-07-15T00:00:00+00:00",
            str(_M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"),
        )
        entree = plan["items_proposes"][0]
        lien = utm_engine.utm_pour_fenetre(
            entree, "2026-07-15T00:00:00+00:00", source="gbp", medium="social",
            url_base=URL_BASE_TEST,
        )
        verdicts = utm_engine.valider_lien_utm(lien)

        fails = [v for v in verdicts if v[1] == "fail"]
        assert len(fails) == 0, (
            f"Lien UTM d'intégration S008 a échoué : {fails}\n"
            f"Lien complet : {lien}\n"
            f"Tous les verdicts : {verdicts}"
        )

    def test_fenetre_campaign_prefixe(self):
        approval.reset()
        plan = campagne_saisonniere.planifier_campagne_saisonniere(
            "2026-07-15T00:00:00+00:00",
            str(_M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"),
        )
        entree = plan["items_proposes"][0]
        lien = utm_engine.utm_pour_fenetre(
            entree, "2026-07-15T00:00:00+00:00", source="gbp", medium="social",
            url_base=URL_BASE_TEST,
        )
        assert "utm_campaign=fenetre-fw-haute-saison-estivale" in lien

    def test_fenetre_contient_source_medium_fournis(self):
        approval.reset()
        plan = campagne_saisonniere.planifier_campagne_saisonniere(
            "2026-07-15T00:00:00+00:00",
            str(_M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"),
        )
        entree = plan["items_proposes"][0]
        lien = utm_engine.utm_pour_fenetre(
            entree, "2026-07-15T00:00:00+00:00", source="linkedin", medium="social",
            url_base=URL_BASE_TEST,
        )
        assert "utm_source=linkedin" in lien
        assert "utm_medium=social" in lien

    def test_content_item_produit_par_un_workflow_obtient_un_lien_utm(self):
        """RED — bug corrigé (mission §3, utm_engine.py ~l.336-341) : les workflows
        (campagne_saisonniere, chantier_social) appellent tous deux
        build_content_item(surface="google_aio", type="post_social"), ce qui donne
        pillar="social" — un triplet (google_aio, social, post_social) qui était ABSENT
        du mapping de utm_pour_content_item. Tout item produit par un workflow était donc
        structurellement incapable d'obtenir un lien UTM."""
        approval.reset()
        plan = campagne_saisonniere.planifier_campagne_saisonniere(
            "2026-07-15T00:00:00+00:00",
            str(_M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"),
        )
        item = plan["items_proposes"][0]["content_item"]
        assert (item["surface"], item["pillar"], item["type"]) == ("google_aio", "social", "post_social")

        lien = utm_engine.utm_pour_content_item(item, url_base=URL_BASE_TEST)
        verdicts = utm_engine.valider_lien_utm(lien)
        fails = [v for v in verdicts if v[1] == "fail"]
        assert not fails, f"Lien UTM d'un item de workflow non conforme : {fails}\n{lien}"


class TestAucunDomaineCodeEnDur:
    """RED — bug corrigé (mission §3/8) : utm_pour_content_item/utm_pour_fenetre avaient un
    domaine par défaut codé en dur ("https://opsys-ai.ca/"), qui s'appliquait silencieusement
    à N'IMPORTE QUELLE entreprise cliente de M7. L'identité de l'entreprise (URL du site) doit
    désormais toujours venir d'un paramètre explicite (profil de marque)."""

    def test_utm_pour_content_item_exige_url_base(self):
        item = {
            "surface": "google_aio",
            "pillar": "seo",
            "type": "page_seo",
            "timestamp": "2026-07-26T00:00:00+00:00",
            "title": "Titre",
        }
        with pytest.raises(TypeError):
            utm_engine.utm_pour_content_item(item)  # url_base manquant, aucun défaut

    def test_utm_pour_fenetre_exige_url_base(self):
        with pytest.raises(TypeError):
            utm_engine.utm_pour_fenetre(
                {"fenetre_id": "fw-x"}, "2026-07-15T00:00:00+00:00",
                source="gbp", medium="social",
            )  # url_base manquant, aucun défaut


class TestZeroReseau:
    def test_absence_urllib_request(self):
        source = inspect.getsource(utm_engine)
        assert "urllib.request" not in source, "urllib.request interdit dans utm_engine"
        assert "requests" not in source, "lib requests interdite dans utm_engine"
        assert "httpx" not in source, "lib httpx interdite dans utm_engine"
        assert "socket" not in source, "module socket interdit dans utm_engine"
        assert "http.client" not in source, "http.client interdit dans utm_engine"

    def test_urllib_parse_est_autorise(self):
        source = inspect.getsource(utm_engine)
        assert "urllib.parse" in source, "urllib.parse devrait être utilisé pour l'encodage"

    def test_aucun_appel_reseau_dans_generateur(self):
        # Vérifier que générer un lien ne provoque pas de résolution DNS
        # en patchant socket pour interdire les connexions
        import socket

        original_socket = socket.socket
        try:
            socket.socket = lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("Tentative réseau détectée !")
            )
            lien = utm_engine.generer_lien_utm(
                "https://opsys-ai.ca/services", "google", "organique", "fenetre-ete-2026"
            )
            assert lien.startswith("https://")
        finally:
            socket.socket = original_socket
