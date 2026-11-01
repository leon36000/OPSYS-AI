"""Moteur de rendu Python pur : site fictif bilingue complet, idempotence octet pour octet, actifs contrôlés."""

from __future__ import annotations

import base64
import hashlib
import json
import re

import pytest
from m7_marketing.aeo import aeo_engine
from m7_marketing.seo import seo_audit
from m7_marketing.site import guardrail, qa_site, rendu_statique

FICTIF = True

PAGES_ATTENDUES = {
    "index.html", "services/index.html", "services/revetement-exterieur/index.html", "services/gouttieres/index.html",
    "services/soffites-et-fascias/index.html", "questions-frequentes/index.html", "contact/index.html",
    "mentions-legales/index.html", "confidentialite/index.html", "404.html",
    "en/index.html", "en/services/index.html", "en/services/exterior-siding/index.html",
    "en/services/gutters/index.html",
    "en/services/soffit-and-fascia/index.html", "en/faq/index.html", "en/contact/index.html",
    "en/legal-notice/index.html", "en/privacy/index.html", "en/404.html",
}


def _page(fichiers, chemin):
    return fichiers[chemin].decode("utf-8")


def _json_ld(document):
    [bloc] = re.findall(r'<script type="application/ld\+json">(.*?)</script>', document, re.S)
    return json.loads(bloc)


def test_le_site_fictif_complet_est_genere_en_francais_et_en_anglais(fichiers):
    pages = {f for f in fichiers if f.endswith(".html")}
    assert pages == PAGES_ATTENDUES
    assert {"sitemap.xml", "robots.txt", "favicon.svg", "images/facade-revetement.svg", "images/gouttiere.svg"} <= set(
        fichiers
    )
    assert '<html lang="fr-CA">' in _page(fichiers, "index.html")
    assert '<html lang="en-CA">' in _page(fichiers, "en/index.html")


def test_idempotence_meme_schema_memes_octets(schema, actifs, fichiers_demo):
    deuxieme = rendu_statique.rendre_site(schema, actifs)
    assert deuxieme == fichiers_demo
    empreinte = hashlib.sha256(b"".join(k.encode() + v for k, v in sorted(deuxieme.items()))).hexdigest()
    troisieme = rendu_statique.rendre_site(schema, actifs)
    assert hashlib.sha256(b"".join(k.encode() + v for k, v in sorted(troisieme.items()))).hexdigest() == empreinte


def test_un_changement_de_contenu_change_les_octets(schema, actifs, fichiers_demo):
    schema["faq"][0]["reponse"]["fr-CA"] += " Merci."
    autre = rendu_statique.rendre_site(schema, actifs)
    differents = {f for f in autre if autre[f] != fichiers_demo[f]}
    assert differents == {"questions-frequentes/index.html"}


def test_hreflang_x_default_et_canonique_propres(fichiers):
    page = _page(fichiers, "en/services/gutters/index.html")
    assert '<link rel="canonical" href="https://revetements-horizon.example/en/services/gutters/">' in page
    assert ('<link rel="alternate" hreflang="fr-CA" href="https://revetements-horizon.example/services/gouttieres/">'
            in page)
    assert ('<link rel="alternate" hreflang="x-default" '
            'href="https://revetements-horizon.example/services/gouttieres/">') in page
    assert '<a href="/services/gouttieres/" hreflang="fr-CA" lang="fr-CA">Français</a>' in page


def test_open_graph_et_csp_par_empreinte_du_style(fichiers):
    page = _page(fichiers, "index.html")
    assert '<meta property="og:locale" content="fr_CA">' in page
    assert '<meta property="og:locale:alternate" content="en_CA">' in page
    [css] = re.findall(r"<style>(.*?)</style>", page, re.S)
    empreinte = base64.b64encode(hashlib.sha256(css.encode()).digest()).decode()
    assert f"style-src &#x27;sha256-{empreinte}&#x27;" in page
    assert "default-src &#x27;none&#x27;" in page


def test_aucune_ressource_tierce_ni_script_executable(fichiers):
    for chemin, octets in fichiers.items():
        if not chemin.endswith(".html"):
            continue
        texte = octets.decode()
        assert not re.search(r'(?:src|href)="(?:https?:)?//(?!revetements-horizon\.example)', texte), chemin
        assert re.findall(r"<script\b[^>]*>", texte) == ['<script type="application/ld+json">']
        assert "@import" not in texte and "@font-face" not in texte


def test_json_ld_graphe_coherent_avec_la_nap(fichiers, schema):
    graphe = _json_ld(_page(fichiers, "services/gouttieres/index.html"))["@graph"]
    entreprise = graphe[0]
    nap = schema["entreprise"]["nap"]
    assert entreprise["@type"] == "HomeAndConstructionBusiness"
    assert (entreprise["telephone"], entreprise["email"]) == (nap["telephone"], nap["courriel"])
    assert entreprise["address"]["postalCode"] == "H7N 1A1"
    assert [z["name"] for z in entreprise["areaServed"]] == ["Laval", "Terrebonne", "Blainville", "Boisbriand"]
    [service] = [n for n in graphe if n["@type"] == "Service"]
    assert service["provider"] == {"@id": entreprise["@id"]}
    assert service["url"] == "https://revetements-horizon.example/services/gouttieres/"
    faq = _json_ld(_page(fichiers, "en/faq/index.html"))["@graph"][-1]
    assert faq["@type"] == "FAQPage" and len(faq["mainEntity"]) == 3


def test_temoignages_marques_consentis_et_en_initiales(fichiers):
    page = _page(fichiers, "index.html")
    assert "M. T., Laval. Publié avec le consentement de son auteur." in page
    assert "Published with the author&#x27;s consent." in _page(fichiers, "en/index.html")


