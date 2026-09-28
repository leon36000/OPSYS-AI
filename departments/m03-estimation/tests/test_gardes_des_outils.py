"""Les gardes des outils de preuve sont vérifiées directement par pytest.

Ces tests remplacent un vérificateur monolithique dont la complexité était devenue
le goulot : après sept rondes de revue, chaque itération avait apporté son défaut
propre. Les mêmes propriétés tiennent ici en quelques lignes lisibles, isolées par
pytest et exécutées par la CI.

Limite assumée : ces tests certifient que les gardes se déclenchent sur les
sabotages effectués ici. Ils ne certifient pas les instruments contre un auteur
hostile : un outil simulant exactement les messages attendus passerait. Un
instrument ne peut pas prouver qu'un autre instrument n'est pas un leurre.
"""

import ast
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

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


def _lancer(outil, *arguments):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(outil),
            str(_RACINE),
            *arguments,
        ],
        capture_output=True,
        text=True,
        cwd=_RACINE,
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


def _pyc_temporaires(noms):
    """Retourne les caches Python associés aux fichiers temporaires connus."""
    traces = []
    for racine in (_M3 / "src", _TESTS):
        for cache in racine.rglob("__pycache__"):
            for chemin in cache.glob("*.pyc"):
                if any(chemin.name.startswith(f"{nom}.") for nom in noms):
                    traces.append(chemin)
    return sorted(traces, key=str)


def _supprimer_pyc_temporaires(noms):
    """Supprime exclusivement les caches issus des fichiers d'épreuve créés ici."""
    for chemin in _pyc_temporaires(noms):
        chemin.unlink()


def _assert_aucune_trace_temporaire(noms):
    traces = _pyc_temporaires(noms)
    assert not traces, (
        "cache Python temporaire survivant après l'épreuve : "
        + ", ".join(str(trace) for trace in traces)
    )


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
    """Dépose puis retire un test volontairement rouge pour les batteries."""
    chemin = _TESTS / "test_epreuve_garde_suite_rouge.py"
    assert not chemin.exists(), f"fichier d'épreuve déjà présent : {chemin}"
    chemin.write_text(
        "def test_epreuve_deliberement_rouge():\n"
        '    assert False, "épreuve volontairement rouge des gardes"\n',
        encoding="utf-8",
    )
    try:
        yield chemin
    finally:
        if chemin.exists():
            chemin.unlink()
        _supprimer_pyc_temporaires((chemin.stem,))
        _assert_aucune_trace_temporaire((chemin.stem,))


