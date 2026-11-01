"""Cycle OAuth côté serveur : PKCE, `state` signé à usage unique, portées minimales, jetons dans le coffre seulement,
rafraîchissement avec rotation, révocation. Réseau = doubles (`courriel_doubles`) ; coffre, base et sas = vrais."""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.parse

import courriel_doubles as dbl
import courriel_qa as qa
import pytest
from sqlalchemy import select, text

from opsys import stockage
from opsys.courriel_connecteurs import comptes
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.courriel_connecteurs.jetons import JeuJetons, StockageJetonsCoffre
from opsys.courriel_connecteurs.oauth import PORTEES_GMAIL, PORTEES_GRAPH, config_gmail
from opsys.secrets_coffre import coffre, masquage
from opsys.stockage.schema import COURRIEL_ETATS_OAUTH

FICTIF = True


@pytest.fixture
def monde(tmp_path, monkeypatch):
    return qa.preparer(tmp_path, monkeypatch)


def _demarrer(monde, compte_id="gmail-paul"):
    url = monde.service.demarrer_autorisation(qa.ADMIN, compte_id)
    return url, urllib.parse.parse_qs(urllib.parse.urlsplit(url.url).query)


# -- l'URL d'autorisation -------------------------------------------------------------------------
def test_url_autorisation_pkce_portee_minimale_et_state_signe(monde):
    qa.creer_compte(monde)
    url, p = _demarrer(monde)
    assert url.url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert p["scope"] == [qa.SCOPE_GMAIL_LECTURE]  # lecture seule : ni gmail.send, ni mail.google.com, ni modify
    assert p["code_challenge_method"] == ["S256"] and len(p["code_challenge"][0]) == 43
    assert p["access_type"] == ["offline"] and p["response_type"] == ["code"]
    assert "client_secret" not in url.url and "code_verifier" not in url.url
    # Le code_verifier n'est jamais stocké : le defi se re-dérive du nonce, aucune colonne ne le contient.
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(COURRIEL_ETATS_OAUTH)).mappings().one()
        assert comptes.lire(cnx, "gmail-paul")["etat"] == "autorisation_en_cours"
    verifier = monde.oauth["gmail"]._verifier_pkce(ligne["nonce"])
    assert (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        == p["code_challenge"][0]
    )
    assert verifier not in json.dumps(dict(ligne), default=str)


def test_portee_envoi_demandee_seulement_pour_l_usage_lecture_envoi(monde):
    qa.creer_compte(monde, usage="lecture_envoi")
    _, p = _demarrer(monde)
    assert sorted(p["scope"][0].split()) == sorted([qa.SCOPE_GMAIL_LECTURE, qa.SCOPE_GMAIL_ENVOI])


def test_consentement_loi_25_requis_avant_toute_autorisation(monde):
    qa.creer_compte(monde, consentement=False)
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.demarrer_autorisation(qa.ADMIN, "gmail-paul")
    assert exc.value.code == "REJ-COURRIEL-CONSENTEMENT-ABSENT"
    assert monde.oauth_google.requetes == []


def test_administration_requise_pour_connecter(monde):
    qa.creer_compte(monde)
    with stockage.transaction() as cnx:
        from opsys import identite

        identite.creer_personne(cnx, "employe", "Employé fictif", "mot-de-passe-employe-1234", ["employee"])
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.demarrer_autorisation("employe", "gmail-paul")
    assert exc.value.code == "REJ-COURRIEL-ADMIN-REQUIS"


