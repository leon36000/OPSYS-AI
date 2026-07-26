import sys
import hashlib
import inspect
import urllib.request
import urllib.parse
from pathlib import Path
import pytest
import yaml

_M7 = Path(__file__).resolve().parents[2]
for p in (str(_M7 / "src" / "utm"), str(_M7 / "src" / "content"), str(_M7 / "src" / "workflows")):
    if p not in sys.path:
        sys.path.insert(0, p)
import utm_engine  # noqa: E402
import factory  # noqa: E402  (content factory M7-S006)
import campagne_saisonniere  # noqa: E402  (workflow S008)
import approval  # noqa: E402 (S006 gate)

CONTRAT = _M7 / "contracts" / "utm-convention.v1.yaml"


class TestIntegrationS006:
    def test_item_s006_reel(self):
        # Charger le profil de marque réel
        profile_path = _M7 / "src" / "brand" / "profile.yaml"
        brand = yaml.safe_load(profile_path.read_text(encoding="utf-8"))

        # Construire un content item via la factory
        item = factory.build_content_item(
            brand,
            surface="google_aio",
            type="page_seo",
            sujet={"titre": "Plomberie résidentielle à Montréal",
                   "description": "Services de plomberie résidentielle pour les propriétaires de la région de Montréal.",
                   "mots_cles": ["plomberie", "montreal"]},
            timestamp="2026-07-26T00:00:00+00:00",
        )

        lien = utm_engine.utm_pour_content_item(item)
        verdicts = utm_engine.valider_lien_utm(lien)

        fails = [v for v in verdicts if v[1] == "fail"]
        assert len(fails) == 0, (
            f"Lien UTM d'intégration S006 a échoué : {fails}\n"
            f"Lien complet : {lien}\n"
            f"Tous les verdicts : {verdicts}"
        )

    def test_item_s006_campaign_bien_forme(self):
        profile_path = _M7 / "src" / "brand" / "profile.yaml"
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

        lien = utm_engine.utm_pour_content_item(item)
        assert "utm_campaign=contenu-" in lien
        assert "utm_source=perplexity" in lien
        assert "utm_medium=organique" in lien

    def test_item_s006_sans_timestamp_rejete(self):
        profile_path = _M7 / "src" / "brand" / "profile.yaml"
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
            utm_engine.utm_pour_content_item(item)


class TestIntegrationS008:
    def test_fenetre_s008_reelle(self):
        approval.reset()
        plan = campagne_saisonniere.planifier_campagne_saisonniere(
            "2026-07-15T00:00:00+00:00",
            str(_M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"),
        )
        entree = plan["items_proposes"][0]
        lien = utm_engine.utm_pour_fenetre(
            entree, "2026-07-15T00:00:00+00:00", source="gbp", medium="social"
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
            entree, "2026-07-15T00:00:00+00:00", source="gbp", medium="social"
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
            entree, "2026-07-15T00:00:00+00:00", source="linkedin", medium="social"
        )
        assert "utm_source=linkedin" in lien
        assert "utm_medium=social" in lien


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
