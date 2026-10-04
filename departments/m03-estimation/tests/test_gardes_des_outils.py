"""Les gardes des outils de preuve sont vérifiées directement par pytest.

Ces tests remplacent un vérificateur monolithique dont la complexité était devenue
le goulot : après sept rondes de revue, chaque itération avait apporté son défaut
propre. Les mêmes propriétés tiennent ici en quelques lignes lisibles, isolées par
pytest et exécutées par la CI.

PLAN T0.12-suite : cette épreuve dépose deux artefacts volontairement défectueux
(un test rouge, un module sans garde) pour vérifier que les outils les détectent,
et une copie sabotée d'un outil pour vérifier le signalement d'une mutation non
compilable. Jusqu'ici, ces trois artefacts étaient écrits directement dans les
VRAIS dossiers du département (``departments/m03-estimation/tests``,
``.../tests/outils_preuve`` et ``.../src/m3_estimation``), puis retirés dans un
``finally`` — le même schéma « écrire puis restaurer » dont l'incident du
2026-09-28 (PLAN T0.12, voir ``_environnement_mutation.py``) a montré le risque :
un processus tué entre l'écriture et le retrait laisse le fichier en place, la
suite suivante échoue, et un ``git add -A`` le commiterait. Cette épreuve utilise
désormais la MÊME ``EnvironnementMutation`` que les outils de mutation qu'elle
éprouve : chaque artefact est écrit dans une copie jetable du département, jamais
sous sa vraie racine, et un ``kill -9`` en cours de route laisse au pire un
dossier orphelin sous le répertoire temporaire du système — jamais une trace dans
le dépôt. Preuves structurelle et dynamique de cette propriété, dans l'esprit de
celles de T0.12 : ``test_l_epreuve_des_gardes_n_ecrit_jamais_sous_la_vraie_racine_
du_departement`` et ``test_empreinte_de_src_et_tests_identique_apres_confection_
d_une_epreuve`` en fin de fichier.

Limite assumée : ces tests certifient que les gardes se déclenchent sur les
sabotages effectués ici. Ils ne certifient pas les instruments contre un auteur
hostile : un outil simulant exactement les messages attendus passerait. Un
instrument ne peut pas prouver qu'un autre instrument n'est pas un leurre.
"""

import ast
import hashlib
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

# EnvironnementMutation (PLAN T0.12, `_environnement_mutation.py`) : copie jetable du
# département, jamais la vraie source. Importé comme le font enumerer_gardes.py et
# chaque muter_<module>.py : chemin explicite (pas l'effet de bord d'un lancement
# direct), calculé depuis __file__ pour ne dépendre d'aucune affectation ci-dessous.
sys.path.insert(0, str(Path(__file__).resolve().parent / "outils_preuve"))
from _environnement_mutation import EnvironnementMutation

# Ce sont des PHRASES, et non des mots isolés : un mot pourrait être présent dans
# une sortie saine ou dans une erreur sans rapport et ne discriminerait pas la garde.
PHRASE_SUITE_ROUGE = "muter une suite non verte ne prouve rien"
PHRASE_SANS_GARDE = "l'extracteur n'a rien trouvé"
PHRASE_NE_COMPILE_PAS = "NE COMPILE PAS"

_M3 = Path(__file__).resolve().parents[1]
_RACINE = Path(__file__).resolve().parents[3]
_TESTS = _M3 / "tests"
_SOURCE = _M3 / "src" / "m3_estimation"
_OUTILS = _TESTS / "outils_preuve"
_ENUMERATEUR = _OUTILS / "enumerer_gardes.py"
_OUTILS_MUTATION = sorted(_OUTILS.glob("muter_*.py"))

# Noms de fichier des deux artefacts déposés par cette épreuve, dans la copie jetable —
# jamais sous la vraie racine du département (voir la docstring du module).
_NOM_SUITE_ROUGE = "test_epreuve_garde_suite_rouge"
_NOM_MODULE_SANS_GARDE = "epreuve_module_sans_garde"


def _modules_disponibles():
    """Retourne les modules cibles des outils de mutation, dans un ordre stable."""
    modules = sorted(outil.stem[len("muter_"):] for outil in _OUTILS_MUTATION)
    assert modules, (
        "aucun module disponible : aucun outil muter_<module>.py trouvé, "
        "le chemin nominal de l'énumérateur ne prouve rien"
    )
    return modules


