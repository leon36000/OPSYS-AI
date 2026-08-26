"""AUD-CORE-006 — Oracle statique : aucun littéral de chemin hôte absolu ne
doit apparaître dans le code source scanné de `audit/core-baseline/`. Un
test qui se lie à un tel littéral (au lieu de lire `OPSYS_PACK`, ou de
skipper proprement en son absence) ne mesure que la présence d'un dossier
sur UNE machine — c'est le défaut mesuré par l'issue #570 (53 tests verts
uniquement chez Nathan).

AUD-CORE-006 tour 2 (revue aveugle, mesurée fondée) — deux angles morts de
l'oracle lui-même, fermés ici :

1. AUTO-EXCLUSION. Mesuré : une recherche textuelle du premier motif de
   `MOTIFS_CHEMIN_HOTE` sur `audit/core-baseline/` rendait encore 7
   occurrences, toutes dans CE fichier — la version
   précédente excluait explicitement `Path(__file__).resolve()` du scan
   pour ne pas se signaler elle-même (ses fixtures synthétiques
   contiennent, par construction, les motifs recherchés). Cette exclusion
   créait un angle mort MESURÉ : un vrai littéral de chemin hôte ajouté
   dans ce fichier n'aurait jamais été détecté. Fermé en ne s'excluant
   plus JAMAIS soi-même : les motifs (`MOTIFS_CHEMIN_HOTE`) et les
   littéraux de fixtures ci-dessous sont composés PAR FRAGMENTS au moment
   de l'exécution (cf. `_fragment_motif` / `_chemin_hote_synthetique`) —
   la sous-chaîne contiguë complète (préfixe encadré de barres obliques)
   n'apparaît donc JAMAIS en texte source de ce fichier, qui n'a dès lors
   plus besoin d'aucune exclusion pour se scanner proprement lui-même.
   Preuve exécutée par
   `test_un_litteral_injecte_dans_une_copie_de_ce_fichier_est_detecte`
   (mutation sur une COPIE hors dépôt, jamais dans le fichier réel).

2. PÉRIMÈTRE DE FICHIERS. Mesuré : `racine.rglob("*.py")` ignorait les 8
   CSV, 5 JSON, 1 MD et 1 TXT réellement présents dans
   `audit/core-baseline/` — un littéral de chemin hôte dans
   STAGE-EVIDENCE.csv ou CANONICAL-PATH-MAP.json, par exemple, passait
   inaperçu. Fermé en étendant le scan à `EXTENSIONS_SCANNEES`. Décision
   PRISE ET DOCUMENTÉE sur `/media/`, `/mnt/`, `/opt/` : délibérément PAS
   ajoutés aux motifs recherchés (voir le commentaire sur
   `MOTIFS_CHEMIN_HOTE` ci-dessous) — `TARGET.json`, artefact généré hors
   de l'autorité d'écriture de cette tâche, porte déjà légitimement
   `"worktree": "/media/pc1/Storage/opsys-core-v2.3.0"` ; ajouter le
   préfixe media ferait rougir l'oracle sur un fichier qu'AUD-CORE-006 n'a
   pas le droit de corriger dans son périmètre autorisé."""
from __future__ import annotations

from pathlib import Path

import pytest


def _fragment_motif(prefixe: str) -> str:
    """Compose, à l'EXÉCUTION, un motif de chemin hôte absolu en encadrant
    `prefixe` de deux barres obliques — jamais en texte contigu dans le
    SOURCE de ce fichier, sinon ce fichier s'auto-signalerait dès qu'il est
    lui-même scanné (plus aucune exclusion ne le couvre, cf. point 1 de la
    docstring du module)."""
    return f"/{prefixe}/"


# Préfixes de chemin absolu propres à UN poste de développement — jamais
# les 3 motifs complets écrits en toutes lettres ici (cf. _fragment_motif
# ci-dessus : c'est précisément ce qui évite l'auto-signalement).
_PREFIXES_HOTE: tuple[str, ...] = ("home", "Users", "root")
MOTIFS_CHEMIN_HOTE: tuple[str, ...] = tuple(_fragment_motif(p) for p in _PREFIXES_HOTE)

