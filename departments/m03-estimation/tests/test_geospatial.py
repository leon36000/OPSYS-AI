"""Estimation géospatiale du Québec (M3.7) : ports, doubles, agrégation, sources candidates. AUCUNE donnée réelle."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contexte_site, geospatial  # noqa: E402
from m3_estimation.geospatial import (  # noqa: E402
    CadastreDouble,
    ImagerieDouble,
    LotCadastral,
    PortAbsent,
    ReferenceImagerie,
    RoleEvaluationDouble,
    SourceDonnee,
    UniteEvaluation,
)

FICTIF = True
LE = "2026-10-01T09:00:00-04:00"
ADRESSE = {
    "numero_civique": "123",
    "odonyme": "Rue de l'Exemple",
    "municipalite": "Ville Fictive",
    "code_postal": "h2x 1y4",
}


def _source(source_id="double-fictif", fictif=True):
    return SourceDonnee(source_id, "2025-12", LE, "CC-BY 4.0 (fictif)", fictif)


def _cle():
    adresse, _ = geospatial.normaliser_adresse(ADRESSE)
    return adresse.cle


def _lot(sommets=None):
    sommets = sommets or (
        ("45.5000000", "-73.6000000"),
        ("45.5000000", "-73.5990000"),
        ("45.5009000", "-73.5990000"),
        ("45.5009000", "-73.6000000"),
    )
    return LotCadastral("1234567", "Ville Fictive", tuple(sommets), _source())


def _unite(**plus):
    base = {
        "matricule": "0000-00-0000",
        "annee_construction": 1978,
        "nombre_etages": 2,
        "superficie_terrain_m2": "612.0",
        "aire_batiment_m2": "98.0",
        "usage_code": "1000",
        "source": _source(),
    }
    base.update(plus)
    return UniteEvaluation(**base)


def _ports(lot=None, unite=None, refs=None):
    cle = _cle()
    return (
        CadastreDouble({cle: lot or _lot()}),
        RoleEvaluationDouble({cle: unite or _unite()}),
        ImagerieDouble(
            {cle: refs if refs is not None else [ReferenceImagerie("ortho-2024", "2024", "0.2", _source())]}
        ),
    )


def test_l_adresse_est_normalisee_en_cle_stable_sans_accent_ni_casse():
    a, v = geospatial.normaliser_adresse(ADRESSE)
    assert v is None and a.code_postal == "H2X 1Y4"
    b, _ = geospatial.normaliser_adresse(
        {**ADRESSE, "odonyme": "  RUE  DE L’EXEMPLE ", "municipalite": "ville fictive"}
    )
    assert a.cle == b.cle
    c, _ = geospatial.normaliser_adresse({**ADRESSE, "municipalite": "Québec"})
    d, _ = geospatial.normaliser_adresse({**ADRESSE, "municipalite": "Quebec"})
    assert c.cle == d.cle


@pytest.mark.parametrize(
    "adresse",
    [
        None,
        {},
        {"numero_civique": "1"},
        {**ADRESSE, "code_postal": "12345"},
        {**ADRESSE, "odonyme": ""},
        {**ADRESSE, "numero_civique": "x" * 81},
        {**ADRESSE, "intrus": 1},
        {**ADRESSE, "municipalite": 5},
        {**ADRESSE, "odonyme": "ligne\nbrisee"},
    ],
)
def test_adresses_invalides_refusees(adresse):
    a, v = geospatial.normaliser_adresse(adresse)
    assert a is None and v["code"] == "REJ-GEO-ENTREE-INVALIDE"


def test_l_agregation_depuis_des_doubles_donne_lot_surface_calculee_unite_et_imagerie_en_contexte():
    resultat, verdict = geospatial.agreger(ADRESSE, *_ports())
    assert verdict is None and resultat["fictif"] is True
    assert resultat["statuts"] == {"cadastre": "ok", "role_evaluation": "ok", "imagerie": "ok"}
    lot = resultat["donnees"]["lot"]
    assert lot["numero_lot"] == "1234567" and 5000 < float(lot["surface_m2"]) < 8000  # ~ 80 m x 100 m
    assert len(lot["recu_geometrie"]) == 64
    assert resultat["donnees"]["unite_evaluation"]["annee_construction"] == 1978
    assert resultat["donnees"]["imagerie"][0]["usage"] == "contexte_seulement"
    assert resultat["faits_pour_contexte"]["faits"] == {"age": {"annee_construction": 1978}, "hauteur": {"etages": 2}}
    assert "adresse" not in str(resultat["adresse_cle"]).lower() and len(resultat["adresse_cle"]) == 24


def test_la_surface_vient_du_moteur_jamais_de_la_superficie_que_le_role_affirme():
    resultat, _ = geospatial.agreger(ADRESSE, *_ports(unite=_unite(superficie_terrain_m2="999999.0")))
    assert resultat["donnees"]["unite_evaluation"]["superficie_terrain_m2"] == "999999.0"  # donnée citée, pas reprise
    assert float(resultat["donnees"]["lot"]["surface_m2"]) < 10000  # la surface du lot est celle du polygone


def test_sans_source_branchee_chaque_port_dit_non_configure_et_rien_n_est_invente():
    absent = PortAbsent()
    resultat, verdict = geospatial.agreger(ADRESSE, absent, absent, absent)
    assert verdict is None and resultat["statuts"] == {
        "cadastre": "non_configure",
        "role_evaluation": "non_configure",
        "imagerie": "non_configure",
    }
    assert resultat["donnees"] == {"lot": None, "unite_evaluation": None, "imagerie": []}
    assert resultat["faits_pour_contexte"] is None and resultat["fictif"] is False and resultat["sources"] == []


def test_adresse_inconnue_des_sources_est_introuvable_pas_une_valeur_par_defaut():
    autre = {**ADRESSE, "numero_civique": "999"}
    resultat, _ = geospatial.agreger(autre, *_ports())
    assert set(resultat["statuts"].values()) == {"introuvable"} and resultat["faits_pour_contexte"] is None


def test_un_port_qui_leve_ne_bloque_pas_les_autres_et_son_erreur_n_est_pas_recopiee():
    class Casse:
        def lot_par_adresse(self, adresse):
            raise ConnectionError("secret-interne-123 : serveur injoignable")

    _, role, imagerie = _ports()
    resultat, verdict = geospatial.agreger(ADRESSE, Casse(), role, imagerie)
    assert (
        verdict is None
        and resultat["statuts"]["cadastre"] == "echec"
        and resultat["statuts"]["role_evaluation"] == "ok"
    )
    assert "secret-interne" not in str(resultat)


def test_un_lot_au_polygone_invalide_est_refuse_avec_le_motif_et_sans_surface():
    papillon = (("45.5", "-73.6"), ("45.5", "-73.599"), ("45.5009", "-73.6"), ("45.5009", "-73.599"))
    resultat, _ = geospatial.agreger(ADRESSE, *_ports(lot=_lot(papillon)))
    assert resultat["statuts"]["cadastre"] == "invalide" and resultat["donnees"]["lot"] is None
    assert any("REJ-GEO-AUTO-INTERSECTION" in a for a in resultat["avertissements"])
    hors = (("48.85", "2.35"), ("48.85", "2.351"), ("48.851", "2.351"), ("48.851", "2.35"))  # Paris
    resultat, _ = geospatial.agreger(ADRESSE, *_ports(lot=_lot(hors)))
    assert resultat["statuts"]["cadastre"] == "invalide"
    assert any("REJ-GEO-HORS-QUEBEC" in a for a in resultat["avertissements"])


def test_un_port_qui_rend_n_importe_quoi_est_invalide_sans_exception():
    class Mauvais:
        def lot_par_adresse(self, adresse):
            return {"surface_m2": "100000"}

        def unite_par_adresse(self, adresse):
            return "ceci n'est pas une unité"

        def imagerie_pour(self, adresse):
            return ["x", ReferenceImagerie("ortho", "2024", None, _source())]

    resultat, verdict = geospatial.agreger(ADRESSE, Mauvais(), Mauvais(), Mauvais())
    assert verdict is None
    assert resultat["statuts"]["cadastre"] == "invalide" and resultat["statuts"]["role_evaluation"] == "invalide"
    assert resultat["donnees"]["lot"] is None and resultat["donnees"]["unite_evaluation"] is None
    assert len(resultat["donnees"]["imagerie"]) == 1 and any("ignorées" in a for a in resultat["avertissements"])


def test_un_double_ne_porte_que_des_donnees_fictives():
    reel = LotCadastral("1", "V", (), _source(fictif=False))
    with pytest.raises(ValueError):
        CadastreDouble({"k": reel})
    with pytest.raises(ValueError):
        RoleEvaluationDouble({"k": _unite(source=_source(fictif=False))})
    with pytest.raises(ValueError):
        ImagerieDouble({"k": [ReferenceImagerie("o", "2024", None, _source(fictif=False))]})


def test_les_faits_geospatiaux_alimentent_le_contexte_et_un_conflit_avec_m2_reste_un_conflit():
    resultat, _ = geospatial.agreger(ADRESSE, *_ports())
    entrees = {
        "lead_id": "lead-geo-1",
        "service": "service_a",
        "date_reference": "2026-10-15",
        "profil_geospatial": resultat["faits_pour_contexte"],
    }
    contexte, verdict = contexte_site.construire(entrees)
    assert verdict is None
    f = {x["facteur"]: x for x in contexte["facteurs"]}
    assert f["age"]["statut"] == "connu" and f["age"]["sources"][0]["type"] == "port_geospatial"
    entrees["profil_propriete"] = {
        "identifiant": "m2",
        "version": "1",
        "recu_le": LE,
        "faits": {"age": {"annee_construction": 1990}},
    }
    contexte, _ = contexte_site.construire(entrees)
    assert {x["facteur"]: x for x in contexte["facteurs"]}["age"]["statut"] == "conflit"


def test_un_role_d_evaluation_incoherent_est_refuse_par_le_contexte_pas_accepte_en_silence():
    resultat, _ = geospatial.agreger(ADRESSE, *_ports(unite=_unite(annee_construction=3025, nombre_etages=99)))
    contexte, verdict = contexte_site.construire(
        {
            "lead_id": "l",
            "service": "service_a",
            "date_reference": "2026-10-15",
            "profil_geospatial": resultat["faits_pour_contexte"],
        }
    )
    assert contexte is None and verdict["code"] == "REJ-CONTEXTE-ENTREE-INVALIDE"


def test_les_sources_candidates_sont_toutes_a_verifier_avec_une_licence_presumee_et_jamais_lues():
    sources = geospatial.sources_candidates()
    ids = {s["identifiant"] for s in sources}
    assert {
        "quebec.role-evaluation-fonciere",
        "quebec.cadastre",
        "quebec.rqa",
        "osm.openstreetmap",
        "google.street-view",
    } <= ids
    for s in sources:
        assert s["lue_par"] is None and s["licence_presumee"]
        assert s["verification"] in ("a_verifier", "deja_documentee", "ferme_budget_et_conditions"), s["identifiant"]
    non_verifiees = [s for s in sources if s["verification"] == "a_verifier"]
    assert len(non_verifiees) >= 5
    street = next(s for s in sources if s["identifiant"] == "google.street-view")
    assert street["verification"] == "ferme_budget_et_conditions" and "CONTEXTE SEULEMENT" in street["note"]
    osm = next(s for s in sources if s["identifiant"] == "osm.openstreetmap")
    assert "ODbL" in osm["licence_presumee"]


def test_le_portable_des_sources_est_une_copie_qu_on_ne_peut_pas_corrompre_pour_les_appels_suivants():
    geospatial.sources_candidates()[0]["verification"] = "verifiee"
    assert geospatial.sources_candidates()[0]["verification"] == "a_verifier"
