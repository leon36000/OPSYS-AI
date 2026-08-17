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
from collections.abc import Callable, Mapping, Set as AbstractSet
from dataclasses import dataclass, field, fields
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
_ORACLES_PYTEST: Final[frozenset[str]] = frozenset({"raises", "fail"})
_APPELS_DE_SAUT: Final[Mapping[str, frozenset[str]]] = {
    "pytest": frozenset({"skip", "xfail", "importorskip"}),
    "unittest": frozenset({"skip", "skipIf", "skipUnless"}),
}
_BASE_REF_GIT_AUTORISEE: Final[re.Pattern[str]] = re.compile(r"(?!-)[^\x00-\x20\x7f]+")
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
_SORTIE_LITTERALE_SHELL: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[;|&()\s])exit\s+(?P<code>[0-9]+)(?=$|[^A-Za-z0-9_])"
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
_COMMANDES_SUCCES_GARANTI: Final[str] = (
    f"true{_SUITE_NOM_COMMANDE}"
    f"|:{_SUITE_NOM_COMMANDE}"
    f"|echo{_SUITE_NOM_COMMANDE}"
    f"|printf{_SUITE_NOM_COMMANDE}"
    r"|exit\s+0(?=$|[^A-Za-z0-9_])"
)
_FALLBACK_SHELL: Final[re.Pattern[str]] = re.compile(
    r"\|\|\s*(?P<prefixe>"
    + _PREFIXES_NEUTRES_REPLI
    + r")(?P<command>"
    + _COMMANDES_SUCCES_GARANTI
    + r")"
)
_SUCCES_GARANTI_EN_TETE: Final[re.Pattern[str]] = re.compile(
    r"^(?:" + _PREFIXES_NEUTRES_REPLI + r")(?:" + _COMMANDES_SUCCES_GARANTI + r")"
)
_INTERPRETES_SHELL: Final[str] = r"(?:ba|da|k|z|a)?sh"
_REPLI_SHELL_INLINE: Final[re.Pattern[str]] = re.compile(
    r"\|\|\s*(?P<prefixe>"
    + _PREFIXES_NEUTRES_REPLI
    + r")(?P<shell>"
    + _INTERPRETES_SHELL
    + r")"
    + _SUITE_NOM_COMMANDE
    + r"(?:\s+-[A-Za-z]+)*?\s+-[A-Za-z]*c\s+"
    + r"(?P<script>'[^']*'|\"[^\"]*\"|[^\s;|&]+)"
)
_SUCCES_FORCE_COMPACT: Final[re.Pattern[str]] = re.compile(
    r"(?:\|\|true|\|\|:|\|\|exit0|;true)" + _SUITE_NOM_COMMANDE
)
_GROUPE_APRES_OU: Final[re.Pattern[str]] = re.compile(r"\|\|\s*(?P<ouverture>[{(])")
_MOT_IF_SHELL: Final[str] = "if"
_MOT_SINON_SHELL: Final[str] = "else"
_SEPARATEUR_MOTIF_CASE: Final[str] = ";;"
_SEPARATEUR_COMMANDE_SHELL: Final[re.Pattern[str]] = re.compile(r";|\n|&&")
_SORTIE_NON_NULLE: Final[re.Pattern[str]] = re.compile(
    r"^(?:exit|return)\s+(?P<code>[0-9]+)\s*$"
)
_COMMANDES_ECHOUANT_TOUJOURS: Final[frozenset[str]] = frozenset({"false"})
_ECHEC_GARANTI_EN_TETE: Final[re.Pattern[str]] = re.compile(
    r"(?:"
    + _PREFIXES_NEUTRES_REPLI
    + r")(?:"
    + "|".join(
        f"{nom}{_SUITE_NOM_COMMANDE}"
        for nom in sorted(_COMMANDES_ECHOUANT_TOUJOURS)
    )
    + r")\s*$"
)
_JETONS_SHELL: Final[re.Pattern[str]] = re.compile(
    f"(?P<ouvre>{_IF_SHELL.pattern}|{_CASE_SHELL.pattern})"
    f"|(?P<ferme>{_FIN_IF_SHELL.pattern}|{_FIN_CASE_SHELL.pattern})"
    f"|(?P<sortie>{_SORTIE_LITTERALE_SHELL.pattern})"
)
_POSITION_COMMANDE_SHELL: Final[str] = r"(?:^|[;|&()\s])"
_FIN_DE_MOT_SHELL: Final[str] = r"(?=$|[;|&()\s])"
_JETONS_CONDITIONNELLES: Final[re.Pattern[str]] = re.compile(
    f"(?P<ouvre>{_POSITION_COMMANDE_SHELL}(?P<mot_ouvre>if|case){_FIN_DE_MOT_SHELL})"
    f"|(?P<then>{_POSITION_COMMANDE_SHELL}then{_FIN_DE_MOT_SHELL})"
    f"|(?P<sinon>{_POSITION_COMMANDE_SHELL}(?:else|elif){_FIN_DE_MOT_SHELL})"
    f"|(?P<ferme>{_POSITION_COMMANDE_SHELL}(?:fi|esac){_FIN_DE_MOT_SHELL})"
)
_CONDITIONNELLE_APRES_OU: Final[re.Pattern[str]] = re.compile(
    r"\|\|\s*(?P<mot>if|case)" + _FIN_DE_MOT_SHELL
)
_OPERATEUR_OU_SHELL: Final[re.Pattern[str]] = re.compile(r"\|\|")
_OPERATEUR_OU_TEXTE: Final[str] = "||"
_MOT_FERMANT_SHELL: Final[re.Pattern[str]] = re.compile(r"fi|esac")
_MOT_COMPOSE_SHELL: Final[re.Pattern[str]] = re.compile(
    r"(?P<compose>if|case)" + _FIN_DE_MOT_SHELL
)
_FIN_DE_BRANCHE_SIMPLE: Final[re.Pattern[str]] = re.compile(r";|\n|&&|\|\|")
_SHELL_INLINE_EN_TETE: Final[re.Pattern[str]] = re.compile(
    r"(?:"
    + _PREFIXES_NEUTRES_REPLI
    + r")(?:"
    + _INTERPRETES_SHELL
    + r")"
    + _SUITE_NOM_COMMANDE
    + r"(?:\s+-[A-Za-z]+)*?\s+-[A-Za-z]*c\s+"
    + r"(?P<script>'[^']*'|\"[^\"]*\"|[^\s;|&]+)"
)
_OUVERTURES_DE_GROUPE_SHELL: Final[str] = "{("
_FERMETURES_DE_GROUPE_SHELL: Final[str] = "})"
_SEPARATEURS_SIMPLES_SHELL: Final[str] = ";\n"
_ENCHAINEMENT_ET_SHELL: Final[str] = "&&"
_MODULO_CODE_DE_SORTIE: Final[int] = 256
_PROFONDEUR_REPLI_MAX: Final[int] = 8
_DESIGNATION_REPLI_VIDE: Final[str] = "branche vide"
_DESIGNATION_REPLI_ACCOLADES: Final[str] = "{ … }"
_DESIGNATION_REPLI_PARENTHESES: Final[str] = "( … )"
_DESIGNATION_REPLI_SI: Final[str] = "if … fi"
_DESIGNATION_REPLI_FILTRAGE: Final[str] = "case … esac"
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
_VALEURS_FAUSSES_YAML: Final[frozenset[str]] = frozenset(
    {"false", "no", "off", "n"}
)
_CONDITIONS_REQUISES_ACCEPTEES: Final[frozenset[str]] = frozenset(
    {"always()", "success()"}
)
_CONDITIONS_REQUISES_MALGRE_NEEDS: Final[frozenset[str]] = frozenset({"always()"})
_NOMS_EXCEPTIONS_BUILTINS: Final[frozenset[str]] = frozenset(
    nom
    for nom, objet in vars(builtins).items()
    if isinstance(objet, type) and issubclass(objet, BaseException)
)
_NOMS_TEST_CASE_UNITTEST: Final[frozenset[str]] = frozenset(
    {"TestCase", "IsolatedAsyncioTestCase", "FunctionTestCase"}
)
_NOMS_ABSENCE_IMPLEMENTATION: Final[frozenset[str]] = frozenset(
    {
        "NotImplementedError",  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
        "NotImplemented",
    }
)  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
_CHAMPS_ETAPE_EFFECTIVE: Final[tuple[str, ...]] = ("run", "uses")
_ATTRIBUT_PROUVANT_PROTOCOL: Final[str] = "Protocol"
_ATTRIBUT_PROUVANT_ABSTRACTMETHOD: Final[str] = "abstractmethod"
_MODULES_TYPING: Final[frozenset[str]] = frozenset({"typing", "typing_extensions"})
_MODULES_ABC: Final[frozenset[str]] = frozenset({"abc"})
_PORTEES_PROPRES: Final[tuple[type[ast.AST], ...]] = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
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
    oracles_raises: frozenset[str]
    oracles_fail: frozenset[str]
    test_cases: frozenset[str]
    modules_builtins: frozenset[str]
    exceptions_builtins: frozenset[str]


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
    oracles_raises: set[str] = field(default_factory=set)
    oracles_fail: set[str] = field(default_factory=set)
    test_cases: set[str] = field(default_factory=set)
    modules_builtins: set[str] = field(default_factory=set)
    exceptions_builtins: set[str] = field(
        default_factory=lambda: set(_NOMS_EXCEPTIONS_BUILTINS)
    )

    @classmethod
    def depuis(cls, preuve: _AliasesImports) -> "_CollecteAliases":
        """Reprend une preuve FIGÉE pour la compléter sans jamais la modifier.

        Les champs sont recopiés par leur nom déclaré, jamais énumérés à la
        main : la preuve d'origine et la collecte portent les mêmes champs, si
        bien qu'aucun ajout futur ne peut être oublié ici — l'oubli rendrait un
        alias déjà prouvé invisible à la portée locale qui le reprend.
        """
        return cls(
            **{
                champ.name: set(getattr(preuve, champ.name))
                for champ in fields(_AliasesImports)
            }
        )

    def ajouter(self, apport: "_CollecteAliases") -> None:
        """Ajoute ce qu'une portée plus proche prouve, sans jamais rien retirer.

        L'ajout est unilatéral, et c'est délibéré : un import écrit dans une
        fonction PROUVE une origine dans sa portée, alors qu'une réaffectation
        locale ne détruit aucune preuve pour les règles de DÉTECTION — un nom
        réécrit après son import reste jugé fail-closed. Les règles d'EXEMPTION,
        elles, consultent déjà le masquage lexical, qui refuse l'exemption dès
        qu'une liaison locale rend le nom incertain.
        """
        for ensemble, ajout in zip(self._ensembles(), apport._ensembles()):
            ensemble |= ajout

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
            self.oracles_raises,
            self.oracles_fail,
            self.test_cases,
            self.modules_builtins,
            self.exceptions_builtins,
        )

    def retirer(self, noms: set[str]) -> None:
        """Retire les noms réaffectés : leur origine standard n'est plus prouvée."""
        for ensemble in self._ensembles():
            ensemble.difference_update(noms)

    def retirer_preuves_importees(self, noms: set[str]) -> None:
        """Retire ce qu'un import ANTÉRIEUR prouvait d'un nom qu'un autre import relie.

        Un import est une LIAISON : ``from typing import Protocol`` puis ``from
        transport import Protocol`` fait désigner au nom ce que ``transport``
        exporte, exactement comme une affectation. Les imports ne comptaient
        pourtant pas parmi les réaffectations, si bien que le second n'écrasait
        jamais la preuve établie par le premier. MESURÉ, la même cause produisait
        les deux effets opposés : une ellipse EXEMPTÉE sous un protocole qui n'en
        était plus un, et une levée REFUSÉE sur un porteur qui n'était plus
        ``builtins``.

        Le retrait précède l'ajout dans ``_lier_import``, si bien que la liaison
        la plus proche décide : un retour vers l'origine standard rétablit la
        preuve, et deux origines prouvantes — ``typing`` et ``typing_extensions``
        — se remplacent sans rien retirer.

        ``exceptions_builtins`` est le seul ensemble épargné, et l'exception est
        structurelle : il n'est pas prouvé par un import mais SEMÉ avec les noms
        de l'interpréteur, que seul ``retirer_exceptions_importees`` ampute. L'y
        inclure ferait perdre à ``from builtins import ValueError`` la preuve que
        cet import vient précisément d'apporter. Tous les autres ensembles sont
        énumérés par ``_ensembles`` plutôt que recopiés : un champ ajouté demain
        est révoqué sans qu'aucune liste n'ait à être tenue à jour.
        """
        for ensemble in self._ensembles():
            if ensemble is self.exceptions_builtins:
                continue
            ensemble.difference_update(noms)

    def _ensembles_exemptants(self) -> tuple[set[str], ...]:
        """Énumère les seules preuves dont le retrait rend le gate PLUS strict.

        Ces ensembles servent à EXEMPTER : sans eux, l'ellipse d'un protocole ou
        d'une méthode abstraite, l'oracle hérité d'un cas de test, l'oracle
        pytest importé directement et le corps vide d'un type d'exception
        redeviennent des violations. Les autres ensembles servent au contraire à
        DÉTECTER (marques de saut, absences d'implémentation) : les retirer
        rendrait le gate muet, donc fail-open. Cette liste est volontairement
        partielle, et c'est la raison pour laquelle elle est séparée de
        ``_ensembles``.
        """
        return (
            self.protocols,
            self.modules_typing,
            self.abstractmethods,
            self.modules_abc,
            self.oracles_raises,
            self.oracles_fail,
            self.test_cases,
            self.modules_builtins,
            self.exceptions_builtins,
        )

    def retirer_exemptions(self, noms: set[str]) -> None:
        """Retire les seules preuves d'exemption portées par les noms donnés."""
        for ensemble in self._ensembles_exemptants():
            ensemble.difference_update(noms)

    def retirer_attributs_prouvants(self, attributs: set[tuple[str, str]]) -> None:
        """Retire un alias de module dont l'attribut PROUVANT une exemption est réécrit.

        ``t.Protocol = object`` laisse le module ``t`` en place mais détruit
        l'origine de l'exemption : la classe qui hérite ensuite de ``t.Protocol``
        ne dérive plus du protocole de la bibliothèque standard. Le retrait vise
        l'attribut réécrit, pas le module entier, afin qu'une écriture sur un
        attribut sans rapport ne fasse pas disparaître une preuve valide.
        """
        for module, attribut in attributs:
            if attribut == _ATTRIBUT_PROUVANT_PROTOCOL:
                self.modules_typing.discard(module)
            elif attribut == _ATTRIBUT_PROUVANT_ABSTRACTMETHOD:
                self.modules_abc.discard(module)

    def ajouter_absences_prouvees(self, noms: set[str]) -> None:
        """Ajoute les noms qu'une affectation lie à l'absence d'implémentation."""
        self.not_implemented_errors.update(noms)

    def retirer_exceptions_importees(self, noms: set[str]) -> None:
        """Retire les noms d'exception qu'un import lie à autre chose que ``builtins``.

        ``from transport import ValueError`` fait désigner au nom ce que
        ``transport`` exporte : l'exception de l'interpréteur n'est plus prouvée.
        Le retrait est réservé à cet ensemble parce qu'un import est justement ce
        qui PROUVE les autres alias — les y appliquer effacerait la preuve qu'ils
        viennent d'établir.
        """
        self.exceptions_builtins.difference_update(noms)

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
            frozenset(self.oracles_raises),
            frozenset(self.oracles_fail),
            frozenset(self.test_cases),
            frozenset(self.modules_builtins),
            frozenset(self.exceptions_builtins),
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


