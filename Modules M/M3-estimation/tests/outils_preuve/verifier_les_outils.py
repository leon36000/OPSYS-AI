#!/usr/bin/env python3
"""Vérifie que les gardes des outils de preuve mordent réellement.

Les preuves initiales affirmant que les gardes mordaient vivaient dans le pack de
revue : elles n'existaient donc nulle part sous la forme d'un instrument versionné
et rejouable. Un extrait Python recopié dans un dossier de revue n'est pas une
preuve reproductible ; c'est une affirmation dont personne ne peut contrôler la
portée, la branche, les sources ni les conditions d'exécution.

Ce script provoque la référence déjà rouge, l'extracteur vide et l'outil orphelin,
puis exige que les outils concernés sortent en erreur. Après chaque épreuve, il
contrôle aussi que tous les fichiers sous les sources M3 et les tests ont retrouvé
exactement leur contenu et leurs chemins initiaux.

Deux objections critiques convergentes ont toutefois relevé qu'un code de retour
non nul ne dit pas QUELLE garde a parlé. Sans contrôle négatif préalable ni motif
attendu, un instrument hors d'usage — erreur de syntaxe, import manquant ou
dépendance absente — serait certifié conforme. Chaque outil est donc d'abord exigé
sain sans sabotage, puis son échec provoqué doit contenir le motif propre à la
garde exercée. Le contrôle de discrimination compare aussi deux sabotages distincts
pour rendre un leurre plus coûteux ; il ne peut toutefois pas prouver qu'un autre
instrument n'est pas lui-même un leurre.
"""
import hashlib
import pathlib
import subprocess
import sys

MOTIFS_ATTENDUS = {
    "reference_rouge": ("ABANDON", "ROUGE"),
    "extracteur_vide": ("ABANDON", "extracteur"),
    "outil_orphelin": ("test_chaque_outil_de_mutation_a_son_module_cible",),
}

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
ESTIMATION = RACINE / "Modules M" / "M3-estimation"
SRC = ESTIMATION / "src" / "m3_estimation"
TESTS = ESTIMATION / "tests"
OUTILS = TESTS / "outils_preuve"
TEST_OUTILS = TESTS / "test_outils_de_preuve.py"
ENUMERER = OUTILS / "enumerer_gardes.py"

TEST_ROUGE = TESTS / "test_verifier_les_outils_temporaire.py"
MODULE_VIDE = SRC / "module_verifier_les_outils_sans_garde.py"
OUTIL_ORPHELIN = OUTILS / "muter_module_verifier_les_outils_orphelin.py"


def empreinte(chemin):
    """Retourne l'empreinte sha256 binaire d'un fichier."""
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def fichiers_controles():
    """Énumère tous les fichiers de contenu des sources et des tests."""
    for dossier in (SRC, TESTS):
        for chemin in sorted(dossier.rglob("*")):
            if not chemin.is_file():
                continue
            # Les caches Python et pytest sont des artefacts d'exécution, pas
            # du contenu livré : ils sont donc explicitement exclus du contrôle.
            if "__pycache__" in chemin.parts or ".pytest_cache" in chemin.parts:
                continue
            yield chemin


def relever_chemins():
    """Relève l'ensemble des chemins contrôlés, relatifs à la racine."""
    return {
        str(chemin.relative_to(RACINE))
        for chemin in fichiers_controles()
    }


def relever_empreintes():
    """Relève l'empreinte de tous les fichiers contrôlés, toute extension incluse."""
    return {
        str(chemin.relative_to(RACINE)): empreinte(chemin)
        for chemin in fichiers_controles()
    }


def retirer(chemin):
    """Retire un dépôt temporaire sans toucher aux fichiers préexistants."""
    if chemin.exists():
        chemin.unlink()


def lancer(commande):
    """Exécute une commande depuis la racine du dépôt."""
    return subprocess.run(
        commande,
        capture_output=True,
        text=True,
        cwd=RACINE,
    )


