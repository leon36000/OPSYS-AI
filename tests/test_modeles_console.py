"""Console « Modèles et rôles » : protections, gestes N3 confirmés, parcours HTTP avec faux serveur, aucune fuite."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from faux_litellm import CLE_FICTIVE
from modeles_aide import (
    ALIAS,
    CLE_AMONT,
    MOT_DE_PASSE,
    PROPRIETAIRE,
    declarer_profil,
    definir_secrets,
    preparer_identites,
)

from opsys import identite
from opsys.console import application, modeles_ui
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.roles_modeles import service

FICTIF = True


@pytest.fixture
def client(session, cle_coffre, faux):
    preparer_identites(session)
    app = application.creer_application(
        Configuration("secret-session-modeles-fictif-" + "x" * 32), charger_departements(), session
    )
    with TestClient(app, base_url="https://testserver/opsys") as c:
        c.faux = faux
        yield c


def _connexion(client, user=PROPRIETAIRE):
    r = client.post("/connexion", data={"identifiant": user, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False)
    assert r.status_code == 303


def _csrf(client):
    return client.get("/api/session").json()["csrf"]


def _post(client, chemin, **champs):
    return client.post(chemin, data={"csrf": _csrf(client), **champs}, follow_redirects=False)


def _suivre(client, reponse):
    assert reponse.status_code == 303
    return client.get(reponse.headers["location"].removeprefix("/opsys"))


def _preparer(session, faux):
    declarer_profil(session)
    definir_secrets(session, CLE_FICTIVE)


def _connecter(client, faux, **extra):
    return _post(
        client,
        "/plateforme/modeles/passerelle",
        mode="integree",
        url_base=faux.url,
        secret_cle="passerelle.cle",
        secret_openrouter="passerelle.openrouter",
        confirme_n3="oui",
        **extra,
    )


def test_pages_protegees_session_role_no_store(client):
    assert client.get("/plateforme/modeles", follow_redirects=False).status_code == 303
    assert client.get("/api/plateforme/modeles").status_code == 401
    _connexion(client, "vendeur_fictif")
    for chemin in ("/plateforme/modeles", "/api/plateforme/modeles"):
        assert client.get(chemin, follow_redirects=False).status_code == 403
    r = _post(client, "/plateforme/modeles/role/retirer", role="llm_fort", confirme_n3="oui")
    assert r.status_code == 403
    client.post("/deconnexion", data={"csrf": _csrf(client)})
    _connexion(client)
    r = client.get("/plateforme/modeles")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert '<a href="/opsys/plateforme/modeles" aria-current="page">Modèles et rôles</a>' in r.text


def test_csrf_obligatoire_sur_chaque_ecriture(client):
    _connexion(client)
    for chemin in (
        "passerelle",
        "passerelle/retirer",
        "passerelle/tester",
        "raisonnement/activer",
        "raisonnement/desactiver",
        "role/connecter",
        "role/affecter",
        "role/retirer",
        "role/plafonds",
        "role/tester",
        "revenir",
    ):
        r = client.post(
            f"/plateforme/modeles/{chemin}",
            data={"csrf": "faux", "role": "llm_fort", "confirme_n3": "oui"},
            follow_redirects=False,
        )
        assert r.status_code == 403, chemin
    assert client.faux.appels == []


def test_role_relu_en_base_a_chaque_requete(client, session):
    _connexion(client)
    assert client.get("/plateforme/modeles").status_code == 200
    with session() as cnx:
        identite.ajouter_role(cnx, PROPRIETAIRE, "employee")
        identite.retirer_role(cnx, PROPRIETAIRE, "nathan_owner")
    csrf = _csrf(client)
    assert client.get("/plateforme/modeles", follow_redirects=False).status_code == 403
    r = client.post("/plateforme/modeles/raisonnement/desactiver", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 403


def test_page_d_une_installation_neuve_rend_les_dix_roles_inertes_et_les_recommandations(client):
    _connexion(client)
    page = client.get("/plateforme/modeles").text
    for role in (
        "llm_rapide",
        "llm_fort",
        "llm_raisonnement",
        "embeddings",
        "reranker",
        "ocr",
        "vl",
        "stt",
        "tts",
        "image",
    ):
        assert f'id="r-{role}"' in page
    assert page.count("aucun appel (fail-closed)") == 10
    assert "recommandation, non validée" in page.lower() or "recommandation non validee" in page.lower().replace(
        "é", "e"
    )
    assert "PROFIL_CLIENT_ABSENT" in page and "Non configurée" in page and "Escalade inactive" in page
    assert "escalade_raisonnement" in page and "approbation requise" in page
    api = client.get("/api/plateforme/modeles").json()
    assert api["ok"] and len(api["roles"]) == 10 and api["passerelle"] == {"configuree": False}


def test_parcours_http_passerelle_catalogue_role_plafonds_raisonnement_retour_arriere(client, session, faux):
    _connexion(client)
    _preparer(session, faux)
    # N3 sans confirmation : refusé, rien n'est écrit
    r = _post(client, "/plateforme/modeles/passerelle", mode="integree", url_base=faux.url, secret_cle="passerelle.cle")
    assert "erreur=REJ-MODELES-CONFIRMATION-N3-REQUISE" in r.headers["location"]
    assert "Action refusée (REJ-MODELES-CONFIRMATION-N3-REQUISE)" in _suivre(client, r).text
    with session() as cnx:
        assert service.passerelle(cnx) is None
    assert "ok=passerelle" in _connecter(client, faux).headers["location"]
    # catalogue
    r = _post(client, "/plateforme/modeles/passerelle/tester")
    assert "ok=catalogue" in r.headers["location"]
    page = _suivre(client, r).text
    assert "opsys-haiku-5-5" in page and "Catalogue de la passerelle" in page and "Connectée" in page
    # connecter un modèle à un rôle : N3 + EFVP + contrat
    champs = dict(
        role="llm_rapide",
        alias="opsys-haiku-5-5",
        amont="openrouter/anthropic/claude-haiku-5.5",
        efvp_ref="EFVP-FICTIVE-1",
        contrat_ref="CONTRAT-FICTIF-1",
    )
    assert (
        "REJ-MODELES-CONFIRMATION-N3-REQUISE"
        in _post(client, "/plateforme/modeles/role/connecter", **champs).headers["location"]
    )
    r = _post(client, "/plateforme/modeles/role/connecter", confirme_n3="oui", **champs)
    assert "ok=role_connecte" in r.headers["location"]
    page = _suivre(client, r).text
    assert "llm.passerelle.opsys-haiku-5-5" in page and "Conforme" in page and "Non mesuré" in page
    assert "sur_contrat" in page and "EFVP-FICTIVE-1" in page and "coût non déclaré" in page
    # test de connexion : un appel minuscule
    r = _post(client, "/plateforme/modeles/role/tester", role="llm_rapide")
    assert "ok=teste" in r.headers["location"]
    assert "succes" in _suivre(client, r).text
    assert faux.appels_modele("opsys-haiku-5-5")[0]["max_tokens"] == 8
    # plafonds (N2 : sans confirmation)
    r = _post(
        client,
        "/plateforme/modeles/role/plafonds",
        role="llm_rapide",
        plafond_jetons_jour="5000",
        budget_usd_mois="3.5",
    )
    assert "ok=plafonds" in r.headers["location"]
    page = _suivre(client, r).text
    assert "plafond 5000 jetons/jour" in page and "budget 3.5 USD/mois" in page
    assert (
        "REJ-MODELES-DECLARATION-INVALIDE"
        in _post(client, "/plateforme/modeles/role/plafonds", role="llm_rapide", plafond_jetons_jour="-3").headers[
            "location"
        ]
    )
    # raisonnement : activation refusée sans N3 explicite, puis acceptée avec rôle affecté
    assert (
        "REJ-MODELES-ROLE-NON-CONFIGURE"
        in _post(
            client,
            "/plateforme/modeles/raisonnement/activer",
            motif="Analyse contractuelle complexe",
            confirme_n3="oui",
        ).headers["location"]
    )
    _post(
        client,
        "/plateforme/modeles/role/connecter",
        role="llm_raisonnement",
        alias="opsys-opus-5-5",
        amont="openrouter/anthropic/claude-opus-5.5",
        efvp_ref="EFVP-FICTIVE-1",
        contrat_ref="CONTRAT-FICTIF-1",
        confirme_n3="oui",
    )
    assert (
        "REJ-MODELES-CONFIRMATION-N3-REQUISE"
        in _post(client, "/plateforme/modeles/raisonnement/activer", motif="Analyse contractuelle complexe").headers[
            "location"
        ]
    )
    r = _post(
        client,
        "/plateforme/modeles/raisonnement/activer",
        motif="Analyse <b>contractuelle</b> complexe",
        confirme_n3="oui",
    )
    assert "ok=raisonnement_active" in r.headers["location"]
    page = _suivre(client, r).text
    assert (
        "Escalade ACTIVE" in page and "&lt;b&gt;contractuelle&lt;/b&gt;" in page and "<b>contractuelle</b>" not in page
    )
    r = _post(client, "/plateforme/modeles/raisonnement/desactiver")
    assert "ok=raisonnement_desactive" in r.headers["location"]
    # retrait puis retour arrière
    assert (
        "REJ-MODELES-CONFIRMATION-N3-REQUISE"
        in _post(client, "/plateforme/modeles/role/retirer", role="llm_rapide").headers["location"]
    )
    assert (
        "ok=role_retire"
        in _post(client, "/plateforme/modeles/role/retirer", role="llm_rapide", confirme_n3="oui").headers["location"]
    )
    ligne = client.get("/plateforme/modeles").text.split('id="r-llm_rapide"')[1].split("</tr>")[0]
    assert "aucun appel (fail-closed)" in ligne
    assert (
        "ok=revenu"
        in _post(client, "/plateforme/modeles/revenir", cible="role:llm_rapide", confirme_n3="oui").headers["location"]
    )
    ligne = client.get("/plateforme/modeles").text.split('id="r-llm_rapide"')[1].split("</tr>")[0]
    assert "aucun appel (fail-closed)" not in ligne and "opsys-haiku-5-5" in ligne
    # historique visible, sans secret
    page = client.get("/plateforme/modeles").text
    assert "role.affecter" in page and "role.retirer" in page and "revenir" in page


def test_aucun_secret_dans_les_pages_ni_l_api(client, session, faux):
    _connexion(client)
    _preparer(session, faux)
    _connecter(client, faux)
    _post(client, "/plateforme/modeles/passerelle/tester")
    _post(
        client,
        "/plateforme/modeles/role/connecter",
        role="llm_fort",
        alias="opsys-sonnet-5-5",
        efvp_ref="E-1",
        contrat_ref="C-1",
        amont="openrouter/anthropic/claude-sonnet-5.5",
        confirme_n3="oui",
    )
    for chemin in ("/plateforme/modeles", "/api/plateforme/modeles", "/plateforme/secrets", "/plateforme/fournisseurs"):
        texte = client.get(chemin).text
        assert CLE_FICTIVE not in texte and CLE_AMONT not in texte, chemin
    page = client.get("/plateforme/modeles").text
    assert "passerelle.cle" in page  # le NOM du secret est visible, jamais sa valeur


def test_la_page_est_refusee_si_un_secret_s_y_glisse(client, session, faux, monkeypatch):
    _connexion(client)
    from opsys.secrets_coffre import masquage

    monkeypatch.setattr(modeles_ui, "contenu", lambda *a, **k: "<p>sk-abcdefghijklmnop</p>")
    assert masquage.contient_secret("sk-abcdefghijklmnop")
    assert client.get("/plateforme/modeles", follow_redirects=False).status_code == 500


def test_erreurs_de_saisie_ne_font_pas_de_500(client, session, faux):
    _connexion(client)
    _preparer(session, faux)
    for chemin, champs in (
        ("passerelle", {"mode": "x", "url_base": "n'importe quoi", "secret_cle": "?"}),
        ("role/connecter", {"role": "inconnu", "confirme_n3": "oui"}),
        ("role/connecter", {"role": "llm_fort", "alias": "a", "confirme_n3": "oui"}),
        (
            "role/affecter",
            {
                "role": "llm_fort",
                "fournisseur_id": "x",
                "modele_appel": "m",
                "replis": "sans-egal",
                "confirme_n3": "oui",
            },
        ),
        ("role/tester", {"role": "inconnu"}),
        ("role/tester", {"role": "llm_fort"}),
        ("revenir", {"cible": "role:llm_fort", "confirme_n3": "oui"}),
        ("raisonnement/activer", {"motif": "x", "confirme_n3": "oui"}),
        ("passerelle/tester", {}),
    ):
        r = _post(client, f"/plateforme/modeles/{chemin}", **champs)
        assert r.status_code == 303 and "erreur=REJ-MODELES-" in r.headers["location"], (chemin, r.headers)
        assert "Action refusée" in _suivre(client, r).text


def test_affectation_directe_d_un_fournisseur_du_registre_et_replis(client, session, faux):
    _connexion(client)
    _preparer(session, faux)
    _connecter(client, faux)
    from modeles_aide import fournisseur_local, fournisseur_passerelle

    local = fournisseur_local(session, "llm.local.fictif", "http://127.0.0.1:8000/v1")
    ident = fournisseur_passerelle(session, "llm_fort", ALIAS["llm_fort"])
    r = _post(
        client,
        "/plateforme/modeles/role/affecter",
        role="llm_fort",
        fournisseur_id=ident,
        modele_appel=ALIAS["llm_fort"],
        replis=f"{local}=qwen-local-fictif\n",
        confirme_n3="oui",
    )
    assert "ok=role_affecte" in r.headers["location"]
    ligne = client.get("/plateforme/modeles").text.split('id="r-llm_fort"')[1].split("</tr>")[0]
    assert "<li><code>llm.local.fictif</code> — qwen-local-fictif (conforme)</li>" in ligne
