"""AUD-CORE-006 — Oracle statique : aucun littéral de chemin hôte absolu
(`/home/`, `/Users/`, `/root/`) ne doit apparaître dans le code source de
`audit/core-baseline/`. Un test qui se lie à un tel littéral (au lieu de
lire `OPSYS_PACK`, ou de skipper proprement en son absence) ne mesure que
la présence d'un dossier sur UNE machine — c'est le défaut mesuré par
l'issue #570 (53 tests verts uniquement chez Nathan).

Ce fichier vit lui-même sous `audit/core-baseline/tests/` et doit, pour ses
propres fixtures synthétiques ci-dessous, contenir en toutes lettres les
motifs qu'il recherche — il s'auto-signalerait donc sans précaution. La
précaution retenue n'est PAS une exclusion par nom de fichier non vérifiée :
c'est l'identité RÉSOLUE de ce fichier précis (`Path(__file__).resolve()`),
et sa nécessité comme son étroitesse sont chacune prouvées par un test dédié
ci-dessous (`test_sans_exclusion_ce_fichier_s_auto_signalerait` et
`test_exclusion_par_defaut_ne_couvre_que_ce_fichier_precis`)."""
from __future__ import annotations

from pathlib import Path

import pytest

MOTIFS_CHEMIN_HOTE: tuple[str, ...] = ("/home/", "/Users/", "/root/")

# Racine du scan réel (le périmètre exact de l'issue #570).
AUDIT_CORE_BASELINE = Path(__file__).resolve().parent.parent

# Identité exacte de CE fichier — jamais un nom ou un motif générique.
CE_FICHIER = Path(__file__).resolve()

# Exclusion par défaut du scanner : un ensemble figé (frozenset) d'un seul
# chemin résolu. Sa cardinalité et son contenu exacts sont vérifiés par
# test_exclusion_par_defaut_ne_couvre_que_ce_fichier_precis plus bas — ce
# n'est pas une hypothèse, c'est une assertion exécutée.
EXCLUSION_PAR_DEFAUT: frozenset[Path] = frozenset({CE_FICHIER})


def trouver_chemins_hote_code_en_dur(
    racine: Path, *, exclure: frozenset[Path] = EXCLUSION_PAR_DEFAUT
) -> list[tuple[Path, int, str]]:
    """Scanne récursivement les `.py` sous `racine` et renvoie chaque
    occurrence (chemin, numéro de ligne 1-indexé, texte de la ligne) d'un
    des `MOTIFS_CHEMIN_HOTE`. `exclure` est un ensemble de chemins déjà
    résolus (identité de fichier, pas un motif de nom) — par défaut,
    seulement ce fichier de test lui-même."""
    trouvailles: list[tuple[Path, int, str]] = []
    for chemin in sorted(racine.rglob("*.py")):
        if chemin.resolve() in exclure:
            continue
        texte = chemin.read_text(encoding="utf-8")
        for numero, ligne in enumerate(texte.splitlines(), start=1):
            if any(motif in ligne for motif in MOTIFS_CHEMIN_HOTE):
                trouvailles.append((chemin, numero, ligne.strip()))
    return trouvailles


def _formater(trouvailles: list[tuple[Path, int, str]], racine: Path) -> str:
    return "\n".join(
        f"{chemin.relative_to(racine)}:{numero}: {ligne}"
        for chemin, numero, ligne in trouvailles
    )


# ---------------------------------------------------------------------------
# Oracle réel — RED tant qu'un littéral de chemin hôte traîne dans le
# périmètre exact de l'issue #570.
# ---------------------------------------------------------------------------


def test_aucun_chemin_hote_code_en_dur_dans_audit_core_baseline():
    """Rouge par le nom du test si un littéral /home/, /Users/ ou /root/
    apparaît dans un .py de audit/core-baseline/ (hors ce fichier — cf.
    exclusion ci-dessus, elle-même prouvée étroite plus bas)."""
    trouvailles = trouver_chemins_hote_code_en_dur(AUDIT_CORE_BASELINE)
    assert not trouvailles, (
        "chemin(s) hôte codé(s) en dur détecté(s) dans audit/core-baseline/ "
        "— faux succès potentiel au sens de l'issue #570 :\n"
        + _formater(trouvailles, AUDIT_CORE_BASELINE)
    )