# AUD-CORE-006 tour 2 (mesuré) : les préfixes de montage media, mnt et opt
# sont tout aussi propres à UN poste que les trois préfixes ci-dessus
# (home, Users, root) — mais NE SONT PAS ajoutés à MOTIFS_CHEMIN_HOTE.
# TARGET.json (généré, hors périmètre
# d'écriture de cette tâche — cf. docstring du module) porte déjà
# "worktree": "/media/pc1/Storage/opsys-core-v2.3.0", un vrai chemin hôte
# absolu. Étendre les motifs au préfixe media tout en étendant le scan aux
# .json (EXTENSIONS_SCANNEES ci-dessous) ferait rougir l'oracle sur ce
# fichier généré SANS qu'on puisse le corriger ici. Arbitrage retenu :
# garder exactement les 3 motifs du critère littéral de l'issue #570
# (home, Users, root) ; media, mnt et opt restent une limitation connue, à
# traiter quand TARGET.json pourra être régénéré ou corrigé (hors périmètre
# ABSOLU de cette tâche).


def _chemin_hote_synthetique(prefixe: str, reste: str) -> str:
    """Compose, pour les fixtures synthétiques ci-dessous, un littéral de
    chemin hôte complet en accolant `_fragment_motif(prefixe)` et `reste`
    — SANS jamais faire apparaître le motif complet en texte contigu dans
    CE fichier source (même précaution que `_fragment_motif`)."""
    return f"{_fragment_motif(prefixe)}{reste}"


# Racine du scan réel (le périmètre exact de l'issue #570).
AUDIT_CORE_BASELINE = Path(__file__).resolve().parent.parent

# Identité de CE fichier — n'est plus utilisée pour une exclusion (il n'y en
# a plus, cf. docstring du module). Sert uniquement de SOURCE pour la
# mutation hors dépôt de
# test_un_litteral_injecte_dans_une_copie_de_ce_fichier_est_detecte.
CE_FICHIER = Path(__file__).resolve()

# AUD-CORE-006 tour 2 (mesuré) : un .rglob("*.py") seul ignorait les 8 CSV,
# 5 JSON, 1 MD et 1 TXT réellement présents dans audit/core-baseline/ — un
# littéral de chemin hôte dans STAGE-EVIDENCE.csv ou
# CANONICAL-PATH-MAP.json, par exemple, y passerait inaperçu. Étendu à ces
# 4 extensions ; voir le commentaire sur MOTIFS_CHEMIN_HOTE ci-dessus pour
# l'arbitrage media/mnt/opt qui accompagne cette extension.
EXTENSIONS_SCANNEES: tuple[str, ...] = (".py", ".csv", ".json", ".md", ".txt")


def trouver_chemins_hote_code_en_dur(
    racine: Path, *, exclure: frozenset[Path] = frozenset()
) -> list[tuple[Path, int, str]]:
    """Scanne récursivement les fichiers de `EXTENSIONS_SCANNEES` sous
    `racine` et renvoie chaque occurrence (chemin, numéro de ligne
    1-indexé, texte de la ligne) d'un des `MOTIFS_CHEMIN_HOTE`. `exclure`
    est un ensemble de chemins déjà résolus (identité de fichier, pas un
    motif de nom) — VIDE par défaut : aucune exclusion, y compris de ce
    fichier de test lui-même (angle mort fermé en tour 2, cf. docstring du
    module)."""
    trouvailles: list[tuple[Path, int, str]] = []
    candidats = (
        chemin
        for chemin in racine.rglob("*")
        if chemin.is_file() and chemin.suffix in EXTENSIONS_SCANNEES
    )
    for chemin in sorted(candidats):
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
# périmètre exact de l'issue #570 (désormais élargi aux 5 extensions de
# EXTENSIONS_SCANNEES, et sans aucune exclusion — pas même ce fichier).
# ---------------------------------------------------------------------------