def _noms_cibles_directes(noeud: ast.stmt) -> set[str]:
    """Extrait les noms qu'une INSTRUCTION lie par sa cible déclarée.

    Trois formes s'ajoutaient à celles que la collecte lisait déjà, et MESURÉ,
    toutes trois laissaient survivre une exemption dont l'origine avait pourtant
    été écrasée : l'affectation augmentée, le nom du gestionnaire d'exception
    (``except … as Protocol``) et la SUPPRESSION du nom. Les trois lient — ou
    délient — le nom, ce qui suffit à retirer sa preuve d'origine standard.
    """
    if isinstance(noeud, ast.Assign):
        return set().union(*(_noms_lies_cible(cible) for cible in noeud.targets))
    if isinstance(noeud, ast.AnnAssign):
        return _noms_lies_cible(noeud.target)
    if isinstance(noeud, ast.AugAssign):
        return _noms_lies_cible(noeud.target)
    if isinstance(noeud, ast.Delete):
        return set().union(*(_noms_lies_cible(cible) for cible in noeud.targets))
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
    if isinstance(noeud, (ast.Try, ast.TryStar)):
        return {
            gestionnaire.name
            for gestionnaire in noeud.handlers
            if gestionnaire.name is not None
        }
    if isinstance(noeud, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return {noeud.name}
    return set()


def _enfants_hors_corps(noeud: ast.AST) -> list[ast.AST]:
    """Énumère les enfants d'un nœud en sautant le corps des portées PROPRES.

    Le corps d'une fonction, d'un lambda ou d'une classe ouvre un espace de noms
    distinct : ce qu'on y lie n'appartient pas à la portée parcourue. Le champ
    ``body`` n'est écarté que pour ces trois formes, jamais sur son seul nom : il
    désigne ailleurs une simple expression — celui d'``a if c else b`` en est
    une — et l'écarter partout perdrait une liaison bien réelle.
    """
    ignorer_corps = isinstance(
        noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    )
    enfants: list[ast.AST] = []
    for champ, valeur in ast.iter_fields(noeud):
        if ignorer_corps and champ == "body":
            continue
        elements = valeur if isinstance(valeur, list) else [valeur]
        enfants.extend(element for element in elements if isinstance(element, ast.AST))
    return enfants


def _noms_lies_par_expression_daffectation(noeud: ast.stmt) -> set[str]:
    """Extrait les noms qu'une EXPRESSION d'affectation lie dans la portée courante.

    ``(Protocol := object)`` est une expression, jamais une instruction : la
    collecte des cibles, qui ne lisait que des instructions, la manquait
    entièrement. MESURÉ, l'écrasement passait alors inaperçu et la classe qui
    héritait ensuite du nom restait exemptée alors qu'elle dérivait d'``object``.

    Les compréhensions sont parcourues à dessein : MESURÉ à l'interpréteur,
    ``[(P := 1) for _ in range(1)]`` laisse ``P`` défini dans la portée
    ENGLOBANTE, à la différence de la cible de boucle ``[P for P in …]``, qui
    reste confinée et n'est donc pas collectée.
    """
    noms: set[str] = set()
    pile: list[ast.AST] = _enfants_hors_corps(noeud)
    while pile:
        courant = pile.pop()
        if isinstance(courant, ast.NamedExpr):
            noms |= _noms_lies_cible(courant.target)
        pile.extend(_enfants_hors_corps(courant))
    return noms


def _noms_lies_par_filtrage(noeud: ast.stmt) -> set[str]:
    """Extrait les noms qu'une capture ``match``/``case`` lie dans la portée courante.

    Un motif de capture n'ouvre aucune portée : le nom qu'il lie survit au bloc.
    MESURÉ à l'interpréteur, après ``match object:`` / ``case Protocol:``, le nom
    ``Protocol`` vaut ``object`` et la classe qui en hérite a bien ``object``
    dans son MRO — le contournement est donc VALIDE à l'exécution, contrairement
    aux formes qui lèvent une erreur à l'import.

    Les trois formes de capture sont lues : le nom d'un ``as``, celui d'une
    étoile de séquence, et le reste d'un motif de mapping. Le motif est parcouru
    en entier, une capture pouvant être imbriquée dans une alternative, une
    séquence ou un motif de classe.
    """
    if not isinstance(noeud, ast.Match):
        return set()
    noms: set[str] = set()
    for cas in noeud.cases:
        for motif in ast.walk(cas.pattern):
            if isinstance(motif, (ast.MatchAs, ast.MatchStar)) and motif.name:
                noms.add(motif.name)
            elif isinstance(motif, ast.MatchMapping) and motif.rest:
                noms.add(motif.rest)
    return noms


def _noms_cibles_affectation(noeud: ast.stmt) -> set[str]:
    """Extrait TOUS les noms que toute liaison module-level peut réaffecter.

    Une instruction lie de trois façons distinctes, et n'en lire qu'une laissait
    à chaque fois un contournement ouvert : par sa CIBLE déclarée, par une
    EXPRESSION d'affectation écrite n'importe où dans ses sous-expressions, et
    par une CAPTURE de filtrage. Les trois sources sont réunies ici, à un seul
    endroit, afin qu'aucun appelant ne puisse en oublier une.
    """
    return (
        _noms_cibles_directes(noeud)
        | _noms_lies_par_expression_daffectation(noeud)
        | _noms_lies_par_filtrage(noeud)
    )


def _attributs_lies_cible(noeud: ast.expr) -> set[tuple[str, str]]:
    """Extrait les attributs de module liés par une cible, même destructurée."""
    if isinstance(noeud, ast.Attribute) and isinstance(noeud.value, ast.Name):
        return {(noeud.value.id, noeud.attr)}
    if isinstance(noeud, (ast.Tuple, ast.List)):
        return set().union(*(_attributs_lies_cible(element) for element in noeud.elts))
    if isinstance(noeud, ast.Starred):
        return _attributs_lies_cible(noeud.value)
    return set()


def _attributs_cibles_directes(noeud: ast.stmt) -> set[tuple[str, str]]:
    """Extrait les attributs de module qu'une INSTRUCTION réécrit par sa cible.

    Surveiller les seules cibles ``ast.Name`` laissait ``typing.Protocol =
    object`` intact : le nom du module survit, mais l'attribut par lequel
    l'exemption est prouvée ne désigne plus le protocole standard.

    La SUPPRESSION de l'attribut détruit la même preuve, et plus radicalement
    encore : après ``del t.Protocol``, la classe qui prétend en hériter échoue à
    l'import sur une ``AttributeError``. Ne lire que les affectations laissait
    donc exempter un code qui ne s'importe même pas. La symétrie avec
    ``_noms_cibles_directes``, qui compte déjà le ``del`` d'un NOM, est ici
    rétablie pour les attributs.

    L'affectation AUGMENTÉE fermait la dernière asymétrie de cette liste : le
    chemin des noms la lisait, celui des attributs non, si bien que
    ``t.Protocol += ()`` laissait l'exemption debout. MESURÉ à l'interpréteur,
    la forme réécrit pourtant l'attribut du module aussi sûrement qu'une
    affectation simple — un module n'a pas de ``__iadd__``, l'opération retombe
    sur ``__add__`` puis réaffecte la cible.

    Les autres formes liantes du chemin des noms n'ont PAS d'équivalent ici, et
    l'absence est mesurée, pas supposée : ``except … as t.X``, ``(t.X := …)`` et
    la capture ``case t.X`` sont soit refusées par la grammaire, soit — pour le
    ``case`` — un motif de VALEUR qui lit l'attribut sans jamais le lier.
    """
    if isinstance(noeud, ast.Assign):
        return set().union(
            *(_attributs_lies_cible(cible) for cible in noeud.targets)
        )
    if isinstance(noeud, ast.Delete):
        return set().union(
            *(_attributs_lies_cible(cible) for cible in noeud.targets),
            set(),
        )
    if isinstance(noeud, ast.AnnAssign):
        return _attributs_lies_cible(noeud.target)
    if isinstance(noeud, ast.AugAssign):
        return _attributs_lies_cible(noeud.target)
    if isinstance(noeud, (ast.For, ast.AsyncFor)):
        return _attributs_lies_cible(noeud.target)
    if isinstance(noeud, (ast.With, ast.AsyncWith)):
        return set().union(
            *(
                _attributs_lies_cible(element.optional_vars)
                for element in noeud.items
                if element.optional_vars is not None
            ),
            set(),
        )
    return set()


def _attributs_lies_par_comprehension(noeud: ast.stmt) -> set[tuple[str, str]]:
    """Extrait les attributs de module qu'une CIBLE de compréhension réécrit.

    C'est le seul point où les deux chemins doivent DIVERGER, et ne pas diverger
    était le défaut. La portée d'une compréhension confine le NOM qu'elle lie —
    raison pour laquelle ``_noms_lies_par_expression_daffectation`` l'ignore à
    dessein — mais elle ne confine rien du tout pour un ATTRIBUT : MESURÉ à
    l'interpréteur, ``[1 for t.Protocol in (object,)]`` écrase l'attribut du
    module tout comme une affectation ordinaire, la portée ne protégeant que le
    dictionnaire local, jamais l'objet module visé.

    Les sous-expressions sont parcourues parce qu'une compréhension n'est jamais
    une instruction : ``x = [1 for t.Protocol in (object,)]`` la cache derrière
    une affectation dont la cible est un simple nom, et ne lire que le premier
    niveau la manquerait entièrement.

    Les portées PROPRES restent sautées via ``_enfants_hors_corps``, et la portée
    de ce saut a CHANGÉ sans que la fonction bouge : son appelant l'applique
    désormais à chaque instruction de l'arbre, corps de fonctions et de classes
    compris, si bien que seul le corps d'un LAMBDA — une expression, qu'aucun
    parcours d'instructions n'atteint — lui échappe encore. MESURÉ,
    ``f = lambda: [1 for t.Protocol in (object,)]`` n'écrit rien tant que ``f``
    n'est pas appelée, et cette frontière-là est tenue par un test dédié.

    La cible d'un GÉNÉRATEUR est comptée sans exiger la preuve qu'il soit
    consommé : l'analyse est fail-closed, comme l'est déjà le mépris de l'ORDRE
    des instructions. Retenir l'attribut coûte au pire une exemption refusée là
    où le générateur dort ; l'ignorer rouvrirait le contournement dès qu'un
    appel l'entoure.
    """
    attributs: set[tuple[str, str]] = set()
    pile: list[ast.AST] = _enfants_hors_corps(noeud)
    while pile:
        courant = pile.pop()
        if isinstance(courant, ast.comprehension):
            attributs |= _attributs_lies_cible(courant.target)
        pile.extend(_enfants_hors_corps(courant))
    return attributs


def _attributs_cibles_affectation(arbre: ast.AST) -> set[tuple[str, str]]:
    """Extrait TOUS les attributs de module que l'arbre réécrit, à toute PROFONDEUR.

    C'est ici que le chemin des ATTRIBUTS quitte celui des NOMS, et la
    distinction est la raison d'être de la fonction : un nom est lié à une
    portée, si bien qu'une affectation écrite dans une fonction ou dans un corps
    de classe ne touche pas le module ; un attribut de module ne l'est pas, et
    ``t.Protocol = object`` mutile l'objet ``typing`` où qu'il soit écrit.

    MESURÉ avant correction, la collecte n'inspectait que les instructions du
    niveau module et de ses blocs : une fonction contenant ``t.Protocol =
    object``, puis APPELÉE, laissait la classe suivante hériter d'``object`` tout
    en restant exemptée. Le même trou existait dans un corps de classe, où
    ``class Boite: t.Protocol = object`` n'a rien d'un attribut de classe — la
    cible étant un attribut, c'est bien le module qui est écrit, et non un
    membre de la classe.

    Conséquence FAIL-CLOSED assumée : une fonction qui réécrit l'attribut sans
    jamais être appelée révoque elle aussi la preuve. Suivre les appels
    exigerait une analyse de flot qu'un décorateur, un appel indirect ou un
    import tiers rendraient de toute façon incomplète ; et écrire une fonction
    qui mutile ``typing.Protocol`` sans jamais l'appeler n'a aucun usage
    légitime, quand l'angle mort inverse rend l'exemption entièrement
    contournable.

    Les deux sources sont réunies ici, exactement comme ``_noms_cibles_affectation``
    réunit les siennes, mais sur l'ARBRE au lieu d'une instruction : la CIBLE
    déclarée de chaque instruction — ``ast.walk`` les livre toutes, y compris
    celles des corps — et la cible d'une COMPRÉHENSION, qui n'est jamais une
    instruction et se lit donc dans les sous-expressions de chacune.
    """
    return set().union(
        set(),
        *(
            _attributs_cibles_directes(noeud) | _attributs_lies_par_comprehension(noeud)
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.stmt)
        ),
    )


def _valeur_prouve_une_absence(
    valeur: ast.expr,
    noms_prouves: AbstractSet[str],
    modules_builtins: AbstractSet[str],
) -> bool:
    """Prouve qu'une affectation lie son nom à l'absence d'implémentation.

    La preuve est celle qu'exige déjà la levée directe : le nom construit — nu,
    qualifié par un attribut de module, appelé ou non — est celui de l'absence
    d'implémentation. ``E = MonModule.MonErreur`` n'est donc jamais concerné,
    l'origine restant inconnue.

    Les noms DÉJÀ prouvés sont fournis par l'appelant plutôt que relus ici : un
    alias d'alias désigne la même exception, et sans cette transitivité la
    chaîne où une cible reçoit l'absence qualifiée, puis une seconde cible
    échappait entièrement à la règle. La liste inclut toujours les noms de
    l'interpréteur, si bien qu'aucune lecture séparée n'est nécessaire.

    La forme qualifiée exige le MÊME porteur prouvé que la levée directe : sans
    cette symétrie, une affectation recevant l'attribut HOMONYME d'un module
    métier liait le nom à l'absence d'implémentation, et le ``raise`` suivant
    était refusé par ricochet — le faux positif du porteur non prouvé, déplacé
    d'une ligne.
    """  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
    cible = valeur.func if isinstance(valeur, ast.Call) else valeur
    if isinstance(cible, ast.Attribute):
        return _attribut_absence_de_builtins(cible, modules_builtins)
    return isinstance(cible, ast.Name) and cible.id in noms_prouves