def _module_nominal():
    """Retourne un module existant garanti par les outils de mutation présents."""
    return _modules_disponibles()[0]


def _parametres_outils():
    """Conserve un cas exécutable afin qu'une liste vide échoue explicitement."""
    return _OUTILS_MUTATION or [None]


def _parametres_tous_outils():
    """Ajoute l'énumérateur aux outils devant être sains à l'état nominal."""
    outils = [*_OUTILS_MUTATION, _ENUMERATEUR]
    return outils or [None]


def _identifier_outil(outil):
    return outil.name if outil is not None else "aucun-outil-de-mutation"


def _exiger_outil(outil):
    assert _OUTILS_MUTATION, (
        "aucun outil de mutation trouvé : le contrôle n'est pas probant, "
        "car un scanner vide passe toujours"
    )
    assert outil is not None, "outil de mutation absent malgré une paramétrisation active"


def _exiger_tous_les_outils(outil):
    assert _OUTILS_MUTATION, (
        "aucun outil de mutation trouvé : le contrôle n'est pas probant, "
        "car un scanner vide passe toujours"
    )
    assert _ENUMERATEUR.exists(), f"énumérateur absent : {_ENUMERATEUR}"
    assert outil is not None, "outil absent malgré une paramétrisation active"


def _sortie(resultat):
    return resultat.stdout + "\n" + resultat.stderr


def _lancer(outil, *arguments, racine=None):
    """Lance ``outil`` avec ``racine`` en argv[1] ET en cwd, même convention que les
    outils eux-mêmes (voir ``_environnement_mutation.py``). Par défaut, la vraie
    racine du dépôt — cas nominal, sans artefact déposé, déjà sans risque depuis
    T0.12 (l'outil crée sa propre copie interne). Un appelant qui a déposé un
    artefact rouge passe explicitement ``racine=<dossier d'une EnvironnementMutation>``
    pour que CET outil, à son tour, copie CETTE copie plutôt que la vraie source.
    """
    racine = _RACINE if racine is None else racine
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(outil),
            str(racine),
            *arguments,
        ],
        capture_output=True,
        text=True,
        cwd=racine,
    )


def _arguments_nominals(outil):
    if outil == _ENUMERATEUR:
        return (_module_nominal(),)
    return ()


def _empreinte_chemin(chemin):
    """Retourne sha256 et mode ; un dossier a une empreinte vide stable."""
    mode = chemin.stat().st_mode & 0o7777
    if chemin.is_dir():
        return hashlib.sha256(b"").hexdigest(), mode
    return hashlib.sha256(chemin.read_bytes()).hexdigest(), mode


def _instantane_arborescence():
    """Capture tous les chemins utiles sous src/ et tests/, caches exclus."""
    instantane = {}
    for racine in (_M3 / "src", _TESTS):
        chemins = [racine, *racine.rglob("*")]
        for chemin in sorted(chemins, key=str):
            relatif = chemin.relative_to(_M3)
            if "__pycache__" in relatif.parts or ".pytest_cache" in relatif.parts:
                continue
            instantane[str(relatif)] = _empreinte_chemin(chemin)
    return instantane


def _assert_instantanes_identiques(avant, apres):
    chemins_avant = set(avant)
    chemins_apres = set(apres)
    apparus = sorted(chemins_apres - chemins_avant)
    disparus = sorted(chemins_avant - chemins_apres)
    contenu_modifie = sorted(
        chemin
        for chemin in chemins_avant & chemins_apres
        if avant[chemin][0] != apres[chemin][0]
    )
    mode_modifie = sorted(
        chemin
        for chemin in chemins_avant & chemins_apres
        if avant[chemin][1] != apres[chemin][1]
    )

    differences = {
        "chemin apparu": apparus,
        "chemin disparu": disparus,
        "contenu modifié": contenu_modifie,
        "mode modifié": mode_modifie,
    }
    assert not any(differences.values()), (
        "trace laissée après les épreuves : "
        + "; ".join(
            f"{nature}={chemins}"
            for nature, chemins in differences.items()
            if chemins
        )
    )


