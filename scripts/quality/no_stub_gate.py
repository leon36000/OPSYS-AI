"""Gate de qualité refusant les stubs et les régressions de qualité ajoutées."""

from __future__ import annotations

import argparse
import ast
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


@dataclass(frozen=True)
class Violation:
    """Décrit une règle de qualité enfreinte dans un fichier du dépôt."""

    code: str
    path: str
    line: int
    detail: str


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
    if corps and _est_docstring(corps[0]):
        return corps[1:]
    return corps


def _nom_decorateur(decorateur: ast.expr) -> str | None:
    """Extrait le nom qualifié d'un décorateur sans interpréter le code."""
    cible = decorateur.func if isinstance(decorateur, ast.Call) else decorateur
    morceaux: list[str] = []
    while isinstance(cible, ast.Attribute):
        morceaux.append(cible.attr)
        cible = cible.value
    if isinstance(cible, ast.Name):
        morceaux.append(cible.id)
        return ".".join(reversed(morceaux))
    return None


def _est_classe_protocol(classe: ast.ClassDef) -> bool:
    """Détermine par ses bases AST si une classe est un Protocol."""
    for base in classe.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if (
            isinstance(base, ast.Attribute)
            and isinstance(base.value, ast.Name)
            and base.value.id == "typing"
            and base.attr == "Protocol"
        ):
            return True
    return False


