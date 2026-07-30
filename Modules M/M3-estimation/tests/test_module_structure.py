"""Sentinelle d'arborescence et de cadrage du module M3 — branchée AVANT la première story.

Leçon M1 puis M4 : une CI branchée après coup laisse passer des stories non
gardées. Ce fichier existe donc dès le cadrage, et il EXÉCUTE le gate de
cohérence des artefacts BMAD plutôt que de se contenter de constater sa
présence — un gate présent mais jamais lancé ne prouve rien.
"""
import subprocess
import sys
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[1]
_BMAD = _MODULE / "docs" / "bmad"


def test_arborescence_minimale_du_module():
    assert (_MODULE / "README.md").is_file()
    assert _BMAD.is_dir(), "le cadrage BMAD doit précéder la première story"


def test_les_trois_artefacts_bmad_sont_presents_et_non_vides():
    for nom in ("01-BRIEF-ANALYSTE.md", "02-PRD-PM.md", "03-ARCHITECTURE.md"):
        chemin = _BMAD / nom
        assert chemin.is_file(), f"artefact BMAD manquant : {nom}"
        assert len(chemin.read_text(encoding="utf-8")) > 1000, f"artefact trop court : {nom}"


def test_le_gate_de_coherence_bmad_est_execute_et_vert():
    """EXÉCUTE le gate : constater sa présence ne prouve pas qu'il passe."""
    resultat = subprocess.run(
        [sys.executable, str(_BMAD / "verif_coherence.py")],
        capture_output=True, text=True, timeout=120,
    )
    assert resultat.returncode == 0, (
        f"le gate de cohérence BMAD échoue :\n{resultat.stdout}\n{resultat.stderr}"
    )
    assert "TOUT VERT" in resultat.stdout


def test_aucun_paquet_source_avant_la_premiere_story():
    """M3 est déclaré CADRE au registre : cadré et gardé, mais sans code encore.

    Ce test a lui-même RÉVÉLÉ le statut manquant. La gate statut_lint (#152)
    exigeait qu'un STUB ne porte ni module source ni test — or ce fichier EST un
    test, et le brancher avant la première story est la pratique prouvée (leçon
    M1 puis M4). Le seul choix était de mentir en STUB ou de relâcher la règle :
    un statut manquant force le mensonge. D'où CADRE, qui exige exactement cet
    état — zéro module source ET au moins un fichier de test.

    Ce test sera retiré par la première story qui livrera du code, en même temps
    que le passage du registre à PARTIAL.
    """
    src = _MODULE / "src"
    modules = [p for p in src.rglob("*.py") if p.name != "__init__.py"] if src.exists() else []
    assert modules == [], f"du code source existe : le registre doit passer à PARTIAL ({modules})"