def _assert_mutations_effectives(sortie, outil):
    mutations = re.search(r"\b(\d+)/(\d+)\s+mordent\b", sortie)
    assert mutations is not None, (
        f"{outil.name} ne prouve aucun travail de mutation effectif :\n{sortie}"
    )
    assert int(mutations.group(1)) > 0 and int(mutations.group(2)) > 0, (
        f"{outil.name} annonce un compte de mutations inactif :\n{sortie}"
    )


def _assert_controles_effectifs(sortie):
    bilan = re.search(r"\bcontroles=(\d+)\b", sortie)
    assert bilan is not None and int(bilan.group(1)) > 0, (
        "l'énumérateur nominal n'a produit aucun bilan de contrôles effectifs :\n"
        f"{sortie}"
    )


@contextmanager
def _suite_rouge():
    """Dépose un test volontairement rouge dans une COPIE jetable du département
    (``EnvironnementMutation``, PLAN T0.12), jamais sous la vraie racine — voir la
    docstring du module. Rend l'environnement ; l'appelant lance l'outil à éprouver
    avec ``racine=<le .dossier de cet environnement>`` pour que le fichier rouge soit
    visible dans la copie interne QUE CET OUTIL construit à son tour. Un ``kill -9``
    pendant le ``yield`` laisse au pire ce dossier temporaire orphelin sous le
    répertoire temporaire du système ; jamais une trace dans le dépôt.
    """
    env = EnvironnementMutation(_RACINE)
    try:
        chemin = env.dossier_tests / f"{_NOM_SUITE_ROUGE}.py"
        chemin.write_text(
            "def test_epreuve_deliberement_rouge():\n"
            '    assert False, "épreuve volontairement rouge des gardes"\n',
            encoding="utf-8",
        )
        yield env
    finally:
        env.nettoyer()


@contextmanager
def _module_sans_garde():
    """Miroir de ``_suite_rouge`` pour un module dont l'AST ne contient aucun ``if``,
    lui aussi déposé exclusivement dans une copie jetable du département."""
    env = EnvironnementMutation(_RACINE)
    try:
        chemin = env.dossier_source / f"{_NOM_MODULE_SANS_GARDE}.py"
        chemin.write_text(
            "def valeur_epreuve():\n"
            "    return 1\n",
            encoding="utf-8",
        )
        yield env
    finally:
        env.nettoyer()


def _offset_ligne(source, ligne, colonne):
    lignes = source.splitlines(keepends=True)
    return sum(len(element) for element in lignes[: ligne - 1]) + colonne


def _mutations_de_la_batterie(source):
    """Retourne les couples texte avant/noeud texte après de ``MUTATIONS``."""
    arbre = ast.parse(source)

    for noeud in arbre.body:
        if not isinstance(noeud, ast.Assign):
            continue
        if not any(
            isinstance(cible, ast.Name) and cible.id == "MUTATIONS"
            for cible in noeud.targets
        ):
            continue
        if not isinstance(noeud.value, (ast.List, ast.Tuple)):
            continue

        mutations = []
        for element in noeud.value.elts:
            if not isinstance(element, (ast.Tuple, ast.List)) or len(element.elts) < 3:
                continue
            avant, apres = element.elts[1:3]
            if (
                isinstance(avant, ast.Constant)
                and isinstance(avant.value, str)
                and isinstance(apres, ast.Constant)
                and isinstance(apres.value, str)
            ):
                mutations.append((avant.value, apres))
        return mutations

    return []


def _constante_remplacement_ancre_unique(source_batterie, source_module):
    """Choisit le premier remplacement dont l'ancre avant est unique dans le module."""
    for avant, apres in _mutations_de_la_batterie(source_batterie):
        if source_module.count(avant) == 1:
            return apres
    return None


def _rendre_une_mutation_non_compilable(
    source_batterie,
    source_module,
):
    """Sabote le remplacement d'une mutation atteignable jusqu'à ``compile``."""
    remplacement = _constante_remplacement_ancre_unique(
        source_batterie,
        source_module,
    )
    if remplacement is None:
        return None

    debut = _offset_ligne(
        source_batterie,
        remplacement.lineno,
        remplacement.col_offset,
    )
    fin = _offset_ligne(
        source_batterie,
        remplacement.end_lineno,
        remplacement.end_col_offset,
    )
    fragment_invalide = repr("def epreuve_non_compilable(:\n")
    return source_batterie[:debut] + fragment_invalide + source_batterie[fin:]


