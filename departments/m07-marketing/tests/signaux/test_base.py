"""La base commune des connecteurs : un seul chemin d'appel, les mêmes garde-fous pour tous."""

from __future__ import annotations

import contextlib
from datetime import date

import pytest
from fabriques_signaux import JETON, Horloge, coffre_pour, compte, masqueur
from m7_marketing.signaux import base, modele
from m7_marketing.signaux.erreurs import ErreurSignaux
from m7_marketing.signaux.quotas import Quota
from m7_marketing.signaux.transport import (
    Authentification,
    ErreurTransport,
    ReponseHttp,
    RequeteHttp,
    TransportNonBranche,
)

URL = "https://searchconsole.googleapis.com/webmasters/v3/x"


class Transport:
    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.requetes: list[RequeteHttp] = []

    def envoyer(self, requete, *, delai_s=30.0):
        self.requetes.append(requete)
        r = self.reponses.pop(0) if self.reponses else ReponseHttp(200, {"ok": True})
        if isinstance(r, Exception):
            raise r
        return r


class Mini(base.ConnecteurLecture):
    SOURCE = modele.SEARCH_CONSOLE
    FOURNISSEUR = "test"
    VERSION_API = "t/1"
    LIMITES = Quota(par_minute=100, par_jour=1000, source="test")
    POINTS_ACCES = frozenset({"lecture"})
    HOTES = frozenset({"searchconsole.googleapis.com"})

    def lire_page(self, flux, fenetre, curseur):
        raise AssertionError("non utilisé")


def fabrique(*reponses, coffre=None, **kw):
    t = Transport(*reponses)
    coffre = coffre or coffre_pour("search_console")
    con = Mini(
        t,
        compte("search_console", "https://www.horizon.example/"),
        coffre.fournisseurs(),
        maintenant=kw.pop("maintenant", Horloge()),
        masqueur=masqueur(),
        **kw,
    )
    return con, t, coffre


def appel(con, **kw):
    return con._appeler(kw.pop("point", "lecture"), kw.pop("methode", "POST"), kw.pop("url", URL), **kw)


def erreur(con, **kw):
    with pytest.raises(ErreurSignaux) as exc:
        appel(con, **kw)
    return exc.value


@pytest.mark.parametrize(
    "reponse,code,reprenable,attente",
    [
        (ReponseHttp(401, {}), "REJ-SIGNAUX-AUTH-REFUSEE", False, None),
        (
            ReponseHttp(403, {"error": {"errors": [{"reason": "forbidden"}]}}),
            "REJ-SIGNAUX-PERMISSION-REFUSEE",
            False,
            None,
        ),
        (
            ReponseHttp(403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}),
            "REJ-SIGNAUX-LIMITE-DEBIT",
            True,
            60,
        ),
        (ReponseHttp(403, {"error": {"status": "RESOURCE_EXHAUSTED"}}), "REJ-SIGNAUX-LIMITE-DEBIT", True, 60),
        (ReponseHttp(403, "texte"), "REJ-SIGNAUX-PERMISSION-REFUSEE", False, None),
        (ReponseHttp(429, {}, {"Retry-After": "17"}), "REJ-SIGNAUX-LIMITE-DEBIT", True, 17),
        (ReponseHttp(429, {}, {"retry-after": "0"}), "REJ-SIGNAUX-LIMITE-DEBIT", True, 1),
        (ReponseHttp(429, {}, {"RETRY-AFTER": "999999"}), "REJ-SIGNAUX-LIMITE-DEBIT", True, 86400),
        (ReponseHttp(429, {}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), "REJ-SIGNAUX-LIMITE-DEBIT", True, 60),
        (ReponseHttp(408, {}), "REJ-SIGNAUX-RESEAU", True, None),
        (ReponseHttp(400, {"error": "x"}), "REJ-SIGNAUX-REQUETE-INVALIDE", False, None),
        (ReponseHttp(404, {}), "REJ-SIGNAUX-INTROUVABLE", False, None),
        (ReponseHttp(500, {}), "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE", True, None),
        (ReponseHttp(503, {}, {"Retry-After": "5"}), "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE", True, 5),
        (ReponseHttp(418, {}), "REJ-SIGNAUX-REPONSE-INVALIDE", False, None),
        (ReponseHttp(302, {}), "REJ-SIGNAUX-REPONSE-INVALIDE", False, None),
        (ReponseHttp(200, "pas un objet"), "REJ-SIGNAUX-REPONSE-INVALIDE", False, None),
        (ReponseHttp(200, None), "REJ-SIGNAUX-REPONSE-INVALIDE", False, None),
        (ReponseHttp(200, {"rows": ["x" * 1024] * 6000}), "REJ-SIGNAUX-REPONSE-TROP-GROSSE", False, None),
    ],
)
def test_chaque_statut_a_son_refus_typé(reponse, code, reprenable, attente):
    con, _, _ = fabrique(reponse)
    e = erreur(con)
    assert (e.code, e.reprenable, e.reessayer_apres_s) == (code, reprenable, attente)


