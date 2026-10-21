#!/usr/bin/env python3
"""Batterie de mutations MÉTIER sur l'assemblage du devis M3.

Ce script vérifie que les tests du module devis verrouillent les propriétés
gelées qui portent le contrat métier : encodage déterministe du devis_id,
forme canonique de l'empreinte M2, garde de longueur protégeant l'encodage,
priorité des verdicts et cohérence entre blocage et intervalle produit. Il ne
prouve ni l'absence de collision du SHA-256 tronqué, ni la validité métier
des données fournies par les modules amont : ces propriétés sont hors de la
portée de devis.py. Une mutation ne compte que si elle crée un nouvel échec
par rapport à une référence explicitement mesurée verte.
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
SRC = RACINE / "departments/m03-estimation/src/m3_estimation/devis.py"
original = SRC.read_text(encoding="utf-8")

MUTATIONS = [
    (
        "largeur du prefixe de longueur alteree",
        '_FORMAT_LONGUEUR = "04d"',
        '_FORMAT_LONGUEUR = "03d"',
    ),
    (
        "troncature du condensat alteree",
        "    ).hexdigest()[:16]",
        "    ).hexdigest()[:15]",
    ),
    (
        "prefixe devis altere",
        '_PREFIXE_DEVIS_ID = "M3-DEVIS-"',
        '_PREFIXE_DEVIS_ID = "M3-DEVIS-V2-"',
    ),
    (
        "ordre lead et empreinte permute dans l encodage",
        """        format(len(lead_id), _FORMAT_LONGUEUR)
        + lead_id
        + format(len(empreinte_marqueur_m2), _FORMAT_LONGUEUR)
        + empreinte_marqueur_m2""",
        """        format(len(empreinte_marqueur_m2), _FORMAT_LONGUEUR)
        + empreinte_marqueur_m2
        + format(len(lead_id), _FORMAT_LONGUEUR)
        + lead_id""",
    ),
    (
        "garde de longueur du lead neutralisee",
        "    if len(lead_id) > _LONGUEUR_MAXIMALE_ENCODABLE:",
        "    if False:",
    ),
    (
        "longueur exigee de l empreinte neutralisee",
        "        and len(empreinte) == _LONGUEUR_EMPREINTE",
        "        and True",
    ),
    (
        "exigence de minuscules de l empreinte neutralisee",
        """        and all(
            caractere in _CARACTERES_HEXADECIMAUX_MINUSCULES
            for caractere in empreinte
        )""",
        "        and True",
    ),
    (
        "cle litterale hash_maillon alteree",
        '"hash_maillon": hash_maillon,',
        '"hash_maillon_v2": hash_maillon,',
    ),
    (
        "rangs qualite et reference permutes",
        """    contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,
    contrats.VERDICT_REFERENCE_ECHELLE_ABSENTE,""",
        """    contrats.VERDICT_REFERENCE_ECHELLE_ABSENTE,
    contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,""",
    ),
    (
        "bornes bloquees None ne sont plus imposees",
        "        return borne_basse is None and borne_haute is None",
        "        return True",
    ),
]

REDONDANCES_DECLAREES = []

# La liste ci-dessus est VIDE, et c'est un résultat, pas un oubli : les mutations de ce
# module mordent toutes, aucune n'a dû être requalifiée en redondance structurelle. Elle
# reste déclarée pour que l'apparition d'une première entrée soit un geste visible en revue
# — déclarer qu'une mutation ne mord pas doit coûter une ligne de justification, jamais un
# silence.


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
        prefix="muter_devis_", suffix=".xml"
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
                continue

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
