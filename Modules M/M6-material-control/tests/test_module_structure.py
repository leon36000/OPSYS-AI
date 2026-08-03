"""Sentinelle d'arborescence M6 — branchée à la CI AVANT la première story.

Leçon M1 (exigence unanime des reviewers, PR #88) : un module dont les tests ne
sont pas exécutés par le job gates peut merger du rouge en silence. Cette
sentinelle donne à la CI quelque chose à exécuter dès le jour zéro, impose
l'identité de paquet (chore #109) dès la naissance, et exécute le gate de
cohérence du cadrage.
"""
import subprocess
import sys
from pathlib import Path

_M6 = Path(__file__).resolve().parents[1]


def test_arborescence_module():
    """Les dossiers fondamentaux du module existent."""
    for dossier in ("src", "tests", "contracts", "docs"):
        assert (_M6 / dossier).is_dir(), f"dossier manquant : {dossier}"


def test_cadrage_bmad_present():
    """Les trois artefacts BMAD existent et ne sont pas vides."""
    for artefact in ("01-BRIEF-ANALYSTE.md", "02-PRD-PM.md", "03-ARCHITECTURE.md"):
        chemin = _M6 / "docs" / "bmad" / artefact
        assert chemin.is_file() and chemin.stat().st_size > 500, (
            f"artefact BMAD manquant ou vide : {artefact}"
        )


def test_verif_coherence_tout_vert():
    """Le gate déterministe du cadrage passe — exécuté, pas supposé."""
    resultat = subprocess.run(
        [sys.executable, str(_M6 / "docs" / "bmad" / "verif_coherence.py")],
        capture_output=True, text=True,
    )
    assert resultat.returncode == 0, (
        f"verif_coherence en écart :\n{resultat.stdout}\n{resultat.stderr}"
    )
    assert "TOUT VERT" in resultat.stdout, resultat.stdout


def test_aucun_module_a_plat_sous_src():
    """Identité de paquet dès la naissance (chore #109) : aucun .py à plat sous
    src/, exactement le paquet m6_material_control."""
    src = _M6 / "src"
    a_plat = sorted(p.name for p in src.glob("*.py"))
    assert a_plat == [], f"modules à plat sous src/ : {a_plat}"
    paquets = [d.name for d in src.iterdir()
               if d.is_dir() and (d / "__init__.py").exists()]
    assert paquets == ["m6_material_control"], (
        f"src/ doit contenir exactement le paquet m6_material_control, trouvé : {paquets}"
    )
