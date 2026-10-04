#!/usr/bin/env python3
"""Batterie de mutations MÉTIER sur la garde anti-précision-inventée.

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
import subprocess
import sys
import tempfile

# Ces batteries sont des SCRIPTS lancés directement ; le dossier du script est alors en
# tête de sys.path et l'import ci-dessous fonctionne. On ne s'appuie pas sur cet effet de
# bord : le chemin est inséré explicitement, pour que l'import tienne quel que soit le
# répertoire courant et le mode de lancement.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _environnement_mutation import EnvironnementMutation
from lecture_junit import echecs_junit as _echecs_junit

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SRC = RACINE / "departments/m03-estimation/src/m3_estimation/blocage_prix.py"
original = SRC.read_text(encoding="utf-8")

MUTATIONS = [
    ("bornes : None -> zero (un zero se lit comme un prix)",
     '        "borne_basse": None,\n        "borne_haute": None,',
     '        "borne_basse": 0.0,\n        "borne_haute": 0.0,'),
    ("ordre EPINGLE : le verdict qui NOMME cede a l echappatoire",
     "        verdict_estimation = (\n"
     "            VERDICT_QUALITE_INSUFFISANTE if qualite_insuffisante else VERDICT_INDETERMINE\n"
     "        )",
     "        verdict_estimation = (\n"
     "            VERDICT_INDETERMINE if niveau_indetermine else VERDICT_QUALITE_INSUFFISANTE\n"
     "        )"),
    ("la regle de blocage : OU -> ET (une seule cause ne bloque plus)",
     "    if qualite_insuffisante or niveau_indetermine:",
     "    if qualite_insuffisante and niveau_indetermine:"),
    ("le niveau INDETERMINE ne bloque plus",
     "    if qualite_insuffisante or niveau_indetermine:",
     "    if qualite_insuffisante:"),
    ("la qualite insuffisante ne bloque plus",
     "    if qualite_insuffisante or niveau_indetermine:",
     "    if niveau_indetermine:"),
    ("raison_blocage : le constat disparait du chemin bloque",
     '            "raison_blocage": _construire_raison(\n                verdict_estimation, '
     'qualification["elements_manquants"]\n            ),',
     '            "raison_blocage": "blocage",'),
    ("taux nominal de l intervalle -> le nom du niveau (le defaut d origine)",
     '        "niveau": NIVEAU_CONFIANCE_NOMINAL,',
     '        "niveau": niveau_confiance,'),
    ("verdict hors blocage -> un verdict BLOQUANT",
     '        "verdict_estimation": VERDICT_AUCUN_BLOCAGE,',
     '        "verdict_estimation": VERDICT_INDETERMINE,'),
    ("prix_bloque : True -> False sur le chemin bloque",
     '            "prix_bloque": True,', '            "prix_bloque": False,'),
    ("prix_bloque : False -> True sur le chemin non bloque",
     '        "prix_bloque": False,', '        "prix_bloque": True,'),
]

REDONDANCES_DECLAREES = []


# La liste ci-dessus est VIDE, et c'est un résultat, pas un oubli : les dix mutations de ce
# module mordent toutes, aucune n'a dû être requalifiée en redondance. Elle reste déclarée
# pour que l'apparition d'une première entrée soit un geste visible en revue — déclarer
# qu'une mutation ne mord pas doit coûter une ligne de justification, jamais un silence.


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
    descripteur, nom_rapport = tempfile.mkstemp(prefix="muter_blocage_prix_", suffix=".xml")
    os.close(descripteur)
    rapport = pathlib.Path(nom_rapport)
    try:
        resultat = subprocess.run(
            # Ce dossier contient les tests qui LANCENT ces batteries ; les inclure crée une
            # récursion mutuelle qui a mesurablement ramené la détection à 0/15 et laissé des
            # sources MUTÉES sur le disque. Une sentinelle sur disque ne suffit pas : elle ne
            # survit pas aux exécutions concurrentes. L'exclusion est explicite et locale.
            [
                sys.executable, "-B", "-m", "pytest", str(_ENV.dossier_tests), "-q",
                f"--ignore={_ENV.dossier_tests / 'test_gardes_des_outils.py'}",
                # test_outils_de_preuve.py lance lui-meme une batterie complete (preuve
                # dynamique PLAN T0.12) : l'inclure crée la même récursion mutuelle que
                # test_gardes_des_outils.py ci-dessus.
                f"--ignore={_ENV.dossier_tests / 'test_outils_de_preuve.py'}",
                f"--ignore={_ENV.dossier_tests / 'test_campagne_m3_persistante.py'}",
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
_ENV = EnvironnementMutation(RACINE)
_CIBLE = _ENV.cible(SRC)
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
                compile(mutant, str(_CIBLE), "exec")
            except SyntaxError as erreur:
                echecs.append(f"{nom} : ne compile pas ({erreur.msg})")
                print(f"{nom:<52} -> NE COMPILE PAS")
                # Le scénario de compilation invalide est un échec fermé : annoncer
                # seulement le refus, sans continuer ni imprimer de bilan validant.
                sys.exit(1)

            _CIBLE.write_text(mutant, encoding="utf-8")
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
            compile(mutant, str(_CIBLE), "exec")
            _CIBLE.write_text(mutant, encoding="utf-8")
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
    _ENV.nettoyer()

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
