"""Cas RED du gate anti-stub et de protection qualité diff-aware."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

from scripts.quality.no_stub_gate import Violation, scan_repository


_BASE_REF: Final[str] = "HEAD"


def _executer_git(repo: Path, *arguments: str) -> None:
    """Exécute git avec échec explicite afin que chaque diff testé soit réel."""
    subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _depot_git_initialise(tmp_path: Path) -> Path:
    """Crée un dépôt avec un commit de base réel pour les règles dépendantes du diff."""
    _executer_git(tmp_path, "init")
    _executer_git(tmp_path, "config", "user.email", "tests@example.invalid")
    _executer_git(tmp_path, "config", "user.name", "Tests Quality")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _executer_git(tmp_path, "add", "README.md")
    _executer_git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _ecrire(repo: Path, chemin: str, contenu: str) -> Path:
    """Écrit un fichier synthétique sous le dépôt isolé du cas testé."""
    cible = repo / chemin
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(contenu, encoding="utf-8")
    return cible


def _scanner(repo: Path, scopes: tuple[str, ...] = ("src",)) -> list[Violation]:
    """Lance le gate avec HEAD comme référence d'un dépôt git effectivement initialisé."""
    return scan_repository(repo, scopes, base_ref=_BASE_REF)


def _codes(violations: list[Violation]) -> set[str]:
    """Extrait les codes afin que les oracles restent indépendants du format du détail."""
    return {violation.code for violation in violations}


def _contrat(repo: Path) -> None:
    """Écrit le contrat minimal qui rend les racines et jobs de test explicites."""
    _ecrire(
        repo,
        "core/quality-scopes.toml",
        'python_roots = ["core/src", "core/scripts", "tools/proof", "scripts", ".opsys/tools/github-control"]\n'
        'target_required_job_ids = ["gates", "types", "tests", "security", "pack-validation", "proof-sealed"]\n',
    )


def test_refuse_une_fonction_dont_le_corps_est_pass(tmp_path: Path) -> None:
    """Prouve qu'un corps exécutable réduit à pass est interdit sur tout le périmètre."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "def calculer() -> None:\n    pass\n")
    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_return_none_comme_unique_corps_utile(tmp_path: Path) -> None:
    """Prouve que return None seul ne contourne plus la détection de stub."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "def calculer() -> None:\n    return None\n")
    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_return_nu_comme_unique_corps_utile(tmp_path: Path) -> None:
    """Prouve que return nu seul ne contourne plus la détection de stub."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "def calculer() -> None:\n    return\n")
    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_un_corps_multi_instruction_entierement_trivial(tmp_path: Path) -> None:
    """Prouve que multiplier pass et return ne crée pas un échappatoire de comptage."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def calculer() -> None:\n    pass\n    return None\n",
    )
    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_un_return_nu_apres_un_effet_reel(tmp_path: Path) -> None:
    """Prouve que return nu n'est signalé que lorsqu'il est l'unique instruction utile."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def calculer() -> None:\n    valeur = 1\n    return\n",
    )
    assert "EXECUTABLE_PASS" not in _codes(_scanner(repo))


def test_refuse_un_lambda_ellipsis(tmp_path: Path) -> None:
    """Prouve que les lambdas stubs ne sont plus ignorés par le parcours AST."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "service = lambda: ...\n")
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_lambda_none(tmp_path: Path) -> None:
    """Prouve que None est aussi un corps de lambda dépourvu de comportement."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "service = lambda: None\n")
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_dans_une_methode_ordinaire(tmp_path: Path) -> None:
    """Prouve que seule une abstraction reconnue peut employer une ellipse de corps."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Depot:\n    def lire(self) -> str:\n        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_une_ellipse_dans_un_protocol_reel(tmp_path: Path) -> None:
    """Prouve que l'import direct de typing.Protocol ouvre l'exception légitime."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_un_alias_typing_protocol(tmp_path: Path) -> None:
    """Prouve que typing importé sous alias reste reconnu sans faux positif fermé."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n"
        "class Depot(t.Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_un_alias_direct_protocol(tmp_path: Path) -> None:
    """Prouve que l'alias explicite d'un import Protocol reste une abstraction réelle."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol as P\n\n"
        "class Depot(P):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_protocol_local_usurpe(tmp_path: Path) -> None:
    """Prouve qu'une classe locale nommée Protocol ne peut plus exempter un stub."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Protocol:\n"
        "    valeur = 1\n\n"
        "class Service(Protocol):\n"
        "    def executer(self):\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_une_methode_abstraite_importee(tmp_path: Path) -> None:
    """Prouve qu'un abstractmethod réellement importé conserve son exemption."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from abc import abstractmethod\n\n"
        "class Depot:\n"
        "    @abstractmethod\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_un_alias_module_abc(tmp_path: Path) -> None:
    """Prouve qu'un alias de module abc est relié à son décorateur réel."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import abc as a\n\n"
        "class Depot:\n"
        "    @a.abstractmethod\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_abstractmethod_local_usurpe(tmp_path: Path) -> None:
    """Prouve qu'un décorateur local homonyme ne peut plus masquer une ellipse."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def abstractmethod(f):\n"
        "    return f\n\n"
        "class Depot:\n"
        "    @abstractmethod\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_raise_not_implemented_error(tmp_path: Path) -> None:
    """Prouve qu'une levée de NotImplementedError ne masque pas une absence d'implémentation."""  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def calculer() -> int:\n    raise NotImplementedError\n",  # proof:allow — fixture/constante du gate NO-STUB : ce motif EST le sujet du test
    )
    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_une_fonction_avec_seulement_une_docstring(tmp_path: Path) -> None:
    """Prouve qu'une documentation seule ne constitue pas un corps fonctionnel."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        'def calculer() -> None:\n    """Décrit le calcul."""\n',
    )
    assert "DOCSTRING_ONLY_BODY" in _codes(_scanner(repo))


