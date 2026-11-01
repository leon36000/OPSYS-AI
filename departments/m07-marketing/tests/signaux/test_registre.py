"""Le registre des faits : identité, révision, tout-ou-rien, bornes, chaîne de hachage."""

from __future__ import annotations

from datetime import date

import pytest
from m7_marketing import journal_chaine
from m7_marketing.signaux import modele, registre
from m7_marketing.signaux.erreurs import ErreurSignaux

PROV = {
    "fournisseur": "google",
    "point_acces": "searchAnalytics.query",
    "version_api": "webmasters/v3",
    "mode": "api_lecture",
    "empreinte_reponse": "a" * 64,
    "page": 0,
}
HORO = "2026-11-01T12:00:00Z"


def f(
    jour="2026-10-01",
    clics="10",
    source="search_console",
    nature="performance_recherche_jour",
    ref="propriete",
    type_="site",
    compte="principal",
    **kw,
):
    return modele.brouillon_fait(
        source=source,
        compte_ref=compte,
        nature=nature,
        portee_type=type_,
        portee_ref=ref,
        debut=jour,
        fin=kw.pop("fin", jour),
        mesures={"clics": clics},
        observe_le="2026-11-01T12:00:00Z",
        fictif=kw.pop("fictif", True),
        provenance=kw.pop("provenance", PROV),
        **kw,
    )


def code(exc):
    return exc.value.code


def test_un_nouveau_fait_une_relecture_identique_puis_une_revision():
    j: list = []
    assert registre.enregistrer(j, [f()], HORO) == {"nouveaux": 1, "revisions": 0, "inchanges": 0}
    assert registre.enregistrer(j, [f()], HORO) == {"nouveaux": 0, "revisions": 0, "inchanges": 1}
    assert len(j) == 1
    assert registre.enregistrer(j, [f(clics="11")], HORO) == {"nouveaux": 0, "revisions": 1, "inchanges": 0}
    assert [m["revision"] for m in j] == [1, 2]
    assert registre.courants(registre.charger(j))[j[0]["fait_id"]]["mesures"] == {"clics": "11"}


def test_la_provenance_variable_ne_cree_pas_de_revision():
    j: list = []
    registre.enregistrer(j, [f()], HORO)
    autre = f(provenance={**PROV, "empreinte_reponse": "b" * 64, "page": 4})
    assert registre.enregistrer(j, [autre], "2026-11-02T12:00:00Z")["inchanges"] == 1
    assert len(j) == 1


def test_une_revision_vers_une_valeur_deja_vue_reste_une_revision():
    j: list = []
    registre.enregistrer(j, [f(clics="10")], HORO)
    registre.enregistrer(j, [f(clics="11")], HORO)
    registre.enregistrer(j, [f(clics="10")], HORO)
    assert [m["mesures"]["clics"] for m in j] == ["10", "11", "10"] and [m["revision"] for m in j] == [1, 2, 3]


def test_deux_valeurs_pour_le_meme_fait_dans_une_page_refusent_la_page_entiere():
    j: list = []
    with pytest.raises(ErreurSignaux) as exc:
        registre.enregistrer(j, [f(ref="a"), f(clics="1", type_="site"), f(clics="2", type_="site")], HORO)
    assert code(exc) == "REJ-SIGNAUX-FAIT-CONFLIT" and len(j) == 0


def test_le_meme_fait_identique_deux_fois_dans_une_page_n_est_ecrit_qu_une_fois():
    j: list = []
    assert registre.enregistrer(j, [f(), f()], HORO)["nouveaux"] == 1 and len(j) == 1


def test_un_fait_invalide_dans_la_page_n_ecrit_rien_du_tout():
    j: list = []
    mauvais = f(jour="2026-10-02")
    mauvais["mesures"] = {"clics": 3.5}
    with pytest.raises(ErreurSignaux):
        registre.enregistrer(j, [f(), mauvais], HORO)
    assert len(j) == 0


def test_le_registre_refuse_au_dela_de_sa_borne_sans_rien_tronquer(monkeypatch):
    monkeypatch.setattr(registre, "MAX_FAITS", 2)
    j: list = []
    registre.enregistrer(j, [f(jour="2026-10-01"), f(jour="2026-10-02")], HORO)
    with pytest.raises(ErreurSignaux) as exc:
        registre.enregistrer(j, [f(jour="2026-10-03")], HORO)
    assert code(exc) == "REJ-SIGNAUX-REGISTRE-PLEIN" and len(j) == 2
    # une relecture identique n'ajoute rien : elle passe même à la borne
    assert registre.enregistrer(j, [f(jour="2026-10-01")], HORO)["inchanges"] == 1


