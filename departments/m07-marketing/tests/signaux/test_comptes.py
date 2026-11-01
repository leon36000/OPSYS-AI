"""Le registre des sources déclarées : jamais un secret, une adresse sûre, un compte ne se modifie pas."""

from __future__ import annotations

import pytest
from m7_marketing import journal_chaine
from m7_marketing.signaux import comptes, modele

RESSOURCES = {
    "search_console": "https://www.horizon.example/",
    "pagespeed": "https://www.horizon.example/",
    "crux": "https://www.horizon.example",
    "bing_webmaster": "https://www.horizon.example/",
    "umami": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    "matomo": "7",
    "gbp_avis": "accounts/123/locations/456",
    "gbp_insights": "locations/456",
    "google_ads": "1234567890",
    "meta_ads": "act_123456789",
}
BASE = "https://analytique.horizon.example"
SECRET = {"nom": "secret.principal"}
ANNEXES_ADS = {"jeton_developpeur": {"nom": "secret.developpeur"}}


def reg(journal, source, ressource=None, **kw):
    args = {
        "compte_ref": "principal",
        "secret_ref": SECRET,
        "secrets_annexes": None,
        "base_url": None,
        "options": None,
        "fictif": True,
        "par": "nathan",
        "horodatage": "2026-11-01T12:00:00Z",
    }
    if source == "google_ads":
        args["secrets_annexes"] = ANNEXES_ADS
    if modele.SOURCES[source].auto_heberge:
        args["base_url"] = BASE
    args.update(kw)
    return comptes.enregistrer(
        journal,
        source,
        args.pop("compte_ref"),
        ressource or RESSOURCES[source],
        args.pop("secret_ref"),
        args.pop("secrets_annexes"),
        args.pop("base_url"),
        args.pop("options"),
        args.pop("fictif"),
        args.pop("par"),
        args.pop("horodatage"),
    )


def code(res):
    assert res["accepte"] is False
    return res["refus"][0]["code"]


@pytest.mark.parametrize("source", sorted(RESSOURCES))
def test_chaque_source_de_lecture_se_declare_avec_sa_ressource(source):
    journal: list = []
    assert reg(journal, source)["accepte"] is True
    c = comptes.actifs(journal)[(source, "principal")]
    assert c.ressource == RESSOURCES[source] and c.secret_nom == "secret.principal" and c.fictif is True
    assert (c.base_url is not None) == modele.SOURCES[source].auto_heberge


def test_une_source_d_import_seulement_n_a_pas_de_compte():
    for source in ("search_console_ia", "bing_ai_performance", "journaux_serveur", "inconnue"):
        res = comptes.enregistrer(
            [], source, "principal", "x", SECRET, None, None, None, True, "n", "2026-11-01T12:00:00Z"
        )
        assert code(res) == "REJ-SIGNAUX-SOURCE-INCONNUE"


@pytest.mark.parametrize(
    "source,mauvaise",
    [
        ("search_console", "http://www.horizon.example/"),
        ("search_console", "www.horizon.example"),
        ("search_console", "sc-domain:"),
        ("search_console", "https://x.example/ and 1=1"),
        ("umami", "pas-un-uuid"),
        ("matomo", "0"),
        ("matomo", "7; DROP"),
        ("gbp_avis", "locations/456"),
        ("gbp_insights", "accounts/1/locations/2"),
        ("google_ads", "123-456-7890"),
        ("google_ads", "12345"),
        ("meta_ads", "123456789"),
        ("crux", "https://x.example/chemin"),
    ],
)
def test_une_ressource_mal_formee_est_refusee(source, mauvaise):
    assert code(reg([], source, mauvaise)) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"


def test_search_console_accepte_une_propriete_de_domaine():
    assert reg([], "search_console", "sc-domain:horizon.example")["accepte"]


@pytest.mark.parametrize(
    "secret",
    [
        None,
        {},
        {"nom": ""},
        {"nom": "AB"},
        {"nom": "Secret.Majuscule"},
        {"nom": 5},
        {"nom": "ok.nom", "valeur": "jeton-brut"},
        "jeton-brut-en-texte",
        {"valeur": "jeton-brut"},
    ],
)
def test_un_secret_se_declare_par_son_nom_seulement(secret):
    assert code(reg([], "search_console", secret_ref=secret)) == "REJ-SIGNAUX-SECRET-REF"


def test_les_secrets_annexes_sont_exactement_ceux_de_la_source():
    assert code(reg([], "google_ads", secrets_annexes=None)) == "REJ-SIGNAUX-SECRET-REF"
    assert code(reg([], "google_ads", secrets_annexes={"autre": {"nom": "secret.x"}})) == "REJ-SIGNAUX-SECRET-REF"
    assert (
        code(
            reg(
                [],
                "google_ads",
                secrets_annexes={"jeton_developpeur": {"nom": "secret.developpeur"}, "plus": {"nom": "secret.plus"}},
            )
        )
        == "REJ-SIGNAUX-SECRET-REF"
    )
    assert code(reg([], "google_ads", secrets_annexes={"jeton_developpeur": "brut"})) == "REJ-SIGNAUX-SECRET-REF"
    assert code(reg([], "search_console", secrets_annexes=ANNEXES_ADS)) == "REJ-SIGNAUX-SECRET-REF"


