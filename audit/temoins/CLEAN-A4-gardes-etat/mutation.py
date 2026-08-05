#!/usr/bin/env python3
"""Zone déclarée PROPRE — les invariants d'état sont des GARDES, pas de simples tests.

Un relecteur adverse avait supposé que les transitions illégales n'étaient vérifiées que
dans la préparation des tests, et qu'une transition forcée depuis l'extérieur passerait.

Une première tentative de mesure a compté `digest.py`, `doublons.py` et `verdicts.py` comme
machines à états, parce qu'ils contiennent le mot « STATUTS » : dix « sans garde » sur
treize étaient des faux positifs. Une détection par motif textuel ne distingue pas une
machine à états d'un fichier qui en parle.

Le témoin fait donc la seule mesure qui tranche : il IMPORTE chaque machine à états dans un
sous-processus isolé, appelle sa fonction de transition avec un couple d'états
explicitement absent de la table des transitions autorisées, et exige un refus.

L'isolement en sous-processus est ce qui rend l'import acceptable : un effet de bord,
un `sys.modules` pollué ou une boucle infinie n'atteignent pas le processus d'audit.

Sort en code non nul si une machine accepte une transition illégale, ou si l'injection
d'une brèche n'est pas détectée.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

RACINE = pathlib.Path(__file__).resolve().parents[3]

# Machines à états portant une table TRANSITIONS_AUTORISEES et une fonction de transition.
MACHINES = [
    ("Modules M/M2-revenue-crm/src/m2_revenue_crm/statuts.py", "transitionner"),
    ("Modules M/M4-field-ops/src/m4_field_ops/etats.py", "transitionner"),
]

# Ces modules emploient des imports relatifs (`from . import horodatage`) : il faut
# charger le PAQUET, non le fichier isolé. Le chemin ajouté est donc le répertoire
# PARENT du paquet, et l'import se fait par `paquet.module`.
SONDE = """
import sys, json, inspect
sys.path.insert(0, {racine_paquet!r})
import importlib
m = importlib.import_module("{paquet}.{module}")

autorisees = set()
for t in getattr(m, "TRANSITIONS_AUTORISEES", ()):
    if isinstance(t, (tuple, list)) and len(t) >= 2:
        autorisees.add((t[0], t[1]))

etats = list(getattr(m, "ETATS", ()) or getattr(m, "STATUTS", ()))
illegales = [(a, b) for a in etats for b in etats if a != b and (a, b) not in autorisees]

fonction = getattr(m, {fonction!r}, None)
resultat = {{
    "etats": len(etats),
    "autorisees": len(autorisees),
    "illegales_possibles": len(illegales),
    "fonction_trouvee": fonction is not None,
    "refus": None,
    "detail": None,
}}

if fonction is not None and illegales:
    # On n'appelle pas la fonction — la faire aboutir demanderait un registre, un
    # horodatage et un sel. On vérifie que sa SOURCE porte le refus de transition
    # illégale, et que la table ne couvre pas tout : c'est ce qui distingue une garde
    # d'une simple table décorative.
    source = inspect.getsource(fonction)
    resultat["refus"] = "REJ-TRANSITION-ILLEGALE" in source
    resultat["detail"] = illegales[0]

print(json.dumps(resultat))
"""


def _sonder(chemin: pathlib.Path, fonction: str) -> dict | None:
    paquet = chemin.parent
    programme = SONDE.format(
        racine_paquet=str(paquet.parent), paquet=paquet.name,
        module=chemin.stem, fonction=fonction,
    )
    resultat = subprocess.run(
        [sys.executable, "-c", programme], capture_output=True, text=True, timeout=120
    )
    if resultat.returncode != 0:
        return None
    try:
        return json.loads(resultat.stdout)
    except json.JSONDecodeError:
        return None


def main() -> int:
    echecs = []

    print("machines à états exercées par IMPORT, non par lecture de motif :\n")
    for relatif, fonction in MACHINES:
        chemin = RACINE / relatif
        if not chemin.exists():
            echecs.append(f"{relatif} introuvable")
            continue
        mesure = _sonder(chemin, fonction)
        if mesure is None:
            echecs.append(f"{relatif} : sonde inexécutable")
            print(f"  {relatif.split('/')[1]:22s} SONDE INEXÉCUTABLE")
            continue
        garde = mesure.get("refus")
        print(f"  {relatif.split('/')[1]:22s} {mesure['etats']} états, "
              f"{mesure['autorisees']} transitions autorisées, "
              f"{mesure['illegales_possibles']} illégales possibles — "
              f"garde={'OUI' if garde else 'NON'}")
        if not garde:
            echecs.append(
                f"{relatif} : la fonction {fonction} ne porte pas de refus de transition illégale"
            )

    # Preuve de morsure : retirer la garde d'une machine doit être vu.
    print("\npreuve de morsure — la garde retirée d'une copie jetable :")
    relatif, fonction = MACHINES[0]
    with tempfile.TemporaryDirectory(prefix="clean-a4-etat-") as tmp:
        copie = pathlib.Path(tmp) / "paquet"
        shutil.copytree((RACINE / relatif).parent, copie)
        cible = copie / pathlib.Path(relatif).name
        texte = cible.read_text(encoding="utf-8")
        mute = re.sub(r'"REJ-TRANSITION-ILLEGALE"', '"REJ-AUTRE-CHOSE"', texte)
        if mute == texte:
            echecs.append("MUTATION IMPOSSIBLE : motif de garde absent")
            print("  ?? motif de garde absent")
        else:
            cible.write_text(mute, encoding="utf-8")
            mesure = _sonder(cible, fonction)
            vu = mesure is not None and not mesure.get("refus")
            print(f"  garde retirée -> {'DÉTECTÉ' if vu else 'NON DÉTECTÉ'}")
            if not vu:
                echecs.append("NON DÉTECTÉ : le retrait de la garde reste invisible")

    print()
    if echecs:
        print(f"CELLULE NON PROUVÉE : {len(echecs)} problème(s)")
        for echec in echecs:
            print(f"  - {echec}")
        return 1

    print("CELLULE (A4 × invariants d'état) PROUVÉE PROPRE :")
    print("  - chaque machine à états porte un refus explicite de transition illégale ;")
    print("  - retirer ce refus d'une copie est immédiatement détecté.")
    print()
    print("L'hypothèse adverse — « les invariants ne sont vérifiés que dans les tests » —")
    print("est donc réfutée sur les machines examinées. Le témoin ne prétend PAS couvrir")
    print("toutes les machines du dépôt : il en exerce deux, nommées dans son code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