@pytest.fixture(autouse=True)
def aucune_trace_dans_le_departement():
    """Chaque scénario garde l’empreinte réelle, même si son assertion échoue.

    Les cas nominaux/rouges/sans-garde portent déjà les invocations probantes.
    Les empreinter séparément évite de les rejouer dans une campagne agrégée.
    """
    avant = _instantane_arborescence()
    try:
        yield
    finally:
        _assert_instantanes_identiques(avant, _instantane_arborescence())


@pytest.fixture
def lancer_outil():
    yield _lancer


@pytest.fixture
def suite_deja_rouge():
    """Rend l'``EnvironnementMutation`` portant le test rouge (pas un chemin)."""
    with _suite_rouge() as env:
        yield env


@pytest.fixture
def module_sans_garde():
    """Rend l'``EnvironnementMutation`` portant le module sans garde."""
    with _module_sans_garde() as env:
        yield env


def test_reference_rouge_fixture_est_reelle_et_reutilisee(campagne_gardes):
    test_rouge = (
        campagne_gardes.rouge.dossier_tests / f"{_NOM_SUITE_ROUGE}.py"
    )
    assert test_rouge.is_file(), "la copie partagée n'a pas reçu le test volontairement rouge"

    for outil in (campagne_gardes.outils_mutation[0], campagne_gardes.enumerateur):
        premier = campagne_gardes.suite_rouge(outil)
        assert premier.processus_lance_ici or premier.recu_durable is not None
        if premier.recu_durable is not None:
            assert Path(premier.recu_durable).is_file()
        assert premier.preuve.specification.scenario == "suite-rouge"
        assert premier.preuve.commande[2] == str(outil)
        assert premier.preuve.retour != 0
        assert PHRASE_SUITE_ROUGE in _sortie(premier.preuve)
        assert premier.preuve.nettoyage_prouve

        replay = campagne_gardes.suite_rouge(outil)
        assert replay.processus_lance_ici is False
        assert replay.preuve is premier.preuve


@pytest.mark.parametrize(
    "outil",
    _parametres_outils(),
    ids=_identifier_outil,
)
def test_chaque_batterie_refuse_une_suite_deja_rouge(outil, campagne_gardes):
    _exiger_outil(outil)
    acces = campagne_gardes.suite_rouge(outil)
    resultat = acces.preuve
    assert resultat.nettoyage_prouve, f"{outil.name} n'a pas restauré son entrée capturée"
    sortie = _sortie(resultat)

    assert resultat.retour != 0, f"{outil.name} a accepté une suite déjà rouge"
    assert PHRASE_SUITE_ROUGE in sortie, (
        f"{outil.name} a échoué sans identifier la suite déjà rouge :\n{sortie}"
    )


def test_l_enumerateur_refuse_une_suite_deja_rouge(campagne_gardes):
    resultat = campagne_gardes.suite_rouge(_ENUMERATEUR).preuve
    assert resultat.nettoyage_prouve
    sortie = _sortie(resultat)

    assert resultat.retour != 0, "l'énumérateur a accepté une suite déjà rouge"
    assert PHRASE_SUITE_ROUGE in sortie, (
        "l'énumérateur a échoué sans identifier la suite déjà rouge :\n"
        f"{sortie}"
    )


def test_l_enumerateur_refuse_un_module_sans_garde(campagne_gardes):
    resultat = campagne_gardes.sans_garde_preuve().preuve
    assert resultat.nettoyage_prouve
    sortie = _sortie(resultat)

    assert resultat.retour != 0, "l'énumérateur a accepté un module sans garde"
    assert PHRASE_SANS_GARDE in sortie, (
        "l'énumérateur a échoué sans identifier l'extracteur vide :\n"
        f"{sortie}"
    )


