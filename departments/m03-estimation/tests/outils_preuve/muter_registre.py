"""Batterie de mutations métier sur le registre hash-chaîné M3.

Les neuf mutations de ``MUTATIONS`` doivent toutes mordre. Les deux protections
de rang sont déclarées redondantes individuellement : le chaînage détecte les
altérations structurelles lorsque l'une seule est neutralisée. Leur
neutralisation combinée est néanmoins exécutée et doit rester INERTE, car le
chaînage demeure actif et porte seul la détection des retraits, permutations et
duplications de maillons.

Cette inertie combinée confirme la déclaration de redondance. Si elle venait à
MORDRE, ce serait cette déclaration qui tomberait ; ce cas fait donc échouer
l'instrument. La mutation du chaînage est exécutée séparément et doit MORDRE :
elle établit que ce contrôle porte réellement la détection des réécritures
cohérentes d'un maillon intermédiaire et étaye ainsi la déclaration de
redondance au lieu de la supposer.
"""

import os
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _environnement_mutation import EnvironnementMutation
from lecture_junit import echecs_junit as _echecs_junit

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SRC = RACINE / "departments/m03-estimation/src/m3_estimation/registre.py"
original = SRC.read_text(encoding="utf-8")

MUTATIONS = [
    (
        "le hash precedent est retire du hachage",
        '''            "rang": rang,
            "hash_precedent": hash_precedent,''',
        '''            "rang": rang,''',
    ),
    (
        "le predecesseur initial conventionnel est altere",
        '''HASH_PREDECESSEUR_INITIAL = (
    "0000000000000000000000000000000000000000000000000000000000000000"
)''',
        '''HASH_PREDECESSEUR_INITIAL = (
    "1111111111111111111111111111111111111111111111111111111111111111"
)''',
    ),
    (
        "le tri canonique des dictionnaires est neutralise",
        '''        elements.sort(key=lambda paire: paire[0])''',
        '''        elements = list(elements)''',
    ),
    (
        "le controle d integrite propre est neutralise",
        '''                if maillon["hash_maillon"] != hash_recalcule:''',
        '''                if False:''',
    ),
    (
        "la lecture renvoie la reference interne vivante",
        '''        return copy.deepcopy(self._maillons)''',
        '''        return self._maillons''',
    ),
    (
        "la charge ajoutee n est plus copiee defensivement",
        '''            charge_copiee = copy.deepcopy(charge)''',
        '''            charge_copiee = charge''',
    ),
    (
        "la place du cout reel n est plus reservee a None",
        '''            cout_reel = None''',
        '''            cout_reel = 0''',
    ),
    (
        "la garde des cles de charge requises est neutralisee",
        '''        if not _CLES_CHARGE_REQUISES.issubset(charge):''',
        '''        if False:''',
    ),
    (
        "le controle de chainage est neutralise",
        '''                if maillon["hash_precedent"] != hash_attendu_precedent:''',
        '''                if False:''',
    ),
]

REDONDANCES_DECLAREES = [
    (
        "le rang est retire du hachage",
        '''            "rang": rang,
            "hash_precedent": hash_precedent,''',
        '''            "hash_precedent": hash_precedent,''',
    ),
    (
        "le controle de correspondance rang position est neutralise",
        '''                if type(maillon["rang"]) is not int or maillon["rang"] != rang:''',
        '''                if False:''',
    ),
]


def purge():
    _ENV.purger_caches()


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
        prefix="muter_registre_", suffix=".xml"
    )
    os.close(descripteur)
    rapport = pathlib.Path(nom_rapport)
    try:
        resultat = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                str(_ENV.dossier_tests),
                "-q",
                f"--ignore={_ENV.dossier_tests / 'test_gardes_des_outils.py'}",
                # test_outils_de_preuve.py lance lui-meme une batterie complete (preuve
                # dynamique PLAN T0.12) : l'inclure crée la même récursion mutuelle que
                # test_gardes_des_outils.py ci-dessus.
                f"--ignore={_ENV.dossier_tests / 'test_outils_de_preuve.py'}",
                "-p",
                "no:cacheprovider",
                "--color=no",
                f"--junitxml={rapport}",
            ],
            capture_output=True,
            text=True,
            cwd=RACINE,
        )
        sortie = resultat.stdout + resultat.stderr
        return resultat, _echecs_junit(rapport) | _echecs_sortie(sortie), sortie
    finally:
        rapport.unlink(missing_ok=True)


