"""Contrôle qualité du site généré : conforme sur le site fictif ; chaque contrôle échoue sur sa propre altération."""

from __future__ import annotations

import copy

import pytest
from m7_marketing.site import qa_site

FICTIF = True
ACCUEIL = "index.html"
FAQ_EN = "en/faq/index.html"


def _echecs(fichiers, schema):
    rapport = qa_site.controler_site(fichiers, schema)
    return {c["code"] for c in rapport["controles"] if not c["ok"]}


def _remplacer(fichiers, chemin, avant, apres, compte=1):
    texte = fichiers[chemin].decode("utf-8")
    assert avant in texte, avant
    fichiers[chemin] = texte.replace(avant, apres, compte).encode("utf-8")


def test_le_site_fictif_genere_est_conforme_a_tous_les_controles(fichiers, schema):
    rapport = qa_site.controler_site(fichiers, schema)
    assert [c["code"] for c in rapport["controles"]] == [code for code, _ in qa_site.CONTROLES]
    assert rapport["conforme"] is True, qa_site.rapport_lisible(rapport)
    assert (rapport["pages"], rapport["fichiers"]) == (20, 25)
    assert all(c["constats"] == [] for c in rapport["controles"])


def test_controles_attendus_par_la_decision_d_architecte():
    assert len(qa_site.CONTROLES) == 17
    assert {"QA-LIENS-INTERNES", "QA-ANCRES", "QA-HTML-BIEN-FORME", "QA-JSONLD", "QA-CONTRASTE", "QA-POIDS"} <= {
        code for code, _ in qa_site.CONTROLES
    }


@pytest.mark.parametrize(("avant", "apres"), [
    ("</section>", ""),                                     # élément non fermé
    ('<section id="section-2">', '<section id="section-1">'),  # id en double
    ("<br>", "<br></br>"),                                  # fermeture d'un élément vide
])
def test_html_mal_forme_detecte(fichiers, schema, avant, apres):
    _remplacer(fichiers, ACCUEIL, avant, apres)
    assert "QA-HTML-BIEN-FORME" in _echecs(fichiers, schema)


def test_doctype_absent_detecte(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, "<!DOCTYPE html>\n", "")
    assert _echecs(fichiers, schema) == {"QA-HTML-BIEN-FORME"}


def test_garde_fou_de_page_rejoue_deux_h1(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, "<h2>Nos services</h2>", "<h1>Nos services</h1>")
    rapport = qa_site.controler_site(fichiers, schema)
    garde = next(c for c in rapport["controles"] if c["code"] == "QA-GARDE-FOU-PAGE")
    assert not garde["ok"] and garde["constats"][0]["detail"].startswith("G-09")


def test_lien_interne_casse_detecte(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, 'href="/contact/"', 'href="/nous-joindre/"')
    assert _echecs(fichiers, schema) == {"QA-LIENS-INTERNES"}


def test_lien_sans_barre_finale_ne_resout_pas_une_url_propre(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, 'href="/contact/"', 'href="/contact"')
    assert _echecs(fichiers, schema) == {"QA-LIENS-INTERNES"}


def test_lien_relatif_resolu_depuis_la_page(fichiers, schema):
    _remplacer(fichiers, "services/index.html", 'href="/services/gouttieres/"', 'href="gouttieres/"')
    assert _echecs(fichiers, schema) == set()
    _remplacer(fichiers, "services/index.html", 'href="gouttieres/"', 'href="../gouttieres/"')
    assert _echecs(fichiers, schema) == {"QA-LIENS-INTERNES"}


def test_ancre_absente_detectee(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, 'href="/contact/"', 'href="/contact/#formulaire"')
    assert _echecs(fichiers, schema) == {"QA-ANCRES"}
    _remplacer(fichiers, ACCUEIL, 'href="/contact/#formulaire"', 'href="/contact/#coordonnees"')
    assert _echecs(fichiers, schema) == set()


@pytest.mark.parametrize(("avant", "apres"), [
    (' width="1200" height="630"', ""),       # dimensions absentes
    (' width="1200" height="630"', ' width="1200" height="600"'),  # dimensions déclarées fausses
])
def test_image_sans_dimensions_justes_detectee(fichiers, schema, avant, apres):
    _remplacer(fichiers, ACCUEIL, avant, apres)
    assert "QA-IMAGES" in _echecs(fichiers, schema)


