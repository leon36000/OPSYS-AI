"""Garde des matrices d'exigences M1-M8 et M10 (docs/reprise/MATRICES-20261031).

Une matrice n'est utile que si elle ne ment pas : ce test ne juge pas le métier, il refuse les
dérives mécaniques qui rendraient une matrice invérifiable.

- chaque matrice est un JSON valide du schéma de la matrice M9 (champs, vocabulaire de statuts) ;
- chaque chemin cité en preuve ou en lecture existe dans le dépôt (aucun chemin inventé) ;
- aucun statut FAIT_PROUVE sans au moins un test existant cité (« CI verte » n'est pas une preuve) ;
- aucun statut FAIT_PROUVE sans limite écrite (le périmètre prouvé est toujours dit) ;
- aucun identifiant en double ; le préfixe des identifiants suit le module du fichier ;
- le tableau de synthèse du README reprend exactement les comptes des matrices.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "docs" / "reprise" / "MATRICES-20261031"
MODULES = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M10")
STATUTS = ("FAIT_PROUVE", "PARTIEL", "SIMULE", "ABSENT", "INCONNU")
CHAMPS_REQUIS = (
    "id", "title", "target", "acceptance", "reuse_read_first", "initial_status",
    "gates_to_resolve_or_keep_open", "decisions_nathan", "proofs", "verified_commit",
    "current_status", "limite",
)
CHAMPS_MATRICE = (
    "schema", "mission", "module", "scope_preserved", "canonical_source", "base_sha", "date",
    "statuses", "proof_levels", "run_summary", "requirements",
)


def _chemin(module: str) -> Path:
    return DOSSIER / f"MATRICE-EXIGENCES-{module}.json"


def _charger(module: str) -> dict:
    return json.loads(_chemin(module).read_text(encoding="utf-8"))


def _chemins_cites(exigence: dict) -> list[str]:
    cites = list(exigence["reuse_read_first"])
    for preuve in exigence["proofs"]:
        cites += preuve.get("tests", []) + preuve.get("docs", [])
    return cites


def test_les_neuf_matrices_sont_presentes_et_seules():
    presentes = sorted(p.name for p in DOSSIER.glob("MATRICE-EXIGENCES-*.json"))
    assert presentes == sorted(f"MATRICE-EXIGENCES-{m}.json" for m in MODULES)


@pytest.mark.parametrize("module", MODULES)
def test_la_matrice_est_un_json_valide_du_schema_m9(module):
    matrice = _charger(module)
    assert set(CHAMPS_MATRICE) <= set(matrice), sorted(set(CHAMPS_MATRICE) - set(matrice))
    assert matrice["schema"] == "opsys.mission.requirements.v1"
    assert matrice["module"] == module
    assert matrice["mission"] == f"MATRICE-EXIGENCES-{module}"
    assert tuple(matrice["statuses"]) == STATUTS
    assert re.fullmatch(r"[0-9a-f]{40}", matrice["base_sha"])
    assert matrice["requirements"], "une matrice sans exigence ne prouve rien"
    for exigence in matrice["requirements"]:
        manquants = [c for c in CHAMPS_REQUIS if c not in exigence]
        assert not manquants, (exigence.get("id"), manquants)
        for champ in ("id", "title", "target", "limite", "verified_commit"):
            assert isinstance(exigence[champ], str) and exigence[champ].strip(), (exigence["id"], champ)
        for champ in ("reuse_read_first", "gates_to_resolve_or_keep_open", "decisions_nathan", "proofs"):
            assert isinstance(exigence[champ], list), (exigence["id"], champ)
        for preuve in exigence["proofs"]:
            assert isinstance(preuve.get("tests", []), list)
            assert isinstance(preuve.get("docs", []), list)
            assert preuve.get("niveau", "").strip(), (exigence["id"], "niveau de preuve")


@pytest.mark.parametrize("module", MODULES)
def test_les_statuts_sont_dans_le_vocabulaire(module):
    for exigence in _charger(module)["requirements"]:
        assert exigence["current_status"] in STATUTS, (exigence["id"], exigence["current_status"])
        assert exigence["initial_status"] in STATUTS, (exigence["id"], exigence["initial_status"])


@pytest.mark.parametrize("module", MODULES)
def test_aucun_identifiant_en_double_et_prefixe_du_module(module):
    identifiants = [e["id"] for e in _charger(module)["requirements"]]
    assert len(identifiants) == len(set(identifiants)), [i for i, n in Counter(identifiants).items() if n > 1]
    for identifiant in identifiants:
        assert re.fullmatch(rf"{module}\.\d+(–{module}\.\d+)?", identifiant), identifiant


@pytest.mark.parametrize("module", MODULES)
def test_chaque_chemin_de_preuve_existe_dans_le_depot(module):
    inexistants = []
    for exigence in _charger(module)["requirements"]:
        for chemin in _chemins_cites(exigence):
            assert not chemin.startswith("/") and ".." not in Path(chemin).parts, chemin
            if not (RACINE / chemin).is_file():
                inexistants.append((exigence["id"], chemin))
    assert not inexistants, inexistants


@pytest.mark.parametrize("module", MODULES)
def test_un_fait_prouve_cite_au_moins_un_test_existant(module):
    for exigence in _charger(module)["requirements"]:
        if exigence["current_status"] != "FAIT_PROUVE":
            continue
        tests = [t for preuve in exigence["proofs"] for t in preuve.get("tests", [])]
        assert tests, f"{exigence['id']} : FAIT_PROUVE sans test cité"
        assert all((RACINE / t).is_file() for t in tests), exigence["id"]
        assert exigence["limite"].strip(), f"{exigence['id']} : FAIT_PROUVE sans périmètre dit"


@pytest.mark.parametrize("module", MODULES)
def test_un_statut_absent_ne_cite_aucun_test(module):
    """Une capacité ABSENTE n'a pas de test qui la prouve : un test cité contredirait le statut."""
    for exigence in _charger(module)["requirements"]:
        if exigence["current_status"] == "ABSENT":
            tests = [t for preuve in exigence["proofs"] for t in preuve.get("tests", [])]
            assert not tests, (exigence["id"], tests)


def test_le_tableau_de_synthese_du_readme_reprend_les_comptes_des_matrices():
    readme = (DOSSIER / "README.md").read_text(encoding="utf-8")
    for module in MODULES:
        comptes = Counter(e["current_status"] for e in _charger(module)["requirements"])
        attendu = [sum(comptes.values())] + [comptes.get(s, 0) for s in STATUTS]
        ligne = next(
            (m for m in re.findall(rf"^\| {module} \|(.*)$", readme, flags=re.M)), None
        )
        assert ligne is not None, f"README : pas de ligne de synthèse pour {module}"
        cellules = [c.strip() for c in ligne.split("|")]
        nombres = [int(c) for c in cellules[:6]]
        assert nombres == attendu, (module, nombres, attendu)
    for module in MODULES:
        assert _chemin(module).name in readme, f"README : {_chemin(module).name} n'est pas listé"