def test_une_chaine_alteree_est_une_erreur_pas_une_lecture_partielle():
    j: list = []
    registre.enregistrer(j, [f(), f(jour="2026-10-02")], HORO)
    j[0] = {**j[0], "mesures": {"clics": "999"}}
    for appel in (lambda: registre.charger(j), lambda: registre.lire(j), lambda: registre.enregistrer(j, [f()], HORO)):
        with pytest.raises(ErreurSignaux) as exc:
            appel()
        assert code(exc) == "REJ-SIGNAUX-JOURNAL-ALTERE"


def test_un_maillon_etranger_ou_un_fait_devenu_non_conforme_sont_refuses():
    j: list = []
    journal_chaine.ajouter(j, "autre", {"x": 1}, HORO)
    with pytest.raises(ErreurSignaux) as exc:
        registre.charger(j)
    assert code(exc) == "REJ-SIGNAUX-REGISTRE-INVALIDE"
    k: list = []
    mauvais = f()
    mauvais["mesures"] = {"clics": 1.5}
    journal_chaine.ajouter(k, "signal", mauvais, HORO)
    with pytest.raises(ErreurSignaux) as exc:
        registre.charger(k)
    assert code(exc) == "REJ-SIGNAUX-REGISTRE-INVALIDE"


def test_une_suite_de_revisions_incoherente_est_une_erreur():
    base = modele.normaliser_fait(f())
    saut = modele.normaliser_fait({**f(clics="2"), "revision": 3})
    with pytest.raises(ErreurSignaux):
        registre.courants([base, saut])
    with pytest.raises(ErreurSignaux):
        registre.courants([saut])


def test_lire_filtre_par_source_nature_compte_et_chevauchement_de_periode():
    j: list = []
    registre.enregistrer(
        j,
        [
            f(jour="2026-10-01"),
            f(jour="2026-10-10"),
            f(jour="2026-10-20"),
            f(jour="2026-10-01", fin="2026-10-07", nature="requetes_periode", type_="requete", ref="gouttiere"),
            f(jour="2026-10-05", source="bing_webmaster", compte="second"),
        ],
        HORO,
    )
    tout = registre.lire(j, limite=50)
    assert tout["total"] == 5
    assert [
        x["periode_debut"]
        for x in registre.lire(j, source="search_console", nature="performance_recherche_jour", limite=50)["faits"]
    ] == ["2026-10-01", "2026-10-10", "2026-10-20"]
    assert registre.lire(j, compte_ref="second")["total"] == 1
    # chevauchement : la requête du 1er au 7 est dans [5 au 6] ; le 10 et le 20 ne le sont pas
    dans = registre.lire(j, debut=date(2026, 10, 5), fin=date(2026, 10, 6), limite=50)
    assert {x["nature"] for x in dans["faits"]} == {"requetes_periode", "performance_recherche_jour"} and dans[
        "total"
    ] == 2
    assert registre.lire(j, debut=date(2026, 10, 8), fin=date(2026, 10, 9))["total"] == 0


def test_lire_trie_pagine_et_dit_ce_qui_reste():
    j: list = []
    registre.enregistrer(j, [f(jour=f"2026-10-{d:02d}") for d in (5, 3, 4, 1, 2)], HORO)
    p1 = registre.lire(j, limite=2)
    assert [x["periode_debut"] for x in p1["faits"]] == ["2026-10-01", "2026-10-02"] and p1["reste"] == 3
    p3 = registre.lire(j, limite=2, decalage=4)
    assert [x["periode_debut"] for x in p3["faits"]] == ["2026-10-05"] and p3["reste"] == 0 and p3["total"] == 5


def test_lire_ne_rend_que_la_derniere_revision_et_compte_les_revisees():
    j: list = []
    registre.enregistrer(j, [f(clics="1")], HORO)
    registre.enregistrer(j, [f(clics="2")], HORO)
    lu = registre.lire(j)
    assert lu["total"] == 1 and lu["faits"][0]["mesures"] == {"clics": "2"} and lu["revises"] == 1


@pytest.mark.parametrize(
    "modif", [{"limite": 0}, {"limite": 1001}, {"limite": True}, {"decalage": -1}, {"decalage": 1.5}]
)
def test_les_bornes_de_lecture_sont_strictes(modif):
    with pytest.raises(ErreurSignaux) as exc:
        registre.lire([], **modif)
    assert code(exc) == "REJ-SIGNAUX-ARGUMENT-INVALIDE"


def test_filtres_inconnus_ou_periode_inversee_sont_refuses():
    with pytest.raises(ErreurSignaux):
        registre.lire([], source="tiktok")
    with pytest.raises(ErreurSignaux):
        registre.lire([], nature="inconnue")
    with pytest.raises(ErreurSignaux):
        registre.lire([], debut=date(2026, 10, 5), fin=date(2026, 10, 1))
