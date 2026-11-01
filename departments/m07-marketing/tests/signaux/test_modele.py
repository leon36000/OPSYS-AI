"""Le modèle des signaux : un fait n'entre au registre que sous sa forme canonique, fermée, en texte décimal."""

from __future__ import annotations

import copy
from datetime import date

import pytest
from m7_marketing.signaux import modele
from m7_marketing.signaux.erreurs import ErreurSignaux

PROV = {
    "fournisseur": "google",
    "point_acces": "searchAnalytics.query",
    "version_api": "webmasters/v3",
    "mode": "api_lecture",
    "empreinte_reponse": "a" * 64,
    "page": 0,
}


def fait(**modif):
    base = modele.brouillon_fait(
        source="search_console",
        compte_ref="principal",
        nature="performance_recherche_jour",
        portee_type="site",
        portee_ref="propriete",
        debut="2026-10-01",
        fin="2026-10-01",
        mesures={"clics": "12", "impressions": "340", "ctr": "0.035294", "position": "8.2"},
        observe_le="2026-11-01T12:00:00Z",
        fictif=True,
        provenance=PROV,
    )
    base.update(modif)
    return base


def refuse(brut, code="REJ-SIGNAUX-FAIT-INVALIDE"):
    with pytest.raises(ErreurSignaux) as exc:
        modele.normaliser_fait(brut)
    assert exc.value.code == code
    return exc.value


def test_un_fait_conforme_est_normalise_et_son_identifiant_est_recalcule():
    f = modele.normaliser_fait(fait())
    assert f["fait_id"] == modele.identifiant_fait(
        "search_console",
        "principal",
        "performance_recherche_jour",
        {"type": "site", "ref": "propriete"},
        "2026-10-01",
        "2026-10-01",
    )
    assert len(f["fait_id"]) == 32 and f["revision"] == 1
    assert list(f["mesures"]) == sorted(f["mesures"])  # ordre canonique


def test_l_identite_depend_de_chaque_composante():
    base = ("search_console", "principal", "pages_periode", {"type": "page", "ref": "/a"}, "2026-10-01", "2026-10-07")
    ids = {modele.identifiant_fait(*base)}
    for i, autre in enumerate(
        ["bing_webmaster", "second", "requetes_periode", {"type": "page", "ref": "/b"}, "2026-10-02", "2026-10-08"]
    ):
        variante = list(base)
        variante[i] = autre
        ids.add(modele.identifiant_fait(*variante))
    assert len(ids) == 7
    assert modele.identifiant_fait(*base) == modele.identifiant_fait(*base)


def test_la_portee_de_type_different_ne_se_confond_pas():
    a = modele.identifiant_fait(
        "search_console", "p", "pages_periode", {"type": "page", "ref": "x"}, "2026-10-01", "2026-10-01"
    )
    b = modele.identifiant_fait(
        "search_console", "p", "pages_periode", {"type": "requete", "ref": "x"}, "2026-10-01", "2026-10-01"
    )
    assert a != b


def test_un_identifiant_menteur_est_refuse():
    refuse(fait(fait_id="0" * 32))


@pytest.mark.parametrize(
    "modif",
    [
        {"mesures": {"clics": 12}},  # nombre JSON
        {"mesures": {"clics": 12.5}},  # flottant
        {"mesures": {"clics": "1e3"}},  # notation scientifique
        {"mesures": {"clics": "12,5"}},  # virgule
        {"mesures": {"clics": "NaN"}},
        {"mesures": {"Clics": "12"}},  # nom hors snake_case
        {"mesures": {}},
        {"mesures": {f"m{i}": "1" for i in range(25)}},  # plus de 24 mesures
        {"periode_debut": "2026-13-01"},
        {"periode_debut": "2026-10-05", "periode_fin": "2026-10-01"},
        {"periode_debut": "2024-01-01", "periode_fin": "2026-10-01"},  # plus de 367 jours
        {"observe_le": "2026-11-01T12:00:00"},  # sans fuseau
        {"observe_le": "hier"},
        {"fictif": "oui"},
        {"revision": 0},
        {"revision": True},
        {"devise": "BTC"},
        {"texte": "a\x00b"},
        {"texte": "x" * 301},
        {"echantillon": {"nature": "inventé", "n": None}},
        {"echantillon": {"nature": "complet", "n": -1}},
        {"echantillon": {"nature": "complet"}},
        {"portee": {"type": "inconnu", "ref": "x"}},
        {"portee": {"type": "site", "ref": ""}},
        {"portee": {"type": "site", "ref": "x" * 201}},
        {"provenance": {**PROV, "mode": "scraping"}},
        {"provenance": {**PROV, "empreinte_reponse": "xyz"}},
        {"provenance": {**PROV, "page": -1}},
        {"provenance": {**PROV, "version_api": "v 1; rm -rf"}},
        {"provenance": {k: v for k, v in PROV.items() if k != "page"}},
    ],
)
def test_chaque_forme_hors_contrat_est_refusee(modif):
    brut = fait()
    brut.update(modif)
    if "periode_debut" in modif or "portee" in modif:
        brut["fait_id"] = "0" * 32  # l'identifiant ne peut pas se recalculer : le refus arrive de toute façon
    refuse(brut)


