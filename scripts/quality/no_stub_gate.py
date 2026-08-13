"""Gate de qualité refusant les stubs et les régressions de qualité ajoutées."""

from __future__ import annotations

import argparse
import ast
import builtins
import re
import subprocess
import sys
import tokenize
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Final

import yaml


_SCOPE_FILE: Final[Path] = (
    Path(__file__).resolve().parents[2] / "core" / "quality-scopes.toml"
)
_DEFAULT_REQUIRED_JOB_IDS: Final[tuple[str, ...]] = (
    "gates",
    "types",
    "tests",
    "security",
    "pack-validation",
    "proof-sealed",
)
_DEBT_MARKERS: Final[tuple[str, ...]] = (
    "TODO",  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
    "FIXME",  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
    "XXX",  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
)  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
_MARQUEUR_TYPE_IGNORE: Final[str] = "type: ignore"
_SUPPRESSION_MARKERS: Final[tuple[str, ...]] = (_MARQUEUR_TYPE_IGNORE, "noqa", "nosec")
_MOTIFS_DIRECTIVE: Final[Mapping[str, re.Pattern[str]]] = {
    _MARQUEUR_TYPE_IGNORE: re.compile(r"type:\s*ignore", re.IGNORECASE),
    "noqa": re.compile(r"noqa", re.IGNORECASE),
    "nosec": re.compile(r"nosec", re.IGNORECASE),
}
_MARQUES_DE_SAUT_PYTEST: Final[frozenset[str]] = frozenset({"skip", "skipif", "xfail"})
_APPELS_DE_SAUT: Final[Mapping[str, frozenset[str]]] = {
    "pytest": frozenset({"skip", "xfail", "importorskip"}),
    "unittest": frozenset({"skip", "skipIf", "skipUnless"}),
}
_IDENTIFIANT_REGLE_OPTIONNEL: Final[re.Pattern[str]] = re.compile(
    r"(?:[A-Za-z]+[0-9][A-Za-z0-9_-]*|\[[A-Za-z0-9_.-]+\]|[A-Za-z][A-Za-z0-9_.-]*)"
)
_IDENTIFIANTS_REGLE_OPTIONNELS: Final[re.Pattern[str]] = re.compile(
    r":?\s*"
    + _IDENTIFIANT_REGLE_OPTIONNEL.pattern
    + r"(?:\s*,\s*"
    + _IDENTIFIANT_REGLE_OPTIONNEL.pattern
    + r")*"
)
_EXIT_ZERO: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[;|&()\s])exit\s+0(?=$|[^A-Za-z0-9_])"
)
_DEBUT_COMMANDE_SHELL: Final[str] = r"(?:^|[;|&(]|\bthen\b|\bdo\b|\belse\b)\s*"
_IF_SHELL: Final[re.Pattern[str]] = re.compile(_DEBUT_COMMANDE_SHELL + r"if\b")
_CASE_SHELL: Final[re.Pattern[str]] = re.compile(_DEBUT_COMMANDE_SHELL + r"case\b")
_FIN_IF_SHELL: Final[re.Pattern[str]] = re.compile(r"(?:^|[;|&()\s])fi(?=$|[;|&()\s])")
_FIN_CASE_SHELL: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[;|&()\s])esac(?=$|[;|&()\s])"
)
_SUITE_NOM_COMMANDE: Final[str] = r"(?![A-Za-z0-9_./-])"
_PREFIXE_CHEMIN_COMMANDE: Final[str] = r"(?:[A-Za-z0-9_.-]*/)+"
_PREFIXE_BUILTIN_COMMAND: Final[str] = r"command\s+(?:-[A-Za-z]+\s+)*"
_PREFIXES_NEUTRES_REPLI: Final[str] = (
    f"(?:{_PREFIXE_BUILTIN_COMMAND})?(?:{_PREFIXE_CHEMIN_COMMANDE})?"
)
_FALLBACK_SHELL: Final[re.Pattern[str]] = re.compile(
    r"\|\|\s*(?P<prefixe>" + _PREFIXES_NEUTRES_REPLI + r")(?P<command>"
    f"true{_SUITE_NOM_COMMANDE}"
    f"|:{_SUITE_NOM_COMMANDE}"
    f"|echo{_SUITE_NOM_COMMANDE}"
    f"|printf{_SUITE_NOM_COMMANDE}"
    r"|exit\s+0(?=$|[^A-Za-z0-9_])"
    r")"
)
_SUCCES_FORCE_COMPACT: Final[re.Pattern[str]] = re.compile(
    r"(?:\|\|true|\|\|:|\|\|exit0|;true)" + _SUITE_NOM_COMMANDE
)
_GROUPE_APRES_OU: Final[re.Pattern[str]] = re.compile(r"\|\|\s*(?P<ouverture>[{(])")
_SEPARATEUR_COMMANDE_SHELL: Final[re.Pattern[str]] = re.compile(r";|\n|&&")
_SORTIE_NON_NULLE: Final[re.Pattern[str]] = re.compile(
    r"^(?:exit|return)\s+(?P<code>[0-9]+)(?![0-9])"
)
_COMMANDES_ECHOUANT_TOUJOURS: Final[frozenset[str]] = frozenset({"false"})
_JETONS_SHELL: Final[re.Pattern[str]] = re.compile(
    f"(?P<ouvre>{_IF_SHELL.pattern}|{_CASE_SHELL.pattern})"
    f"|(?P<ferme>{_FIN_IF_SHELL.pattern}|{_FIN_CASE_SHELL.pattern})"
    f"|(?P<sortie>{_EXIT_ZERO.pattern})"
)
_POSITION_COMMANDE_SHELL: Final[str] = r"(?:^|[;|&()\s])"
_FIN_DE_MOT_SHELL: Final[str] = r"(?=$|[;|&()\s])"
_JETONS_CONDITIONNELLES: Final[re.Pattern[str]] = re.compile(
    f"(?P<ouvre>{_POSITION_COMMANDE_SHELL}(?P<mot_ouvre>if|case){_FIN_DE_MOT_SHELL})"
    f"|(?P<then>{_POSITION_COMMANDE_SHELL}then{_FIN_DE_MOT_SHELL})"
    f"|(?P<sinon>{_POSITION_COMMANDE_SHELL}(?:else|elif){_FIN_DE_MOT_SHELL})"
    f"|(?P<ferme>{_POSITION_COMMANDE_SHELL}(?:fi|esac){_FIN_DE_MOT_SHELL})"
)
_NEGATION_APRES_IF: Final[re.Pattern[str]] = re.compile(r"\s*!")
_SEPARATEUR_CONDITION_SHELL: Final[re.Pattern[str]] = re.compile(r"[;\n|&]+")
_SONDES_SHELL: Final[frozenset[str]] = frozenset(
    {"[", "[[", "test", "command", "grep", "git"}
)
_RACINES_SCRIPTS_DU_DEPOT: Final[tuple[str, ...]] = (
    "scripts/",
    "core/scripts/",
    "tools/",
)
_SUFFIXES_SCRIPTS_DU_DEPOT: Final[tuple[str, ...]] = (".py", ".sh")
_GENRE_NEUTRE: Final[str] = ""
_GENRE_NEGATION: Final[str] = "négation"
_GENRE_CONTROLE_DIRECT: Final[str] = "contrôle direct"
_COMMANDE_SET_SHELL: Final[re.Pattern[str]] = re.compile(
    _POSITION_COMMANDE_SHELL + r"set(?P<arguments>[^\n;|&]*)"
)
_OPTION_DESARMANT_ERREXIT: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)\+(?:[A-Za-z]*e[A-Za-z]*|o\s+errexit)(?=$|\s)"
)
_OUVERTURES_DE_MOT_SHELL: Final[frozenset[str]] = frozenset(
    {" ", "\t", "\n", "\r", ";", "|", "&", "(", ")"}
)
_MAX_ACTION_DEPTH: Final[int] = 5
_VALEURS_VRAIES_YAML: Final[frozenset[str]] = frozenset(
    {"true", "yes", "on", "y", "1"}
)
_CONDITIONS_REQUISES_ACCEPTEES: Final[frozenset[str]] = frozenset(
    {"always()", "success()"}
)
_NOMS_EXCEPTIONS_BUILTINS: Final[frozenset[str]] = frozenset(
    nom
    for nom, objet in vars(builtins).items()
    if isinstance(objet, type) and issubclass(objet, BaseException)
)
_NOMS_TEST_CASE_UNITTEST: Final[frozenset[str]] = frozenset(
    {"TestCase", "IsolatedAsyncioTestCase", "FunctionTestCase"}
)


@dataclass(frozen=True)
class Violation:
    """Décrit une règle de qualité enfreinte dans un fichier du dépôt."""

    code: str
    path: str
    line: int
    detail: str


@dataclass(frozen=True)
class _AliasesImports:
    """Conserve les noms locaux prouvés comme issus des modules standards visés."""

    protocols: frozenset[str]
    modules_typing: frozenset[str]
    abstractmethods: frozenset[str]
    modules_abc: frozenset[str]
    not_implemented_errors: frozenset[str]
    modules_pytest: frozenset[str]
    modules_unittest: frozenset[str]
    marques_pytest: frozenset[str]
    sauts_directs: frozenset[str]
    test_cases: frozenset[str]


@dataclass
class _CollecteAliases:
    """Accumule les noms liés par les imports pendant le parcours du module.

    La preuve consommée par les règles reste immuable : cette collecte n'existe
    que le temps du parcours, puis est figée en ``_AliasesImports``. Séparer les
    deux garantit qu'aucune règle ne peut modifier après coup l'origine prouvée
    d'un nom.
    """

    protocols: set[str] = field(default_factory=set)
    modules_typing: set[str] = field(default_factory=set)
    abstractmethods: set[str] = field(default_factory=set)
    modules_abc: set[str] = field(default_factory=set)
    not_implemented_errors: set[str] = field(default_factory=set)
    modules_pytest: set[str] = field(default_factory=set)
    modules_unittest: set[str] = field(default_factory=set)
    marques_pytest: set[str] = field(default_factory=set)
    sauts_directs: set[str] = field(default_factory=set)
    test_cases: set[str] = field(default_factory=set)

    def _ensembles(self) -> tuple[set[str], ...]:
        """Énumère TOUS les ensembles : un oubli ici rendrait un alias ininvalidable."""
        return (
            self.protocols,
            self.modules_typing,
            self.abstractmethods,
            self.modules_abc,
            self.not_implemented_errors,
            self.modules_pytest,
            self.modules_unittest,
            self.marques_pytest,
            self.sauts_directs,
            self.test_cases,
        )

    def retirer(self, noms: set[str]) -> None:
        """Retire les noms réaffectés : leur origine standard n'est plus prouvée."""
        for ensemble in self._ensembles():
            ensemble.difference_update(noms)

    def figer(self) -> _AliasesImports:
        """Fige la collecte en preuve immuable consommée par les règles."""
        return _AliasesImports(
            frozenset(self.protocols),
            frozenset(self.modules_typing),
            frozenset(self.abstractmethods),
            frozenset(self.modules_abc),
            frozenset(self.not_implemented_errors),
            frozenset(self.modules_pytest),
            frozenset(self.modules_unittest),
            frozenset(self.marques_pytest),
            frozenset(self.sauts_directs),
            frozenset(self.test_cases),
        )


def _chemin_relatif(repo: Path, fichier: Path) -> str:
    """Retourne le chemin POSIX stable d'un fichier relativement au dépôt."""
    return fichier.relative_to(repo).as_posix()


def _violation(code: str, repo: Path, fichier: Path, line: int, detail: str) -> Violation:
    """Construit une violation avec son chemin affichable."""
    return Violation(code, _chemin_relatif(repo, fichier), line, detail)