def _est_methode_abstraite(fonction: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Détermine si une méthode porte explicitement le décorateur abstractmethod."""
    return any(
        _nom_decorateur(decorateur) in {"abstractmethod", "abc.abstractmethod"}
        for decorateur in fonction.decorator_list
    )


def _leve_not_implemented(fonction: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Recherche une levée de NotImplementedError dans le corps d'une fonction."""  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
    for noeud in ast.walk(fonction):
        if not isinstance(noeud, ast.Raise) or noeud.exc is None:
            continue
        exception = noeud.exc
        cible = exception.func if isinstance(exception, ast.Call) else exception
        if isinstance(cible, ast.Name) and cible.id == "NotImplementedError":  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
            return True
    return False


def _analyser_fonction(
    repo: Path,
    fichier: Path,
    fonction: ast.FunctionDef | ast.AsyncFunctionDef,
    dans_protocol: bool,
) -> list[Violation]:
    """Applique les règles anti-stub locales à une fonction."""
    violations: list[Violation] = []
    utile = _corps_utile(fonction.body)
    ligne = fonction.lineno

    if len(fonction.body) == 1 and _est_docstring(fonction.body[0]):
        violations.append(
            _violation(
                "DOCSTRING_ONLY_BODY",
                repo,
                fichier,
                ligne,
                "le corps de la fonction ne contient qu'une docstring",
            )
        )

    if len(utile) == 1 and isinstance(utile[0], ast.Pass):
        violations.append(
            _violation(
                "EXECUTABLE_PASS",
                repo,
                fichier,
                ligne,
                "le corps exécutable est réduit à pass",
            )
        )

    est_ellipse = (
        len(utile) == 1
        and isinstance(utile[0], ast.Expr)
        and isinstance(utile[0].value, ast.Constant)
        and utile[0].value.value is Ellipsis
    )
    if est_ellipse and not (dans_protocol or _est_methode_abstraite(fonction)):
        violations.append(
            _violation(
                "EXECUTABLE_ELLIPSIS",
                repo,
                fichier,
                ligne,
                "le corps exécutable est réduit à une ellipse",
            )
        )

    if _leve_not_implemented(fonction):
        violations.append(
            _violation(
                "NOT_IMPLEMENTED_STUB",
                repo,
                fichier,
                ligne,
                "la fonction lève NotImplementedError",  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
            )
        )
    return violations


def _analyser_stubs(repo: Path, fichier: Path, arbre: ast.Module) -> list[Violation]:
    """Parcourt les fonctions en conservant le contexte exact des classes Protocol."""
    violations: list[Violation] = []

    def visiter(noeuds: Iterable[ast.stmt], dans_protocol: bool) -> None:
        for noeud in noeuds:
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                violations.extend(_analyser_fonction(repo, fichier, noeud, dans_protocol))
                visiter(noeud.body, False)
            elif isinstance(noeud, ast.ClassDef):
                visiter(noeud.body, _est_classe_protocol(noeud))

    visiter(arbre.body, False)
    return violations


def _est_fichier_production(fichier: Path) -> bool:
    """Exclut les fichiers de test de la règle réservée aux modules de production."""
    nom = fichier.name
    return not (nom.startswith("test_") or nom.endswith("_test.py"))


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

    commande = ["git", "diff", "--unified=0", f"{base_ref}...HEAD", "--", relatif]
    resultat = subprocess.run(
        commande,
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if resultat.returncode != 0:
        return set(range(1, len(contenu.splitlines()) + 1))
    return _parser_hunks(resultat.stdout)


def _parser_hunks(diff: str) -> set[int]:
    """Parse les en-têtes de hunk unifié afin d'obtenir les lignes nouvelles."""
    lignes: set[int] = set()
    for ligne in diff.splitlines():
        if not ligne.startswith("@@ "):
            continue
        morceaux = ligne.split()
        if len(morceaux) < 3:
            continue
        nouveau = morceaux[2]
        if not nouveau.startswith("+"):
            continue
        intervalle = nouveau[1:]
        debut_texte, separateur, compte_texte = intervalle.partition(",")
        try:
            debut = int(debut_texte)
            compte = int(compte_texte) if separateur else 1
        except ValueError:
            continue
        lignes.update(range(debut, debut + compte))
    return lignes


def _fonction_modifiee(fonction: ast.FunctionDef | ast.AsyncFunctionDef, lignes: set[int]) -> bool:
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
        if isinstance(noeud, ast.With):
            for element in noeud.items:
                if isinstance(element.context_expr, ast.Call) and _est_appel_pytest(
                    element.context_expr, "raises"
                ):
                    return True
        if isinstance(noeud, ast.Call):
            if _est_appel_pytest(noeud, "fail"):
                return True
            if isinstance(noeud.func, ast.Attribute) and noeud.func.attr.startswith("assert"):
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
        if isinstance(noeud, ast.Assert) and noeud.lineno in lignes:
            if _est_constante_vraie(noeud.test):
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
                if decorateur.lineno in lignes and _est_decorateur_skip_ou_xfail(decorateur):
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
    """Limite la preuve aux lanceurs de scan, car une liste partielle y masque un audit.

    Les listes de racines dans des tests ou fixtures décrivent souvent un cas local
    intentionnel. Un fichier nommé ``run_*`` ou placé sous ``core/scripts`` porte,
    lui, la responsabilité opérationnelle de transmettre le périmètre aux outils
    de scan : y omettre une racine est plus dangereux qu'omettre toute liste, car
    la liste partielle donne une apparence trompeuse de couverture exhaustive.
    """
    relatif = fichier.relative_to(repo)
    return fichier.name.startswith("run_") or relatif.parts[:2] == ("core", "scripts")


def _analyser_omissions_racines(
    repo: Path,
    fichier: Path,
    arbre: ast.Module,
    racines: tuple[str, ...] | None,
) -> list[Violation]:
    """Prouve qu'un lanceur de scan énumère partiellement les racines contractuelles."""
    if not racines or not _est_cible_controle_perimetre(repo, fichier):
        return []

    violations: list[Violation] = []
    ensemble_racines = set(racines)
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.List, ast.Tuple)):
            continue
        if not all(
            isinstance(element, ast.Constant) and isinstance(element.value, str)
            for element in noeud.elts
        ):
            continue
        valeurs = {
            element.value
            for element in noeud.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
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
            apres_index = position + len(marqueur)
            apres = texte[apres_index] if apres_index < len(texte) else ""
            separateur = not avant or not (avant.isalnum() or avant == "_")
            fin_valide = not apres or not (apres.isalnum() or apres == "_")
            if separateur and fin_valide:
                return marqueur
            position = texte.find(marqueur, position + 1)
    return None


def _suppression_justifiee(commentaire: str) -> bool:
    """Vérifie la présence d'une justification structurée après une suppression."""
    texte = commentaire[1:].strip()
    texte_minuscule = texte.lower()
    for marqueur in _SUPPRESSION_MARKERS:
        position = texte_minuscule.find(marqueur)
        if position < 0:
            continue
        suite = texte[position + len(marqueur) :].lstrip()
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
        jetons = tokenize.generate_tokens(StringIO(contenu).readline)
        for jeton in jetons:
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
    """Analyse un fichier Python selon les règles globales et diff-aware."""
    contenu = fichier.read_text(encoding="utf-8")
    violations: list[Violation] = []
    if not contenu.strip() and _est_fichier_production(fichier) and not _est_vide_autorise(fichier):
        violations.append(
            _violation(
                "EMPTY_PRODUCTION_FILE",
                repo,
                fichier,
                1,
                "le module de production est vide",
            )
        )
        return violations
    try:
        arbre = ast.parse(contenu, filename=str(fichier))
    except SyntaxError:
        return violations

    violations.extend(_analyser_stubs(repo, fichier, arbre))
    violations.extend(_analyser_omissions_racines(repo, fichier, arbre, racines_contractuelles))
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
    return "||true" in compacte or "||:" in compacte or "||exit0" in compacte


def _commande_run_inline(ligne: str) -> str | None:
    """Extrait une commande run, y compris depuis un item YAML `- run:`."""
    if ligne.startswith("run:"):
        return _valeur_apres_deux_points(ligne)
    if ligne.startswith("- run:"):
        return _valeur_apres_deux_points(ligne[2:].lstrip())
    return None


def _analyser_workflow(
    repo: Path,
    fichier: Path,
    jobs_requis: tuple[str, ...],
) -> list[Violation]:
    """Analyse un sous-ensemble YAML honnête des jobs CI requis."""
    violations: list[Violation] = []
    lignes = fichier.read_text(encoding="utf-8").splitlines()
    dans_jobs = False
    indentation_jobs = -1
    job_courant: str | None = None
    indentation_job = -1

    for numero, brute in enumerate(lignes, start=1):
        sans_espace = brute.lstrip()
        if not sans_espace or sans_espace.startswith("#"):
            continue
        indentation = len(brute) - len(sans_espace)
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
            if _valeur_apres_deux_points(sans_espace).lower() == "true":
                violations.append(
                    _violation(
                        "REQUIRED_JOB_SOFT_FAILURE",
                        repo,
                        fichier,
                        numero,
                        f"le job requis {job_courant} accepte les erreurs",
                    )
                )

        commande = _commande_run_inline(sans_espace)
        if commande is not None and _contient_succes_force(commande):
            violations.append(
                _violation(
                    "REQUIRED_JOB_FORCED_SUCCESS",
                    repo,
                    fichier,
                    numero,
                    f"le job requis {job_courant} force un succès shell",
                )
            )
    return violations


def _analyser_workflows(repo: Path, jobs_requis: tuple[str, ...]) -> list[Violation]:
    """Analyse tous les workflows YAML présents dans le dépôt."""
    repertoire = repo / ".github" / "workflows"
    if not repertoire.is_dir():
        return []
    fichiers = sorted((*repertoire.glob("*.yml"), *repertoire.glob("*.yaml")))
    violations: list[Violation] = []
    for fichier in fichiers:
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

