import json
from pathlib import Path

import pytest
import yaml
from m7_marketing.competitive import analyzers, compare, loader, report

_M7 = Path(__file__).resolve().parents[2]


# -------------------------------------------------------------------- helpers HTML

def _html_minimal(title="Test", meta_desc=None, h1="Titre principal", liens=None,
                  schema=False, domaine="https://example.com"):
    head = f"<title>{title}</title>"
    if meta_desc:
        head += f'\n<meta name="description" content="{meta_desc}">'
    if schema:
        head += '\n<script type="application/ld+json">{"@type": "Organization", "name": "Test Corp"}</script>'
    liens_html = " ".join(f'<a href="{domaine}{lien}">link</a>' for lien in liens) if liens else ""
    body = f"<h1>{h1}</h1>" + liens_html
    return f"<html><head>{head}</head><body>{body}</body></html>"


def _html_sans_title():
    return "<html><head></head><body><h1>Sans titre</h1></body></html>"


def _html_sans_meta_desc():
    return "<html><head><title>Titre</title></head><body><h1>Titre</h1></body></html>"


def _html_deux_h1():
    return "<html><head><title>Titre</title></head><body><h1>Premier</h1><h1>Second</h1></body></html>"


def _html_sans_h1():
    return "<html><head><title>Titre</title></head><body><p>Pas de h1</p></body></html>"


def _html_sans_schema():
    return _html_minimal(schema=False)


def _html_peu_liens():
    return _html_minimal(liens=["/page1"], domaine="https://example.com")


# Robots helpers
ROBOTS_PERMISSIF = "User-agent: *\nDisallow:"
ROBOTS_BLOQUANT_GPT = "User-agent: GPTBot\nDisallow: /"


# Sitemap helpers
SITEMAP_VALIDE = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/</loc></url></urlset>'
SITEMAP_INVALIDE = '<xml><bad>'
SITEMAP_VIDE = ""


# Couverture helpers
TEXTE_COMMUN_1 = "analyse référencement concurrent optimisation moteur recherche mots clés trafic web"
TEXTE_COMMUN_2 = "optimisation moteur recherche trafic web audit seo concurrent analyse"
TEXTE_DIFF_1 = "python java programmation"
TEXTE_DIFF_2 = "fromage baguette vin"


# Création d'une fixture complète pour generate_report
def _creer_fixture_complete(tmp_path, slug="test", meta_overrides=None):
    dossier = tmp_path / slug
    dossier.mkdir()
    meta = {"name": f"Concurrent {slug}", "url": f"https://{slug}.example.com", "type": "direct",
            "fictif": True, "description": "Fixture"}
    if meta_overrides:
        meta.update(meta_overrides)
    with open(dossier / "meta.yaml", "w") as f:
        yaml.safe_dump(meta, f)
    with open(dossier / "index.html", "w") as f:
        f.write(_html_minimal(title=f"{slug} title", meta_desc=f"{slug} description"))
    with open(dossier / "robots.txt", "w") as f:
        f.write(ROBOTS_PERMISSIF)
    with open(dossier / "sitemap.xml", "w") as f:
        f.write(SITEMAP_VALIDE)
    return dossier


