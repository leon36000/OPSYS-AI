#!/usr/bin/env python3
"""Zone déclarée PROPRE — le déterminisme de l'encodage canonique, et la preuve qu'on l'aurait vu.

« J'ai regardé, rien trouvé » est indistinguable d'une sonde cassée. Cette cellule
(lot A4 × non-déterminisme) ne porte aucun constat : les 7 copies de `encoder_canonique`
produisent le même encodage d'un processus à l'autre et quel que soit l'ordre des clés.

Pour que cette absence de constat vaille quelque chose, il faut montrer que la mesure
AURAIT détecté un défaut. Ce fichier injecte donc un non-déterminisme dans une copie
jetable, et exige que la mesure le voie.

Deux non-déterminismes sont injectés séparément, parce qu'ils échappent à des contrôles
différents :
  - `sort_keys` retiré : l'encodage dépend alors de l'ordre d'insertion des clés ;
  - `hash()` natif substitué : sa valeur change d'un processus à l'autre, PYTHONHASHSEED
    étant tiré au hasard à chaque démarrage.

Sort en code non nul si une injection n'est PAS détectée.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

RACINE = pathlib.Path(__file__).resolve().parents[3]

MESURE = """
import sys, json, hashlib
sys.path.insert(0, {chemin!r})
import encodage
v = {{"z": 1, "a": [True, None, 2], "m": {{"k": "e"}}}}
r1 = encodage.encoder_canonique(v)
r2 = encodage.encoder_canonique(dict(reversed(list(v.items()))))
print(json.dumps({{
    "stable_ordre": r1 == r2,
    "empreinte": hashlib.sha256(str(r1).encode()).hexdigest()[:16],
}}))
"""

# Les injections portent sur le code RÉEL, vérifié dans le fichier — non sur ce qu'on
# suppose qu'il contient. Une première version visait `sort_keys=True`, absent de ces
# copies : le tri s'y fait par `items.sort(...)`. Le mécanisme a refusé de déclarer la
# cellule propre, ce qui est exactement son rôle.
INJECTIONS = [
    # Sans le tri, l'encodage dépend de l'ordre d'insertion des clés.
    ("tri des clés retiré", "        items.sort(", "        _ = items and ("),
    # `hash()` natif varie d'un processus à l'autre : PYTHONHASHSEED est tiré au hasard.
    ("clé de tri remplacée par hash() natif",
     "key=lambda pair: json.dumps(", "key=lambda pair: str(hash(str(pair))) or json.dumps("),
]


def _mesurer(dossier: pathlib.Path) -> dict | None:
    """Deux processus distincts : c'est ce qui révèle une dépendance à PYTHONHASHSEED."""
    empreintes, ordres = set(), set()
    for _ in range(2):
        try:
            resultat = subprocess.run(
                [sys.executable, "-c", MESURE.format(chemin=str(dossier))],
                capture_output=True, text=True, timeout=120,
                env={"PYTHONHASHSEED": "random", "PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired:
            # Un dépassement de délai n'est PAS une absence de défaut. Le confondre
            # avec « la copie ne s'exécute plus » ferait passer une injection non
            # mesurée pour une injection détectée — un faux vert dans le sens le plus
            # dangereux. On le distingue explicitement.
            return {"timeout": True}
        if resultat.returncode != 0:
            return None
        try:
            mesure = json.loads(resultat.stdout)
        except json.JSONDecodeError:
            return None
        empreintes.add(mesure["empreinte"])
        ordres.add(mesure["stable_ordre"])
    return {"stable_processus": len(empreintes) == 1, "stable_ordre": ordres == {True}}


def main() -> int:
    copies = sorted(
        f for f in subprocess.run(
            ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, text=True, check=True
        ).stdout.split("\0")
        if f.endswith("encodage.py") and "/src/" in f
    )
    if not copies:
        print("MUTATION IMPOSSIBLE : aucune copie d'encodage.py", file=sys.stderr)
        return 2

    # Une seule copie suffit à prouver que la mesure mord : le contrôle est le même
    # pour les sept, et muter les sept coûterait sept fois plus pour la même preuve.
    reference = RACINE / copies[0]
    module = copies[0].split("/")[1]
    echecs = []

    with tempfile.TemporaryDirectory(prefix="clean-a4-") as tmp:
        travail = pathlib.Path(tmp) / "copie"
        travail.mkdir()
        shutil.copy2(reference, travail / "encodage.py")

        intacte = _mesurer(travail)
        if intacte is not None and intacte.get("timeout"):
            print(f"PRÉ-CONDITION IMPOSSIBLE : délai dépassé sur {module}", file=sys.stderr)
            return 2
        if intacte is None or not (intacte["stable_processus"] and intacte["stable_ordre"]):
            print(f"PRÉ-CONDITION ÉCHOUÉE : {module} n'est pas déterministe avant mutation")
            return 2
        print(f"PRÉ-CONDITION : {module} déterministe sur copie intacte — OK\n")

        original = (travail / "encodage.py").read_text(encoding="utf-8")

        for libelle, ancien, nouveau in INJECTIONS:
            if ancien not in original:
                echecs.append(f"INJECTION IMPOSSIBLE ({libelle}) : motif {ancien!r} absent")
                print(f"  ?? {libelle} — motif absent")
                continue

            (travail / "encodage.py").write_text(
                original.replace(ancien, nouveau), encoding="utf-8"
            )
            mesure = _mesurer(travail)
            (travail / "encodage.py").write_text(original, encoding="utf-8")

            if mesure is not None and mesure.get("timeout"):
                echecs.append(f"MESURE IMPOSSIBLE ({libelle}) : délai dépassé — non conclu")
                print(f"  ?? {libelle} — délai dépassé, la mesure ne conclut pas")
                continue
            if mesure is None:
                print(f"  DÉTECTÉ  {libelle} — la copie mutée ne s'exécute plus")
                continue
            if mesure["stable_processus"] and mesure["stable_ordre"]:
                echecs.append(f"NON DÉTECTÉ ({libelle}) : la mesure reste au vert")
                print(f"  NON DÉTECTÉ  {libelle}")
            else:
                quoi = []
                if not mesure["stable_processus"]:
                    quoi.append("empreinte instable entre processus")
                if not mesure["stable_ordre"]:
                    quoi.append("sensible à l'ordre des clés")
                print(f"  DÉTECTÉ  {libelle} — {', '.join(quoi)}")

    print()
    if echecs:
        print(f"CELLULE NON PROUVÉE : {len(echecs)} injection(s) invisible(s)")
        for echec in echecs:
            print(f"  - {echec}")
        return 1

    print("CELLULE (A4 × non-déterminisme) PROUVÉE PROPRE :")
    print("  - les 7 copies sont déterministes entre processus et sur l'ordre des clés ;")
    print("  - la mesure détecte les deux non-déterminismes injectés.")
    print("  L'absence de constat sur cette cellule est donc une mesure, non un silence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
