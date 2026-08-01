#!/usr/bin/env python3
"""Vérifie que les gardes des outils de preuve mordent réellement.

Les preuves initiales affirmant que les gardes mordaient vivaient dans le pack de
revue : elles n'existaient donc nulle part sous la forme d'un instrument versionné
et rejouable. Un extrait Python recopié dans un dossier de revue n'est pas une
preuve reproductible ; c'est une affirmation dont personne ne peut contrôler la
portée, la branche, les sources ni les conditions d'exécution.

Ce script répond aux quatre objections critiques convergentes soulevées contre ce
défaut. Il provoque la référence déjà rouge, l'extracteur vide et l'outil orphelin,
puis exige que les outils concernés sortent en erreur. Après chaque épreuve, il
contrôle aussi que tous les fichiers Python sources et tous les outils ont retrouvé
exactement leur empreinte sha256 initiale. Ainsi, le vérificateur ne se contente pas
d'affirmer que les gardes existent : il rejoue les conditions qui doivent les faire
mordre et refuse de conclure si l'instrument laisse la moindre trace.
"""
import hashlib
import pathlib
import subprocess
import sys

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
        print(f"Garde 4 — restauration après {etape} : conforme")
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


def exiger_morsure(libelle, resultat, echecs):
    """Enregistre le code observé et exige que la garde fasse échouer l'outil."""
    print(f"{libelle} : rc={resultat.returncode}")
    if resultat.returncode == 0:
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

EMPREINTES_INITIALES = relever_empreintes()
if not EMPREINTES_INITIALES:
    abandonner("aucun fichier Python à empreinter dans les périmètres contrôlés")

echecs = []
epreuves = 0

for muter in MUTEURS:
    libelle = f"Garde 1 — référence déjà ROUGE — {muter.name}"
    resultat = None
    try:
        TEST_ROUGE.write_text(
            'def test_echec_delibere_verifier_les_outils():\n'
            '    raise AssertionError("référence volontairement rouge")\n',
            encoding="utf-8",
        )
        resultat = lancer([sys.executable, "-B", str(muter), str(RACINE)])
        epreuves += 1
        exiger_morsure(libelle, resultat, echecs)
    finally:
        retirer(TEST_ROUGE)
        verifier_restauration(
            libelle,
            [TEST_ROUGE],
            EMPREINTES_INITIALES,
            echecs,
        )

libelle = "Garde 1 — référence déjà ROUGE — enumerer_gardes.py"
try:
    TEST_ROUGE.write_text(
        'def test_echec_delibere_verifier_les_outils():\n'
        '    raise AssertionError("référence volontairement rouge")\n',
        encoding="utf-8",
    )
    resultat = lancer([sys.executable, "-B", str(ENUMERER), str(RACINE)])
    epreuves += 1
    exiger_morsure(libelle, resultat, echecs)
finally:
    retirer(TEST_ROUGE)
    verifier_restauration(
        libelle,
        [TEST_ROUGE],
        EMPREINTES_INITIALES,
        echecs,
    )

libelle = "Garde 2 — extracteur vide — enumerer_gardes.py"
try:
    MODULE_VIDE.write_text(
        '"""Module temporaire volontairement dépourvu de garde."""\n'
        "\n"
        "def valeur():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    resultat = lancer(
        [
            sys.executable,
            "-B",
            str(ENUMERER),
            str(RACINE),
            MODULE_VIDE.stem,
        ]
    )
    epreuves += 1
    exiger_morsure(libelle, resultat, echecs)
finally:
    retirer(MODULE_VIDE)
    verifier_restauration(
        libelle,
        [MODULE_VIDE],
        EMPREINTES_INITIALES,
        echecs,
    )

libelle = "Garde 3 — outil orphelin — test_outils_de_preuve.py"
try:
    OUTIL_ORPHELIN.write_text(
        '"""Outil temporaire dont la cible est volontairement absente."""\n'
        'SRC = "module_verifier_les_outils_orphelin.py"\n',
        encoding="utf-8",
    )
    resultat = lancer(
        [
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
    )
    epreuves += 1
    exiger_morsure(libelle, resultat, echecs)
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