def test_image_sans_alt_detectee(fichiers, schema):
    texte = fichiers[ACCUEIL].decode()
    debut = texte.index('alt="Illustration d&#x27;une façade')
    fin = texte.index('"', debut + 5)
    fichiers[ACCUEIL] = (texte[:debut] + 'alt=""' + texte[fin + 1:]).encode()
    assert "QA-IMAGES" in _echecs(fichiers, schema)


def test_champ_de_formulaire_sans_libelle_detecte_et_libelle_accepte(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, "</main>", '<form><input type="text" name="nom"></form></main>')
    assert _echecs(fichiers, schema) == {"QA-FORMULAIRES"}
    _remplacer(fichiers, ACCUEIL, '<input type="text" name="nom">',
               '<label for="nom">Nom</label><input type="text" id="nom" name="nom">')
    assert _echecs(fichiers, schema) == set()
    _remplacer(fichiers, ACCUEIL, '<label for="nom">Nom</label><input type="text" id="nom" name="nom">',
               '<label>Nom <select name="ville"><option>Laval</option></select></label>')
    assert _echecs(fichiers, schema) == set()


@pytest.mark.parametrize(("avant", "apres"), [
    ("a:focus-visible { outline: 3px solid #e8590c; outline-offset: 2px; }", ""),
    ("a:focus-visible { outline: 3px solid #e8590c;", "a:focus-visible { outline: 1px solid #e8590c;"),
    ("img { max-width: 100%; height: auto; }", "img { max-width: 100%; height: auto; } a { outline: none; }"),
])
def test_focus_invisible_detecte(fichiers, schema, avant, apres):
    _remplacer(fichiers, ACCUEIL, avant, apres)
    assert "QA-FOCUS-VISIBLE" in _echecs(fichiers, schema)


def test_contraste_de_la_charte_insuffisant_detecte(fichiers, schema):
    charte = copy.deepcopy(schema)
    charte["charte"]["focus"] = "#ffd8a8"
    assert _echecs(fichiers, charte) == {"QA-CONTRASTE"}


def test_langue_de_page_et_hreflang_non_reciproque_detectes(fichiers, schema):
    _remplacer(fichiers, FAQ_EN, '<html lang="en-CA">', '<html lang="fr-CA">')
    assert "QA-LANGUES" in _echecs(fichiers, schema)


def test_hreflang_absent_detecte(fichiers, schema):
    _remplacer(fichiers, FAQ_EN,
               '<link rel="alternate" hreflang="x-default" href="https://revetements-horizon.example/questions-frequentes/">\n',
               "")
    assert _echecs(fichiers, schema) == {"QA-LANGUES"}


def test_hreflang_vers_une_page_qui_ne_renvoie_pas_detecte(fichiers, schema):
    _remplacer(fichiers, "questions-frequentes/index.html",
               'hreflang="en-CA" href="https://revetements-horizon.example/en/faq/"',
               'hreflang="en-CA" href="https://revetements-horizon.example/en/contact/"')
    assert "QA-LANGUES" in _echecs(fichiers, schema)


@pytest.mark.parametrize(("avant", "apres"), [
    ('<link rel="canonical" href="https://revetements-horizon.example/">',
     '<link rel="canonical" href="https://revetements-horizon.example/accueil/">'),
    ('<meta property="og:title" content="Revêtement extérieur et gouttières à Laval">\n', ""),
    ('<meta property="og:locale" content="fr_CA">', '<meta property="og:locale" content="en_CA">'),
])
def test_canonique_et_open_graph_detectes(fichiers, schema, avant, apres):
    _remplacer(fichiers, ACCUEIL, avant, apres)
    assert "QA-CANONIQUE-OG" in _echecs(fichiers, schema)


@pytest.mark.parametrize(("avant", "apres"), [
    ('"telephone": "+1 450 555 0142"', '"telephone": "+1 450 555 0199"'),       # JSON-LD discordant de la NAP
    ('"@graph": [{', '"@graph": [{{'),                                          # JSON mal formé
    ('"name": "Which cities do you serve?"', '"name": "Do you work in Montreal?"'),  # FAQ absente du texte visible
])
def test_json_ld_invalide_ou_discordant_detecte(fichiers, schema, avant, apres):
    _remplacer(fichiers, FAQ_EN, avant, apres)
    assert "QA-JSONLD" in _echecs(fichiers, schema)


def test_nap_absente_du_texte_visible_detectee(fichiers, schema):
    _remplacer(fichiers, FAQ_EN, ">+1 450 555 0142</a>", ">nous appeler</a>")
    assert _echecs(fichiers, schema) == {"QA-JSONLD"}


