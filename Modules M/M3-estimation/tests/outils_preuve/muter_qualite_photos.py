#!/usr/bin/env python3
"""Batterie de mutations M3-S002 — rejouable. Chaque garde neutralisée isolément doit ROUGIR.

Les gardes structurelles sont couvertes par les tests dédiés. Ce script s'attaque aux
règles de validation elles-mêmes. Une référence verte est mesurée avant toute mutation,
puis chaque rouge doit contenir au moins un nouvel échec attribuable à la mutation.
Ces deux mesures distinguent « la suite est rouge » de « la suite est rouge À CAUSE de
cette mutation ». Sans elles, une suite déjà cassée pourrait faire annoncer « toutes les
mutations mordent » sans rien prouver.

Les sources sont restaurées à l'identique, ce qui est vérifié en fin de course. Le script
sort non-zéro si une mutation reste verte, n'est pas attribuable, ne compile pas, n'est
pas appliquée, si la référence est déjà rouge, ou si aucune mutation n'est mesurée.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
D = RACINE / "Modules M/M3-estimation/src/m3_estimation"
Q, S, C = D/"qualite_photos.py", D/"signaux.py", D/"contrats.py"
TESTS = RACINE / "Modules M/M3-estimation/tests"
TQ, TS = (
    RACINE / "Modules M/M3-estimation/tests/test_qualite_photos.py",
    RACINE / "Modules M/M3-estimation/tests/test_signaux.py",
)
SOURCES = (Q, S, C)
originaux = {p: p.read_text(encoding="utf-8") for p in SOURCES}

MUTATIONS = [
 ("regle des DEUX dimensions : min -> max", Q, TQ, "        plus_petite_dimension = min(", "        plus_petite_dimension = max("),
 ("borne resolution : < devient <=", Q, TQ, "        if plus_petite_dimension < resolution_minimale:", "        if plus_petite_dimension <= resolution_minimale:"),
 ("borne eclairage : < devient <=", Q, TQ, '        if photo["eclairage"] < eclairage_minimal:', '        if photo["eclairage"] <= eclairage_minimal:'),
 ("echelle 0-10 retiree", Q, TQ, "    if type(eclairage) not in (int, float) or not 0 <= eclairage <= 10:", "    if type(eclairage) not in (int, float):"),
 ("typage STRICT -> isinstance (accepte True)", Q, TQ, '    if type(seuils["resolution_minimale"]) is not int:', '    if not isinstance(seuils["resolution_minimale"], int):'),
 ("cles des seuils : egalite -> sous-ensemble", Q, TQ, "    if set(seuils) != set(contrats.CHAMPS_SEUILS_QUALITE):", "    if not set(seuils) <= set(contrats.CHAMPS_SEUILS_QUALITE):"),
 ("CHAMPS_SEUILS_QUALITE tronque", C, TQ, '"resolution_minimale", "eclairage_minimal"', '"resolution_minimale"'),
 ("emission_count devient un compteur", S, TS, "EMISSION_UNIQUE = 1", "EMISSION_UNIQUE = 2"),
]

REDONDANCES_DECLAREES = []

GARDES_TARDIVES = [
 ("garde « photos est une liste »", Q, TQ, "    if not isinstance(photos, list):", "    if False:"),
 ("borne INFERIEURE de l echelle 0-10", Q, TQ, "not 0 <= eclairage <= 10", "eclairage > 10"),
 ("cles exactes de reference_echelle", Q, TQ, '        if not isinstance(reference, dict) or set(reference) != {', '        if not isinstance(reference, dict) or not set(reference) <= {'),
 ("type booleen STRICT de dimensions_connues", Q, TQ, '        if type(reference["dimensions_connues"]) is not bool:', "        if False:"),
]


def purge():
    for cache in RACINE.joinpath("Modules M/M3-estimation/src").rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _nom_balise(element):
    return element.tag.rsplit("}", 1)[-1]


def _echecs_junit(chemin):
    try:
        racine = ET.parse(chemin).getroot()
    except ET.ParseError:
        return set()

    echecs = set()
    for cas in racine.iter():
        if _nom_balise(cas) != "testcase":
            continue
        if not any(_nom_balise(enfant) in {"failure", "error"} for enfant in cas):
            continue
        classe = cas.attrib.get("classname", "")
        nom = cas.attrib.get("name", "<test sans nom>")
        echecs.add(f"{classe}::{nom}" if classe else nom)

    for suite in racine.iter():
        if _nom_balise(suite) != "testsuite":
            continue
        for enfant in suite:
            if _nom_balise(enfant) in {"failure", "error"}:
                echecs.add(
                    f"{suite.attrib.get('name', '<collecte>')}::{_nom_balise(enfant)}"
                )
    return echecs


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
        prefix="muter_qualite_photos_", suffix=".xml"
    )
    os.close(descripteur)
    rapport = pathlib.Path(nom_rapport)
    try:
        resultat = subprocess.run(
            [
                sys.executable, "-B", "-m", "pytest", str(TESTS), "-q",
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


def construire_mutations_dynamiques():
    mutations = []
    erreurs = []

    correspondance = re.search(
        r"CHAMPS_PHOTO\s*=\s*\((.*?)\)", originaux[C], re.DOTALL
    )
    if not correspondance:
        erreurs.append("CHAMPS_PHOTO ampute de sa derniere cle : declaration introuvable")
    else:
        cles = re.findall(r'"([a-z_]+)"', correspondance.group(1))
        if not cles:
            erreurs.append(
                "CHAMPS_PHOTO ampute de sa derniere cle : aucune cle extractible"
            )
        else:
            avant = correspondance.group(0)
            apres = avant.replace(f'"{cles[-1]}"', "", 1)
            mutations.append(
                (
                    "CHAMPS_PHOTO ampute de sa derniere cle",
                    C,
                    TQ,
                    avant,
                    apres,
                )
            )

    originaux_signaux = originaux[S]
    for libelle, candidats, transformation in [
        (
            "copie defensive retiree",
            [
                ligne for ligne in originaux_signaux.splitlines()
                if "elements_manquants" in ligne and "list(" in ligne
            ],
            lambda ligne: re.sub(r"list\(([^)]*)\)", r"\1", ligne),
        ),
        (
            "refus de la liste vide neutralise",
            [
                ligne for ligne in originaux_signaux.splitlines()
                if "elements_manquants" in ligne
                and "if" in ligne
                and ("not " in ligne or "len(" in ligne)
            ],
            lambda ligne: re.sub(r"if .*:", "if False:", ligne),
        ),
    ]:
        if len(candidats) != 1:
            erreurs.append(f"{libelle} : {len(candidats)} candidates")
            continue
        mutations.append((libelle, S, TS, candidats[0], transformation(candidats[0])))

    return mutations, erreurs


if not MUTATIONS:
    print("ABANDON : MUTATIONS est vide ; un instrument qui ne mesure rien ne prouve rien.")
    sys.exit(1)

mutations_dynamiques, erreurs_preparation = construire_mutations_dynamiques()
mutations = list(MUTATIONS) + mutations_dynamiques + list(GARDES_TARDIVES)
echecs = list(erreurs_preparation)
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
        for nom, fichier, cible, avant, apres in mutations:
            original = originaux[fichier]
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
                compile(mutant, str(fichier), "exec")
            except SyntaxError as erreur:
                echecs.append(f"{nom} : ne compile pas ({erreur.msg})")
                print(f"{nom:<52} -> NE COMPILE PAS")
                continue

            try:
                fichier.write_text(mutant, encoding="utf-8")
                purge()
                resultat, echecs_mutant, sortie_mutant = executer_tests()
            finally:
                fichier.write_text(original, encoding="utf-8")
                purge()

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

        for nom, fichier, avant, apres, raison in REDONDANCES_DECLAREES:
            original = originaux[fichier]
            if original.count(avant) != 1:
                echecs.append(f"[redondance] {nom} : ancre x{original.count(avant)}")
                continue
            mutant = original.replace(avant, apres, 1)
            if mutant == original:
                echecs.append(
                    f"[redondance] {nom} : mutation SANS EFFET (texte inchange)"
                )
                continue
            try:
                compile(mutant, str(fichier), "exec")
            except SyntaxError as erreur:
                echecs.append(f"[redondance] {nom} : ne compile pas ({erreur.msg})")
                continue

            try:
                fichier.write_text(mutant, encoding="utf-8")
                purge()
                resultat, _, _ = executer_tests()
            finally:
                fichier.write_text(original, encoding="utf-8")
                purge()

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
    for fichier, original in originaux.items():
        fichier.write_text(original, encoding="utf-8")
    purge()

intactes = all(
    fichier.read_text(encoding="utf-8") == original
    for fichier, original in originaux.items()
)
print(
    f"\n{mutations_mordues}/{len(mutations)} mordent | "
    + (
        f"{len(REDONDANCES_DECLAREES)} redondances declarees et verifiees INERTES | "
        if REDONDANCES_DECLAREES else ""
    )
    + f"sources restaurees a l identique : {intactes}"
)
sys.exit(1 if (echecs or not intactes) else 0)