def test_un_champ_inconnu_ou_manquant_est_refuse():
    refuse({**fait(), "extra": 1})
    brut = fait()
    del brut["devise"]
    refuse(brut)
    refuse("pas un objet")


def test_la_nature_doit_appartenir_a_la_source():
    brut = fait(nature="avis")
    refuse(brut)


def test_une_source_inconnue_a_son_propre_code():
    refuse(fait(source="tiktok_ads"), "REJ-SIGNAUX-SOURCE-INCONNUE")


def test_le_pire_fait_legal_reste_sous_la_borne_d_octets():
    """La borne de 4096 octets est une défense en profondeur : elle ne refuse jamais un fait légal au pire cas."""
    pire = fait(texte="é" * 300)
    pire["mesures"] = {f"m{i:02d}" + "x" * 36: "-1234567890123.12345678" for i in range(24)}
    pire["portee"] = {"type": "page", "ref": "/" + "é" * 199}
    pire["nature"] = "pages_periode"
    pire["fait_id"] = modele.identifiant_fait(
        "search_console", "principal", "pages_periode", pire["portee"], "2026-10-01", "2026-10-01"
    )
    normal = modele.normaliser_fait(pire)
    import json

    assert len(json.dumps(normal, ensure_ascii=False).encode("utf-8")) < modele.MAX_OCTETS_FAIT


def test_la_borne_d_octets_refuse_au_dela(monkeypatch):
    monkeypatch.setattr(modele, "MAX_OCTETS_FAIT", 300)
    err = refuse(fait())
    assert "octets" in err.detail


def test_l_unicode_est_normalise_avant_l_identite():
    def avec(ref):
        return modele.normaliser_fait(
            modele.brouillon_fait(
                source="search_console",
                compte_ref="principal",
                nature="requetes_periode",
                portee_type="requete",
                portee_ref=ref,
                debut="2026-10-01",
                fin="2026-10-07",
                mesures={"clics": "1"},
                observe_le="2026-11-01T12:00:00Z",
                fictif=True,
                provenance=PROV,
            )
        )

    decompose, compose = "été", "été"
    assert decompose != compose
    a, b = avec(decompose), avec(compose)
    assert a["fait_id"] == b["fait_id"] and a["portee"]["ref"] == compose


def test_la_valeur_d_un_fait_ignore_la_provenance_variable():
    a, b = fait(), fait()
    b["provenance"] = {**PROV, "empreinte_reponse": "b" * 64, "page": 3}
    b["observe_le"] = "2026-11-02T12:00:00Z"
    assert modele.sans_provenance_variable(modele.normaliser_fait(a)) == modele.sans_provenance_variable(
        modele.normaliser_fait(b)
    )
    c = fait(mesures={"clics": "13", "impressions": "340", "ctr": "0.035294", "position": "8.2"})
    assert modele.sans_provenance_variable(modele.normaliser_fait(a)) != modele.sans_provenance_variable(
        modele.normaliser_fait(c)
    )


def test_le_catalogue_des_sources_est_coherent():
    assert set(modele.SOURCES_LECTURE) | {s for s in modele.SOURCES if modele.SOURCES[s].import_seulement} == set(
        modele.SOURCES
    )
    for source in modele.SOURCES.values():
        assert source.natures and set(source.natures) <= set(modele.NATURES)
        assert source.fraicheur_h >= 1 and source.retard_donnees_jours >= 0
    assert modele.SOURCES["google_ads"].secrets_annexes == ("jeton_developpeur",)
    assert modele.SOURCES["google_ads"].canal_depenses == "google_ads"
    assert modele.SOURCES["meta_ads"].canal_depenses == "meta"
    assert modele.SOURCES["umami"].auto_heberge and modele.SOURCES["matomo"].auto_heberge
    assert not modele.SOURCES["search_console"].auto_heberge


@pytest.mark.parametrize("debut,fin", [(date(2026, 10, 5), date(2026, 10, 1)), (date(2025, 1, 1), date(2026, 10, 1))])
def test_une_fenetre_invalide_est_refusee(debut, fin):
    with pytest.raises(ErreurSignaux) as exc:
        modele.Fenetre(debut, fin)
    assert exc.value.code == "REJ-SIGNAUX-FENETRE-INVALIDE"


def test_la_fenetre_a_une_cle_stable():
    assert modele.Fenetre(date(2026, 10, 1), date(2026, 10, 7)).cle() == "2026-10-01/2026-10-07"


def test_les_helpers_de_date_et_d_instant_refusent_les_formes_ambigues():
    with pytest.raises(ErreurSignaux):
        modele.date_iso("2026-1-1")
    with pytest.raises(ErreurSignaux):
        modele.instant_rfc3339("2026-11-01T12:00:00")
    assert modele.instant_rfc3339("2026-11-01T12:00:00Z").utcoffset().total_seconds() == 0


def test_normaliser_ne_modifie_pas_son_entree():
    brut = fait()
    avant = copy.deepcopy(brut)
    modele.normaliser_fait(brut)
    assert brut == avant