def test_une_reponse_de_transport_illisible_est_refusee():
    con, _, _ = fabrique("pas une ReponseHttp")
    assert erreur(con).code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_le_corps_de_la_reponse_n_est_jamais_recopie_dans_l_erreur():
    secret_du_serveur = "SECRET-DU-SERVEUR-9981"
    con, _, _ = fabrique(ReponseHttp(500, {"error": {"message": secret_du_serveur}}))
    e = erreur(con)
    assert secret_du_serveur not in str(e) and secret_du_serveur not in repr(e.publique())


def test_un_succes_rend_le_corps_et_une_empreinte_independante_de_l_ordre_des_cles():
    con, _, _ = fabrique(ReponseHttp(200, {"a": 1, "b": [1, 2]}), ReponseHttp(200, {"b": [1, 2], "a": 1}))
    c1, e1 = appel(con)
    c2, e2 = appel(con)
    assert c1 == {"a": 1, "b": [1, 2]} and e1 == e2 and len(e1) == 64
    assert base.empreinte_reponse({"a": 1}) != base.empreinte_reponse({"a": 2})


@pytest.mark.parametrize(
    "url",
    [
        "http://searchconsole.googleapis.com/x",
        "https://autre.example/x",
        "https://searchconsole.googleapis.com.evil.test/x",
        "https://usager:mdp@searchconsole.googleapis.com/x",
        "https://searchconsole.googleapis.com:8443/x",
        "https://searchconsole.googleapis.com/x#frag",
        "ftp://searchconsole.googleapis.com/x",
        "//searchconsole.googleapis.com/x",
        "https://searchconsole.googleapis.com:99999999/x",
    ],
)
def test_une_url_hors_des_hotes_declares_n_atteint_jamais_le_transport(url):
    con, transport, coffre = fabrique()
    assert erreur(con, url=url).code == "REJ-SIGNAUX-HOTE-NON-PERMIS"
    assert transport.requetes == [] and sum(coffre.ouvertures.values()) == 0


def test_le_port_443_explicite_est_permis():
    con, transport, _ = fabrique()
    appel(con, url="https://searchconsole.googleapis.com:443/x")
    assert len(transport.requetes) == 1


@pytest.mark.parametrize("point", ["mutate", "sites.delete", "", "LECTURE", "lecture "])
def test_un_point_d_acces_hors_liste_blanche_est_une_ecriture_interdite(point):
    con, transport, coffre = fabrique()
    assert erreur(con, point=point).code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    assert transport.requetes == [] and sum(coffre.ouvertures.values()) == 0


@pytest.mark.parametrize("methode", ["PUT", "DELETE", "PATCH", "get", "post", "HEAD"])
def test_une_methode_d_ecriture_ne_se_construit_meme_pas(methode):
    with pytest.raises(ErreurSignaux) as exc:
        RequeteHttp(methode, URL)
    assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"