def test_aucun_chemin_hote_code_en_dur_dans_audit_core_baseline():
    """Rouge par le nom du test si un des `MOTIFS_CHEMIN_HOTE` apparaît
    dans un fichier de `EXTENSIONS_SCANNEES` sous `audit/core-baseline/` —
    AUCUNE exclusion, pas même de ce fichier de test lui-même."""
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
    """Injecte un faux fichier contenant un littéral de chemin hôte (motif
    composé par fragments, cf. `_chemin_hote_synthetique` — jamais écrit en
    toutes lettres ici) dans un dossier jetable et vérifie qu'il est bien
    signalé, avec le bon chemin, le bon numéro de ligne ET le bon texte de
    ligne — chaque champ comparé à une valeur littérale construite
    indépendamment.

    AUD-CORE-006 tour 2 (revue aveugle, mesurée fondée) : la version
    précédente comparait `trouvailles == [(faux.resolve(), 2,
    trouvailles[0][2])]` — le 3e élément du tuple attendu était le 3e
    élément du tuple obtenu, une portion qui ne peut structurellement
    jamais échouer, et qui aurait levé `IndexError` (pas un échec
    d'assertion) si `trouvailles` avait été vide. Même motif que le commit
    `a32d99c` sur main (« remove tautological encoding assertions »).
    Fermé en vérifiant d'abord la CARDINALITÉ, puis chaque CHAMP contre une
    valeur composée séparément du code testé."""
    chemin_hote = _chemin_hote_synthetique("home", "pc1/core-pack/exemple")
    ligne_attendue = f'DEFAUT = os.environ.get("OPSYS_PACK", "{chemin_hote}")'
    faux = tmp_path / "module_sale.py"
    faux.write_text(f"import os\n{ligne_attendue}\n", encoding="utf-8")

    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)

    assert len(trouvailles) == 1, f"attendu exactement 1 trouvaille, obtenu : {trouvailles!r}"
    chemin, numero, ligne = trouvailles[0]
    assert chemin == faux.resolve()
    assert numero == 2
    assert ligne == ligne_attendue


def test_detecteur_ne_signale_pas_un_fichier_propre(tmp_path):
    """Fichier propre (aucun motif de chemin hôte, seulement une lecture
    d'environnement) : jamais signalé — sinon l'oracle serait bruyant au
    point d'être ignoré en pratique."""
    propre = tmp_path / "module_propre.py"
    propre.write_text(
        'import os\nPACK_ROOT = os.environ.get("OPSYS_PACK")\n', encoding="utf-8"
    )
    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)
    assert trouvailles == []


def test_detecteur_signale_plusieurs_fichiers_independamment(tmp_path):
    """Deux faux fichiers, un seul sale : la présence d'un fichier propre ne
    doit ni masquer ni contaminer le signalement de l'autre."""
    sale = tmp_path / "a_sale.py"
    sale.write_text(f'P = "{_chemin_hote_synthetique("root", "pack")}"\n', encoding="utf-8")
    propre = tmp_path / "b_propre.py"
    propre.write_text('P = os.environ.get("OPSYS_PACK")\n', encoding="utf-8")
    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)
    fichiers_signales = {chemin for chemin, _, _ in trouvailles}
    assert fichiers_signales == {sale.resolve()}


def test_detecteur_scanne_recursivement_les_sous_dossiers(tmp_path):
    """Preuve de récursion : une violation dans un sous-dossier imbriqué
    (ex. un dossier tests/ jetable, comme le serait un vrai
    audit/core-baseline/tests/) est détectée au même titre qu'un fichier à
    la racine du périmètre scanné — `rglob`, jamais un glob limité au
    premier niveau."""
    autre = tmp_path / "tests" / "test_autre_module.py"
    autre.parent.mkdir(parents=True)
    litteral = _chemin_hote_synthetique("home", "quelquun/pack")
    autre.write_text(f'PACK_ROOT = Path("{litteral}")\n', encoding="utf-8")
    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)
    fichiers_signales = {chemin for chemin, _, _ in trouvailles}
    assert autre.resolve() in fichiers_signales


# ---------------------------------------------------------------------------
# Extension du périmètre de fichiers (AUD-CORE-006 tour 2, mesurée) — pas
# seulement les .py.
# ---------------------------------------------------------------------------


