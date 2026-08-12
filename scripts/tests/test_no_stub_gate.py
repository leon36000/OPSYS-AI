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


def test_refuse_une_fonction_dont_le_corps_est_pass(tmp_path: Path) -> None:
    """Prouve qu'un corps exécutable réduit à pass est interdit sur tout le périmètre."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "def calculer() -> None:\n    pass\n")
    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_une_fonction_dont_le_corps_est_ellipsis(tmp_path: Path) -> None:
    """Prouve qu'une ellipse exécutable ordinaire est reconnue comme un stub."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "def calculer() -> None:\n    ...\n")
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


def test_accepte_une_ellipse_dans_un_protocol(tmp_path: Path) -> None:
    """Prouve que la signature abstraite d'un Protocol reste une exception légitime."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n\nclass Depot(Protocol):\n    def lire(self) -> str:\n        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_une_ellipse_dans_une_methode_abstraite(tmp_path: Path) -> None:
    """Prouve qu'une méthode explicitement abstraite n'est pas prise pour un stub."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from abc import ABC, abstractmethod\n\n\nclass Depot(ABC):\n    @abstractmethod\n    def lire(self) -> str:\n        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_une_ellipse_dans_une_methode_ordinaire(tmp_path: Path) -> None:
    """Prouve que seule une abstraction reconnue peut employer une ellipse de corps."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Depot:\n    def lire(self) -> str:\n        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_type_ignore_ajoute_sans_justification(tmp_path: Path) -> None:
    """Prouve qu'une suppression de typage nouvelle exige une justification structurée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "valeur = inconnu  # type: ignore\n")
    assert "UNJUSTIFIED_SUPPRESSION" in _codes(_scanner(repo))


def test_detecte_le_retrait_de_tools_proof_du_scope_securite(tmp_path: Path) -> None:
    """Prouve que le scanner sécurité ne peut pas omettre une racine définie par le contrat."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "core/quality-scopes.toml",
        'python_roots = ["core/src", "core/scripts", "tools/proof", "scripts", ".opsys/tools/github-control"]\n'
        'target_required_job_ids = ["gates", "types", "tests", "security", "pack-validation", "proof-sealed"]\n',
    )
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        'argv = ["bandit", "-r", "core/src", "core/scripts", "scripts"]\n',
    )
    assert _scanner(repo, ("core/scripts",))


def test_detecte_le_retrait_du_controle_github_du_scope_codeql(tmp_path: Path) -> None:
    """Prouve que le scanner CodeQL ne peut pas exclure le contrôle GitHub contractuel."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "core/quality-scopes.toml",
        'python_roots = ["core/src", "core/scripts", "tools/proof", "scripts", ".opsys/tools/github-control"]\n'
        'target_required_job_ids = ["gates", "types", "tests", "security", "pack-validation", "proof-sealed"]\n',
    )
    _ecrire(
        repo,
        "core/scripts/run_codeql_scan.py",
        'sources = ["core/src", "core/scripts", "tools/proof", "scripts"]\n',
    )
    assert _scanner(repo, ("core/scripts",))


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


def test_accepte_les_memes_mecanismes_dans_un_job_non_requis(tmp_path: Path) -> None:
    """Prouve que la protection CI cible les jobs contractuels sans faux positif général."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n  rapport-optionnel:\n    continue-on-error: true\n    runs-on: ubuntu-latest\n    steps:\n      - run: python rapport.py || true\n",
    )
    assert _codes(_scanner(repo)) == set()
