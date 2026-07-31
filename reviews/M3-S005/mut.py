#!/usr/bin/env python3
"""Batterie de mutations MÉTIER sur le Monte Carlo déterministe.

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
SRC = RACINE / "Modules M/M3-estimation/src/m3_estimation/monte_carlo.py"
TESTS = RACINE / "Modules M/M3-estimation/tests"
original = SRC.read_text(encoding="utf-8")

MUTATIONS = [
    ("determinisme : generateur LOCAL -> module global (l ordre des appels fuite)",
     "    generateur = random.Random(graine)", "    generateur = random"),
    ("determinisme : la graine fournie est ignoree",
     "    generateur = random.Random(graine)", "    generateur = random.Random(0)"),
    ("le niveau demande est ignore (intervalle a taux fixe)",
     "    alpha = (1.0 - niveau) / 2.0", "    alpha = (1.0 - 0.90) / 2.0"),
    ("intervalle SYMETRIQUE -> queue basse seule",
     "    alpha = (1.0 - niveau) / 2.0", "    alpha = 1.0 - niveau"),
    ("le niveau rendu est ARRONDI au lieu d etre celui fourni",
     '        "niveau": float(niveau),', '        "niveau": round(niveau, 1),'),
    ("quantite ignoree dans le tirage (bornes sans rapport avec l ouvrage)",
     "        echantillon.append(cout_unitaire * quantite)",
     "        echantillon.append(cout_unitaire)"),
    ("echantillon NON TRIE : les quantiles perdent leur sens",
     "    echantillon.sort()", "    pass"),
    ("ordre des bornes : basse et haute permutees",
     "    borne_basse = echantillon[indice_bas]\n    borne_haute = echantillon[indice_haut]",
     "    borne_basse = echantillon[indice_haut]\n    borne_haute = echantillon[indice_bas]"),
    ("nombre de tirages rendu variable (deux estimations incomparables)",
     "NOMBRE_TIRAGES = 10000", "NOMBRE_TIRAGES = 101"),
    ("bornes du bareme : min > max devient tolere",
     "    if cout_min > cout_max:", "    if False:"),
]

REDONDANCES_DECLAREES = [
    ("bornage au bareme : le plancher ne s applique plus",
     "    if borne_basse < plancher:\n        borne_basse = plancher",
     "    if False:\n        borne_basse = plancher",
     "Chaque tirage vaut generateur.uniform(cout_min, cout_max) * quantite et le plancher "
     "vaut cout_min * quantite : le tirage est DANS les bornes par construction. MESURE : "
     "sur 300 graines, le bornage ne s est declenche 0 fois. C est un filet contre un "
     "depassement d un chiffre binaire lie a l arrondi flottant, pas un controle metier ; "
     "il est conserve parce que le contrat exige que les bornes restent dans le bareme."),
    ("bornage au bareme : le plafond ne s applique plus",
     "    if borne_haute > plafond:\n        borne_haute = plafond",
     "    if False:\n        borne_haute = plafond",
     "Meme raison, symetrique : le plafond vaut cout_max * quantite et aucun tirage ne le "
     "depasse. MESURE : 0 declenchement sur 300 graines."),
]


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