def _appariement_destructure(
    cibles: list[ast.expr], valeurs: list[ast.expr]
) -> list[tuple[ast.expr, ast.expr]]:
    """Aligne une destructuration POSITION par POSITION, comme le fait l'interpréteur.

    Deux erreurs symétriques étaient possibles, et l'appariement les écarte
    toutes les deux. Ne rien prouver — le comportement observé — laissait une
    destructuration dont la PREMIÈRE valeur est l'absence d'implémentation
    qualifiée passer pour un objet quelconque, puisque la valeur globale est un
    tuple. Tout prouver dès qu'UNE valeur convient ferait au contraire de la
    seconde cible un stub qu'elle n'est pas.

    L'étoile absorbe un nombre variable de valeurs : les positions qui la
    précèdent restent alignées par la gauche, celles qui la suivent par la
    droite. L'étoile elle-même lie une LISTE, jamais l'exception, et n'est donc
    appariée avec rien. Une longueur incompatible n'apparie rien du tout : la
    forme échouerait à l'exécution, et en déduire une preuve serait inventer.
    """  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
    etoiles = [rang for rang, cible in enumerate(cibles) if isinstance(cible, ast.Starred)]
    if len(etoiles) > 1:
        return []
    if not etoiles:
        return list(zip(cibles, valeurs)) if len(cibles) == len(valeurs) else []
    if len(valeurs) < len(cibles) - 1:
        return []
    pivot = etoiles[0]
    suffixe = len(cibles) - pivot - 1
    apparies = list(zip(cibles[:pivot], valeurs[:pivot]))
    if suffixe:
        apparies += list(zip(cibles[pivot + 1 :], valeurs[len(valeurs) - suffixe :]))
    return apparies


def _noms_lies_a_une_absence(
    cible: ast.expr,
    valeur: ast.expr,
    noms_prouves: AbstractSet[str],
    modules_builtins: AbstractSet[str],
) -> set[str]:
    """Nomme les seules cibles qu'une affectation lie à l'absence d'implémentation.

    La destructuration n'est appariée que lorsque les DEUX côtés énumèrent leurs
    éléments : ``A, B = fabriquer()`` ne dit rien de ce que chaque nom reçoit, et
    l'appelant retombe alors sur la lecture globale de la valeur.
    """
    if isinstance(cible, (ast.Tuple, ast.List)):
        if not isinstance(valeur, (ast.Tuple, ast.List)):
            return (
                _noms_lies_cible(cible)
                if _valeur_prouve_une_absence(
                    valeur, noms_prouves, modules_builtins
                )
                else set()
            )
        return set().union(
            *(
                _noms_lies_a_une_absence(
                    sous_cible, sous_valeur, noms_prouves, modules_builtins
                )
                for sous_cible, sous_valeur in _appariement_destructure(
                    cible.elts, valeur.elts
                )
            ),
            set(),
        )
    return (
        _noms_lies_cible(cible)
        if _valeur_prouve_une_absence(valeur, noms_prouves, modules_builtins)
        else set()
    )


def _absences_prouvees(
    affectations: list[ast.Assign | ast.AnnAssign],
    aliases_importes: AbstractSet[str],
    modules_builtins: AbstractSet[str],
) -> set[str]:
    """Résout par POINT FIXE les noms qu'un module lie à l'absence d'implémentation.

    Un alias d'alias est le même stub que la levée directe : s'arrêter au premier
    cran laissait la chaîne entière échapper à la règle. Le parcours ignore
    l'ORDRE des lignes, comme le reste de la collecte des liaisons, et s'arrête
    dès qu'un tour n'ajoute plus rien — ce qui le borne, le nombre de noms liés
    par le module étant fini.

    Le résultat exclut la graine : les noms de l'interpréteur sont déjà reconnus
    par la règle de levée, et les alias d'import le sont par la collecte des
    imports. Ne rendre que les noms liés par AFFECTATION laisse donc intact le
    traitement des autres origines.
    """
    graine = set(_NOMS_ABSENCE_IMPLEMENTATION) | set(aliases_importes)
    prouves = set(graine)
    ajout = True
    while ajout:
        ajout = False
        for noeud in affectations:
            if noeud.value is None:
                continue
            cibles = (
                noeud.targets if isinstance(noeud, ast.Assign) else [noeud.target]
            )
            nouveaux = set().union(
                *(
                    _noms_lies_a_une_absence(
                        cible, noeud.value, prouves, modules_builtins
                    )
                    for cible in cibles
                ),
                set(),
            )
            if nouveaux - prouves:
                prouves |= nouveaux
                ajout = True
    return prouves - graine


def _noeuds_de_la_portee(fonction: ast.AST) -> list[ast.AST]:
    """Énumère les nœuds de la portée PROPRE d'une fonction, sans les portées filles.

    Une fonction, un lambda ou une classe imbriqués ouvrent leur propre espace de
    noms : ce qu'ils déclarent n'appartient pas à la portée parcourue ici, et
    chaque fonction imbriquée est de toute façon analysée pour elle-même.
    """
    noeuds: list[ast.AST] = []
    pile: list[ast.AST] = list(ast.iter_child_nodes(fonction))
    while pile:
        noeud = pile.pop()
        if isinstance(
            noeud,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
        ):
            continue
        noeuds.append(noeud)
        pile.extend(ast.iter_child_nodes(noeud))
    return noeuds


