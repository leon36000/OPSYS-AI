from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from m7_marketing.utm import utm_engine

_M7 = Path(__file__).resolve().parents[2]

CONTRAT = _M7 / "contracts" / "utm-convention.v1.yaml"


class TestDeterminisme:
    def test_appels_identiques_deterministes(self):
        args = ("https://opsys-ai.ca/services", "google", "organique", "fenetre-ete-2026")
        premier = utm_engine.generer_lien_utm(*args)
        for _ in range(100):
            assert utm_engine.generer_lien_utm(*args) == premier

    def test_bytes_identiques(self):
        args = ("https://opsys-ai.ca/services", "google", "organique", "fenetre-ete-2026")
        a = utm_engine.generer_lien_utm(*args)
        b = utm_engine.generer_lien_utm(*args)
        assert a.encode("utf-8") == b.encode("utf-8")


class TestOrdreCanonique:
    def test_ordre_utm_dans_query(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/services", "google", "organique", "fenetre-ete-2026"
        )
        parsed = urlparse(lien)
        qs = parsed.query
        assert "utm_source" in qs
        assert "utm_medium" in qs
        assert "utm_campaign" in qs
        idx_src = qs.index("utm_source")
        idx_med = qs.index("utm_medium")
        idx_camp = qs.index("utm_campaign")
        assert idx_src < idx_med < idx_camp

    def test_content_apres_campaign(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/services",
            "google",
            "organique",
            "fenetre-ete-2026",
            content="variante-a",
        )
        parsed = urlparse(lien)
        qs = parsed.query
        assert "utm_content" in qs
        idx_camp = qs.index("utm_campaign")
        idx_cont = qs.index("utm_content")
        assert idx_camp < idx_cont

    def test_utm_en_fin_de_query(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/p?ref=abc", "google", "organique", "fenetre-ete-2026"
        )
        parsed = urlparse(lien)
        qs = parsed.query
        assert "ref=abc" in qs
        assert qs.index("ref=abc") < qs.index("utm_source")


class TestPreservationParams:
    def test_params_existants_conserves(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/p?ref=abc&foo=bar",
            "google",
            "organique",
            "fenetre-ete-2026",
        )
        parsed = urlparse(lien)
        params = parse_qs(parsed.query)
        assert "ref" in params
        assert "foo" in params
        assert params["ref"] == ["abc"]

    def test_ecrasement_utm_preexistant(self):
        base = "https://opsys-ai.ca/p?utm_source=vieux&utm_medium=ancien"
        lien = utm_engine.generer_lien_utm(base, "google", "organique", "fenetre-ete-2026")
        parsed = urlparse(lien)
        params = parse_qs(parsed.query)
        assert sorted(params["utm_source"]) == ["google"]
        assert sorted(params["utm_medium"]) == ["organique"]

    def test_pas_de_doublon_apres_ecrasement(self):
        base = "https://opsys-ai.ca/p?utm_source=vieux&utm_campaign=ancien-ete-2020"
        lien = utm_engine.generer_lien_utm(base, "google", "organique", "fenetre-ete-2026")
        assert lien.count("utm_source=") == 1
        assert lien.count("utm_campaign=") == 1


class TestEncodageValeurs:
    def test_espace_encode(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/p",
            "google",
            "organique",
            "fenetre-ete-2026",
            content="variante A",
        )
        assert "utm_content=variante%20A" in lien or "utm_content=variante+A" in lien

    def test_accent_encode(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/p",
            "google",
            "organique",
            "fenetre-ete-2026",
            content="variante_é",
        )
        assert "utm_content=variante_%C3%A9" in lien or "utm_content=variante_%C3%a9" in lien

    def test_cles_jamais_encodees(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/p",
            "google",
            "organique",
            "fenetre-ete-2026",
        )
        assert "utm_source=google" in lien
        assert "utm_medium=organique" in lien
        assert "utm_campaign=fenetre-ete-2026" in lien


class TestNormaliserSlug:
    def test_simple(self):
        assert utm_engine.normaliser_slug("Rénovation — Toiture #1 !") == "renovation-toiture-1"

    def test_diacritiques(self):
        result = utm_engine.normaliser_slug("Été 2026")
        assert result == "ete-2026"

    def test_tirets_consecutifs(self):
        result = utm_engine.normaliser_slug("a---b")
        assert result == "a-b"

    def test_tirets_terminaux(self):
        result = utm_engine.normaliser_slug("-abc-")
        assert result == "abc"

    def test_caracteres_speciaux(self):
        result = utm_engine.normaliser_slug("hello@world!")
        assert result == "hello-world"

    def test_majuscules(self):
        result = utm_engine.normaliser_slug("HELLO World")
        assert result == "hello-world"


class TestConstruireCampaign:
    def test_basique(self):
        result = utm_engine.construire_campaign("fenetre", "Été 2026", 2026)
        assert result == "fenetre-ete-2026"

    def test_avec_tirets_slug(self):
        result = utm_engine.construire_campaign("workflow", "Villa  Nice -- 2024", 2024)
        assert result == "workflow-villa-nice-2024"

    def test_annee_bornee_2019(self):
        with pytest.raises(ValueError):
            utm_engine.construire_campaign("fenetre", "ete", 2019)

    def test_annee_bornee_2100(self):
        with pytest.raises(ValueError):
            utm_engine.construire_campaign("fenetre", "ete", 2100)

    def test_origine_valide_workflow(self):
        result = utm_engine.construire_campaign("workflow", "villa-nice", 2024)
        assert result == "workflow-villa-nice-2024"

    def test_origine_valide_contenu(self):
        result = utm_engine.construire_campaign("contenu", "seo-plomberie", 2025)
        assert result == "contenu-seo-plomberie-2025"


class TestGenererLienUtm:
    def test_sans_content(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/services", "google", "organique", "fenetre-ete-2026"
        )
        assert "utm_source=google" in lien
        assert "utm_medium=organique" in lien
        assert "utm_campaign=fenetre-ete-2026" in lien
        assert "utm_content" not in lien

    def test_avec_content(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/services",
            "google",
            "organique",
            "fenetre-ete-2026",
            content="variante-a",
        )
        assert "utm_content=variante-a" in lien

    def test_url_base_avec_fragment(self):
        lien = utm_engine.generer_lien_utm(
            "https://opsys-ai.ca/services#section", "google", "organique", "fenetre-ete-2026"
        )
        assert "#section" in lien
        assert "utm_source=google" in lien

    def test_url_base_avec_authentification(self):
        lien = utm_engine.generer_lien_utm(
            "https://user:pass@opsys-ai.ca/services", "google", "organique", "fenetre-ete-2026"
        )
        assert lien.startswith("https://user:pass@")
        assert "utm_source=google" in lien
