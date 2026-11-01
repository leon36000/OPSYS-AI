"""M8.8 — Wallboards dans la VRAIE console : accès, fraîcheur visible, flux SSE borné, accessibilité, pas de script en
ligne.

Prouve (données fictives, vraie base migrée, vraie application FastAPI, vrais outils de M8) :
- accès : session obligatoire, rôle `admin` relu en base ; employé et propriétaire seul refusés ; l'API répond 401
sans session ;
- la page se sert sans script (rendu serveur) ; aucune ressource en ligne (CSP) ; langue, titres, région annoncée,
boutons ;
- une mesure périmée est écrite « PÉRIMÉE » avec son âge et la bannière n'est pas « ok » ; le même état est dans l'API ;
- le flux SSE envoie au plus `flux_max` instantanés puis `fin`, relit session et rôle à chaque envoi et se ferme si le
rôle
  est retiré ; paramètres inconnus refusés ; identifiant hostile = 404 ;
- contrastes WCAG calculés sur les paires de couleurs réellement servies, clair et sombre.
"""

from __future__ import annotations

import html as html_module
import json
import re

import pytest
from fastapi.testclient import TestClient
from m8_analytics import analytique_outils, jeux_fictifs
from sqlalchemy import select

from opsys import identite, stockage
from opsys.console import application, wallboards_ressources, wallboards_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL

FICTIF = True
MOT_DE_PASSE = "mot-de-passe-wallboard-fictif-123"
SECRET = "secret-wallboard-fictif-" + "x" * 64
FRAIS = "2026-10-30T20:00:00-04:00"
PERIME = "2026-11-12T09:00:00-04:00"
REGISTRES = {
    "chantier": "faits_chantier",
    "entonnoir": "faits_entonnoir",
    "contenus": "faits_contenus",
    "cash_libre": "faits_cash_libre",
}


@pytest.fixture
def horloge(monkeypatch):
    instant = {"valeur": FRAIS}
    monkeypatch.setattr(wallboards_ui, "_maintenant", lambda: instant["valeur"])
    monkeypatch.setattr(wallboards_ui, "_dormir", lambda secondes: instant.setdefault("dormi", []).append(secondes))
    return instant


@pytest.fixture
def navigateur(tmp_path, monkeypatch, horloge):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'wallboards-fictifs.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-fictif"))
    stockage.liberer()
    stockage.migrer()
    deps = charger_departements()
    with stockage.transaction() as cnx:
        for ident, roles in (
            ("owner.fictif", ["nathan_owner"]),
            ("admin.fictif", ["admin"]),
            ("employe.fictif", ["employee"]),
        ):
            identite.creer_personne(cnx, ident, ident, MOT_DE_PASSE, roles)
        registres = jeux_fictifs.registres_fictifs()
        for cle, nom in REGISTRES.items():
            cible = stockage.maillons("m08-analytics", nom)
            for fait in registres[cle]:
                cible.append(fait)
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe="/opsys"), deps, stockage.transaction
    )
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client
    stockage.liberer()