def test_la_requete_ne_porte_le_secret_ni_dans_l_url_ni_dans_son_repr():
    con, transport, _ = fabrique()
    appel(con, params={"a": "1"}, corps={"b": 2})
    requete = transport.requetes[0]
    assert JETON not in requete.url and JETON not in repr(requete) and JETON not in repr(requete.authentification)
    assert JETON not in str(sorted(requete.params.items())) and requete.authentification.valeur == JETON
    assert "•••" in repr(requete.authentification)


def test_le_secret_est_ouvert_pour_un_seul_appel_puis_referme_meme_en_erreur():
    coffre = coffre_pour("search_console")
    con, _, _ = fabrique(ReponseHttp(200, {"ok": 1}), ReponseHttp(500, {}), ErreurTransport("delai"), coffre=coffre)
    appel(con)
    assert coffre.ouvertures["principal"] == 1 and coffre.ouverts == 0
    erreur(con)
    erreur(con)
    assert coffre.ouvertures["principal"] == 3 and coffre.ouverts == 0


def test_une_exception_du_transport_dont_le_texte_contient_le_secret_ne_fuit_pas():
    con, _, _ = fabrique(RuntimeError(f"connexion refusée avec {JETON}"))
    e = erreur(con)
    assert e.code == "REJ-SIGNAUX-RESEAU" and e.reprenable
    assert JETON not in str(e) and JETON not in repr(e.publique()) and e.__cause__ is None


def test_un_delai_ou_une_panne_de_connexion_est_reprenable():
    con, _, _ = fabrique(ErreurTransport("delai"))
    e = erreur(con)
    assert (e.code, e.reprenable) == ("REJ-SIGNAUX-RESEAU", True)


def test_un_coffre_indisponible_donne_un_refus_sans_son_message():
    class Casse:
        def __init__(self):
            self.n = 0

        def __call__(self):
            @contextlib.contextmanager
            def ouvrir():
                raise RuntimeError("COFFRE_TRANSACTION_METIER : détail interne secret-xyz")
                yield  # pragma: no cover

            return ouvrir()

    t = Transport()
    con = Mini(
        t,
        compte("search_console", "https://www.horizon.example/"),
        {"principal": Casse()},
        maintenant=Horloge(),
        masqueur=masqueur(),
    )
    e = erreur(con)
    assert e.code == "REJ-SIGNAUX-COFFRE-INDISPONIBLE" and "secret-xyz" not in str(e) and t.requetes == []


def test_le_quota_local_refuse_avant_le_transport_et_avant_le_coffre():
    coffre = coffre_pour("search_console")
    t = Transport()

    class Petit(Mini):
        LIMITES = Quota(par_minute=1, par_jour=None, source="test")

    con = Petit(
        t,
        compte("search_console", "https://www.horizon.example/"),
        coffre.fournisseurs(),
        maintenant=Horloge(),
        masqueur=masqueur(),
    )
    appel(con)
    e = erreur(con)
    assert e.code == "REJ-SIGNAUX-QUOTA-LOCAL" and len(t.requetes) == 1 and coffre.ouvertures["principal"] == 1


def test_un_fournisseur_de_secret_manquant_ou_en_trop_est_refuse_a_la_construction():
    for fournisseurs in ({}, {"principal": lambda: None, "extra": lambda: None}):
        with pytest.raises(ErreurSignaux) as exc:
            Mini(
                Transport(),
                compte("search_console", "https://www.horizon.example/"),
                fournisseurs,
                maintenant=Horloge(),
                masqueur=masqueur(),
            )
        assert exc.value.code == "REJ-SIGNAUX-SECRET-REF"


def test_un_compte_d_une_autre_source_ou_desactive_est_refuse():
    with pytest.raises(ErreurSignaux):
        Mini(
            Transport(),
            compte("pagespeed", "https://www.horizon.example/"),
            coffre_pour("search_console").fournisseurs(),
            maintenant=Horloge(),
            masqueur=masqueur(),
        )
    inactif = compte("search_console", "https://www.horizon.example/")
    import dataclasses

    with pytest.raises(ErreurSignaux) as exc:
        Mini(
            Transport(),
            dataclasses.replace(inactif, actif=False),
            coffre_pour("search_console").fournisseurs(),
            maintenant=Horloge(),
            masqueur=masqueur(),
        )
    assert exc.value.code == "REJ-SIGNAUX-COMPTE-INACTIF"


