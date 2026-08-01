#!/usr/bin/env python3
"""Produit un bilan rejouable des contrôles de preuve du dépôt.

Un bilan de preuves recopié dans un pack de revue n'est pas rejouable : il devient
une affirmation. À la suite d'une objection critique de revue, ce script produit
le même bilan directement depuis le dépôt et refuse de conclure lorsqu'un contrôle
n'a pas pu être exécuté.
"""

import pathlib
import shlex
import shutil
import subprocess
import sys


RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
ESTIMATION = RACINE / "Modules M" / "M3-estimation"
TESTS = ESTIMATION / "tests"
OUTILS = TESTS / "outils_preuve"
TEST_OUTILS = TESTS / "test_outils_de_preuve.py"
BMAD = ESTIMATION / "docs" / "bmad" / "verif_coherence.py"
STATUT_LINT = RACINE / "scripts" / "statut_lint.py"
STRUCTURE_LINT = RACINE / "scripts" / "structure_lint.py"
NO_STUB = pathlib.Path.home() / "proof-method" / "git-hooks" / "no_stub_ast.py"


def executable_disponible(executable):
    """Indique si un exécutable peut être lancé."""
    chemin = pathlib.Path(executable)
    if chemin.is_absolute() or chemin.parent != pathlib.Path("."):
        return chemin.is_file()
    return shutil.which(executable) is not None


def derniere_ligne_significative(sortie):
    """Extrait la dernière ligne non vide de la sortie observée."""
    lignes = [ligne.strip() for ligne in sortie.splitlines() if ligne.strip()]
    if lignes:
        return lignes[-1]
    return "<aucune ligne significative>"


def afficher_controle(nom, commande, code_retour, derniere_ligne):
    """Affiche le résultat consolidé d'un contrôle."""
    print(f"contrôle : {nom}")
    print(f"commande : {shlex.join([str(element) for element in commande])}")
    print(f"code de retour : {code_retour}")
    print(f"dernière ligne significative : {derniere_ligne}")


def executer(nom, commande, preconditions):
    """Exécute un contrôle ou produit un échec explicite s'il est indisponible."""
    indisponibles = [str(chemin) for chemin in preconditions if not chemin.exists()]
    if indisponibles:
        message = "introuvable : " + ", ".join(indisponibles)
        afficher_controle(nom, commande, "introuvable", message)
        return False, False

    executable = commande[0]
    if not executable_disponible(executable):
        message = f"exécutable introuvable : {executable}"
        afficher_controle(nom, commande, "introuvable", message)
        return False, False

    try:
        resultat = subprocess.run(
            commande,
            cwd=RACINE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        message = f"exécutable introuvable : {executable}"
        afficher_controle(nom, commande, "introuvable", message)
        return False, False
    except PermissionError:
        message = f"exécutable non lançable : {executable}"
        afficher_controle(nom, commande, "non lançable", message)
        return False, False
    except OSError as erreur:
        message = f"échec de lancement : {erreur}"
        afficher_controle(nom, commande, "non lançable", message)
        return False, False

    afficher_controle(
        nom,
        commande,
        resultat.returncode,
        derniere_ligne_significative(resultat.stdout),
    )
    return True, resultat.returncode == 0


fichiers_outils = sorted(OUTILS.rglob("*.py")) if OUTILS.is_dir() else []
cibles_no_stub = fichiers_outils + [TEST_OUTILS]

controles = [
    (
        "suite de tests du module",
        [
            "pytest",
            str(TESTS),
            "-q",
            "-p",
            "no:cacheprovider",
            "--color=no",
        ],
        [TESTS],
    ),
    (
        "gate BMAD",
        [sys.executable, str(BMAD)],
        [BMAD],
    ),
    (
        "statut lint",
        [sys.executable, str(STATUT_LINT)],
        [STATUT_LINT],
    ),
    (
        "structure lint",
        [sys.executable, str(STRUCTURE_LINT)],
        [STRUCTURE_LINT],
    ),
    (
        "garde no-stub",
        [sys.executable, str(NO_STUB)] + [str(chemin) for chemin in cibles_no_stub],
        [NO_STUB, OUTILS, TEST_OUTILS] + cibles_no_stub,
    ),
]

if not controles:
    print("ABANDON : aucun contrôle défini ; le bilan n'est pas probant.")
    sys.exit(1)

exécutés = 0
echecs = 0

for nom, commande, preconditions in controles:
    a_execute, reussi = executer(nom, commande, preconditions)
    if a_execute:
        exécutés += 1
    if not reussi:
        echecs += 1

print(f"bilan final : contrôles exécutés={exécutés}  contrôles échoués={echecs}")
sys.exit(1 if echecs else 0)
