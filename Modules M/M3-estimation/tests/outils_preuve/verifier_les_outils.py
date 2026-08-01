#!/usr/bin/env python3
"""Vérifie que les gardes des outils de preuve mordent réellement.

Les preuves initiales affirmant que les gardes mordaient vivaient dans le pack de
revue : elles n'existaient donc nulle part sous la forme d'un instrument versionné
et rejouable. Un extrait Python recopié dans un dossier de revue n'est pas une
preuve reproductible ; c'est une affirmation dont personne ne peut contrôler la
portée, la branche, les sources ni les conditions d'exécution.

Ce script provoque la référence déjà rouge, l'extracteur vide et l'outil orphelin,
puis exige que les outils concernés sortent en erreur. Après chaque épreuve, il
contrôle aussi que tous les fichiers Python sources et tous les outils ont retrouvé
exactement leur empreinte sha256 initiale.

Deux objections critiques convergentes ont toutefois relevé qu'un code de retour
non nul ne dit pas QUELLE garde a parlé. Sans contrôle négatif préalable ni motif
attendu, un instrument hors d'usage — erreur de syntaxe, import manquant ou
dépendance absente — serait certifié conforme. Chaque outil est donc d'abord exigé
sain sans sabotage, puis son échec provoqué doit contenir le motif propre à la
garde exercée.
"""
import hashlib
import pathlib
import subprocess
import sys

# Un code de retour seul ne distingue pas « la garde a mordu » de « l'outil est
# cassé » : chaque sabotage doit produire son motif distinctif.
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


def relever_empreintes():
    """Relève toutes les empreintes Python des sources et des outils."""
    resultat = {}
    for dossier in (SRC, OUTILS):
        for chemin in sorted(dossier.rglob("*.py")):
            resultat[str(chemin.relative_to(RACINE))] = empreinte(chemin)
    return resultat


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


def verifier_restauration(etape, depots, empreintes_initiales, echecs):
    """Contrôle les dépôts retirés et l'identité exacte de toutes les empreintes."""
    absents = [str(depot.relative_to(RACINE)) for depot in depots if depot.exists()]
    empreintes_finales = relever_empreintes()
    conforme = not absents and empreintes_finales == empreintes_initiales

    if conforme:
        return

    details = []
    if absents:
        details.append("dépôts encore présents : " + ", ".join(absents))

    manquants = sorted(set(empreintes_initiales) - set(empreintes_finales))
    ajoutes = sorted(set(empreintes_finales) - set(empreintes_initiales))
    modifies = sorted(
        nom
        for nom in set(empreintes_initiales) & set(empreintes_finales)
        if empreintes_initiales[nom] != empreintes_finales[nom]
    )
    if manquants:
        details.append("fichiers disparus : " + ", ".join(manquants))
    if ajoutes:
        details.append("fichiers ajoutés : " + ", ".join(ajoutes))
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

EMPREINTES_INITIALES = relever_empreintes()
if not EMPREINTES_INITIALES:
    abandonner("aucun fichier Python à empreinter dans les périmètres contrôlés")

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
            echecs,
        )

libelle = "Garde 1 — référence déjà ROUGE — enumerer_gardes.py"
commande_enumerer = [sys.executable, "-B", str(ENUMERER), str(RACINE)]
try:
    verifier_etat_sain(ENUMERER.name, commande_enumerer)
    TEST_ROUGE.write_text(
        'def test_echec_delibere_verifier_les_outils():\n'
        '    raise AssertionError("référence volontairement rouge")\n',
        encoding="utf-8",
    )
    resultat = lancer(commande_enumerer)
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
        echecs,
    )

libelle = "Garde 2 — extracteur vide — enumerer_gardes.py"
commande_extracteur = [
    sys.executable,
    "-B",
    str(ENUMERER),
    str(RACINE),
    MODULE_VIDE.stem,
]
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
    resultat = lancer(commande_extracteur)
    epreuves += 1
    exiger_morsure(
        libelle,
        resultat,
        MOTIFS_ATTENDUS["extracteur_vide"],
        echecs,
    )
finally:
    retirer(MODULE_VIDE)
    verifier_restauration(
        libelle,
        [MODULE_VIDE],
        EMPREINTES_INITIALES,
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
        echecs,
    )

if not epreuves:
    abandonner("aucune garde n'a pu être éprouvée")

print(f"bilan final : gardes éprouvées={epreuves}  échecs={len(echecs)}")
if echecs:
    print("gardes ne mordant pas ou restauration invalide : " + "; ".join(echecs))
    sys.exit(1)

sys.exit(0)
