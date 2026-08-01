#!/usr/bin/env python3
"""Batterie de mutations MÉTIER sur le plancher rentable.

Les gardes structurelles sont couvertes par enum_gardes.py. Ce script s'attaque à ce que
la neutralisation de gardes ne touche pas : les RÈGLES de classification elles-mêmes.
Chaque mutation est une erreur de conception PLAUSIBLE — celle qu'un relecteur pressé
laisserait passer — et doit faire virer la suite au ROUGE.

Chaque mutation est vérifiée COMPILABLE et APPLIQUÉE (le texte doit avoir changé) : une
mutation sans effet ne prouve rien. Les sources sont restaurées à l'identique, ce qui est
vérifié en fin de course. Le script sort non-zéro si une seule mutation reste verte.
"""
import pathlib, shutil, subprocess, sys

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SRC = RACINE / "Modules M/M3-estimation/src/m3_estimation/plancher.py"
TESTS = RACINE / "Modules M/M3-estimation/tests"
original = SRC.read_text(encoding="utf-8")

MUTATIONS = [
    ("comparaison STRICTE -> large (l egalite alerte a tort)",
     "    alerte = borne_basse < plancher_rentable",
     "    alerte = borne_basse <= plancher_rentable"),
    ("sens de la comparaison inverse",
     "    alerte = borne_basse < plancher_rentable",
     "    alerte = borne_basse > plancher_rentable"),
    ("l alerte ne se declenche jamais",
     "    alerte = borne_basse < plancher_rentable", "    alerte = False"),
    ("l alerte se declenche toujours",
     "    alerte = borne_basse < plancher_rentable", "    alerte = True"),
    ("le plancher FOURNI est remplace par un seuil code en dur",
     "    alerte = borne_basse < plancher_rentable", "    alerte = borne_basse < 0.0"),
    ("les deux verdicts sont permutes",
     "_VERDICT_ALERTE = contrats.VERDICT_PLANCHER_RENTABILITE_FRANCHI\n_VERDICT_SANS_ALERTE = contrats.VERDICT_AUCUN_BLOCAGE",
     "_VERDICT_ALERTE = contrats.VERDICT_AUCUN_BLOCAGE\n_VERDICT_SANS_ALERTE = contrats.VERDICT_PLANCHER_RENTABILITE_FRANCHI"),
    ("le plancher NEGATIF devient tolere",
     "    if plancher_rentable < 0:", "    if False:"),
    ("intervalle INVERSE : la coherence des bornes n est plus verifiee",
     "    if borne_basse > borne_haute:", "    if False:"),
    ("la borne haute est confrontee au lieu de la borne basse",
     "    alerte = borne_basse < plancher_rentable",
     "    alerte = intervalle[\"borne_haute\"] < plancher_rentable"),
]

REDONDANCES_DECLAREES = []


# Mutations qui ne PEUVENT PAS mordre, et dont l'inertie est elle-même une propriété à
# prouver. Les faire « passer » exigerait de fabriquer une entrée impossible ; la
# discipline est de les DÉCLARER, et d'exiger qu'elles restent VERTES. Si l'une venait à
# mordre, l'hypothèse de redondance serait tombée et il faudrait la réexaminer — le
# script échoue donc dans les DEUX sens.


def purge():
    for c in SRC.parent.rglob("__pycache__"):
        shutil.rmtree(c, ignore_errors=True)


echecs = []
try:
    for nom, avant, apres in MUTATIONS:
        if original.count(avant) != 1:
            echecs.append(f"{nom} : ancre x{original.count(avant)}")
            print(f"{nom:<52} -> ANCRE INTROUVABLE/AMBIGUE")
            continue
        mutant = original.replace(avant, apres, 1)
        if mutant == original:
            echecs.append(f"{nom} : mutation SANS EFFET")
            print(f"{nom:<52} -> SANS EFFET")
            continue
        try:
            compile(mutant, str(SRC), "exec")
        except SyntaxError as e:
            echecs.append(f"{nom} : ne compile pas ({e.msg})")
            print(f"{nom:<52} -> NE COMPILE PAS")
            continue
        SRC.write_text(mutant, encoding="utf-8")
        purge()
        r = subprocess.run([sys.executable, "-B", "-m", "pytest", str(TESTS), "-q",
                            "-p", "no:cacheprovider", "--color=no"],
                           capture_output=True, cwd=RACINE)
        if r.returncode == 0:
            echecs.append(f"{nom} : reste VERTE")
        print(f"{nom:<52} -> {'ROUGE' if r.returncode else 'VERTE (NON DETECTEE)'}")
    for nom, avant, apres, raison in REDONDANCES_DECLAREES:
        if original.count(avant) != 1:
            echecs.append(f"[redondance] {nom} : ancre x{original.count(avant)}")
            continue
        mutant = original.replace(avant, apres, 1)
        if mutant == original:
            echecs.append(f"[redondance] {nom} : mutation SANS EFFET (texte inchange)")
            continue
        compile(mutant, str(SRC), "exec")
        SRC.write_text(mutant, encoding="utf-8")
        purge()
        r = subprocess.run([sys.executable, "-B", "-m", "pytest", str(TESTS), "-q",
                            "-p", "no:cacheprovider", "--color=no"],
                           capture_output=True, cwd=RACINE)
        if r.returncode != 0:
            echecs.append(f"[redondance] {nom} : MORD alors qu elle est declaree inerte "
                          f"— l hypothese de redondance est tombee")
            etat = "MORD (HYPOTHESE TOMBEE)"
        else:
            etat = "INERTE (conforme a la declaration)"
        print(f"[declaree] {nom:<52} -> {etat}")
        print(f"           raison : {raison}")
finally:
    SRC.write_text(original, encoding="utf-8")
    purge()

intact = SRC.read_text(encoding="utf-8") == original
mordantes = len(MUTATIONS) - len([e for e in echecs if not e.startswith("[redondance]")])
print(f"\n{mordantes}/{len(MUTATIONS)} mordent | "
      + (f"{len(REDONDANCES_DECLAREES)} redondances declarees et verifiees INERTES | "
         if REDONDANCES_DECLAREES else "") +
      f""
      f"sources restaurees a l identique : {intact}")
sys.exit(1 if (echecs or not intact) else 0)
