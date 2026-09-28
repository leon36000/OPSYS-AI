#!/usr/bin/env python3
"""Batterie de mutations MÉTIER sur le Monte Carlo déterministe.

Les gardes structurelles sont couvertes par enum_gardes.py. Ce script s'attaque à ce que
la neutralisation de gardes ne touche pas : les RÈGLES de classification elles-mêmes.
Chaque mutation est une erreur de conception PLAUSIBLE — celle qu'un relecteur pressé
laisserait passer — et doit faire virer la suite au ROUGE.

Chaque mutation est vérifiée COMPILABLE et APPLIQUÉE (le texte doit avoir changé) : une
mutation sans effet ne prouve rien. Une référence verte est mesurée avant toute mutation,
puis chaque rouge doit contenir au moins un nouvel échec attribuable à la mutation.
Ces deux mesures distinguent « la suite est rouge » de « la suite est rouge À CAUSE de
cette mutation ». Sans elles, une suite déjà cassée ferait passer l'instrument pour un
succès complet — c'est l'objection de revue qui a produit ce correctif.

Les sources sont restaurées à l'identique, ce qui est vérifié en fin de course. Le script
sort non-zéro si une seule mutation reste verte, n'est pas attribuable, ou si la référence
est déjà rouge.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
# Ces batteries sont des SCRIPTS lancés directement ; le dossier du script est alors en
# tête de sys.path et l'import ci-dessous fonctionne. On ne s'appuie pas sur cet effet de
# bord : le chemin est inséré explicitement, pour que l'import tienne quel que soit le
# répertoire courant et le mode de lancement.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lecture_junit import echecs_junit as _echecs_junit, nom_balise as _nom_balise

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SRC = RACINE / "departments/m03-estimation/src/m3_estimation/monte_carlo.py"
TESTS = RACINE / "departments/m03-estimation/tests"
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
     "INERTIE EMPIRIQUE, NON PROUVEE — requalification apres objection de revue scellee. "
     "Chaque tirage vaut generateur.uniform(cout_min, cout_max) * quantite et le plancher "
     "vaut cout_min * quantite. MESURE : 0 declenchement sur 300 graines de cette batterie, "
     "et 0 excursion hors [min, max] sur 2 500 000 tirages eprouves separement. MAIS la "
     "documentation CPython avertit que la borne haute de uniform PEUT OU NON etre incluse "
     "selon l arrondi flottant : l impossibilite n est donc PAS etablie. Un echantillon, "
     "meme large, ne demontre pas une impossibilite. La garde est conservee comme filet, et "
     "cette declaration dit ce qu elle est : une observation, pas une preuve."),
    ("bornage au bareme : le plafond ne s applique plus",
     "    if borne_haute > plafond:\n        borne_haute = plafond",
     "    if False:\n        borne_haute = plafond",
     "Meme raison, symetrique, et MEME LIMITE : le plafond vaut cout_max * quantite, aucun "
     "depassement observe, aucune impossibilite prouvee."),
]


# Mutations dont l'inertie est OBSERVÉE et non démontrée — chaque entrée ci-dessus dit
# elle-même l'étendue et la limite de sa mesure. On ne prétend donc PAS qu'elles ne
# peuvent pas mordre : on déclare qu'on ne les a jamais vues mordre, et on exige qu'elles
# restent VERTES. Si l'une venait à mordre, l'hypothèse d'inertie tomberait et il faudrait
# la réexaminer — le script échoue donc dans les DEUX sens. C'est précisément parce que
# l'impossibilité n'est pas établie que ce contrôle a une valeur : il surveille une
# observation, il ne consacre pas une certitude.


def purge():
    for c in SRC.parent.rglob("__pycache__"):
        shutil.rmtree(c, ignore_errors=True)






def _echecs_sortie(sortie):
    echecs = set()
    motif = re.compile(r"^\s*(?:FAILED|ERROR)\s+(.+?)(?:\s+-\s+.*)?\s*$")
    for ligne in sortie.splitlines():
        trouve = motif.match(ligne)
        if trouve:
            echecs.add(trouve.group(1))
    return echecs


def executer_tests():
    descripteur, nom_rapport = tempfile.mkstemp(
        prefix="muter_monte_carlo_", suffix=".xml"
    )
    os.close(descripteur)
    rapport = pathlib.Path(nom_rapport)
    try:
        resultat = subprocess.run(
            # Ce dossier contient les tests qui LANCENT ces batteries ; les inclure crée une
            # récursion mutuelle qui a mesurablement ramené la détection à 0/15 et laissé des
            # sources MUTÉES sur le disque. Une sentinelle sur disque ne suffit pas : elle ne
            # survit pas aux exécutions concurrentes. L'exclusion est explicite et locale.
            [
                sys.executable, "-B", "-m", "pytest", str(TESTS), "-q",
                f"--ignore={TESTS / 'test_gardes_des_outils.py'}",
                "-p", "no:cacheprovider", "--color=no", f"--junitxml={rapport}",
            ],
            capture_output=True,
            text=True,
            cwd=RACINE,
        )
        sortie = resultat.stdout + resultat.stderr
        echecs = _echecs_junit(rapport) | _echecs_sortie(sortie)
        return resultat, echecs, sortie
    finally:
        rapport.unlink(missing_ok=True)


def afficher_echecs(titre, echecs, sortie):
    if echecs:
        print(f"{titre} :")
        for echec in sorted(echecs):
            print(f"  - {echec}")
    else:
        print(f"{titre} : aucun nom de test extractible ; sortie pytest :")
        print(sortie.rstrip())


if not MUTATIONS:
    print("ABANDON : MUTATIONS est vide ; un instrument qui ne mesure rien ne prouve rien.")
    sys.exit(1)

echecs = []
mutations_mordues = 0
try:
    purge()
    reference, echecs_reference, sortie_reference = executer_tests()
    if reference.returncode != 0:
        echecs.append("reference : suite deja rouge")
        afficher_echecs(
            "REFERENCE ROUGE — tests qui echouaient deja",
            echecs_reference,
            sortie_reference,
        )
        print("ABANDON : muter une suite non verte ne prouve rien.")
    else:
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
            except SyntaxError as erreur:
                echecs.append(f"{nom} : ne compile pas ({erreur.msg})")
                print(f"{nom:<52} -> NE COMPILE PAS")
                continue

            SRC.write_text(mutant, encoding="utf-8")
            purge()
            resultat, echecs_mutant, sortie_mutant = executer_tests()
            nouveaux_echecs = echecs_mutant - echecs_reference

            if resultat.returncode == 0:
                echecs.append(f"{nom} : reste VERTE")
                etat = "VERTE (NON DETECTEE)"
            elif not nouveaux_echecs:
                echecs.append(f"{nom} : rouge NON ATTRIBUABLE")
                etat = "ROUGE (NON ATTRIBUABLE)"
                afficher_echecs(
                    f"  echec(s) mutant pour {nom}",
                    echecs_mutant,
                    sortie_mutant,
                )
            else:
                mutations_mordues += 1
                etat = "ROUGE"
            print(f"{nom:<52} -> {etat}")

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
            resultat, _, _ = executer_tests()
            if resultat.returncode != 0:
                echecs.append(
                    f"[redondance] {nom} : MORD alors qu elle est declaree inerte "
                    f"— l hypothese de redondance est tombee"
                )
                etat = "MORD (HYPOTHESE TOMBEE)"
            else:
                etat = "INERTE (conforme a la declaration)"
            print(f"[declaree] {nom:<52} -> {etat}")
            print(f"           raison : {raison}")
finally:
    SRC.write_text(original, encoding="utf-8")
    purge()

intact = SRC.read_text(encoding="utf-8") == original
print(
    f"\n{mutations_mordues}/{len(MUTATIONS)} mordent | "
    + (
        f"{len(REDONDANCES_DECLAREES)} redondances declarees et verifiees INERTES | "
        if REDONDANCES_DECLAREES else ""
    )
    + f"sources restaurees a l identique : {intact}"
)
sys.exit(1 if (echecs or not intact) else 0)