def _connecter(client, personne="admin.fictif"):
    reponse = client.post(
        "/connexion", data={"identifiant": personne, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False
    )
    assert reponse.status_code == 303, reponse.text


# ---------------------------------------------------------------------------
# Accès
# ---------------------------------------------------------------------------
def test_sans_session_la_page_redirige_et_l_api_refuse(navigateur):
    assert navigateur.get("/wallboards", follow_redirects=False).status_code == 303
    assert navigateur.get("/wallboards/direction", follow_redirects=False).status_code == 303
    for chemin in ("/api/wallboards/direction", "/api/wallboards/direction/flux"):
        assert navigateur.get(chemin).status_code == 401


@pytest.mark.parametrize("personne", ["employe.fictif", "owner.fictif"])
def test_seul_l_admin_relu_en_base_voit_un_wallboard(navigateur, personne):
    _connecter(navigateur, personne)
    for chemin in (
        "/wallboards",
        "/wallboards/direction",
        "/api/wallboards/direction",
        "/api/wallboards/direction/flux",
    ):
        assert navigateur.get(chemin).status_code == 403, (personne, chemin)


def test_un_identifiant_hostile_ou_inconnu_est_un_404_sans_rien_executer(navigateur):
    _connecter(navigateur)
    for chemin in (
        "/wallboards/inexistant",
        "/wallboards/DIRECTION",
        "/wallboards/..%2f..%2fetc",
        "/wallboards/a%00b",
        "/api/wallboards/inexistant",
        "/api/wallboards/x'--",
    ):
        assert navigateur.get(chemin).status_code == 404, chemin


# ---------------------------------------------------------------------------
# La page
# ---------------------------------------------------------------------------
def test_la_page_se_sert_sans_script_avec_les_gardes_d_un_ecran_accessible(navigateur):
    _connecter(navigateur)
    reponse = navigateur.get("/wallboards/direction")
    assert reponse.status_code == 200 and reponse.headers["cache-control"] == "no-store"
    html = reponse.text
    assert '<html lang="fr-CA">' in html and html.count("<h1") == 1 and 'id="wallboard"' in html
    assert 'role="status" aria-live="polite"' in html  # une seule région annoncée : la bannière
    assert html.count("aria-live") == 1
    assert '<script src="/opsys/statique/wallboard.js" defer>' in html
    assert "<script>" not in html and " style=" not in html and " onclick=" not in html  # CSP : rien en ligne
    assert "script-src 'self'" in reponse.headers["content-security-policy"]
    assert 'aria-pressed="false"' in html and "Mettre en pause" in html and 'class="saut"' in html
    assert html.count('class="tuile ') == 9 and "25 000,00 $" in html and "50,00 %" in html
    assert 'data-flux="/opsys/api/wallboards/direction/flux"' in html and 'data-intervalle="30"' in html
    for interdit in ("tech-fictif", "technicien", "client_id", "@example"):
        assert interdit not in html
    assert navigateur.get("/statique/wallboard.css").status_code == 200
    assert "EventSource" in navigateur.get("/statique/wallboard.js").text


def test_les_valeurs_a_jour_ne_portent_pas_la_mention_perimee(navigateur):
    _connecter(navigateur)
    html = navigateur.get("/wallboards/direction").text
    assert "PÉRIMÉE" not in html and "banniere-ok" in html
    assert "Toutes les mesures affichées sont à jour" in html


def test_une_mesure_perimee_est_ecrite_perimee_avec_son_age_et_la_banniere_n_est_pas_ok(navigateur, horloge):
    _connecter(navigateur)
    horloge["valeur"] = PERIME
    html = navigateur.get("/wallboards/direction").text
    assert html.count("PÉRIMÉE") >= 6 and "banniere-ok" not in html and "banniere-attention" in html
    assert "ne pas s'y fier" in html_module.unescape(html) and "fraicheur-perime" in html
    assert re.search(r"Dernier fait il y a \d+ j", html)
    api = navigateur.get("/api/wallboards/direction").json()
    assert api["banniere"]["niveau"] == "attention" and any(t["perimee"] for t in api["tuiles"])
    assert all(t["a_jour"] is False for t in api["tuiles"] if t["perimee"])


def test_le_mode_tele_et_les_parametres(navigateur):
    _connecter(navigateur)
    assert '<body class="tv">' in navigateur.get("/wallboards/direction?tv=1").text
    assert '<body class="tv">' not in navigateur.get("/wallboards/direction?tv=0").text
    for requete in ("?tv=oui", "?x=1", "?tv=1&tv=1", "?tv=1&x=1"):
        assert navigateur.get(f"/wallboards/direction{requete}").status_code == 400, requete


def test_la_liste_des_wallboards(navigateur):
    _connecter(navigateur)
    reponse = navigateur.get("/wallboards")
    assert reponse.status_code == 200 and "Pouls de l'entreprise" in html_module.unescape(reponse.text)
    assert "/opsys/wallboards/marketing" in reponse.text and 'aria-current="page">Wallboards' in reponse.text


def test_l_api_rend_le_meme_etat_que_la_page_sans_donnee_personnelle(navigateur):
    _connecter(navigateur)
    api = navigateur.get("/api/wallboards/marketing").json()
    assert api["ok"] is True and api["donnees_personnelles"] is False and len(api["tuiles"]) == 6
    impressions = next(t for t in api["tuiles"] if t["id"] == "impressions")
    assert impressions["valeur"] is None and impressions["valeur_affichee"] == "non calculable"


def test_une_page_n_est_pas_servie_si_elle_contient_un_secret(navigateur, monkeypatch):
    _connecter(navigateur)
    original = wallboards_ui.rendre_page
    monkeypatch.setattr(wallboards_ui, "rendre_page", lambda *a, **k: original(*a, **k) + "opsys-jeton:v1:" + "A" * 43)
    assert navigateur.get("/wallboards/direction").status_code == 500


# ---------------------------------------------------------------------------
# Flux SSE
# ---------------------------------------------------------------------------
def _petit_wallboard(monkeypatch, flux_max=3, intervalle=5):
    base = analytique_outils._wallboards()
    petit = dict(base["direction"], intervalle_s=intervalle, flux_max=flux_max)
    monkeypatch.setattr(analytique_outils, "_wallboards", lambda: {**base, "direction": petit})


def _evenements(reponse):
    sortie = []
    courant = {}
    for ligne in reponse.iter_lines():
        if ligne == "":
            if courant:
                sortie.append(courant)
            courant = {}
        elif ":" in ligne:
            cle, _, valeur = ligne.partition(": ")
            courant[cle] = valeur
    return sortie


def test_le_flux_envoie_au_plus_flux_max_instantanes_puis_se_ferme(navigateur, monkeypatch, horloge):
    _petit_wallboard(monkeypatch, flux_max=3, intervalle=5)
    _connecter(navigateur)
    with navigateur.stream("GET", "/api/wallboards/direction/flux") as reponse:
        assert reponse.headers["content-type"].startswith("text/event-stream")
        assert reponse.headers["cache-control"] == "no-store"
        evenements = _evenements(reponse)
    assert [e.get("event") for e in evenements] == [None, "instantane", "instantane", "instantane", "fin"]
    assert evenements[0]["retry"] == "5000"
    donnees = json.loads(evenements[1]["data"])
    assert donnees["ok"] is True and len(donnees["tuiles"]) == 9 and donnees["banniere"]["niveau"] == "ok"
    assert json.loads(evenements[-1]["data"]) == {"raison": "flux_borne", "envois": 3}
    assert horloge["dormi"] == [5, 5]  # dort entre les envois, jamais après le dernier


def test_le_flux_relit_le_role_a_chaque_envoi_et_se_ferme_si_il_est_retire(navigateur, monkeypatch, horloge):
    _petit_wallboard(monkeypatch, flux_max=5, intervalle=5)
    _connecter(navigateur)

    def retirer_le_role(secondes):
        horloge.setdefault("dormi", []).append(secondes)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "admin.fictif", "admin")

    monkeypatch.setattr(wallboards_ui, "_dormir", retirer_le_role)
    with navigateur.stream("GET", "/api/wallboards/direction/flux") as reponse:
        evenements = _evenements(reponse)
    genres = [e.get("event") for e in evenements]
    assert genres == [None, "instantane", "fin"]
    assert json.loads(evenements[-1]["data"]) == {"raison": "session_ou_role_perdu"}