def test_pages_legales_loi_25_et_404(fichiers):
    confidentialite = _page(fichiers, "confidentialite/index.html")
    assert "Responsable de la protection des renseignements personnels" in confidentialite
    assert "mailto:confidentialite@revetements-horizon.example" in confidentialite
    assert "aucun témoin (cookie) ni traceur non essentiel" in confidentialite
    assert "Licence RBQ : 5555-0142-01" in _page(fichiers, "mentions-legales/index.html")
    for chemin in ("404.html", "en/404.html"):
        assert '<meta name="robots" content="noindex">' in _page(fichiers, chemin)


def test_images_avec_dimensions_et_texte_de_remplacement(fichiers):
    page = _page(fichiers, "index.html")
    assert ('<img src="/images/facade-revetement.svg" alt="Illustration d&#x27;une façade de maison avec un '
            'revêtement horizontal neuf" width="1200" height="630" decoding="async">') in page
    assert 'loading="lazy"' in _page(fichiers, "services/gouttieres/index.html")


def test_sitemap_et_robots(fichiers):
    sitemap = fichiers["sitemap.xml"].decode()
    assert sitemap.count("<url>") == 18
    assert "<lastmod>2026-10-31</lastmod>" in sitemap
    assert 'hreflang="x-default" href="https://revetements-horizon.example/"' in sitemap
    assert fichiers["robots.txt"].decode() == (
        "User-agent: *\nAllow: /\n\nSitemap: https://revetements-horizon.example/sitemap.xml\n"
    )


def test_chaque_page_passe_le_garde_fou_de_page_herite(fichiers):
    for chemin, octets in fichiers.items():
        if chemin.endswith(".html"):
            langue = "en-CA" if chemin.startswith("en/") else "fr-CA"
            assert guardrail.validate(octets.decode(), content={"lang": langue}) == [], chemin


def test_g15_refuse_un_graphe_sans_entreprise(fichiers):
    page = _page(fichiers, "index.html").replace('"@type": "HomeAndConstructionBusiness"', '"@type": "Thing"')
    assert {c for c, _ in guardrail.validate(page)} == {"G-15"}


def test_audit_seo_existant_vert_sur_le_site_bilingue(fichiers, tmp_path):
    for chemin, octets in fichiers.items():
        (tmp_path / chemin).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / chemin).write_bytes(octets)
    rapport = seo_audit.audit_dir(tmp_path)
    assert rapport["resume"] == {"pages_auditees": 20, "regles_ko": 0}
    anglais = next(p for p in rapport["pages"] if p["fichier"] == "en/index.html")
    lang = next(v for v in anglais["verdicts"] if v["regle"] == "lang_fr")
    assert "version française déclarée" in lang["detail"]


def test_seo_audit_refuse_une_page_anglaise_sans_version_francaise(tmp_path):
    page = '<html lang="en-CA"><head><title>T</title></head><body><h1>x</h1></body></html>'
    (tmp_path / "index.html").write_text(page)
    (tmp_path / "robots.txt").write_text("User-agent: *\nAllow: /\n")
    page = seo_audit.audit_dir(tmp_path)["pages"][0]
    assert next(v for v in page["verdicts"] if v["regle"] == "lang_fr")["ok"] is False


def test_aeo_trouve_l_entreprise_dans_le_graphe(fichiers, tmp_path):
    (tmp_path / "index.html").write_bytes(fichiers["index.html"])
    artefact = aeo_engine.build_site_artifact(tmp_path / "index.html", aeo_engine.SEO_KNOWLEDGE_PATH,
                                              "2026-10-31T12:00:00-04:00")
    a08 = next(v for v in aeo_engine.evaluate(artefact)["surface_reports"]["perplexity"] if v["rule_id"] == "A-08")
    assert a08["measured_fact"] != "pas_de_localbusiness_jsonld"


def test_actifs_absents_refuses(schema, actifs):
    del actifs["images/gouttiere.svg"]
    assert [r["code"] for r in rendu_statique.verifier_actifs(schema, actifs)] == [rendu_statique.REJ_IMAGE_ABSENTE]


def test_dimensions_reelles_differentes_refusees(schema, actifs):
    schema["images"][0]["largeur"] = 1600
    refus = rendu_statique.verifier_actifs(schema, actifs)
    assert [r["code"] for r in refus] == [rendu_statique.REJ_IMAGE_DIMENSIONS]
    assert "1200x630" in refus[0]["detail"]


@pytest.mark.parametrize("contenu", [
    b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><script>alert(1)</script></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" onload="x()"></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><image href="https://cdn.example/a.png"/></svg>',
])
def test_svg_actif_ou_externe_refuse(schema, actifs, contenu):
    actifs["images/gouttiere.svg"] = contenu
    assert [r["code"] for r in rendu_statique.verifier_actifs(schema, actifs)] == [rendu_statique.REJ_IMAGE_ACTIVE]


def test_png_lu_par_son_en_tete_et_format_illisible_refuse(schema, actifs):
    schema["images"][1]["fichier"] = "images/gouttiere.png"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (800).to_bytes(4, "big") + (600).to_bytes(4, "big") + b"\x08"
    actifs["images/gouttiere.png"] = png
    assert rendu_statique.verifier_actifs(schema, actifs) == []
    actifs["images/gouttiere.png"] = b"pas une image"
    assert [r["code"] for r in rendu_statique.verifier_actifs(schema, actifs)] == [rendu_statique.REJ_IMAGE_FORMAT]


def test_texte_visible_exclut_tete_et_style(fichiers):
    texte = qa_site.texte_visible(_page(fichiers, "contact/index.html"))
    assert "+1 450 555 0142" in texte and "box-sizing" not in texte and "@graph" not in texte