def verifier_restauration(etape, depots, empreintes_initiales, chemins_initiaux, echecs):
    """Contrôle les dépôts retirés, chemins et empreintes après une épreuve."""
    absents = [str(depot.relative_to(RACINE)) for depot in depots if depot.exists()]
    chemins_finaux = relever_chemins()
    empreintes_finales = relever_empreintes()
    conforme = (
        not absents
        and chemins_finaux == chemins_initiaux
        and empreintes_finales == empreintes_initiales
    )

    if conforme:
        return

    details = []
    if absents:
        details.append("dépôts encore présents : " + ", ".join(absents))

    chemins_manquants = sorted(chemins_initiaux - chemins_finaux)
    chemins_ajoutes = sorted(chemins_finaux - chemins_initiaux)
    if chemins_manquants:
        details.append("chemins disparus : " + ", ".join(chemins_manquants))
    if chemins_ajoutes:
        details.append("chemins ajoutés : " + ", ".join(chemins_ajoutes))

    manquants = sorted(set(empreintes_initiales) - set(empreintes_finales))
    ajoutes = sorted(set(empreintes_finales) - set(empreintes_initiales))
    modifies = sorted(
        nom
        for nom in set(empreintes_initiales) & set(empreintes_finales)
        if empreintes_initiales[nom] != empreintes_finales[nom]
    )
    if manquants:
        details.append("empreintes disparues : " + ", ".join(manquants))
    if ajoutes:
        details.append("empreintes ajoutées : " + ", ".join(ajoutes))
    if modifies:
        details.append("empreintes modifiées : " + ", ".join(modifies))

    print(
        f"Garde 4 — restauration après {etape} : ECHEC — "
        + "; ".join(details)
    )
    echecs.append(f"restauration après {etape}")


def sortie_complete(resultat):
    """Retourne stdout et stderr afin de contrôler le motif réel de l'échec."""
    return resultat.stdout + resultat.stderr


def verifier_etat_sain(nom_outil, commande):
    """Exige qu'un outil fonctionne avant que son sabotage soit créé."""
    resultat = lancer(commande)
    if resultat.returncode != 0:
        abandonner(
            f"outil cassé à l'état sain : {nom_outil} "
            f"(rc={resultat.returncode})"
        )


def exiger_morsure(libelle, resultat, motifs, echecs):
    """Exige l'échec et le motif qui identifie la garde réellement exercée."""
    if resultat.returncode == 0:
        print(f"{libelle} : rc=0 — ECHEC : la garde ne mord pas")
        echecs.append(libelle)
        return

    texte = sortie_complete(resultat)
    motifs_absents = [motif for motif in motifs if motif not in texte]
    if motifs_absents:
        print(
            f"{libelle} : rc={resultat.returncode} — ECHEC : "
            "la garde n'a pas été exercée ; cause inconnue "
            "(motif attendu absent : " + ", ".join(motifs_absents) + ")"
        )
        echecs.append(f"{libelle} (motif attendu absent)")
        return

    print(f"{libelle} : rc={resultat.returncode} — garde exercée")


def exiger_discrimination(libelle, sortie_a, sortie_b, echecs):
    """Exige que deux sabotages de nature distincte ne produisent pas le même message."""
    if sortie_a != sortie_b:
        print(f"{libelle} : messages distincts")
        return

    print(f"{libelle} : ECHEC : les deux sabotages produisent le même message")
    echecs.append(libelle)


def abandonner(message):
    """Refuse une conclusion positive lorsque le contrôle n'est pas probant."""
    print(f"ABANDON : {message} ; le contrôle n'est pas probant.")
    sys.exit(1)


if not SRC.is_dir():
    abandonner(f"répertoire source introuvable : {SRC}")
if not OUTILS.is_dir():
    abandonner(f"répertoire des outils introuvable : {OUTILS}")
if not TESTS.is_dir():
    abandonner(f"répertoire de tests introuvable : {TESTS}")
if not TEST_OUTILS.is_file():
    abandonner(f"test transverse introuvable : {TEST_OUTILS}")
if not ENUMERER.is_file():
    abandonner(f"outil transverse introuvable : {ENUMERER}")

MUTEURS = sorted(OUTILS.glob("muter_*.py"))
if not MUTEURS:
    abandonner(f"aucune batterie muter_*.py trouvée sous {OUTILS}")

for depot in (TEST_ROUGE, MODULE_VIDE, OUTIL_ORPHELIN):
    if depot.exists():
        abandonner(
            f"le dépôt temporaire attendu absent existe déjà : "
            f"{depot.relative_to(RACINE)}"
        )

CHEMINS_INITIAUX = relever_chemins()
EMPREINTES_INITIALES = relever_empreintes()
if not EMPREINTES_INITIALES:
    abandonner("aucun fichier à empreinter dans les périmètres contrôlés")

echecs = []
epreuves = 0

