"""Gate de qualité refusant les stubs et les régressions de qualité ajoutées."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tokenize
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
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
_SUPPRESSION_MARKERS: Final[tuple[str, ...]] = ("type: ignore", "noqa", "nosec")
_IDENTIFIANT_REGLE_OPTIONNEL: Final[re.Pattern[str]] = re.compile(
    r"(?:[A-Za-z]+[0-9][A-Za-z0-9_-]*|\[[A-Za-z0-9_.-]+\]|[A-Za-z][A-Za-z0-9_.-]*)"
)
_EXIT_ZERO: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[;|&()\s])exit\s+0(?=$|[^A-Za-z0-9_])"
)
_IF_SHELL: Final[re.Pattern[str]] = re.compile(r"^\s*if\b.*\bthen\s*$")
_CASE_SHELL: Final[re.Pattern[str]] = re.compile(r"^\s*case\b.*\bin\s*$")
_FIN_IF_SHELL: Final[re.Pattern[str]] = re.compile(r"^\s*fi\s*;?\s*$")
_FIN_CASE_SHELL: Final[re.Pattern[str]] = re.compile(r"^\s*esac\s*;?\s*$")
_MAX_ACTION_DEPTH: Final[int] = 5
_VALEURS_VRAIES_YAML: Final[frozenset[str]] = frozenset(
    {"true", "yes", "on", "y", "1"}
)
_CONDITIONS_REQUISES_ACCEPTEES: Final[frozenset[str]] = frozenset(
    {"always()", "success()"}
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


def _noms_cibles_affectation(noeud: ast.stmt) -> set[str]:
    """Extrait les noms réaffectés directement au niveau module, forme exploitable simple."""
    cibles: list[ast.expr] = []
    if isinstance(noeud, ast.Assign):
        cibles = noeud.targets
    elif isinstance(noeud, ast.AnnAssign):
        cibles = [noeud.target]
    else:
        return set()
    return {cible.id for cible in cibles if isinstance(cible, ast.Name)}


def _analyser_imports(arbre: ast.Module) -> _AliasesImports:
    """Prouve les imports standards et retire les alias réaffectés au niveau module.

    Une affectation directe ultérieure rend l'origine importée non prouvable :
    l'exemption est donc retirée fail-closed. Les réaffectations conditionnelles,
    locales ou indirectes restent hors périmètre de cette analyse syntaxique.
    """
    protocols: set[str] = set()
    modules_typing: set[str] = set()
    abstractmethods: set[str] = set()
    modules_abc: set[str] = set()
    not_implemented_errors: set[str] = set()

    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                if alias.name == "typing":
                    modules_typing.add(alias.asname or "typing")
                elif alias.name == "abc":
                    modules_abc.add(alias.asname or "abc")
        elif isinstance(noeud, ast.ImportFrom):
            if noeud.module == "typing":
                protocols.update(
                    alias.asname or "Protocol"
                    for alias in noeud.names
                    if alias.name == "Protocol"
                )
            elif noeud.module == "abc":
                abstractmethods.update(
                    alias.asname or "abstractmethod"
                    for alias in noeud.names
                    if alias.name == "abstractmethod"
                )
            elif noeud.module == "builtins":
                not_implemented_errors.update(
                    alias.asname or alias.name
                    for alias in noeud.names
                    if alias.name in {"NotImplementedError", "NotImplemented"}  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
                )

    for noeud in arbre.body:
        reassignees = _noms_cibles_affectation(noeud)
        protocols.difference_update(reassignees)
        modules_typing.difference_update(reassignees)
        abstractmethods.difference_update(reassignees)
        modules_abc.difference_update(reassignees)
        not_implemented_errors.difference_update(reassignees)

    return _AliasesImports(
        frozenset(protocols),
        frozenset(modules_typing),
        frozenset(abstractmethods),
        frozenset(modules_abc),
        frozenset(not_implemented_errors),
    )


def _est_classe_protocol(classe: ast.ClassDef, aliases: _AliasesImports) -> bool:
    """Détermine si une base est prouvée comme le véritable typing.Protocol."""
    for base in classe.bases:
        if isinstance(base, ast.Name) and base.id in aliases.protocols:
            return True
        if (
            isinstance(base, ast.Attribute)
            and isinstance(base.value, ast.Name)
            and base.value.id in aliases.modules_typing
            and base.attr == "Protocol"
        ):
            return True
    return False


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
    """Reconnaît NotImplementedError, y compris un alias importé prouvé de builtins."""  # proof:allow — constante/fixture du gate NO-STUB : ce motif EST le sujet
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
        == "NotImplementedError"  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
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
    violations: list[Violation] = []

    class Visiteur(ast.NodeVisitor):
        """Visite chaque définition sans perdre le contexte de sa classe parente."""

        def __init__(self) -> None:
            self.protocols: list[bool] = [False]

        def visit_ClassDef(self, noeud: ast.ClassDef) -> None:
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


def _est_appel_pytest(noeud: ast.Call, attribut: str) -> bool:
    """Reconnaît un appel direct pytest.<attribut> par sa forme syntaxique."""
    return (
        isinstance(noeud.func, ast.Attribute)
        and noeud.func.attr == attribut
        and isinstance(noeud.func.value, ast.Name)
        and noeud.func.value.id == "pytest"
    )


def _contient_oracle(fonction: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Détermine si une fonction de test contient au moins un oracle reconnu."""
    for noeud in ast.walk(fonction):
        if isinstance(noeud, ast.Assert):
            return True
        if isinstance(noeud, ast.With) and any(
            isinstance(element.context_expr, ast.Call)
            and _est_appel_pytest(element.context_expr, "raises")
            for element in noeud.items
        ):
            return True
        if isinstance(noeud, ast.Call) and (
            _est_appel_pytest(noeud, "fail")
            or isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr.startswith("assert")
        ):
            return True
    return False


