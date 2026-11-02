"""Les seuils du radar passent par la couche UNIQUE des réglages de direction (CFG-1) : déclarés au manifeste de M9, lus
adopté > fichier > absence, jamais une valeur par défaut ni une proposition (fictif)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml
from m9_strategic_intelligence import reglages_radar
from m9_strategic_intelligence import risques as rk

from opsys import stockage
from opsys.reglages.declaration import lire as lire_declarations

_spec = importlib.util.spec_from_file_location(
    "reglages_aide", Path(__file__).resolve().parents[3] / "tests" / "reglages_aide.py"
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)

FICTIF = True
MANIFESTE = Path(reglages_radar._MANIFESTE)


def _donnees() -> dict:
    return yaml.safe_load(MANIFESTE.read_text(encoding="utf-8"))


def _manifeste_avec(tmp_path, monkeypatch, radar) -> None:
    donnees = _donnees()
    donnees["configuration"]["radar"] = radar
    chemin = tmp_path / "department.yaml"
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(reglages_radar, "_MANIFESTE", chemin)


def test_le_manifeste_declare_exactement_les_reglages_du_radar_avec_leur_type_et_leur_unite():
    declares = {
        r.cle: r for r in lire_declarations(_donnees()["reglages"], "manifeste", "M9", "m09-strategic-intelligence")
    }
    assert set(declares) == {r.cle for r in rk.REGLAGES.values()}
    for nom, reglage in rk.REGLAGES.items():
        d = declares[reglage.cle]
        assert d.type == reglage.nature and d.unite == reglage.unite and d.libelle == reglage.libelle, nom
        assert d.chemin == ("configuration", "radar", nom) and d.proposition is None, "aucune valeur inventée"
        assert d.niveau.value == "N3"


def test_le_fichier_livre_ne_declare_aucun_seuil_fail_closed():
    assert _donnees()["configuration"]["radar"] == {}
    assert reglages_radar.lire() == {"seuils": {}, "seuils_refuses": {}}


def test_une_valeur_du_fichier_valide_est_lue_une_invalide_est_refusee_avec_son_code(tmp_path, monkeypatch):
    _manifeste_avec(
        tmp_path,
        monkeypatch,
        {
            "plaintes_seuil_nombre": 4,
            "estimation_ecart_relatif_max": "0.3",
            "retard_chantier_jours": 0,
            "donnees_perimees_jours": "14",
            "cash_libre_plancher_cad": None,
        },
    )
    lu = reglages_radar.lire()
    assert lu["seuils"] == {"plaintes_seuil_nombre": 4, "estimation_ecart_relatif_max": "0.3"}
    assert lu["seuils_refuses"] == {
        "retard_chantier_jours": "REJ-REGLAGE-HORS-BORNES",
        "donnees_perimees_jours": "REJ-REGLAGE-TYPE",
    }


def test_un_bloc_illisible_n_invente_aucun_seuil(tmp_path, monkeypatch):
    _manifeste_avec(tmp_path, monkeypatch, 5)
    assert reglages_radar.lire() == {"seuils": {}, "seuils_refuses": {}}


def test_ce_que_lit_le_radar_est_exactement_ce_qu_il_declare_comme_seuil_a_declarer(tmp_path, monkeypatch):
    _manifeste_avec(tmp_path, monkeypatch, {"plaintes_seuil_nombre": 4})
    res = rk.evaluer([], connaissance="2026-10-28T13:00:00Z", **reglages_radar.lire())
    assert res["seuils_declares"] == {"m9.plaintes_seuil_nombre": "4"}
    manquants = {cle for n in res["regles_non_evaluees"] for cle in n.get("a_declarer", [])}
    assert set(res["reglages_a_declarer"]) == manquants | {"m9.multiple_seuil_critique"}
    assert "m9.plaintes_seuil_nombre" not in manquants and "m9.retard_chantier_jours" in manquants


@pytest.fixture
def deps(tmp_path, monkeypatch):
    yield aide.installer(tmp_path, monkeypatch)
    stockage.liberer()


def test_une_valeur_adoptee_par_le_proprietaire_l_emporte_sur_le_fichier_puis_le_retour_arriere_rend_le_fichier(
    deps, tmp_path, monkeypatch
):
    _manifeste_avec(tmp_path, monkeypatch, {"plaintes_seuil_nombre": 4})
    with stockage.transaction() as cnx:
        assert reglages_radar.lire()["seuils"] == {"plaintes_seuil_nombre": 4}
        aide.resultat(aide.adopter(cnx, deps, "m9.plaintes_seuil_nombre", 7))
        aide.resultat(aide.adopter(cnx, deps, "m9.multiple_seuil_critique", "1.5"))
    with stockage.transaction():
        lu = reglages_radar.lire()["seuils"]
        assert lu == {"plaintes_seuil_nombre": 7, "multiple_seuil_critique": "1.5"}
    with stockage.transaction() as cnx:
        aide.resultat(aide.revenir(cnx, deps, "m9.plaintes_seuil_nombre"))
    with stockage.transaction():
        assert reglages_radar.lire()["seuils"] == {"plaintes_seuil_nombre": 4, "multiple_seuil_critique": "1.5"}


def test_une_adoption_hors_bornes_ou_mal_typee_est_refusee_par_la_declaration_de_m9(deps):
    with stockage.transaction() as cnx:
        for cle, valeur in (
            ("m9.plaintes_seuil_nombre", 0),
            ("m9.plaintes_seuil_nombre", "3"),
            ("m9.multiple_seuil_critique", "1.0"),
            ("m9.capacite_utilisation_seuil_pct", "301"),
        ):
            refus = aide.refus(aide.adopter(cnx, deps, cle, valeur))
            assert re.search(r"REJ-REGLAGE-(HORS-BORNES|TYPE)", refus), (cle, valeur, refus)
