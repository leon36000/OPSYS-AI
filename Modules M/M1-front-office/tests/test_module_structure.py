import pytest
from pathlib import Path

_M1 = Path(__file__).resolve().parents[1]


def test_arborescence_module():
    """Vérifie la présence des dossiers fondamentaux du module M1."""
    dossiers_requis = ["src", "tests", "contracts", "docs"]
    for dossier in dossiers_requis:
        chemin = _M1 / dossier
        assert chemin.is_dir(), f"Dossier manquant : {dossier} (attendu dans {_M1})"


def test_cadrage_bmad_present():
    """Vérifie que les trois artefacts de cadrage BMAD existent et contiennent un minimum de contenu."""
    artefacts = [
        "docs/bmad/01-BRIEF-ANALYSTE.md",
        "docs/bmad/02-PRD-PM.md",
        "docs/bmad/03-ARCHITECTURE.md",
    ]
    for artefact in artefacts:
        chemin = _M1 / artefact
        assert chemin.is_file(), f"Artefact BMAD absent : {artefact}"
        taille = chemin.stat().st_size
        assert taille > 500, (
            f"Artefact {artefact} trop léger ({taille} octets). "
            "Minimum 500 octets attendu pour un contenu significatif."
        )


def test_readme_present():
    """Vérifie la présence du README.md à la racine du module."""
    readme = _M1 / "README.md"
    assert readme.is_file(), "README.md introuvable à la racine du module"