def test_le_flux_ne_fuit_pas_de_donnees_a_un_non_admin(navigateur, monkeypatch):
    _petit_wallboard(monkeypatch)
    _connecter(navigateur, "employe.fictif")
    reponse = navigateur.get("/api/wallboards/direction/flux")
    assert reponse.status_code == 403 and "tuiles" not in reponse.text


def test_la_lecture_n_ecrit_rien_aux_registres_ni_au_journal_d_audit(navigateur):
    _connecter(navigateur)
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(JOURNAL)).mappings().all()
    navigateur.get("/wallboards/direction")
    navigateur.get("/api/wallboards/direction")
    with stockage.transaction() as cnx:
        apres = cnx.execute(select(JOURNAL)).mappings().all()
        faits = [m for m in stockage.maillons("m08-analytics", "faits_chantier")]
    assert [dict(r) for r in apres[: len(avant)]] == [dict(r) for r in avant]
    assert not [r for r in apres[len(avant) :] if "wallboard" in str(r["action"])]
    assert len(faits) == len(jeux_fictifs.registres_fictifs()["chantier"])  # rien n'a été écrit aux registres


# ---------------------------------------------------------------------------
# Accessibilité : contrastes calculés sur les couleurs réellement servies
# ---------------------------------------------------------------------------
def _luminance(hexa):
    r, g, b = (int(hexa[i : i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contraste(fg, bg):
    a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


@pytest.mark.parametrize("theme", ["PAIRES_CLAIR", "PAIRES_SOMBRE"])
def test_chaque_paire_de_couleurs_atteint_le_contraste_aa(theme):
    for nom, (fg, bg) in getattr(wallboards_ressources, theme).items():
        assert _contraste(fg, bg) >= 4.5, (theme, nom, fg, bg, _contraste(fg, bg))


def test_le_css_servi_utilise_exactement_les_paires_verifiees():
    css = wallboards_ressources.CSS
    for paires in (wallboards_ressources.PAIRES_CLAIR, wallboards_ressources.PAIRES_SOMBRE):
        for nom, (fg, bg) in paires.items():
            assert f"--{nom}-fg: {fg}; --{nom}-bg: {bg};" in css
    for regle in (":focus-visible", "prefers-reduced-motion", "prefers-color-scheme: dark", "forced-colors", ".tv "):
        assert regle in css
    assert "min-height: 44px" in css  # cibles tactiles


def test_l_etat_n_est_jamais_porte_par_la_couleur_seule():
    css = wallboards_ressources.CSS
    assert "line-through" in css and "repeating-linear-gradient" in css and "dashed" in css
    t = {
        "id": "a",
        "titre": "A",
        "page": 1,
        "valeur_affichee": "1",
        "etat_seuil": "critique",
        "fraicheur": "perime",
        "libelle_fraicheur": "PÉRIMÉE",
        "libelle_seuil": "critique",
        "age_affiche": "3 j 2 h",
        "source": "s",
    }
    html = wallboards_ui._tuile_html(t)
    assert "PÉRIMÉE" in html and 'aria-hidden="true"' in html and "3 j 2 h" in html


def test_la_page_relit_elle_meme_le_role_sans_compter_sur_l_outil(navigateur, monkeypatch):
    """Défense en profondeur : même si la lecture métier répondait, la page refuse un non-admin (garde de la page)."""
    from opsys.console import metier

    reponse = {"ok": True, "resultat": {"wallboards": [], "wallboard": {"id": "direction"}}}
    monkeypatch.setattr(metier, "executer", lambda *a, **k: reponse)
    _connecter(navigateur, "employe.fictif")
    for chemin in ("/wallboards", "/api/wallboards/direction"):
        assert navigateur.get(chemin).status_code == 403, chemin
    _connecter(navigateur, "owner.fictif")
    assert navigateur.get("/wallboards").status_code == 403  # propriétaire seul : l'outil de M8 exige `admin`
