"""Amorçage VIDE des fournisseurs connus : les NOMS seulement, « à fournir », aucune donnée devinée.

Gentek, Royal Solution de Bâtiment, O.A.M. et Kaycan n'ont fourni ni courriel, ni compte, ni tarif : le manifeste ne
porte que leurs noms et ce qu'il faut fournir pour chacun ; la liste dit lesquels n'ont aucune fiche. Données fictives.
"""

from __future__ import annotations

from pathlib import Path

import m6_material_control.outils as outils_mod
import pytest
import yaml
from m6_material_control import fournisseurs_a_fournir as af

NOMS = ["Gentek", "Royal Solution de Bâtiment", "O.A.M.", "Kaycan"]


def _bloc():
    donnees = yaml.safe_load(Path(outils_mod._MANIFESTE).read_text(encoding="utf-8"))
    return donnees["configuration"]["fournisseurs_a_fournir"]


def test_le_manifeste_ne_porte_que_les_quatre_noms_et_ce_qu_il_faut_fournir_aucune_donnee():
    bloc = _bloc()
    assert set(bloc) == {"noms", "pour_chacun"} and bloc["noms"] == NOMS
    texte = yaml.safe_dump(bloc, allow_unicode=True)
    for donnee_reelle in ("@", "http", "tel:", "514", "418", "450"):
        assert donnee_reelle not in texte, "aucun courriel, lien ni téléphone : rien n'a été fourni"
    assert len(bloc["pour_chacun"]) >= 5


def test_sans_fiche_les_quatre_sont_a_fournir_et_une_fiche_ne_retire_que_le_sien():
    noms, exigences = af.lire_configuration({"fournisseurs_a_fournir": _bloc()})
    assert noms == NOMS and exigences
    assert af.a_fournir(noms, []) == NOMS
    assert af.a_fournir(noms, [{"nom": "Gentek"}]) == NOMS[1:]
    assert af.a_fournir(noms, [{"nom": "ROYAL SOLUTION DE BATIMENT"}, {"nom": "oam"}]) == ["Gentek", "Kaycan"]


def test_un_nom_proche_n_est_pas_le_meme_fournisseur():
    assert af.a_fournir(NOMS, [{"nom": "Gentek (fictif)"}, {"nom": "Kaycan Québec"}]) == NOMS


@pytest.mark.parametrize("configuration", [None, {}, {"fournisseurs_a_fournir": None}, {"fournisseurs_a_fournir": []},
                                           {"fournisseurs_a_fournir": {"noms": "Gentek"}},
                                           {"fournisseurs_a_fournir": {"noms": [1, "", None]}}, "texte", 5])
def test_une_configuration_absente_ou_illisible_n_invente_aucun_nom(configuration):
    assert af.lire_configuration(configuration) == ([], [])
