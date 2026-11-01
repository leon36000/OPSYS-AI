"""Revue adverse « web » (M7) : validations à `$`, schémas d'URL détournés, SVG actif, couleur injectée dans un SVG.

Chaque test est un exploit : ROUGE sur le code d'origine, vert après correctif. Données fictives seulement.
"""

from __future__ import annotations

import pytest
from m7_marketing.site import deploiement, guardrail, qa_site, rendu_statique, schema_site
from m7_marketing.studio import logos
from m7_marketing.wordpress import contenu

FICTIF = True
DOMAINE = "revetements-horizon.example"


def _codes(refus):
    return [r["code"] for r in refus]


# ======================================================================================= web-03 : `$` accepte « \n »
@pytest.mark.parametrize("champ,valeur", [
    ("hote", "vps.revetements-horizon.example\n"),
    ("utilisateur", "opsys-deploy\n"),
    ("utilisateur", "root\n"),  # contourne le refus explicite de « root »
])
def test_la_cible_de_deploiement_refuse_un_saut_de_ligne_final(champ, valeur):
    cible = {"hote": "vps.revetements-horizon.example", champ: valeur}
    normalisee, refus = deploiement.valider_cible(cible, DOMAINE)
    assert normalisee is None and refus, "un « \\n » final passe la validation de la cible"


def test_la_cible_de_deploiement_legitime_reste_acceptee():
    normalisee, refus = deploiement.valider_cible({"hote": "vps.revetements-horizon.example",
                                                   "utilisateur": "opsys-deploy"}, DOMAINE)
    assert refus == [] and normalisee["hote"] == "vps.revetements-horizon.example"


def _site_valide(schema):
    assert schema_site.valider_schema(schema) == []
    return schema


def test_le_schema_de_demonstration_reste_valide(schema):
    _site_valide(schema)


def test_le_schema_refuse_un_site_id_avec_saut_de_ligne_final(schema):
    schema["site_id"] += "\n"
    assert schema_site.REJ_SCHEMA_IDENTIFIANT in _codes(schema_site.valider_schema(schema))


def test_le_schema_refuse_un_slug_avec_saut_de_ligne_final(schema):
    page = next(p for p in schema["pages"] if p["slug"]["fr-CA"] != "")
    page["slug"]["fr-CA"] += "\n"
    page["slug"]["en-CA"] += "\n"
    assert schema_site.REJ_SCHEMA_SLUG in _codes(schema_site.valider_schema(schema))


def test_le_schema_refuse_un_courriel_public_avec_saut_de_ligne_final(schema):
    schema["entreprise"]["nap"]["courriel"] += "\n"
    assert schema_site.REJ_SCHEMA_NAP in _codes(schema_site.valider_schema(schema))


def test_le_schema_refuse_un_fichier_image_avec_saut_de_ligne_final(schema):
    schema["images"][0]["fichier"] += "\n"
    assert schema_site.valider_schema(schema), "un nom de fichier d'image se terminant par « \\n » est accepté"


def test_le_schema_refuse_un_domaine_reel_avec_saut_de_ligne_final(schema):
    schema["fictif"] = False
    schema["domaine"] = "exemple-reel.com\n"
    schema["entreprise"]["nap"]["courriel"] = "bonjour@exemple-reel.com"
    codes = _codes(schema_site.valider_schema(schema))
    assert schema_site.REJ_SCHEMA_CHAMP in codes


# ======================================================================================= web-06 : `javascript:` déguisé
SCHEMAS_ACTIFS = [
    '<a href="java&#9;script:alert(1)">x</a>',      # tabulation dans le schéma : retirée par les navigateurs
    '<a href="java&#10;script:alert(1)">x</a>',     # saut de ligne dans le schéma
    '<a href="&#1;javascript:alert(1)">x</a>',       # caractère de contrôle en tête : retiré par les navigateurs
    '<a href=" \tJaVaScRiPt:alert(1)">x</a>',
    '<img src="vbscr&#13;ipt:msgbox(1)">',
    '<a href="da&#9;ta:text/html;base64,PHNjcmlwdD4=">x</a>',
]


@pytest.mark.parametrize("html", SCHEMAS_ACTIFS)
def test_le_garde_fou_wordpress_refuse_un_schema_actif_deguise(html):
    article = {"type": "post", "titre": "Titre sobre", "contenu": html, "extrait": "", "slug": ""}
    assert contenu.REJ_CONTENU_ACTIF in _codes(contenu.controler(article))