def test_detecteur_scanne_aussi_csv_json_md_txt_pas_seulement_py(tmp_path):
    """AUD-CORE-006 tour 2 (mesurée fondée) : un `.rglob("*.py")` seul
    laissait passer un littéral de chemin hôte dans un `.csv`, un `.json`,
    un `.md` ou un `.txt` — types réellement présents dans
    `audit/core-baseline/` (STAGE-EVIDENCE.csv, CANONICAL-PATH-MAP.json,
    RIVAL-SOURCES-DISPOSITION.md, GIT-REFS.txt). Les 4 types sont testés
    indépendamment ici, avec un `.py` propre en contrôle négatif dans le
    même dossier — sa présence ne doit ni masquer ni remplacer la
    détection dans les 4 autres fichiers."""
    litteral = _chemin_hote_synthetique("home", "pc1/core-pack/x")
    fichiers_sales = {
        tmp_path / "data.csv": f"colonne\n{litteral}\n",
        tmp_path / "config.json": f'{{"chemin": "{litteral}"}}\n',
        tmp_path / "notes.md": f"Voir {litteral} pour le détail.\n",
        tmp_path / "refs.txt": f"{litteral}\n",
    }
    for chemin, contenu in fichiers_sales.items():
        chemin.write_text(contenu, encoding="utf-8")
    (tmp_path / "propre.py").write_text(
        'PACK_ROOT = os.environ.get("OPSYS_PACK")\n', encoding="utf-8"
    )

    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)

    fichiers_signales = {chemin for chemin, _, _ in trouvailles}
    assert fichiers_signales == {chemin.resolve() for chemin in fichiers_sales}


def test_detecteur_ignore_les_extensions_hors_perimetre(tmp_path):
    """Frontière volontaire du scan (`EXTENSIONS_SCANNEES`) : un fichier
    d'une extension non listée n'est jamais lu, même s'il contient
    littéralement un motif de chemin hôte — décision documentée (cf.
    docstring du module), pas un oubli."""
    litteral = _chemin_hote_synthetique("home", "pc1/core-pack/x")
    (tmp_path / "binaire.lock").write_text(litteral, encoding="utf-8")
    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)
    assert trouvailles == []


# ---------------------------------------------------------------------------
# Fermeture de l'angle mort d'auto-exclusion (AUD-CORE-006 tour 2, mesurée)
# — remplace les 2 tests qui ne justifiaient que le mécanisme d'exclusion
# supprimé (`test_sans_exclusion_ce_fichier_s_auto_signalerait` et
# `test_exclusion_par_defaut_ne_couvre_que_ce_fichier_precis`, tour 1).
# ---------------------------------------------------------------------------


def test_un_litteral_injecte_dans_une_copie_de_ce_fichier_est_detecte(tmp_path):
    """Preuve que l'angle mort d'auto-exclusion est fermé : plus aucune
    exclusion ne couvre ce fichier de test. Mutation exécutée sur une
    COPIE de ce fichier placée hors du dépôt (`tmp_path` — un dossier
    jetable pytest, jamais le worktree réel ni le fichier réel) : un
    littéral de chemin hôte ajouté DANS L'ORACLE LUI-MÊME doit désormais
    être détecté, exactement comme n'importe quel autre fichier du
    périmètre scanné."""
    litteral_injecte = _chemin_hote_synthetique("home", "quelquun/injecte-dans-l-oracle")
    contenu_mute = (
        CE_FICHIER.read_text(encoding="utf-8")
        + f'\n_LITTERAL_DE_MUTATION_INJECTE_PAR_LE_TEST = "{litteral_injecte}"\n'
    )
    copie = tmp_path / "copie_de_l_oracle.py"
    copie.write_text(contenu_mute, encoding="utf-8")

    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)

    par_fichier: dict[Path, list[tuple[int, str]]] = {}
    for chemin, numero, ligne in trouvailles:
        par_fichier.setdefault(chemin, []).append((numero, ligne))
    assert copie.resolve() in par_fichier, (
        "un littéral de chemin hôte ajouté dans une copie de ce fichier "
        "(l'oracle lui-même) n'a pas été détecté — l'angle mort mesuré en "
        "revue serait rouvert"
    )
    assert any(litteral_injecte in ligne for _, ligne in par_fichier[copie.resolve()])
