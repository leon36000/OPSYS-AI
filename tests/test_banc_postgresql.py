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


def test_l_inventaire_des_gardes_retrouve_les_gardes_connues():
    gardes = _charger("gardes")
    inventaire = gardes.inventaire()
    fichiers = {g["fichier"] for g in inventaire}
    assert "src/opsys/service_politiques.py" in fichiers  # BACKEND_NON_SQLITE
    assert "src/opsys/liaison_cibles.py" in fichiers
    assert any(f.startswith("departments/m07-marketing/") for f in fichiers)
    assert len(inventaire) >= 80 and all(g["ligne"] > 0 and g["garde"] for g in inventaire)
    # ce qui n'est PAS une garde : les branches par dialecte qui servent les deux moteurs ne comptent pas comme refus
    assert not any(g["fichier"] == "src/opsys/connaissances/lexical.py" for g in inventaire)
    assert "| Module | Gardes |" in gardes.markdown(inventaire)


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