# -- le state -------------------------------------------------------------------------------------
def test_state_falsifie_refuse_et_rien_n_est_echange(monde):
    qa.creer_compte(monde)
    url, _ = _demarrer(monde)
    charge, signature = url.state.split(".")
    donnees = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
    donnees["c"] = "autre-compte"
    falsifie = (
        base64.urlsafe_b64encode(json.dumps(donnees, sort_keys=True, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.terminer_autorisation(qa.ADMIN, f"{falsifie}.{signature}", "code")
    assert exc.value.code == "REJ-COURRIEL-OAUTH-ETAT-INVALIDE"
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.terminer_autorisation(qa.ADMIN, "n'importe-quoi", "code")
    assert exc.value.code == "REJ-COURRIEL-OAUTH-ETAT-INVALIDE"
    assert not any(r.url.endswith("/token") for r in monde.oauth_google.requetes)


def test_state_a_usage_unique_meme_si_l_echange_echoue(monde):
    qa.creer_compte(monde)
    url, p = _demarrer(monde)
    with pytest.raises(ErreurCourriel) as exc:  # code inconnu du fournisseur
        monde.service.terminer_autorisation(qa.ADMIN, url.state, "code-invalide")
    assert exc.value.code == "REJ-COURRIEL-OAUTH-ECHANGE-REFUSE"
    monde.oauth_google.autoriser("bon-code", p["code_challenge"][0])
    with pytest.raises(ErreurCourriel) as exc:  # le state est brûlé : rejouer avec un bon code ne passe pas
        monde.service.terminer_autorisation(qa.ADMIN, url.state, "bon-code")
    assert exc.value.code == "REJ-COURRIEL-OAUTH-ETAT-REUTILISE"
    with stockage.transaction() as cnx:
        assert comptes.lire(cnx, "gmail-paul")["etat"] == "erreur"
        assert comptes.lire(cnx, "gmail-paul")["derniere_erreur_code"] == "REJ-COURRIEL-OAUTH-ECHANGE-REFUSE"


def test_state_expire(monde):
    qa.creer_compte(monde)
    url, p = _demarrer(monde)
    monde.oauth_google.autoriser("c", p["code_challenge"][0])
    monde.horloge.t += 601
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.terminer_autorisation(qa.ADMIN, url.state, "c")
    assert exc.value.code == "REJ-COURRIEL-OAUTH-ETAT-EXPIRE"


def test_state_d_un_autre_fournisseur_refuse(monde):
    qa.creer_compte(monde)
    url, _ = _demarrer(monde)
    with pytest.raises(
        ErreurCourriel
    ) as exc:  # le state Gmail présenté au service Graph : signature OK, fournisseur non
        monde.oauth["graph"]._ouvrir_state(url.state)
    assert exc.value.code == "REJ-COURRIEL-OAUTH-ETAT-INVALIDE"


def test_pkce_mauvais_verifier_refuse_par_le_fournisseur(monde):
    qa.creer_compte(monde)
    url, p = _demarrer(monde)
    monde.oauth_google.autoriser("c", "defi-d-un-autre-flux-" + "x" * 22)
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.terminer_autorisation(qa.ADMIN, url.state, "c")
    assert exc.value.code == "REJ-COURRIEL-OAUTH-ECHANGE-REFUSE"


# -- jetons : coffre seulement
# ------------------------------------------------------------------------------------------
def test_connexion_complete_jetons_chiffres_dans_le_coffre_seulement(monde):
    qa.creer_compte(monde)
    vue = qa.connecter_oauth(monde)
    assert vue["etat"] == "connecte" and vue["portees"] == [qa.SCOPE_GMAIL_LECTURE]
    assert vue["secret_nom"] == "courriel.gmail-paul.g1"
    acces = monde.oauth_google.dernier_acces
    refresh = next(iter(monde.oauth_google.refresh_valides))
    # ni la base, ni le journal du compte, ni le journal du coffre ne contiennent les jetons
    octets = b""
    stockage.liberer()
    for chemin in (monde.tmp_path / "opsys-home").rglob("*"):
        if chemin.is_file():
            octets += chemin.read_bytes()
    assert acces.encode() not in octets and refresh.encode() not in octets
    assert base64.b64encode(acces.encode()) not in octets
    with stockage.transaction() as cnx:
        journal = json.dumps(comptes.journal(cnx), default=str) + json.dumps(coffre.journal(cnx), default=str)
        assert acces not in journal and refresh not in journal
        meta = coffre.metadonnees(cnx, "courriel.gmail-paul.g1")
        assert meta["service"] == "google" and meta["valeur"] == "non affichable"
    # le coffre sait les rendre au serveur
    jeu = StockageJetonsCoffre(stockage.transaction, acteur=qa.ADMIN).lire("courriel.gmail-paul.g1")
    assert jeu.access_token == acces and jeu.refresh_token == refresh
    assert acces not in repr(jeu) and refresh not in repr(jeu) and acces not in str(jeu)


def test_portee_excessive_accordee_refus_typé_et_aucun_secret_stocke(tmp_path, monkeypatch):
    monde = qa.preparer(tmp_path, monkeypatch, scope_google=f"{qa.SCOPE_GMAIL_LECTURE} https://mail.google.com/")
    qa.creer_compte(monde)
    with pytest.raises(ErreurCourriel) as exc:
        qa.connecter_oauth(monde)
    assert exc.value.code == "REJ-COURRIEL-PORTEE-EXCESSIVE" and "mail.google.com" in exc.value.detail
    with stockage.transaction() as cnx:
        assert comptes.lire(cnx, "gmail-paul")["etat"] == "erreur"
        assert coffre.lister(cnx) == []  # rien n'est entré dans le coffre


def test_portee_d_envoi_accordee_a_un_compte_en_lecture_est_excessive(tmp_path, monkeypatch):
    monde = qa.preparer(tmp_path, monkeypatch, scope_google=f"{qa.SCOPE_GMAIL_LECTURE} {qa.SCOPE_GMAIL_ENVOI}")
    qa.creer_compte(monde, usage="lecture")
    with pytest.raises(ErreurCourriel) as exc:
        qa.connecter_oauth(monde)
    assert exc.value.code == "REJ-COURRIEL-PORTEE-EXCESSIVE"


def test_portee_de_lecture_decochee_par_l_utilisateur_est_insuffisante(tmp_path, monkeypatch):
    monde = qa.preparer(tmp_path, monkeypatch, scope_google="openid")
    qa.creer_compte(monde)
    with pytest.raises(ErreurCourriel) as exc:
        qa.connecter_oauth(monde)
    assert exc.value.code == "REJ-COURRIEL-PORTEE-EXCESSIVE"  # « openid » n'est pas tolérée chez Google


def test_absence_de_refresh_token_refusee(tmp_path, monkeypatch):
    monde = qa.preparer(tmp_path, monkeypatch)
    monde.oauth_google.avec_refresh = False
    qa.creer_compte(monde)
    with pytest.raises(ErreurCourriel) as exc:
        qa.connecter_oauth(monde)
    assert exc.value.code == "REJ-COURRIEL-REFRESH-ABSENT"


@pytest.mark.parametrize(
    "accordees, usage, code",
    [
        ("Mail.Read offline_access", "lecture", None),
        ("https://graph.microsoft.com/Mail.Read offline_access openid profile", "lecture", None),
        ("mail.read OFFLINE_ACCESS", "lecture", None),  # Graph est insensible à la casse
        ("Mail.Read Mail.ReadWrite offline_access", "lecture", "REJ-COURRIEL-PORTEE-EXCESSIVE"),
        ("Mail.Read Mail.Send", "lecture", "REJ-COURRIEL-PORTEE-EXCESSIVE"),
        ("Mail.Read Files.Read.All", "lecture", "REJ-COURRIEL-PORTEE-EXCESSIVE"),
        ("Mail.Read Mail.Send.Shared", "lecture_envoi", "REJ-COURRIEL-PORTEE-EXCESSIVE"),
        ("Mail.Read", "lecture_envoi", "REJ-COURRIEL-PORTEE-INSUFFISANTE"),
        ("offline_access", "lecture", "REJ-COURRIEL-PORTEE-INSUFFISANTE"),
        ("Mail.Read Mail.Send offline_access", "lecture_envoi", None),
    ],
)
def test_politique_de_portees_graph(accordees, usage, code):
    if code is None:
        PORTEES_GRAPH.verifier(accordees.split(), usage)
    else:
        with pytest.raises(ErreurCourriel) as exc:
            PORTEES_GRAPH.verifier(accordees.split(), usage)
        assert exc.value.code == code


@pytest.mark.parametrize(
    "accordees, code",
    [
        (["https://www.googleapis.com/auth/gmail.readonly"], None),
        (["https://www.googleapis.com/auth/gmail.modify"], "REJ-COURRIEL-PORTEE-EXCESSIVE"),
        (["https://www.googleapis.com/auth/gmail.compose"], "REJ-COURRIEL-PORTEE-EXCESSIVE"),
        (["https://www.googleapis.com/auth/gmail.metadata"], "REJ-COURRIEL-PORTEE-EXCESSIVE"),
        (
            ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/drive"],
            "REJ-COURRIEL-PORTEE-EXCESSIVE",
        ),
        ([], "REJ-COURRIEL-PORTEE-INSUFFISANTE"),
    ],
)
def test_politique_de_portees_gmail(accordees, code):
    if code is None:
        assert PORTEES_GMAIL.verifier(accordees, "lecture")
    else:
        with pytest.raises(ErreurCourriel) as exc:
            PORTEES_GMAIL.verifier(accordees, "lecture")
        assert exc.value.code == code


# -- rafraîchissement, rotation, expiration -------------------------------------------------------
def _fournisseur(monde, compte_id="gmail-paul"):
    return monde.service.fournisseur(compte_id)


def test_rafraichissement_avant_expiration_sans_rotation_conserve_le_refresh(monde):
    qa.creer_compte(monde)
    qa.connecter_oauth(monde)
    premier = monde.oauth_google.dernier_acces
    refresh = next(iter(monde.oauth_google.refresh_valides))
    monde.horloge.t += 3600 - 30  # dans la marge de 60 s avant l'expiration
    _fournisseur(monde).lister_boites()
    assert monde.oauth_google.dernier_acces != premier
    jeu = StockageJetonsCoffre(stockage.transaction, acteur=qa.ADMIN).lire("courriel.gmail-paul.g1")
    assert jeu.access_token == monde.oauth_google.dernier_acces and jeu.refresh_token == refresh  # pas de rotation
    with stockage.transaction() as cnx:
        assert coffre.metadonnees(cnx, "courriel.gmail-paul.g1")["version"] == 2


def test_rotation_du_refresh_token_quand_le_fournisseur_en_renvoie_un(tmp_path, monkeypatch):
    monde = qa.preparer(tmp_path, monkeypatch, rotation_google=True)
    qa.creer_compte(monde)
    qa.connecter_oauth(monde)
    ancien = next(iter(monde.oauth_google.refresh_valides))
    monde.horloge.t += 4000
    _fournisseur(monde).lister_boites()
    nouveau = next(iter(monde.oauth_google.refresh_valides))
    assert nouveau != ancien
    jeu = StockageJetonsCoffre(stockage.transaction, acteur=qa.ADMIN).lire("courriel.gmail-paul.g1")
    assert jeu.refresh_token == nouveau
    # l'ancien refresh token est mort chez le fournisseur : le suivant doit être le nouveau, sinon invalid_grant
    monde.horloge.t += 4000
    _fournisseur(monde).lister_boites()


def test_refresh_revoque_chez_le_fournisseur_reconnexion_requise(monde):
    qa.creer_compte(monde)
    qa.connecter_oauth(monde)
    monde.oauth_google.invalid_grant = True
    monde.horloge.t += 4000
    with pytest.raises(ErreurCourriel) as exc:
        _fournisseur(monde).lister_boites()
    assert exc.value.code == "REJ-COURRIEL-JETON-REVOQUE"
    monde.service.signaler_erreur("gmail-paul", exc.value)
    with stockage.transaction() as cnx:
        vue = comptes.lire(cnx, "gmail-paul")
    assert vue["etat"] == "reconnexion_requise" and vue["derniere_erreur_code"] == "REJ-COURRIEL-JETON-REVOQUE"


def test_portee_reverifiee_a_chaque_rafraichissement(monde):
    qa.creer_compte(monde)
    qa.connecter_oauth(monde)
    monde.oauth_google.scope_accorde = f"{qa.SCOPE_GMAIL_LECTURE} https://mail.google.com/"  # élargie après coup
    monde.horloge.t += 4000
    with pytest.raises(ErreurCourriel) as exc:
        _fournisseur(monde).lister_boites()
    assert exc.value.code == "REJ-COURRIEL-PORTEE-EXCESSIVE"


def test_jeton_expire_sans_moyen_de_rafraichir(monde):
    qa.creer_compte(monde, "imap-x", "imap", configuration={"hote": "imap.example.test"})  # sans OAuth
    from opsys.courriel_connecteurs.client_oauth import GestionnaireJetons

    stock = dbl.StockageJetonsMemoire()
    stock.ecrire("n", JeuJetons("acces", None, int(monde.horloge.t) - 1, frozenset()), service="google")
    g = GestionnaireJetons("n", stock, None, usage="lecture", service="google", horloge=monde.horloge)
    with pytest.raises(ErreurCourriel) as exc:
        g.jeton_acces()
    assert exc.value.code == "REJ-COURRIEL-JETON-EXPIRE"


# -- révocation -----------------------------------------------------------------------------------
def test_revocation_chez_google_et_destruction_du_secret(monde):
    qa.creer_compte(monde)
    qa.connecter_oauth(monde)
    refresh = next(iter(monde.oauth_google.refresh_valides))
    vue = monde.service.revoquer(qa.ADMIN, "gmail-paul")
    assert vue["etat"] == "revoque"
    assert monde.oauth_google.revoques == [refresh]
    with stockage.transaction() as cnx:
        assert coffre.metadonnees(cnx, "courriel.gmail-paul.g1")["etat"] == "revoque"
        assert (
            cnx.execute(text("SELECT count(*) FROM coffre_versions WHERE valeur_chiffree IS NOT NULL")).scalar_one()
            == 0
        )
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.fournisseur("gmail-paul")
    assert exc.value.code == "REJ-COURRIEL-COMPTE-INACTIF"
    with pytest.raises(ErreurCourriel):  # un compte révoqué ne se reconnecte pas
        monde.service.demarrer_autorisation(qa.ADMIN, "gmail-paul")


def test_revocation_graph_sans_point_de_revocation_detruit_quand_meme_le_secret(monde):
    qa.creer_compte(monde, "graph-paul", "graph")
    qa.connecter_oauth(monde, "graph-paul")
    vue = monde.service.revoquer(qa.ADMIN, "graph-paul")
    assert vue["etat"] == "revoque"
    with stockage.transaction() as cnx:
        assert coffre.metadonnees(cnx, "courriel.graph-paul.g1")["etat"] == "revoque"
        journal = comptes.journal(cnx, "graph-paul")
    assert any(j["evenement"] == "compte.revocation" and '"statut": "local"' in j["details"] for j in journal)


def test_secret_client_oauth_jamais_dans_l_url_ni_les_erreurs(tmp_path, monkeypatch):
    monde = qa.preparer(tmp_path, monkeypatch)
    from contextlib import contextmanager

    from opsys.courriel_connecteurs.oauth import ServiceOAuth

    monde.oauth_google.secret_client = "secret-client-fictif-ABCDEF"

    @contextmanager
    def secret():
        yield "mauvais-secret-client-fictif"

    monde.service._oauth["gmail"] = ServiceOAuth(
        config_gmail(client_id="c", redirect_uri="https://opsys.example.test/cb"),
        monde.transport,
        lambda: qa.CLE_SIGNATURE,
        horloge=monde.horloge,
        secret_client=secret,
    )
    qa.creer_compte(monde)
    with pytest.raises(ErreurCourriel) as exc:
        qa.connecter_oauth(monde)
    assert "mauvais-secret" not in str(exc.value) and "secret-client-fictif" not in str(exc.value)


def test_state_lie_au_compte_en_base_meme_si_la_signature_est_valide(monde):
    qa.creer_compte(monde)
    url, p = _demarrer(monde)
    monde.oauth_google.autoriser("c", p["code_challenge"][0])
    with stockage.transaction() as cnx:  # altération de la ligne : le nonce appartiendrait à un autre compte
        cnx.execute(COURRIEL_ETATS_OAUTH.update().values(compte_id="autre-compte"))
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.terminer_autorisation(qa.ADMIN, url.state, "c")
    assert exc.value.code == "REJ-COURRIEL-OAUTH-ETAT-REUTILISE"


def test_aucun_jeton_dans_les_journaux_applicatifs_pendant_un_parcours_complet(monde, caplog):
    import logging

    from opsys.courriel_connecteurs.ingestion import IngestionCourriel
    masquage.installer()
    qa.creer_compte(monde)
    with caplog.at_level(logging.DEBUG):
        qa.connecter_oauth(monde)
        monde.gmail.ajouter(dbl.courriel_brut())
        monde.horloge.t += 4000
        IngestionCourriel(stockage.transaction, acteur="nathan").synchroniser(
            "gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
        monde.service.revoquer(qa.ADMIN, "gmail-paul")
    for secret in (monde.oauth_google.dernier_acces, *monde.oauth_google.refresh_valides, *monde.oauth_google.revoques):
        assert secret not in caplog.text
    assert "refresh-fictif" not in caplog.text and "acces-fictif" not in caplog.text
