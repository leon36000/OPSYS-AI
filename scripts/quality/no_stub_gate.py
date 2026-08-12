"""Gate de qualité refusant les stubs et les régressions de qualité ajoutées."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tokenize
import tomllib
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Final, Iterable


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
_DEBT_MARKERS: Final[tuple[str, ...]] = ("TODO", "FIXME", "XXX")  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
_SUPPRESSION_MARKERS: Final[tuple[str, ...]] = ("type: ignore", "noqa", "nosec")
_IDENTIFIANT_REGLE_OPTIONNEL: Final[re.Pattern[str]] = re.compile(
    r"(?:[A-Za-z]+[0-9][A-Za-z0-9_-]*|\[[A-Za-z0-9_.-]+\]|[A-Za-z][A-Za-z0-9_.-]*)"
)
_EXIT_ZERO: Final[re.Pattern[str]] = re.compile(r"(?:^|[;|&()\s])exit\s+0(?:\s|$)")
_IF_SHELL: Final[re.Pattern[str]] = re.compile(r"^\s*if\b.*\bthen\s*$")
_CASE_SHELL: Final[re.Pattern[str]] = re.compile(r"^\s*case\b.*\bin\s*$")
_FIN_IF_SHELL: Final[re.Pattern[str]] = re.compile(r"^\s*fi\s*;?\s*$")
_FIN_CASE_SHELL: Final[re.Pattern[str]] = re.compile(r"^\s*esac\s*;?\s*$")
_VALEURS_YAML_VRAIES: Final[frozenset[str]] = frozenset(
    {"true", "yes", "on", "y", "1"}
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


def _charger_contrat(repo: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Charge le contrat local, ou le contrat canonique si le dépôt testé ne l'a pas."""
    fichier = repo / "core" / "quality-scopes.toml"
    source = fichier if fichier.is_file() else _SCOPE_FILE
    try:
        with source.open("rb") as flux:
            contrat = tomllib.load(flux)
    except (OSError, tomllib.TOMLDecodeError):
        return (), _DEFAULT_REQUIRED_JOB_IDS

    racines = contrat.get("python_roots", [])
    jobs = contrat.get("target_required_job_ids", [])
    if not isinstance(racines, list) or not all(isinstance(item, str) for item in racines):
        racines = []
    if not isinstance(jobs, list) or not all(isinstance(item, str) for item in jobs):
        jobs = list(_DEFAULT_REQUIRED_JOB_IDS)
    return tuple(racines), tuple(jobs)


def _charger_racines_contractuelles(repo: Path) -> tuple[str, ...] | None:
    """Charge les racines du contrat du dépôt analysé sans inventer de repli externe."""
    fichier = repo / "core" / "quality-scopes.toml"
    if not fichier.is_file():
        return None
    try:
        with fichier.open("rb") as flux:
            contrat = tomllib.load(flux)
    except (OSError, tomllib.TOMLDecodeError):
        return None

    racines = contrat.get("python_roots")
    if not isinstance(racines, list) or not all(isinstance(item, str) for item in racines):
        return None
    return tuple(racines)


def _chemin_relatif(repo: Path, fichier: Path) -> str:
    """Retourne le chemin POSIX stable d'un fichier relativement au dépôt."""
    return fichier.relative_to(repo).as_posix()


def _violation(code: str, repo: Path, fichier: Path, line: int, detail: str) -> Violation:
    """Construit une violation avec son chemin affichable."""
    return Violation(code, _chemin_relatif(repo, fichier), line, detail)


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
    """Retire la docstring initiale d'un corps exécutable."""
    return corps[1:] if corps and _est_docstring(corps[0]) else corps


