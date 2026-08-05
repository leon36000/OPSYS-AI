#!/usr/bin/env python3
"""Batterie de mutation du gate de cohérence du cadrage AUDIT-000.

Un gate vert ne prouve rien tant qu'on n'a pas montré qu'il MORD. Cette batterie
injecte des défauts connus et EXIGE le rouge, avec le motif attendu — « rouge »
ne suffit pas, il faut rouge POUR LA BONNE RAISON (une mutation qui mord par
accident masquerait un contrôle mort).

Différence avec le patron de M10 (DA-AUD-08) : la mutation opère sur une COPIE
JETABLE dans un répertoire temporaire, jamais dans l'arbre de travail. L'audit
doit pouvoir prouver n'avoir rien modifié (CA-AUD-09) ; muter en place laisserait
une fenêtre où l'arbre est altéré et dépendrait du bon déroulement du `finally`.

Sort en code non nul si UNE SEULE mutation ne mord pas.
"""
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Chemin déduit de l'EMPLACEMENT DU SCRIPT (DA-AUD-05) : rejouable depuis n'importe
# quel répertoire courant, en CI comme chez un tiers.
SOURCE = Path(__file__).resolve().parent

MUTATIONS = [
    # (fichier, ancien, nouveau, motif attendu dans la sortie du gate)
    (
        "02-PRD-PM.md",
        'SEVERITE = ("critique", "majeure", "mineure", "indetermine")',
        'SEVERITE = ("critique", "majeure", "mineure")',
        "échappatoire D-032",
    ),
    (
        "02-PRD-PM.md",
        "- **CA-AUD-07**",
        "- **CA-AUD-99**",
        "Numéros CA",
    ),
    (
        "02-PRD-PM.md",
        "| **Tier** | T1 — la sortie de sonde est le constat, sans interprétation |",
        "| **Tier** | T2 — la sortie de sonde est le constat, sans interprétation |",
        "Lot AUD-A1 devrait être T1",
    ),
    (
        "03-ARCHITECTURE.md",
        "### DA-AUD-04 —",
        "### DA-AUD-XX —",
        "DA-AUD-04",
    ),
    (
        "01-BRIEF-ANALYSTE.md",
        "| H7 |",
        "| HX |",
        "H7",
    ),
    (
        "01-BRIEF-ANALYSTE.md",
        "## 7. CE QUE L'AUDIT NE PRÉTENDRA PAS ÊTRE",
        "## 7. LIMITES",
        "limites de l'audit",
    ),
    # L'invariant « ne corrige rien » doit être exigé dans les TROIS documents :
    # le retirer d'un seul doit suffire à faire rougir le gate.
    (
        "03-ARCHITECTURE.md",
        "### DA-AUD-04 — L'audit ne corrige rien",
        "### DA-AUD-04 — L'audit reste passif",
        "ne corrige rien",
    ),
    (
        "02-PRD-PM.md",
        "### AUD-A5 — Sécurité",
        "### AUD-XX — Sécurité",
        "Lot A5",
    ),
    (
        "03-ARCHITECTURE.md",
        "### DA-AUD-09 —",
        "### DA-AUD-99 —",
        "DA-AUD-09",
    ),
]


def _lancer_gate(racine: Path) -> tuple[int, str]:
    """Exécute le gate dans la racine donnée. Capture le rc SANS pipeline.

    Un pipe masquerait le code retour (mesuré sur `tally.py | head`, qui affiche
    rc=0 alors que le script sort en 2).
    """
    resultat = subprocess.run(
        [sys.executable, str(racine / "verif_coherence.py")],
        capture_output=True,
        text=True,
    )
    return resultat.returncode, resultat.stdout + resultat.stderr


def _empreinte_dossier(racine: Path) -> str:
    """Empreinte stable de l'ensemble des fichiers du cadrage."""
    condensat = hashlib.sha256()
    for chemin in sorted(racine.rglob("*")):
        if chemin.is_file():
            condensat.update(chemin.relative_to(racine).as_posix().encode("utf-8"))
            condensat.update(chemin.read_bytes())
    return condensat.hexdigest()


def main() -> int:
    empreinte_source_avant = _empreinte_dossier(SOURCE)

    with tempfile.TemporaryDirectory(prefix="audit-mutation-") as tmp:
        travail = Path(tmp) / "bmad"
        shutil.copytree(SOURCE, travail)

        # Pré-condition : le gate doit être VERT sur la copie intacte, sinon un
        # rouge ultérieur ne prouverait rien (il serait rouge de toute façon).
        code, sortie = _lancer_gate(travail)
        if code != 0:
            print("PRÉ-CONDITION ÉCHOUÉE : le gate n'est pas vert sur la copie intacte")
            print(sortie)
            return 2
        print("PRÉ-CONDITION : gate VERT sur copie intacte — OK\n")

        echecs = []

        for nom_fichier, ancien, nouveau, motif in MUTATIONS:
            chemin = travail / nom_fichier
            original = chemin.read_text(encoding="utf-8")

            if ancien not in original:
                echecs.append(
                    f"MUTATION IMPOSSIBLE ({nom_fichier}) : motif source absent — "
                    f"{ancien[:60]!r}"
                )
                continue

            occurrences = original.count(ancien)
            # Muter TOUTES les occurrences : muter une seule occurrence d'un motif
            # répété laisserait le gate vert À JUSTE TITRE, et l'on conclurait à
            # tort que le contrôle est mort.
            chemin.write_text(original.replace(ancien, nouveau), encoding="utf-8")

            code, sortie = _lancer_gate(travail)

            chemin.write_text(original, encoding="utf-8")

            if code == 0:
                echecs.append(
                    f"NON DÉTECTÉ ({nom_fichier}, {occurrences} occurrence(s)) : "
                    f"{ancien[:50]!r} laisse le gate VERT"
                )
            elif motif not in sortie:
                echecs.append(
                    f"MORD POUR LA MAUVAISE RAISON ({nom_fichier}) : rouge, mais le "
                    f"motif attendu {motif!r} est absent de la sortie"
                )
            else:
                print(f"DÉTECTÉ ({nom_fichier}) : {ancien[:44]!r} -> motif {motif!r} OK")

        # Post-condition : la copie est revenue au vert après restauration.
        code, sortie = _lancer_gate(travail)
        if code != 0:
            echecs.append("POST-CONDITION : la copie n'est pas revenue au VERT")
            print(sortie)

    # L'arbre de travail RÉEL n'a jamais été touché — on le prouve.
    empreinte_source_apres = _empreinte_dossier(SOURCE)
    if empreinte_source_avant != empreinte_source_apres:
        echecs.append(
            "ARBRE DE TRAVAIL MODIFIÉ : la batterie a altéré les sources "
            f"({empreinte_source_avant[:16]} -> {empreinte_source_apres[:16]})"
        )
    else:
        print(f"\nSOURCE INTACTE : sha256 {empreinte_source_avant[:16]}… inchangé")

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
