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
   inaperçu. Fermé en étendant le scan à `EXTENSIONS_SCANNEES`.

AUD-CORE-006 tour 3 (tâche de suivi) — la limitation laissée sciemment
ouverte au tour 2 est LEVÉE, avec sa cause racine :

3. PRÉFIXES DE POINT DE MONTAGE (media, mnt, opt). Le tour 2 les avait
   délibérément écartés des motifs pour une raison d'AUTORITÉ, jamais de
   fond : `TARGET.json` — artefact généré, hors des 5 fichiers que la
   tâche AUD-CORE-006 pouvait écrire — portait un vrai chemin hôte absolu
   dans son champ `worktree` (un point de montage propre à UNE machine).
   Ajouter le préfixe correspondant aurait rendu l'oracle rouge sur un
   fichier non corrigeable dans le périmètre d'alors.

   Autorité du champ, établie dans le CODE et non dans un état GitHub :
   `worktree` est écrit par `custody.py` (`_ancre_worktree_portable`), PAS
   par `path_and_authority_map.py` — `grep -n TARGET
   audit/core-baseline/path_and_authority_map.py` ne rend rien. Rejouable
   à tout moment, sur n'importe quel clone, sans réseau.

   Le constat de non-collision entre branches est daté par nature : il vit
   dans la description de la pull request, jamais ici. Un fichier versionné
   qui énumère les pull requests ouvertes et leurs fichiers devient faux à
   l'ouverture de la suivante — y compris celle qui le porte.

   Le champ a été rendu portable des DEUX côtés — générateur (ancre
   relative, cf. `ANCRE_WORKTREE_PORTABLE` dans `custody.py` et le
   commentaire qui la justifie) et artefact committé — puis les trois
   préfixes ont rejoint `_PREFIXES_HOTE`. Aucun d'eux n'apparaît en
   littéral contigu ici, docstring comprise : la composition par fragments
   du point 1 les couvre exactement de la même façon."""
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


# Préfixes de chemin absolu propres à UN poste — jamais écrits ici en
# motifs complets (cf. _fragment_motif ci-dessus : c'est précisément ce qui
# évite l'auto-signalement).
#
# Les 3 premiers sont le critère littéral de l'issue #570. Les 3 suivants
# (points de montage) les ont rejoints au tour 3, une fois `TARGET.json`
# rendu portable — cf. point 3 de la docstring du module pour la raison
# d'autorité qui les avait fait écarter au tour 2, et
# `test_les_six_prefixes_exacts_sont_couverts` pour le verrou de
# non-régression sur cette liste.
#
# FRONTIÈRE VOLONTAIRE, déclarée sur le modèle d'`EXTENSIONS_SCANNEES` :
# cette liste ne prétend PAS à l'exhaustivité des points de montage. Sont
# notamment NON couverts /srv, /data, /var et /Volumes (macOS) — mesuré,
# un littéral les employant passe l'oracle au vert. Sont également hors de
# portée d'un scanner de sous-chaîne contiguë : la casse différente, le
# séparateur Windows, l'échappement JSON, et tout chemin composé à
# l'exécution (concaténation, os.path.join, f-string, variable
# d'environnement) — c'est la technique que ce module emploie
# délibérément sur lui-même, et elle vaut donc aussi comme contournement.
# Élargir la liste exige de modifier `_PREFIXES_ATTENDUS` dans le même
# geste : c'est le seul chemin d'extension, et il est délibérément bruyant.
#
# L'AUTRE MOITIÉ DE LA FRONTIÈRE — les faux POSITIFS. La recherche est une
# sous-chaîne NON ANCRÉE : tout chemin RELATIF ou toute URL dont un segment
# médian porte l'un des préfixes est signalé comme « chemin hôte absolu ».
# Un fichier QUI SERAIT rangé sous un répertoire nommé `media`, ou une URL
# dont un segment médian s'appellerait `media`, seraient signalés — mesuré
# sur fixture, aucun objet de ce nom n'existant aujourd'hui dans l'arbre.
# Le risque est en revanche DÉJÀ MATÉRIALISÉ, et là c'est mesuré sur l'arbre
# réel : ajouter `data` — l'un des préfixes cités ci-dessus comme non
# couverts — rend l'oracle ROUGE, non pas sur un chemin hôte mais sur la
# ligne 325 de `FILE-INVENTORY.csv`, qui inventorie un fichier sous un
# répertoire nommé `data` : un chemin RELATIF généré, pas un chemin de poste.
#
# QUATRE AUTRES LIMITES, mesurées en revue et PRÉEXISTANTES à ce correctif —
# `trouver_chemins_hote_code_en_dur` est identique à sa version sur `main`.
# Nommées ici parce que cette section a pour objet de dire ce que l'oracle
# ne voit pas, et qu'une frontière énoncée à moitié rassure autant qu'une
# frontière tue :
#   1. La casse du SUFFIXE de fichier n'est pas normalisée : un `.CSV`, un
#      `.Json` ou un `.PY` n'est jamais lu. Distinct de la casse du LITTÉRAL
#      déjà nommée plus haut.
#   2. Rien n'atteste que le scan RÉEL a visité au moins un fichier. Si
#      `AUDIT_CORE_BASELINE` cessait de désigner un répertoire peuplé,
#      l'oracle rendrait vert en ne couvrant rien, sans qu'aucun test rougisse.
#   3. Les liens symboliques sont traités de façon asymétrique : un lien de
#      FICHIER est suivi et son contenu hors périmètre est lu et imputé au
#      lien ; un lien de RÉPERTOIRE n'est pas parcouru et masque son sous-arbre.
#   4. Un seul octet non-UTF8 dans un fichier scanné interrompt le scan
#      ENTIER par exception. Échec BRUYANT, jamais un faux vert — mais les
#      fichiers suivants ne sont alors plus examinés.
# (Ces exemples sont écrits en nommant le segment plutôt qu'en collant les
# barres autour : un commentaire qui illustre le motif le déclencherait,
# et cette note en a fait la démonstration en rendant l'oracle rouge.)
# C'est la raison de fond de ne pas élargir à l'aveugle : chaque préfixe
# ajouté est aussi un nom de répertoire que le dépôt peut légitimement
# employer.
_PREFIXES_HOTE: tuple[str, ...] = ("home", "Users", "root", "media", "mnt", "opt")
MOTIFS_CHEMIN_HOTE: tuple[str, ...] = tuple(_fragment_motif(p) for p in _PREFIXES_HOTE)


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
# 4 extensions. C'est cette extension aux .json qui rendait l'oracle rouge
# sur le champ `worktree` de TARGET.json dès que les préfixes de montage
# rejoignaient les motifs — cf. point 3 de la docstring du module.
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


# ---------------------------------------------------------------------------
# Couverture des préfixes (AUD-CORE-006 tour 3) — les 3 préfixes de point de
# montage écartés au tour 2 pour une raison d'autorité, ajoutés ici une fois
# TARGET.json rendu portable. Cf. point 3 de la docstring du module.
# ---------------------------------------------------------------------------

# Liste GOLDEN, écrite indépendamment de `_PREFIXES_HOTE`. Paramétrer les
# tests ci-dessous sur `_PREFIXES_HOTE` lui-même serait tautologique :
# retirer un préfixe retirerait AUSSI son cas de test, et la suite
# repasserait au vert en couvrant strictement moins — le motif exact que le
# commit `a32d99c` sur main a retiré ailleurs (« remove tautological
# encoding assertions »). Ici, retirer un préfixe rend RED.
_PREFIXES_ATTENDUS: tuple[str, ...] = ("home", "Users", "root", "media", "mnt", "opt")


def test_les_six_prefixes_exacts_sont_couverts():
    """Verrou sur la LISTE elle-même : ni rétrécissement silencieux (le
    défaut réel — le tour 2 n'en couvrait que 3), ni élargissement
    accidentel qui rendrait l'oracle bruyant. La composition attendue des
    motifs est reconstruite ici à partir de la liste golden, sans passer
    par `_fragment_motif` — sinon le test ne comparerait la fonction qu'à
    elle-même."""
    assert _PREFIXES_HOTE == _PREFIXES_ATTENDUS
    assert MOTIFS_CHEMIN_HOTE == tuple("/" + prefixe + "/" for prefixe in _PREFIXES_ATTENDUS)


@pytest.mark.parametrize("prefixe", _PREFIXES_ATTENDUS)
def test_chaque_prefixe_est_reellement_detecte(tmp_path, prefixe):
    """Chaque préfixe est prouvé VIVANT dans le détecteur, un par un :
    figurer dans un tuple ne prouve pas qu'il déclenche.

    Ce que ce test ferme EN PROPRE, et lui seul : une **comparaison cassée**
    dans `trouver_chemins_hote_code_en_dur` — par exemple n'y confronter
    qu'une partie de `MOTIFS_CHEMIN_HOTE`. Mesuré : cette mutation laisse
    `test_les_six_prefixes_exacts_sont_couverts` au VERT et fait rougir ce
    test-ci sur les préfixes devenus muets.

    Ce que ce test NE PEUT PAS fermer, et il faut le dire plutôt que le
    laisser croire : un **motif mal composé** (`_fragment_motif` renvoyant
    autre chose que `/<prefixe>/`). Sa fixture est construite PAR
    `_chemin_hote_synthetique`, donc par `_fragment_motif` elle-même : sur
    ce point précis il comparerait la fonction à elle-même, et il reste
    VERT quand le détecteur est mort. Mesuré : `_fragment_motif` renvoyant
    `/<prefixe>/zzz` laisse les 6 cas de ce test au vert.

    Le motif mal composé est fermé par le SECOND assert de
    `test_les_six_prefixes_exacts_sont_couverts`, qui recompose les motifs
    attendus sans passer par `_fragment_motif`. C'est le seul filet sur ce
    cas : le retirer rend la suite intégralement verte avec un détecteur
    mort. Les deux tests sont complémentaires, aucun ne subsume l'autre."""
    litteral = _chemin_hote_synthetique(prefixe, "pc1/core-pack/exemple")
    faux = tmp_path / "module_sale.py"
    faux.write_text(f'PACK = "{litteral}"\n', encoding="utf-8")

    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)

    assert len(trouvailles) == 1, f"attendu 1 trouvaille pour {prefixe!r}, obtenu : {trouvailles!r}"
    chemin, numero, ligne = trouvailles[0]
    assert chemin == faux.resolve()
    assert numero == 1
    assert litteral in ligne