def _analyser_imports(arbre: ast.Module) -> _AliasesImports:
    """Prouve les alias réellement liés à typing.Protocol et abc.abstractmethod.

    Cette preuve est volontairement limitée aux imports : une réaffectation
    ultérieure d'un alias importé n'est pas suivie par cette analyse statique.
    """
    protocols: set[str] = set()
    modules_typing: set[str] = set()
    abstractmethods: set[str] = set()
    modules_abc: set[str] = set()

    for noeud in arbre.body:
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                if alias.name == "typing":
                    modules_typing.add(alias.asname or "typing")
                if alias.name == "abc":
                    modules_abc.add(alias.asname or "abc")
        elif isinstance(noeud, ast.ImportFrom):
            if noeud.module == "typing":
                protocols.update(
                    alias.asname or "Protocol"
                    for alias in noeud.names
                    if alias.name == "Protocol"
                )
            if noeud.module == "abc":
                abstractmethods.update(
                    alias.asname or "abstractmethod"
                    for alias in noeud.names
                    if alias.name == "abstractmethod"
                )
    return _AliasesImports(
        frozenset(protocols),
        frozenset(modules_typing),
        frozenset(abstractmethods),
        frozenset(modules_abc),
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


def _est_exception_non_implementee(noeud: ast.expr) -> bool:
    """Reconnaît les exceptions indiquant explicitement une absence d'implémentation."""
    cible = noeud.func if isinstance(noeud, ast.Call) else noeud
    return (
        isinstance(cible, ast.Name)
        and cible.id in {"NotImplementedError", "NotImplemented"}  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
    ) or (
        isinstance(cible, ast.Attribute)
        and cible.attr == "NotImplementedError"  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
    )


def _leve_not_implemented(fonction: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Recherche une levée de NotImplementedError ou NotImplemented dans le corps."""  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
    return any(
        isinstance(noeud, ast.Raise)
        and noeud.exc is not None
        and _est_exception_non_implementee(noeud.exc)
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

    if _leve_not_implemented(fonction):
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
    """Refuse les lambdas réduits à None ou Ellipsis, stubs hors corps de fonction."""
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
    """Parcourt les fonctions avec le contexte d'abstraction prouvé par les imports."""
    violations: list[Violation] = []
    aliases = _analyser_imports(arbre)

    def visiter(noeuds: Iterable[ast.stmt], dans_protocol: bool) -> None:
        for noeud in noeuds:
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                violations.extend(
                    _analyser_fonction(repo, fichier, noeud, dans_protocol, aliases)
                )
                visiter(noeud.body, False)
            elif isinstance(noeud, ast.ClassDef):
                visiter(noeud.body, _est_classe_protocol(noeud, aliases))

    visiter(arbre.body, False)
    violations.extend(_analyser_lambdas(repo, fichier, arbre))
    return violations


def _est_fichier_production(fichier: Path) -> bool:
    """Exclut les fichiers de test de la règle réservée aux modules de production."""
    return not (fichier.name.startswith("test_") or fichier.name.endswith("_test.py"))


def _est_vide_autorise(fichier: Path) -> bool:
    """Reconnaît les deux exceptions explicites aux modules Python vides."""
    return fichier.name in {"__init__.py", ".gitkeep"}


def _lignes_du_diff(repo: Path, fichier: Path, base_ref: str, contenu: str) -> set[int]:
    """Retourne les lignes ajoutées par Git, avec repli fermé pour les fichiers non suivis."""
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
    """Limite la preuve aux lanceurs de scan responsables du périmètre effectif."""
    relatif = fichier.relative_to(repo)
    return fichier.name.startswith("run_") or relatif.parts[:2] == ("core", "scripts")


def _valeurs_litterales(noeud: ast.expr) -> set[str] | None:
    """Extrait les chaînes d'une collection littérale ou de concaténations de listes."""
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
    """Indique si une expression désigne la variable de boucle de la compréhension."""
    return isinstance(noeud, ast.Name) and noeud.id == nom_boucle


def _comparaison_exclut_racine(noeud: ast.expr, nom_boucle: str) -> bool:
    """Détecte une exclusion littérale, y compris dans une condition composée.

    Une indirection telle que ``r not in exclus`` n'est volontairement pas suivie :
    la déterminer nécessiterait une analyse de flot de données.
    """
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


def _comprehension_filtre_racines(noeud: ast.expr) -> bool:
    """Détecte un filtrage explicite de racines dans une compréhension."""
    if not isinstance(noeud, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return False
    return any(
        isinstance(generateur.target, ast.Name)
        and any(
            _comparaison_exclut_racine(condition, generateur.target.id)
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
    """Prouve les omissions littérales et exclusions explicites des racines."""
    if not racines or not _est_cible_controle_perimetre(repo, fichier):
        return []

    violations: list[Violation] = []
    ensemble_racines = set(racines)
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.expr) and _comprehension_filtre_racines(noeud):
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
        valeurs = _valeurs_litterales(noeud) if isinstance(noeud, ast.expr) else None
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
    """Analyse un fichier Python selon les règles globales et diff-aware.

    Tout échec de lecture ou de parsing est une violation fail-closed :
    un fichier impossible à analyser ne peut jamais être considéré comme propre.
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

    violations: list[Violation] = []
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

    violations.extend(_analyser_stubs(repo, fichier, arbre))
    violations.extend(
        _analyser_omissions_racines(repo, fichier, arbre, racines_contractuelles)
    )
    lignes = _lignes_du_diff(repo, fichier, base_ref, contenu)
    violations.extend(_analyser_ast_diff(repo, fichier, arbre, lignes))
    violations.extend(_analyser_commentaires(repo, fichier, contenu, lignes))
    return violations


def _valeur_apres_deux_points(ligne: str) -> str:
    """Extrait la valeur textuelle d'une clé YAML simple."""
    return ligne.split(":", 1)[1].strip().strip("'\"")


def _contient_succes_force(commande: str) -> bool:
    """Reconnaît les neutralisations shell usuelles d'un code de retour."""
    compacte = commande.replace(" ", "")
    return (
        "||true" in compacte
        or "||:" in compacte
        or "||exit0" in compacte
        or ";true" in compacte
    )


def _contient_exit_zero_non_garde(commande: str, dans_condition: bool) -> bool:
    """Détecte un exit 0 hors d'une branche shell conditionnelle connue."""
    return not dans_condition and _EXIT_ZERO.search(commande) is not None


def _commande_run_inline(ligne: str) -> str | None:
    """Extrait une commande run, y compris depuis un item YAML `- run:`."""
    if ligne.startswith("run:"):
        return _valeur_apres_deux_points(ligne)
    if ligne.startswith("- run:"):
        return _valeur_apres_deux_points(ligne[2:].lstrip())
    return None


def _valeur_uses(ligne: str) -> str | None:
    """Extrait la référence d'une action depuis une clé YAML `uses`."""
    if ligne.startswith("uses:"):
        return _valeur_apres_deux_points(ligne)
    if ligne.startswith("- uses:"):
        return _valeur_apres_deux_points(ligne[2:].lstrip())
    return None


def _est_indicateur_bloc_yaml(valeur: str) -> bool:
    """Reconnaît les indicateurs YAML de scalaire littéral ou replié."""
    return valeur in {"|", "|-", "|+", ">", ">-", ">+"}


def _violation_succes_force(
    repo: Path,
    fichier: Path,
    ligne: int,
    job: str,
) -> Violation:
    """Construit la violation commune aux commandes de job et d'action composite."""
    return _violation(
        "REQUIRED_JOB_FORCED_SUCCESS",
        repo,
        fichier,
        ligne,
        f"le job requis {job} force un succès shell",
    )


def _analyser_commandes_yaml(
    repo: Path,
    fichier: Path,
    job: str,
) -> list[Violation]:
    """Analyse les commandes run d'un YAML d'action composite locale."""
    try:
        lignes = fichier.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    violations: list[Violation] = []
    dans_bloc = False
    indentation_bloc = -1
    profondeur_conditionnelle = 0
    for numero, brute in enumerate(lignes, start=1):
        sans_espace = brute.lstrip()
        indentation = len(brute) - len(sans_espace)
        if dans_bloc:
            if sans_espace and indentation > indentation_bloc:
                if _IF_SHELL.match(sans_espace) or _CASE_SHELL.match(sans_espace):
                    profondeur_conditionnelle += 1
                if _contient_succes_force(sans_espace) or _contient_exit_zero_non_garde(
                    sans_espace, profondeur_conditionnelle > 0
                ):
                    violations.append(_violation_succes_force(repo, fichier, numero, job))
                if _FIN_IF_SHELL.match(sans_espace) or _FIN_CASE_SHELL.match(sans_espace):
                    profondeur_conditionnelle = max(0, profondeur_conditionnelle - 1)
                continue
            dans_bloc = False
            profondeur_conditionnelle = 0

        commande = _commande_run_inline(sans_espace)
        if commande is None:
            continue
        if _est_indicateur_bloc_yaml(commande):
            dans_bloc = True
            indentation_bloc = indentation
        elif _contient_succes_force(commande) or _contient_exit_zero_non_garde(
            commande, False
        ):
            violations.append(_violation_succes_force(repo, fichier, numero, job))
    return violations


def _analyser_action_locale(
    repo: Path,
    reference: str,
    job: str,
) -> list[Violation]:
    """Analyse action.yml d'une action composite locale référencée par un job requis.

    Les références externes ``owner/repo@sha`` ne sont pas analysables localement :
    leur délégation échappe donc nécessairement à cette vérification statique.
    """
    if not reference.startswith("./"):
        return []
    repertoire = repo / reference[2:]
    for nom in ("action.yml", "action.yaml"):
        fichier = repertoire / nom
        if fichier.is_file():
            return _analyser_commandes_yaml(repo, fichier, job)
    return []


def _analyser_workflow(
    repo: Path,
    fichier: Path,
    jobs_requis: tuple[str, ...],
) -> list[Violation]:
    """Analyse textuellement les jobs requis et leurs commandes shell.

    Un ``exit 0`` dans un bloc ``if`` ou ``case`` est considéré conditionnel.
    Une condition toujours vraie n'est pas détectable ici : cette règle lit du
    texte shell, elle ne l'exécute pas. Les actions locales sont inspectées,
    contrairement aux actions externes qui échappent à cette vérification.
    """
    violations: list[Violation] = []
    try:
        lignes = fichier.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return violations

    dans_jobs = False
    indentation_jobs = -1
    job_courant: str | None = None
    indentation_job = -1
    bloc_requis = False
    indentation_bloc = -1
    profondeur_conditionnelle = 0

    for numero, brute in enumerate(lignes, start=1):
        sans_espace = brute.lstrip()
        indentation = len(brute) - len(sans_espace)

        if bloc_requis:
            if sans_espace and indentation > indentation_bloc:
                if _IF_SHELL.match(sans_espace) or _CASE_SHELL.match(sans_espace):
                    profondeur_conditionnelle += 1
                if _contient_succes_force(sans_espace) or _contient_exit_zero_non_garde(
                    sans_espace, profondeur_conditionnelle > 0
                ):
                    if job_courant is not None:
                        violations.append(
                            _violation_succes_force(
                                repo, fichier, numero, job_courant
                            )
                        )
                if _FIN_IF_SHELL.match(sans_espace) or _FIN_CASE_SHELL.match(sans_espace):
                    profondeur_conditionnelle = max(0, profondeur_conditionnelle - 1)
                continue
            bloc_requis = False
            indentation_bloc = -1
            profondeur_conditionnelle = 0

        if not sans_espace or sans_espace.startswith("#"):
            continue
        if sans_espace == "jobs:":
            dans_jobs = True
            indentation_jobs = indentation
            job_courant = None
            continue
        if not dans_jobs:
            continue
        if indentation <= indentation_jobs:
            dans_jobs = False
            job_courant = None
            continue

        est_cle = ":" in sans_espace and not sans_espace.startswith("- ")
        if est_cle and indentation == indentation_jobs + 2:
            job_courant = sans_espace.split(":", 1)[0].strip("'\"")
            indentation_job = indentation
            continue

        if job_courant not in jobs_requis or indentation <= indentation_job:
            continue

        if sans_espace.startswith("continue-on-error:"):
            valeur = _valeur_apres_deux_points(sans_espace)
            if "${{" in valeur:
                violations.append(
                    _violation(
                        "REQUIRED_JOB_SOFT_FAILURE",
                        repo,
                        fichier,
                        numero,
                        f"le job requis {job_courant} utilise une valeur dynamique "
                        "pour continue-on-error, refusée par principe",
                    )
                )
            elif valeur.lower() in _VALEURS_YAML_VRAIES:
                violations.append(
                    _violation(
                        "REQUIRED_JOB_SOFT_FAILURE",
                        repo,
                        fichier,
                        numero,
                        f"le job requis {job_courant} accepte les erreurs",
                    )
                )

        reference = _valeur_uses(sans_espace)
        if reference is not None:
            violations.extend(_analyser_action_locale(repo, reference, job_courant))
            continue

        commande = _commande_run_inline(sans_espace)
        if commande is None:
            continue
        if _est_indicateur_bloc_yaml(commande):
            bloc_requis = True
            indentation_bloc = indentation
            profondeur_conditionnelle = 0
        elif _contient_succes_force(commande) or _contient_exit_zero_non_garde(
            commande, False
        ):
            violations.append(_violation_succes_force(repo, fichier, numero, job_courant))
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


def main(argv: list[str] | None = None) -> int:
    """Exécute le gate depuis la ligne de commande et affiche ses violations."""
    parser = argparse.ArgumentParser(description="Détecte les stubs et dettes qualité.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--scope", action="append", dest="scopes")
    arguments = parser.parse_args(argv)

    repo = arguments.repo.resolve()
    racines, _ = _charger_contrat(repo)
    scopes = tuple(arguments.scopes) if arguments.scopes else racines
    violations = scan_repository(repo, scopes, base_ref=arguments.base_ref)
    for violation in violations:
        print(
            f"{violation.code} {violation.path}:{violation.line} {violation.detail}",
            file=sys.stdout,
        )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
