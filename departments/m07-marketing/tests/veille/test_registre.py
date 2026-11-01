"""Le registre des concurrents déclarés : liste blanche de sources publiques, plateformes interdites, SSRF, données
personnelles."""

from __future__ import annotations

import pytest
from fabriques_veille import ACCUEIL, AUTRE_HOTE, COMMUNIQUE, DOMAINE, HOTE, PLAN, SERVICES, declarer_horizon
from m7_marketing import journal_chaine
from m7_marketing.veille import registre

H = "2026-10-01T00:00:00Z"


def _declarer(journal, **modif):
    base = {"concurrent_id": "horizon", "nom_affiche": "Revêtements Horizon", "domaine": DOMAINE,
            "sources": [{"url": ACCUEIL, "nature": "site_officiel"}], "hotes_additionnels": None}
    base.update(modif)
    return registre.declarer(journal, base["concurrent_id"], base["nom_affiche"], base["domaine"], base["sources"],
                             base["hotes_additionnels"], "nathan", H)


def _code(resultat):
    assert resultat["accepte"] is False, resultat
    return resultat["refus"][0]["code"]


def test_declaration_valide_inscrite_a_la_chaine_de_hachage():
    journal = []
    ack = _declarer(journal, sources=[{"url": ACCUEIL, "nature": "site_officiel"},
                                      {"url": PLAN, "nature": "plan_de_site"}])
    assert ack == {"accepte": True, "concurrent_id": "horizon", "deja_declare": False}
    assert journal_chaine.verifier(journal) == []
    m = journal[0]
    assert m["type"] == "concurrent_declare" and m["par"] == "nathan" and m["domaine"] == DOMAINE
    assert [s["url"] for s in m["sources"]] == [ACCUEIL, PLAN]
    c = registre.actifs(journal)["horizon"]
    assert c.actif and c.possede_hote(HOTE) and c.possede_hote(DOMAINE)
    assert not c.possede_hote("horizon.example.evil.test")


def test_declaration_idempotente_et_modification_refusee():
    journal = []
    _declarer(journal)
    assert _declarer(journal)["deja_declare"] is True and len(journal) == 1
    assert _code(_declarer(journal, nom_affiche="Autre Nom")) == "REJ-VEILLE-CONCURRENT-EXISTANT"
    assert _code(_declarer(journal, sources=[{"url": SERVICES, "nature": "site_officiel"}])) == \
        "REJ-VEILLE-CONCURRENT-EXISTANT"
    assert len(journal) == 1


def test_retrait_idempotent_et_identifiant_non_reutilisable():
    journal = []
    _declarer(journal)
    assert registre.retirer(journal, "horizon", "gestion", "plus pertinent", H)["deja_retire"] is False
    assert registre.retirer(journal, "horizon", "gestion", "encore", H)["deja_retire"] is True
    assert registre.actifs(journal) == {}
    assert _code(_declarer(journal)) == "REJ-VEILLE-CONCURRENT-RETIRE"
    assert _code(registre.retirer(journal, "inconnu", "gestion", "x", H)) == "REJ-VEILLE-CONCURRENT-INCONNU"
    assert [m["type"] for m in journal] == ["concurrent_declare", "concurrent_retire"]


def test_au_plus_dix_concurrents_actifs():
    journal = []
    for i in range(10):
        assert _declarer(journal, concurrent_id=f"conc-{i:02d}", nom_affiche=f"Entreprise {i}",
                         domaine=f"entreprise{i}.example",
                         sources=[{"url": f"https://www.entreprise{i}.example/", "nature": "site_officiel"}])["accepte"]
    assert _code(_declarer(journal, concurrent_id="conc-10", nom_affiche="Onzième", domaine="onzieme.example",
                           sources=[{"url": "https://onzieme.example/", "nature": "site_officiel"}])) == \
        "REJ-VEILLE-LIMITE-CONCURRENTS"
    registre.retirer(journal, "conc-00", "gestion", "place", H)
    assert _declarer(journal, concurrent_id="conc-10", nom_affiche="Onzième", domaine="onzieme.example",
                     sources=[{"url": "https://onzieme.example/", "nature": "site_officiel"}])["accepte"]