def _lire_contrat(
    repo: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    """Lit le contrat local et refuse ses listes vides, qui annuleraient le périmètre."""
    fichier = repo / "core" / "quality-scopes.toml"
    if not fichier.is_file():
        return (), _DEFAULT_REQUIRED_JOB_IDS, "le contrat core/quality-scopes.toml est absent"

    try:
        with fichier.open("rb") as flux:
            contrat = tomllib.load(flux)
    except OSError as erreur:
        return (), _DEFAULT_REQUIRED_JOB_IDS, f"le contrat est illisible : {erreur}"
    except tomllib.TOMLDecodeError as erreur:
        return (), _DEFAULT_REQUIRED_JOB_IDS, f"le contrat TOML est invalide : {erreur}"

    racines = contrat.get("python_roots")
    jobs = contrat.get("target_required_job_ids")
    if not isinstance(racines, list) or not all(isinstance(item, str) for item in racines):
        return (), _DEFAULT_REQUIRED_JOB_IDS, "python_roots est absent ou invalide"
    if not racines:
        return (), _DEFAULT_REQUIRED_JOB_IDS, "python_roots est vide"
    if not isinstance(jobs, list) or not all(isinstance(item, str) for item in jobs):
        return (), _DEFAULT_REQUIRED_JOB_IDS, "target_required_job_ids est absent ou invalide"
    if not jobs:
        return (), _DEFAULT_REQUIRED_JOB_IDS, "target_required_job_ids est vide"
    return tuple(racines), tuple(jobs), None


def _charger_contrat(repo: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Charge le contrat sans inventer de racines si son format local est invalide."""
    racines, jobs, erreur = _lire_contrat(repo)
    if erreur is None:
        return racines, jobs

    try:
        with _SCOPE_FILE.open("rb") as flux:
            contrat = tomllib.load(flux)
    except (OSError, tomllib.TOMLDecodeError):
        return (), _DEFAULT_REQUIRED_JOB_IDS

    jobs_source = contrat.get("target_required_job_ids", [])
    if (
        not isinstance(jobs_source, list)
        or not jobs_source
        or not all(isinstance(item, str) for item in jobs_source)
    ):
        return (), _DEFAULT_REQUIRED_JOB_IDS
    return (), tuple(jobs_source)


def _charger_racines_contractuelles(repo: Path) -> tuple[str, ...] | None:
    """Charge les racines locales sans inventer de contrat pour les tests isolés."""
    racines, _, erreur = _lire_contrat(repo)
    return racines if erreur is None else None


def _fichiers_python(repo: Path, scopes: tuple[str, ...]) -> list[Path]:
    """Énumère de façon déterministe les fichiers Python présents dans les scopes."""
    fichiers: list[Path] = []
    for scope in scopes:
        racine = repo / scope
        if racine.is_file() and racine.suffix == ".py":
            fichiers.append(racine)
        elif racine.is_dir():
            fichiers.extend(sorted(racine.rglob("*.py")))
    return sorted(set(fichiers))


def _est_docstring(noeud: ast.stmt) -> bool:
    """Indique si une instruction est une docstring Python littérale."""
    return (
        isinstance(noeud, ast.Expr)
        and isinstance(noeud.value, ast.Constant)
        and isinstance(noeud.value.value, str)
    )


def _corps_utile(corps: list[ast.stmt]) -> list[ast.stmt]:
    """Retire la docstring initiale afin de mesurer le vrai corps exécutable."""
    return corps[1:] if corps and _est_docstring(corps[0]) else corps


def _noms_lies_cible(noeud: ast.expr) -> set[str]:
    """Extrait tous les noms liés par une cible simple, destructurée ou étoilée."""
    if isinstance(noeud, ast.Name):
        return {noeud.id}
    if isinstance(noeud, (ast.Tuple, ast.List)):
        return set().union(*(_noms_lies_cible(element) for element in noeud.elts))
    if isinstance(noeud, ast.Starred):
        return _noms_lies_cible(noeud.value)
    return set()


def _noms_cibles_affectation(noeud: ast.stmt) -> set[str]:
    """Extrait les noms que toute liaison module-level peut réaffecter."""
    if isinstance(noeud, ast.Assign):
        return set().union(*(_noms_lies_cible(cible) for cible in noeud.targets))
    if isinstance(noeud, ast.AnnAssign):
        return _noms_lies_cible(noeud.target)
    if isinstance(noeud, (ast.For, ast.AsyncFor)):
        return _noms_lies_cible(noeud.target)
    if isinstance(noeud, (ast.With, ast.AsyncWith)):
        return set().union(
            *(
                _noms_lies_cible(element.optional_vars)
                for element in noeud.items
                if element.optional_vars is not None
            )
        )
    if isinstance(noeud, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return {noeud.name}
    return set()


def _imports_module(
    corps: list[ast.stmt],
) -> tuple[_CollecteAliases, set[str]]:
    """Collecte les liaisons du namespace du module : ses imports ET ses écrasements.

    Les blocs module-level — ``if`` (notamment ``if TYPE_CHECKING:``), ``for``,
    ``while``, ``with``, ``try`` et ``match`` — sont parcourus dans les DEUX
    sens, car ils lient le module exactement comme son premier niveau : leurs
    imports prouvent un alias, leurs affectations le détruisent. Ne descendre
    que pour les imports laissait une réaffectation cachée d'un seul cran
    conserver l'alias, donc exempter une classe qui hérite en réalité d'``object``.

    Les corps de fonctions et de méthodes ne sont jamais parcourus : leur portée
    est locale, si bien qu'un import local ne crée aucune exemption globale et
    qu'une affectation locale n'invalide aucun alias du module.
    """
    aliases = _CollecteAliases()
    reassignees: set[str] = set()

    def visiter(instructions: list[ast.stmt]) -> None:
        for noeud in instructions:
            reassignees.update(_noms_cibles_affectation(noeud))
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    if alias.name == "typing":
                        aliases.modules_typing.add(alias.asname or "typing")
                    elif alias.name == "abc":
                        aliases.modules_abc.add(alias.asname or "abc")
                    elif alias.name == "pytest":
                        aliases.modules_pytest.add(alias.asname or "pytest")
                    elif alias.name == "unittest":
                        aliases.modules_unittest.add(alias.asname or "unittest")
            elif isinstance(noeud, ast.ImportFrom):
                origine = noeud.module or ""
                if origine == "typing":
                    aliases.protocols.update(
                        alias.asname or "Protocol"
                        for alias in noeud.names
                        if alias.name == "Protocol"
                    )
                elif origine == "abc":
                    aliases.abstractmethods.update(
                        alias.asname or "abstractmethod"
                        for alias in noeud.names
                        if alias.name == "abstractmethod"
                    )
                elif origine == "builtins":
                    aliases.not_implemented_errors.update(
                        alias.asname or alias.name
                        for alias in noeud.names
                        if alias.name in {"NotImplementedError", "NotImplemented"}  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
                    )
                elif origine in _APPELS_DE_SAUT:
                    if origine == "pytest":
                        aliases.marques_pytest.update(
                            alias.asname or "mark"
                            for alias in noeud.names
                            if alias.name == "mark"
                        )
                    if origine == "unittest":
                        aliases.test_cases.update(
                            alias.asname or alias.name
                            for alias in noeud.names
                            if alias.name in _NOMS_TEST_CASE_UNITTEST
                        )
                    aliases.sauts_directs.update(
                        alias.asname or alias.name
                        for alias in noeud.names
                        if alias.name in _APPELS_DE_SAUT[origine]
                    )
            elif isinstance(noeud, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                visiter(noeud.body)
                visiter(noeud.orelse)
            elif isinstance(noeud, (ast.With, ast.AsyncWith)):
                visiter(noeud.body)
            elif isinstance(noeud, ast.Try):
                visiter(noeud.body)
                visiter(noeud.orelse)
                visiter(noeud.finalbody)
                for gestionnaire in noeud.handlers:
                    visiter(gestionnaire.body)
            elif isinstance(noeud, ast.Match):
                for cas in noeud.cases:
                    visiter(cas.body)

    visiter(corps)
    return aliases, reassignees


def _analyser_imports(arbre: ast.Module) -> _AliasesImports:
    """Prouve les imports module-level et retire toute liaison qui les écrase.

    Toute définition, affectation, cible de boucle ou cible de contexte au niveau
    module retire l'alias, à quelque profondeur de bloc qu'elle soit écrite. Cette
    règle fail-closed empêche une exemption lorsque l'origine standard du nom
    n'est plus certaine, et elle s'applique sans tenir compte de l'ORDRE : une
    réaffectation écrite avant l'import compte autant qu'une réaffectation écrite
    après lui.
    """
    aliases, reassignees = _imports_module(arbre.body)
    aliases.retirer(reassignees)
    return aliases.figer()


def _est_classe_protocol(classe: ast.ClassDef, aliases: _AliasesImports) -> bool:
    """Détermine si une base est prouvée comme le véritable typing.Protocol.

    La forme paramétrée ``Protocol[T]`` est un ``ast.Subscript`` : la valeur
    souscrite est dépliée avant la preuve, car un protocole générique est la même
    abstraction que sa forme nue. La preuve d'origine de l'alias est inchangée :
    une classe locale usurpant le nom reste refusée sous les deux formes.
    """
    for base in classe.bases:
        cible = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(cible, ast.Name) and cible.id in aliases.protocols:
            return True
        if (
            isinstance(cible, ast.Attribute)
            and isinstance(cible.value, ast.Name)
            and cible.value.id in aliases.modules_typing
            and cible.attr == "Protocol"
        ):
            return True
    return False


def _base_declaree(base: ast.expr) -> ast.expr:
    """Déplie la forme paramétrée ``Base[T]``, qui désigne la même classe que ``Base``."""
    return base.value if isinstance(base, ast.Subscript) else base


def _noms_de_classes_derivees(
    arbre: ast.Module,
    est_base_prouvee: Callable[[ast.expr], bool],
) -> frozenset[str]:
    """Résout par POINT FIXE les classes du module dérivant d'une base prouvée.

    L'héritage indirect vaut l'héritage direct : une classe qui dérive d'une
    classe elle-même dérivée de la base visée EST de ce type, et s'arrêter au
    premier cran manquerait toute hiérarchie intermédiaire — un socle de tests
    partagé, une racine d'erreurs propre au module. Le parcours s'arrête dès
    qu'un tour n'ajoute plus rien, ce qui le borne même sur un héritage
    circulaire : Python refuse cette forme à l'exécution, mais un fichier
    analysé peut la contenir.

    Seules les bases nommées du MÊME module sont suivies : un nom importé d'un
    autre module n'est pas résolvable statiquement et ne prouve donc rien.
    """
    classes = [noeud for noeud in ast.walk(arbre) if isinstance(noeud, ast.ClassDef)]
    derivees: set[str] = set()
    ajout = True
    while ajout:
        ajout = False
        for classe in classes:
            if classe.name in derivees:
                continue
            for base in classe.bases:
                cible = _base_declaree(base)
                if est_base_prouvee(cible) or (
                    isinstance(cible, ast.Name) and cible.id in derivees
                ):
                    derivees.add(classe.name)
                    ajout = True
                    break
    return frozenset(derivees)


def _est_base_exception_builtin(base: ast.expr) -> bool:
    """Reconnaît une base d'exception fournie par builtins, nue ou qualifiée.

    La liste des noms est LUE dans ``builtins`` à l'import du gate, jamais
    recopiée : toute hiérarchie d'exceptions de l'interpréteur est ainsi couverte
    sans qu'un oubli de recopie puisse rendre un type d'exception méconnaissable.
    """
    if isinstance(base, ast.Name):
        return base.id in _NOMS_EXCEPTIONS_BUILTINS
    return isinstance(base, ast.Attribute) and base.attr in _NOMS_EXCEPTIONS_BUILTINS


def _est_base_test_case(base: ast.expr, aliases: _AliasesImports) -> bool:
    """Prouve qu'une base désigne réellement un cas de test ``unittest``.

    L'origine est prouvée par les imports du module, jamais par le nom seul :
    ``import unittest`` puis ``unittest.TestCase``, ou ``from unittest import
    TestCase`` sous son nom comme sous un alias. Le sens de cette exigence est
    inverse de celui des règles de saut : ici, reconnaître un nom NON prouvé
    reviendrait à ACCEPTER un oracle inexistant, si bien qu'une classe locale
    usurpant le nom ``TestCase`` ne doit jamais suffire.
    """
    if isinstance(base, ast.Name):
        return base.id in aliases.test_cases
    return (
        isinstance(base, ast.Attribute)
        and base.attr in _NOMS_TEST_CASE_UNITTEST
        and isinstance(base.value, ast.Name)
        and base.value.id in aliases.modules_unittest
    )


def _est_methode_abstraite(
    fonction: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: _AliasesImports,
) -> bool:
    """Détermine si le décorateur vise réellement abc.abstractmethod."""
    for decorateur in fonction.decorator_list:
        cible = decorateur.func if isinstance(decorateur, ast.Call) else decorateur
        if isinstance(cible, ast.Name) and cible.id in aliases.abstractmethods:
            return True
        if (
            isinstance(cible, ast.Attribute)
            and isinstance(cible.value, ast.Name)
            and cible.value.id in aliases.modules_abc
            and cible.attr == "abstractmethod"
        ):
            return True
    return False


def _est_exception_non_implementee(noeud: ast.expr, aliases: _AliasesImports) -> bool:
    """Reconnaît l'absence d'implémentation sous ses formes simple, appelée, importée et qualifiée.

    La sentinelle et l'exception sont traitées à égalité : une forme qualifiée par
    attribut, telle qu'un accès via le module builtins, reste un stub explicite.
    """  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
    cible = noeud.func if isinstance(noeud, ast.Call) else noeud
    return (
        isinstance(cible, ast.Name)
        and cible.id
        in {
            "NotImplementedError",  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
            "NotImplemented",
        }  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
    ) or (
        isinstance(cible, ast.Name) and cible.id in aliases.not_implemented_errors
    ) or (
        isinstance(cible, ast.Attribute)
        and cible.attr
        in {
            "NotImplementedError",  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet du test
            "NotImplemented",
        }  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
    )


def _leve_not_implemented(
    fonction: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: _AliasesImports,
) -> bool:
    """Recherche une levée explicite d'absence d'implémentation dans la fonction."""
    return any(
        isinstance(noeud, ast.Raise)
        and noeud.exc is not None
        and _est_exception_non_implementee(noeud.exc, aliases)
        for noeud in ast.walk(fonction)
    )


def _est_retour_vide(noeud: ast.stmt) -> bool:
    """Reconnaît return et return None, deux formes sans comportement utile."""
    return isinstance(noeud, ast.Return) and (
        noeud.value is None
        or isinstance(noeud.value, ast.Constant)
        and noeud.value.value is None
    )


def _est_instruction_triviale(noeud: ast.stmt) -> bool:
    """Reconnaît les instructions qui ne réalisent aucun travail observable."""
    return (
        isinstance(noeud, ast.Pass)
        or _est_retour_vide(noeud)
        or isinstance(noeud, ast.Expr)
        and isinstance(noeud.value, ast.Constant)
        and noeud.value.value is Ellipsis
    )


def _analyser_fonction(
    repo: Path,
    fichier: Path,
    fonction: ast.FunctionDef | ast.AsyncFunctionDef,
    dans_protocol: bool,
    aliases: _AliasesImports,
) -> list[Violation]:
    """Applique les règles anti-stub locales à une fonction."""
    violations: list[Violation] = []
    utile = _corps_utile(fonction.body)

    if len(fonction.body) == 1 and _est_docstring(fonction.body[0]):
        violations.append(
            _violation(
                "DOCSTRING_ONLY_BODY",
                repo,
                fichier,
                fonction.lineno,
                "le corps de la fonction ne contient qu'une docstring",
            )
        )

    est_ellipse_unique = (
        len(utile) == 1
        and isinstance(utile[0], ast.Expr)
        and isinstance(utile[0].value, ast.Constant)
        and utile[0].value.value is Ellipsis
    )
    if est_ellipse_unique and (
        dans_protocol or _est_methode_abstraite(fonction, aliases)
    ):
        return violations

    if utile and all(_est_instruction_triviale(noeud) for noeud in utile):
        code = "EXECUTABLE_ELLIPSIS" if est_ellipse_unique else "EXECUTABLE_PASS"
        detail = (
            "le corps exécutable est réduit à une ellipse"
            if est_ellipse_unique
            else "le corps exécutable ne contient que des instructions triviales"
        )
        violations.append(_violation(code, repo, fichier, fonction.lineno, detail))

    if _leve_not_implemented(fonction, aliases):
        violations.append(
            _violation(
                "NOT_IMPLEMENTED_STUB",
                repo,
                fichier,
                fonction.lineno,
                "la fonction lève une exception d'absence d'implémentation",
            )
        )
    return violations


def _analyser_classe(
    repo: Path,
    fichier: Path,
    classe: ast.ClassDef,
    exceptions: frozenset[str],
) -> list[Violation]:
    """Refuse un corps de CLASSE réduit à un stub, hors types d'exception.

    Le corps d'une classe s'exécute à la création de la classe : réduit à
    ``pass`` ou à une ellipse, il ne déclare rien de plus que son en-tête et
    relève exactement de la même dette qu'un corps de fonction vide. La règle
    des fonctions est reprise à l'identique, docstring seule comprise :
    documenter un vide ne le remplit pas.

    Un TYPE D'EXCEPTION en est exempté, et lui seul. ``class Panne(ValueError):
    pass`` est du code COMPLET : l'identité du type est tout son contenu,
    puisqu'elle se lève et se rattrape sélectivement — il n'y a rien d'autre à
    écrire. MESURÉ sur les racines contractuelles de ce dépôt : 21 des 99 classes
    ont un corps vide, et TOUTES sont des types d'exception ; les signaler
    produirait 21 faux positifs sur un idiome Python courant, ce qui pousserait à
    désarmer le gate au lieu de le respecter.

    L'exemption tient à la nature du type, jamais au simple fait d'hériter :
    ``class Service(Base): pass`` reste refusée, car une classe métier vide
    n'annonce aucune implémentation.
    """
    if classe.name in exceptions:
        return []

    if len(classe.body) == 1 and _est_docstring(classe.body[0]):
        return [
            _violation(
                "DOCSTRING_ONLY_BODY",
                repo,
                fichier,
                classe.lineno,
                "le corps de la classe ne contient qu'une docstring",
            )
        ]

    utile = _corps_utile(classe.body)
    if not utile or not all(_est_instruction_triviale(noeud) for noeud in utile):
        return []

    est_ellipse_unique = (
        len(utile) == 1
        and isinstance(utile[0], ast.Expr)
        and isinstance(utile[0].value, ast.Constant)
        and utile[0].value.value is Ellipsis
    )
    code = "EXECUTABLE_ELLIPSIS" if est_ellipse_unique else "EXECUTABLE_PASS"
    detail = (
        "le corps de la classe est réduit à une ellipse"
        if est_ellipse_unique
        else "le corps de la classe ne contient que des instructions triviales"
    )
    return [_violation(code, repo, fichier, classe.lineno, detail)]


def _instructions_hors_fonction(corps: list[ast.stmt]) -> list[ast.stmt]:
    """Énumère les instructions exécutées hors de tout corps de fonction.

    Les blocs module et les corps de classes sont parcourus car ils s'exécutent à
    l'import ; les corps de fonctions ne le sont jamais, puisque
    ``_analyser_fonction`` les juge déjà et qu'un double comptage transformerait
    un seul défaut en deux violations.
    """
    instructions: list[ast.stmt] = []
    for noeud in corps:
        instructions.append(noeud)
        if isinstance(noeud, ast.ClassDef):
            instructions.extend(_instructions_hors_fonction(noeud.body))
        elif isinstance(noeud, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            instructions.extend(_instructions_hors_fonction(noeud.body))
            instructions.extend(_instructions_hors_fonction(noeud.orelse))
        elif isinstance(noeud, (ast.With, ast.AsyncWith)):
            instructions.extend(_instructions_hors_fonction(noeud.body))
        elif isinstance(noeud, (ast.Try, ast.TryStar)):
            instructions.extend(_instructions_hors_fonction(noeud.body))
            instructions.extend(_instructions_hors_fonction(noeud.orelse))
            instructions.extend(_instructions_hors_fonction(noeud.finalbody))
            for gestionnaire in noeud.handlers:
                instructions.extend(_instructions_hors_fonction(gestionnaire.body))
        elif isinstance(noeud, ast.Match):
            for cas in noeud.cases:
                instructions.extend(_instructions_hors_fonction(cas.body))
    return instructions


def _analyser_absences_hors_fonction(
    repo: Path,
    fichier: Path,
    arbre: ast.Module,
    aliases: _AliasesImports,
) -> list[Violation]:
    """Refuse une absence d'implémentation levée hors de toute fonction.

    Un module ou une classe qui lève cette exception échoue À L'IMPORT, et échoue
    précisément parce que le code n'est pas écrit : c'est le stub le plus visible
    qui soit, et il échappait entièrement au parcours limité aux fonctions.
    """
    return [
        _violation(
            "NOT_IMPLEMENTED_STUB",
            repo,
            fichier,
            noeud.lineno,
            "une exception d'absence d'implémentation est levée hors de toute "
            "fonction, donc à l'import",
        )
        for noeud in _instructions_hors_fonction(arbre.body)
        if isinstance(noeud, ast.Raise)
        and noeud.exc is not None
        and _est_exception_non_implementee(noeud.exc, aliases)
    ]


def _analyser_lambdas(repo: Path, fichier: Path, arbre: ast.Module) -> list[Violation]:
    """Refuse les lambdas réduits à None ou Ellipsis, stubs hors fonction."""
    violations: list[Violation] = []
    for noeud in ast.walk(arbre):
        if (
            isinstance(noeud, ast.Lambda)
            and isinstance(noeud.body, ast.Constant)
            and noeud.body.value in {None, Ellipsis}
        ):
            violations.append(
                _violation(
                    "EXECUTABLE_ELLIPSIS",
                    repo,
                    fichier,
                    noeud.lineno,
                    "le lambda est réduit à une valeur de stub",
                )
            )
    return violations


def _analyser_stubs(repo: Path, fichier: Path, arbre: ast.Module) -> list[Violation]:
    """Parcourt tous les blocs en conservant le contexte Protocol des classes."""
    aliases = _analyser_imports(arbre)
    exceptions = _noms_de_classes_derivees(arbre, _est_base_exception_builtin)
    violations: list[Violation] = []

    class Visiteur(ast.NodeVisitor):
        """Visite chaque définition sans perdre le contexte de sa classe parente."""

        def __init__(self) -> None:
            self.protocols: list[bool] = [False]

        def visit_ClassDef(self, noeud: ast.ClassDef) -> None:
            violations.extend(_analyser_classe(repo, fichier, noeud, exceptions))
            self.protocols.append(_est_classe_protocol(noeud, aliases))
            self.generic_visit(noeud)
            self.protocols.pop()

        def visit_FunctionDef(self, noeud: ast.FunctionDef) -> None:
            violations.extend(
                _analyser_fonction(repo, fichier, noeud, self.protocols[-1], aliases)
            )
            self.protocols.append(False)
            self.generic_visit(noeud)
            self.protocols.pop()

        def visit_AsyncFunctionDef(self, noeud: ast.AsyncFunctionDef) -> None:
            violations.extend(
                _analyser_fonction(repo, fichier, noeud, self.protocols[-1], aliases)
            )
            self.protocols.append(False)
            self.generic_visit(noeud)
            self.protocols.pop()

    Visiteur().visit(arbre)
    violations.extend(_analyser_absences_hors_fonction(repo, fichier, arbre, aliases))
    violations.extend(_analyser_lambdas(repo, fichier, arbre))
    return violations


def _est_fichier_production(fichier: Path) -> bool:
    """Exclut les fichiers de test de la règle réservée aux modules de production."""
    return not (fichier.name.startswith("test_") or fichier.name.endswith("_test.py"))


def _est_vide_autorise(fichier: Path) -> bool:
    """Reconnaît les deux exceptions explicites aux modules Python vides."""
    return fichier.name in {"__init__.py", ".gitkeep"}


def _lignes_du_diff(repo: Path, fichier: Path, base_ref: str, contenu: str) -> set[int]:
    """Retourne les lignes ajoutées par Git, avec repli fermé pour non suivis."""
    relatif = _chemin_relatif(repo, fichier)
    suivi = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relatif],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if suivi.returncode != 0:
        return set(range(1, len(contenu.splitlines()) + 1))
    resultat = subprocess.run(
        ["git", "diff", "--unified=0", f"{base_ref}...HEAD", "--", relatif],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return (
        _parser_hunks(resultat.stdout)
        if resultat.returncode == 0
        else set(range(1, len(contenu.splitlines()) + 1))
    )


def _parser_hunks(diff: str) -> set[int]:
    """Parse les en-têtes de hunk unifié afin d'obtenir les lignes nouvelles."""
    lignes: set[int] = set()
    for ligne in diff.splitlines():
        if not ligne.startswith("@@ "):
            continue
        morceaux = ligne.split()
        if len(morceaux) < 3 or not morceaux[2].startswith("+"):
            continue
        debut_texte, separateur, compte_texte = morceaux[2][1:].partition(",")
        try:
            debut = int(debut_texte)
            compte = int(compte_texte) if separateur else 1
        except ValueError:
            continue
        lignes.update(range(debut, debut + compte))
    return lignes


def _fonction_modifiee(
    fonction: ast.FunctionDef | ast.AsyncFunctionDef,
    lignes: set[int],
) -> bool:
    """Indique si une ligne du rectangle source de la fonction est dans le diff."""
    fin = getattr(fonction, "end_lineno", fonction.lineno)
    return any(ligne in lignes for ligne in range(fonction.lineno, fin + 1))


def _est_constante_vraie(expression: ast.expr) -> bool:
    """Reconnaît une constante AST dont la vérité est établie sans exécution."""
    return isinstance(expression, ast.Constant) and bool(expression.value)


def _est_appel_pytest(
    noeud: ast.Call,
    attribut: str,
    aliases: _AliasesImports,
) -> bool:
    """Reconnaît ``pytest.<attribut>`` sous le nom canonique comme sous ses alias.

    L'origine est prouvée par les imports déjà résolus du module, le même
    mécanisme que la détection des sauts : renommer ``pytest`` à l'import ne
    change rien à ce que l'oracle vérifie, et refuser un test légitime pousse à
    désarmer le gate. La qualification est conservée en sens inverse : un
    homonyme métier — ``mon_module.raises(...)`` — ne prouve toujours aucun
    oracle.
    """
    cible = noeud.func
    if not (isinstance(cible, ast.Attribute) and cible.attr == attribut):
        return False
    porteur = cible.value
    return isinstance(porteur, ast.Name) and (
        porteur.id == "pytest" or porteur.id in aliases.modules_pytest
    )


def _receveurs_de_cas_de_test(
    arbre: ast.Module,
    aliases: _AliasesImports,
) -> dict[ast.stmt, str]:
    """Associe chaque méthode d'un cas de test ``unittest`` au nom de son receveur.

    Le receveur est le PREMIER paramètre de la méthode — ``self`` par convention,
    mais librement renommable : c'est lui, et lui seul, qui porte les oracles
    hérités d'``unittest.TestCase``. Une méthode sans paramètre, telle une
    ``staticmethod``, n'a aucun receveur et n'est donc pas recensée.
    """
    cas_de_test = _noms_de_classes_derivees(
        arbre, lambda base: _est_base_test_case(base, aliases)
    )
    receveurs: dict[ast.stmt, str] = {}
    for noeud in ast.walk(arbre):
        if not (isinstance(noeud, ast.ClassDef) and noeud.name in cas_de_test):
            continue
        for membre in noeud.body:
            if (
                isinstance(membre, (ast.FunctionDef, ast.AsyncFunctionDef))
                and membre.args.args
            ):
                receveurs[membre] = membre.args.args[0].arg
    return receveurs


def _est_oracle_unittest(noeud: ast.Call, receveur: str | None) -> bool:
    """Reconnaît un ``self.assertXxx(…)`` porté par le receveur d'un cas de test.

    Les deux preuves sont exigées ensemble : le nom de la méthode appelée ET
    l'appartenance à une classe dont l'héritage ``unittest.TestCase`` est établi.
    """
    return (
        receveur is not None
        and isinstance(noeud.func, ast.Attribute)
        and noeud.func.attr.startswith("assert")
        and isinstance(noeud.func.value, ast.Name)
        and noeud.func.value.id == receveur
    )


def _contient_oracle(
    fonction: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: _AliasesImports,
    receveur: str | None,
) -> bool:
    """Détermine si une fonction de test contient au moins un oracle PROUVÉ.

    Un appel ``…assertXxx(…)`` ne compte que porté par le receveur d'une méthode
    dont la classe hérite RÉELLEMENT d'``unittest.TestCase``. Accepter tout
    attribut dont le nom commence par ``assert`` suffisait à faire passer un test
    qui ne vérifie rien : il suffisait de nommer ainsi une méthode métier —
    ``Silencieux().assert_rien()`` — pour fabriquer un oracle de façade.

    L'assertion nue et ``pytest.raises`` restent les oracles de référence du
    dépôt, inchangés : le durcissement ne retire que ce qui n'était jamais prouvé.
    """
    for noeud in ast.walk(fonction):
        if isinstance(noeud, ast.Assert):
            return True
        if isinstance(noeud, ast.With) and any(
            isinstance(element.context_expr, ast.Call)
            and _est_appel_pytest(element.context_expr, "raises", aliases)
            for element in noeud.items
        ):
            return True
        if isinstance(noeud, ast.Call) and (
            _est_appel_pytest(noeud, "fail", aliases)
            or _est_oracle_unittest(noeud, receveur)
        ):
            return True
    return False


def _est_marque_de_saut_pytest(cible: ast.expr, aliases: _AliasesImports) -> bool:
    """Reconnaît ``pytest.mark.<saut>`` sous le nom canonique comme sous ses alias.

    Le porteur de la marque est prouvé de deux façons : un module importé sous un
    autre nom (``import pytest as pt`` puis ``pt.mark.skip``) ou la marque
    elle-même importée (``from pytest import mark`` puis ``mark.skip``). Renommer
    un import ne change rien à ce que pytest exécute : le saut reste un saut.
    """
    if not (isinstance(cible, ast.Attribute) and cible.attr in _MARQUES_DE_SAUT_PYTEST):
        return False
    porteur = cible.value
    if isinstance(porteur, ast.Name):
        return porteur.id in aliases.marques_pytest
    return (
        isinstance(porteur, ast.Attribute)
        and porteur.attr == "mark"
        and isinstance(porteur.value, ast.Name)
        and (
            porteur.value.id == "pytest" or porteur.value.id in aliases.modules_pytest
        )
    )


def _est_saut_qualifie(cible: ast.expr, aliases: _AliasesImports) -> bool:
    """Reconnaît ``<module>.<saut>`` où le module est prouvé pytest ou unittest.

    Le nom canonique est reconnu inconditionnellement, l'alias uniquement s'il
    est PROUVÉ par un import du module correspondant. Ce sens est délibéré : sans
    le nom canonique, un fichier qui réaffecte ``pytest`` désarmerait la règle,
    et sans la preuve d'import, un homonyme métier serait un faux positif.
    """
    if not (isinstance(cible, ast.Attribute) and isinstance(cible.value, ast.Name)):
        return False
    porteur = cible.value.id
    if cible.attr in _APPELS_DE_SAUT.get(porteur, frozenset()):
        return True
    if porteur in aliases.modules_pytest and cible.attr in _APPELS_DE_SAUT["pytest"]:
        return True
    return (
        porteur in aliases.modules_unittest
        and cible.attr in _APPELS_DE_SAUT["unittest"]
    )


def _est_decorateur_skip_ou_xfail(
    decorateur: ast.expr,
    aliases: _AliasesImports,
) -> bool:
    """Reconnaît les décorateurs de saut, y compris la forme conditionnelle.

    ``skipif`` saute exactement comme ``skip`` dès que sa condition est vraie :
    l'exclure laisserait un test ajouté ne jamais s'exécuter tout en paraissant
    présent dans la suite. Le nom nu — ``from unittest import skip`` puis
    ``@skip`` — n'est jugé que si son import prouve son origine.
    """
    cible = decorateur.func if isinstance(decorateur, ast.Call) else decorateur
    if isinstance(cible, ast.Name):
        return cible.id in aliases.sauts_directs
    return _est_marque_de_saut_pytest(cible, aliases) or _est_saut_qualifie(
        cible, aliases
    )


def _est_appel_de_saut(noeud: ast.Call, aliases: _AliasesImports) -> bool:
    """Reconnaît un appel qui saute ou abandonne un test, qualifié par son origine.

    La qualification est conservée : un homonyme porté par un objet métier
    (``lecteur.skipIf(…)``) ou par une instance (``self.skip(…)``) ne saute rien
    et ne doit jamais être confondu avec la dette visée.
    """
    cible = noeud.func
    if isinstance(cible, ast.Name):
        return cible.id in aliases.sauts_directs
    return _est_saut_qualifie(cible, aliases)


def _analyser_ast_diff(
    repo: Path,
    fichier: Path,
    arbre: ast.Module,
    lignes: set[int],
) -> list[Violation]:
    """Applique les règles AST limitées aux éléments effectivement modifiés."""
    aliases = _analyser_imports(arbre)
    receveurs = _receveurs_de_cas_de_test(arbre, aliases)
    violations: list[Violation] = []
    for noeud in ast.walk(arbre):
        if (
            isinstance(noeud, ast.Assert)
            and noeud.lineno in lignes
            and _est_constante_vraie(noeud.test)
        ):
            violations.append(
                _violation(
                    "TRIVIAL_ASSERTION",
                    repo,
                    fichier,
                    noeud.lineno,
                    "l'assertion porte sur une constante vraie",
                )
            )
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if noeud.name.startswith("test_") and _fonction_modifiee(noeud, lignes):
                if not _contient_oracle(noeud, aliases, receveurs.get(noeud)):
                    violations.append(
                        _violation(
                            "TEST_WITHOUT_ORACLE",
                            repo,
                            fichier,
                            noeud.lineno,
                            "le test modifié ne contient aucun oracle",
                        )
                    )
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Les classes portent les mêmes décorateurs : pytest applique une
            # marque de classe à CHACUNE de ses méthodes de test. Ne lire que les
            # fonctions laissait déserter une suite entière d'un seul décorateur
            # déplacé d'un cran vers le haut.
            for decorateur in noeud.decorator_list:
                if decorateur.lineno in lignes and _est_decorateur_skip_ou_xfail(
                    decorateur, aliases
                ):
                    violations.append(
                        _violation(
                            "NEW_SKIP_OR_XFAIL",
                            repo,
                            fichier,
                            decorateur.lineno,
                            "un décorateur skip ou xfail a été ajouté",
                        )
                    )
        if isinstance(noeud, ast.Call) and noeud.lineno in lignes:
            if _est_appel_de_saut(noeud, aliases):
                violations.append(
                    _violation(
                        "NEW_SKIP_OR_XFAIL",
                        repo,
                        fichier,
                        noeud.lineno,
                        "un appel de skip a été ajouté",
                    )
                )
    return violations


def _est_cible_controle_perimetre(repo: Path, fichier: Path) -> bool:
    """Limite la preuve aux lanceurs core/scripts/run_* responsables du périmètre."""
    relatif = fichier.relative_to(repo)
    return (
        len(relatif.parts) >= 3
        and relatif.parts[:2] == ("core", "scripts")
        and fichier.name.startswith("run_")
    )


def _valeurs_litterales(noeud: ast.expr) -> set[str] | None:
    """Extrait les chaînes d'une collection littérale ou concaténation de listes."""
    if isinstance(noeud, (ast.List, ast.Tuple, ast.Set)):
        if not all(
            isinstance(element, ast.Constant) and isinstance(element.value, str)
            for element in noeud.elts
        ):
            return None
        return {
            element.value
            for element in noeud.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
    if isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Add):
        gauche = _valeurs_litterales(noeud.left)
        droite = _valeurs_litterales(noeud.right)
        if gauche is not None and droite is not None:
            return gauche | droite
    return None


def _est_nom_racine(noeud: ast.expr, nom_boucle: str) -> bool:
    """Indique si une expression désigne la variable de boucle de compréhension."""
    return isinstance(noeud, ast.Name) and noeud.id == nom_boucle


def _comparaison_exclut_racine(noeud: ast.expr, nom_boucle: str) -> bool:
    """Détecte une exclusion littérale, y compris dans une condition composée."""
    if isinstance(noeud, ast.BoolOp):
        return any(
            _comparaison_exclut_racine(valeur, nom_boucle)
            for valeur in noeud.values
        )
    if isinstance(noeud, ast.UnaryOp) and isinstance(noeud.op, ast.Not):
        return _comparaison_exclut_racine(noeud.operand, nom_boucle)
    if not isinstance(noeud, ast.Compare) or len(noeud.ops) != 1:
        return False
    if len(noeud.comparators) != 1:
        return False

    comparateur = noeud.comparators[0]
    operateur = noeud.ops[0]
    if isinstance(operateur, (ast.NotEq, ast.NotIn)):
        return _est_nom_racine(noeud.left, nom_boucle) and (
            isinstance(comparateur, ast.Constant)
            and isinstance(comparateur.value, str)
            or _valeurs_litterales(comparateur) is not None
        )
    if isinstance(operateur, (ast.Eq, ast.In)):
        return (
            isinstance(comparateur, ast.Name)
            and comparateur.id == nom_boucle
            and (
                isinstance(noeud.left, ast.Constant)
                and isinstance(noeud.left.value, str)
                or _valeurs_litterales(noeud.left) is not None
            )
        )
    return False


_NOMS_ITERABLES_RACINES = frozenset(
    {"racines", "roots", "python_roots", "racines_contractuelles", "scopes"}
)


def _itere_sur_les_racines(generateur: ast.comprehension) -> bool:
    """Indique si la compréhension parcourt bien les racines contractuelles."""
    iterable = generateur.iter
    if isinstance(iterable, ast.Name):
        return iterable.id in _NOMS_ITERABLES_RACINES
    if isinstance(iterable, ast.Call):
        cible = iterable.func
        nom = cible.attr if isinstance(cible, ast.Attribute) else getattr(cible, "id", "")
        return "racine" in nom.lower() or "root" in nom.lower()
    return False


def _comprehension_filtre_racines(noeud: ast.expr) -> bool:
    """Détecte une exclusion littérale seulement sur une itération de racines prouvée."""
    if not isinstance(noeud, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return False
    return any(
        isinstance(generateur.target, ast.Name)
        and _itere_sur_les_racines(generateur)
        and any(
            _comparaison_exclut_racine(condition, generateur.target.id)
            for condition in generateur.ifs
        )
        for generateur in noeud.generators
    )


def _est_appel_exists(noeud: ast.expr) -> bool:
    """Reconnaît le filtre d'existence légitime qui ne retire pas une racine connue."""
    cible = noeud.func if isinstance(noeud, ast.Call) else noeud
    return isinstance(cible, ast.Attribute) and cible.attr == "exists"


def _filtre_statiquement_decidable(noeud: ast.expr, nom_boucle: str) -> bool:
    """Distingue un filtre littéral prouvable d'une exclusion indirecte inconnue."""
    if _comparaison_exclut_racine(noeud, nom_boucle) or _est_appel_exists(noeud):
        return True
    if isinstance(noeud, ast.BoolOp):
        return all(
            _filtre_statiquement_decidable(valeur, nom_boucle)
            for valeur in noeud.values
        )
    if isinstance(noeud, ast.UnaryOp) and isinstance(noeud.op, ast.Not):
        return _filtre_statiquement_decidable(noeud.operand, nom_boucle)
    return False


def _comprehension_filtre_indecidable(noeud: ast.expr) -> bool:
    """Prouve qu'un filtre de racines ne peut pas être décidé statiquement."""
    if not isinstance(noeud, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return False
    return any(
        isinstance(generateur.target, ast.Name)
        and _itere_sur_les_racines(generateur)
        and any(
            not _filtre_statiquement_decidable(condition, generateur.target.id)
            for condition in generateur.ifs
        )
        for generateur in noeud.generators
    )


_MOTS_DECLARATION_PERIMETRE: Final[frozenset[str]] = frozenset(
    {"argv", "cible", "perimetre", "racine", "root", "scope", "target"}
)

_PARTIES_IDENTIFIANT: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def _nom_designe_un_perimetre(nom: str) -> bool:
    """Prouve par son NOM qu'un identifiant annonce une déclaration de périmètre.

    Le nom est découpé sur ses séparateurs puis comparé mot à mot, jamais par
    sous-chaîne : ``python_roots``, ``cibles`` ou ``argv`` annoncent un
    périmètre, alors qu'un mot qui contient ces lettres par hasard ne l'annonce
    pas. Le pluriel est ramené au singulier parce que les deux formes désignent
    la même chose.
    """
    for partie in _PARTIES_IDENTIFIANT.split(nom.lower()):
        if partie in _MOTS_DECLARATION_PERIMETRE:
            return True
        if partie.endswith("s") and partie[:-1] in _MOTS_DECLARATION_PERIMETRE:
            return True
    return False


def _nom_identifiant(noeud: ast.expr) -> str:
    """Retourne l'identifiant lisible d'une cible ou d'un appelé, sinon rien."""
    if isinstance(noeud, ast.Name):
        return noeud.id
    if isinstance(noeud, ast.Attribute):
        return noeud.attr
    return ""


def _expressions_de_perimetre(arbre: ast.Module) -> set[ast.expr]:
    """Recense les expressions dont le CONTEXTE prouve une déclaration de périmètre.

    Ce recensement existe pour lever une condition de fail-open : ne signaler
    une omission que lorsqu'il RESTE au moins une racine offrait la sortie
    exactement inverse de l'intention du contrôle, puisque désarmer un lanceur
    se fait en retirant TOUTES les racines d'un coup, jamais une seule.

    La preuve reste le contexte, jamais le contenu : une collection anonyme de
    chaînes quelconques n'est pas jugée, sans quoi tout message ou drapeau
    littéral d'un lanceur deviendrait un faux positif. Quatre contextes la
    prouvent — affectation à un nom ou à un attribut de périmètre, affectation
    annotée, argument nommé de périmètre, argument d'un appel dont le nom
    l'annonce.
    """
    declarations: set[ast.expr] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Assign):
            if any(
                _nom_designe_un_perimetre(_nom_identifiant(cible))
                for cible in noeud.targets
            ):
                declarations.add(noeud.value)
        elif isinstance(noeud, ast.AnnAssign):
            if noeud.value is not None and _nom_designe_un_perimetre(
                _nom_identifiant(noeud.target)
            ):
                declarations.add(noeud.value)
        elif isinstance(noeud, ast.keyword):
            if noeud.arg is not None and _nom_designe_un_perimetre(noeud.arg):
                declarations.add(noeud.value)
        elif isinstance(noeud, ast.Call):
            if _nom_designe_un_perimetre(_nom_identifiant(noeud.func)):
                declarations.update(noeud.args)
    return declarations


def _analyser_omissions_racines(
    repo: Path,
    fichier: Path,
    arbre: ast.Module,
    racines: tuple[str, ...] | None,
) -> list[Violation]:
    """Prouve les omissions littérales et refuse les filtres non prouvables."""
    if not racines or not _est_cible_controle_perimetre(repo, fichier):
        return []

    violations: list[Violation] = []
    ensemble_racines = set(racines)
    declarations = _expressions_de_perimetre(arbre)
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.expr):
            continue
        if _comprehension_filtre_racines(noeud):
            violations.append(
                _violation(
                    "SCOPE_ROOT_OMITTED",
                    repo,
                    fichier,
                    noeud.lineno,
                    "une compréhension exclut une racine contractuelle par identité",
                )
            )
            continue
        if _comprehension_filtre_indecidable(noeud):
            violations.append(
                _violation(
                    "SCOPE_FILTRE_INDECIDABLE",
                    repo,
                    fichier,
                    noeud.lineno,
                    "le filtre de racines n'est pas décidable statiquement ; "
                    "il doit être rendu littéral ou justifié",
                )
            )
            continue
        valeurs = _valeurs_litterales(noeud)
        if valeurs is None:
            continue
        presentes = ensemble_racines.intersection(valeurs)
        manquantes = tuple(racine for racine in racines if racine not in valeurs)
        if manquantes and (presentes or noeud in declarations):
            violations.append(
                _violation(
                    "SCOPE_ROOT_OMITTED",
                    repo,
                    fichier,
                    noeud.lineno,
                    "la liste de périmètre omet les racines contractuelles : "
                    + ", ".join(manquantes),
                )
            )
    return violations


def _marqueur_dette(commentaire: str) -> str | None:
    """Trouve un marqueur de dette isolé dans le texte d'un commentaire."""
    texte = commentaire[1:].lstrip()
    for marqueur in _DEBT_MARKERS:
        position = texte.find(marqueur)
        while position >= 0:
            avant = texte[position - 1] if position else ""
            index_apres = position + len(marqueur)
            apres = texte[index_apres] if index_apres < len(texte) else ""
            if (
                (not avant or not (avant.isalnum() or avant == "_"))
                and (not apres or not (apres.isalnum() or apres == "_"))
            ):
                return marqueur
            position = texte.find(marqueur, position + 1)
    return None


def _directives_de_suppression(commentaire: str) -> list[tuple[str, str]]:
    """Isole les directives réellement actives et leur suite dans un commentaire.

    MESURÉ sur les outils eux-mêmes — mypy 2.1.0, ruff 0.15.20, bandit 1.9.4 —
    une directive n'agit que si elle suit DIRECTEMENT un ``#`` : écrite au fil
    d'une phrase (« ne pas utiliser type: ignore ici »), elle ne supprime rien et
    la refuser était un faux positif. La borne est le ``#``, pas le début du
    jeton : ``# texte  # noqa: F401`` supprime réellement le diagnostic chez ruff
    et bandit, donc reste jugé.
    """
    directives: list[tuple[str, str]] = []
    for fragment in commentaire.split("#"):
        texte = fragment.lstrip(" \t")
        for marqueur in _SUPPRESSION_MARKERS:
            correspondance = _MOTIFS_DIRECTIVE[marqueur].match(texte)
            if correspondance is not None:
                directives.append((marqueur, texte[correspondance.end() :]))
                break
    return directives


def _justification_suffisante(suite: str) -> bool:
    """Exige une justification humaine après la directive et ses identifiants.

    Les identifiants de règles supprimés — précédés ou non de ``:``, séparés par
    des virgules — décrivent CE QUI est supprimé, jamais POURQUOI : ils sont
    consommés avant de chercher le séparateur puis le texte de justification.
    """
    reste = suite.lstrip()
    identifiants = _IDENTIFIANTS_REGLE_OPTIONNELS.match(reste)
    if identifiants is not None:
        reste = reste[identifiants.end() :].lstrip()
    return len(reste) >= 2 and reste[0] in {"—", "-", ":"} and bool(reste[1:].strip())


def _suppression_justifiee(commentaire: str) -> bool:
    """Vérifie que CHAQUE directive du commentaire porte sa justification."""
    return all(
        _justification_suffisante(suite)
        for _, suite in _directives_de_suppression(commentaire)
    )


def _supprime_le_typage(commentaire: str) -> bool:
    """Détecte une directive qui masque une erreur de typage, justifiée ou non."""
    return any(
        marqueur == _MARQUEUR_TYPE_IGNORE
        for marqueur, _ in _directives_de_suppression(commentaire)
    )


def _ligne_de_tokenisation(erreur: tokenize.TokenError) -> int:
    """Extrait la ligne rapportée par tokenize, à défaut la première du fichier."""
    if len(erreur.args) >= 2:
        position = erreur.args[1]
        if isinstance(position, tuple) and position and isinstance(position[0], int):
            return max(1, position[0])
    return 1


def _analyser_commentaires(
    repo: Path,
    fichier: Path,
    contenu: str,
    lignes: set[int],
) -> list[Violation]:
    """Analyse exclusivement les tokens COMMENT appartenant aux lignes ajoutées.

    Un fichier accepté par l'AST mais refusé par le tokeniseur ne rend aucun
    commentaire lisible : il est signalé en fail-closed, jamais tu, conformément
    à la règle du dépôt qui traite l'inanalysable comme une violation.
    """
    violations: list[Violation] = []
    try:
        for jeton in tokenize.generate_tokens(StringIO(contenu).readline):
            if jeton.type != tokenize.COMMENT or jeton.start[0] not in lignes:
                continue
            marqueur = _marqueur_dette(jeton.string)
            if marqueur is not None:
                violations.append(
                    _violation(
                        "FORBIDDEN_MARKER",
                        repo,
                        fichier,
                        jeton.start[0],
                        f"le commentaire contient le marqueur de dette {marqueur}",
                    )
                )
            if _supprime_le_typage(jeton.string):
                violations.append(
                    _violation(
                        "NEW_TYPE_IGNORE",
                        repo,
                        fichier,
                        jeton.start[0],
                        "une suppression de typage est ajoutée : masquer une erreur "
                        "de typage n'est pas une dette justifiable",
                    )
                )
            if not _suppression_justifiee(jeton.string):
                violations.append(
                    _violation(
                        "UNJUSTIFIED_SUPPRESSION",
                        repo,
                        fichier,
                        jeton.start[0],
                        "la suppression de contrôle n'a pas de justification structurée",
                    )
                )
    except tokenize.TokenError as erreur:
        message = erreur.args[0] if erreur.args else erreur
        violations.append(
            _violation(
                "FICHIER_NON_ANALYSABLE",
                repo,
                fichier,
                _ligne_de_tokenisation(erreur),
                f"tokenisation impossible : {message}",
            )
        )
    return violations


def _analyser_fichier_python(
    repo: Path,
    fichier: Path,
    base_ref: str,
    racines_contractuelles: tuple[str, ...] | None,
) -> list[Violation]:
    """Analyse un fichier Python et refuse toute lecture ou syntaxe invalide.

    Partage DÉLIBÉRÉ du périmètre entre les règles — à ne pas « harmoniser » :

    Règles jugées sur l'ÉTAT du dépôt, fichier entier, diff ignoré :

    - ``_analyser_stubs`` : un stub est un défaut de l'état livré, pas un ajout.
      Le filtrer par le diff laisserait vivre indéfiniment tout stub déjà
      commité, qu'aucun commit ultérieur ne toucherait plus jamais.
    - ``_analyser_omissions_racines`` : une racine contractuelle absente d'un
      lanceur est un trou de périmètre permanent ; réduite au diff, l'omission
      deviendrait invisible dès le commit suivant, et le périmètre non couvert
      resterait non couvert sans que rien ne le signale.

    Règles jugées sur le DIFF, lignes ajoutées seulement :

    - ``_analyser_ast_diff`` : un test sans oracle, une assertion triviale ou un
      skip sont des AJOUTS de dette ; ne juger que les lignes ajoutées cible
      l'acte du contributeur sans bloquer sur l'historique hérité.
    - ``_analyser_commentaires`` : un marqueur de dette et une suppression de
      contrôle sont des ajouts de la même nature, jugés à la même borne.

    Le dépôt est à zéro violation : les deux règles d'état ne coûtent donc rien
    aujourd'hui et garantissent qu'il en reste ainsi. Ce partage est verrouillé
    par les tests nommés ``…_choix_delibere`` de
    ``scripts/tests/test_no_stub_gate.py``.
    """
    try:
        contenu = fichier.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as erreur:
        return [
            _violation(
                "FICHIER_NON_ANALYSABLE",
                repo,
                fichier,
                1,
                f"lecture impossible : {erreur}",
            )
        ]

    if (
        not contenu.strip()
        and _est_fichier_production(fichier)
        and not _est_vide_autorise(fichier)
    ):
        return [
            _violation(
                "EMPTY_PRODUCTION_FILE",
                repo,
                fichier,
                1,
                "le module de production est vide",
            )
        ]

    try:
        arbre = ast.parse(contenu, filename=str(fichier))
    except SyntaxError as erreur:
        ligne = erreur.lineno or 1
        message = erreur.msg or str(erreur)
        return [
            _violation(
                "FICHIER_NON_ANALYSABLE",
                repo,
                fichier,
                ligne,
                f"erreur de syntaxe ligne {ligne} : {message}",
            )
        ]

    violations = _analyser_stubs(repo, fichier, arbre)
    violations.extend(
        _analyser_omissions_racines(repo, fichier, arbre, racines_contractuelles)
    )
    lignes = _lignes_du_diff(repo, fichier, base_ref, contenu)
    violations.extend(_analyser_ast_diff(repo, fichier, arbre, lignes))
    violations.extend(_analyser_commentaires(repo, fichier, contenu, lignes))
    return violations


def _type_yaml(valeur: object) -> str:
    """Décrit le type YAML effectif pour expliquer pourquoi la preuve a échoué."""
    if valeur is None:
        return "null"
    if isinstance(valeur, bool):
        return "booléen"
    if isinstance(valeur, str):
        return "chaîne"
    if isinstance(valeur, list):
        return "liste"
    if isinstance(valeur, Mapping):
        return "mapping"
    return type(valeur).__name__


def _charger_yaml(
    repo: Path,
    fichier: Path,
) -> tuple[Mapping[object, object] | None, list[Violation]]:
    """Charge YAML et refuse une racine qui ne permet pas une analyse structurée."""
    try:
        contenu = fichier.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as erreur:
        return None, [
            _violation(
                "FICHIER_NON_ANALYSABLE",
                repo,
                fichier,
                1,
                f"lecture impossible : {erreur}",
            )
        ]

    try:
        document = yaml.safe_load(contenu)
    except yaml.YAMLError as erreur:
        return None, [
            _violation(
                "FICHIER_NON_ANALYSABLE",
                repo,
                fichier,
                1,
                f"erreur YAML : {erreur}",
            )
        ]

    if document is None:
        return {}, []
    if not isinstance(document, Mapping):
        return None, [
            _violation(
                "FICHIER_NON_ANALYSABLE",
                repo,
                fichier,
                1,
                "la racine YAML doit être un mapping, "
                f"mais {_type_yaml(document)} a été trouvé",
            )
        ]
    return document, []


def _neutraliser_chaines_shell(commande: str) -> str:
    """Neutralise quotes et commentaires afin de ne prouver que le code shell.

    Les positions et retours à la ligne sont conservés. Un ``#`` n'ouvre un
    commentaire qu'après le traitement des quotes, ce qui préserve notamment les
    couleurs et autres données littérales contenant ce caractère.

    Il faut de plus qu'il soit en DÉBUT DE MOT, comme dans un shell réel :
    précédé du début de la commande, d'une espace, d'une tabulation, d'un retour
    à la ligne ou d'un séparateur ``;``, ``|``, ``&``, ``(``, ``)``. Collé à un
    mot il reste un caractère ordinaire — ``gate.py x#note || true`` exécute bien
    son repli, et ``$#`` ne coupe pas la ligne. Neutraliser jusqu'au bout de la
    ligne dans ces cas rendait invisible le code qui suit, donc muet tout contrôle
    fondé sur cette lecture.
    """
    neutre: list[str] = []
    i = 0
    n = len(commande)
    while i < n:
        caractere = commande[i]
        if caractere in {"'", '"'}:
            quote = caractere
            neutre.append(quote)
            i += 1
            while i < n:
                courant = commande[i]
                if quote == '"' and courant == "\\" and i + 1 < n:
                    suivant = commande[i + 1]
                    neutre.append(" ")
                    neutre.append("\n" if suivant == "\n" else " ")
                    i += 2
                    continue
                if courant == quote:
                    neutre.append(quote)
                    i += 1
                    break
                neutre.append("\n" if courant == "\n" else " ")
                i += 1
            continue
        if caractere == "#" and (
            i == 0 or commande[i - 1] in _OUVERTURES_DE_MOT_SHELL
        ):
            while i < n and commande[i] != "\n":
                neutre.append(" ")
                i += 1
            continue
        neutre.append(caractere)
        i += 1
    return "".join(neutre)


def _normaliser_commande(commande: str) -> str:
    """Supprime tous les espaces du code shell neutralisé pour les motifs répartis."""
    return re.sub(r"\s+", "", _neutraliser_chaines_shell(commande))


def _fin_de_groupe_shell(texte: str, ouverture: int) -> int:
    """Retourne l'index de la fermeture du groupe shell ouvert à ``ouverture``.

    Les accolades et les parenthèses sont suivies ensemble, ce qui traverse
    correctement les substitutions ``$( … )`` internes. Un groupe jamais refermé
    s'étend jusqu'à la fin de la commande : son contenu reste ainsi analysé au
    lieu d'être abandonné en silence.
    """
    profondeur = 0
    for index in range(ouverture, len(texte)):
        if texte[index] in "{(":
            profondeur += 1
        elif texte[index] in "})":
            profondeur -= 1
            if profondeur == 0:
                return index
    return len(texte)


def _derniere_commande_shell(groupe: str) -> str:
    """Isole la dernière commande utile d'un groupe, seule à fixer son code de retour.

    Le découpage retient ``;``, le retour à la ligne et ``&&`` : ce sont les
    séparateurs après lesquels la commande suivante décide du statut du groupe.
    """
    commandes = [
        morceau.strip()
        for morceau in _SEPARATEUR_COMMANDE_SHELL.split(groupe)
        if morceau.strip()
    ]
    return commandes[-1] if commandes else ""


def _groupe_propage_echec(groupe: str) -> bool:
    """Prouve qu'un groupe de repli se termine par une sortie non nulle explicite.

    Seule cette forme rend l'échec au job requis. Toute autre fin — y compris un
    ``exit 0``, un statut hérité ou une simple journalisation — laisse le groupe
    réussir, donc absorbe l'échec de la commande gardée.
    """
    derniere = _derniere_commande_shell(groupe)
    if derniere in _COMMANDES_ECHOUANT_TOUJOURS:
        return True
    correspondance = _SORTIE_NON_NULLE.match(derniere)
    return correspondance is not None and int(correspondance.group("code")) % 256 != 0


def _groupe_repli_succes(neutre: str) -> str | None:
    """Détecte un groupe ``|| { … }`` ou ``|| ( … )`` qui absorbe l'échec.

    Un groupe placé derrière ``||`` ne s'exécute que si la commande gardée a
    échoué, et devient alors le code de retour de l'étape. Il n'est licite que
    s'il se termine par une sortie non nulle prouvée : sans cela, le contrôle
    requis échoue et le job réussit quand même.
    """
    for correspondance in _GROUPE_APRES_OU.finditer(neutre):
        debut = correspondance.start("ouverture")
        fin = _fin_de_groupe_shell(neutre, debut)
        if _groupe_propage_echec(neutre[debut + 1 : fin]):
            continue
        return "{ … }" if neutre[debut] == "{" else "( … )"
    return None


def _commande_repli_succes(commande: str) -> str | None:
    """Prouve qu'une branche ``||`` se termine inconditionnellement avec succès.

    Le nom de la commande est lu APRÈS les préfixes qui ne changent pas ce qui
    s'exécute : un chemin (``/usr/bin/true``, ``/bin/true``) désigne le même
    binaire que son nom nu, et le builtin ``command`` ne fait que le lancer en
    court-circuitant fonctions et alias du shell. La borne de fin de nom survit
    au préfixe : ``/usr/bin/true_story`` reste un exécutable tiers légitime.
    """
    neutre = _neutraliser_chaines_shell(commande)
    correspondance = _FALLBACK_SHELL.search(neutre)
    if correspondance is None:
        return _groupe_repli_succes(neutre)
    commande_repli = correspondance.group("command")
    if commande_repli.startswith("echo"):
        commande_repli = "echo"
    elif commande_repli.startswith("printf"):
        commande_repli = "printf"
    elif commande_repli.startswith("exit"):
        commande_repli = "exit 0"
    return correspondance.group("prefixe") + commande_repli


def _contient_succes_force(commande: str) -> bool:
    """Détecte les neutralisations shell hors chaînes et commentaires littéraux.

    Les motifs sont bornés par la fin du NOM de commande : ``true_story`` et
    ``:mon_label`` sont des exécutables valides, jamais les commandes shell
    ``true`` et ``:``. Sans cette borne, un job requis licite était refusé.
    """
    return (
        _SUCCES_FORCE_COMPACT.search(_normaliser_commande(commande)) is not None
        or _commande_repli_succes(commande) is not None
    )


def _contient_exit_zero_non_garde(commande: str) -> bool:
    """Distingue les ``exit 0`` nus des branches conditionnelles shell prouvées.

    Les ouvertures, les fermetures et les sorties sont lues dans leur ORDRE
    d'apparition, y compris plusieurs fois sur une même ligne. Un ``exit 0``
    placé après le ``fi`` qui referme la garde s'exécute donc toujours et reste
    un contournement, alors qu'un ``exit 0`` situé entre l'ouverture et la
    fermeture demeure conditionnel. Les mots-clés ne comptent qu'en position de
    commande, afin qu'une option longue comme ``--if-exists`` ou
    ``--ignore-case`` n'ouvre aucune garde imaginaire.
    """
    profondeur_conditionnelle = 0
    for ligne in _neutraliser_chaines_shell(commande).splitlines() or [commande]:
        for jeton in _JETONS_SHELL.finditer(ligne):
            if jeton.group("ouvre") is not None:
                profondeur_conditionnelle += 1
            elif jeton.group("ferme") is not None:
                profondeur_conditionnelle = max(0, profondeur_conditionnelle - 1)
            elif profondeur_conditionnelle == 0:
                return True
    return False


@dataclass
class _CadreConditionnel:
    """Suit une conditionnelle shell ouverte afin d'isoler sa branche de repli.

    ``genre`` nomme la forme absorbante reconnue, car la branche exécutée quand
    le contrôle échoue n'est pas la même : ``if !`` rend son ``then``, un ``if``
    non nié gardant un contrôle du dépôt rend son ``else``. ``condition`` retient
    l'index où commence la condition, seule à décider ce second genre.
    """

    genre: str
    condition: int | None = None
    debut: int | None = None
    mesuree: bool = False


def _mot_designe_un_script_du_depot(mot: str) -> bool:
    """Reconnaît un script versionné ICI, jamais un exécutable fourni par le système.

    Un suffixe ``.py``/``.sh`` ou une racine ``scripts/``, ``core/scripts/``,
    ``tools/`` sont les marques du dépôt : elles nomment un contrôle que la CI
    doit exécuter, pas un outil dont on sonde la présence.
    """
    chemin = mot.strip("\"'")
    if chemin.startswith("./"):
        chemin = chemin[2:]
    return chemin.endswith(_SUFFIXES_SCRIPTS_DU_DEPOT) or chemin.startswith(
        _RACINES_SCRIPTS_DU_DEPOT
    )


def _condition_invoque_un_script_du_depot(condition: str) -> bool:
    """Prouve qu'une condition ``if`` exécute un contrôle versionné dans le dépôt.

    Chaque commande de la condition est jugée par son NOM : une sonde shell
    (``[``, ``[[``, ``test``, ``command``, ``grep``, ``git``) interroge un état,
    et citer un chemin du dépôt en ARGUMENT ne l'exécute pas. Toute autre
    commande nommant un script du dépôt est, elle, le contrôle lui-même — et
    c'est son échec que la conditionnelle exempte d'``errexit``.
    """
    for morceau in _SEPARATEUR_CONDITION_SHELL.split(condition):
        mots = morceau.split()
        if not mots or mots[0] in _SONDES_SHELL:
            continue
        if any(_mot_designe_un_script_du_depot(mot) for mot in mots):
            return True
    return False


def _ouvrir_cadre_conditionnel(
    neutre: str, jeton: re.Match[str]
) -> _CadreConditionnel:
    """Ouvre le cadre d'une conditionnelle en fixant ce qui est déjà décidable.

    La négation se lit dès le mot ``if`` ; le genre d'un ``if`` non nié dépend de
    sa condition, dont seule la fin est connue au ``then``. Un ``case`` n'exempte
    rien : il reste neutre.
    """
    if jeton.group("mot_ouvre") != "if":
        return _CadreConditionnel(_GENRE_NEUTRE)
    if _NEGATION_APRES_IF.match(neutre, jeton.end()) is not None:
        return _CadreConditionnel(_GENRE_NEGATION)
    return _CadreConditionnel(_GENRE_NEUTRE, condition=jeton.end())


def _qualifier_cadre_conditionnel(
    cadre: _CadreConditionnel, neutre: str, jeton: re.Match[str]
) -> None:
    """Décide au premier ``then`` si un ``if`` non nié garde un contrôle du dépôt.

    La condition est le texte compris entre le mot ``if`` et son ``then`` : c'est
    lui, et lui seul, dont l'échec devient exempt d'``errexit``. La mesure n'a
    lieu qu'une fois par cadre, les ``then`` d'un ``elif`` gardant leur propre
    condition, déjà atteinte après l'échec du contrôle.
    """
    if cadre.condition is None:
        return
    condition = neutre[cadre.condition : jeton.start()]
    cadre.condition = None
    if _condition_invoque_un_script_du_depot(condition):
        cadre.genre = _GENRE_CONTROLE_DIRECT


def _branches_de_repli_conditionnel(neutre: str) -> list[tuple[str, str]]:
    """Isole la branche exécutée à l'ÉCHEC de chaque conditionnelle gardant un contrôle.

    Deux formes exemptent un contrôle d'``errexit`` et leur repli diffère :
    ``if ! contrôle; then …`` exécute son ``then`` quand le contrôle échoue,
    ``if contrôle; then …`` exécute son ``else``. Une seule lecture du texte
    neutralisé les sert toutes deux, afin qu'aucune ne dérive de l'autre. Un
    contrôle direct SANS ``else`` produit une branche VIDE : c'est exactement ce
    que le shell exécute alors — rien, et le ``fi`` rend 0.
    """
    branches: list[tuple[str, str]] = []
    pile: list[_CadreConditionnel] = []
    for jeton in _JETONS_CONDITIONNELLES.finditer(neutre):
        if jeton.group("ouvre") is not None:
            pile.append(_ouvrir_cadre_conditionnel(neutre, jeton))
            continue
        if not pile:
            continue
        cadre = pile[-1]
        if cadre.debut is not None:
            branches.append((cadre.genre, neutre[cadre.debut : jeton.start()]))
            cadre.debut = None
            cadre.mesuree = True
        elif jeton.group("then") is not None:
            _qualifier_cadre_conditionnel(cadre, neutre, jeton)
            if cadre.genre == _GENRE_NEGATION and not cadre.mesuree:
                cadre.debut = jeton.end()
        elif jeton.group("sinon") is not None:
            if cadre.genre == _GENRE_CONTROLE_DIRECT and not cadre.mesuree:
                cadre.debut = jeton.end()
        if jeton.group("ferme") is not None:
            if cadre.genre == _GENRE_CONTROLE_DIRECT and not cadre.mesuree:
                branches.append((_GENRE_CONTROLE_DIRECT, ""))
            pile.pop()
    return branches


def _branches_de_negation(neutre: str) -> list[str]:
    """Isole le corps ``then`` de chaque conditionnelle ``if !`` du texte neutralisé.

    Seule la PREMIÈRE branche d'un ``if !`` est retenue : c'est elle, et elle
    seule, qui s'exécute quand la commande gardée échoue. Une branche ``elif`` ou
    ``else`` du même bloc s'exécute au contraire quand la commande a réussi, et
    n'absorbe donc aucun échec.
    """
    return [
        branche
        for genre, branche in _branches_de_repli_conditionnel(neutre)
        if genre == _GENRE_NEGATION
    ]


def _branches_de_controle_direct(neutre: str) -> list[str]:
    """Isole la branche ``else`` de chaque ``if`` non nié gardant un contrôle du dépôt.

    Symétrique exact de la lecture des ``if !`` : ici, la branche prise quand le
    contrôle échoue est le ``else`` (ou le ``elif``), et son absence vaut branche
    vide.
    """
    return [
        branche
        for genre, branche in _branches_de_repli_conditionnel(neutre)
        if genre == _GENRE_CONTROLE_DIRECT
    ]


def _condition_negation_absorbe(commande: str) -> bool:
    """Prouve qu'une garde ``if !`` avale l'échec de la commande qu'elle teste.

    ``if ! contrôle; then …; fi`` exempte le contrôle d'``errexit`` : le statut de
    l'étape devient celui de la branche ``then``. Le critère est donc le même que
    pour les groupes de repli ``|| { … }`` — la branche propage-t-elle l'échec par
    une sortie non nulle prouvée, ou le laisse-t-elle réussir ?
    """
    return any(
        not _groupe_propage_echec(branche)
        for branche in _branches_de_negation(_neutraliser_chaines_shell(commande))
    )


def _condition_controle_direct_absorbe(commande: str) -> bool:
    """Prouve qu'un ``if`` SANS négation avale l'échec du contrôle qu'il teste.

    Retirer le ``!`` ne rend pas la forme sûre : quand le contrôle échoue, la
    branche ``then`` n'est pas prise, et c'est le ``else`` qui fixe alors le
    statut de l'étape. Absent, rien ne s'exécute et le ``fi`` rend 0 — le job
    requis est vert avec un contrôle rouge. Le critère reste celui des groupes de
    repli : cette branche propage-t-elle l'échec ?
    """
    return any(
        not _groupe_propage_echec(branche)
        for branche in _branches_de_controle_direct(
            _neutraliser_chaines_shell(commande)
        )
    )


def _desarme_errexit(commande: str) -> bool:
    """Détecte un ``set +e`` qui désarme errexit pour tout le reste de l'étape.

    Les autres options restent libres : seule celle qui cesse d'interrompre
    l'étape au premier échec transforme un contrôle rouge en job vert.
    """
    return any(
        _OPTION_DESARMANT_ERREXIT.search(correspondance.group("arguments")) is not None
        for correspondance in _COMMANDE_SET_SHELL.finditer(
            _neutraliser_chaines_shell(commande)
        )
    )


def _violation_echec_absorbe(
    repo: Path,
    fichier: Path,
    job: str,
    detail: str,
) -> Violation:
    """Construit la violation commune aux formes shell qui avalent un échec requis."""
    return _violation(
        "REQUIRED_JOB_FORCED_SUCCESS",
        repo,
        fichier,
        1,
        f"le job requis {job} {detail}",
    )


def _violation_succes_force(
    repo: Path,
    fichier: Path,
    ligne: int,
    job: str,
    commande_repli: str | None = None,
) -> Violation:
    """Construit la violation commune aux commandes de job et action composite."""
    detail = f"le job requis {job} force un succès shell"
    if commande_repli is not None:
        detail += f" avec la commande de repli {commande_repli}"
    return _violation(
        "REQUIRED_JOB_FORCED_SUCCESS",
        repo,
        fichier,
        ligne,
        detail,
    )


def _analyser_commande(
    repo: Path,
    fichier: Path,
    commande: object,
    job: str,
) -> list[Violation]:
    """Refuse les commandes qui absorbent l'échec d'un contrôle requis."""
    if not isinstance(commande, str):
        return []
    commande_repli = _commande_repli_succes(commande)
    if commande_repli is not None:
        return [_violation_succes_force(repo, fichier, 1, job, commande_repli)]
    if _contient_succes_force(commande) or _contient_exit_zero_non_garde(commande):
        return [_violation_succes_force(repo, fichier, 1, job)]
    if _condition_negation_absorbe(commande):
        return [
            _violation_echec_absorbe(
                repo,
                fichier,
                job,
                "garde un contrôle par une condition de négation dont la branche "
                "absorbe l'échec au lieu de le propager",
            )
        ]
    if _condition_controle_direct_absorbe(commande):
        return [
            _violation_echec_absorbe(
                repo,
                fichier,
                job,
                "place un contrôle du dépôt en condition d'un if sans négation, "
                "dont aucune branche ne propage l'échec",
            )
        ]
    if _desarme_errexit(commande):
        return [
            _violation_echec_absorbe(
                repo,
                fichier,
                job,
                "désarme errexit, ce qui rend vert tout échec survenant ensuite "
                "dans l'étape",
            )
        ]
    return []


def _analyser_continue_on_error(
    repo: Path,
    fichier: Path,
    valeur: object,
    job: str,
) -> list[Violation]:
    """Refuse une tolérance d'erreur vraie sous ses formes booléenne, numérique et quotée.

    MESURÉ avec PyYAML 6.0.1 : ``yes``, ``on`` et ``true`` sont rendus comme le
    booléen ``True``, ``y`` et ``Y`` comme des chaînes, mais ``1`` est rendu comme
    l'ENTIER 1 — que ni ``valeur is True`` ni le test de chaîne n'attrapaient. La
    tolérance passait alors inaperçue et le job requis restait vert avec son
    contrôle rouge.

    La forme numérique est donc jugée sur sa VALEUR, non sur son type : tout
    nombre non nul tolère les erreurs (``1``, ``2``, ``-1``, ``0x1`` que PyYAML
    rend 1, ``1.0``), tandis que ``0`` et ``0.0`` ne tolèrent rien et ne sont
    jamais signalés. ``False`` échoue à cette comparaison et poursuit sans
    violation, comme il le doit. Les formes non numériques dont la vérité n'est
    pas décidable ici — ``.nan``, ``.inf`` — restent refusées en fail-closed :
    aucune ne désigne un contrôle obligatoire.
    """
    if valeur is True:
        detail = f"le job requis {job} accepte les erreurs"
    elif isinstance(valeur, (int, float)) and valeur != 0:
        detail = (
            f"le job requis {job} accepte les erreurs "
            f"par la valeur numérique {valeur!r}"
        )
    elif isinstance(valeur, str) and "${{" in valeur:
        detail = (
            f"le job requis {job} utilise une valeur dynamique "
            "pour continue-on-error, refusée par principe"
        )
    elif (
        isinstance(valeur, str)
        and valeur.strip().lower() in _VALEURS_VRAIES_YAML
    ):
        detail = f"le job requis {job} accepte les erreurs"
    else:
        return []
    return [
        _violation(
            "REQUIRED_JOB_SOFT_FAILURE",
            repo,
            fichier,
            1,
            detail,
        )
    ]


def _condition_requise_acceptee(valeur: object) -> bool:
    """Accepte uniquement always() et success(), garanties sans dépendance métier."""
    if not isinstance(valeur, str):
        return False
    condition = valeur.strip()
    if condition.startswith("${{") and condition.endswith("}}"):
        condition = condition[3:-2].strip()
    return condition.lower() in _CONDITIONS_REQUISES_ACCEPTEES


def _analyser_condition_requise(
    repo: Path,
    fichier: Path,
    valeur: object,
    job: str,
) -> list[Violation]:
    """Refuse les conditions qui peuvent neutraliser un job requis ou une étape requise."""
    if valeur is None or _condition_requise_acceptee(valeur):
        return []
    return [
        _violation(
            "REQUIRED_JOB_CONDITIONNEL",
            repo,
            fichier,
            1,
            f"le job requis {job} dépend d'une condition non garantie : {valeur!r}",
        )
    ]


def _fichier_action_locale(repo: Path, reference: str) -> Path | None:
    """Résout une référence locale vers son descripteur action.yml ou action.yaml.

    L'appelant garantit une référence locale : ``None`` signifie donc « aucun
    descripteur n'existe à cet emplacement », jamais « référence externe ».
    """
    repertoire = repo / reference.removeprefix("./")
    for nom in ("action.yml", "action.yaml"):
        fichier = repertoire / nom
        if fichier.is_file():
            return fichier
    return None


def _analyser_action_locale(
    repo: Path,
    source: Path,
    reference: str,
    job: str,
    visites: frozenset[Path] = frozenset(),
    profondeur: int = 0,
) -> list[Violation]:
    """Analyse récursivement une action composite locale appelée par un job requis.

    Une action EXTERNE ne vit pas dans le dépôt : son absence locale est normale
    et n'est jamais signalée. Une action LOCALE référencée mais absente est au
    contraire un contrôle qui n'existe pas, tout en rendant le job requis vert.
    """
    if not reference.startswith("./"):
        return []

    fichier = _fichier_action_locale(repo, reference)
    if fichier is None:
        return [
            _violation(
                "LOCAL_ACTION_INTROUVABLE",
                repo,
                source,
                1,
                f"le job requis {job} référence l'action locale {reference}, "
                "dont aucun descripteur action.yml ou action.yaml n'existe",
            )
        ]

    chemin = fichier.resolve()
    if chemin in visites:
        return [
            _violation(
                "LOCAL_ACTION_CYCLE",
                repo,
                fichier,
                1,
                f"le job requis {job} référence un cycle d'actions composites locales",
            )
        ]
    if profondeur >= _MAX_ACTION_DEPTH:
        return [
            _violation(
                "LOCAL_ACTION_DEPTH_EXCEEDED",
                repo,
                fichier,
                1,
                f"le job requis {job} dépasse la profondeur maximale d'actions locales",
            )
        ]

    document, violations = _charger_yaml(repo, fichier)
    if document is None:
        return violations

    runs = document.get("runs")
    if not isinstance(runs, Mapping) or runs.get("using") != "composite":
        return violations

    etapes = runs.get("steps")
    etapes_declarees = etapes if isinstance(etapes, list) else []
    if not any(_etape_execute_quelque_chose(etape) for etape in etapes_declarees):
        violations.append(
            _violation_job_requis_sans_etape(
                repo,
                fichier,
                job,
                f"l'action composite locale {reference} ne porte aucune étape "
                "avec run ou uses",
            )
        )
        return violations

    prochaines_visites = visites | {chemin}
    for etape in etapes_declarees:
        if not isinstance(etape, Mapping):
            continue
        violations.extend(_analyser_condition_requise(repo, fichier, etape.get("if"), job))
        violations.extend(
            _analyser_continue_on_error(
                repo,
                fichier,
                etape.get("continue-on-error"),
                job,
            )
        )
        violations.extend(_analyser_commande(repo, fichier, etape.get("run"), job))
        reference_suivante = etape.get("uses")
        if isinstance(reference_suivante, str):
            violations.extend(
                _analyser_action_locale(
                    repo,
                    fichier,
                    reference_suivante,
                    job,
                    prochaines_visites,
                    profondeur + 1,
                )
            )
    return violations


def _violation_structure_job_requis(
    repo: Path,
    fichier: Path,
    job: str,
    detail: str,
) -> Violation:
    """Refuse en fail-closed toute structure de job requis qui empêche sa preuve.

    Un job requis illisible n'apporte aucune garantie : il est donc signalé, et
    jamais sauté en silence comme un job facultatif.
    """
    return _violation(
        "REQUIRED_JOB_STRUCTURE_INVALIDE",
        repo,
        fichier,
        1,
        f"le job requis {job} est inanalysable : {detail}",
    )


def _etape_execute_quelque_chose(etape: object) -> bool:
    """Reconnaît une étape qui exécute réellement une commande ou une action.

    Seuls ``run`` et ``uses`` déclenchent un travail : une étape réduite à un
    ``name`` décoratif n'exécute aucun contrôle.
    """
    return isinstance(etape, Mapping) and ("run" in etape or "uses" in etape)


def _violation_job_requis_sans_etape(
    repo: Path,
    fichier: Path,
    job: str,
    detail: str,
) -> Violation:
    """Refuse un job requis syntaxiquement valide qui n'exécute pourtant rien.

    Un job requis vide satisfait la protection de branche sans lancer le moindre
    contrôle : c'est un gate désarmé, plus dangereux qu'un gate absent puisque
    la CI le rapporte vert.
    """
    return _violation(
        "REQUIRED_JOB_SANS_ETAPE",
        repo,
        fichier,
        1,
        f"le job requis {job} n'exécute aucune étape : {detail}",
    )


def _analyser_workflow(
    repo: Path,
    fichier: Path,
    jobs_requis: tuple[str, ...],
) -> list[Violation]:
    """Analyse un workflow et refuse les structures empêchant la preuve des jobs."""
    document, violations = _charger_yaml(repo, fichier)
    if document is None:
        return violations

    if "jobs" not in document:
        return violations

    jobs = document["jobs"]
    if not isinstance(jobs, Mapping):
        violations.append(
            _violation(
                "FICHIER_NON_ANALYSABLE",
                repo,
                fichier,
                1,
                "la clé workflow jobs doit être un mapping, "
                f"mais {_type_yaml(jobs)} a été trouvé",
            )
        )
        return violations

    for identifiant, definition in jobs.items():
        if not isinstance(identifiant, str) or identifiant not in jobs_requis:
            continue
        if not isinstance(definition, Mapping):
            violations.append(
                _violation_structure_job_requis(
                    repo,
                    fichier,
                    identifiant,
                    "sa définition doit être un mapping, "
                    f"mais {_type_yaml(definition)} a été trouvé",
                )
            )
            continue

        violations.extend(_analyser_condition_requise(repo, fichier, definition.get("if"), identifiant))
        violations.extend(
            _analyser_continue_on_error(
                repo,
                fichier,
                definition.get("continue-on-error"),
                identifiant,
            )
        )

        etapes = definition.get("steps")
        if "steps" in definition and not isinstance(etapes, list):
            violations.append(
                _violation_structure_job_requis(
                    repo,
                    fichier,
                    identifiant,
                    "son champ steps doit être une liste, "
                    f"mais {_type_yaml(etapes)} a été trouvé",
                )
            )
            continue
        if not isinstance(etapes, list):
            if "uses" not in definition:
                violations.append(
                    _violation_job_requis_sans_etape(
                        repo,
                        fichier,
                        identifiant,
                        "il ne déclare ni steps ni appel de workflow réutilisable",
                    )
                )
            continue
        if not any(_etape_execute_quelque_chose(etape) for etape in etapes):
            violations.append(
                _violation_job_requis_sans_etape(
                    repo,
                    fichier,
                    identifiant,
                    "aucune de ses étapes ne porte run ou uses",
                )
            )
        for etape in etapes:
            if not isinstance(etape, Mapping):
                continue
            violations.extend(
                _analyser_condition_requise(repo, fichier, etape.get("if"), identifiant)
            )
            violations.extend(
                _analyser_continue_on_error(
                    repo,
                    fichier,
                    etape.get("continue-on-error"),
                    identifiant,
                )
            )
            violations.extend(
                _analyser_commande(repo, fichier, etape.get("run"), identifiant)
            )
            reference = etape.get("uses")
            if isinstance(reference, str):
                violations.extend(
                    _analyser_action_locale(repo, fichier, reference, identifiant)
                )

    return violations


def _analyser_workflows(repo: Path, jobs_requis: tuple[str, ...]) -> list[Violation]:
    """Analyse tous les workflows YAML présents dans le dépôt."""
    repertoire = repo / ".github" / "workflows"
    if not repertoire.is_dir():
        return []
    violations: list[Violation] = []
    for fichier in sorted((*repertoire.glob("*.yml"), *repertoire.glob("*.yaml"))):
        violations.extend(_analyser_workflow(repo, fichier, jobs_requis))
    return violations


def scan_repository(repo: Path, scopes: tuple[str, ...], *, base_ref: str) -> list[Violation]:
    """Scanne les scopes Python et les protections des workflows du dépôt."""
    _, jobs_requis = _charger_contrat(repo)
    racines_contractuelles = _charger_racines_contractuelles(repo)
    violations: list[Violation] = []
    for fichier in _fichiers_python(repo, scopes):
        violations.extend(
            _analyser_fichier_python(repo, fichier, base_ref, racines_contractuelles)
        )
    violations.extend(_analyser_workflows(repo, jobs_requis))
    return sorted(violations, key=lambda item: (item.path, item.line, item.code))


def _violations_scopes_incomplets(
    repo: Path,
    scopes: tuple[str, ...],
    racines_contractuelles: tuple[str, ...],
) -> list[Violation]:
    """Prouve que chaque racine du contrat est demandée explicitement au CLI."""
    demandes = set(scopes)
    manquantes = tuple(
        racine for racine in racines_contractuelles if racine not in demandes
    )
    if not manquantes:
        return []
    return [
        Violation(
            "SCOPE_ROOT_OMITTED",
            "core/quality-scopes.toml",
            1,
            "les --scope omettent les racines contractuelles : "
            + ", ".join(manquantes),
        )
    ]


def _identifiants_de_jobs_declares(repo: Path) -> set[str]:
    """Collecte les identifiants de jobs de TOUS les workflows, sans se limiter à un fichier."""
    repertoire = repo / ".github" / "workflows"
    identifiants: set[str] = set()
    for fichier in sorted((*repertoire.glob("*.yml"), *repertoire.glob("*.yaml"))):
        document, _ = _charger_yaml(repo, fichier)
        if document is None:
            continue
        jobs = document.get("jobs")
        if not isinstance(jobs, Mapping):
            continue
        identifiants.update(
            identifiant for identifiant in jobs if isinstance(identifiant, str)
        )
    return identifiants


def _violations_jobs_requis_absents(
    repo: Path,
    jobs_requis: tuple[str, ...],
) -> list[Violation]:
    """Prouve que chaque identifiant requis du contrat existe dans un workflow réel.

    La couverture est mesurée globalement : un identifiant peut légitimement être
    défini dans un autre fichier que celui des autres. Un identifiant qu'aucun
    workflow ne définit est un contrôle requis absent, donc un gate manquant.

    La seule borne est le CONTRAT, jamais la présence d'une CI. Se taire quand
    ``.github/workflows/`` n'existe pas produisait l'inverse exact de l'intention :
    un dépôt qui DÉCLARE des jobs requis et n'en exécute aucun est le défaut
    maximal, pas un dépôt dispensé de preuve. Les trois formes de cette absence —
    répertoire inexistant, répertoire vide, répertoire sans fichier ``.yml`` ni
    ``.yaml`` — sont désormais jugées à l'identique, puisqu'elles livrent
    exactement la même CI : aucune. Sans identifiant requis déclaré, en revanche,
    aucun contrôle n'est promis et rien ne peut être reproché — ce cas est porté
    par le calcul de ``manquants``, vide par construction quand ``jobs_requis``
    l'est, donc par le seul ``return`` qui le suit. Une garde explicite en tête
    serait indétectable à la mutation, donc non prouvable : elle a été retirée
    plutôt que laissée en décor.
    """
    declares = _identifiants_de_jobs_declares(repo)
    manquants = tuple(job for job in jobs_requis if job not in declares)
    if not manquants:
        return []
    return [
        Violation(
            "REQUIRED_JOB_ABSENT",
            ".github/workflows",
            1,
            "aucun workflow ne définit les jobs requis du contrat : "
            + ", ".join(manquants),
        )
    ]


def main(argv: list[str] | None = None) -> int:
    """Exécute le gate avec les racines contractuelles par défaut sûr."""
    parser = argparse.ArgumentParser(description="Détecte les stubs et dettes qualité.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--scope", action="append", dest="scopes")
    arguments = parser.parse_args(argv)

    repo = arguments.repo.resolve()
    racines, jobs_requis, erreur_contrat = _lire_contrat(repo)
    if erreur_contrat is not None:
        print(
            "CONTRAT_PERIMETRE_ABSENT core/quality-scopes.toml:1 "
            + erreur_contrat,
            file=sys.stdout,
        )
        return 1

    scopes = tuple(arguments.scopes) if arguments.scopes else racines
    violations = _violations_scopes_incomplets(repo, scopes, racines)
    if not violations:
        violations = scan_repository(repo, scopes, base_ref=arguments.base_ref)
        violations.extend(_violations_jobs_requis_absents(repo, jobs_requis))
    for violation in violations:
        print(
            f"{violation.code} {violation.path}:{violation.line} {violation.detail}",
            file=sys.stdout,
        )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