def test_les_deux_abandons_de_l_enumerateur_sont_distincts(campagne_gardes):
    resultat_rouge = campagne_gardes.suite_rouge(_ENUMERATEUR).preuve
    sortie_rouge = _sortie(resultat_rouge)

    assert resultat_rouge.retour != 0, (
        "l'énumérateur a accepté la condition de suite déjà rouge"
    )
    assert PHRASE_SUITE_ROUGE in sortie_rouge, (
        "abandon suite rouge non identifié :\n" f"{sortie_rouge}"
    )
    assert PHRASE_SANS_GARDE not in sortie_rouge, (
        "l'abandon de suite rouge annonce aussi un extracteur vide :\n"
        f"{sortie_rouge}"
    )

    resultat_vide = campagne_gardes.sans_garde_preuve().preuve
    sortie_vide = _sortie(resultat_vide)

    assert resultat_vide.retour != 0, (
        "l'énumérateur a accepté la condition d'extracteur vide"
    )
    assert PHRASE_SANS_GARDE in sortie_vide, (
        "abandon extracteur vide non identifié :\n" f"{sortie_vide}"
    )
    assert PHRASE_SUITE_ROUGE not in sortie_vide, (
        "l'abandon d'extracteur vide annonce aussi une suite rouge :\n"
        f"{sortie_vide}"
    )
    assert sortie_rouge != sortie_vide, (
        "les abandons suite rouge et extracteur vide produisent la même sortie"
    )


@pytest.mark.parametrize(
    "outil",
    _parametres_tous_outils(),
    ids=_identifier_outil,
)
def test_chaque_outil_est_sain_avant_sabotage(outil, campagne_gardes):
    _exiger_tous_les_outils(outil)
    acces = campagne_gardes.nominal(outil)
    resultat = acces.preuve
    assert resultat.nettoyage_prouve, f"{outil.name} n'a pas restauré son entrée capturée"
    sortie = _sortie(resultat)

    assert resultat.retour == 0, (
        f"{outil.name} n'est pas sain avant sabotage :\n{sortie}"
    )
    assert PHRASE_SUITE_ROUGE not in sortie, (
        f"{outil.name} annonce une suite rouge à l'état sain :\n{sortie}"
    )
    assert PHRASE_SANS_GARDE not in sortie, (
        f"{outil.name} annonce un extracteur vide à l'état sain :\n{sortie}"
    )
    if outil == _ENUMERATEUR:
        _assert_controles_effectifs(sortie)
    else:
        _assert_mutations_effectives(sortie, outil)


def test_le_chemin_nominal_de_l_enumerateur_est_exerce(campagne_gardes):
    avant = _instantane_arborescence()
    resultat = campagne_gardes.nominal(_ENUMERATEUR).preuve
    sortie = _sortie(resultat)
    apres = _instantane_arborescence()

    assert resultat.retour == 0, (
        "le chemin nominal de l'énumérateur a échoué :\n" f"{sortie}"
    )
    _assert_controles_effectifs(sortie)
    assert PHRASE_SUITE_ROUGE not in sortie, (
        "l'énumérateur nominal annonce une suite rouge :\n" f"{sortie}"
    )
    assert PHRASE_SANS_GARDE not in sortie, (
        "l'énumérateur nominal annonce un extracteur vide :\n" f"{sortie}"
    )
    _assert_instantanes_identiques(avant, apres)


def test_une_mutation_non_compilable_est_signalee(campagne_gardes):
    assert _OUTILS_MUTATION, (
        "aucun outil de mutation trouvé : l'épreuve de mutation non compilable "
        "est absente"
    )
    avant = _instantane_arborescence()
    acces, source_outil = campagne_gardes.non_compilable_preuve(
        _rendre_une_mutation_non_compilable
    )
    resultat = acces.preuve
    sortie = _sortie(resultat)

    assert resultat.retour != 0, (
        "la batterie dont une mutation produit du Python non compilable "
        f"a réussi :\n{sortie}"
    )
    assert PHRASE_NE_COMPILE_PAS in sortie, (
        "la batterie a échoué sans atteindre la branche de compilation "
        f"de la mutation :\n{sortie}"
    )
    assert "mordent |" not in sortie, (
        "la batterie a imprimé un bilan malgré le refus de compiler le mutant :\n"
        f"{sortie}"
    )
    assert resultat.nettoyage_prouve
    assert b"def epreuve_non_compilable" in source_outil

    apres = _instantane_arborescence()
    _assert_instantanes_identiques(avant, apres)


# --- PLAN T0.12-suite : preuves structurelle et dynamique que CETTE épreuve n'écrit
# jamais sous la vraie racine du département, dans l'esprit de celles de T0.12
# (test_outils_de_preuve.test_aucun_outil_de_preuve_n_ecrit_jamais_dans_la_vraie_source
# et .test_empreinte_de_la_source_reelle_identique_avant_et_apres_une_batterie_complete)
# — mais portant sur ce fichier lui-même plutôt que sur les outils qu'il éprouve. ---