@pytest.mark.parametrize("plateforme", registre.PLATEFORMES_INTERDITES)
def test_chaque_plateforme_interdite_est_refusee_comme_domaine_comme_source_et_comme_hote(plateforme):
    journal = []
    assert _code(_declarer(journal, domaine=plateforme, sources=[
        {"url": f"https://{plateforme}/page", "nature": "site_officiel"}])) == "REJ-VEILLE-PLATEFORME-INTERDITE"
    # source sur la plateforme, même si l'hôte est déclaré additionnel
    assert _code(_declarer(journal, hotes_additionnels=[plateforme], sources=[
        {"url": f"https://{plateforme}/page", "nature": "site_officiel"}])) == "REJ-VEILLE-PLATEFORME-INTERDITE"
    assert _code(_declarer(journal, sources=[
        {"url": f"https://www.{plateforme}/horizon", "nature": "site_officiel"}])) == "REJ-VEILLE-PLATEFORME-INTERDITE"
    assert _code(_declarer(journal, sources=[
        {"url": f"https://fr-ca.m.{plateforme}/horizon",
            "nature": "site_officiel"}])) == "REJ-VEILLE-PLATEFORME-INTERDITE"
    assert journal == []


@pytest.mark.parametrize(
    "url",
    [
        "HTTPS://WWW.FACEBOOK.COM/horizon",
        "https://www.Facebook.com/horizon",
        "https://www.facebook.com:443/horizon",
        "https://www.facebook.com./horizon",
        "https://www.instagram.com/horizon/?hl=fr",
    ],
)
def test_variantes_de_casse_de_port_et_de_point_final_des_plateformes_sont_aussi_refusees(url):
    resultat = _declarer([], sources=[{"url": url, "nature": "site_officiel"}])
    assert _code(resultat) in {"REJ-VEILLE-PLATEFORME-INTERDITE", "REJ-VEILLE-URL-INVALIDE"}


def test_un_domaine_qui_ressemble_a_une_plateforme_mais_n_en_est_pas_une_n_est_pas_bloque():
    # « notfacebook.com » n'est pas un sous-domaine de facebook.com
    assert registre.plateforme_interdite("notfacebook.com") is None
    assert registre.plateforme_interdite("facebook.com.horizon.example") is None
    assert registre.plateforme_interdite("api.facebook.com") == "facebook.com"
    assert registre.plateforme_interdite("t.me") == "t.me"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/",
        "https://[2001:db8::1]/",
        "https://localhost/",
        "https://10.0.0.1/",
        "https://192.168.1.10/admin",
        "https://2130706433/",  # 127.0.0.1 en décimal
        "https://0x7f000001/",  # 127.0.0.1 en hexadécimal
        "https://0x7f.0.0.1/",
        "https://0177.0.0.1/",  # octal
        "https://service.internal/",
        "https://imprimante.local/",
        "https://monsite.localhost/",
        "https://abcdef.onion/",
        "https://serveur.lan/",
        "https://horizon/",  # une seule étiquette
    ],
)
def test_hotes_internes_ip_et_encodages_d_adresse_refuses_comme_sources(url):
    resultat = _declarer([], sources=[{"url": url, "nature": "site_officiel"}])
    assert _code(resultat) in {"REJ-VEILLE-URL-INVALIDE", "REJ-VEILLE-HOTE-NON-DECLARE"}


@pytest.mark.parametrize("domaine", ["127.0.0.1", "localhost", "[::1]", "10.0.0.1", "169.254.169.254", "a.internal",
                                     "a.local", "x.onion", "horizon.example:8443", "horizon.example/chemin",
                                     "user@horizon.example", "", " ", "horizon", "xn--.example", "-a.example",
                                     "horizon..example", "é.example", 42, None])
