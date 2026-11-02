"""Le banc de qualification PostgreSQL (`install/qualification/postgresql/`) : ses outils purs se testent sans Docker.

Vérifié ici : l'inventaire des gardes « SQLite seulement » retrouve des gardes connues et ne s'égare pas ; la matrice
range les fichiers par tranche et additionne sans rien inventer ; le plugiciel est INERTE sans
`OPSYS_QUALIF_PG_ADMIN_URL` (la suite ordinaire n'est jamais déviée vers PostgreSQL par accident) ; le banc liste ses
cibles comme attendu.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

FICTIF = True
DOSSIER = Path(__file__).resolve().parents[1] / "install/qualification/postgresql"


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(f"banc_pg_{nom}", DOSSIER / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_le_detecteur_de_gardes_distingue_un_refus_de_postgresql_d_une_admission_des_deux_moteurs(tmp_path):
    """Détecteur, sur des sources synthétiques (indépendant de l'état du dépôt)."""
    gardes = _charger("gardes")
    source = (
        "def refuse(cnx):\n    if cnx.dialect.name != 'sqlite':\n        raise RuntimeError('non')\n"
        "def refuse_autre(url):\n    if url.get_backend_name() not in ('sqlite',):\n        return None\n"
        "def admet(cnx):\n    if cnx.dialect.name not in ('sqlite', 'postgresql'):\n        raise RuntimeError('non')\n"
        "def elif_apres_pg(cnx):\n    if cnx.dialect.name == 'postgresql':\n        return 1\n"
        "    elif cnx.dialect.name != 'sqlite':\n        raise RuntimeError('non')\n"
        "def revisions(a_sqlite, b):\n    if a_sqlite != b:\n        raise RuntimeError('non')\n"
    )
    arbre = gardes.ast.parse(source)
    for affinee, attendu in ((False, {"refuse", "refuse_autre", "admet", "elif_apres_pg", "revisions"}),
                             (True, {"refuse", "refuse_autre"})):
        visiteur = gardes._Visiteur(DOSSIER / "synthetique.py", affinee)
        gardes.RACINE, ancien = DOSSIER, gardes.RACINE
        try:
            visiteur.visit(arbre)
        finally:
            gardes.RACINE = ancien
        assert {g["fonction"] for g in visiteur.gardes} == attendu, (affinee, visiteur.gardes)


def test_aucune_garde_sqlite_seulement_ne_s_ajoute_sans_etre_expliquee():
    """Les garde-fous se resserrent, jamais l'inverse : toute garde qui refuse PostgreSQL doit être dans
    `GARDES_RESTANTES` avec sa raison ; une raison orpheline (garde levée depuis) doit être retirée."""
    gardes = _charger("gardes")
    restantes = {gardes.cle(g) for g in gardes.inventaire()}
    assert restantes <= set(gardes.GARDES_RESTANTES), sorted(restantes - set(gardes.GARDES_RESTANTES))
    assert set(gardes.GARDES_RESTANTES) <= restantes, sorted(set(gardes.GARDES_RESTANTES) - restantes)
    assert all(len(raison) > 40 for raison in gardes.GARDES_RESTANTES.values())
    assert "| Module | Gardes |" in gardes.markdown(gardes.inventaire())


def test_chaque_garde_restante_a_une_justification_testee_qui_existe():
    """Une garde qui reste n'est « correcte par construction » que si un test sur PostgreSQL réel le prouve : chaque
    test
    nommé existe, dans un fichier qui n'est pas exclu de la CI PostgreSQL."""
    import ast

    gardes = _charger("gardes")
    racine = DOSSIER.parents[2]
    assert set(gardes.JUSTIFICATIONS_TESTEES) == set(gardes.GARDES_RESTANTES)
    ci = (racine / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for garde, preuves in gardes.JUSTIFICATIONS_TESTEES.items():
        assert preuves, garde
        for preuve in preuves:
            fichier, _, nom = preuve.partition("::")
            fonctions = {n.name for n in ast.walk(ast.parse((racine / fichier).read_text(encoding="utf-8")))
                         if isinstance(n, ast.FunctionDef)}
            assert nom in fonctions, preuve
            assert fichier in ci, f"{fichier} n'est pas dans l'étape PostgreSQL de la CI"


def test_la_regle_de_la_qualification_initiale_compte_bien_moins_de_gardes_qu_au_depart():
    """91 gardes dans 63 fichiers au commit de départ (`6c6dba4e1`) ; la même règle ne doit jamais en retrouver plus."""
    gardes = _charger("gardes")
    assert len(gardes.inventaire_ancien()) <= 91


def test_les_gardes_portees_sont_recensees_avec_un_point_de_passage():
    gardes = _charger("gardes")
    portees = gardes.portees()
    assert len(portees) >= 60 and all(p["ligne"] > 0 and p["id"] for p in portees)
    assert sum(1 for p in portees if p["passage"]) >= 20  # la plupart ont une ligne de passage, les autres un retour
    assert any(p["fichier"] == "src/opsys/liaison_cibles.py" for p in portees)


def test_la_matrice_range_les_fichiers_par_tranche():
    matrice = _charger("matrice")
    assert matrice.tranche("tests/test_connaissances_pipeline.py") == "Connaissances M10 (0041)"
    assert matrice.tranche("tests/test_mnemo_graphe.py") == "Graphe M10 (0052)"
    assert matrice.tranche("departments/m05-financecore/tests/test_x.py") == "M5 financecore"
    assert matrice.tranche("tests/e2e/test_m5_envoi_facture_concurrent.py") == "E2E concurrence"


def _dossier_fictif(tmp_path: Path, nom: str, fichiers: dict[str, tuple[int, str, list[dict]]]) -> Path:
    dossier = tmp_path / nom
    dossier.mkdir()
    resume = []
    for cible, (code, ligne, jsonl) in fichiers.items():
        resume.append({"cible": cible, "code": code, "duree_s": 1.0, "derniere_ligne": ligne, "journal": "x"})
        if jsonl:
            slug = cible.replace("/", "_")
            (dossier / f"{slug}.jsonl").write_text("\n".join(json.dumps(x) for x in jsonl), encoding="utf-8")
    (dossier / "resume.json").write_text(json.dumps(resume), encoding="utf-8")
    return dossier


def test_la_matrice_additionne_sans_rien_inventer(tmp_path):
    matrice = _charger("matrice")
    cible = "tests/test_connaissances_pipeline.py"
    jsonl = [{"nodeid": cible + "::a", "phase": "call", "issue": "passed", "ordres_pg": 4},
             {"nodeid": cible + "::b", "phase": "call", "issue": "failed", "ordres_pg": 2},
             {"nodeid": cible + "::c", "phase": "call", "issue": "passed", "ordres_pg": 0}]
    pg = _dossier_fictif(tmp_path, "pg", {cible: (1, "", jsonl)})
    sqlite = _dossier_fictif(tmp_path, "sq", {cible: (0, "3 passed, 1 skipped in 2s", [])})
    [ligne] = matrice.matrice(pg, sqlite)
    assert ligne["tranche"] == "Connaissances M10 (0041)" and ligne["fichiers"] == 1
    assert (ligne["pg_passed"], ligne["pg_failed"], ligne["pg_touchent_pg"], ligne["pg_rapportes"]) == (2, 1, 2, 3)
    assert (ligne["sqlite_passed"], ligne["sqlite_skipped"]) == (3, 1)
    assert "| **Total** |" in matrice.markdown([ligne])


def test_une_garde_restante_n_est_prouvee_que_par_des_tests_reussis_avec_du_sql_postgresql(tmp_path):
    matrice = _charger("matrice")
    dossier = tmp_path / "pg"
    dossier.mkdir()
    lignes = [
        {"nodeid": "tests/t.py::test_x", "phase": "call", "issue": "passed", "ordres_pg": 3},
        {"nodeid": "tests/t.py::test_y[postgresql]", "phase": "call", "issue": "passed", "ordres_pg": 0},  # sans SQL PG
        {"nodeid": "tests/t.py::test_z", "phase": "call", "issue": "failed", "ordres_pg": 5},  # rouge
    ]
    (dossier / "t.jsonl").write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
    justifications = {"a.py::f": ("tests/t.py::test_x",), "b.py::g": ("tests/t.py::test_x", "tests/t.py::test_y"),
                      "c.py::h": ("tests/t.py::test_z",)}
    preuves = {p["garde"]: p["prouvee"] for p in matrice.preuves_justifications([dossier], justifications)}
    assert preuves == {"a.py::f": True, "b.py::g": False, "c.py::h": False}
    assert "NON PROUVÉE" in matrice.markdown_justifications(matrice.preuves_justifications([dossier], justifications))


def test_le_plugiciel_est_inerte_sans_url_d_administration(monkeypatch):
    with monkeypatch.context() as m:  # variable restaurée aussitôt : le banc lui-même en a besoin en fin de test
        m.delenv("OPSYS_QUALIF_PG_ADMIN_URL", raising=False)
        plugin = _charger("plugin_pg")
    assert plugin._ACTIF is False  # aucune fixture ne dévie la suite vers PostgreSQL


@pytest.mark.parametrize("racine", ["tests", "departments"])
def test_le_banc_liste_ses_cibles_par_fichier(racine):
    banc = _charger("banc")
    cibles = banc._cibles([racine])
    assert len(cibles) > 50 and all(c.endswith(".py") and "/test_" in c for c in cibles)
    if racine == "tests":
        assert "tests/test_stockage.py" in cibles and any(c.startswith("tests/e2e/") for c in cibles)
    else:
        assert any(c.startswith("departments/m05-financecore/tests/") for c in cibles)
