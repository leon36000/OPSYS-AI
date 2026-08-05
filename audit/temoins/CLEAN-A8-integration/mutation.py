#!/usr/bin/env python3
"""Zone déclarée PROPRE — l'intégration entre modules, et pourquoi elle n'a pas de surface.

Le lot A8 a été ouvert par le round adverse : six modèles sur onze, indépendamment, ont
nommé le même angle mort — « les sondes lisent des fichiers isolément, donc un défaut qui
n'existe qu'à la jonction de deux modules est structurellement invisible ».

La mesure donne un résultat que personne n'avait prévu : **il n'y a aucune jonction**.
Zéro import entre les 22 paquets des dix modules. L'angle mort est réel en principe, et
sans objet dans ce dépôt aujourd'hui — non parce qu'on aurait bien intégré, mais parce
qu'on n'a pas intégré du tout.

Ce fichier prouve que la mesure aurait vu une jonction si elle existait : il en injecte
une dans une copie jetable et exige qu'elle soit détectée. Sans cette preuve, « zéro
import trouvé » serait indistinguable d'un détecteur cassé.

L'écart au plan qui en découle — D-010 prévoit des API de domaine entre modules — est
porté par le constat AUD-A3-002, non ici : une sonde mesure, elle ne conclut pas.

Sort en code non nul si l'injection n'est pas détectée.
"""
import ast
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

RACINE = pathlib.Path(__file__).resolve().parents[3]


def _paquets_par_module(fichiers: list[str]) -> dict[str, str]:
    """Nom de paquet -> module qui le porte. Un import de ce nom depuis un autre
    module est un import inter-modules."""
    paquets = {}
    for relatif in fichiers:
        trouve = re.match(r"Modules M/(M\d+)-[^/]+/src/([^/]+)/", relatif)
        if trouve:
            paquets.setdefault(trouve.group(2), trouve.group(1))
    return paquets


def _compter_imports_croises(racine: pathlib.Path, fichiers: list[str]) -> list[tuple[str, str, str]]:
    paquets = _paquets_par_module(fichiers)
    croises = []
    for relatif in fichiers:
        trouve = re.match(r"Modules M/(M\d+)-", relatif)
        if not trouve:
            continue
        mien = trouve.group(1)
        try:
            arbre = ast.parse((racine / relatif).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for noeud in ast.walk(arbre):
            noms = []
            if isinstance(noeud, ast.Import):
                noms = [alias.name for alias in noeud.names]
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                noms = [noeud.module]
            for nom in noms:
                racine_nom = nom.split(".")[0]
                if racine_nom in paquets and paquets[racine_nom] != mien:
                    croises.append((mien, paquets[racine_nom], relatif))
    return croises


def _fichiers(racine: pathlib.Path) -> list[str]:
    sortie = subprocess.run(
        ["git", "ls-files", "-z"], cwd=racine, capture_output=True, text=True, check=True
    ).stdout
    return [
        c for c in sortie.split("\0")
        if c.endswith(".py") and c.startswith("Modules M/") and "/src/" in c
    ]


def main() -> int:
    fichiers = _fichiers(RACINE)
    if not fichiers:
        print("MESURE IMPOSSIBLE : aucun fichier source de module", file=sys.stderr)
        return 2

    reels = _compter_imports_croises(RACINE, fichiers)
    paquets = _paquets_par_module(fichiers)

    print(f"paquets de module : {len(paquets)}")
    print(f"fichiers source analysés : {len(fichiers)}")
    print(f"imports inter-modules RÉELS : {len(reels)}\n")
    for mien, autre, relatif in reels[:10]:
        print(f"  {mien} -> {autre}  ({relatif})")

    # Preuve de morsure : on injecte une jonction et l'on exige de la voir.
    with tempfile.TemporaryDirectory(prefix="clean-a8-") as tmp:
        copie = pathlib.Path(tmp) / "repo"
        shutil.copytree(RACINE / "Modules M", copie / "Modules M")
        subprocess.run(["git", "init", "-q"], cwd=copie, check=True)
        subprocess.run(["git", "add", "-A"], cwd=copie, check=True)

        fichiers_copie = _fichiers(copie)
        paquets_copie = _paquets_par_module(fichiers_copie)

        # Choisir deux modules distincts et faire importer l'un par l'autre.
        par_module = {}
        for nom_paquet, module in paquets_copie.items():
            par_module.setdefault(module, nom_paquet)
        modules = sorted(par_module)
        if len(modules) < 2:
            print("MUTATION IMPOSSIBLE : moins de deux modules", file=sys.stderr)
            return 2

        source_module, cible_module = modules[0], modules[1]
        paquet_cible = par_module[cible_module]
        victime = next(
            f for f in fichiers_copie if f.startswith(f"Modules M/{source_module}-")
        )
        chemin_victime = copie / victime
        original = chemin_victime.read_text(encoding="utf-8")
        chemin_victime.write_text(
            f"import {paquet_cible}  # jonction injectée par la batterie\n" + original,
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=copie, check=True)

        apres = _compter_imports_croises(copie, _fichiers(copie))

    print()
    if len(apres) <= len(reels):
        print(f"CELLULE NON PROUVÉE : la jonction injectée "
              f"({source_module} -> {cible_module}) n'a pas été vue")
        return 1

    print(f"MORSURE PROUVÉE : la jonction injectée {source_module} -> {cible_module} "
          f"est détectée ({len(apres)} imports croisés contre {len(reels)})")
    print()
    if reels:
        print(f"CONSTAT : {len(reels)} import(s) inter-modules à examiner.")
        return 1

    print("CELLULE (A8 × intégration) PROUVÉE PROPRE — et le résultat mérite d'être lu :")
    print("  - zéro import entre les paquets des dix modules ;")
    print("  - la mesure détecte une jonction quand on en injecte une.")
    print()
    print("L'angle mort nommé par six modèles est donc réel en principe et SANS OBJET dans")
    print("ce dépôt aujourd'hui — non parce que l'intégration serait bien faite, mais parce")
    print("qu'il n'y en a aucune. L'écart au plan que cela révèle (D-010 prévoit des API de")
    print("domaine entre modules) est porté par le constat AUD-A3-002, pas par cette sonde :")
    print("une sonde mesure, elle ne conclut pas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