def test_domaine_non_public_refuse(domaine):
    assert _code(_declarer([], domaine=domaine)) == "REJ-VEILLE-DOMAINE-INVALIDE"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://www.horizon.example/", "REJ-VEILLE-URL-INVALIDE"),
        ("ftp://www.horizon.example/", "REJ-VEILLE-URL-INVALIDE"),
        ("//www.horizon.example/", "REJ-VEILLE-URL-INVALIDE"),
        ("https://usager:secret@www.horizon.example/", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://usager@www.horizon.example/", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example@evil.example/", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example:8443/", "REJ-VEILLE-URL-INVALIDE"),
        ("https://www.horizon.example/page#ancre", "REJ-VEILLE-URL-INVALIDE"),
        ("https://www.horizon.example/a b", "REJ-VEILLE-URL-INVALIDE"),
        ("https://www.horizon.example\\@evil.example/", "REJ-VEILLE-URL-INVALIDE"),
        ("https://www.horizon.example/\x00", "REJ-VEILLE-URL-INVALIDE"),
        ("https://www.horizon.example/" + "a" * 400, "REJ-VEILLE-URL-INVALIDE"),
        ("https://www.horizon.example/?token=abc123", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/?API_KEY=abc", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/?apikey=abc", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/?access_token=abc", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/?sessionid=abc", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/?Password=abc", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/?sig=abc", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/?page=2&auth=1", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/login", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://www.horizon.example/wp-admin/", "REJ-VEILLE-AUTHENTIFICATION-INTERDITE"),
        ("https://autre-entreprise.example/", "REJ-VEILLE-HOTE-NON-DECLARE"),
        ("https://horizon.example.evil.example/", "REJ-VEILLE-HOTE-NON-DECLARE"),
        ("https://evilhorizon.example/", "REJ-VEILLE-HOTE-NON-DECLARE"),
    ],
)
def test_sources_refusees_avec_le_bon_code(url, code):
    journal = []
    assert _code(_declarer(journal, sources=[{"url": url, "nature": "site_officiel"}])) == code
    assert journal == []


def test_une_source_avec_parametre_benin_est_permise_mais_pas_avec_un_nom_d_authentification():
    assert _declarer([], sources=[{"url": f"https://{HOTE}/blogue?page=2&langue=fr",
        "nature": "site_officiel"}])["accepte"]


def test_hote_additionnel_explicite_requis_pour_un_autre_domaine():
    journal = []
    sources = [{"url": ACCUEIL, "nature": "site_officiel"}, {"url": COMMUNIQUE, "nature": "communique"}]
    assert _code(_declarer(journal, sources=sources)) == "REJ-VEILLE-HOTE-NON-DECLARE"
    ack = _declarer(journal, sources=sources, hotes_additionnels=[AUTRE_HOTE])
    assert ack["accepte"]
    c = registre.actifs(journal)["horizon"]
    assert c.hotes_additionnels == (AUTRE_HOTE,) and c.possede_hote(AUTRE_HOTE)
    # l'hôte additionnel est lui-même contrôlé
    for mauvais in ("127.0.0.1", "facebook.com", "a.internal", 5):
        assert _code(_declarer([], hotes_additionnels=[mauvais])) in {"REJ-VEILLE-DOMAINE-INVALIDE",
                                                                      "REJ-VEILLE-PLATEFORME-INTERDITE"}
    assert _code(_declarer([], hotes_additionnels=["a.example", "b.example", "c.example", "d.example"])) == \
        "REJ-VEILLE-ARGUMENT-INVALIDE"


