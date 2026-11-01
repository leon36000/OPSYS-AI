#!/usr/bin/env python3
"""Inventaire exécutable des « tours » et de leur état de branchement au planificateur durable.

    python scripts/planification/inventaire_tours.py              # tableau lisible
    python scripts/planification/inventaire_tours.py --json       # le même, en JSON
    python scripts/planification/inventaire_tours.py --verifier   # contrôles (code de sortie 1 au moindre écart)

Les données vivent dans `opsys.connecteurs_planification.inventaire` (source unique, relue par les tests). Les
fonctions citées sont cherchées dans leur fichier par lecture de l'arbre syntaxique : le code des départements n'est
PAS importé et rien n'est exécuté (aucun accès réseau, aucune base).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "src"))

from opsys.connecteurs_planification import etat, inventaire  # noqa: E402


def fonctions_du_module(chemin: Path) -> set[str]:
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(arbre) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def verifier(racine: Path = RACINE) -> list[str]:
    """Les écarts entre l'inventaire, le code et les exécuteurs déclarés (liste vide = cohérent)."""
    problemes: list[str] = []
    cache: dict[str, set[str]] = {}

    def existe(module: str, fonction: str) -> bool:
        chemin = racine / module
        if not chemin.is_file():
            return False
        if module not in cache:
            cache[module] = fonctions_du_module(chemin)
        return fonction in cache[module]

    vus: set[str] = set()
    for t in inventaire.TOURS:
        if t.identifiant in vus:
            problemes.append(f"{t.identifiant} : identifiant en double")
        vus.add(t.identifiant)
        if not existe(t.module, t.fonction):
            problemes.append(f"{t.identifiant} : {t.module}:{t.fonction} introuvable")
        if t.decision not in inventaire.DECISIONS:
            problemes.append(f"{t.identifiant} : décision inconnue {t.decision!r}")
        if t.transport not in inventaire.TRANSPORTS:
            problemes.append(f"{t.identifiant} : transport inconnu {t.transport!r}")
        if not t.justification.strip() or not t.idempotent.strip():
            problemes.append(f"{t.identifiant} : justification et idempotence obligatoires")
        branche = t.decision in ("deja_branche", "brancher_maintenant")
        if branche and t.executeur is None:
            problemes.append(f"{t.identifiant} : décision « {t.decision} » sans exécuteur")
        if not branche and t.executeur is not None:
            problemes.append(f"{t.identifiant} : exécuteur nommé pour une décision « {t.decision} »")
        if t.executeur not in (None, "entrypoint.sh") and t.executeur not in etat.NOMS:
            problemes.append(f"{t.identifiant} : exécuteur {t.executeur!r} inconnu du planificateur")
        if t.n3_ou_plus and branche and not any(m in t.niveau for m in ("approbation", "humain")):
            problemes.append(f"{t.identifiant} : niveau {t.niveau!r} branché sans approbation humaine")
    for nom in etat.NOMS:
        if not any(t.executeur == nom for t in inventaire.TOURS):
            problemes.append(f"exécuteur {nom} : aucun tour de l'inventaire ne le justifie")
    for libelle, module, fonction in inventaire.EVALUATIONS_A_LA_LECTURE:
        if not existe(module, fonction):
            problemes.append(f"évaluation « {libelle} » : {module}:{fonction} introuvable")
    return problemes


def tableau() -> str:
    lignes = []
    for decision in inventaire.DECISIONS:
        choisis = [t for t in inventaire.TOURS if t.decision == decision]
        if not choisis:
            continue
        lignes.append(f"\n== {decision} ({len(choisis)}) ==")
        for t in choisis:
            lignes.append(f"- {t.identifiant} [{t.niveau} ; transport {t.transport}"
                          f"{' ; exécuteur ' + t.executeur if t.executeur else ''}]")
            lignes.append(f"    {t.module}:{t.fonction}")
            lignes.append(f"    idempotence : {t.idempotent}")
            lignes.append(f"    pourquoi : {t.justification}")
    lignes.append("\n== péremptions évaluées à la lecture (rien à balayer) ==")
    lignes += [f"- {libelle} : {module}:{fonction}"
               for libelle, module, fonction in inventaire.EVALUATIONS_A_LA_LECTURE]
    return "\n".join(lignes).lstrip("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verifier", action="store_true")
    args = parser.parse_args(argv)
    problemes = verifier()
    if args.verifier:
        for p in problemes:
            print("ÉCART :", p)
        print("OK" if not problemes else f"{len(problemes)} écart(s)")
        return 1 if problemes else 0
    if args.json:
        print(json.dumps([{**t.__dict__, "n3_ou_plus": t.n3_ou_plus} for t in inventaire.TOURS], ensure_ascii=False,
                         indent=2))
    else:
        print(tableau())
    return 1 if problemes else 0


if __name__ == "__main__":
    raise SystemExit(main())