def _est_decorateur_skip_ou_xfail(decorateur: ast.expr) -> bool:
    """Reconnaît les décorateurs pytest.mark.skip et pytest.mark.xfail."""
    cible = decorateur.func if isinstance(decorateur, ast.Call) else decorateur
    return (
        isinstance(cible, ast.Attribute)
        and cible.attr in {"skip", "xfail"}
        and isinstance(cible.value, ast.Attribute)
        and cible.value.attr == "mark"
        and isinstance(cible.value.value, ast.Name)
        and cible.value.value.id == "pytest"
    )


def _analyser_ast_diff(
    repo: Path,
    fichier: Path,
    arbre: ast.Module,
    lignes: set[int],
) -> list[Violation]:
    """Applique les règles AST limitées aux éléments effectivement modifiés."""
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
                if not _contient_oracle(noeud):
                    violations.append(
                        _violation(
                            "TEST_WITHOUT_ORACLE",
                            repo,
                            fichier,
                            noeud.lineno,
                            "le test modifié ne contient aucun oracle",
                        )
                    )
            for decorateur in noeud.decorator_list:
                if (
                    decorateur.lineno in lignes
                    and _est_decorateur_skip_ou_xfail(decorateur)
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
            if _est_appel_pytest(noeud, "skip") or (
                isinstance(noeud.func, ast.Attribute)
                and noeud.func.attr == "skip"
                and isinstance(noeud.func.value, ast.Name)
                and noeud.func.value.id == "unittest"
            ):
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
        if presentes and manquantes:
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


def _suppression_justifiee(commentaire: str) -> bool:
    """Vérifie une justification après marqueur et identifiant de règle éventuel."""
    texte = commentaire[1:].strip()
    texte_minuscule = texte.lower()
    for marqueur in _SUPPRESSION_MARKERS:
        position = texte_minuscule.find(marqueur)
        if position < 0:
            continue
        suite = texte[position + len(marqueur) :].lstrip()
        identifiant = _IDENTIFIANT_REGLE_OPTIONNEL.match(suite)
        if identifiant is not None:
            suite = suite[identifiant.end() :].lstrip()
        return len(suite) >= 2 and suite[0] in {"—", "-", ":"} and bool(suite[1:].strip())
    return True


def _analyser_commentaires(
    repo: Path,
    fichier: Path,
    contenu: str,
    lignes: set[int],
) -> list[Violation]:
    """Analyse exclusivement les tokens COMMENT appartenant aux lignes ajoutées."""
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
    except tokenize.TokenError:
        return violations
    return violations


def _analyser_fichier_python(
    repo: Path,
    fichier: Path,
    base_ref: str,
    racines_contractuelles: tuple[str, ...] | None,
) -> list[Violation]:
    """Analyse un fichier Python et refuse toute lecture ou syntaxe invalide."""
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


def _charger_yaml(
    repo: Path,
    fichier: Path,
) -> tuple[Mapping[object, object] | None, list[Violation]]:
    """Charge YAML avec PyYAML afin de respecter sa sémantique réelle."""
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
        return None, []
    return document, []


def _neutraliser_chaines_shell(commande: str) -> str:
    """Neutralise le contenu des quotes shell en préservant lignes et positions.

    Les quotes simples sont closes par la quote suivante. Dans les quotes doubles,
    un antislash consomme la paire échappée avant toute recherche de fermeture.
    Un texte non fermé reste neutralisé jusqu'à la fin : il ne constitue pas du
    code shell exploitable pour forcer un succès.
    """
    neutre: list[str] = []
    i = 0
    n = len(commande)
    while i < n:
        caractere = commande[i]
        if caractere not in {"'", '"'}:
            neutre.append(caractere)
            i += 1
            continue

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
    return "".join(neutre)


def _normaliser_commande(commande: str) -> str:
    """Supprime tous les espaces du code shell neutralisé pour les motifs répartis."""
    return re.sub(r"\s+", "", _neutraliser_chaines_shell(commande))


def _contient_succes_force(commande: str) -> bool:
    """Détecte les neutralisations shell hors chaînes littérales uniquement."""
    compacte = _normaliser_commande(commande)
    return (
        "||true" in compacte
        or "||:" in compacte
        or "||exit0" in compacte
        or ";true" in compacte
    )


def _contient_exit_zero_non_garde(commande: str) -> bool:
    """Détecte exit 0 hors quotes, sauf dans une branche shell conditionnelle connue."""
    profondeur_conditionnelle = 0
    for ligne in _neutraliser_chaines_shell(commande).splitlines() or [commande]:
        if _IF_SHELL.match(ligne) or _CASE_SHELL.match(ligne):
            profondeur_conditionnelle += 1
        if profondeur_conditionnelle == 0 and _EXIT_ZERO.search(ligne) is not None:
            return True
        if _FIN_IF_SHELL.match(ligne) or _FIN_CASE_SHELL.match(ligne):
            profondeur_conditionnelle = max(0, profondeur_conditionnelle - 1)
    return False


def _violation_succes_force(
    repo: Path,
    fichier: Path,
    ligne: int,
    job: str,
) -> Violation:
    """Construit la violation commune aux commandes de job et action composite."""
    return _violation(
        "REQUIRED_JOB_FORCED_SUCCESS",
        repo,
        fichier,
        ligne,
        f"le job requis {job} force un succès shell",
    )


def _analyser_commande(
    repo: Path,
    fichier: Path,
    commande: object,
    job: str,
) -> list[Violation]:
    """Analyse une commande YAML complète, blocs littéraux inclus."""
    if not isinstance(commande, str):
        return []
    if _contient_succes_force(commande) or _contient_exit_zero_non_garde(commande):
        return [_violation_succes_force(repo, fichier, 1, job)]
    return []


def _analyser_continue_on_error(
    repo: Path,
    fichier: Path,
    valeur: object,
    job: str,
) -> list[Violation]:
    """Refuse une tolérance d'erreur vraie, y compris écrite comme scalaire YAML quoté."""
    if valeur is True:
        detail = f"le job requis {job} accepte les erreurs"
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
    """Accepte uniquement always() et success(), garanties sans dépendance métier.

    Ces deux formes sont les conditions GitHub Actions explicites qui préservent
    l'exécution du job requis dans le flux attendu. Toute autre expression,
    dynamique ou littéralement fausse, dépend de données d'exécution et ne
    prouve plus que le contrôle obligatoire a été exécuté.
    """
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
    """Résout une référence locale vers son descripteur action.yml ou action.yaml."""
    if not reference.startswith("./"):
        return None
    repertoire = repo / reference[2:]
    for nom in ("action.yml", "action.yaml"):
        fichier = repertoire / nom
        if fichier.is_file():
            return fichier
    return None


def _analyser_action_locale(
    repo: Path,
    reference: str,
    job: str,
    visites: frozenset[Path] = frozenset(),
    profondeur: int = 0,
) -> list[Violation]:
    """Analyse récursivement une action composite locale appelée par un job requis."""
    fichier = _fichier_action_locale(repo, reference)
    if fichier is None:
        return []

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
    if not isinstance(etapes, list):
        return violations

    prochaines_visites = visites | {chemin}
    for etape in etapes:
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
        if isinstance(reference_suivante, str) and reference_suivante.startswith("./"):
            violations.extend(
                _analyser_action_locale(
                    repo,
                    reference_suivante,
                    job,
                    prochaines_visites,
                    profondeur + 1,
                )
            )
    return violations


def _analyser_workflow(
    repo: Path,
    fichier: Path,
    jobs_requis: tuple[str, ...],
) -> list[Violation]:
    """Analyse un workflow selon son arbre PyYAML plutôt que son indentation."""
    document, violations = _charger_yaml(repo, fichier)
    if document is None:
        return violations

    jobs = document.get("jobs")
    if not isinstance(jobs, Mapping):
        return violations

    for identifiant, definition in jobs.items():
        if not isinstance(identifiant, str) or identifiant not in jobs_requis:
            continue
        if not isinstance(definition, Mapping):
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
        if not isinstance(etapes, list):
            continue
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
            if isinstance(reference, str) and reference.startswith("./"):
                violations.extend(
                    _analyser_action_locale(repo, reference, identifiant)
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


def main(argv: list[str] | None = None) -> int:
    """Exécute le gate avec les racines contractuelles par défaut sûr.

    Sans --scope, toutes les racines du contrat sont analysées. Avec --scope,
    chacune des racines contractuelles doit rester présente : un sous-périmètre
    silencieux ne peut pas constituer une preuve de qualité.
    """
    parser = argparse.ArgumentParser(description="Détecte les stubs et dettes qualité.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--scope", action="append", dest="scopes")
    arguments = parser.parse_args(argv)

    repo = arguments.repo.resolve()
    racines, _, erreur_contrat = _lire_contrat(repo)
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
    for violation in violations:
        print(
            f"{violation.code} {violation.path}:{violation.line} {violation.detail}",
            file=sys.stdout,
        )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())

