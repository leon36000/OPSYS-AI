"""Corrections issues du banc de parcours navigateur (docs/qualification/QUALIFICATION-NAVIGATEUR.md).

Chaque test ci-dessous épingle, SANS navigateur, un défaut que le banc a mis en évidence dans Chromium réel :
- la CSP bloquait `fetch`/`EventSource` des wallboards (pas de `connect-src`) : ouverture limitée à ces pages ;
- tableaux sans conteneur défilant (la classe `.table-defilante` n'avait AUCUNE règle) : la PAGE défilait ;
- cases à cocher étirées à 100 % de largeur ; pastille en sombre à 2,52:1 ; texte long sans coupure qui déborde ;
- sous-navigation de la Plateforme incohérente (impasses) et non repérée comme navigation ;
- second `h1` dans des pages du gabarit ; erreurs rendues `role="status"` ; aucun lien d'évitement ;
- refus d'une PAGE rendu en JSON brut pour un navigateur.
Données fictives, aucune route réseau.
"""

from __future__ import annotations

import html as html_module
import re

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from opsys import identite
from opsys.console import application, pages, ressources
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.secrets_coffre import cle_maitresse

FICTIF = True
MDP = "mot-de-passe-corrections-fictif-2026"
SECRET = "secret-session-corrections-fictif-" + "x" * 32


# -- contraste calculé sur la feuille de style réellement servie -----------------------------------------------------

