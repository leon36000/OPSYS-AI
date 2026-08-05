#!/usr/bin/env python3
"""Témoin RED — AUD-A4-002 : le code de production dépend d'une bibliothèque tierce.

Le dépôt s'impose la bibliothèque standard seule en production. C'est une contrainte
structurante : elle rend le produit déployable partout sans gestionnaire de paquets, et
c'est à ce titre qu'elle est répétée dans les cadrages de chaque module.

Le témoin analyse les imports du code de production — sous `src/`, hors tests — et
confronte chaque module de premier niveau à `sys.stdlib_module_names` et aux modules du
dépôt lui-même. Ce qui reste est tiers.

L'analyse est syntaxique : une recherche textuelle confondrait le mot dans un commentaire
ou une chaîne avec un import réel.

Code retour : 1 si un import tiers subsiste, 0 sinon, 2 si la mesure est impossible.
"""
import ast
import pathlib
import subprocess
import sys
from collections import defaultdict

RACINE = pathlib.Path(__file__).resolve().parents[3]


def _fichiers_python() -> list[str]:
    """Chemins NUL-terminés : « Modules M/ » contient une espace."""
    sortie = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, text=True, check=True
    ).stdout
    return [c for c in sortie.split("\0") if c.endswith(".py")]


def _est_production(relatif: str) -> bool:
    """Production = sous src/, hors tests. Un import tiers dans un test ne livre rien."""
    nom = pathlib.Path(relatif).name
    return "/src/" in relatif and "/tests/" not in relatif and not nom.startswith("test_")


def main() -> int:
    fichiers = _fichiers_python()
    if not fichiers:
        print("TÉMOIN INAPPLICABLE : aucun fichier Python suivi", file=sys.stderr)
        return 2

    # Les noms du dépôt lui-même ne sont pas des dépendances tierces : un module qui
    # importe son voisin par un chemin ajouté à sys.path resterait sinon compté à tort.
    locaux = set()
    for relatif in fichiers:
        chemin = pathlib.Path(relatif)
        locaux.add(chemin.stem)
        for partie in chemin.parts[:-1]:
            locaux.add(partie.replace("-", "_"))

    standard = set(sys.stdlib_module_names)
    tiers: dict[str, set[str]] = defaultdict(set)

    for relatif in fichiers:
        if not _est_production(relatif):
            continue
        try:
            arbre = ast.parse((RACINE / relatif).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            # Un fichier illisible est une anomalie distincte, traitée par la sonde A1.
            continue
        for noeud in ast.walk(arbre):
            noms = []
            if isinstance(noeud, ast.Import):
                noms = [alias.name for alias in noeud.names]
            elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
                noms = [noeud.module]
            for nom in noms:
                racine = nom.split(".")[0]
                if racine not in standard and racine not in locaux:
                    tiers[racine].add(relatif)

    production = [f for f in fichiers if _est_production(f)]
    print(f"fichiers de production analysés : {len(production)}")
    print(f"imports hors bibliothèque standard et hors dépôt : {len(tiers)}\n")

    for racine, concernes in sorted(tiers.items()):
        print(f"  « {racine} » — {len(concernes)} fichier(s) de production")
        for relatif in sorted(concernes)[:6]:
            print(f"     {relatif}")
        if len(concernes) > 6:
            print(f"     … et {len(concernes) - 6} autre(s)")

    print()
    if not tiers:
        print("CONSTAT NON REPRODUIT : la production n'importe que la bibliothèque standard.")
        print("AUD-A4-002 est périmé et doit être retiré du rapport.")
        return 0

    total = sum(len(c) for c in tiers.values())
    print(f"CONSTAT AUD-A4-002 CONFIRMÉ — {len(tiers)} dépendance(s) tierce(s) "
          f"dans {total} fichier(s) de production.")
    print()
    print("Ce que le témoin N'AFFIRME PAS : que ces imports soient injustifiés — analyser")
    print("du YAML sans bibliothèque demande d'en écrire une. Il établit que la contrainte")
    print("« bibliothèque standard uniquement », répétée dans les cadrages de module, n'est")
    print("pas tenue par le code livré, et qu'aucun gate ne le signale.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