def _noms_reaffectes_par_global(arbre: ast.Module) -> set[str]:
    """Recense les noms du MODULE qu'une fonction réaffecte via ``global``.

    Les corps de fonctions sont ignorés par la collecte des liaisons parce qu'une
    affectation locale ne touche pas le module. ``global`` supprime précisément
    cette portée locale : l'affectation lie alors le module, et la déclaration
    seule ne suffit pas — le nom doit aussi être affecté dans la même portée.
    """
    reaffectes: set[str] = set()
    for fonction in ast.walk(arbre):
        if not isinstance(fonction, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        portee = _noeuds_de_la_portee(fonction)
        declares = {
            nom
            for noeud in portee
            if isinstance(noeud, ast.Global)
            for nom in noeud.names
        }
        if not declares:
            continue
        affectes: set[str] = set()
        for noeud in portee:
            if isinstance(noeud, ast.stmt):
                affectes |= _noms_cibles_affectation(noeud)
        reaffectes |= declares & affectes
    return reaffectes


def _noms_lies_par_import(noeud: ast.Import | ast.ImportFrom) -> set[str]:
    """Énumère les noms que cet import LIE dans la portée où il est écrit.

    ``import a.b.c`` lie ``a``, jamais ``a.b.c`` : sans alias, seul le paquet
    racine entre dans le namespace. Avec ``as``, c'est l'alias seul qui est lié,
    sous les deux formes d'import. ``from x import *`` ne lie que le pseudo-nom
    ``*``, qui ne correspond à aucun identifiant : rien n'est donc révoqué, ce
    qui est fail-closed pour les détections comme pour les exemptions.
    """
    if isinstance(noeud, ast.Import):
        return {alias.asname or alias.name.partition(".")[0] for alias in noeud.names}
    return {alias.asname or alias.name for alias in noeud.names}


def _lier_import(
    noeud: ast.Import | ast.ImportFrom,
    aliases: _CollecteAliases,
    noms_importes_hors_builtins: set[str],
) -> None:
    """Lie les alias qu'un import PROUVE, quelle que soit la portée qui le porte.

    La règle est la même au niveau module et au fond d'une fonction : ``import
    pytest as pt`` lie ``pt`` au module pytest partout où il est écrit. Ce qui
    change n'est pas la preuve, mais son ÉTENDUE, et c'est l'appelant qui la
    fixe — le module pour le namespace global, ``_aliases_de_portee`` pour une
    portée locale. Un seul endroit lit donc les imports, faute de quoi les deux
    lectures divergeraient au premier alias ajouté.

    Lier commence par DÉLIER : les noms que cet import relie perdent d'abord ce
    qu'un import antérieur leur prouvait, avant que celui-ci n'ajoute le sien.
    L'ordre des deux gestes est ce qui fait décider la liaison la PLUS PROCHE,
    et l'ajout seul laissait survivre indéfiniment la preuve du premier import.
    """
    aliases.retirer_preuves_importees(_noms_lies_par_import(noeud))
    if isinstance(noeud, ast.Import):
        for alias in noeud.names:
            noms_importes_hors_builtins.add(alias.asname or alias.name.partition(".")[0])
            if alias.name in _MODULES_TYPING:
                aliases.modules_typing.add(alias.asname or alias.name)
            elif alias.name in _MODULES_ABC:
                aliases.modules_abc.add(alias.asname or alias.name)
            elif alias.name == "pytest":
                aliases.modules_pytest.add(alias.asname or "pytest")
            elif alias.name == "unittest":
                aliases.modules_unittest.add(alias.asname or "unittest")
            elif alias.name == "builtins":
                aliases.modules_builtins.add(alias.asname or "builtins")
        return

    origine = noeud.module or ""
    if origine != "builtins":
        noms_importes_hors_builtins.update(
            alias.asname or alias.name for alias in noeud.names
        )
    if origine in _MODULES_TYPING:
        aliases.protocols.update(
            alias.asname or "Protocol"
            for alias in noeud.names
            if alias.name == "Protocol"
        )
    elif origine in _MODULES_ABC:
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
            oracles_par_attribut = {
                "raises": aliases.oracles_raises,
                "fail": aliases.oracles_fail,
            }
            for alias in noeud.names:
                if alias.name in _ORACLES_PYTEST:
                    oracles_par_attribut[alias.name].add(alias.asname or alias.name)
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


@dataclass
class _LiaisonsModule:
    """Rassemble ce que le namespace d'un module lie, prouve et détruit."""

    aliases: _CollecteAliases
    reassignees: set[str]
    absences_prouvees: set[str]
    noms_importes_hors_builtins: set[str]


def _imports_module(
    corps: list[ast.stmt],
) -> _LiaisonsModule:
    """Collecte les liaisons du namespace du module : ses imports ET ses écrasements.

    Les blocs module-level — ``if`` (notamment ``if TYPE_CHECKING:``), ``for``,
    ``while``, ``with``, ``try``, ``try``/``except*`` et ``match`` — sont
    parcourus dans les DEUX sens, car ils lient le module exactement comme son
    premier niveau : leurs imports prouvent un alias, leurs affectations le
    détruisent. Ne descendre que pour les imports laissait une réaffectation
    cachée d'un seul cran conserver l'alias, donc exempter une classe qui hérite
    en réalité d'``object``. ``ast.TryStar`` est un nœud DISTINCT d'``ast.Try``,
    et non une sous-classe : l'omettre rendait ``except*`` invisible ici alors
    que ``_instructions_hors_fonction`` le parcourait déjà.

    Les corps de fonctions et de méthodes ne sont jamais parcourus : leur portée
    est locale, si bien qu'un import local ne crée aucune exemption globale et
    qu'une affectation locale n'invalide aucun alias du module. Les corps de
    CLASSES ne le sont pas non plus, et cette divergence avec
    ``_instructions_hors_fonction`` est voulue : une classe est un espace de noms
    propre, si bien que ``class Boite: Protocol = object`` ne réaffecte aucun nom
    du module et ne doit invalider aucune preuve.

    Cette limite vaut pour les NOMS, jamais pour les ATTRIBUTS, et c'est
    exactement pourquoi les seconds ne sont plus collectés ici :
    ``_attributs_cibles_affectation`` lit l'arbre entier, corps compris, parce
    qu'un attribut de module est écrit sur l'objet module quelle que soit la
    portée d'où l'écriture part.
    """
    aliases = _CollecteAliases()
    reassignees: set[str] = set()
    affectations: list[ast.Assign | ast.AnnAssign] = []
    noms_importes_hors_builtins: set[str] = set()

    def visiter(instructions: list[ast.stmt]) -> None:
        for noeud in instructions:
            reassignees.update(_noms_cibles_affectation(noeud))
            if isinstance(noeud, (ast.Assign, ast.AnnAssign)):
                affectations.append(noeud)
            if isinstance(noeud, (ast.Import, ast.ImportFrom)):
                _lier_import(noeud, aliases, noms_importes_hors_builtins)
            elif isinstance(noeud, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                visiter(noeud.body)
                visiter(noeud.orelse)
            elif isinstance(noeud, (ast.With, ast.AsyncWith)):
                visiter(noeud.body)
            elif isinstance(noeud, (ast.Try, ast.TryStar)):
                visiter(noeud.body)
                visiter(noeud.orelse)
                visiter(noeud.finalbody)
                for gestionnaire in noeud.handlers:
                    visiter(gestionnaire.body)
            elif isinstance(noeud, ast.Match):
                for cas in noeud.cases:
                    visiter(cas.body)

    visiter(corps)
    return _LiaisonsModule(
        aliases,
        reassignees,
        _absences_prouvees(
            affectations,
            aliases.not_implemented_errors,
            aliases.modules_builtins,
        ),
        noms_importes_hors_builtins,
    )


def _analyser_imports(arbre: ast.Module) -> _AliasesImports:
    """Prouve les imports module-level et retire toute liaison qui les écrase.

    Toute définition, affectation, cible de boucle ou cible de contexte au niveau
    module retire l'alias, à quelque profondeur de bloc qu'elle soit écrite. Cette
    règle fail-closed empêche une exemption lorsque l'origine standard du nom
    n'est plus certaine, et elle s'applique sans tenir compte de l'ORDRE : une
    réaffectation écrite avant l'import compte autant qu'une réaffectation écrite
    après lui.

    Quatre liaisons échappaient à ce parcours : la réécriture d'un ATTRIBUT de
    module, la réaffectation d'un nom par ``global`` depuis une fonction, le
    détournement d'un nom d'exception builtin par un IMPORT, et l'alias
    d'exception construit par AFFECTATION. Les trois premières détruisent une
    preuve et sont appliquées après le retrait général ; la dernière en crée
    une, et doit donc être ajoutée en dernier — l'affectation qui la porte est
    aussi une réaffectation, si bien que l'appliquer plus tôt reviendrait à
    l'effacer avec elle.

    Les attributs sont collectés sur l'ARBRE, non sur les liaisons du module :
    leur portée d'écriture n'a aucune importance, alors que celle d'un nom
    décide de tout. C'est la seule asymétrie voulue entre les deux collectes, et
    elle est ce qui ferme ``def desarmer(): t.Protocol = object``.
    """
    liaisons = _imports_module(arbre.body)
    liaisons.aliases.retirer(liaisons.reassignees)
    liaisons.aliases.retirer_attributs_prouvants(_attributs_cibles_affectation(arbre))
    liaisons.aliases.retirer_exemptions(_noms_reaffectes_par_global(arbre))
    liaisons.aliases.retirer_exceptions_importees(liaisons.noms_importes_hors_builtins)
    liaisons.aliases.ajouter_absences_prouvees(liaisons.absences_prouvees)
    return liaisons.aliases.figer()


def _est_classe_protocol(
    classe: ast.ClassDef,
    aliases: _AliasesImports,
    portees: _PorteesLexicales,
) -> bool:
    """Détermine si une base est prouvée comme le véritable typing.Protocol.

    La forme paramétrée ``Protocol[T]`` est un ``ast.Subscript`` : la valeur
    souscrite est dépliée avant la preuve, car un protocole générique est la même
    abstraction que sa forme nue. La preuve d'origine de l'alias est inchangée :
    une classe locale usurpant le nom reste refusée sous les deux formes.

    L'alias du module ne suffit pourtant jamais seul : il dit ce que le nom
    désigne AU NIVEAU DU MODULE, jamais ce qu'il désigne à l'endroit où la base
    est écrite. MESURÉ, une définition locale homonyme — ``def f(): class
    Protocol: …`` puis ``class C(Protocol)`` — faisait hériter d'une classe
    ordinaire tout en conservant l'exemption. La base est donc résolue dans la
    portée où elle est écrite, par le résolveur déjà employé pour les types
    d'exception. Sous la forme qualifiée, c'est le PORTEUR qui est résolu : un
    ``t`` masqué localement ne désigne plus le module ``typing``.

    ``typing_extensions`` compte à ÉGALITÉ avec ``typing`` (``_MODULES_TYPING``).
    MESURÉ avant correction : les quatre écritures du rétroportage —
    ``from typing_extensions import Protocol``, son alias, ``import
    typing_extensions`` et son alias — étaient signalées ``EXECUTABLE_ELLIPSIS``
    quand le témoin ``from typing import Protocol`` passait. Le module rétroporte
    ce que la version de Python installée n'expose pas encore : refuser cet
    idiome rendait le gate inutilisable sur du code normal, et un gate qui gêne
    du code normal finit désarmé. La parité est obtenue en versant les deux
    origines dans les MÊMES ensembles de preuve, si bien que toutes les
    révocations déjà en place — réaffectation, ``del``, réécriture ou suppression
    de l'attribut prouvant, ``global``, masquage lexical — s'y appliquent sans
    qu'aucune ait à être dupliquée.

    ``abc`` n'a pas d'équivalent à traiter, et l'absence est MESURÉE :
    ``hasattr(typing_extensions, "abstractmethod")`` vaut ``False`` — le module
    rétroporte ``typing``, jamais ``abc``. ``_MODULES_ABC`` reste donc singleton,
    à la même place et sous la même forme, pour que l'ajout d'un rétroportage
    futur n'ait qu'un seul endroit à modifier.
    """
    for base in classe.bases:
        cible = _base_declaree(base)
        if isinstance(cible, ast.Name):
            if cible.id in aliases.protocols and not portees.masque(cible.id, classe):
                return True
            continue
        if (
            isinstance(cible, ast.Attribute)
            and isinstance(cible.value, ast.Name)
            and cible.value.id in aliases.modules_typing
            and cible.attr == "Protocol"
            and not portees.masque(cible.value.id, classe)
        ):
            return True
    return False


def _base_declaree(base: ast.expr) -> ast.expr:
    """Déplie la forme paramétrée ``Base[T]``, qui désigne la même classe que ``Base``."""
    return base.value if isinstance(base, ast.Subscript) else base


def _parents_de_larbre(arbre: ast.Module) -> dict[ast.AST, ast.AST]:
    """Associe chaque nœud au nœud qui le contient, seul lien vers ses portées.

    L'AST de Python ne porte pas de lien remontant : sans cette table, une
    définition ne peut pas dire dans QUELLE portée elle est écrite, et la
    résolution d'une base ne peut être que globale — le défaut même que la
    résolution lexicale corrige.
    """
    parents: dict[ast.AST, ast.AST] = {}
    for noeud in ast.walk(arbre):
        for enfant in ast.iter_child_nodes(noeud):
            parents[enfant] = noeud
    return parents


def _portee_englobante(
    parents: Mapping[ast.AST, ast.AST], noeud: ast.AST
) -> ast.AST | None:
    """Remonte jusqu'au bloc qui ouvre l'espace de noms contenant ce nœud."""
    courant = parents.get(noeud)
    while courant is not None and not isinstance(courant, _PORTEES_PROPRES):
        courant = parents.get(courant)
    return courant


def _chaine_de_portees(
    parents: Mapping[ast.AST, ast.AST], definition: ast.AST
) -> list[ast.AST]:
    """Énumère, du plus proche au module, les portées où l'EN-TÊTE d'une définition se résout.

    Le corps de classe qui contient DIRECTEMENT la définition en fait partie : la
    base y est évaluée pendant l'exécution de ce corps, si bien qu'une classe
    sœur déclarée juste au-dessus la résout. Les corps de classes plus lointains
    en sont exclus, Python ne les faisant pas participer à la résolution des
    portées imbriquées — ``class A:`` déclarant ``class P:`` puis, dans une
    MÉTHODE de ``A``, ``class S(P)`` lève ``NameError`` à l'exécution.

    La règle vaut pour toute définition, non pour les seules classes : le
    DÉCORATEUR d'une méthode s'évalue exactement là où s'évalueraient les bases
    d'une classe écrite au même endroit. Les deux questions se résolvent donc
    dans la même chaîne, et il n'existe qu'un seul résolveur.
    """
    chaine: list[ast.AST] = []
    portee = _portee_englobante(parents, definition)
    while portee is not None:
        if not chaine or not isinstance(portee, ast.ClassDef):
            chaine.append(portee)
        portee = _portee_englobante(parents, portee)
    return chaine


def _noeuds_propres(portee: ast.AST) -> list[ast.AST]:
    """Énumère la portée PROPRE d'un bloc en CONSERVANT ses définitions filles.

    ``_noeuds_de_la_portee`` écarte une définition imbriquée avant de la retenir :
    son NOM, pourtant lié dans la portée parcourue, y est perdu. Ici la
    définition est conservée et seul son intérieur est ignoré, ce qui est
    exactement ce qu'il faut pour savoir CE QUE la portée lie.
    """
    noeuds: list[ast.AST] = []
    pile: list[ast.AST] = list(ast.iter_child_nodes(portee))
    while pile:
        noeud = pile.pop()
        noeuds.append(noeud)
        if isinstance(noeud, _PORTEES_PROPRES):
            continue
        pile.extend(ast.iter_child_nodes(noeud))
    return noeuds


def _liaisons_de_portee(portee: ast.AST) -> tuple[dict[str, ast.ClassDef], set[str]]:
    """Sépare ce qu'une portée lie à une CLASSE de ce qu'elle lie sans preuve.

    Les IMPORTS en sont volontairement absents : ils sont ce qui PROUVE les alias
    lus par ``_analyser_imports``, et les compter ici ferait passer ``from
    unittest import TestCase`` pour un écrasement du nom — un faux positif sur
    l'idiome le plus courant du dépôt, alors que le module gère déjà ses propres
    écrasements par ``reassignees``.

    Les PARAMÈTRES comptent parmi les liaisons opaques : ``def configurer(Panne)``
    masque le type d'exception du module dans tout le corps de la fonction, et
    une classe qui hérite du paramètre hérite d'une valeur inconnue.

    Une liaison OPAQUE l'emporte sur une définition de classe du même nom :
    quand les deux coexistent, ce que la base désigne n'est plus certain, et
    l'exemption doit tomber. Un nom déclaré ``global`` puis AFFECTÉ tombe sous
    cette règle et le doit : il réécrit le nom du module avec une valeur
    inconnue, si bien qu'en faire une liaison opaque est la lecture exacte de ce
    que la classe héritera.
    """
    classes: dict[str, ast.ClassDef] = {}
    opaques: set[str] = set()
    for noeud in _noeuds_propres(portee):
        if isinstance(noeud, ast.ClassDef):
            classes[noeud.name] = noeud
        elif isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            opaques.add(noeud.name)
        elif isinstance(noeud, ast.arg):
            opaques.add(noeud.arg)
        elif isinstance(noeud, ast.stmt):
            opaques |= _noms_cibles_affectation(noeud)
    return classes, opaques


class _PorteesLexicales:
    """Table des portées d'un module, consultée par TOUTE règle qui résout un nom.

    Un seul résolveur existe, et il est partagé : la résolution par portée
    construite pour les bases d'exception répond mot pour mot à la question que
    posent le protocole d'une classe et le décorateur d'une méthode — ce que le
    nom écrit ICI désigne réellement. En dupliquer un second garantirait de le
    corriger à moitié le jour suivant.

    La table est mémorisée par module : reconstruire le lien parent à chaque
    question referait un parcours complet de l'arbre par nom résolu.
    """

    def __init__(self, arbre: ast.Module) -> None:
        self._parents = _parents_de_larbre(arbre)
        self._liaisons: dict[ast.AST, tuple[dict[str, ast.ClassDef], set[str]]] = {}

    def chaine(self, definition: ast.AST) -> list[ast.AST]:
        """Énumère les portées où un nom écrit dans cet en-tête se résout."""
        return _chaine_de_portees(self._parents, definition)

    def liaisons(self, portee: ast.AST) -> tuple[dict[str, ast.ClassDef], set[str]]:
        """Retourne, en la mémorisant, la table des noms que cette portée lie."""
        connue = self._liaisons.get(portee)
        if connue is None:
            connue = _liaisons_de_portee(portee)
            self._liaisons[portee] = connue
        return connue

    def masque(self, nom: str, definition: ast.AST) -> bool:
        """Dit si une liaison LOCALE prive le nom de l'origine prouvée par le module.

        Toute liaison compte, classe ou non : ``class Protocol:``, ``Protocol =
        object``, un paramètre ``Protocol`` ou une fonction homonyme font tous
        désigner autre chose que le protocole importé. Consulter les imports du
        module malgré ce masquage reviendrait à exempter sur la foi d'une
        orthographe, exactement ce que ``_base_est_derivee`` refuse déjà pour les
        types d'exception.
        """
        for portee in self.chaine(definition):
            classes_locales, opaques = self.liaisons(portee)
            if nom in opaques or nom in classes_locales:
                return True
        return False


def _aliases_de_portee(portee: ast.AST) -> _CollecteAliases:
    """Collecte les alias que les imports ÉCRITS DANS cette portée prouvent.

    Le parcours est celui des liaisons d'une portée — ``_noeuds_propres`` — et
    non celui du module : les imports d'un bloc ``if`` ou ``try`` intérieur à la
    fonction lient la même portée qu'elle, tandis qu'une définition imbriquée
    ouvre la sienne et n'est jamais traversée.

    ``exceptions_builtins`` est délibérément VIDÉ. Cet ensemble n'est jamais
    prouvé par un import : il est la graine des noms de l'interpréteur, que le
    module a pu AMPUTER en détournant l'un d'eux. Le laisser plein le
    réintroduirait à la première portée locale rencontrée, et restaurerait
    précisément la preuve que le module venait de révoquer.

    Les imports sont RÉORDONNÉS par leur position dans le source avant d'être
    liés. ``_noeuds_propres`` dépile ce qu'il a empilé : il rend donc les nœuds à
    REBOURS de l'ordre écrit, ce qui n'avait aucune conséquence tant que lier ne
    faisait qu'ajouter. Depuis qu'un import REBINDE — donc révoque —, cet ordre
    décide, et le rendre inverse ferait l'emporter le PREMIER import écrit sur le
    dernier, à l'exact opposé de l'exécution. Le tri rend la portée locale
    identique au module, dont ``_imports_module`` parcourt déjà les instructions
    dans l'ordre du source.
    """
    aliases = _CollecteAliases(exceptions_builtins=set())
    imports = [
        noeud
        for noeud in _noeuds_propres(portee)
        if isinstance(noeud, (ast.Import, ast.ImportFrom))
    ]
    for noeud in sorted(imports, key=lambda noeud: (noeud.lineno, noeud.col_offset)):
        _lier_import(noeud, aliases, set())
    return aliases


def _affectations_de_portee(portee: ast.AST) -> list[ast.Assign | ast.AnnAssign]:
    """Énumère les affectations que cette portée exécute, blocs intérieurs compris."""
    return [
        noeud
        for noeud in _noeuds_propres(portee)
        if isinstance(noeud, (ast.Assign, ast.AnnAssign))
    ]


class _AliasesVisibles:
    """Résout les alias visibles LÀ OÙ un nœud est écrit, imports locaux compris.

    Un import écrit dans une fonction lie un alias RÉEL, mais seulement DANS SA
    PORTÉE : ``import pytest as pt`` dans ``f`` ne dit rien de ce que ``pt``
    désigne dans ``g``. La collecte du module ne pouvait donc pas simplement
    l'absorber — c'est le miroir exact des ATTRIBUTS de module, écrits n'importe
    où et visibles partout, que la collecte lit sur l'arbre entier. MESURÉ avant
    correction : ``from builtins import <l'absence> as NI`` puis ``raise NI``,
    et ``import pytest as pt`` puis ``pt.skip(…)``, écrits dans une fonction,
    étaient acceptés là où les mêmes lignes au niveau module étaient refusées.

    La résolution réutilise l'UNIQUE table de portées : la chaîne d'un nœud dit
    déjà quelles portées son nom traverse, corps de classes lointains exclus
    comme à l'exécution. En écrire une seconde garantirait de ne corriger
    qu'une moitié des règles au premier défaut suivant.

    Le résultat est mémorisé par portée la plus proche : tous les nœuds d'une
    même fonction voient exactement les mêmes alias, et la chaîne n'est
    reparcourue qu'une fois par portée.
    """  # proof:allow — le motif d'absence est le SUJET du gate, cité ici comme mesure

    def __init__(self, socle: _AliasesImports, portees: _PorteesLexicales) -> None:
        self._socle = socle
        self._portees = portees
        self._visibles: dict[ast.AST, _AliasesImports] = {}

    def au(self, noeud: ast.AST) -> _AliasesImports:
        """Rend les alias visibles à l'endroit où ce nœud est ÉCRIT.

        Un nœud du corps d'une fonction est écrit DANS cette fonction : sa
        chaîne commence par elle. L'en-tête d'une définition — base de classe,
        décorateur — est au contraire écrit dans la portée qui la CONTIENT :
        interroger la définition elle-même rend donc la bonne chaîne pour les
        deux usages, exactement comme pour le masquage lexical.
        """
        chaine = [
            portee
            for portee in self._portees.chaine(noeud)
            if not isinstance(portee, ast.Module)
        ]
        if not chaine:
            return self._socle
        connu = self._visibles.get(chaine[0])
        if connu is None:
            connu = self._socle
            for portee in reversed(chaine):
                connu = self._enrichir(connu, portee)
            self._visibles[chaine[0]] = connu
        return connu

    def _enrichir(
        self, socle: _AliasesImports, portee: ast.AST
    ) -> _AliasesImports:
        """Ajoute au socle ce que cette portée prouve : ses imports, puis ses alias affectés.

        L'ordre compte. Les absences prouvées par AFFECTATION sont résolues
        APRÈS la fusion des imports et avec les alias déjà visibles : ``E =
        b.<l'absence>`` où ``b`` vient d'un import du module ne se lit qu'ainsi,
        et le calculer sur les seuls imports de la portée manquerait la moitié
        des chaînes d'alias.
        """  # proof:allow — le motif d'absence est le SUJET du gate, cité ici comme mesure
        fusion = _CollecteAliases.depuis(socle)
        fusion.ajouter(_aliases_de_portee(portee))
        fusion.ajouter_absences_prouvees(
            _absences_prouvees(
                _affectations_de_portee(portee),
                fusion.not_implemented_errors,
                fusion.modules_builtins,
            )
        )
        return fusion.figer()


def _base_est_derivee(
    cible: ast.expr,
    classe: ast.ClassDef,
    chaine: list[ast.AST],
    portees: _PorteesLexicales,
    positions_derivees: set[tuple[int, int]],
    est_base_prouvee: Callable[[ast.expr, ast.ClassDef], bool],
) -> bool:
    """Décide si une base désigne un type déjà prouvé dérivé, ou la base visée.

    Un nom nu est d'abord résolu dans SA portée, du plus proche au module, comme
    à l'exécution : une définition locale l'emporte sur ce que les imports du
    module prouvent. Ce n'est qu'à défaut de TOUTE liaison locale que la preuve
    d'origine est consultée. Sans cet ordre, une classe locale ordinaire portant
    le nom d'un type d'exception — ou celui de ``TestCase`` — suffisait à exempter
    ce qui en hérite.

    Une liaison locale OPAQUE arrête la résolution sans jamais retomber sur la
    preuve d'origine : le nom désigne alors quelque chose d'inconnu, et
    consulter les imports reviendrait à exempter sur la foi d'une orthographe.

    La CLASSE est transmise à la preuve d'origine : celle-ci se lit dans la
    portée où la base est écrite, un import local prouvant une origine que le
    module ignore. Sans elle, la preuve resterait globale là où la résolution
    est devenue lexicale.
    """
    if not isinstance(cible, ast.Name):
        return est_base_prouvee(cible, classe)
    for portee in chaine:
        classes_locales, opaques = portees.liaisons(portee)
        if cible.id in opaques:
            return False
        definition = classes_locales.get(cible.id)
        if definition is not None:
            return (definition.lineno, definition.col_offset) in positions_derivees
    return est_base_prouvee(cible, classe)


def _positions_de_classes_derivees(
    arbre: ast.Module,
    est_base_prouvee: Callable[[ast.expr, ast.ClassDef], bool],
    portees: _PorteesLexicales,
) -> frozenset[tuple[int, int]]:
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

    Le résultat désigne les DÉFINITIONS par leur position, jamais par leur nom, et
    la RÉSOLUTION d'une base tient désormais compte des PORTÉES. Les deux points
    étaient distincts, et le premier ne suffisait pas : une classe locale
    héritant d'un homonyme LOCAL restait exemptée parce que la résolution par nom
    sur tout l'arbre lui prêtait l'héritage du type d'exception du module. Une
    base se résout maintenant dans la portée où elle est écrite avant de retomber
    sur le module, exactement comme à l'exécution.
    """
    classes = [noeud for noeud in ast.walk(arbre) if isinstance(noeud, ast.ClassDef)]
    chaines = {classe: portees.chaine(classe) for classe in classes}
    positions_derivees: set[tuple[int, int]] = set()
    ajout = True
    while ajout:
        ajout = False
        for classe in classes:
            position = (classe.lineno, classe.col_offset)
            if position in positions_derivees:
                continue
            for base in classe.bases:
                if _base_est_derivee(
                    _base_declaree(base),
                    classe,
                    chaines[classe],
                    portees,
                    positions_derivees,
                    est_base_prouvee,
                ):
                    positions_derivees.add(position)
                    ajout = True
                    break
    return frozenset(positions_derivees)


def _est_base_exception_builtin(base: ast.expr, aliases: _AliasesImports) -> bool:
    """Reconnaît une base d'exception fournie par builtins, nue ou qualifiée.

    La liste des noms est LUE dans ``builtins`` à l'import du gate, jamais
    recopiée : toute hiérarchie d'exceptions de l'interpréteur est ainsi couverte
    sans qu'un oubli de recopie puisse rendre un type d'exception méconnaissable.

    Le NOM ne suffit pourtant jamais à lui seul, dans aucune des deux formes.
    Sous la forme nue, il doit rester celui de l'interpréteur : un module qui
    écrit ``ValueError = object`` ou ``from transport import ValueError`` fait
    hériter d'autre chose, et son exemption tombe — d'où la lecture de
    ``aliases.exceptions_builtins``, amputé de tout nom relié localement.

    Sous la forme qualifiée, c'est le PORTEUR qui doit être prouvé, et non
    l'orthographe de l'attribut. ``Faux.ValueError`` où ``Faux`` déclare
    ``ValueError = object`` désigne ``object`` : accepter l'attribut sur son seul
    nom laissait exempter n'importe quelle classe derrière un porteur inventé en
    deux lignes. Seul un nom que les imports du module lient au module
    ``builtins`` qualifie donc une exception.
    """
    if isinstance(base, ast.Name):
        return base.id in aliases.exceptions_builtins
    return (
        isinstance(base, ast.Attribute)
        and base.attr in _NOMS_EXCEPTIONS_BUILTINS
        and isinstance(base.value, ast.Name)
        and base.value.id in aliases.modules_builtins
    )


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
    portees: _PorteesLexicales,
) -> bool:
    """Détermine si le décorateur vise réellement abc.abstractmethod.

    Le décorateur s'évalue là où la définition est écrite, exactement comme les
    bases d'une classe : un homonyme LOCAL — fonction identité, affectation,
    paramètre — le remplace sans que l'import du module cesse d'exister. Le même
    résolveur de portées tranche donc les deux questions, et un décorateur
    masqué n'exempte plus l'ellipse qu'il décore.
    """
    for decorateur in fonction.decorator_list:
        cible = decorateur.func if isinstance(decorateur, ast.Call) else decorateur
        if isinstance(cible, ast.Name):
            if cible.id in aliases.abstractmethods and not portees.masque(
                cible.id, fonction
            ):
                return True
            continue
        if (
            isinstance(cible, ast.Attribute)
            and isinstance(cible.value, ast.Name)
            and cible.value.id in aliases.modules_abc
            and cible.attr == "abstractmethod"
            and not portees.masque(cible.value.id, fonction)
        ):
            return True
    return False


def _est_exception_non_implementee(noeud: ast.expr, aliases: _AliasesImports) -> bool:
    """Reconnaît l'absence d'implémentation sous ses formes simple, appelée, importée et qualifiée.

    La sentinelle et l'exception sont traitées à égalité : une forme qualifiée par
    attribut, telle qu'un accès via le module builtins, reste un stub explicite.

    Sous la forme qualifiée, c'est le PORTEUR qui décide, jamais l'orthographe de
    l'attribut — exactement l'exigence de ``_est_base_exception_builtin``, dont
    cette règle divergeait. MESURÉ avant correction : la levée de l'attribut
    HOMONYME porté par un module métier — ``raise mon_module.<le nom de
    l'exception>`` — était refusée, alors qu'un module est libre de nommer ainsi
    son propre type d'erreur, qui n'a rien d'un stub. Seul un nom que les imports
    lient au module ``builtins`` qualifie donc l'absence d'implémentation de
    l'interpréteur.

    La forme NUE ne dépend d'aucun porteur et reste le cas principal : elle est
    reconnue par la liste des noms de l'interpréteur, sans qu'aucun import ait à
    la prouver.
    """  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
    cible = noeud.func if isinstance(noeud, ast.Call) else noeud
    if isinstance(cible, ast.Name):
        return (
            cible.id in _NOMS_ABSENCE_IMPLEMENTATION
            or cible.id in aliases.not_implemented_errors
        )
    return _attribut_absence_de_builtins(cible, aliases.modules_builtins)


def _attribut_absence_de_builtins(
    cible: ast.expr, modules_builtins: AbstractSet[str]
) -> bool:
    """Prouve qu'un ATTRIBUT désigne l'absence d'implémentation de l'interpréteur.

    Un seul endroit répond à la question pour les deux chemins qui la posent —
    la levée directe et l'alias construit par affectation — afin qu'ils ne
    puissent plus diverger comme ils l'avaient fait.
    """  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet
    return (
        isinstance(cible, ast.Attribute)
        and cible.attr in _NOMS_ABSENCE_IMPLEMENTATION
        and isinstance(cible.value, ast.Name)
        and cible.value.id in modules_builtins
    )


def _leve_not_implemented(
    fonction: ast.FunctionDef | ast.AsyncFunctionDef,
    visibles: _AliasesVisibles,
) -> bool:
    """Recherche une levée explicite d'absence d'implémentation dans la fonction.

    Chaque levée est jugée avec les alias visibles LÀ OÙ ELLE EST ÉCRITE, et non
    avec ceux du module : le parcours descend dans les fonctions imbriquées, dont
    la portée peut prouver un alias que la fonction extérieure ignore.
    """
    return any(
        isinstance(noeud, ast.Raise)
        and noeud.exc is not None
        and _est_exception_non_implementee(noeud.exc, visibles.au(noeud))
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
    visibles: _AliasesVisibles,
    portees: _PorteesLexicales,
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
        dans_protocol
        or _est_methode_abstraite(fonction, visibles.au(fonction), portees)
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

    if _leve_not_implemented(fonction, visibles):
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
    exceptions: frozenset[tuple[int, int]],
    est_protocol: bool,
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
    n'annonce aucune implémentation. Elle est de plus attachée à la DÉFINITION
    exempte, repérée par sa position, et non à son nom : une classe d'une autre
    portée qui reprend le nom d'un type d'exception du module n'hérite de rien
    et reste jugée sur son propre en-tête.

    Un PROTOCOLE prouvé dont le corps entier est une ellipse est exempté lui
    aussi : ``class Depot(Protocol): ...`` déclare une interface, exactement
    comme l'ellipse acceptée méthode par méthode juste au-dessous. L'exemption
    s'arrête là où celle des méthodes s'arrête — ``pass`` ne déclare rien, et un
    homonyme local de ``Protocol`` ne prouve aucune origine.
    """
    if (classe.lineno, classe.col_offset) in exceptions:
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
    if est_ellipse_unique and est_protocol:
        return []

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
    visibles: _AliasesVisibles,
) -> list[Violation]:
    """Refuse une absence d'implémentation levée hors de toute fonction.

    Un module ou une classe qui lève cette exception échoue À L'IMPORT, et échoue
    précisément parce que le code n'est pas écrit : c'est le stub le plus visible
    qui soit, et il échappait entièrement au parcours limité aux fonctions.

    Un corps de CLASSE est une portée à part entière : la levée y est jugée avec
    les alias que cette classe rend visibles, comme n'importe quel autre nœud.
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
        and _est_exception_non_implementee(noeud.exc, visibles.au(noeud))
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
    portees = _PorteesLexicales(arbre)
    visibles = _AliasesVisibles(aliases, portees)
    exceptions = _positions_de_classes_derivees(
        arbre,
        lambda base, classe: _est_base_exception_builtin(base, visibles.au(classe)),
        portees,
    )
    violations: list[Violation] = []

    class Visiteur(ast.NodeVisitor):
        """Visite chaque définition sans perdre le contexte de sa classe parente."""

        def __init__(self) -> None:
            self.protocols: list[bool] = [False]

        def visit_ClassDef(self, noeud: ast.ClassDef) -> None:
            est_protocol = _est_classe_protocol(noeud, visibles.au(noeud), portees)
            violations.extend(
                _analyser_classe(repo, fichier, noeud, exceptions, est_protocol)
            )
            self.protocols.append(est_protocol)
            self.generic_visit(noeud)
            self.protocols.pop()

        def visit_FunctionDef(self, noeud: ast.FunctionDef) -> None:
            violations.extend(
                _analyser_fonction(
                    repo, fichier, noeud, self.protocols[-1], visibles, portees
                )
            )
            self.protocols.append(False)
            self.generic_visit(noeud)
            self.protocols.pop()

        def visit_AsyncFunctionDef(self, noeud: ast.AsyncFunctionDef) -> None:
            violations.extend(
                _analyser_fonction(
                    repo, fichier, noeud, self.protocols[-1], visibles, portees
                )
            )
            self.protocols.append(False)
            self.generic_visit(noeud)
            self.protocols.pop()

    Visiteur().visit(arbre)
    violations.extend(_analyser_absences_hors_fonction(repo, fichier, arbre, visibles))
    violations.extend(_analyser_lambdas(repo, fichier, arbre))
    return violations


def _est_fichier_production(fichier: Path) -> bool:
    """Exclut les fichiers de test de la règle réservée aux modules de production."""
    return not (fichier.name.startswith("test_") or fichier.name.endswith("_test.py"))


def _est_vide_autorise(fichier: Path) -> bool:
    """Reconnaît les deux exceptions explicites aux modules Python vides."""
    return fichier.name in {"__init__.py", ".gitkeep"}


def _valider_base_ref(base_ref: str) -> str:
    """Refuse une pseudo-référence Git ambiguë avant toute frontière subprocess."""
    if _BASE_REF_GIT_AUTORISEE.fullmatch(base_ref) is None:
        raise ValueError("--base-ref invalide")
    return base_ref


def _lignes_du_diff(repo: Path, fichier: Path, base_ref: str, contenu: str) -> set[int]:
    """Retourne les lignes ajoutées par Git, avec repli fermé pour non suivis."""
    base_ref = _valider_base_ref(base_ref)
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


def _noms_oracle_direct(attribut: str, aliases: _AliasesImports) -> frozenset[str]:
    """Rend les noms NUS que les imports du module lient à l'oracle pytest visé.

    La correspondance est faite attribut par attribut, jamais par un ensemble
    commun, parce que la POSITION compte : ``raises`` ne prouve un oracle qu'en
    gestionnaire de contexte, ``fail`` qu'en appel. Les confondre accepterait un
    ``raises(ValueError)`` nu, qui n'entre jamais dans le gestionnaire et ne
    vérifie donc rien — c'est exactement l'asymétrie que la forme qualifiée
    respecte déjà.
    """
    if attribut == "raises":
        return aliases.oracles_raises
    if attribut == "fail":
        return aliases.oracles_fail
    return frozenset()


def _est_appel_pytest(
    noeud: ast.Call,
    attribut: str,
    aliases: _AliasesImports,
) -> bool:
    """Reconnaît ``pytest.<attribut>`` sous le nom canonique, ses alias et son import direct.

    L'origine est prouvée par les imports déjà résolus du module, le même
    mécanisme que la détection des sauts : renommer ``pytest`` à l'import ne
    change rien à ce que l'oracle vérifie, et refuser un test légitime pousse à
    désarmer le gate. La qualification est conservée en sens inverse : un
    homonyme métier — ``mon_module.raises(...)`` — ne prouve toujours aucun
    oracle.

    Le nom NU importé directement — ``from pytest import raises`` puis ``with
    raises(...)`` — est reconnu au même titre. MESURÉ avant correction : cet
    idiome courant recevait ``TEST_WITHOUT_ORACLE`` alors que le gate traçait
    DÉJÀ les imports directs de ``skip`` et de ``mark`` pour détecter les sauts.
    Un faux positif sur une forme aussi répandue coûte autant qu'un angle mort :
    il se paie du désarmement du gate par ceux qu'il gêne. La preuve d'origine
    est identique à celle des sauts — ``from mon_module import raises`` ne
    prouve rien, et une réaffectation du nom détruit la preuve.
    """
    cible = noeud.func
    if isinstance(cible, ast.Name):
        return cible.id in _noms_oracle_direct(attribut, aliases)
    if not (isinstance(cible, ast.Attribute) and cible.attr == attribut):
        return False
    porteur = cible.value
    return isinstance(porteur, ast.Name) and (
        porteur.id == "pytest" or porteur.id in aliases.modules_pytest
    )


def _receveurs_de_cas_de_test(
    arbre: ast.Module,
    visibles: _AliasesVisibles,
    portees: _PorteesLexicales,
) -> dict[ast.stmt, str]:
    """Associe chaque méthode d'un cas de test ``unittest`` au nom de son receveur.

    Le receveur est le PREMIER paramètre de la méthode — ``self`` par convention,
    mais librement renommable : c'est lui, et lui seul, qui porte les oracles
    hérités d'``unittest.TestCase``. Une méthode sans paramètre, telle une
    ``staticmethod``, n'a aucun receveur et n'est donc pas recensée.

    L'origine de la base est prouvée dans la portée de la CLASSE : ``from
    unittest import TestCase`` écrit dans une fonction y déclare un cas de test
    aussi réellement qu'au niveau module, et l'ignorer signalait comme dépourvues
    d'oracle des méthodes qui en portent un.
    """
    cas_de_test = _positions_de_classes_derivees(
        arbre,
        lambda base, classe: _est_base_test_case(base, visibles.au(classe)),
        portees,
    )
    receveurs: dict[ast.stmt, str] = {}
    for noeud in ast.walk(arbre):
        if not (
            isinstance(noeud, ast.ClassDef)
            and (noeud.lineno, noeud.col_offset) in cas_de_test
        ):
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
    visibles: _AliasesVisibles,
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

    ``raises`` n'est lu qu'en tête d'un ``with`` et ``fail`` qu'en appel, sous la
    forme qualifiée comme sous la forme importée directement. Cette asymétrie est
    celle de l'exécution : un ``raises(...)`` hors ``with`` n'entre jamais dans le
    gestionnaire de contexte et ne vérifie donc rien.

    La recherche se limite à la portée PROPRE du test. MESURÉ avant correction :
    ``def test_x(): def oracle(): assert False`` — la fonction interne n'étant
    JAMAIS appelée — passait le contrôle, alors que rien n'était vérifié à
    l'exécution. Le parcours réutilise ``_noeuds_de_la_portee``, déjà employé
    pour les liaisons ``global`` : écrire un second parcours ferait deux règles
    de portée à maintenir, donc deux occasions de diverger.

    Un bloc n'ouvre AUCUNE portée et n'est jamais écarté : l'oracle d'une boucle,
    d'une condition, d'un gestionnaire de contexte, d'un ``try`` ou d'un ``match``
    appartient au corps du test et compte comme lui. Seules fonctions, lambdas et
    classes imbriquées le sont, parce qu'elles déportent leur contenu dans une
    exécution qui n'a pas lieu.

    L'origine de l'oracle est prouvée avec les alias visibles DANS le test :
    ``from pytest import raises`` écrit à sa première ligne prouve autant que le
    même import au niveau module, et l'ignorer signalait comme dépourvu d'oracle
    un test qui vérifie réellement une levée.
    """
    for noeud in _noeuds_de_la_portee(fonction):
        if isinstance(noeud, ast.Assert):
            return True
        if isinstance(noeud, ast.With) and any(
            isinstance(element.context_expr, ast.Call)
            and _est_appel_pytest(
                element.context_expr, "raises", visibles.au(noeud)
            )
            for element in noeud.items
        ):
            return True
        if isinstance(noeud, ast.Call) and (
            _est_appel_pytest(noeud, "fail", visibles.au(noeud))
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
    """Applique les règles AST limitées aux éléments effectivement modifiés.

    Les alias sont résolus PAR PORTÉE : un import écrit dans une fonction y lie
    un alias réel, et un saut appelé sous cet alias saute aussi sûrement que
    sous celui du module.
    """
    portees = _PorteesLexicales(arbre)
    visibles = _AliasesVisibles(_analyser_imports(arbre), portees)
    receveurs = _receveurs_de_cas_de_test(arbre, visibles, portees)
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
                if not _contient_oracle(noeud, visibles, receveurs.get(noeud)):
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
                # Le décorateur s'évalue là où la DÉFINITION est écrite, jamais
                # dans son corps : c'est donc la définition, et non le
                # décorateur, qui donne la portée où résoudre son nom.
                if decorateur.lineno in lignes and _est_decorateur_skip_ou_xfail(
                    decorateur, visibles.au(noeud)
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
            if _est_appel_de_saut(noeud, visibles.au(noeud)):
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


_CLES_CONTRACTUELLES_RACINES: Final[frozenset[str]] = frozenset({"python_roots"})


def _cle_contractuelle_lue(noeud: ast.expr) -> str | None:
    """Rend la clé LITTÉRALE du contrat que cette expression demande, sinon rien.

    Deux formes d'accès sont retenues, et ce sont les seules que le dépôt écrit
    réellement : l'indexation ``contrat["python_roots"]`` et l'appel qui prend la
    clé en premier argument — ``contrat.get("python_roots")`` avec ou sans
    valeur par défaut, forme employée par les trois lanceurs
    ``run_security_scan``, ``run_pack_validation`` et ``run_codeql_scan``. Le
    déballage ``[*contrat.get("python_roots")]`` n'a besoin d'aucune règle
    propre : l'accès qu'il enveloppe est retrouvé par le parcours de
    l'expression, qui descend jusqu'à lui.

    Le premier argument suffit, et le nom de l'APPELÉ est délibérément ignoré :
    c'est la clé demandée qui porte le sens, jamais l'orthographe de la méthode
    d'accès. Une tranche — ``[:1]``, ``[1:]`` — n'est pas une clé littérale : la
    troncature n'est donc jamais prise pour la lecture qu'elle réduit.
    """
    if isinstance(noeud, ast.Subscript):
        index = noeud.slice
        return index.value if isinstance(index, ast.Constant) and isinstance(index.value, str) else None
    if isinstance(noeud, ast.Call) and noeud.args:
        premier = noeud.args[0]
        return premier.value if isinstance(premier, ast.Constant) and isinstance(premier.value, str) else None
    return None


def _est_source_de_racines(noeud: ast.expr) -> bool:
    """Prouve qu'une expression REND les racines contractuelles telles quelles.

    Trois formes le prouvent : le nom consacré de la collection de racines,
    l'appel dont le nom annonce leur chargement, et la LECTURE du champ du
    contrat ``core/quality-scopes.toml`` qui les déclare. Une telle expression
    est décidable par DÉLÉGATION au contrat — c'est la forme attendue d'un
    lanceur — même si sa valeur n'est pas lisible dans le fichier.

    La troisième forme manquait, et l'angle mort était MESURÉ : dans un lanceur,
    ``contrat.get("python_roots")[:1]`` tronquait le périmètre sans être
    signalé, quand le témoin ``charger_racines_qualite()[:1]`` l'était. La
    reconnaissance s'appuyait sur le nom de l'appelé — ``get`` pour un accès au
    contrat, qui ne contient ni « racine » ni « root ». Le porteur de sens est
    la CLÉ demandée, seule à nommer le champ contractuel des racines.
    """
    if _cle_contractuelle_lue(noeud) in _CLES_CONTRACTUELLES_RACINES:
        return True
    if isinstance(noeud, ast.Name):
        return noeud.id in _NOMS_ITERABLES_RACINES
    if isinstance(noeud, ast.Call):
        nom = _nom_identifiant(noeud.func).lower()
        return "racine" in nom or "root" in nom
    return False


def _itere_sur_les_racines(generateur: ast.comprehension) -> bool:
    """Indique si la compréhension parcourt bien les racines contractuelles."""
    return _est_source_de_racines(generateur.iter)


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


def _perimetre_derive_des_racines_indecidable(noeud: ast.expr) -> bool:
    """Prouve qu'un périmètre TRANSFORME les racines sans valeur décidable.

    Le contrôle des omissions ne sait lire que les collections littérales : toute
    autre valeur le rendait muet. Or retirer des racines ne demande alors qu'une
    transformation opaque de leur source — ``charger_racines()[:1]``,
    ``list(racines)[:1]`` — qui réduit le périmètre d'un contrôle requis sans
    qu'aucune règle ne s'applique. Le critère retenu est l'INDÉCIDABILITÉ, jamais
    la forme du wrapper : déplier ``list(…)`` puis ``sorted(…)`` puis le suivant
    serait une course sans fin, et chaque forme oubliée un trou.

    Trois exclusions bornent la règle à ce qu'elle sait juger :
    — la source elle-même, décidable par délégation au contrat ;
    — les compréhensions sur les racines, qui ont leurs juges dédiés (exclusion
      littérale, filtre indécidable) et seraient sinon condamnées deux fois ;
    — les valeurs littérales, déjà jugées par la règle des omissions.

    Le rôle est prouvé DEUX fois : par le contexte de déclaration (l'appelant)
    et par la présence de la source des racines dans l'expression. MESURÉ sur ce
    dépôt : le seul contexte de déclaration retient 16 expressions légitimes des
    lanceurs — chemins du dépôt, lectures du contrat, lignes de commande — que
    juger produirait autant de faux positifs, soit la pression exacte qui fait
    désarmer un gate.
    """
    if _valeurs_litterales(noeud) is not None:
        return False
    if _est_source_de_racines(noeud):
        return False
    if any(
        isinstance(interne, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp))
        and any(_itere_sur_les_racines(gen) for gen in interne.generators)
        for interne in ast.walk(noeud)
    ):
        return False
    return any(
        isinstance(interne, ast.expr) and _est_source_de_racines(interne)
        for interne in ast.walk(noeud)
    )


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
        if noeud in declarations and _perimetre_derive_des_racines_indecidable(noeud):
            violations.append(
                _violation(
                    "SCOPE_FILTRE_INDECIDABLE",
                    repo,
                    fichier,
                    noeud.lineno,
                    "le périmètre dérive des racines contractuelles sans valeur "
                    "décidable statiquement ; il doit être rendu littéral ou justifié",
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

    L'ANTISLASH est lu selon les trois règles du shell, mesurées avant d'être
    codées, car elles diffèrent d'un contexte à l'autre :

    * HORS quotes, il rend littéral le caractère suivant. MESURÉ dans bash :
      ``python3 -c 'import sys; sys.exit(1)' \\" || true`` sort en 0, le repli
      s'appliquant bel et bien. Ne pas le traiter faisait lire ce guillemet comme
      l'OUVERTURE d'une chaîne, qui effaçait tout ce qui suivait — le repli
      devenait invisible et l'étape d'un job requis restait verte sur un contrôle
      rouge. Les deux caractères sont donc neutralisés ENSEMBLE : ils ne portent
      aucune syntaxe.
    * Entre quotes SIMPLES, il n'échappe RIEN. MESURÉ à l'interpréteur :
      ``printf '%s' '\\"'`` écrit deux octets, ``5c 22``. La quote qui suit ferme
      donc réellement la chaîne, et le repli écrit après elle s'exécute.
    * Entre guillemets DOUBLES, il échappe ``"``, ``\\``, ``$`` et ``` ` ```.
      Devant tout autre caractère il reste littéral, mais la distinction est sans
      effet observable ici : l'intérieur d'une chaîne est neutralisé de toute
      façon, et la seule position qui compte — celle du guillemet fermant — est
      la même dans les deux lectures.

    La longueur et les retours à la ligne sont conservés dans les trois cas, ce
    dont dépendent les index rendus à l'appelant pour retrouver le texte
    d'origine.
    """
    neutre: list[str] = []
    i = 0
    n = len(commande)
    while i < n:
        caractere = commande[i]
        if caractere == "\\" and i + 1 < n:
            suivant = commande[i + 1]
            neutre.append(" ")
            neutre.append("\n" if suivant == "\n" else " ")
            i += 2
            continue
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


def _bornes_utiles(neutre: str, debut: int, fin: int) -> tuple[int, int]:
    """Resserre un intervalle sur son texte utile, séparateurs de bordure exclus.

    Les espaces, retours à la ligne et ``;`` qui encadrent une commande ne font
    pas partie d'elle : les laisser fausserait la lecture du premier caractère,
    seul à distinguer un groupe d'une commande simple.
    """
    borne = " \t\r\n;"
    while debut < fin and neutre[debut] in borne:
        debut += 1
    while fin > debut and neutre[fin - 1] in borne:
        fin -= 1
    return debut, fin


def _ancre_de_composee(debut: int) -> int:
    """Recule d'un caractère pour que le mot ``if``/``case`` reste reconnaissable.

    Les jetons de conditionnelle ne comptent qu'en POSITION DE COMMANDE, donc
    précédés d'un séparateur. Lancer la lecture exactement sur le mot-clé le
    rendait invisible : la profondeur restait nulle, la conditionnelle passait
    pour non ouverte, et ses branches n'étaient jamais isolées. MESURÉ : un
    ``|| if true; then exit 1; fi`` pourtant propageant était refusé.
    """
    return max(debut - 1, 0)


def _increments_de_profondeur(neutre: str, debut: int, fin: int) -> dict[int, int]:
    """Situe les mots qui ouvrent et referment une conditionnelle dans un intervalle.

    L'ouverture est comptée sur le MOT ``if``/``case`` et la fermeture APRÈS le
    mot ``fi``/``esac``, jamais sur le séparateur qui les précède : compter sur
    le séparateur ferait sortir de la conditionnelle un ``;`` qui lui appartient
    encore, et découperait la commande au mauvais endroit.
    """
    increments: dict[int, int] = {}
    for jeton in _JETONS_CONDITIONNELLES.finditer(neutre, _ancre_de_composee(debut)):
        if jeton.start() >= fin:
            break
        if jeton.group("ouvre") is not None:
            position, delta = jeton.start("mot_ouvre"), 1
        elif jeton.group("ferme") is not None:
            position, delta = jeton.end("ferme"), -1
        else:
            continue
        increments[position] = increments.get(position, 0) + delta
    return increments


def _etendue_derniere_commande(neutre: str, debut: int, fin: int) -> tuple[int, int]:
    """Isole la dernière commande d'une suite, groupes et composés traversés entiers.

    Seule cette commande fixe le code de retour de la suite. Le découpage ne
    retient ``;``, le retour à la ligne et ``&&`` qu'au niveau ZÉRO : à
    l'intérieur d'un ``{ … }`` ou d'un ``if … fi`` ces caractères séparent des
    commandes INTERNES, et couper là ferait du mot ``fi`` la dernière commande
    d'un groupe qui se termine pourtant par une conditionnelle propageante.

    Les deux niveaux sont comptés SÉPARÉMENT, et celui des parenthèses ne
    descend jamais sous zéro : un motif de ``case`` s'écrit ``*)`` sans
    parenthèse ouvrante, si bien qu'un compteur unique passait en négatif et
    faisait du mot ``esac`` la dernière commande du filtrage.
    """
    increments = _increments_de_profondeur(neutre, debut, fin)
    composee = 0
    groupe = 0
    depart = debut
    index = debut
    while index < fin:
        composee += increments.get(index, 0)
        caractere = neutre[index]
        if caractere in _OUVERTURES_DE_GROUPE_SHELL:
            groupe += 1
        elif caractere in _FERMETURES_DE_GROUPE_SHELL:
            groupe = max(0, groupe - 1)
        elif composee <= 0 and groupe <= 0:
            if caractere in _SEPARATEURS_SIMPLES_SHELL:
                depart = index + 1
            elif neutre.startswith(_ENCHAINEMENT_ET_SHELL, index):
                depart = index + len(_ENCHAINEMENT_ET_SHELL)
        index += 1
    return _bornes_utiles(neutre, depart, fin)


def _shell_inline_propage(
    original: str, neutre: str, debut: int, fin: int, profondeur: int
) -> bool:
    """Prouve la propagation d'un ``sh -c '…'`` en relisant le script réellement exécuté.

    Le script vit dans une chaîne, donc effacé du texte neutralisé : il est relu
    à la MÊME position dans le texte d'origine, la neutralisation conservant les
    positions. Sans cette relecture, un repli ``sh -c 'exit 1'`` parfaitement
    propageant serait refusé faute de pouvoir être lu.
    """
    correspondance = _SHELL_INLINE_EN_TETE.match(neutre, debut, fin)
    if correspondance is None:
        return False
    ouverture, fermeture = correspondance.span("script")
    if (
        fermeture - ouverture >= 2
        and original[ouverture] in {"'", '"'}
        and original[fermeture - 1] == original[ouverture]
    ):
        ouverture, fermeture = ouverture + 1, fermeture - 1
    script = original[ouverture:fermeture]
    return _branche_propage_lechec(
        script,
        _neutraliser_chaines_shell(script),
        0,
        len(script),
        profondeur - 1,
    )


def _sortie_litterale_est_nulle(code: str) -> bool:
    """Décide si un littéral d'``exit``/``return`` rend un statut NUL. Prédicat UNIQUE.

    Les deux chemins qui jugent une sortie — la sortie NUE d'une étape et la
    branche de REPLI d'un ``||`` — consomment ce prédicat, et c'est tout l'objet
    de la fonction. MESURÉ avant unification : ``gate.py || exit 00`` était
    refusé quand ``gate.py; exit 00`` passait, le repli lisant la VALEUR pendant
    que le chemin direct exigeait l'orthographe exacte ``0``. La même question
    recevait deux réponses, et la classe entière des orthographes du zéro
    (``exit 000``, ``exit 256``, ``exit 0512``) restait disponible d'un côté.

    Le critère est celui du shell, MESURÉ dans bash, dash et sh : le statut rendu
    est le littéral modulo 256, si bien que ``exit 256`` et ``exit 0512`` valent
    ``exit 0``. Ce que chaque appelant FAIT du verdict diffère à dessein — la
    sortie nue est signalée quand elle est nulle, la branche de repli n'est
    admise que lorsqu'elle ne l'est pas — mais la valeur, elle, ne se juge plus
    qu'ici.
    """
    return int(code) % _MODULO_CODE_DE_SORTIE == 0


def _commande_simple_propage(
    original: str, neutre: str, debut: int, fin: int, profondeur: int
) -> bool:
    """Décide si une commande SIMPLE de repli propage l'échec, par liste blanche.

    Trois formes seulement le prouvent, et elles ont été MESURÉES dans bash, dash
    et sh : ``false`` (1, y compris préfixé d'un chemin ou de ``command``),
    ``exit``/``return`` suivi d'un littéral décimal dont la VALEUR n'est pas nulle
    au sens de ``_sortie_litterale_est_nulle`` — ``exit 00``, ``exit 000`` et
    ``exit 256`` rendent 0 — et le script d'un ``sh -c``. Tout le reste rend un
    statut que rien ne détermine ici : ``env true``, ``nice true``, ``timeout 1
    true`` rendent 0 et l'échec disparaît. Énumérer ces porteurs ne converge pas,
    donc l'inconnu est refusé.
    """
    texte = neutre[debut:fin]
    if _ECHEC_GARANTI_EN_TETE.match(texte) is not None:
        return True
    sortie = _SORTIE_NON_NULLE.match(texte)
    if sortie is not None:
        return not _sortie_litterale_est_nulle(sortie.group("code"))
    return _shell_inline_propage(original, neutre, debut, fin, profondeur)


def _branche_propage_lechec(
    original: str, neutre: str, debut: int, fin: int, profondeur: int
) -> bool:
    """Prouve qu'une branche de repli rend l'échec au job requis — liste BLANCHE.

    La question est posée à l'envers de l'ancienne règle : au lieu de chercher
    les formes qui absorbent, on exige que la branche DÉMONTRE sa propagation.
    Un groupe et une conditionnelle sont traversés récursivement — chacune de
    leurs branches exécutables doit propager — et une commande simple est jugée
    sur la liste blanche mesurée. Une branche vide, illisible ou trop profonde ne
    prouve rien : elle est refusée, et c'est le sens même du fail-closed.
    """
    if profondeur <= 0:
        return False
    debut, fin = _etendue_derniere_commande(neutre, *_bornes_utiles(neutre, debut, fin))
    if debut >= fin:
        return False
    if neutre[debut] in _OUVERTURES_DE_GROUPE_SHELL:
        fermeture = min(_fin_de_groupe_shell(neutre, debut), fin)
        return _branche_propage_lechec(
            original, neutre, debut + 1, fermeture, profondeur - 1
        )
    compose = _MOT_COMPOSE_SHELL.match(neutre, debut)
    if compose is not None:
        ancre = _ancre_de_composee(debut)
        fermeture = _fin_de_conditionnelle_shell(neutre, ancre)
        branches = (
            _branches_de_conditionnelle(neutre, ancre, fermeture)
            if compose.group("compose") == _MOT_IF_SHELL
            else _branches_de_filtrage(neutre, debut, fermeture)
        )
        return bool(branches) and all(
            _branche_propage_lechec(
                branche, branche, 0, len(branche), profondeur - 1
            )
            for branche in branches
        )
    return _commande_simple_propage(original, neutre, debut, fin, profondeur)


def _groupe_propage_echec(groupe: str) -> bool:
    """Prouve qu'un corps de repli rend l'échec, par la liste blanche des formes.

    Seules les formes MESURÉES comme propageantes sont admises ; toute autre fin
    — ``exit 0``, un statut hérité, une simple journalisation, une commande dont
    le gate ne sait rien — laisse le corps réussir, donc absorbe l'échec de la
    commande gardée. Le texte reçu est déjà neutralisé par ses appelants : un
    script cité y est effacé, donc non prouvé, donc refusé.
    """
    return _branche_propage_lechec(
        groupe, groupe, 0, len(groupe), _PROFONDEUR_REPLI_MAX
    )


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


def _fin_de_conditionnelle_shell(neutre: str, debut: int) -> int:
    """Retourne l'index du mot qui referme la conditionnelle ouverte à ``debut``.

    Ouvertures et fermetures sont comptées ensemble — ``if``/``case`` d'un côté,
    ``fi``/``esac`` de l'autre — si bien qu'une conditionnelle imbriquée dans une
    branche n'arrête pas le comptage trop tôt. Non refermée, elle s'étend jusqu'à
    la fin de la commande : son contenu reste analysé au lieu d'être abandonné en
    silence, exactement comme pour les groupes.
    """
    profondeur = 0
    for jeton in _JETONS_CONDITIONNELLES.finditer(neutre, debut):
        if jeton.group("ouvre") is not None:
            profondeur += 1
        elif jeton.group("ferme") is not None:
            profondeur -= 1
            if profondeur == 0:
                return jeton.start("ferme")
    return len(neutre)


def _branches_de_conditionnelle(neutre: str, debut: int, fin: int) -> list[str]:
    """Isole les corps de branches d'un ``if`` de repli, conditions exclues.

    Un corps commence après ``then`` ou ``else`` et s'arrête au jeton de même
    niveau qui suit. La condition d'un ``elif`` n'est PAS un corps : elle est
    évaluée, jamais exécutée en repli, et la juger refuserait un repli qui
    propage pourtant l'échec par chacune de ses branches.
    """
    branches: list[str] = []
    profondeur = 0
    ouverture: int | None = None
    for jeton in _JETONS_CONDITIONNELLES.finditer(neutre, debut):
        if jeton.start() >= fin:
            break
        if jeton.group("ouvre") is not None:
            profondeur += 1
            continue
        if jeton.group("ferme") is not None:
            profondeur -= 1
            if profondeur == 0:
                break
            continue
        if profondeur != 1:
            continue
        if ouverture is not None:
            branches.append(neutre[ouverture : jeton.start()])
            ouverture = None
        sinon = jeton.group("sinon")
        if jeton.group("then") is not None or (
            sinon is not None and sinon.strip() == "else"
        ):
            ouverture = jeton.end()
    if ouverture is not None:
        branches.append(neutre[ouverture:fin])
    return branches


def _branches_de_filtrage(neutre: str, debut: int, fin: int) -> list[str]:
    """Isole les corps de motifs d'un ``case`` de repli, motifs exclus.

    Chaque alternative est délimitée par ``;;`` et son corps commence après la
    parenthèse qui referme le motif. Le motif lui-même ne s'exécute pas, il
    filtre : le juger reviendrait à refuser un repli qui propage l'échec.
    """
    return [
        suite
        for alternative in neutre[debut:fin].split(_SEPARATEUR_MOTIF_CASE)
        for _motif, separateur, suite in [alternative.partition(")")]
        if separateur
    ]


def _compose_conditionnel_repli_succes(neutre: str) -> str | None:
    """Détecte un ``|| if … fi`` ou ``|| case … esac`` qui absorbe l'échec requis.

    Une conditionnelle placée derrière ``||`` ne s'exécute que si le contrôle a
    échoué, et son code de retour devient celui de l'étape. Le critère est celui
    des groupes ``|| { … }`` : chaque branche exécutable doit se terminer par une
    sortie non nulle prouvée, faute de quoi le job requis redevient vert avec son
    contrôle rouge. MESURÉ, ``gate.py || if true; then :; fi`` échappait à tous
    les motifs — le ``||`` exempte la gauche, le ``fi`` rend 0, l'étape est
    verte. ``|| if …; then exit 1; fi`` reste au contraire licite : sa branche
    propage.

    Le ``case`` est traité au même critère que le ``if``, et non laissé de côté :
    le gate les tokenise déjà comme la même conditionnelle, si bien que fermer le
    seul ``if`` rendrait le contournement disponible au mot-clé voisin.

    Une conditionnelle SANS aucune branche lisible est refusée : rien ne prouve
    alors qu'un échec en sorte, et l'incertitude se tranche en faveur du contrôle.
    """
    for correspondance in _CONDITIONNELLE_APRES_OU.finditer(neutre):
        debut = correspondance.start()
        fin = _fin_de_conditionnelle_shell(neutre, debut)
        est_si = correspondance.group("mot") == _MOT_IF_SHELL
        branches = (
            _branches_de_conditionnelle(neutre, debut, fin)
            if est_si
            else _branches_de_filtrage(neutre, debut, fin)
        )
        if branches and all(_groupe_propage_echec(branche) for branche in branches):
            continue
        return "if … fi" if est_si else "case … esac"
    return None


def _script_shell_force_le_succes(script: str) -> bool:
    """Décide si un script shell inline se termine forcément avec succès.

    Le critère est celui des replis directs, appliqué à la commande qui FIXE le
    code de retour du script : ``exit 0``, ``true``, ``:``, ``echo`` et
    ``printf`` réussissent toujours, si bien que le job requis redevient vert.
    Toute autre fin — ``exit 1``, ``false``, un outil qui peut échouer — propage
    son statut et reste licite, exactement comme ``|| make rapport``.

    Le script est de plus relu comme une commande à part entière, ce qui traite
    un repli imbriqué (``sh -c 'verif || true'``). La récursion est bornée :
    chaque niveau lit une sous-chaîne strictement plus courte que le précédent.
    """
    if _commande_repli_succes(script) is not None:
        return True
    return _SUCCES_GARANTI_EN_TETE.match(_derniere_commande_shell(script)) is not None


def _repli_shell_inline_succes(commande: str, neutre: str) -> str | None:
    """Détecte un repli ``|| sh -c '…'`` dont le script force le succès de l'étape.

    Cette forme échappait à tous les motifs : la neutralisation des quotes, qui
    protège des replis simplement CITÉS, effaçait aussi le contenu réellement
    exécuté par ``-c``. Les deux besoins sont conciliés en repérant l'appel sur
    le texte NEUTRALISÉ — un ``|| sh -c 'exit 0'`` écrit dans une chaîne y est
    effacé, donc jamais signalé — puis en lisant le script à la même position
    dans le texte d'origine, la neutralisation conservant les positions.

    Les options précédant ``-c`` sont admises, groupées ou non (``sh -ec``),
    car seul compte le fait que l'argument suivant soit le script exécuté.
    """
    for correspondance in _REPLI_SHELL_INLINE.finditer(neutre):
        debut, fin = correspondance.span("script")
        script = commande[debut:fin]
        if len(script) >= 2 and script[0] in {"'", '"'} and script[-1] == script[0]:
            script = script[1:-1]
        if _script_shell_force_le_succes(script):
            return f"{correspondance.group('prefixe')}{correspondance.group('shell')} -c"
    return None


def _etendue_de_branche_apres_ou(neutre: str, apres: int) -> tuple[int, int]:
    """Délimite la branche que le shell exécute quand la commande gardée échoue.

    Trois formes seulement s'étendent au-delà du premier séparateur : le groupe
    ``{ … }`` / ``( … )``, qui court jusqu'à sa fermeture, et la conditionnelle
    ``if``/``case``, qui court jusqu'à son ``fi``/``esac``. Une commande simple
    s'arrête au premier ``;``, retour à la ligne, ``&&`` ou ``||`` : ce qui suit
    est une AUTRE commande, dont le sort ne dit rien de ce repli.
    """
    debut = apres
    while debut < len(neutre) and neutre[debut] in " \t":
        debut += 1
    if debut >= len(neutre):
        return debut, debut
    if neutre[debut] in _OUVERTURES_DE_GROUPE_SHELL:
        return debut, min(_fin_de_groupe_shell(neutre, debut) + 1, len(neutre))
    if _MOT_COMPOSE_SHELL.match(neutre, debut) is not None:
        ferme = _fin_de_conditionnelle_shell(neutre, _ancre_de_composee(debut))
        mot = _MOT_FERMANT_SHELL.search(neutre, ferme)
        return debut, mot.end() if mot is not None else len(neutre)
    fin = _FIN_DE_BRANCHE_SIMPLE.search(neutre, debut)
    return debut, fin.start() if fin is not None else len(neutre)


def _branche_est_terminale(neutre: str, fin: int) -> bool:
    """Vérifie que la branche fixe bien le statut, sans commande enchaînée derrière.

    Un ``|`` derrière la branche en fait un simple MAILLON : c'est le dernier
    élément du tube qui fixe le code de retour, jamais elle. MESURÉ dans bash :
    ``{ exit 1; } | true`` et ``false | true`` rendent 0. Seuls ``;``, le retour
    à la ligne, ``&&``, ``||`` et la fin de l'étape laissent la branche décider ;
    toute autre suite — tube, redirection — n'est pas prouvable et est refusée.
    """
    index = fin
    while index < len(neutre) and neutre[index] in " \t":
        index += 1
    if index >= len(neutre):
        return True
    return (
        neutre[index] in _SEPARATEURS_SIMPLES_SHELL
        or neutre.startswith(_ENCHAINEMENT_ET_SHELL, index)
        or neutre.startswith(_OPERATEUR_OU_TEXTE, index)
    )


def _designer_repli(neutre: str, debut: int, fin: int) -> str:
    """Nomme la branche refusée afin que le message dise QUOI corriger.

    Le nom lu est celui de la FORME quand la branche est composée, et le premier
    mot quand elle est simple : c'est lui que l'auteur du workflow reconnaîtra.
    """
    if debut >= fin:
        return _DESIGNATION_REPLI_VIDE
    if neutre[debut] == "{":
        return _DESIGNATION_REPLI_ACCOLADES
    if neutre[debut] == "(":
        return _DESIGNATION_REPLI_PARENTHESES
    compose = _MOT_COMPOSE_SHELL.match(neutre, debut)
    if compose is not None:
        return (
            _DESIGNATION_REPLI_SI
            if compose.group("compose") == _MOT_IF_SHELL
            else _DESIGNATION_REPLI_FILTRAGE
        )
    mots = neutre[debut:fin].split()
    return mots[0] if mots else _DESIGNATION_REPLI_VIDE


def _repli_non_prouve(commande: str, neutre: str) -> str | None:
    """Refuse tout ``||`` dont la branche ne PROUVE pas qu'elle propage l'échec.

    C'est l'inversion de la règle. Énumérer les formes qui absorbent ne converge
    pas : ``|| exit 00``, ``|| env true``, ``|| nice true``, ``|| timeout 1 true``
    ont tour à tour échappé aux motifs, et la liste des porteurs de commande est
    OUVERTE. La classe entière se ferme en exigeant l'inverse — la branche doit
    démontrer sa propagation — si bien qu'une orthographe inédite est refusée
    d'office au lieu de rouvrir la brèche.
    """
    for correspondance in _OPERATEUR_OU_SHELL.finditer(neutre):
        debut, fin = _etendue_de_branche_apres_ou(neutre, correspondance.end())
        if _branche_est_terminale(neutre, fin) and _branche_propage_lechec(
            commande, neutre, debut, fin, _PROFONDEUR_REPLI_MAX
        ):
            continue
        return _designer_repli(neutre, debut, fin)
    return None


def _commande_repli_succes(commande: str) -> str | None:
    """Prouve qu'une branche ``||`` se termine inconditionnellement avec succès.

    Le nom de la commande est lu APRÈS les préfixes qui ne changent pas ce qui
    s'exécute : un chemin (``/usr/bin/true``, ``/bin/true``) désigne le même
    binaire que son nom nu, et le builtin ``command`` ne fait que le lancer en
    court-circuitant fonctions et alias du shell. La borne de fin de nom survit
    au préfixe : ``/usr/bin/true_story`` reste un exécutable tiers légitime.

    Quatre formes de repli sont éprouvées tour à tour, de la plus simple à la
    plus composée : la commande nue, le script ``sh -c``, le groupe ``{ … }`` et
    la conditionnelle ``if … fi`` / ``case … esac``. Toutes répondent à la même
    question — ce qui s'exécute après l'échec du contrôle propage-t-il cet
    échec ? Elles ne servent plus qu'à NOMMER précisément la forme reconnue : le
    verdict, lui, revient à ``_repli_non_prouve``, qui refuse par défaut toute
    branche dont la propagation n'est pas démontrée.
    """
    neutre = _neutraliser_chaines_shell(commande)
    correspondance = _FALLBACK_SHELL.search(neutre)
    if correspondance is None:
        inline = _repli_shell_inline_succes(commande, neutre)
        if inline is not None:
            return inline
        groupe = _groupe_repli_succes(neutre)
        if groupe is not None:
            return groupe
        compose = _compose_conditionnel_repli_succes(neutre)
        if compose is not None:
            return compose
        return _repli_non_prouve(commande, neutre)
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
    """Distingue les sorties de valeur NULLE nues des branches conditionnelles prouvées.

    Les ouvertures, les fermetures et les sorties sont lues dans leur ORDRE
    d'apparition, y compris plusieurs fois sur une même ligne. Une sortie nulle
    placée après le ``fi`` qui referme la garde s'exécute donc toujours et reste
    un contournement, alors qu'une sortie nulle située entre l'ouverture et la
    fermeture demeure conditionnelle. Les mots-clés ne comptent qu'en position de
    commande, afin qu'une option longue comme ``--if-exists`` ou
    ``--ignore-case`` n'ouvre aucune garde imaginaire.

    Le jeton de sortie capture désormais le littéral ENTIER, et c'est
    ``_sortie_litterale_est_nulle`` — le prédicat que consomme aussi le chemin de
    repli — qui décide. Avant cette unification, le motif exigeait l'orthographe
    exacte ``0`` : MESURÉ, ``gate.py; exit 00`` passait pendant que
    ``gate.py || exit 00`` était refusé. Élargir la CAPTURE sans élargir le
    verdict est ce qui préserve la garde inverse : ``exit 1`` est maintenant
    reconnu comme sortie, puis laissé passer sur sa valeur, et un argument qui
    n'est pas un littéral décimal — ``exit 0x0``, ``exit 1x`` — n'est pas capturé
    du tout, le shell rendant alors 2, donc un échec, jamais un succès forcé.
    """
    profondeur_conditionnelle = 0
    for ligne in _neutraliser_chaines_shell(commande).splitlines() or [commande]:
        for jeton in _JETONS_SHELL.finditer(ligne):
            if jeton.group("ouvre") is not None:
                profondeur_conditionnelle += 1
            elif jeton.group("ferme") is not None:
                profondeur_conditionnelle = max(0, profondeur_conditionnelle - 1)
            elif profondeur_conditionnelle == 0 and _sortie_litterale_est_nulle(
                jeton.group("code")
            ):
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
    premier_then_vu: bool = False
    sinon_vu: bool = False


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
    ``if contrôle; then …`` exécute tout le RESTE de la chaîne — le corps de
    chaque ``elif`` dont la condition est vraie, sinon le ``else``. Une seule
    lecture du texte neutralisé les sert toutes deux, afin qu'aucune ne dérive
    de l'autre. Un contrôle direct SANS ``else`` produit une branche VIDE : c'est
    exactement ce que le shell exécute alors — rien, et le ``fi`` rend 0.

    MESURÉ avant correction : sur un contrôle direct, la seule branche relevée
    était la CONDITION du premier ``elif``, et le corps du ``else`` — le seul
    exécuté quand toutes les conditions échouent — n'était jamais lu. Un ``elif``
    suffisait donc à rendre la garde muette. Une condition n'est PAS une branche :
    seuls les corps ouverts par ``then`` et ``else`` en sont.
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
        if jeton.group("then") is not None:
            _qualifier_cadre_conditionnel(cadre, neutre, jeton)
            if cadre.genre == _GENRE_NEGATION and not cadre.mesuree:
                cadre.debut = jeton.end()
            elif cadre.genre == _GENRE_CONTROLE_DIRECT and cadre.premier_then_vu:
                cadre.debut = jeton.end()
            cadre.premier_then_vu = True
        elif jeton.group("sinon") is not None:
            if jeton.group("sinon").strip() == _MOT_SINON_SHELL:
                cadre.sinon_vu = True
                if cadre.genre == _GENRE_CONTROLE_DIRECT:
                    cadre.debut = jeton.end()
        if jeton.group("ferme") is not None:
            if cadre.genre == _GENRE_CONTROLE_DIRECT and not cadre.sinon_vu:
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


def _chaine_numerique_non_nulle(texte: str) -> bool:
    """Décide si un scalaire QUOTÉ porte un nombre qui tolère les erreurs.

    MESURÉ : ``continue-on-error: '2'`` était accepté quand ``2`` non quoté et
    ``'true'`` étaient refusés — la liste des chaînes vraies est fermée
    (``true``, ``yes``, ``on``, ``y``, ``1``) et ne couvrait aucun autre
    numérique quoté, si bien qu'un caractère de quote suffisait à tolérer les
    erreurs d'un job requis. La valeur est donc lue comme celle d'un entier, et
    non l'orthographe : ``'2'``, ``'-1'`` et ``'1.5'`` tolèrent, ``'0'`` et
    ``'0.0'`` ne tolèrent rien et restent acceptés. Un texte non numérique
    n'appartient pas à cette règle et est laissé aux suivantes.

    Cette lecture ne décide plus de l'ACCEPTATION, seulement du message : la
    décision appartient désormais à ``_chaine_tolere_les_erreurs``, qui refuse
    par défaut. Elle sert à nommer précisément une tolérance chiffrée plutôt que
    de la ranger avec les orthographes quelconques.
    """
    try:
        return float(texte) != 0
    except ValueError:
        return False


def _chaine_tolere_les_erreurs(texte: str) -> bool:
    """Refuse tout scalaire QUOTÉ dont la fausseté n'est pas ÉCRITE.

    La règle est inversée, comme celle des replis shell, et pour la même raison
    MESURÉE : énumérer les orthographes vraies ne converge pas. ``'2'`` avait été
    fermé par une lecture décimale, que ``'0x1'``, ``'0o7'`` et ``'0b1'``
    rouvraient aussitôt — ces bases échouent à la conversion décimale, qui
    retombait silencieusement sur « faux » et acceptait la tolérance. La liste
    des orthographes vraies est OUVERTE ; celle des façons d'écrire la fausseté
    ne l'est pas, si bien que c'est elle qu'il faut énumérer.

    Trois écritures disent la fausseté sans ambiguïté et restent donc acceptées :
    le scalaire VIDE, un mot-clé faux de YAML (``false``, ``no``, ``off``, ``n``)
    et un zéro DÉCIMAL (``0``, ``0.0``, ``-0``). Tout le reste tolère, y compris
    ``'0x0'`` : une base non décimale n'est la façon d'écrire « aucune tolérance »
    de personne, et l'incertitude se tranche en faveur du contrôle.

    Le scalaire fait de blancs seuls n'est pas le scalaire VIDE et n'écrit aucune
    fausseté : il est refusé, la comparaison n'étant faite qu'après avoir écarté
    la chaîne réellement vide.

    Cette lecture est plus stricte que la sémantique nominale de YAML et le
    doit : d'après le contrat GitHub Actions rappelé au mandat de cette
    correction — non exécutable ici, donc rapporté comme tel — toute chaîne non
    vide y est convertie en vrai. Accepter les quatre mots-clés et le zéro
    décimal est une concession assumée à l'INTENTION, qu'ils écrivent sans
    équivoque, et aux cas déjà couverts par la suite de tests.
    """
    if texte == "":
        return False
    normalisee = texte.strip().lower()
    if normalisee in _VALEURS_FAUSSES_YAML:
        return False
    try:
        return float(normalisee) != 0
    except ValueError:
        return True


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

    La même lecture par la valeur s'applique aux scalaires QUOTÉS, et elle est
    placée APRÈS la liste des chaînes vraies afin que ``'1'``, déjà couvert par
    elle, garde son message d'origine. MESURÉ avant correction : ``'2'`` était
    accepté quand ``2`` était refusé — la quote seule désarmait la règle.

    La DERNIÈRE branche renverse la charge de la preuve pour tout scalaire quoté
    restant : ``_chaine_tolere_les_erreurs`` refuse celui dont la fausseté n'est
    pas écrite. Les branches numériques la précèdent afin de garder leur message
    chiffré, plus précis ; elles ne décident plus seules de l'acceptation, ce qui
    ferme la classe entière au lieu d'en fermer une orthographe à la fois.
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
    elif isinstance(valeur, str) and _chaine_numerique_non_nulle(valeur.strip()):
        detail = (
            f"le job requis {job} accepte les erreurs "
            f"par la valeur numérique {valeur!r}"
        )
    elif isinstance(valeur, str) and _chaine_tolere_les_erreurs(valeur):
        detail = (
            f"le job requis {job} accepte les erreurs par la chaîne {valeur!r}, "
            "dont la fausseté n'est pas écrite : seuls le scalaire vide, "
            "false, no, off, n et un zéro décimal ne tolèrent rien"
        )
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


def _condition_requise_acceptee(valeur: object, *, depend_de_jobs: bool) -> bool:
    """Accepte les seules conditions dont la VÉRITÉ est garantie dans le contexte donné.

    ``always()`` vaut vrai en toutes circonstances, y compris quand une
    dépendance déclarée par ``needs`` a échoué ou a été sautée : le job requis
    s'exécute, et la condition ne peut donc jamais le neutraliser.

    ``success()`` n'a cette garantie que SANS ``needs``. Dès qu'une dépendance
    est déclarée, GitHub Actions évalue le statut de cette dépendance : un job
    dont on dépend qui est sauté — ce qu'une simple condition fausse sur un job
    NON requis suffit à provoquer — ou qui échoue rend ``success()`` faux, et le
    job requis est alors sauté. La protection de branche est satisfaite sans
    qu'aucun contrôle ait tourné.
    """
    if not isinstance(valeur, str):
        return False
    condition = valeur.strip()
    if condition.startswith("${{") and condition.endswith("}}"):
        condition = condition[3:-2].strip()
    acceptees = (
        _CONDITIONS_REQUISES_MALGRE_NEEDS
        if depend_de_jobs
        else _CONDITIONS_REQUISES_ACCEPTEES
    )
    return condition.lower() in acceptees


def _job_depend_dautres_jobs(definition: Mapping[object, object]) -> bool:
    """Détecte la PRÉSENCE d'un ``needs``, sans juger ce qu'il contient.

    La forme d'un ``needs`` varie — chaîne unique, liste, valeur dynamique — et
    une déclaration illisible n'apporte aucune garantie. Retenir la seule
    présence de la clé est donc fail-closed : au pire, un ``needs`` dégénéré et
    sans dépendance réelle oblige à écrire ``always()``, qui exécute le contrôle.
    """
    return "needs" in definition


def _analyser_condition_requise(
    repo: Path,
    fichier: Path,
    valeur: object,
    job: str,
    *,
    depend_de_jobs: bool = False,
) -> list[Violation]:
    """Refuse les conditions qui peuvent neutraliser un job requis ou une étape requise.

    Le défaut est ``depend_de_jobs=False`` parce que les ÉTAPES, seules autres
    porteuses d'un ``if``, n'ont pas de ``needs`` : leur ``success()`` ne dépend
    que des étapes précédentes du même job, dont l'échec rend le job — donc le
    contrôle requis — rouge. Aucun saut silencieux n'y est possible.
    """
    if valeur is None or _condition_requise_acceptee(
        valeur, depend_de_jobs=depend_de_jobs
    ):
        return []
    detail = (
        f"le job requis {job} porte un needs et une condition que l'échec ou le "
        f"saut d'une dépendance rend fausse : {valeur!r}"
        if depend_de_jobs
        else f"le job requis {job} dépend d'une condition non garantie : {valeur!r}"
    )
    return [
        _violation(
            "REQUIRED_JOB_CONDITIONNEL",
            repo,
            fichier,
            1,
            detail,
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

    La CLÉ ne suffit pourtant pas, et c'est MESURÉ : ``run: ''`` et ``run:
    '   '`` satisfaisaient l'exigence d'étape effective alors qu'une commande
    vide ou blanche ne lance rien — le job requis rapportait vert sans exécuter
    le moindre contrôle, exactement le gate désarmé que la règle vise. La VALEUR
    est donc lue, au même titre pour ``uses``, dont la référence vide ne désigne
    aucune action.

    Une valeur NON-CHAÎNE ne compte pas non plus, en fail-closed : l'analyse des
    commandes ignore déjà tout ``run`` qui n'est pas une chaîne, si bien que la
    compter comme effective laisserait un job requis satisfaire l'exigence avec
    une valeur qu'aucune règle du gate ne sait lire.
    """
    if not isinstance(etape, Mapping):
        return False
    for champ in _CHAMPS_ETAPE_EFFECTIVE:
        valeur = etape.get(champ)
        if isinstance(valeur, str) and valeur.strip():
            return True
    return False


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

        violations.extend(
            _analyser_condition_requise(
                repo,
                fichier,
                definition.get("if"),
                identifiant,
                depend_de_jobs=_job_depend_dautres_jobs(definition),
            )
        )
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
    parser.add_argument("--base-ref", type=_valider_base_ref, default="HEAD")
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