@pytest.mark.parametrize("html", [
    '<p>Voyez <a href="https://exemple.example/page">notre guide</a> et <a href="/services/">nos services</a>.</p>',
    '<a href="mailto:bonjour@revetements-horizon.example">écrire</a> <a href="tel:+14505550142">appeler</a>',
    '<p>Le mot javascript n\'est pas un lien : java script</p>',
])
def test_le_garde_fou_wordpress_laisse_passer_les_liens_legitimes(html):
    article = {"type": "post", "titre": "Titre sobre", "contenu": html, "extrait": "", "slug": ""}
    assert contenu.REJ_CONTENU_ACTIF not in _codes(contenu.controler(article))


def _page(corps_lien):
    return (
        '<!doctype html><html lang="fr-CA"><head><meta charset="utf-8"><title>t</title></head>'
        f"<body><main>{corps_lien}</main></body></html>"
    )


def test_le_garde_fou_de_page_voit_un_javascript_deguise():
    codes = [c for c, _ in guardrail.validate(_page('<a href="java&#9;script:alert(1)">x</a>'))]
    assert "G-14" in codes
    assert "G-14" not in [c for c, _ in guardrail.validate(_page('<a href="/contact/">x</a>'))]


def test_le_controle_qualite_voit_un_javascript_deguise(fichiers, schema):
    fichiers = dict(fichiers)
    page = fichiers["index.html"].decode("utf-8")
    fichiers["index.html"] = page.replace("</main>", '<a href="java&#9;script:alert(1)">x</a></main>', 1).encode()
    rapport = qa_site.controler_site(fichiers, schema)
    echecs = {c["code"] for c in rapport["controles"] if not c["ok"]}
    assert "QA-SCRIPTS" in echecs


# ===================================================================================== web-07 : SVG du client
def _svg(corps):
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="800" '
            f'height="600">{corps}</svg>').encode()


SVG_ACTIFS = [
    '<a href="&#106;avascript:alert(1)"><rect width="9" height="9"/></a>',            # entité : décodée par le XML
    '<a xlink:href="java&#9;script:alert(1)"><rect width="9" height="9"/></a>',
    '<a href="&#x68;ttps://hameconnage.example/"><rect width="9" height="9"/></a>',
    '<a><set attributeName="href" to="javascript:alert(1)"/><rect width="9" height="9"/></a>',
    '<a><animate attributeName="xlink:href" values="javascript:alert(1)"/><rect width="9" height="9"/></a>',
    '<rect width="9" height="9" style="fill:url(&#104;ttps://pixel.example/p.svg#a)"/>',
    '<rect width="9" height="9" ONCLICK="alert(1)"/>',
]


@pytest.mark.parametrize("corps", SVG_ACTIFS)
def test_un_svg_actif_deguise_est_refuse(schema, actifs, corps):
    actifs["images/gouttiere.svg"] = _svg(corps)
    assert _codes(rendu_statique.verifier_actifs(schema, actifs)) == [rendu_statique.REJ_IMAGE_ACTIVE]


@pytest.mark.parametrize("corps", [
    '<rect width="9" height="9" fill="#003366"/>',
    '<a href="#ancre"><rect width="9" height="9"/></a>',
    '<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
    '<rect width="9" height="9" fill="url(#g)"/>',
])
def test_un_svg_decoratif_legitime_reste_accepte(schema, actifs, corps):
    actifs["images/gouttiere.svg"] = _svg(corps)
    assert rendu_statique.verifier_actifs(schema, actifs) == []


# ======================================================================================= web-08 : couleur d'un logo
LOGO = logos.logo_depuis_chemins(["M 0 0 H 10 V 10 H 0 Z"], 10, 10)


@pytest.mark.parametrize("couleur,fond", [('#"><b/>', None), ("#000000", '#"><b/>'), ("#12345g", None)])
def test_le_svg_du_logo_refuse_une_couleur_qui_n_est_pas_hexadecimale(couleur, fond):
    with pytest.raises(ValueError):
        logos.svg_du_logo(LOGO, couleur, fond)


def test_le_svg_du_logo_accepte_une_couleur_hexadecimale():
    svg = logos.svg_du_logo(LOGO, "#0A1b2C", "#FFFFFF")
    assert b'fill="#0A1b2C"' in svg and b'fill="#FFFFFF"' in svg