# ---------------------------------------------------------------------------
# Preuve que le détecteur n'est pas vide (fixtures synthétiques, tmp_path —
# hors de audit/core-baseline/ réel, donc jamais vues par le test ci-dessus).
# ---------------------------------------------------------------------------


def test_detecteur_signale_un_fichier_synthetique_avec_litteral(tmp_path):
    """Injecte un faux fichier contenant un littéral /home/ dans un dossier
    jetable et vérifie qu'il est bien signalé, avec le bon numéro de ligne."""
    faux = tmp_path / "module_sale.py"
    faux.write_text(
        "import os\n"
        'DEFAUT = os.environ.get("OPSYS_PACK", "/home/pc1/core-pack/exemple")\n',
        encoding="utf-8",
    )
    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path, exclure=frozenset())
    assert trouvailles == [(faux.resolve(), 2, trouvailles[0][2])]
    assert "/home/pc1/core-pack/exemple" in trouvailles[0][2]


def test_detecteur_ne_signale_pas_un_fichier_propre(tmp_path):
    """Fichier propre (aucun motif de chemin hôte, seulement une lecture
    d'environnement) : jamais signalé — sinon l'oracle serait bruyant au
    point d'être ignoré en pratique."""
    propre = tmp_path / "module_propre.py"
    propre.write_text(
        'import os\nPACK_ROOT = os.environ.get("OPSYS_PACK")\n', encoding="utf-8"
    )
    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path, exclure=frozenset())
    assert trouvailles == []


def test_detecteur_signale_plusieurs_fichiers_independamment(tmp_path):
    """Deux faux fichiers, un seul sale : la présence d'un fichier propre ne
    doit ni masquer ni contaminer le signalement de l'autre."""
    sale = tmp_path / "a_sale.py"
    sale.write_text('P = "/root/pack"\n', encoding="utf-8")
    propre = tmp_path / "b_propre.py"
    propre.write_text('P = os.environ.get("OPSYS_PACK")\n', encoding="utf-8")
    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path, exclure=frozenset())
    fichiers_signales = {chemin for chemin, _, _ in trouvailles}
    assert fichiers_signales == {sale.resolve()}


# ---------------------------------------------------------------------------
# Preuve dédiée de la non-auto-signalisation — pas une exclusion par nom
# acceptée sans vérification (cf. consigne AUD-CORE-006).
# ---------------------------------------------------------------------------


def test_sans_exclusion_ce_fichier_s_auto_signalerait():
    """Preuve que l'exclusion par défaut n'est pas décorative : SANS elle,
    ce fichier de test — qui porte les fixtures synthétiques ci-dessus,
    donc les motifs recherchés en toutes lettres — s'auto-signale bel et
    bien. La relaxe plus haut comble un vrai risque, pas un risque supposé."""
    trouvailles = trouver_chemins_hote_code_en_dur(AUDIT_CORE_BASELINE, exclure=frozenset())
    fichiers_signales = {chemin for chemin, _, _ in trouvailles}
    assert CE_FICHIER in fichiers_signales


def test_exclusion_par_defaut_ne_couvre_que_ce_fichier_precis():
    """L'exclusion par défaut est l'identité résolue d'exactement un
    fichier — ce précis fichier — jamais un nom, un suffixe ou un motif
    générique qui pourrait, lui, avaler silencieusement une vraie
    régression ailleurs dans audit/core-baseline/."""
    assert EXCLUSION_PAR_DEFAUT == frozenset({CE_FICHIER})
    assert len(EXCLUSION_PAR_DEFAUT) == 1


def test_exclusion_par_defaut_ne_masque_pas_une_vraie_violation_ailleurs(tmp_path):
    """Preuve croisée : même avec l'exclusion par défaut de CE fichier
    active, une violation injectée dans un AUTRE fichier — y compris un
    fichier qui se trouverait être un dossier tests/ jetable distinct —
    reste détectée. L'exclusion ne couvre que ce qu'elle nomme."""
    autre = tmp_path / "tests" / "test_autre_module.py"
    autre.parent.mkdir(parents=True)
    autre.write_text('PACK_ROOT = Path("/home/quelquun/pack")\n', encoding="utf-8")
    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path, exclure=EXCLUSION_PAR_DEFAUT)
    fichiers_signales = {chemin for chemin, _, _ in trouvailles}
    assert autre.resolve() in fichiers_signales