_RACINES_REELLES = {"_M3", "_RACINE", "_TESTS", "_SOURCE", "_OUTILS"}
_METHODES_MUTANTES = {
    "write_text",
    "write_bytes",
    "unlink",
    "rmdir",
    "rename",
    "replace",
    "touch",
    "symlink_to",
    "chmod",
}
_FONCTIONS_SHUTIL_MUTANTES = {"copyfile", "copy", "copy2", "copytree", "move", "rmtree"}


def _racine_nom(expression):
    """Nom de la racine SYNTAXIQUE d'une chaîne d'attributs/indices/appels/chemins
    ``/`` (ex. ``_TESTS / "x.py"`` -> ``"_TESTS"``, ``env.dossier_tests`` -> ``"env"``).
    """
    while isinstance(expression, (ast.Attribute, ast.Subscript)):
        expression = expression.value
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Div):
        return _racine_nom(expression.left)
    if isinstance(expression, ast.Call):
        return _racine_nom(expression.func)
    if isinstance(expression, ast.Name):
        return expression.id
    return None


def _racine_ultime(nom, table):
    """Résout ``nom`` à travers la table d'affectations simples ``{cible: racine}``
    jusqu'à une racine réelle connue ou l'absence d'affectation — le premier des deux
    qui survient. Bornée par l'ensemble des noms déjà vus, pour ignorer un cycle
    plutôt que boucler indéfiniment.
    """
    vus = set()
    while nom is not None and nom not in _RACINES_REELLES and nom in table and nom not in vus:
        vus.add(nom)
        nom = table[nom]
    return nom


def test_l_epreuve_des_gardes_n_ecrit_jamais_sous_la_vraie_racine_du_departement():
    """Preuve STRUCTURELLE (PLAN T0.12-suite) : aucun appel d'écriture de ce fichier ne
    cible ``_M3``, ``_RACINE``, ``_TESTS``, ``_SOURCE`` ou ``_OUTILS`` — les cinq
    constantes qui désignent le VRAI dépôt et le VRAI département, jamais une copie.

    Couvre ``Path.write_text``/``write_bytes``/``unlink``/``rmdir``/``rename``/
    ``replace``/``touch``/``symlink_to``/``chmod``, ainsi qu'un ``shutil.copyfile``/
    ``copy``/``copy2``/``copytree``/``move``/``rmtree`` référençant directement l'une
    de ces racines dans SES arguments. La résolution suit les affectations simples à
    une variable locale (``chemin = _TESTS / "x.py"`` puis ``chemin.write_text(...)``
    EST détecté : exactement le motif qu'utilisait ce fichier avant T0.12-suite, et
    celui de l'incident du 2026-09-28 dans ``blocage_prix.py`` que corrigeait déjà
    T0.12 pour les outils de mutation eux-mêmes) sur UNE SEULE table construite pour
    tout le module, par simplicité.

    Limite assumée, comme pour le test miroir de T0.12 : cette résolution est
    SYNTAXIQUE, pas un vrai suivi de flux de données control-flow-sensible ; une
    variable réaffectée entre deux portées homonymes pourrait en théorie échapper à
    la table. La limite est déclarée ici plutôt que tue.
    """
    arbre = ast.parse(Path(__file__).read_text(encoding="utf-8"))

    table = {}
    for noeud in ast.walk(arbre):
        if (
            isinstance(noeud, ast.Assign)
            and len(noeud.targets) == 1
            and isinstance(noeud.targets[0], ast.Name)
        ):
            racine = _racine_nom(noeud.value)
            if racine is not None:
                table[noeud.targets[0].id] = racine

    fautifs = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call) or not isinstance(noeud.func, ast.Attribute):
            continue
        if noeud.func.attr in _METHODES_MUTANTES:
            racine = _racine_ultime(_racine_nom(noeud.func.value), table)
            if racine in _RACINES_REELLES:
                fautifs.append(f"L{noeud.lineno} {racine}.{noeud.func.attr}(...)")
        elif (
            noeud.func.attr in _FONCTIONS_SHUTIL_MUTANTES
            and isinstance(noeud.func.value, ast.Name)
            and noeud.func.value.id == "shutil"
        ):
            for argument in noeud.args:
                racine = _racine_ultime(_racine_nom(argument), table)
                if racine in _RACINES_REELLES:
                    fautifs.append(
                        f"L{noeud.lineno} shutil.{noeud.func.attr}(...) référence "
                        f"{racine} directement"
                    )

    assert not fautifs, (
        "cette épreuve écrit sous la vraie racine du département ou du dépôt :\n  "
        + "\n  ".join(fautifs)
    )


