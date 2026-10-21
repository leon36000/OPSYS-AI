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


def test_le_paquet_source_porte_l_identite_de_paquet():
    """Garde l'identité de paquet de M3, désormais que du code source existe.

    La sentinelle précédente (test_aucun_paquet_source_avant_la_premiere_story)
    gardait l'absence de code tant que le module était CADRE ; elle a rempli son
    office quand la story M3-S001 a livré le paquet source et fait passer le
    registre à PARTIAL. La garde change d'objet, elle ne disparaît pas : ce qui
    doit tenir maintenant, c'est l'identité de paquet (décision #109). Le nom
    ``m3_estimation`` est UNIQUE au dépôt, et c'est cette identité qui empêche
    ``sys.modules`` de confondre deux modules exposant des fichiers de même nom
    — ``contrats``, ``verdicts`` et ``validation`` existent dans des modules
    voisins.

    Ce test vérifie donc que : (1) le paquet ``src/m3_estimation`` existe et
    porte un ``__init__.py`` ; (2) ce ``__init__.py`` documente la décision
    #109 et nomme l'« identité » qu'il garantit ; (3) AUCUN fichier ``.py`` ne
    se trouve directement sous ``src/`` — tout module Python doit vivre DANS le
    paquet, sinon l'identité est contournée.
    """
    paquet = _MODULE / "src" / "m3_estimation"
    init = paquet / "__init__.py"

    assert paquet.is_dir(), (
        "le paquet src/m3_estimation doit exister : la story S001 a livré du code"
    )
    assert init.is_file(), (
        "src/m3_estimation/__init__.py manquant : "
        "l'identité de paquet (#109) n'est pas portée"
    )

    contenu = init.read_text(encoding="utf-8")
    assert "#109" in contenu, (
        "le __init__.py doit mentionner la décision #109 "
        "(identité de paquet unique au dépôt)"
    )
    assert "identité" in contenu, (
        "le __init__.py doit nommer l'« identité » de paquet qu'il garantit"
    )

    src = _MODULE / "src"
    hors_paquet = list(src.glob("*.py"))
    assert hors_paquet == [], (
        "aucun fichier .py ne doit se trouver directement sous src/ : tout "
        "module doit vivre DANS le paquet m3_estimation, sinon l'identité de "
        f"paquet est contournée ({hors_paquet})"
    )
