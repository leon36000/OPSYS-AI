#!/usr/bin/env python3
"""Batterie de mutations MÉTIER sur le contrôle de conformité M3.

Cette batterie vérifie que les tests détectent les régressions de conception du
contrôle statique : résolution transitive des constantes, échappatoires, bornes
fail-closed, familles d'effets interdits et distinction des appels licites.
Elle ne prouve pas l'exhaustivité sémantique de l'analyse AST ; elle mesure
seulement que les règles explicitement portées par conformite.py sont
effectivement couvertes par une suite de tests discriminante.
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
# bord : le chemin est inséré explicitement, pour que l’import tienne quel que soit le
# répertoire courant et le mode de lancement.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lecture_junit import echecs_junit as _echecs_junit, nom_balise as _nom_balise

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SRC = RACINE / "Modules M/M3-estimation/src/m3_estimation/conformite.py"
TESTS = RACINE / "Modules M/M3-estimation/tests"
original = SRC.read_text(encoding="utf-8")

MUTATIONS = [
    (
        'la resolution des constantes textuelles est neutralisee',
        '        return expression.value, None, []',
        '        return None, ast.unparse(expression), []',
    ),
    (
        'la borne de profondeur transitive devient nulle',
        '_PROFONDEUR_RESOLUTION_MAXIMALE = 32',
        '_PROFONDEUR_RESOLUTION_MAXIMALE = 0',
    ),
    (
        'les noms de champs deviennent des enumeres de domaine',
        '        and not nom.startswith("CHAMPS_")',
        '        and True',
    ),
    (
        'aucun enumere public ne peut etre reconnu',
        '        and not nom.startswith("_")',
        '        and False',
    ),
    (
        'la derogation TYPES_TRAVAUX est retiree',
        '    "TYPES_TRAVAUX": {',
        '    "TYPES_TRAVAUX_SUPPRIME": {',
    ),
    (
        'les appels random non ensemences ne sont plus detectes',
        '            elif est_random and suffixe not in {',
        '            elif False and suffixe not in {',
    ),
    (
        'Random ou seed sans graine deviennent illicitement licites',
        'return not (isinstance(argument, ast.Constant) and argument.value is None)',
        'return True',
    ),
    (
        'les appels d horloge interne ne sont plus detectes',
        '            if est_horloge and suffixe in {',
        '            if False and suffixe in {',
    ),
    (
        'les appels reseau ne sont plus detectes',
        '            if est_reseau:',
        '            if False:',
    ),
    (
        'datetime.fromisoformat devient illicitement interdit',
        '                "utcnow",',
        '                "utcnow",\n                "fromisoformat",',
    ),
    (
        'l absence de fichiers analyses conclut illicitement au vert',
        '    if not fichiers:',
        '    if False:',
    ),
    (
        'l absence d enumere examine conclut illicitement au vert',
        '    if not enumerees:',
        '    if False:',
    ),
    (
        'alea_systeme_neutralise',
        'if est_alea_systeme:',
        'if False:',
    ),
]

REDONDANCES_DECLAREES = []

# La liste ci-dessus est VIDE, et c'est un résultat, pas un oubli : toutes les mutations
# métier de cette batterie doivent être discriminées par les tests. Une redondance ne peut
# être ajoutée qu'avec une justification structurelle et une mesure qui démontre son inertie.


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
        prefix="muter_conformite_", suffix=".xml"
    )
    os.close(descripteur)
    rapport = pathlib.Path(nom_rapport)
    try:
        resultat = subprocess.run(
            # Ce dossier contient les tests qui LANCENT ces batteries ; les inclure crée une
            # récursion mutuelle qui a mesurablement laissé des sources MUTÉES sur le disque.
            # Une sentinelle sur disque ne suffit pas : elle ne survit pas aux exécutions
            # concurrentes. L'exclusion est explicite et locale.
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
