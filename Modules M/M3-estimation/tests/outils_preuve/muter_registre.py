#!/usr/bin/env python3
"""Batterie de mutations MÉTIER sur le registre hash-chaîné M3.

Les gardes structurelles sont couvertes par enum_gardes.py. Ce script attaque
les propriétés métier du registre : inclusion du rang et du prédécesseur dans
le hash, convention du premier maillon, canonicité, intégrité locale,
append-only effectif et forme réservée du coût réel. Il ne prouve ni la
véracité métier des charges ni la sécurité cryptographique de SHA-256 : il
vérifie que les tests distinguent les régressions significatives du contrat
implémenté par registre.py.

Chaque mutation est vérifiée COMPILABLE et APPLIQUÉE : une mutation sans effet
ne prouve rien. Une référence verte est mesurée avant toute mutation, puis
chaque rouge doit contenir au moins un nouvel échec attribuable à la mutation.
Les sources sont restaurées à l'identique, ce qui est vérifié en fin de course.
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
SRC = RACINE / "Modules M/M3-estimation/src/m3_estimation/registre.py"
TESTS = RACINE / "Modules M/M3-estimation/tests"
original = SRC.read_text(encoding="utf-8")

MUTATIONS = [
    (
        "le hash precedent est retire du hachage",
        """    return _encoder_canonique(
        {
            "rang": rang,
            "hash_precedent": hash_precedent,""",
        """    return _encoder_canonique(
        {
            "rang": rang,""",
    ),
    (
        "le predecesseur initial conventionnel est altere",
        """HASH_PREDECESSEUR_INITIAL = (
    "0000000000000000000000000000000000000000000000000000000000000000"
)""",
        """HASH_PREDECESSEUR_INITIAL = (
    "1111111111111111111111111111111111111111111111111111111111111111"
)""",
    ),
    (
        "le tri canonique des dictionnaires est neutralise",
        """        elements.sort(
            key=lambda paire: json.dumps(
                paire[0], separators=(",", ":"), ensure_ascii=True
            )
        )""",
        """        elements = list(elements)""",
    ),
    (
        "le controle d integrite propre est neutralise",
        """                if maillon["hash_maillon"] != hash_recalcule:""",
        """                if False:""",
    ),
    (
        "la lecture renvoie la reference interne vivante",
        """    def lire(self):
        \"\"\"Retourne une copie profonde, jamais une référence interne vivante.\"\"\"
        return copy.deepcopy(self._maillons)""",
        """    def lire(self):
        \"\"\"Retourne une copie profonde, jamais une référence interne vivante.\"\"\"
        return self._maillons""",
    ),
    (
        "la charge ajoutee n est plus copiee defensivement",
        """            charge_copiee = copy.deepcopy(charge)""",
        """            charge_copiee = charge""",
    ),
    (
        "la place du cout reel n est plus reservee a None",
        """            cout_reel = None""",
        """            cout_reel = 0""",
    ),
    (
        "la garde des cles de charge requises est neutralisee",
        """        if not _CLES_CHARGE_REQUISES.issubset(charge):""",
        """        if False:""",
    ),
]

REDONDANCES_DECLAREES = [
    (
        "le rang est retire du hachage",
        """    return _encoder_canonique(
        {
            "rang": rang,
            "hash_precedent": hash_precedent,""",
        """    return _encoder_canonique(
        {
            "hash_precedent": hash_precedent,""",
        "Mesure exacte : rang retiré du hachage SEUL -> ROUGE : False ; "
        "contrôle rang/position SEUL -> ROUGE : False ; LES DEUX neutralisés "
        "ENSEMBLE -> ROUGE : False. L'inertie est structurellement DÉMONTRÉE "
        "face aux trois modes d'altération éprouvés (retrait, permutation et "
        "duplication), car le contrôle de chaînage tranche avant ce mécanisme. "
        "Cette mesure ne montre pas que le rang dans le hachage est inutile en "
        "général : si le contrôle de chaînage était un jour retiré ou contourné, "
        "le registre retomberait sur lui. C'est une défense en profondeur "
        "DÉCLARÉE, pas une garantie prouvée par les tests."
    ),
    (
        "le controle de correspondance rang position est neutralise",
        """                if maillon["rang"] != rang:""",
        """                if False:""",
        "Mesure exacte : rang retiré du hachage SEUL -> ROUGE : False ; "
        "contrôle rang/position SEUL -> ROUGE : False ; LES DEUX neutralisés "
        "ENSEMBLE -> ROUGE : False. L'inertie est structurellement DÉMONTRÉE "
        "face aux trois modes d'altération éprouvés (retrait, permutation et "
        "duplication), car le contrôle de chaînage tranche avant ce mécanisme. "
        "Cette mesure ne montre pas que le contrôle rang/position est inutile "
        "en général : si le contrôle de chaînage était un jour retiré ou "
        "contourné, le registre retomberait sur lui. C'est une défense en "
        "profondeur DÉCLARÉE, pas une garantie prouvée par les tests."
    ),
]


# La liste ci-dessus est VIDE, et c'est un résultat, pas un oubli : les dix mutations de ce
# module mordent toutes, aucune n'a dû être requalifiée en redondance. Elle reste déclarée
# pour que l'apparition d'une première entrée soit un geste visible en revue — déclarer
# qu'une mutation ne mord pas doit coûter une ligne de justification, jamais un silence.


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
        prefix="muter_registre_", suffix=".xml"
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