def test_empreinte_de_src_et_tests_identique_apres_confection_d_une_epreuve():
    """Preuve DYNAMIQUE (PLAN T0.12-suite), miroir de ``test_outils_de_preuve.
    test_empreinte_de_la_source_reelle_identique_avant_et_apres_une_batterie_complete``
    — mais sur la CONFECTION DES ARTEFACTS de cette épreuve elle-même, pas sur une
    batterie de mutation (déjà empreintée autour d'un appel d'outil par
    ``test_le_chemin_nominal_de_l_enumerateur_est_exerce``, ``test_une_mutation_non_
    compilable_est_signalee`` et la fixture d’empreinte appliquée à chaque cas).

    Fabrique réellement les deux ``EnvironnementMutation`` (test rouge, module sans
    garde), vérifie que chaque artefact existe dans SA copie et nulle part sous la
    vraie racine, détruit les deux copies, puis compare l'empreinte SHA-256 et le mode
    d'accès de chaque fichier sous ``departments/m03-estimation/src`` ET ``tests``
    avant et après : identiques. Volontairement sans sous-processus (aucun outil n'est
    lancé) : ce test isole la seule opération qui écrivait réellement sur disque avant
    T0.12-suite — la fabrication puis la destruction de la copie — du bruit d'une
    batterie complète, déjà éprouvée ailleurs dans ce fichier.
    """
    avant = _instantane_arborescence()

    with _suite_rouge() as env_rouge:
        chemin = env_rouge.dossier_tests / f"{_NOM_SUITE_ROUGE}.py"
        assert chemin.is_file(), "le test rouge n'a pas été écrit dans la copie"
        assert not chemin.is_relative_to(_M3), (
            "le test rouge est écrit sous la vraie racine du département"
        )
        assert not (_TESTS / chemin.name).exists(), (
            "le test rouge est également apparu sous la vraie racine des tests"
        )

    with _module_sans_garde() as env_sans_garde:
        chemin = env_sans_garde.dossier_source / f"{_NOM_MODULE_SANS_GARDE}.py"
        assert chemin.is_file(), "le module sans garde n'a pas été écrit dans la copie"
        assert not chemin.is_relative_to(_M3), (
            "le module sans garde est écrit sous la vraie racine du département"
        )
        assert not (_SOURCE / chemin.name).exists(), (
            "le module sans garde est également apparu sous la vraie racine de src"
        )

    apres = _instantane_arborescence()
    _assert_instantanes_identiques(avant, apres)


@pytest.mark.parametrize("trace", ["apparu", "disparu", "contenu", "mode", "exception"])
def test_la_garde_d_empreinte_refuse_une_trace_reelle(tmp_path, monkeypatch, trace):
    """Éprouve le teardown réel avec une copie locale, y compris après une erreur."""
    source_locale = tmp_path / "src"
    tests_locaux = tmp_path / "tests"
    source_locale.mkdir()
    tests_locaux.mkdir()
    cible = source_locale / "epreuve.py"
    cible.write_text("valeur = 1\n", encoding="utf-8")
    with monkeypatch.context() as contexte:
        contexte.setitem(globals(), "_M3", tmp_path)
        contexte.setitem(globals(), "_TESTS", tests_locaux)
        garde = aucune_trace_dans_le_departement.__wrapped__()
        next(garde)
        if trace == "apparu":
            (tests_locaux / "trace.py").write_text("valeur = 2\n", encoding="utf-8")
        elif trace == "disparu":
            cible.unlink()
        elif trace == "mode":
            cible.chmod((cible.stat().st_mode & 0o7777) ^ 0o100)
        else:
            cible.write_text("valeur = 2\n", encoding="utf-8")
        attendu = "contenu" if trace == "exception" else trace
        with pytest.raises(AssertionError, match=attendu):
            if trace == "exception":
                garde.throw(RuntimeError("échec fictif de l’épreuve"))
            else:
                garde.close()