# Classe de tests
class TestReglesSEO:
    # C-01
    def test_c01_conforme(self):
        html = _html_minimal(title="Titre valide"[:60])
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-01"] == "conforme", "Un title présent et non vide doit être conforme"

    def test_c01_non_conforme(self):
        html = _html_sans_title()
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-01"] == "non_conforme", "Absence de title doit donner non_conforme"
        # Test title vide
        html_vide = _html_minimal(title="")
        result_vide = analyzers.analyze_page(html_vide, "https://example.com")
        assert result_vide["C-01"] == "non_conforme", "Title vide doit donner non_conforme"

    # C-02
    def test_c02_conforme(self):
        html = _html_minimal(title="T", meta_desc="Description correcte"[:160])
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-02"] == "conforme", "Meta description présente doit être conforme"

    def test_c02_non_conforme(self):
        html = _html_sans_meta_desc()
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-02"] == "non_conforme", "Absence de meta description doit donner non_conforme"
        # description vide
        html_vide = _html_minimal(title="T", meta_desc="")
        result_vide = analyzers.analyze_page(html_vide, "https://example.com")
        assert result_vide["C-02"] == "non_conforme", "Meta description vide doit donner non_conforme"

    # C-03
    def test_c03_conforme(self):
        html = _html_minimal()  # un seul h1
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-03"] == "conforme", "Un unique h1 doit être conforme"

    def test_c03_non_conforme_deux_h1(self):
        html = _html_deux_h1()
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-03"] == "non_conforme", "Deux h1 doit donner non_conforme"

    def test_c03_non_conforme_sans_h1(self):
        html = _html_sans_h1()
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-03"] == "non_conforme", "Absence de h1 doit donner non_conforme"

    # C-04
    def test_c04_conforme(self):
        html = _html_minimal(schema=True)
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-04"] in ("conforme", "candidat_a_verifier"), \
            "Schema.org présent doit être conforme ou candidat_a_verifier"

    def test_c04_non_conforme(self):
        html = _html_sans_schema()
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-04"] == "non_conforme", "Absence de schema.org doit donner non_conforme"

    # C-05
    def test_c05_conforme(self):
        html = _html_minimal(liens=["/a", "/b", "/c"], domaine="https://example.com")
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-05"] == "conforme", "3 liens internes doivent être conformes"

    def test_c05_non_conforme(self):
        html = _html_peu_liens()
        result = analyzers.analyze_page(html, "https://example.com")
        assert result["C-05"] == "non_conforme", "Moins de 3 liens internes doit être non_conforme"

    # C-06
    def test_c06_conforme(self):
        result = analyzers.analyze_robots(ROBOTS_PERMISSIF)
        assert result["C-06"] == "conforme", "Robots permissif doit être conforme"

    def test_c06_non_conforme(self):
        result = analyzers.analyze_robots(ROBOTS_BLOQUANT_GPT)
        assert result["C-06"] == "non_conforme", "Robots bloquant GPTBot doit être non_conforme"

    def test_c06_ko_absent(self):
        result = analyzers.analyze_robots("")
        assert result["C-06"] == "KO", "Absence de robots.txt doit donner KO"

    # C-07
    def test_c07_conforme(self):
        result = analyzers.analyze_sitemap(SITEMAP_VALIDE)
        assert result["C-07"] == "conforme", "Sitemap valide doit être conforme"

    def test_c07_non_conforme_invalide(self):
        result = analyzers.analyze_sitemap(SITEMAP_INVALIDE)
        assert result["C-07"] == "KO", "Sitemap invalide doit donner KO"
        # doit générer une erreur de parsing
        assert "parse_error" in str(result).lower() or "erreur" in str(result).lower()

    def test_c07_ko_absent(self):
        result = analyzers.analyze_sitemap("")
        assert result["C-07"] == "KO"

    def test_analyze_sitemap_rejette_un_xml_trop_volumineux(self):
        overflow = "x" * (analyzers._XML_MAX_BYTES + 1)
        xml_str = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f'{overflow}\n'
            '</urlset>'
        )
        result = analyzers.analyze_sitemap(xml_str)
        assert result == {
            "C-07": "KO",
            "detail_C-07": "sitemap.xml dépasse la taille maximale autorisée",
        }

    # C-08
    def test_c08_conforme(self, tmp_path):
        # Créer un fichier stopwords minimal (vide pour ne filtrer aucun mot)
        stopwords_path = tmp_path / "stopwords.txt"
        stopwords_path.write_text("")  # aucun mot exclu
        score = compare.calculate_coverage(TEXTE_COMMUN_1, TEXTE_COMMUN_2, str(stopwords_path))
        assert score >= 0.5, f"Score de couverture attendu >= 0.5, obtenu {score}"

    def test_c08_non_conforme(self, tmp_path):
        stopwords_path = tmp_path / "stopwords_vide.txt"
        stopwords_path.write_text("")
        score = compare.calculate_coverage(TEXTE_DIFF_1, TEXTE_DIFF_2, str(stopwords_path))
        assert score < 0.5, f"Score de couverture attendu < 0.5, obtenu {score}"

    # Déterminisme du rapport
    def test_determinisme_rapport(self, tmp_path):
        _creer_fixture_complete(tmp_path, "fort")
        _creer_fixture_complete(tmp_path, "faible")
        slugs = ["fort", "faible"]
        # On suppose que generate_report accepte un timestamp optionnel pour le déterminisme
        timestamp = "2024-01-01T00:00:00Z"
        rapport1 = report.generate_report(slugs, notre_site="", base_fixtures=tmp_path,
                                          stopwords_path="", timestamp=timestamp)
        rapport2 = report.generate_report(slugs, notre_site="", base_fixtures=tmp_path,
                                          stopwords_path="", timestamp=timestamp)
        assert rapport1 == rapport2, "Les rapports doivent être identiques quand le timestamp est fixé"

    # Absence de score agrégé et structure des verdicts
    def test_verdicts_par_regle_sans_score(self, tmp_path):
        _creer_fixture_complete(tmp_path, "fort")
        slugs = ["fort"]
        # on ne passe pas de timestamp pour avoir le rapport normal, on enlèvera timestamp si présent
        rapport = report.generate_report(slugs, notre_site="", base_fixtures=tmp_path,
                                         stopwords_path="")
        # Pas de score agrégé
        rapport_json = json.dumps(rapport).lower()
        assert "score" not in rapport_json, "Le rapport ne doit pas contenir de score agrégé"

        # Vérification de la structure des verdicts
        for concurrent in rapport.get("concurrents", []):
            assert "verdicts" in concurrent, "Chaque concurrent doit avoir une clé 'verdicts'"
            for verdict in concurrent["verdicts"]:
                assert "regle" in verdict, f"Verdict sans clé 'regle': {verdict}"
                assert "verdict" in verdict, f"Verdict sans clé 'verdict': {verdict}"
                assert verdict["verdict"] in ("conforme", "non_conforme", "candidat_a_verifier", "KO"), \
                    f"Valeur de verdict invalide: {verdict['verdict']}"


