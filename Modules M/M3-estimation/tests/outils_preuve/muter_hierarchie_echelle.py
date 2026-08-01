#!/usr/bin/env python3
"""Batterie de mutations MÉTIER sur la hiérarchie des niveaux de confiance.

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
SRC = RACINE / "Modules M/M3-estimation/src/m3_estimation/hierarchie_echelle.py"
TESTS = RACINE / "Modules M/M3-estimation/tests"
original = SRC.read_text(encoding="utf-8")

MUTATIONS = [
    ("une reference qualifiante ne suffit plus (>=1 -> >=2)",
     'if motifs["photos_avec_reference"] >= 1:',
     'if motifs["photos_avec_reference"] >= 2:'),
    ("la reference d echelle perd sa primaute (regle 1 desactivee)",
     'if motifs["photos_avec_reference"] >= 1:',
     'if False and motifs["photos_avec_reference"] >= 1:'),
    ("MULTI_VUES : angles DISTINCTS -> nombre de photos",
     '        and motifs["angles_distincts"] >= 3',
     '        and nombre_photos >= 3'),
    ("MULTI_VUES : quantificateur UNIVERSEL -> au moins une",
     "        and au_dessus_resolution == nombre_photos",
     "        and au_dessus_resolution >= 1"),
    ("MONO_VUE : borne haute 2 -> 3 photos",
     "        1 <= nombre_photos <= 2", "        1 <= nombre_photos <= 3"),
    ("MONO_VUE : quantificateur UNIVERSEL -> au moins une",
     '        and motifs["photos_au_dessus_du_seuil"] == nombre_photos',
     '        and motifs["photos_au_dessus_du_seuil"] >= 1'),
    ("resolution : la PLUS PETITE dimension -> la plus grande",
     "            min(photo[\"resolution_largeur\"], photo[\"resolution_hauteur\"])",
     "            max(photo[\"resolution_largeur\"], photo[\"resolution_hauteur\"])"),
    ("resolution : cas d egalite ACCEPTABLE -> refuse",
     "            >= resolution_minimale", "            > resolution_minimale"),
    ("eclairage : cas d egalite ACCEPTABLE -> refuse",
     'eclairage_ok = photo["eclairage"] >= eclairage_minimal',
     'eclairage_ok = photo["eclairage"] > eclairage_minimal'),
    ("angles : valeurs DISTINCTES -> comptage brut (perte du set)",
     '        angles_distincts.add(photo["angle"])',
     '        angles_distincts.add((photo["angle"], len(angles_distincts)))'),
    ("MONO_VUE : les DEUX seuils -> la resolution seule",
     "        if resolution_ok and eclairage_ok:",
     "        if resolution_ok:"),
    ("echappatoire D-032 : INDETERMINE -> repli OPTIMISTE",
     "    return NIVEAUX_CONFIANCE[3], motifs",
     "    return NIVEAUX_CONFIANCE[2], motifs"),
]


# Mutations qui ne PEUVENT PAS mordre, et dont l'inertie est elle-même une propriété à
# prouver. Les faire « passer » exigerait de fabriquer une entrée impossible ; la
# discipline est de les DÉCLARER, et d'exiger qu'elles restent VERTES. Si l'une venait à
# mordre, l'hypothèse de redondance serait tombée et il faudrait la réexaminer — le
# script échoue donc dans les DEUX sens.
REDONDANCES_DECLAREES = [
    ("dimensions_connues : booleen STRICT -> valeur vraie",
     '            and reference["dimensions_connues"] is True',
     '            and bool(reference["dimensions_connues"])',
     "qualite_photos._valider_photo porte deja la garde "
     "type(reference['dimensions_connues']) is not bool : la valeur est GARANTIE booleenne "
     "quand la classification s execute, donc `is True` et `bool(...)` sont equivalents. "
     "Epingle par test_le_type_booleen_de_dimensions_connues_est_garanti_en_amont."),
    ("MULTI_VUES : 3 photos -> 2 photos",
     "        nombre_photos >= 3\n", "        nombre_photos >= 2\n",
     "angles_distincts est le cardinal d un ensemble de valeurs prises sur les photos, donc "
     "angles_distincts <= nombre_photos toujours : la condition angles_distincts >= 3 IMPLIQUE "
     "nombre_photos >= 3. La borne est conservee parce que le critere d acceptation l enonce. "
     "Epinglee par test_trois_angles_distincts_impliquent_au_moins_trois_photos."),
]


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
    print()
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
      f"{len(REDONDANCES_DECLAREES)} redondances declarees et verifiees INERTES | "
      f"sources restaurees a l identique : {intact}")
sys.exit(1 if (echecs or not intact) else 0)
