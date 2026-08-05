#!/usr/bin/env python3
"""Témoin RED — AUD-A4-001 : une même fonction rend deux choses selon le module.

Sept modules portent chacun leur copie de `encoder_canonique`. Six renvoient une CHAÎNE
— la forme canonique sérialisée. Un, M2, renvoie un DIGEST sha256 de cette forme.

Le nom est identique, la convention est inverse. Un lecteur qui a compris la fonction dans
un module la comprend de travers dans l'autre, et le typage ne l'arrête pas : les deux
renvoient `str`. Un appel qui hacherait le retour de M2 hacherait un hachage.

Le témoin ne lit pas le code : il IMPORTE chaque copie dans un sous-processus isolé et lui
fait encoder la même valeur. Une lecture pourrait se tromper sur ce que fait réellement la
fonction ; une exécution, non. L'isolement en sous-processus est ce qui rend cet import
acceptable — le dépôt a un précédent où des tests d'un module exerçaient le code d'un autre
par `sys.modules` partagé.

Code retour : 1 si les conventions divergent, 0 si elles concordent, 2 si la mesure est
impossible.
"""
import json
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parents[3]

# Ce que l'on fait encoder à chaque copie. Une valeur simple suffit : ce qui est mesuré
# est la FORME du retour, pas la richesse de l'encodage.
VALEUR = {"b": 2, "a": 1}

GABARIT = """
import json, sys
sys.path.insert(0, {chemin!r})
import encodage
resultat = encodage.encoder_canonique({valeur!r})
print(json.dumps({{
    "type": type(resultat).__name__,
    "longueur": len(resultat) if hasattr(resultat, "__len__") else None,
    "valeur": resultat if isinstance(resultat, str) else repr(resultat),
}}))
"""


def _copies() -> list[pathlib.Path]:
    sortie = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, text=True, check=True
    ).stdout
    return sorted(
        RACINE / c for c in sortie.split("\0")
        if c.endswith("encodage.py") and "/src/" in c
    )


def _encoder_dans_un_sous_processus(chemin: pathlib.Path) -> dict | None:
    """Import isolé : un effet de bord ne doit pas atteindre le processus d'audit."""
    programme = GABARIT.format(chemin=str(chemin.parent), valeur=VALEUR)
    resultat = subprocess.run(
        [sys.executable, "-c", programme],
        capture_output=True, text=True, timeout=30,
    )
    if resultat.returncode != 0:
        return {"erreur": resultat.stderr.strip().splitlines()[-1] if resultat.stderr else "?"}
    try:
        return json.loads(resultat.stdout)
    except json.JSONDecodeError:
        return {"erreur": "sortie non-JSON"}


def main() -> int:
    copies = _copies()
    if not copies:
        print("TÉMOIN INAPPLICABLE : aucune copie d'encodage.py", file=sys.stderr)
        return 2

    par_forme: dict[str, list[str]] = {}
    erreurs = []

    print(f"copies de encoder_canonique exécutées sur la MÊME valeur {VALEUR} :\n")

    for chemin in copies:
        module = chemin.relative_to(RACINE).parts[1]
        mesure = _encoder_dans_un_sous_processus(chemin)
        if mesure is None or "erreur" in mesure:
            erreurs.append((module, (mesure or {}).get("erreur", "?")))
            print(f"  {module:26s} ERREUR — {(mesure or {}).get('erreur', '?')[:60]}")
            continue

        valeur = mesure["valeur"]
        # Un digest sha256 : 64 caractères hexadécimaux. Une forme canonique : du JSON.
        est_digest = (
            mesure["type"] == "str"
            and mesure["longueur"] == 64
            and all(c in "0123456789abcdef" for c in valeur)
        )
        forme = "DIGEST sha256" if est_digest else "CHAÎNE canonique"
        par_forme.setdefault(forme, []).append(module)
        print(f"  {module:26s} {forme:18s} {valeur[:44]}")

    print()
    for forme, modules in sorted(par_forme.items()):
        print(f"  {forme:18s} : {len(modules)} module(s) — {', '.join(sorted(modules))}")

    if erreurs:
        print(f"\n  copies non exécutables : {len(erreurs)}")
        for module, raison in erreurs:
            print(f"     {module} — {raison[:70]}")

    print()
    if len(par_forme) <= 1:
        print("CONSTAT NON REPRODUIT : toutes les copies partagent la même convention.")
        print("AUD-A4-001 est périmé et doit être retiré du rapport.")
        return 0

    minoritaire = min(par_forme.items(), key=lambda x: len(x[1]))
    majoritaire = max(par_forme.items(), key=lambda x: len(x[1]))

    print("CONSTAT AUD-A4-001 CONFIRMÉ :")
    print(f"  - {len(majoritaire[1])} copies renvoient une {majoritaire[0]}")
    print(f"  - {len(minoritaire[1])} copie renvoie un {minoritaire[0]} "
          f"— {', '.join(minoritaire[1])}")
    print("  - le nom, la signature et le type de retour sont identiques : rien, dans")
    print("    l'appel, ne signale la différence")
    print()
    print("Ce que le témoin N'AFFIRME PAS : qu'une des deux conventions soit la mauvaise,")
    print("ni qu'un appel se trompe aujourd'hui. Il établit que deux fonctions de même nom")
    print("et de même signature rendent des choses de nature différente, et qu'un lecteur")
    print("qui a compris l'une comprend l'autre de travers.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