def _luminance(hexa: str) -> float:
    r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contraste(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _variables(bloc: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", bloc))


def _themes() -> tuple[dict[str, str], dict[str, str]]:
    css = ressources.CSS
    sombre = css.split("@media (prefers-color-scheme: dark)")[1].split("}")[0]
    return _variables(css.split("@media (prefers-color-scheme: dark)")[0]), _variables(sombre)


def test_pastille_lisible_en_clair_et_en_sombre():
    clair, sombre = _themes()
    assert "color: var(--sur-danger)" in ressources.CSS and "color: #ffffff; font-size: .8em" not in ressources.CSS
    assert _contraste(clair["sur-danger"], clair["danger"]) >= 4.5
    # Avant : texte blanc sur #ff7b72 = 2,52:1 (mesuré dans Chromium en thème sombre).
    assert _contraste(sombre["sur-danger"], sombre["danger"]) >= 4.5


def test_paires_de_badges_et_messages_conformes_aa_dans_les_deux_themes():
    clair, sombre = _themes()
    for theme in (clair, sombre):
        for texte, fond in (("ok", "ok-fond"), ("alerte", "alerte-fond"), ("danger", "danger-fond"), ("texte", "fond"),
                            ("attenue", "surface"), ("accent-texte", "accent")):
            assert _contraste(theme[texte], theme[fond]) >= 4.5, (texte, fond)


def test_feuille_de_style_regles_issues_du_banc():
    css = ressources.CSS
    assert re.search(r"\.table-defilante\s*\{[^}]*overflow-x:\s*auto", css)  # la classe existait sans aucune règle
    assert re.search(r'input\[type="checkbox"\], input\[type="radio"\]\s*\{\s*width:\s*auto', css)
    assert re.search(r"\.carte, \.grille > \*\s*\{[^}]*min-width:\s*0[^}]*overflow-wrap:\s*anywhere", css)
    assert re.search(r"\bcode\s*\{\s*overflow-wrap:\s*anywhere", css)
    assert ".message-ok, .message-succes" in css  # « succes » est le genre rendu après une demande cron
    assert re.search(r"\.saut:focus\s*\{[^}]*left:\s*\.5rem", css)
    assert re.search(r"@media \(max-width: 600px\)\s*\{.*?\.entete nav \{ flex-basis: 100%", css, re.S)


# -- gabarit ---------------------------------------------------------------------------------------------------------

def test_tableaux_enveloppes_une_seule_fois_et_sans_casser_les_imbriques():
    brut = "<p>a</p><table><tr><td>1</td></tr></table><p>b</p>"
    attendu = '<p>a</p><div class="table-defilante"><table><tr><td>1</td></tr></table></div><p>b</p>'
    assert pages.envelopper_tables(brut) == attendu
    deja = '<div class="table-defilante"><table><tr><td>1</td></tr></table></div>'
    assert pages.envelopper_tables(deja) == deja  # idempotent : pas de double enveloppe
    assert pages.envelopper_tables(pages.envelopper_tables(brut)) == pages.envelopper_tables(brut)
    imbrique = "<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>"
    assert pages.envelopper_tables(imbrique) == f'<div class="table-defilante">{imbrique}</div>'
    assert pages.envelopper_tables("<p>aucun tableau</p>") == "<p>aucun tableau</p>"
    # Un attribut ou un texte contenant « table » n'est pas une balise.
    assert pages.envelopper_tables("<p>tableau &lt;table&gt;</p>") == "<p>tableau &lt;table&gt;</p>"


def test_gabarit_un_seul_h1_lien_d_evitement_et_cible():
    html = pages.gabarit("Titre", "<section><h1>Second titre</h1><p>x</p></section><table><tr><td>1</td></tr></table>",
                         prefixe="/opsys")
    assert html.count("<h1") == 1 and "<h2>Second titre</h2>" in html
    assert '<a class="saut" href="#contenu">Aller au contenu</a>' in html
    assert '<h1 id="contenu" tabindex="-1">Titre</h1>' in html
    assert html.index('class="saut"') < html.index("<header")  # premier arrêt de tabulation
    assert '<div class="table-defilante"><table>' in html
    assert "<main>" in html  # la forme « <main> » est épinglée par d'autres tests (split)


def test_erreur_annoncee_en_alert_succes_en_status():
    erreur = pages.gabarit("T", "", prefixe="/opsys", bandeau=("Échec", "erreur"))
    assert '<p class="message message-erreur" role="alert">Échec</p>' in erreur
    for genre in ("ok", "alerte", "succes"):
        page = pages.gabarit("T", "", prefixe="/opsys", bandeau=("M", genre))
        assert f'class="message message-{genre}" role="status"' in page


# Épinglées ici : relues du code, une section retirée du code passerait inaperçue.
SECTIONS_ATTENDUES = ["fournisseurs", "secrets", "avatars", "connaissances", "connecteurs"]


def test_navigation_plateforme_unique_nommee_et_courante():
    assert [cle for cle, _ in pages.SECTIONS_PLATEFORME] == SECTIONS_ATTENDUES
    for courant in SECTIONS_ATTENDUES:
        nav = pages.navigation_plateforme("/opsys", courant)
        assert nav.startswith('<nav aria-label="Plateforme">')
        assert nav.count("aria-current") == 1 and f'/plateforme/{courant}" aria-current="page"' in nav
        for cle, libelle in pages.SECTIONS_PLATEFORME:
            assert f'<a href="/opsys/plateforme/{cle}"' in nav and f">{libelle}</a>" in nav
    assert "&lt;" in pages.navigation_plateforme("/<x>", "secrets")  # préfixe échappé


# -- CSP : ouverture `connect-src` limitée aux wallboards ------------------------------------------------------------

def _app_minimale():
    async def ok(request):
        return PlainTextResponse("ok")

    return application._EntetesSecurite(Starlette(routes=[
        Route("/opsys/wallboards/pouls-de-l-entreprise", ok), Route("/opsys/wallboards", ok),
        Route("/opsys/departements", ok), Route("/opsys/api/wallboards/pouls/flux", ok)
    ]))


@pytest.mark.parametrize("chemin,ouvert", [
    ("/opsys/wallboards/pouls-de-l-entreprise", True),
    ("/opsys/wallboards", False),  # la liste n'a pas de script de rafraîchissement
    ("/opsys/departements", False),
    ("/opsys/api/wallboards/pouls/flux", False),  # le flux est appelé PAR la page ; sa propre CSP importe peu
])
def test_csp_connect_src_seulement_sur_la_page_de_wallboard(chemin, ouvert):
    reponse = TestClient(_app_minimale()).get(chemin)
    csp = reponse.headers["content-security-policy"]
    assert ("connect-src 'self'" in csp) is ouvert
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "*" not in csp  # aucune origine externe


def test_csp_regex_page_wallboard_refuse_les_chemins_deguises():
    motif = application._PAGE_WALLBOARD
    assert motif.search("/opsys/wallboards/pouls")
    for hostile in ("/opsys/wallboards/", "/opsys/wallboards/../departements", "/opsys/wallboards/Pouls",
                    "/opsys/wallboards/pouls/x", "/opsys/x/wallboards", "/opsys/wallboards/-pouls"):
        assert not motif.search(hostile), hostile


# -- pages réelles : navigation Plateforme, refus lisible ------------------------------------------------------------

@pytest.fixture
def client(session, tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    with session() as cnx:
        identite.creer_personne(cnx, "owner_fictif", "Owner fictif", MDP, ["nathan_owner"])
        identite.creer_personne(cnx, "vendeur_fictif", "Vendeur fictif", MDP, ["seller"])
    app = application.creer_application(Configuration(SECRET), charger_departements(), session)
    with TestClient(app, base_url="https://testserver/opsys") as c:
        yield c


def _connexion(client, user="owner_fictif"):
    reponse = client.post("/connexion", data={"identifiant": user, "mot_de_passe": MDP}, follow_redirects=False)
    assert reponse.status_code == 303


def test_cinq_pages_plateforme_exposent_les_quatre_autres_sans_impasse(client):
    _connexion(client)
    cles = SECTIONS_ATTENDUES
    for cle in cles:
        page = client.get(f"/plateforme/{cle}")
        assert page.status_code == 200, cle
        nav = re.search(r'<nav aria-label="Plateforme">.*?</nav>', page.text, re.S)
        assert nav, cle  # Avant : un <p> différent par page, sans repère de navigation
        liens = re.findall(r'href="/opsys/plateforme/([a-z]+)"', nav.group())
        assert liens == cles, (cle, liens)  # Avant : « Connaissances » absente de Secrets et Connecteurs, etc.
        assert nav.group().count('aria-current="page"') == 1
        assert f'/plateforme/{cle}" aria-current="page"' in nav.group()
        assert page.text.count("<h1") == 1 and 'class="saut"' in page.text


def test_refus_de_page_lisible_pour_un_navigateur_json_pour_les_clients(client):
    _connexion(client, "vendeur_fictif")
    page = client.get("/plateforme/secrets", headers={"accept": "text/html,application/xhtml+xml"})
    assert page.status_code == 403 and page.headers["content-type"].startswith("text/html")
    assert "<h1" in page.text and "Accès refusé" in page.text and 'role="alert"' in page.text
    assert "Retour à la console" in page.text and "default-src 'none'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    # Un client sans « Accept: text/html » (API, serveur à serveur, tests) garde la réponse JSON d'origine.
    brut = client.get("/plateforme/secrets")
    assert brut.status_code == 403 and brut.headers["content-type"].startswith("application/json")
    assert "detail" in brut.json()
    # Un chemin d'API reste en JSON même si le client accepte le HTML.
    api = client.get("/api/plateforme/secrets", headers={"accept": "text/html"})
    assert api.status_code == 403 and api.headers["content-type"].startswith("application/json")


def test_page_inconnue_404_html_pour_navigateur_sans_trace(client):
    _connexion(client)
    r = client.get("/page-qui-n-existe-pas", headers={"accept": "text/html"})
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/html") and "Page introuvable" in r.text
    assert "Traceback" not in r.text and ".py" not in r.text
    texte = html_module.unescape(r.text)
    assert "Not Found" not in texte and "Cette page n'existe pas" in texte  # jamais le libellé anglais par défaut
    sans_page = client.post("/departements", data={}, headers={"accept": "text/html"})
    assert sans_page.status_code == 405 and "Method Not Allowed" not in sans_page.text
    assert client.get("/page-qui-n-existe-pas").status_code == 404


def test_refus_html_n_echappe_pas_un_detail_hostile(client):
    _connexion(client)
    r = client.get("/wallboards/%3Cscript%3Ealert(1)%3C%2Fscript%3E", headers={"accept": "text/html"})
    assert r.status_code in (403, 404)
    assert "<script>alert(1)" not in r.text


def test_cinq_pages_html_sans_tableau_nu_hors_conteneur_defilant(client):
    _connexion(client)
    pages_testees = ("/plateforme/fournisseurs", "/plateforme/secrets", "/plateforme/avatars",
                     "/plateforme/connaissances", "/plateforme/connecteurs", "/budgets", "/departements")
    for chemin in pages_testees:
        html = client.get(chemin).text
        assert html.count("<table") == html.count('<div class="table-defilante"><table'), chemin