@contextmanager
def _module_sans_garde():
    """Dépose puis retire un module dont l'AST ne contient aucun ``if``."""
    chemin = _SOURCE / "epreuve_module_sans_garde.py"
    assert not chemin.exists(), f"module d'épreuve déjà présent : {chemin}"
    chemin.write_text(
        "def valeur_epreuve():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    try:
        yield chemin
    finally:
        if chemin.exists():
            chemin.unlink()
        _supprimer_pyc_temporaires((chemin.stem,))
        _assert_aucune_trace_temporaire((chemin.stem,))


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


@pytest.fixture
def lancer_outil():
    yield _lancer


@pytest.fixture
def suite_deja_rouge():
    with _suite_rouge() as chemin:
        yield chemin


@pytest.fixture
def module_sans_garde():
    with _module_sans_garde() as chemin:
        yield chemin


@pytest.mark.parametrize(
    "outil",
    _parametres_outils(),
    ids=_identifier_outil,
)
def test_chaque_batterie_refuse_une_suite_deja_rouge(
    outil, suite_deja_rouge, lancer_outil
):
    _exiger_outil(outil)
    resultat = lancer_outil(outil)
    sortie = _sortie(resultat)

    assert resultat.returncode != 0, f"{outil.name} a accepté une suite déjà rouge"
    assert PHRASE_SUITE_ROUGE in sortie, (
        f"{outil.name} a échoué sans identifier la suite déjà rouge :\n{sortie}"
    )


def test_l_enumerateur_refuse_une_suite_deja_rouge(
    suite_deja_rouge, lancer_outil
):
    resultat = lancer_outil(_ENUMERATEUR, _module_nominal())
    sortie = _sortie(resultat)

    assert resultat.returncode != 0, "l'énumérateur a accepté une suite déjà rouge"
    assert PHRASE_SUITE_ROUGE in sortie, (
        "l'énumérateur a échoué sans identifier la suite déjà rouge :\n"
        f"{sortie}"
    )


def test_l_enumerateur_refuse_un_module_sans_garde(
    module_sans_garde, lancer_outil
):
    resultat = lancer_outil(_ENUMERATEUR, module_sans_garde.stem)
    sortie = _sortie(resultat)

    assert resultat.returncode != 0, "l'énumérateur a accepté un module sans garde"
    assert PHRASE_SANS_GARDE in sortie, (
        "l'énumérateur a échoué sans identifier l'extracteur vide :\n"
        f"{sortie}"
    )


def test_les_deux_abandons_de_l_enumerateur_sont_distincts(lancer_outil):
    with _suite_rouge():
        resultat_rouge = lancer_outil(_ENUMERATEUR, _module_nominal())
        sortie_rouge = _sortie(resultat_rouge)

    assert resultat_rouge.returncode != 0, (
        "l'énumérateur a accepté la condition de suite déjà rouge"
    )
    assert PHRASE_SUITE_ROUGE in sortie_rouge, (
        "abandon suite rouge non identifié :\n" f"{sortie_rouge}"
    )
    assert PHRASE_SANS_GARDE not in sortie_rouge, (
        "l'abandon de suite rouge annonce aussi un extracteur vide :\n"
        f"{sortie_rouge}"
    )

    with _module_sans_garde() as chemin_module_sans_garde:
        resultat_vide = lancer_outil(
            _ENUMERATEUR,
            chemin_module_sans_garde.stem,
        )
        sortie_vide = _sortie(resultat_vide)

    assert resultat_vide.returncode != 0, (
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
def test_chaque_outil_est_sain_avant_sabotage(outil, lancer_outil):
    _exiger_tous_les_outils(outil)
    resultat = lancer_outil(outil, *_arguments_nominals(outil))
    sortie = _sortie(resultat)

    assert resultat.returncode == 0, (
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


def test_le_chemin_nominal_de_l_enumerateur_est_exerce(lancer_outil):
    avant = _instantane_arborescence()
    resultat = lancer_outil(_ENUMERATEUR, _module_nominal())
    sortie = _sortie(resultat)
    apres = _instantane_arborescence()

    assert resultat.returncode == 0, (
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


def test_une_mutation_non_compilable_est_signalee(lancer_outil):
    assert _OUTILS_MUTATION, (
        "aucun outil de mutation trouvé : l'épreuve de mutation non compilable "
        "est absente"
    )
    outil_original = _OUTILS_MUTATION[0]
    module = outil_original.stem[len("muter_"):]
    source_module = _SOURCE / f"{module}.py"
    assert source_module.exists(), (
        "sabotage non probant : le module cible dérivé de la batterie est absent : "
        f"{source_module}"
    )

    outil_temporaire = _OUTILS / "epreuve_mutation_non_compilable.py"
    noms_temporaires = (outil_temporaire.stem,)
    assert not outil_temporaire.exists(), (
        f"fichier d'épreuve déjà présent : {outil_temporaire}"
    )

    avant = _instantane_arborescence()
    try:
        shutil.copyfile(outil_original, outil_temporaire)
        source_batterie = outil_temporaire.read_text(encoding="utf-8")
        sabotage = _rendre_une_mutation_non_compilable(
            source_batterie,
            source_module.read_text(encoding="utf-8"),
        )

        # Une ancre ambiguë arrête la batterie à son contrôle d'ancre : le test
        # mesurait alors un autre chemin que celui de la compilation qu'il nommait.
        if sabotage is None:
            pytest.fail(
                "sabotage non probant : aucune mutation de la batterie ne possède "
                "une ancre AVANT unique dans le module cible"
            )

        outil_temporaire.write_text(sabotage, encoding="utf-8")

        resultat = lancer_outil(outil_temporaire)
        sortie = _sortie(resultat)

        assert resultat.returncode != 0, (
            "la batterie dont une mutation produit du Python non compilable "
            f"a réussi :\n{sortie}"
        )
        assert PHRASE_NE_COMPILE_PAS in sortie, (
            "la batterie a échoué sans atteindre la branche de compilation "
            f"de la mutation :\n{sortie}"
        )
    finally:
        if outil_temporaire.exists():
            outil_temporaire.unlink()
        _supprimer_pyc_temporaires(noms_temporaires)

    _assert_aucune_trace_temporaire(noms_temporaires)
    apres = _instantane_arborescence()
    _assert_instantanes_identiques(avant, apres)


def test_aucune_trace_apres_les_epreuves(lancer_outil):
    chemin_suite_rouge = _TESTS / "test_epreuve_garde_suite_rouge.py"
    chemin_module_sans_garde = _SOURCE / "epreuve_module_sans_garde.py"
    noms_temporaires = (chemin_suite_rouge.stem, chemin_module_sans_garde.stem)

    assert not chemin_suite_rouge.exists(), (
        f"fichier d'épreuve déjà présent : {chemin_suite_rouge}"
    )
    assert not chemin_module_sans_garde.exists(), (
        f"module d'épreuve déjà présent : {chemin_module_sans_garde}"
    )
    assert _OUTILS_MUTATION, (
        "aucun outil de mutation trouvé : l'épreuve de suite rouge est absente"
    )

    avant = _instantane_arborescence()
    try:
        for outil in _OUTILS_MUTATION:
            resultat_normal = lancer_outil(outil)
            sortie_normale = _sortie(resultat_normal)
            assert resultat_normal.returncode == 0, (
                f"l'épreuve normale de {outil.name} n'a pas abouti ; "
                "le contrôle d'absence de trace n'est pas probant :\n"
                f"{sortie_normale}"
            )
            _assert_mutations_effectives(sortie_normale, outil)

        chemin_suite_rouge.write_text(
            "def test_epreuve_deliberement_rouge():\n"
            '    assert False, "épreuve volontairement rouge des gardes"\n',
            encoding="utf-8",
        )

        resultats_batteries = [
            (outil, lancer_outil(outil)) for outil in _OUTILS_MUTATION
        ]
        for outil, resultat in resultats_batteries:
            sortie = _sortie(resultat)
            assert resultat.returncode != 0, (
                f"{outil.name} a accepté l'épreuve complète de suite rouge"
            )
            assert PHRASE_SUITE_ROUGE in sortie, (
                f"{outil.name} n'a pas nommé la suite rouge :\n{sortie}"
            )

        chemin_suite_rouge.unlink()
        _supprimer_pyc_temporaires((chemin_suite_rouge.stem,))

        chemin_module_sans_garde.write_text(
            "def valeur_epreuve():\n"
            "    return 1\n",
            encoding="utf-8",
        )
        resultat_vide = lancer_outil(_ENUMERATEUR, chemin_module_sans_garde.stem)
        sortie_vide = _sortie(resultat_vide)

        assert resultat_vide.returncode != 0, (
            "l'énumérateur a accepté l'épreuve complète d'extracteur vide"
        )
        assert PHRASE_SANS_GARDE in sortie_vide, (
            "l'énumérateur n'a pas nommé l'extracteur vide"
        )
    finally:
        if chemin_suite_rouge.exists():
            chemin_suite_rouge.unlink()
        if chemin_module_sans_garde.exists():
            chemin_module_sans_garde.unlink()
        _supprimer_pyc_temporaires(noms_temporaires)

    _assert_aucune_trace_temporaire(noms_temporaires)
    apres = _instantane_arborescence()
    _assert_instantanes_identiques(avant, apres)