def test_refuse_assert_true_dans_un_test(tmp_path: Path) -> None:
    """Prouve qu'une assertion tautologique ajoutée ne peut pas simuler un oracle."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/test_service.py", "def test_calcul() -> None:\n    assert True\n")
    assert "TRIVIAL_ASSERTION" in _codes(_scanner(repo))


def test_refuse_un_test_ajoute_sans_oracle(tmp_path: Path) -> None:
    """Prouve qu'un nouveau test sans assertion ni attente vérifiable est signalé."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/test_service.py", "def test_calcul() -> None:\n    calculer()\n")
    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_refuse_un_skip_ajoute(tmp_path: Path) -> None:
    """Prouve qu'un skip introduit après la référence git est une dette explicite."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest\n\n\ndef test_calcul() -> None:\n    pytest.skip('indisponible')\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_fichier_de_production_vide(tmp_path: Path) -> None:
    """Prouve qu'un module de production vide est détecté même hors modification diff-aware."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "")
    assert "EMPTY_PRODUCTION_FILE" in _codes(_scanner(repo))


def test_refuse_un_marqueur_de_dette_ajoute_dans_un_commentaire(tmp_path: Path) -> None:
    """Prouve que les marqueurs de dette ajoutés dans les commentaires restent visibles."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "# " + "TO" + "DO traiter ce cas\nvaleur = 1\n")
    assert "FORBIDDEN_MARKER" in _codes(_scanner(repo))


def test_accepte_le_mot_de_dette_dans_une_chaine_litterale(tmp_path: Path) -> None:
    """Prouve qu'une chaîne métier contenant ce mot n'est pas confondue avec un commentaire."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", 'message = "' + "TO" + 'DO traité par le client"\n')
    assert _codes(_scanner(repo)) == set()


def test_refuse_un_type_ignore_ajoute_sans_justification(tmp_path: Path) -> None:
    """Prouve qu'une suppression de typage nouvelle exige une justification structurée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "valeur = inconnu  # type: ignore\n")
    assert "UNJUSTIFIED_SUPPRESSION" in _codes(_scanner(repo))


def test_accepte_nosec_avec_identifiant_et_justification(tmp_path: Path) -> None:
    """Prouve que l'identifiant B310 précède valablement une justification obligatoire."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "valeur = 1  # nosec B310 — schéma validé par liste blanche\n",
    )
    assert "UNJUSTIFIED_SUPPRESSION" not in _codes(_scanner(repo))


def test_refuse_nosec_avec_identifiant_sans_justification(tmp_path: Path) -> None:
    """Prouve que l'identifiant seul ne remplace jamais la justification humaine."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "valeur = 1  # nosec B310\n")
    assert "UNJUSTIFIED_SUPPRESSION" in _codes(_scanner(repo))


def test_detecte_le_retrait_de_tools_proof_du_scope_securite(tmp_path: Path) -> None:
    """Prouve que le scanner sécurité ne peut pas omettre une racine définie par le contrat."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        'argv = ["bandit", "-r", "core/src", "core/scripts", "scripts"]\n',
    )
    assert "SCOPE_ROOT_OMITTED" in _codes(_scanner(repo, ("core/scripts",)))


def test_detecte_une_omission_dans_un_set_litteral(tmp_path: Path) -> None:
    """Prouve que le changement de collection ne contourne pas le contrôle des racines."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        'cibles = {"core/src", "core/scripts", "scripts"}\n',
    )
    assert "SCOPE_ROOT_OMITTED" in _codes(_scanner(repo, ("core/scripts",)))


def test_detecte_une_omission_dans_une_concatenation_litterale(tmp_path: Path) -> None:
    """Prouve que deux listes partielles concaténées restent contrôlées ensemble."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        'cibles = ["core/src"] + ["core/scripts"]\n',
    )
    assert "SCOPE_ROOT_OMITTED" in _codes(_scanner(repo, ("core/scripts",)))


def test_detecte_un_filtrage_par_comprehension_des_racines(tmp_path: Path) -> None:
    """Prouve qu'une compréhension filtrant racines est une omission dynamique visible."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        'cibles = tuple(r for r in racines if r != "tools/proof")\n',
    )
    assert "SCOPE_ROOT_OMITTED" in _codes(_scanner(repo, ("core/scripts",)))


def test_refuse_continue_on_error_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve qu'un job requis ne peut pas transformer son échec en succès souple."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n  tests:\n    continue-on-error: true\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
    )
    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_refuse_or_true_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve qu'une commande de job requis ne peut pas forcer artificiellement le succès."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n  security:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python core/scripts/run_security_scan.py || true\n",
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_or_true_dans_un_bloc_run_de_job_requis(tmp_path: Path) -> None:
    """Prouve que chaque ligne d'un scalaire YAML block est inspectée dans un job requis."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  security:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: |\n"
        "          python scripts/quality/no_stub_gate.py || true\n",
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_or_true_dans_un_bloc_run_de_job_non_requis(tmp_path: Path) -> None:
    """Prouve que l'inspection des blocs ne produit pas de faux positif hors contrat."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  rapport-optionnel:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: >-\n"
        "          python rapport.py || true\n",
    )
    assert _codes(_scanner(repo)) == set()
