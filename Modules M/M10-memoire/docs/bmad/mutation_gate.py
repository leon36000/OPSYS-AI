#!/usr/bin/env python3
"""Batterie de mutation du gate de cohérence M10.

Chaque mutation est appliquée EN PLACE au document visé, le gate est relancé, et
l'on EXIGE le rouge (exit != 0) avec le motif attendu. Le fichier est ensuite
restauré et son identité (sha256) vérifiée — un gate vert après restauration
ne suffit pas : il faut prouver que le fichier est bit-à-bit l'original.

Sort en code non nul si UNE SEULE mutation ne mord pas.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

# Chemin déduit de l'EMPLACEMENT DU SCRIPT, jamais du répertoire courant ni d'un
# chemin absolu (ADR-0003) : sinon le script n'est rejouable ni en CI ni chez un
# autre développeur — et un pack de revue doit porter le SCRIPT, pas sa sortie.
BASE = Path(__file__).resolve().parent
GATE = BASE / "verif_coherence.py"

MUTATIONS = [
    # (fichier, ancien, nouveau, motif attendu dans la sortie du gate)
    (
        "02-PRD-PM.md",
        'STATUT_DECISION = ("proposee", "validee", "remplacee", "annulee", "indetermine")',
        'STATUT_DECISION = ("proposee", "validee", "remplacee", "annulee")',
        "échappatoire D-032",
    ),
    (
        "02-PRD-PM.md",
        '"obsolete_marquee"',
        '"fusionnes"',
        "valeur de fusion interdite",
    ),
    (
        "02-PRD-PM.md",
        "- **CA-M10-07**",
        "- **CA-M10-99**",
        "Numéros CA",
    ),
    (
        "02-PRD-PM.md",
        "| **Tier** | T1 (patron 6 fois prouvé) |",
        "| **Tier** | T3 (patron 6 fois prouvé) |",
        "Story S002 devrait être T1",
    ),
    (
        "03-ARCHITECTURE.md",
        "### DA-M10-06 —",
        "### DA-M10-XX —",
        "DA-M10-06",
    ),
    # NB : CONSOMMATEURS_CIBLES apparaît PLUSIEURS fois dans chaque document.
    # Muter une seule occurrence laisserait le gate vert à juste titre (le contrat
    # resterait cité ailleurs) — leçon « mutation count=1 sur motif répété = faux
    # négatif ». On mute donc TOUTES les occurrences, dans les DEUX documents.
    (
        "03-ARCHITECTURE.md",
        "CONSOMMATEURS_CIBLES",
        "LISTE_CIBLES",
        "CONSOMMATEURS_CIBLES",
    ),
    (
        "01-BRIEF-ANALYSTE.md",
        "CONSOMMATEURS_CIBLES",
        "LISTE_CIBLES",
        "CONSOMMATEURS_CIBLES",
    ),
    (
        "01-BRIEF-ANALYSTE.md",
        "## 1. BESOIN MÉTIER",
        "## 1. OBJECTIF",
        "BESOIN MÉTIER",
    ),
]


def lancer_gate():
    resultat = subprocess.run(
        [sys.executable, str(GATE)], capture_output=True, text=True
    )
    return resultat.returncode, resultat.stdout + resultat.stderr


def empreinte(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def main():
    # Pré-condition : le gate DOIT être vert avant toute mutation, sinon
    # un rouge ultérieur ne prouverait rien (il serait rouge de toute façon).
    code, sortie = lancer_gate()
    if code != 0:
        print("PRÉ-CONDITION ÉCHOUÉE : le gate n'est pas vert avant mutation")
        print(sortie)
        return 2
    print("PRÉ-CONDITION : gate VERT avant mutation — OK\n")

    echecs = []

    for nom_fichier, ancien, nouveau, motif in MUTATIONS:
        chemin = BASE / nom_fichier
        original = chemin.read_text(encoding="utf-8")
        empreinte_avant = empreinte(chemin)

        if ancien not in original:
            echecs.append(
                f"MUTATION IMPOSSIBLE ({nom_fichier}) : motif source absent — "
                f"{ancien[:50]!r}"
            )
            continue

        occurrences = original.count(ancien)
        chemin.write_text(original.replace(ancien, nouveau), encoding="utf-8")

        try:
            code, sortie = lancer_gate()
        finally:
            chemin.write_text(original, encoding="utf-8")

        empreinte_apres = empreinte(chemin)
        if empreinte_apres != empreinte_avant:
            echecs.append(
                f"RESTAURATION ROMPUE ({nom_fichier}) : sha256 différent"
            )
            continue

        if code == 0:
            echecs.append(
                f"NON DÉTECTÉ ({nom_fichier}, {occurrences} occurrence(s)) : "
                f"{ancien[:40]!r} -> {nouveau[:40]!r} laisse le gate VERT"
            )
        elif motif not in sortie:
            echecs.append(
                f"MORD POUR LA MAUVAISE RAISON ({nom_fichier}) : rouge, mais le "
                f"motif attendu {motif!r} est absent de la sortie"
            )
        else:
            print(
                f"DÉTECTÉ ({nom_fichier}) : {ancien[:38]!r} -> motif {motif!r} OK"
            )

    # Post-condition : le gate doit être redevenu vert après restauration.
    code, sortie = lancer_gate()
    if code != 0:
        echecs.append("POST-CONDITION : le gate n'est pas revenu au VERT")
        print(sortie)

    print()
    if echecs:
        print(f"BATTERIE INCOMPLÈTE : {len(echecs)} problème(s)")
        for echec in echecs:
            print(f"  - {echec}")
        return 1

    print(f"BATTERIE COMPLÈTE : {len(MUTATIONS)}/{len(MUTATIONS)} mutations mordent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