def test_load_stopwords_leve_si_le_chemin_est_fourni_mais_introuvable():
    with pytest.raises(FileNotFoundError):
        compare._load_stopwords("/chemin/qui/nexiste/pas.txt")


def test_site_reel_compare():
    notre = (_M7 / "src" / "m7_marketing" / "site" / "static" / "index.html").read_text(encoding="utf-8")
    rapport = report.generate_report(
        ["fort"],
        notre_site=notre,
        base_fixtures=str(_M7 / "fixtures" / "concurrents"),
        stopwords_path="",
        timestamp="2026-07-25T00:00:00+00:00"
    )
    assert len(rapport.get("concurrents", [])) == 1
    verdicts = rapport["concurrents"][0].get("verdicts", [])
    assert len(verdicts) > 0
    for v in verdicts:
        assert v["verdict"] in {"conforme", "non_conforme", "candidat_a_verifier", "KO"}
    regles = [v["regle"] for v in verdicts]
    assert "C-08" in regles
    couverture = rapport["concurrents"][0]["couverture"]
    assert 0.0 <= couverture <= 1.0


def test_fixture_casse_reelle_parse_error():
    data = loader.load_fixture("casse", base_fixtures=str(_M7 / "fixtures" / "concurrents"))
    res = analyzers.analyze_sitemap(data["sitemap_xml"])
    assert res.get("C-07") == "KO"
    detail = res.get("detail_C-07", "")
    assert "parse_error" in detail.lower()
