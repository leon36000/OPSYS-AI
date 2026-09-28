from __future__ import annotations

import shutil

import pytest
import yaml

from opsys.departements import charger_departements, dependances_manquantes, lire_manifeste, tous_les_outils


def _copie(racine_demo, tmp_path):
    cible = tmp_path / "departements"
    shutil.copytree(racine_demo, cible)
    return cible / "m09-demo"


def _modifier(dossier, **changements):
    chemin = dossier / "department.yaml"
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    donnees.update(changements)
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")


def test_manifeste_demo_valide(departements_demo):
    dep = departements_demo["m09-demo"]
    assert dep.code == "M9"
    assert dep.prefixe_outils == "m9"
    assert dep.mode == "supervise"
    assert dep.budget.tokens_jour == 1000
    assert dep.planifications[0].cron == "0 7 * * 1-5"
    assert [o.nom for o in dep.charger_outils()][:2] == ["m9_additionner", "m9_refuser_si_negatif"]


@pytest.mark.parametrize(
    ("changements", "message"),
    [
        ({"schema": "autre"}, "schema attendu"),
        ({"id": "m09-autre"}, "différent du dossier"),
        ({"code": "M3"}, "incohérent"),
        ({"modeles": {"defaut": "geant"}}, "palier"),
        ({"mode": "libre"}, "mode de département inconnu"),
        ({"skills": ["inexistante"]}, "introuvable"),
        ({"planifications": [{"nom": "x", "cron": "tous les jours", "consigne": "y"}]}, "cron invalide"),
        ({"budget": {"tokens_jour": 10, "tokens_mois": 5}}, "tokens_mois"),
        ({"budget": {"tokens_jour": 0, "tokens_mois": 5}}, "strictement positif"),
    ],
)
def test_manifestes_invalides(racine_demo, tmp_path, changements, message):
    dossier = _copie(racine_demo, tmp_path)
    _modifier(dossier, **changements)
    with pytest.raises(ValueError, match=message):
        lire_manifeste(dossier)


def test_outil_hors_prefixe_refuse(racine_demo, tmp_path):
    dossier = _copie(racine_demo, tmp_path)
    cible = dossier.parent / "m08-demo"
    dossier.rename(cible)
    _modifier(cible, id="m08-demo", code="M8")
    dep = lire_manifeste(cible)
    with pytest.raises(ValueError, match="doit commencer par m8_"):
        dep.charger_outils()


def test_dependances_manquantes_signalees(racine_demo, tmp_path):
    dossier = _copie(racine_demo, tmp_path)
    _modifier(dossier, dependances=["m02-revenue-crm"])
    deps = charger_departements(dossier.parent)
    assert dependances_manquantes(deps) == {"m09-demo": ["m02-revenue-crm"]}


def test_index_global_des_outils(departements_demo):
    index = tous_les_outils(departements_demo.values())
    assert set(index) >= {"m9_additionner", "m9_payer"}
    assert index["m9_payer"][0].id == "m09-demo"