def test_nombre_et_forme_des_sources():
    assert _code(_declarer([], sources=[])) == "REJ-VEILLE-ARGUMENT-INVALIDE"
    six = [{"url": f"https://{HOTE}/p{i}", "nature": "site_officiel"} for i in range(6)]
    assert _code(_declarer([], sources=six)) == "REJ-VEILLE-ARGUMENT-INVALIDE"
    assert _code(_declarer([], sources=[{"url": ACCUEIL, "nature": "reseau_social"}])) == "REJ-VEILLE-ARGUMENT-INVALIDE"
    assert _code(_declarer([], sources=[{"url": ACCUEIL}])) == "REJ-VEILLE-ARGUMENT-INVALIDE"
    assert _code(_declarer([], sources=[{"url": ACCUEIL, "nature": "site_officiel", "cookie": "x"}])) == \
        "REJ-VEILLE-ARGUMENT-INVALIDE"
    assert _code(_declarer([], sources=[{"url": ACCUEIL,
        "nature": "site_officiel"}] * 2)) == "REJ-VEILLE-ARGUMENT-INVALIDE"
    assert _code(_declarer([], sources="https://x.example")) == "REJ-VEILLE-ARGUMENT-INVALIDE"


@pytest.mark.parametrize("nom", ["jean.tremblay@example.test", "Entreprise 514-555-0123", "Maison 450 555 0199",
                                 "Mme Tremblay", "M. Gagnon", "Dr Lavoie", "Entreprise NAS 046 454 286"])
def test_un_nom_qui_ressemble_a_une_personne_ou_porte_une_coordonnee_est_refuse(nom):
    assert _code(_declarer([], nom_affiche=nom)) == "REJ-VEILLE-DONNEE-PERSONNELLE"


@pytest.mark.parametrize("nom", ["", "A", "x" * 81, "Nom\x00caché", "Nom‮trompeur", 12, None])
def test_nom_d_affichage_invalide(nom):
    assert _code(_declarer([], nom_affiche=nom)) in {"REJ-VEILLE-ARGUMENT-INVALIDE", "REJ-VEILLE-DONNEE-PERSONNELLE"}


@pytest.mark.parametrize("ident", ["", "A", "Majuscule", "avec espace", "a" * 41, "-tiret", "é", None, 3])
def test_identifiant_de_concurrent_invalide(ident):
    assert _code(_declarer([], concurrent_id=ident)) == "REJ-VEILLE-CONCURRENT-INVALIDE"


def test_un_journal_altere_bloque_toute_ecriture():
    journal = []
    _declarer(journal)
    journal[0] = {**journal[0], "nom_affiche": "Falsifié"}
    assert _code(_declarer(journal, concurrent_id="autre")) == "REJ-VEILLE-JOURNAL-ALTERE"
    assert _code(registre.retirer(journal, "horizon", "g", "x", H)) == "REJ-VEILLE-JOURNAL-ALTERE"


def test_sources_actives_ne_liste_que_les_concurrents_actifs():
    journal = []
    declarer_horizon(journal)
    assert set(registre.sources_actives(registre.plier(journal))) == {ACCUEIL, SERVICES, PLAN}
    registre.retirer(journal, "horizon", "g", "x", H)
    assert registre.sources_actives(registre.plier(journal)) == {}


def test_erreur_veille_masque_les_secrets_et_refuse_un_code_hors_catalogue():
    from opsys.secrets_coffre import masquage

    masquage.enregistrer("secret-vivant-123456")
    try:
        e = registre.ErreurVeille("REJ-VEILLE-RESEAU", "échec avec secret-vivant-123456 dedans")
    finally:
        masquage.oublier("secret-vivant-123456")
    assert "secret-vivant" not in str(e) and "•••" in e.detail
    with pytest.raises(ValueError, match="hors catalogue"):
        registre.ErreurVeille("REJ-VEILLE-INVENTE")


def test_url_sans_parametres():
    assert registre.url_sans_parametres(f"https://{HOTE}/a/b?x=1&y=2") == f"https://{HOTE}/a/b"
    assert registre.url_sans_parametres(f"https://{HOTE}") == f"https://{HOTE}/"
