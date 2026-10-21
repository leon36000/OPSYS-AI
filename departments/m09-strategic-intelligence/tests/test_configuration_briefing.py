"""Réglages du briefing (PLAN T1.5-d) : fenêtre d'alertes lue dans `department.yaml`, budget de sortie
tiré de la limite du socle. Aucun défaut inventé : une valeur absente ou invalide retombe sur le
comportement d'avant (le jour même)."""

from __future__ import annotations

import json

import pytest
from m9_strategic_intelligence import outils as m9_outils

from opsys import jetons


def test_le_vrai_manifeste_fixe_une_fenetre_de_trois_jours_pour_couvrir_la_fin_de_semaine():
    assert m9_outils._fenetre_alertes_jours() == 3


@pytest.mark.parametrize("contenu", [
    "configuration: {}\n",
    "nom: sans-configuration\n",
    "configuration:\n  fenetre_alertes_jours: -1\n",
    "configuration:\n  fenetre_alertes_jours: '3'\n",
    "configuration:\n  fenetre_alertes_jours: true\n",
    "configuration:\n  fenetre_alertes_jours: 2.5\n",
    "configuration: 3\n",
])
def test_une_fenetre_absente_ou_invalide_retombe_sur_le_jour_meme(tmp_path, monkeypatch, contenu):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(m9_outils, "_MANIFESTE", manifeste)
    assert m9_outils._fenetre_alertes_jours() == 0


def test_une_fenetre_valide_est_lue_telle_quelle(tmp_path, monkeypatch):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text("configuration:\n  fenetre_alertes_jours: 5\n", encoding="utf-8")
    monkeypatch.setattr(m9_outils, "_MANIFESTE", manifeste)
    assert m9_outils._fenetre_alertes_jours() == 5


def test_le_budget_de_sortie_laisse_la_place_de_l_enveloppe_sous_la_limite_du_socle():
    enveloppe = len(json.dumps({"ok": True, "resultat": ""}, ensure_ascii=False))
    assert m9_outils.BUDGET_SORTIE == jetons.LIMITE_SORTIE_DEFAUT - 100
    assert m9_outils.BUDGET_SORTIE + enveloppe <= jetons.LIMITE_SORTIE_DEFAUT