def test_sans_masqueur_aucun_connecteur_ne_demarre():
    for sans in (None, object()):
        with pytest.raises(ErreurSignaux):
            Mini(
                Transport(),
                compte("search_console", "https://www.horizon.example/"),
                coffre_pour("search_console").fournisseurs(),
                maintenant=Horloge(),
                masqueur=sans,
            )


def test_le_transport_par_defaut_refuse_tout():
    with pytest.raises(ErreurSignaux) as exc:
        TransportNonBranche().envoyer(RequeteHttp("GET", URL))
    assert exc.value.code == "REJ-SIGNAUX-TRANSPORT-NON-BRANCHE" and not exc.value.reprenable


def test_authentification_exige_un_nom_hors_bearer_et_une_valeur():
    with pytest.raises(ErreurSignaux):
        Authentification("parametre", "v")
    with pytest.raises(ErreurSignaux):
        Authentification("bearer", "")
    with pytest.raises(ErreurSignaux):
        Authentification("cookie", "v", nom="x")
    assert "v-secret" not in repr(Authentification("en_tete", "v-secret", nom="x-api-key"))


@pytest.mark.parametrize(
    "valeur,attendu",
    [
        (12, "12"),
        (12.5, "12.5"),
        ("0.10", "0.1"),
        (0.1, "0.1"),
        (-0.0, "0"),
        (1234567.891234567, "1234567.891235"),
        ("007", "7"),
    ],
)
def test_nombre_texte_est_un_texte_decimal_sans_zero_inutile(valeur, attendu):
    assert base.nombre_texte(valeur) == attendu


@pytest.mark.parametrize(
    "mauvais", [True, False, None, "abc", "NaN", float("inf"), float("nan"), "1e999999", [1], {"a": 1}]
)
def test_nombre_texte_refuse_ce_qui_n_est_pas_un_nombre_fini(mauvais):
    with pytest.raises(ErreurSignaux) as exc:
        base.nombre_texte(mauvais)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_champ_et_liste_refusent_l_absent_et_le_mal_type():
    corps = {"a": {"b": [10, {"c": "x"}]}, "n": True}
    assert base.champ(corps, "a", "b", 0, types=(int,)) == 10
    assert base.champ(corps, "a", "b", 1, "c", types=(str,)) == "x"
    for chemin, types in (
        (("a", "z"), (int,)),
        (("a", "b", 5), (int,)),
        (("a", "b", 0), (str,)),
        (("n",), (int, bool)),
        (("a", "b", 0, "x"), (int,)),
    ):
        with pytest.raises(ErreurSignaux) as exc:
            base.champ(corps, *chemin, types=types)
        assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"
    assert base.liste(corps, "a", "b") == [10, {"c": "x"}]
    with pytest.raises(ErreurSignaux) as exc:
        base.liste({"x": list(range(11))}, "x", maximum=10)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-TROP-GROSSE"


def test_la_fenetre_suivante_relit_les_derniers_jours_puis_avance():
    con, _, _ = fabrique()
    # search_console : retard 3 jours, historique 35 jours (Mini hérite de la base : 28 jours, relecture 3)
    f = con.fenetre_suivante(None, date(2026, 11, 1))
    assert (f.fin, (f.fin - f.debut).days + 1) == (date(2026, 10, 29), 28)
    suite = con.fenetre_suivante(date(2026, 10, 29), date(2026, 11, 4))
    assert (suite.debut, suite.fin) == (date(2026, 10, 27), date(2026, 11, 1))
    # la relecture des derniers jours se refait à chaque tour (le fournisseur révise) tant que le repère n'a pas pris
    # trop d'avance
    assert con.fenetre_suivante(date(2026, 10, 29), date(2026, 10, 30)) is not None
    assert con.fenetre_suivante(date(2026, 10, 29), date(2026, 11, 1)) is not None
    assert con.fenetre_suivante(date(2026, 10, 30), date(2026, 10, 30)) is None
