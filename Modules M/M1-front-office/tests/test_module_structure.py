import sys
import pytest
from pathlib import Path

_NOM_PAQUET = "m1_front_office"

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

def test_aucun_module_a_plat_sous_src():
    """PROUVE structurellement qu'aucun fichier .py ne subsiste À PLAT sous src/.

    L'identité de paquet ne protège que ce qui est DANS le paquet. Un nouveau
    module déposé directement sous src/ et importé à plat depuis un test
    rouvrirait exactement la collision que le chore #109 a fermée : sys.modules
    conserverait le premier arbre chargé et l'appartenance redeviendrait
    fonction de l'ordre de collecte.

    Ce contrôle est STRUCTUREL et non comportemental, à dessein : un fichier à
    plat que personne n'importe encore est inerte, donc invisible pour un test
    qui n'observe que les modules chargés — vérifié par mutation (copier un
    module à plat ne faisait rougir aucun test avant l'ajout de celui-ci).
    """
    src = _M1 / "src"
    a_plat = sorted(chemin.name for chemin in src.glob("*.py"))
    assert a_plat == [], (
        f"modules à plat sous src/ : {a_plat}. Ils doivent vivre dans le paquet "
        "src/m1_front_office/ pour que leur nom soit unique au dépôt."
    )
    paquets = [d.name for d in src.iterdir()
               if d.is_dir() and (d / "__init__.py").exists()]
    assert paquets == ["m1_front_office"], (
        f"src/ doit contenir exactement le paquet m1_front_office, trouvé : {paquets}"
    )

def test_aucun_sys_path_insert_vise_le_paquet():
    """PROUVE qu'aucun fichier de test n'insère le PAQUET dans sys.path.

    Deux chemins, deux rôles, et les confondre casse l'un des deux : sys.path
    doit recevoir src/ — le PARENT du paquet — car c'est lui qui rend
    « from PAQUET import ... » résoluble ; le paquet lui-même ne sert qu'à
    SCANNER les sources.

    Défaut réel trouvé par la revue scellée (chore #109, round 2) : un fichier
    insérait le paquet et échouait EXÉCUTÉ SEUL, tout en passant dans la suite
    complète parce qu'un autre fichier avait inséré src/ avant lui — une
    dépendance à l'ordre de collecte, précisément ce que la mise en paquet doit
    supprimer. Le contrôle est STATIQUE parce qu'un tel défaut est invisible en
    exécution groupée.
    """
    tests_dir = Path(__file__).resolve().parent
    fautifs = []
    for fichier in sorted(tests_dir.glob("*.py")):
        for numero, ligne in enumerate(
            fichier.read_text(encoding="utf-8").splitlines(), 1
        ):
            depouillee = ligne.strip()
            if not depouillee.startswith("sys.path.insert"):
                continue
            if _NOM_PAQUET in depouillee:
                fautifs.append(f"{fichier.name}:{numero}: {depouillee}")
    assert not fautifs, (
        "sys.path.insert visant le paquet au lieu de son parent :\n  "
        + "\n  ".join(fautifs)
    )
