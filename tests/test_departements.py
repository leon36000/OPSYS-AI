from __future__ import annotations

import dataclasses
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
    assert dep.evenements_publie == () and dep.evenements_consomme == ()  # absent du manifeste : défaut vide


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
        ({"evenements": "pas un objet"}, "evenements doit être un objet"),
        ({"evenements": {"consomme": "pas une liste"}}, "doit être une liste de chaînes"),
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


# -- evenements: {publie, consomme} (ADR-0009 §3) -----------------------------------------------
def test_manifeste_avec_evenements_valide(racine_demo, tmp_path):
    dossier = _copie(racine_demo, tmp_path)
    _modifier(dossier, evenements={"publie": ["opsys.demo_complete"], "consomme": ["m4.travaux_termines"]})
    dep = lire_manifeste(dossier)
    assert dep.evenements_publie == ("opsys.demo_complete",)
    assert dep.evenements_consomme == ("m4.travaux_termines",)


def test_charger_consommateurs_absent_rend_dict_vide(departements_demo):
    # m1_front_office.outils (département réel qui n'expose pas encore de consommateurs()) —
    # m3_estimation.outils en exposait un au moment de T1.2-a, mais plus depuis PLAN T1.2-d
    # (estimé vs réel, M3 consomme désormais m4.travaux_termines/m6.variance_chantier).
    dep = dataclasses.replace(departements_demo["m09-demo"], module_outils="m1_front_office.outils")
    assert dep.charger_consommateurs() == {}


def test_charger_consommateurs_present(departements_demo):
    dep = departements_demo["m09-demo"]  # demo_outils.consommateurs() (T1.2-a)
    fonctions = dep.charger_consommateurs()
    assert set(fonctions) == {"opsys.demo_complete"}
    assert callable(fonctions["opsys.demo_complete"])
