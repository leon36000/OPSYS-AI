import sys
from pathlib import Path

_M7 = Path(__file__).resolve().parents[2]
_COMP = _M7 / "src" / "competitive"
if str(_COMP) not in sys.path:
    sys.path.insert(0, str(_COMP))

import loader  # noqa: E402
import analyzers  # noqa: E402
import compare  # noqa: E402
import report  # noqa: E402

import pytest
import yaml
import inspect


def _creer_meta(racine: Path, fictif: bool = True):
    meta = {"name": "ConcurrentTest", "url": "https://example.com", "type": "direct",
            "fictif": fictif, "description": "Fixture de test"}
    with open(racine / "meta.yaml", "w") as f:
        yaml.safe_dump(meta, f)


def _creer_index(racine: Path, contenu: str = "<html><head><title>Test</title></head><body></body></html>"):
    with open(racine / "index.html", "w") as f:
        f.write(contenu)


def _creer_robots(racine: Path, contenu: str = "User-agent: *\nDisallow:"):
    with open(racine / "robots.txt", "w") as f:
        f.write(contenu)


def _creer_sitemap(racine: Path, contenu: str = '<?xml version="1.0"?><urlset><url><loc>https://example.com</loc></url></urlset>'):
    with open(racine / "sitemap.xml", "w") as f:
        f.write(contenu)


class TestLoader:
    def test_refus_fixture_sans_fictif(self, tmp_path):
        slug = "test-refus"
        dossier = tmp_path / slug
        dossier.mkdir()
        _creer_meta(dossier, fictif=False)
        _creer_index(dossier)
        _creer_robots(dossier)
        _creer_sitemap(dossier)

        with pytest.raises(ValueError, match="fictif"):
            loader.load_fixture(slug, base_fixtures=tmp_path)

    def test_chargement_fixture_valide(self, tmp_path):
        slug = "test-valide"
        dossier = tmp_path / slug
        dossier.mkdir()
        _creer_meta(dossier, fictif=True)
        index_html = "<html><head></head><body></body></html>"
        robots_txt = "User-agent: *\nDisallow:"
        sitemap_xml = '<?xml version="1.0"?><urlset><url><loc>https://example.com</loc></url></urlset>'
        _creer_index(dossier, index_html)
        _creer_robots(dossier, robots_txt)
        _creer_sitemap(dossier, sitemap_xml)

        resultat = loader.load_fixture(slug, base_fixtures=tmp_path)

        assert "meta" in resultat, "Le résultat doit contenir la clé 'meta'"
        assert resultat["meta"]["fictif"] is True
        assert resultat["meta"]["name"] == "ConcurrentTest"
        assert resultat["index_html"] == index_html
        assert resultat["robots_txt"] == robots_txt
        assert resultat["sitemap_xml"] == sitemap_xml

    def test_fichier_manquant_ko(self, tmp_path):
        slug = "test-manquant"
        dossier = tmp_path / slug
        dossier.mkdir()
        _creer_meta(dossier, fictif=True)
        _creer_index(dossier)
        _creer_robots(dossier)
        # pas de sitemap.xml

        with pytest.raises(Exception, match="sitemap.xml") as exc_info:
            loader.load_fixture(slug, base_fixtures=tmp_path)
        # L'exception doit mentionner le nom du fichier manquant
        assert "sitemap.xml" in str(exc_info.value)

    """zéro réseau : vérifié sur les SOURCES de nos modules (sys.modules global pollué par
    les dépendances de test — non probant)"""




    def test_zero_reseau(self):
        """zéro réseau : vérifié sur les SOURCES de nos modules (sys.modules global pollué par
        les dépendances de test — non probant)"""
        modules_a_verifier = [loader, analyzers, compare, report]
        interdits = ["urllib", "socket", "http.client", "requests"]
        for mod in modules_a_verifier:
            source = inspect.getsource(mod)
            for mot in interdits:
                assert mot not in source, (
                    f"Le module {mod.__name__} contient une référence à {mot} "
                    f"— interdit dans nos sources"
                )