@pytest.mark.parametrize("ajout", [
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">',
    '<link rel="preconnect" href="https://cdn.example.net">',
])
def test_ressource_tierce_detectee(fichiers, schema, ajout):
    _remplacer(fichiers, ACCUEIL, "</head>", ajout + "\n</head>")
    assert "QA-RESSOURCES-TIERCES" in _echecs(fichiers, schema)


def test_police_ou_import_dans_la_feuille_de_style_detecte(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, "<style>", "<style>@import url(https://cdn.example.net/x.css); ")
    assert "QA-RESSOURCES-TIERCES" in _echecs(fichiers, schema)


def test_lien_externe_de_navigation_n_est_pas_une_ressource(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, "</main>", '<p><a href="https://www.rbq.gouv.qc.ca/">RBQ</a></p></main>')
    assert _echecs(fichiers, schema) == set()


@pytest.mark.parametrize("ajout", [
    '<script src="/app.js"></script>',
    '<p><a href="javascript:alert(1)">x</a></p>',
    '<p onclick="x()">x</p>',
])
def test_javascript_detecte(fichiers, schema, ajout):
    _remplacer(fichiers, ACCUEIL, "</main>", ajout + "</main>")
    assert "QA-SCRIPTS" in _echecs(fichiers, schema)


def test_page_trop_lourde_detectee(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, "</main>", "<p>" + "x" * qa_site.POIDS_HTML_MAX + "</p></main>")
    assert _echecs(fichiers, schema) == {"QA-POIDS"}


def test_image_trop_lourde_compte_dans_le_poids_de_la_page(fichiers, schema):
    fichiers["images/facade-revetement.svg"] = fichiers["images/facade-revetement.svg"].replace(
        b"</svg>", b"<!--" + b"x" * qa_site.POIDS_PAGE_MAX + b"--></svg>"
    )
    assert _echecs(fichiers, schema) == {"QA-POIDS"}


def test_plan_du_site_incomplet_ou_mal_forme_detecte(fichiers, schema):
    sitemap = fichiers["sitemap.xml"].decode()
    debut = sitemap.index("<url>")
    fichiers["sitemap.xml"] = (sitemap[:debut] + sitemap[sitemap.index("</url>") + len("</url>\n"):]).encode()
    assert _echecs(fichiers, schema) == {"QA-PLAN-DU-SITE"}
    fichiers["sitemap.xml"] = b"<urlset><url>"
    assert _echecs(fichiers, schema) == {"QA-PLAN-DU-SITE"}
    del fichiers["sitemap.xml"]
    assert "QA-PLAN-DU-SITE" in _echecs(fichiers, schema)


@pytest.mark.parametrize("robots", [
    b"User-agent: *\nDisallow: /\n",
    b"User-agent: *\nAllow: /\n",
])
def test_robots_bloquant_ou_sans_plan_du_site_detecte(fichiers, schema, robots):
    fichiers["robots.txt"] = robots
    assert _echecs(fichiers, schema) == {"QA-ROBOTS"}


def test_page_404_absente_ou_indexable_detectee(fichiers, schema):
    _remplacer(fichiers, "404.html", '<meta name="robots" content="noindex">\n', "")
    assert "QA-404" in _echecs(fichiers, schema)
    del fichiers["en/404.html"]
    rapport = qa_site.controler_site(fichiers, schema)
    page_404 = next(c for c in rapport["controles"] if c["code"] == "QA-404")
    assert {c["fichier"] for c in page_404["constats"]} == {"404.html", "en/404.html"}


def test_rapport_lisible_nomme_chaque_controle_et_chaque_constat(fichiers, schema):
    _remplacer(fichiers, ACCUEIL, 'href="/contact/"', 'href="/nous-joindre/"')
    texte = qa_site.rapport_lisible(qa_site.controler_site(fichiers, schema))
    assert texte.startswith("Contrôle qualité du site revetements-horizon-fictif : NON CONFORME")
    assert "- QA-LIENS-INTERNES — Liens internes valides : ÉCHEC (1)" in texte
    assert "index.html : <a href=\"/nous-joindre/\"> : nous-joindre/index.html introuvable" in texte
    assert "focus/primaire" in texte


def test_chemin_de_fichier_inverse_les_url_propres():
    assert qa_site.chemin_de_fichier("index.html") == "/"
    assert qa_site.chemin_de_fichier("en/services/index.html") == "/en/services/"
    assert qa_site.chemin_de_fichier("en/404.html") == "/en/404.html"
