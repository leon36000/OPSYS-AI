"""La CI teste chaque département : la matrice du job `departement` de `.github/workflows/ci.yml`
doit nommer exactement les dossiers de `departments/`. Un département ajouté sans entrée dans la
matrice ne serait jamais testé par la CI."""

from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]


def test_la_matrice_ci_couvre_exactement_les_departements():
    ci = yaml.safe_load((RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    matrice = ci["jobs"]["departement"]["strategy"]["matrix"]["dossier"]
    dossiers = sorted(p.name for p in (RACINE / "departments").iterdir() if (p / "department.yaml").is_file())
    assert sorted(matrice) == dossiers
    assert len(matrice) == len(set(matrice))


def test_gates_exige_le_succes_de_chaque_job_requis():
    ci = yaml.safe_load((RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    gates = ci["jobs"]["gates"]
    assert set(gates["needs"]) == {"socle", "departement"}
    assert gates["if"] == "always()"
    commandes = "\n".join(etape.get("run", "") for etape in gates["steps"])
    for job in gates["needs"]:
        assert f'needs.{job}.result }}}}" = "success"' in commandes