def appliquer(texte, avant, apres):
    if texte.count(avant) != 1:
        raise ValueError(f"ancre x{texte.count(avant)}")
    resultat = texte.replace(avant, apres, 1)
    if resultat == texte:
        raise ValueError("mutation sans effet")
    compile(resultat, str(_CIBLE), "exec")
    return resultat


def lancer_mutant(nom, mutant, echecs_reference, attend_rouge):
    _CIBLE.write_text(mutant, encoding="utf-8")
    purge()
    resultat, echecs_mutant, sortie = executer_tests()
    nouveaux = echecs_mutant - echecs_reference
    rouge = resultat.returncode != 0 and bool(nouveaux)

    if attend_rouge:
        etat = "ROUGE" if rouge else "NON DETECTEE"
        if not rouge:
            print(sortie.rstrip())
        print(f"{nom:<58} -> {etat}")
        return rouge

    verte = resultat.returncode == 0
    etat = "INERTE" if verte else "MORD (HYPOTHESE TOMBEE)"
    if not verte:
        print(sortie.rstrip())
    print(f"[declaree] {nom:<47} -> {etat}")
    return verte


if not MUTATIONS:
    print("ABANDON : MUTATIONS est vide.")
    sys.exit(1)

echecs = []
mordues = 0
_ENV = EnvironnementMutation(RACINE)
_CIBLE = _ENV.cible(SRC)
try:
    purge()
    reference, echecs_reference, sortie_reference = executer_tests()
    if reference.returncode != 0:
        # Phrase d'abandon CANONIQUE, commune aux batteries : un test du dépôt
        # l'exige nommément. Une batterie qui mute une suite déjà rouge ne mesure
        # rien — chaque mutant paraîtrait mordre pour la faute d'un autre.
        echecs.append("reference deja rouge")
        print("ABANDON : muter une suite non verte ne prouve rien.")
        print(sortie_reference.rstrip())
    else:
        for nom, avant, apres in MUTATIONS:
            try:
                mutant = appliquer(original, avant, apres)
                if lancer_mutant(nom, mutant, echecs_reference, True):
                    mordues += 1
                else:
                    echecs.append(f"{nom} : ne mord pas")
            except (SyntaxError, ValueError) as erreur:
                echecs.append(f"{nom} : {erreur}")
                print(f"{nom:<58} -> INSTRUMENT INVALIDE ({erreur})")

        mutants_redondance = []
        for nom, avant, apres in REDONDANCES_DECLAREES:
            try:
                mutant = appliquer(original, avant, apres)
                mutants_redondance.append((nom, avant, apres))
                if not lancer_mutant(nom, mutant, echecs_reference, False):
                    echecs.append(f"{nom} : redondance individuelle invalidée")
            except (SyntaxError, ValueError) as erreur:
                echecs.append(f"{nom} : {erreur}")

        if len(mutants_redondance) == 2:
            try:
                combine = original
                for _, avant, apres in mutants_redondance:
                    combine = appliquer(combine, avant, apres)
                # La mesure DÉCLARÉE est que la combinaison reste INERTE : c'est
                # elle qui établit que le contrôle de chaînage porte seul la
                # détection des trois modes d'altération éprouvés. On attend donc
                # le VERT. Si la combinaison venait à MORDRE, ce serait la
                # déclaration de redondance qui tomberait, et c'est ce cas-là qui
                # doit faire échouer l'instrument.
                if not lancer_mutant(
                    "neutralisation combinee des deux controles de rang",
                    combine,
                    echecs_reference,
                    False,
                ):
                    echecs.append(
                        "combinaison des controles de rang : elle MORD, donc la "
                        "redondance declaree est REFUTEE — reecrire la declaration"
                    )
            except (SyntaxError, ValueError) as erreur:
                echecs.append(f"combinaison des controles de rang : {erreur}")
finally:
    _ENV.nettoyer()

intact = SRC.read_text(encoding="utf-8") == original
print(
    f"\n{mordues}/{len(MUTATIONS)} mordent | "
    f"sources restaurees a l identique : {intact}"
)
sys.exit(1 if echecs or not intact else 0)
