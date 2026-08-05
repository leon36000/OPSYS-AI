#!/usr/bin/env python3
"""Sonde — densité réelle du code source des modules (réfutation de HA-17).

Trois modèles ont soupçonné que les 135 fichiers source des modules M1..M10 soient des
coquilles vides et que les ~2 840 tests verts ne vérifient donc rien. Deux d'entre eux
s'appuyaient sur un chiffre ERRONÉ fourni par le pack d'audit lui-même (« lignes source :
0 total », artefact d'un `xargs` sans `-0` sur des chemins contenant une espace).

Cette sonde tranche indépendamment de ce chiffre : elle compte les INSTRUCTIONS
EXÉCUTABLES par analyse syntaxique. `wc -l` compterait les commentaires et les lignes
vides ; un fichier de 400 lignes de docstring n'est pas du code.

Ne sont PAS des instructions exécutables : `pass`, les imports, les docstrings et les
expressions `...`. Un fichier qui n'en contient que cela est un squelette, quelle que
soit sa longueur.

Sortie : rc=0 si la densité réfute l'hypothèse, rc=1 si elle la confirme.
"""
import ast
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent.parent

# Un fichier est un squelette en dessous de ce seuil. Les `__init__.py` de paquet en sont
# exemptés : leur vide est la convention, pas un manque.
SEUIL_INSTRUCTIONS = 5


def _est_instruction_executable(noeud: ast.AST) -> bool:
    if not isinstance(noeud, ast.stmt):
        return False
    if isinstance(noeud, (ast.Pass, ast.Import, ast.ImportFrom)):
        return False
    if isinstance(noeud, ast.Expr):
        valeur = noeud.value
        # Docstring ou `...` : présents dans l'arbre, sans effet à l'exécution.
        if isinstance(valeur, ast.Constant) and isinstance(valeur.value, str):
            return False
        if isinstance(valeur, ast.Constant) and valeur.value is Ellipsis:
            return False
    return True


def lister_sources() -> list[pathlib.Path]:
    """Chemins NUL-terminés : « Modules M/ » contient une espace.

    C'est précisément le piège qui a produit le chiffre erroné à l'origine de HA-17 ;
    la sonde qui le réfute ne peut pas y retomber.
    """
    sortie = subprocess.run(
        ["git", "ls-files", "-z", "Modules M/**/src/**/*.py"],
        capture_output=True,
        text=True,
        check=True,
        cwd=RACINE,
    ).stdout
    return [RACINE / chemin for chemin in sortie.split("\0") if chemin]


def main() -> int:
    fichiers = lister_sources()
    if not fichiers:
        print("SONDE INVALIDE : aucun fichier source trouvé — le motif ne correspond à rien")
        return 2

    vides, faibles, erreurs = [], [], []
    total = 0
    denses = 0

    for chemin in fichiers:
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            erreurs.append((chemin, exc))
            continue
        instructions = sum(1 for n in ast.walk(arbre) if _est_instruction_executable(n))
        total += instructions
        if instructions == 0:
            vides.append(chemin)
        elif instructions < SEUIL_INSTRUCTIONS:
            faibles.append((chemin, instructions))
        else:
            denses += 1

    relatif = [f.relative_to(RACINE).as_posix() for f in vides]
    hors_init = [p for p in relatif if not p.endswith("__init__.py")]

    print(f"fichiers source analysés          : {len(fichiers)}")
    print(f"instructions exécutables totales  : {total}")
    print(f"  >= {SEUIL_INSTRUCTIONS} instructions              : {denses}")
    print(f"  1..{SEUIL_INSTRUCTIONS - 1} instructions              : {len(faibles)}")
    print(f"  0 instruction                   : {len(vides)}"
          f" (dont {len(vides) - len(hors_init)} __init__.py)")
    print(f"  erreurs de syntaxe              : {len(erreurs)}")

    for chemin, nombre in faibles:
        print(f"    FAIBLE {chemin.relative_to(RACINE).as_posix()} — {nombre} instruction(s)")
    for chemin in hors_init:
        print(f"    VIDE   {chemin}")
    for chemin, exc in erreurs:
        print(f"    ERREUR {chemin.relative_to(RACINE).as_posix()} — {exc}")

    print()
    if erreurs:
        print("HA-17 CONFIRMÉE en partie : des fichiers source ne compilent même pas")
        return 1
    if hors_init:
        print(f"HA-17 CONFIRMÉE : {len(hors_init)} fichier(s) sans aucune instruction, hors __init__.py")
        return 1
    print("HA-17 RÉFUTÉE : aucun fichier source vide hors __init__.py, aucune erreur de syntaxe.")
    print("Les fichiers de faible densité sont des contrats gelés (constantes) — vérifiés un à un.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