@pytest.mark.parametrize("prefixe", ("media", "mnt", "opt"))
def test_un_champ_worktree_de_json_avec_prefixe_de_montage_est_detecte(tmp_path, prefixe):
    """Non-régression NOMMÉE sur le défaut réellement mesuré : un champ
    `worktree` portant un chemin hôte absolu de point de montage, dans un
    `.json` de la forme exacte de `TARGET.json`. Avant le tour 3, ce
    fichier passait DEUX fois inaperçu — préfixe hors motifs (tour 1) puis
    hors motifs par arbitrage d'autorité (tour 2). Il est désormais
    signalé ; le vrai `TARGET.json`, lui, ne porte plus de chemin absolu
    (cf. `ANCRE_WORKTREE_PORTABLE` dans `custody.py`), donc l'oracle réel
    reste vert sans exclusion ni tolérance."""
    litteral = _chemin_hote_synthetique(prefixe, "pc1/Storage/opsys-core-v2.3.0")
    cible = tmp_path / "TARGET.json"
    cible.write_text(
        '{\n  "branch": "opsys-core/core-v2.3.0-integration",\n'
        f'  "worktree": "{litteral}",\n  "dirty": false\n}}\n',
        encoding="utf-8",
    )

    trouvailles = trouver_chemins_hote_code_en_dur(tmp_path)

    fichiers_signales = {chemin for chemin, _, _ in trouvailles}
    assert fichiers_signales == {cible.resolve()}
    assert any(litteral in ligne for _, _, ligne in trouvailles)


def test_une_ancre_relative_dans_un_champ_worktree_nest_jamais_signalee(tmp_path):
    """Contrôle négatif de la correction retenue : la valeur RÉELLEMENT
    écrite désormais dans `TARGET.json` ne doit pas déclencher l'oracle —
    sinon la correction n'aurait fait que déplacer le rouge. Le contenu
    reproduit la sortie réelle du générateur (`ANCRE_WORKTREE_PORTABLE`)."""
    cible = tmp_path / "TARGET.json"
    cible.write_text(
        '{\n  "branch": "opsys-core/core-v2.3.0-integration",\n'
        '  "worktree": ".",\n  "dirty": false\n}\n',
        encoding="utf-8",
    )
    assert trouver_chemins_hote_code_en_dur(tmp_path) == []