for muter in MUTEURS:
    libelle = f"Garde 1 — référence déjà ROUGE — {muter.name}"
    commande = [sys.executable, "-B", str(muter), str(RACINE)]
    try:
        verifier_etat_sain(muter.name, commande)
        TEST_ROUGE.write_text(
            'def test_echec_delibere_verifier_les_outils():\n'
            '    raise AssertionError("référence volontairement rouge")\n',
            encoding="utf-8",
        )
        resultat = lancer(commande)
        epreuves += 1
        exiger_morsure(
            libelle,
            resultat,
            MOTIFS_ATTENDUS["reference_rouge"],
            echecs,
        )
    finally:
        retirer(TEST_ROUGE)
        verifier_restauration(
            libelle,
            [TEST_ROUGE],
            EMPREINTES_INITIALES,
            CHEMINS_INITIAUX,
            echecs,
        )

libelle_rouge = "Garde 1 — référence déjà ROUGE — enumerer_gardes.py"
commande_enumerer = [sys.executable, "-B", str(ENUMERER), str(RACINE)]
sortie_rouge_enumerer = ""
try:
    verifier_etat_sain(ENUMERER.name, commande_enumerer)
    TEST_ROUGE.write_text(
        'def test_echec_delibere_verifier_les_outils():\n'
        '    raise AssertionError("référence volontairement rouge")\n',
        encoding="utf-8",
    )
    resultat_rouge = lancer(commande_enumerer)
    sortie_rouge_enumerer = sortie_complete(resultat_rouge)
    epreuves += 1
    exiger_morsure(
        libelle_rouge,
        resultat_rouge,
        MOTIFS_ATTENDUS["reference_rouge"],
        echecs,
    )
finally:
    retirer(TEST_ROUGE)
    verifier_restauration(
        libelle_rouge,
        [TEST_ROUGE],
        EMPREINTES_INITIALES,
        CHEMINS_INITIAUX,
        echecs,
    )

libelle_vide = "Garde 2 — extracteur vide — enumerer_gardes.py"
commande_extracteur = [
    sys.executable,
    "-B",
    str(ENUMERER),
    str(RACINE),
    MODULE_VIDE.stem,
]
sortie_vide_enumerer = ""
try:
    verifier_etat_sain(
        f"{ENUMERER.name} (cible saine existante)",
        commande_enumerer,
    )
    MODULE_VIDE.write_text(
        '"""Module temporaire volontairement dépourvu de garde."""\n'
        "\n"
        "def valeur():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    resultat_vide = lancer(commande_extracteur)
    sortie_vide_enumerer = sortie_complete(resultat_vide)
    epreuves += 1
    exiger_morsure(
        libelle_vide,
        resultat_vide,
        MOTIFS_ATTENDUS["extracteur_vide"],
        echecs,
    )
finally:
    retirer(MODULE_VIDE)
    verifier_restauration(
        libelle_vide,
        [MODULE_VIDE],
        EMPREINTES_INITIALES,
        CHEMINS_INITIAUX,
        echecs,
    )

# Cette discrimination rend un leurre plus coûteux, sans pouvoir démontrer
# qu'un instrument externe n'est pas lui-même un leurre.
exiger_discrimination(
    "Garde 2 bis — discrimination référence rouge / extracteur vide",
    sortie_rouge_enumerer,
    sortie_vide_enumerer,
    echecs,
)

libelle = "Garde 3 — outil orphelin — test_outils_de_preuve.py"
commande_pytest = [
    sys.executable,
    "-B",
    "-m",
    "pytest",
    str(TEST_OUTILS),
    "-q",
    "-p",
    "no:cacheprovider",
    "--color=no",
]
try:
    verifier_etat_sain(TEST_OUTILS.name, commande_pytest)
    OUTIL_ORPHELIN.write_text(
        '"""Outil temporaire dont la cible est volontairement absente."""\n'
        'SRC = "module_verifier_les_outils_orphelin.py"\n',
        encoding="utf-8",
    )
    resultat = lancer(commande_pytest)
    epreuves += 1
    exiger_morsure(
        libelle,
        resultat,
        MOTIFS_ATTENDUS["outil_orphelin"],
        echecs,
    )
finally:
    retirer(OUTIL_ORPHELIN)
    verifier_restauration(
        libelle,
        [OUTIL_ORPHELIN],
        EMPREINTES_INITIALES,
        CHEMINS_INITIAUX,
        echecs,
    )

if not epreuves:
    abandonner("aucune garde n'a pu être éprouvée")

print(f"bilan final : gardes éprouvées={epreuves}  échecs={len(echecs)}")
if echecs:
    print("gardes ne mordant pas ou restauration invalide : " + "; ".join(echecs))
    sys.exit(1)

sys.exit(0)