@pytest.mark.parametrize(
    "url",
    [
        "http://analytique.horizon.example",
        "https://127.0.0.1",
        "https://10.0.0.5",
        "https://2130706433",
        "https://localhost",
        "https://[::1]/",
        "https://usager:motdepasse@analytique.horizon.example",
        "https://analytique.horizon.example:8443",
        "https://analytique.horizon.example/?token=abc",
        "https://analytique.horizon.example/#frag",
        "https://serveur.internal",
        "https://nas.local",
        "https://analytique",
        "https://analytique.horizon.example/a/b/c/d",
        "ftp://analytique.horizon.example",
        "https://analytique.horizon.example/%2e%2e/admin",
        "https://analytique.horizon.example/ça",
        "",
        None,
        5,
        "x" * 300,
        "https://169.254.169.254",
        "https://ex ample.test",
    ],
)
def test_une_adresse_auto_hebergee_dangereuse_est_refusee(url):
    assert code(reg([], "umami", base_url=url)) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"


def test_une_adresse_valide_est_canonique_et_le_port_443_est_permis():
    assert comptes.url_base_valide("https://analytique.horizon.example/") == "https://analytique.horizon.example"
    assert (
        comptes.url_base_valide("https://analytique.horizon.example:443/stats/")
        == "https://analytique.horizon.example/stats"
    )


def test_une_source_chez_un_fournisseur_fixe_n_a_pas_d_adresse_de_base():
    assert code(reg([], "search_console", base_url="https://evil.example")) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"


def test_les_options_sont_fermees_par_source():
    assert reg([], "gbp_avis", options={"extraits_avis": True})["accepte"]
    assert code(reg([], "gbp_avis", options={"extraits_avis": "oui"})) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"
    assert code(reg([], "gbp_avis", options={"autre": True})) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"
    assert code(reg([], "search_console", options={"extraits_avis": True})) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"
    j: list = []
    reg(j, "gbp_avis", options={"extraits_avis": True})
    assert comptes.actifs(j)[("gbp_avis", "principal")].option("extraits_avis") is True


@pytest.mark.parametrize("ref", ["A", "x", "Compte Principal", "../x", "", None, 3, "a" * 65])
def test_l_etiquette_du_compte_est_stricte(ref):
    assert code(reg([], "search_console", compte_ref=ref)) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"


def test_fictif_doit_etre_un_booleen():
    for mauvais in ("true", 1, None):
        assert code(reg([], "search_console", fictif=mauvais)) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"


def test_redeclarer_a_l_identique_est_un_no_op_et_modifier_est_refuse():
    j: list = []
    reg(j, "search_console")
    n = len(j)
    assert reg(j, "search_console")["deja_enregistre"] is True and len(j) == n
    assert code(reg(j, "search_console", secret_ref={"nom": "secret.autre"})) == "REJ-SIGNAUX-COMPTE-EXISTANT"
    assert code(reg(j, "search_console", fictif=False)) == "REJ-SIGNAUX-COMPTE-EXISTANT"
    assert len(j) == n


def test_desactiver_est_idempotent_et_definitif():
    j: list = []
    reg(j, "search_console")
    assert comptes.desactiver(j, "search_console", "principal", "nathan", "plus utile", "2026-11-02T00:00:00Z") == {
        "accepte": True,
        "source": "search_console",
        "compte_ref": "principal",
        "deja_desactive": False,
    }
    assert comptes.desactiver(j, "search_console", "principal", "nathan", "encore", "2026-11-02T00:00:01Z")[
        "deja_desactive"
    ]
    assert comptes.actifs(j) == {} and comptes.plier(j)[("search_console", "principal")].actif is False
    assert code(reg(j, "search_console")) == "REJ-SIGNAUX-COMPTE-DESACTIVE"
    assert (
        code(comptes.desactiver(j, "search_console", "inconnu", "n", "m", "2026-11-02T00:00:00Z"))
        == "REJ-SIGNAUX-COMPTE-INCONNU"
    )


def test_aucun_secret_n_entre_au_journal_et_la_chaine_tient():
    j: list = []
    reg(j, "google_ads")
    texte = repr(list(j))
    assert "jeton-brut" not in texte and "secret.principal" in texte  # le NOM, jamais une valeur
    assert journal_chaine.integre(j)


def test_une_chaine_alteree_refuse_toute_ecriture():
    j: list = []
    reg(j, "search_console")
    j[0] = {**j[0], "ressource": "https://pirate.example/"}
    assert code(reg(j, "pagespeed")) == "REJ-SIGNAUX-JOURNAL-ALTERE"
    assert (
        code(comptes.desactiver(j, "search_console", "principal", "n", "m", "2026-11-02T00:00:00Z"))
        == "REJ-SIGNAUX-JOURNAL-ALTERE"
    )
