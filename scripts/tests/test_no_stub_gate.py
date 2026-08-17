"""Cas RED du gate anti-stub et de protection qualité diff-aware."""

from __future__ import annotations

import subprocess
import tokenize
from pathlib import Path
from typing import Final

import pytest

from scripts.quality.no_stub_gate import (
    Violation,
    _violations_jobs_requis_absents,
    main,
    scan_repository,
)


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


def _ecrire_octets(repo: Path, chemin: str, contenu: bytes) -> Path:
    """Écrit des octets bruts sous le dépôt isolé du cas testé."""
    cible = repo / chemin
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(contenu)
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
    """Prouve qu'une levée de NotImplementedError ne masque pas une absence d'implémentation."""  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def calculer() -> int:\n    raise NotImplementedError\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
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


def test_refuse_un_fichier_de_production_syntaxiquement_invalide(
    tmp_path: Path,
) -> None:
    """Prouve que le fail-open précédent laissait un fichier corrompu échapper à TOUTES les règles, le défaut le plus grave possible pour un gate."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/invalide.py", "def casse(:\n")
    assert "FICHIER_NON_ANALYSABLE" in _codes(_scanner(repo))


def test_refuse_un_fichier_de_production_non_decodable_en_utf_8(
    tmp_path: Path,
) -> None:
    """Prouve que le fail-open précédent laissait un fichier corrompu échapper à TOUTES les règles, le défaut le plus grave possible pour un gate."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire_octets(repo, "src/invalide.py", b"\xff\xfe def a(): pass")
    assert "FICHIER_NON_ANALYSABLE" in _codes(_scanner(repo))


def test_refuse_continue_on_error_yes_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que le vocabulaire booléen YAML yes rend aussi un job requis souple."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n  tests:\n    continue-on-error: yes\n",
    )
    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_refuse_continue_on_error_on_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que le vocabulaire booléen YAML on rend aussi un job requis souple."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n  tests:\n    continue-on-error: on\n",
    )
    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_refuse_continue_on_error_dynamique_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve qu'une valeur dynamique indécidable statiquement est refusée, comportement fail-closed correct."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n  tests:\n    continue-on-error: ${{ inputs.x }}\n",
    )
    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_accepte_continue_on_error_false_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que la valeur booléenne YAML false ne transforme pas le job requis en succès souple."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n  tests:\n    continue-on-error: false\n",
    )
    assert "REQUIRED_JOB_SOFT_FAILURE" not in _codes(_scanner(repo))


def test_accepte_continue_on_error_yes_dans_un_job_non_requis(
    tmp_path: Path,
) -> None:
    """Prouve que la protection des erreurs souples reste limitée aux jobs requis du contrat."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n  rapport:\n    continue-on-error: yes\n",
    )
    assert "REQUIRED_JOB_SOFT_FAILURE" not in _codes(_scanner(repo))


def test_refuse_raise_builtins_not_implemented_error(tmp_path: Path) -> None:
    """Prouve qu'une forme qualifiée de NotImplementedError reste un stub explicite."""  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/qualifie.py",
        "import builtins\n\ndef calculer() -> int:\n    raise builtins.NotImplementedError\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_raise_not_implemented(tmp_path: Path) -> None:
    """Prouve que la sentinelle NotImplemented levée est reconnue comme un stub."""  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/qualifie.py",
        "def calculer() -> int:\n    raise NotImplemented\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_raise_not_implemented_appel(tmp_path: Path) -> None:
    """Prouve que la forme appelée de NotImplemented reste reconnue comme un stub."""  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/qualifie.py",
        "def calculer() -> int:\n    raise NotImplemented()\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_detecte_un_filtrage_compose_par_comprehension_des_racines(
    tmp_path: Path,
) -> None:
    """Prouve que le parcours descend dans un ast.BoolOp afin de voir chaque exclusion de racine."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        'cibles = tuple(r for r in racines if r != "tools/proof" and r != "scripts")\n',
    )
    assert "SCOPE_ROOT_OMITTED" in _codes(_scanner(repo, ("core/scripts",)))


def test_refuse_or_true_dans_action_composite_locale_dun_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve qu'un job requis ne délègue pas impunément un succès forcé à une action composite locale."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  security:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: ./.github/actions/controle\n",
    )
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - run: python controle.py || true\n",
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_or_true_dans_action_composite_locale_dun_job_non_requis(
    tmp_path: Path,
) -> None:
    """Prouve que l'inspection des actions composites locales reste limitée aux jobs requis."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  rapport:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: ./.github/actions/controle\n",
    )
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - run: python controle.py || true\n",
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_continue_on_error_yes_commente_et_indente_a_quatre_espaces(
    tmp_path: Path,
) -> None:
    """Prouve que PyYAML suit la sémantique réelle malgré indentation et commentaire inline, là où le parseur maison les calculait mal."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/a.yml",
        "jobs:\n"
        "    tests:\n"
        "        continue-on-error: yes # tolerance\n"
        "        runs-on: ubuntu-latest\n",
    )
    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_refuse_un_succes_force_coupe_apres_operateur_dans_bloc_run(
    tmp_path: Path,
) -> None:
    """Prouve qu'un bloc YAML est une chaîne unique et que la continuation après l'opérateur ne masque pas le succès forcé."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/b.yml",
        "jobs:\n"
        "  security:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: |\n"
        "          verif ||\n"
        "          true\n",
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_exit_zero_suivi_dune_autre_commande_dans_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve que exit 0 non conditionnel force le succès même lorsqu'une commande le suit."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/c.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: exit 0; echo suite\n",
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_workflow_yaml_invalide_en_fail_closed(tmp_path: Path) -> None:
    """Prouve qu'un workflow illisible est refusé plutôt que silencieusement ignoré par le gate."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/invalide.yml",
        "jobs:\n  gates:\n    steps: [\n",
    )
    assert "FICHIER_NON_ANALYSABLE" in _codes(_scanner(repo))


def test_accepte_continue_on_error_false_avec_contrat_de_jobs_requis(
    tmp_path: Path,
) -> None:
    """Prouve que la valeur YAML false ne produit pas de faux positif pour un job explicitement requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/faux.yml",
        "jobs:\n"
        "  gates:\n"
        "    continue-on-error: false\n"
        "    runs-on: ubuntu-latest\n",
    )
    assert "REQUIRED_JOB_SOFT_FAILURE" not in _codes(_scanner(repo))


def test_detecte_le_succes_force_dans_la_seconde_action_composite_locale(
    tmp_path: Path,
) -> None:
    """Prouve que la cascade A vers B appelée par un job requis est analysée et rapporte la violation sur B."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/actions.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: ./.github/actions/A\n",
    )
    _ecrire(
        repo,
        ".github/actions/A/action.yml",
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - uses: ./.github/actions/B\n",
    )
    _ecrire(
        repo,
        ".github/actions/B/action.yml",
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - run: verif || true\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    violations = _scanner(repo)
    assert any(
        violation.code == "REQUIRED_JOB_FORCED_SUCCESS"
        and violation.path == ".github/actions/B/action.yml"
        for violation in violations
    )


def test_detecte_un_cycle_dactions_composites_locales(tmp_path: Path) -> None:
    """Prouve qu'un cycle A vers B vers A est refusé explicitement sans boucle infinie."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/actions.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: ./.github/actions/A\n",
    )
    _ecrire(
        repo,
        ".github/actions/A/action.yml",
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - uses: ./.github/actions/B\n",
    )
    _ecrire(
        repo,
        ".github/actions/B/action.yml",
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - uses: ./.github/actions/A\n",
    )
    assert "LOCAL_ACTION_CYCLE" in _codes(_scanner(repo))


def test_accepte_la_meme_cascade_dactions_pour_un_job_non_requis(
    tmp_path: Path,
) -> None:
    """Prouve que la cascade locale dangereuse reste hors contrôle lorsqu'aucun job requis ne l'appelle."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/actions.yml",
        "jobs:\n"
        "  rapport:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: ./.github/actions/A\n",
    )
    _ecrire(
        repo,
        ".github/actions/A/action.yml",
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - uses: ./.github/actions/B\n",
    )
    _ecrire(
        repo,
        ".github/actions/B/action.yml",
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - run: verif || true\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_protocol_importe_sous_type_checking(tmp_path: Path) -> None:
    """Prouve que l'idiome de production TYPE_CHECKING conserve Protocol et évite de rendre le gate inutilisable."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/proto.py",
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from typing import Protocol\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_refuse_toujours_protocol_local_usurpe_sans_import_typing(
    tmp_path: Path,
) -> None:
    """Prouve que la collecte élargie des imports ne donne jamais une exemption à une classe locale homonyme."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/proto.py",
        "class Protocol:\n"
        "    valeur = 1\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_main_refuse_un_scope_partiel_et_nomme_les_racines_omises(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve qu'un appel CLI partiel ne peut pas réduire silencieusement le périmètre contractuel."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)

    code_retour = main(["--repo", str(repo), "--scope", "core/src"])

    sortie = capsys.readouterr().out
    assert code_retour == 1
    assert "SCOPE_ROOT_OMITTED" in sortie
    assert "core/scripts" in sortie
    assert "tools/proof" in sortie
    assert "scripts" in sortie
    assert ".opsys/tools/github-control" in sortie


def _workflow_de_tous_les_jobs_du_contrat(repo: Path) -> None:
    """Écrit la CI qui satisfait le contrat de `_contrat`, chaque job requis exécutant une commande.

    Sans elle, le dépôt du cas déclarerait six jobs requis sans en définir
    aucun : le gate le refuse à juste titre, et le code de retour ne mesurerait
    plus le périmètre mais l'absence de CI.
    """
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        + "".join(
            f"  {job}:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: python3 -m pytest\n"
            for job in (
                "gates",
                "types",
                "tests",
                "security",
                "pack-validation",
                "proof-sealed",
            )
        ),
    )


def test_main_sans_scope_utilise_toutes_les_racines_du_contrat(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve que l'absence de --scope sélectionne exactement le périmètre contractuel complet."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_de_tous_les_jobs_du_contrat(repo)

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert code_retour == 0
    assert "SCOPE_ROOT_OMITTED" not in sortie


def test_main_refuse_un_contrat_aux_racines_python_vides(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve qu'une liste vide annule le périmètre et doit donc être refusée explicitement."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "core/quality-scopes.toml",
        "python_roots = []\n"
        'target_required_job_ids = ["gates"]\n',
    )

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert code_retour == 1
    assert "CONTRAT_PERIMETRE_ABSENT" in sortie
    assert "python_roots est vide" in sortie


def test_main_refuse_un_contrat_aux_jobs_requis_vides(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve qu'une liste vide de jobs obligatoires invalide le contrat au lieu de désactiver les protections."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "core/quality-scopes.toml",
        'python_roots = ["core/src"]\n'
        "target_required_job_ids = []\n",
    )

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert code_retour == 1
    assert "CONTRAT_PERIMETRE_ABSENT" in sortie
    assert "target_required_job_ids est vide" in sortie


def test_refuse_une_condition_false_sur_un_job_requis(tmp_path: Path) -> None:
    """Prouve qu'une condition littéralement fausse peut neutraliser un job requis et est refusée."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/condition.yml",
        "jobs:\n"
        "  gates:\n"
        "    if: ${{ false }}\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_CONDITIONNEL" in _codes(_scanner(repo))


def test_accepte_always_comme_condition_dun_job_requis(tmp_path: Path) -> None:
    """Prouve que always() maintient l'exécution du contrôle requis sans faux positif."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/condition.yml",
        "jobs:\n"
        "  gates:\n"
        "    if: always()\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_CONDITIONNEL" not in _codes(_scanner(repo))


def test_accepte_une_condition_sur_un_job_non_requis(tmp_path: Path) -> None:
    """Prouve que la contrainte de condition reste limitée aux jobs définis comme requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/condition.yml",
        "jobs:\n"
        "  rapport:\n"
        "    if: ${{ false }}\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_CONDITIONNEL" not in _codes(_scanner(repo))


@pytest.mark.parametrize("valeur", ('"true"', "'yes'", '"on"'))
def test_refuse_continue_on_error_vrai_ecrit_comme_chaine_quotee(
    tmp_path: Path,
    valeur: str,
) -> None:
    """Prouve que les scalaires quotés vrais gardent leur sémantique de succès souple interdite."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/continue.yml",
        "jobs:\n"
        "  gates:\n"
        f"    continue-on-error: {valeur}\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_accepte_continue_on_error_false_ecrit_comme_chaine_quotee(
    tmp_path: Path,
) -> None:
    """Prouve qu'une chaîne quotée false ne déclenche pas la règle réservée aux tolérances réelles."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/continue.yml",
        "jobs:\n"
        "  gates:\n"
        '    continue-on-error: "false"\n'
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" not in _codes(_scanner(repo))


@pytest.mark.parametrize("levee", ("raise E", "raise E()"))
def test_refuse_un_alias_importe_de_not_implemented_error(
    tmp_path: Path,
    levee: str,
) -> None:
    """Prouve qu'un alias prouvé de builtins ne masque pas une absence explicite d'implémentation."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/alias.py",
        "from builtins import NotImplementedError as E\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        f"def calculer() -> int:\n    {levee}\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_accepte_un_filtre_litteral_sur_un_iterable_etranger_aux_racines(
    tmp_path: Path,
) -> None:
    """Prouve qu'un filtre métier sur utilisateurs ne doit pas être confondu avec une omission de racine."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_utilisateurs.py",
        'actifs = [u for u in utilisateurs if u != "admin"]\n',
    )

    assert "SCOPE_ROOT_OMITTED" not in _codes(_scanner(repo, ("core/scripts",)))


def test_detecte_toujours_un_filtre_litteral_sur_les_racines(
    tmp_path: Path,
) -> None:
    """Prouve que l'assouplissement pour les itérables métier conserve la détection des vraies racines."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        'cibles = [r for r in racines if r != "tools/proof"]\n',
    )

    assert "SCOPE_ROOT_OMITTED" in _codes(_scanner(repo, ("core/scripts",)))


def test_accepte_les_motifs_de_succes_force_dans_une_chaine_shell(
    tmp_path: Path,
) -> None:
    """Prouve que les opérateurs écrits dans un argument littéral ne sont pas interprétés comme du shell."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/shell.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: echo "pour forcer, certains écrivent || true"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_exit_zero_dans_une_chaine_shell(tmp_path: Path) -> None:
    """Prouve qu'un texte entre quotes contenant exit 0 ne neutralise pas réellement un job requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/shell.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo 'exit 0'\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_un_succes_force_place_hors_dune_chaine_shell(
    tmp_path: Path,
) -> None:
    """Prouve que neutraliser les quotes ne masque jamais un opérateur dangereux situé dans le code shell."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/shell.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: echo "x" && verif || true\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_protocol_importe_puis_reaffecte(tmp_path: Path) -> None:
    """Prouve qu'une réaffectation retire la preuve d'origine typing et ferme l'exemption d'ellipse."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/proto.py",
        "from typing import Protocol\n\n"
        "Protocol = object\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_un_protocol_importe_non_reaffecte(tmp_path: Path) -> None:
    """Prouve que le retrait d'alias réaffectés ne supprime pas l'exemption du véritable import intact."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/proto.py",
        "from typing import Protocol\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_refuse_protocol_ecrase_par_une_classe_module(tmp_path: Path) -> None:
    """Prouve qu'une classe module-level homonyme retire la preuve de typing.Protocol."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/a.py",
        "from typing import Protocol\n\n"
        "class Protocol:\n"
        "    valeur = 1\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_protocol_ecrase_par_une_fonction_module(tmp_path: Path) -> None:
    """Prouve qu'une fonction module-level homonyme retire aussi l'exemption Protocol."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/a.py",
        "from typing import Protocol\n\n"
        "def Protocol() -> object:\n"
        "    return object\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_protocol_importe_sans_ecrasement_module(tmp_path: Path) -> None:
    """Prouve que l'exemption reste ouverte lorsque l'alias typing.Protocol est intact."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/a.py",
        "from typing import Protocol\n\n"
        "class X(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_refuse_protocol_importe_localement_dans_une_fonction(tmp_path: Path) -> None:
    """Prouve qu'un import local ne fournit jamais une exemption globale non prouvée."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/b.py",
        "def fabriquer() -> object:\n"
        "    from typing import Protocol\n"
        "    return Protocol\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str:\n"
        "        ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_repli_echo_apres_or_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve qu'un echo après || absorbe l'échec du contrôle requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/a.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: verif || echo "gate en echec"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_repli_exit_un_apres_or_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que exit 1 propage l'échec au lieu de le transformer en succès."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/b.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: verif || exit 1\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_repli_printf_apres_or_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve qu'un printf après || absorbe également l'échec du contrôle requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/printf.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: verif || printf "echec"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_repli_deux_points_apres_or_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve que le builtin : après || force un succès interdit."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/colon.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: 'verif || :'\n",  # quoté : `|| :` non quoté rend le YAML invalide
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_repli_false_apres_or_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que false après || conserve un échec visible pour le job requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/false.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: verif || false\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_motif_de_succes_force_uniquement_dans_un_commentaire_shell(
    tmp_path: Path,
) -> None:
    """Prouve qu'un commentaire shell ne déclenche pas de détection de code dangereux."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/c.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "# ne pas utiliser || true"\n',  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_succes_force_avant_un_commentaire_shell(tmp_path: Path) -> None:
    """Prouve que le commentaire après || true ne masque pas le code déjà exécuté."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/commentaire.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: verif || true  # justification\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_succes_force_apres_diese_dans_une_chaine_shell(
    tmp_path: Path,
) -> None:
    """Prouve qu'un # littéral entre quotes ne commence pas un commentaire shell."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/couleur.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: \'echo "couleur #ff0000" && verif || true\'\n',  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_succes_force_apres_un_diese_colle_a_un_mot(
    tmp_path: Path,
) -> None:
    """Prouve qu'un # collé à un mot reste un caractère ordinaire du shell, jamais l'ouverture d'un commentaire."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/mot.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "python3 gate.py x#note || true"\n',  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_succes_force_apres_le_parametre_special_nombre_darguments(
    tmp_path: Path,
) -> None:
    """Prouve que le # de $# ne coupe pas la ligne : la borne est le caractère précédent, pas la seule classe des lettres."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/arguments.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "python3 gate.py $# || true"\n',  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_repli_cite_dans_un_commentaire_shell_ouvert_apres_un_espace(
    tmp_path: Path,
) -> None:
    """Prouve que le commentaire ouvert en milieu de ligne après un espace neutralise toujours sa fin de ligne."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/espace.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py  # commentaire avec || true dedans"\n',  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_un_repli_cite_dans_un_commentaire_ouvert_apres_un_point_virgule(
    tmp_path: Path,
) -> None:
    """Prouve que les séparateurs de commandes ouvrent aussi un mot, donc un commentaire, exactement comme le shell."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/separateur.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py;# commentaire avec || true dedans"\n',  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_exit_zero_dans_un_if_shell_sur_une_ligne(tmp_path: Path) -> None:
    """Prouve qu'un exit 0 protégé par if sur une ligne n'est pas un succès forcé nu."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/d.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: if true; then exit 0; fi\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_exit_zero_nu_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve qu'un exit 0 sans garde conditionnelle force toujours un succès interdit."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/exit.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: exit 0\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_workflow_yaml_a_racine_liste(tmp_path: Path) -> None:
    """Prouve qu'une racine YAML liste ne peut pas être analysée comme un workflow."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(repo, ".github/workflows/e.yml", "- jobs\n- gates\n")

    assert "FICHIER_NON_ANALYSABLE" in _codes(_scanner(repo))


def test_refuse_workflow_avec_jobs_texte(tmp_path: Path) -> None:
    """Prouve que jobs doit être un mapping pour établir les protections requises."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(repo, ".github/workflows/f.yml", 'jobs: "texte"\n')

    assert "FICHIER_NON_ANALYSABLE" in _codes(_scanner(repo))


def test_accepte_workflow_sans_cle_jobs(tmp_path: Path) -> None:
    """Prouve qu'un document YAML sans jobs ne produit pas de faux positif structurel."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(repo, ".github/workflows/g.yml", "name: information\non: push\n")

    assert "FICHIER_NON_ANALYSABLE" not in _codes(_scanner(repo))


def test_refuse_un_job_requis_defini_comme_chaine(tmp_path: Path) -> None:
    """Prouve qu'un job requis réduit à un scalaire n'est plus ignoré en silence."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(repo, ".github/workflows/h.yml", "jobs:\n  gates: disabled\n")

    assert "REQUIRED_JOB_STRUCTURE_INVALIDE" in _codes(_scanner(repo))


def test_refuse_un_job_requis_defini_comme_null(tmp_path: Path) -> None:
    """Prouve qu'un job requis vidé de sa définition est refusé au lieu d'être sauté."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(repo, ".github/workflows/i.yml", "jobs:\n  gates:\n")

    assert "REQUIRED_JOB_STRUCTURE_INVALIDE" in _codes(_scanner(repo))


def test_refuse_un_job_requis_dont_les_etapes_ne_sont_pas_une_liste(
    tmp_path: Path,
) -> None:
    """Prouve qu'un champ steps non liste rend le job requis inanalysable, donc refusé."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/j.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps: aucune\n",
    )

    assert "REQUIRED_JOB_STRUCTURE_INVALIDE" in _codes(_scanner(repo))


def test_accepte_un_job_non_requis_defini_comme_chaine(tmp_path: Path) -> None:
    """Prouve que le refus structurel reste borné aux identifiants du contrat."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(repo, ".github/workflows/k.yml", "jobs:\n  rapport-optionnel: disabled\n")

    assert "REQUIRED_JOB_STRUCTURE_INVALIDE" not in _codes(_scanner(repo))


def test_accepte_un_job_requis_dont_les_etapes_sont_une_liste(tmp_path: Path) -> None:
    """Prouve que la forme normale d'un job requis ne déclenche aucun refus structurel."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/l.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 -m pytest\n",
    )

    assert "REQUIRED_JOB_STRUCTURE_INVALIDE" not in _codes(_scanner(repo))


def _contrat_deux_jobs(repo: Path) -> None:
    """Écrit un contrat réduit à deux jobs requis pour mesurer leur couverture réelle."""
    _ecrire(
        repo,
        "core/quality-scopes.toml",
        'python_roots = ["src"]\n'
        'target_required_job_ids = ["gates", "types"]\n',
    )


def _workflow_dun_job(repo: Path, chemin: str, job: str) -> None:
    """Écrit un workflow minimal définissant un unique job exécutant une vraie commande."""
    _ecrire(
        repo,
        chemin,
        "jobs:\n"
        f"  {job}:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 -m pytest\n",
    )


def test_main_refuse_un_job_requis_absent_de_tous_les_workflows(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve qu'un identifiant requis sans job correspondant est un gate absent, donc refusé."""
    repo = _depot_git_initialise(tmp_path)
    _contrat_deux_jobs(repo)
    _workflow_dun_job(repo, ".github/workflows/ci.yml", "gates")

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert code_retour == 1
    assert "REQUIRED_JOB_ABSENT" in sortie
    assert "types" in sortie


def test_main_accepte_un_job_requis_defini_dans_un_autre_workflow(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve que la couverture des jobs requis est mesurée sur tous les workflows du dépôt."""
    repo = _depot_git_initialise(tmp_path)
    _contrat_deux_jobs(repo)
    _workflow_dun_job(repo, ".github/workflows/ci.yml", "gates")
    _workflow_dun_job(repo, ".github/workflows/core-ci.yml", "types")

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert code_retour == 0
    assert "REQUIRED_JOB_ABSENT" not in sortie


def test_main_refuse_les_deux_jobs_requis_absents_dans_une_seule_violation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve que chaque identifiant requis manquant est nommé dans la sortie du gate."""
    repo = _depot_git_initialise(tmp_path)
    _contrat_deux_jobs(repo)
    _workflow_dun_job(repo, ".github/workflows/ci.yml", "rapport-optionnel")

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert code_retour == 1
    assert "REQUIRED_JOB_ABSENT" in sortie
    assert "gates" in sortie
    assert "types" in sortie


def _workflow_commande_requise(repo: Path, chemin: str, commande: str) -> None:
    """Écrit un job requis dont l'unique étape exécute la commande shell mesurée."""
    _ecrire(
        repo,
        chemin,
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - run: {commande}\n",
    )


def test_refuse_exit_zero_apres_un_fi_sur_la_meme_ligne(tmp_path: Path) -> None:
    """Prouve qu'un exit 0 placé après la fermeture d'un if monoligne s'exécute toujours."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise(
        repo,
        ".github/workflows/m.yml",
        "if false; then :; fi; exit 0",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_exit_zero_apres_la_fermeture_dune_conditionnelle_multiligne(
    tmp_path: Path,
) -> None:
    """Prouve qu'un fi suivi d'un exit 0 sur sa ligne ne masque pas le contournement."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/n.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: |\n"
        "          if false; then\n"
        "            echo garde\n"
        "          fi; exit 0\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_exit_zero_apres_une_option_contenant_le_mot_case(
    tmp_path: Path,
) -> None:
    """Prouve qu'un mot-clé shell en option longue n'ouvre aucune garde conditionnelle."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise(
        repo,
        ".github/workflows/o.yml",
        "grep --ignore-case motif fichier; exit 0",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_exit_zero_apres_une_option_contenant_le_mot_if(
    tmp_path: Path,
) -> None:
    """Prouve qu'une option longue contenant if ne peut pas faire passer un exit 0 pour gardé."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise(
        repo,
        ".github/workflows/p.yml",
        "psql --if-exists --dbname base; exit 0",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_exit_zero_dans_le_second_if_dune_meme_ligne(tmp_path: Path) -> None:
    """Prouve qu'un exit 0 réellement encadré par une seconde garde reste accepté."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise(
        repo,
        ".github/workflows/q.yml",
        "if true; then echo a; fi; if false; then exit 0; fi",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "levee",
    ("raise builtins.NotImplemented", "raise builtins.NotImplemented()"),  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
)
def test_refuse_la_sentinelle_not_implemented_qualifiee(
    tmp_path: Path,
    levee: str,
) -> None:
    """Prouve que la sentinelle qualifiée est un stub au même titre que sa forme simple."""  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/sentinelle.py",
        f"import builtins\n\ndef calculer() -> int:\n    {levee}\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_accepte_un_attribut_homonyme_qui_nest_pas_une_levee(tmp_path: Path) -> None:
    """Prouve que le refus vise la levée elle-même et non tout attribut du même nom."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/registre.py",
        "import builtins\n\n"
        "def decrire() -> str:\n"
        "    return repr(builtins.NotImplemented)\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "NOT_IMPLEMENTED_STUB" not in _codes(_scanner(repo))


def _workflow_commande_requise_citee(repo: Path, chemin: str, commande: str) -> None:
    """Écrit un job requis dont l'unique étape cite sa commande, accolades comprises.

    La citation YAML est indispensable ici : les commandes mesurées contiennent
    des indicateurs de flux qu'un scalaire nu rendrait ambigus.
    """
    citee = commande.replace("'", "''")
    _ecrire(
        repo,
        chemin,
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - run: '{citee}'\n",
    )


def test_refuse_un_groupe_daccolades_de_repli_apres_or_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve qu'un groupe { … } derrière || absorbe l'échec du contrôle requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/n.yml",
        "python3 gate.py || { :; }",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_groupe_de_parentheses_de_repli_apres_or_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve que le sous-shell ( … ) neutralise l'échec exactement comme { … }."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/o.yml",
        "python3 gate.py || ( : )",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_groupe_de_repli_qui_journalise_sans_propager_lechec(
    tmp_path: Path,
) -> None:
    """Prouve qu'un groupe de repli qui se contente de journaliser reste un contournement."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/p.yml",
        'python3 gate.py || { echo "gate ignoré" >&2; }',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_groupe_de_repli_termine_par_exit_zero(tmp_path: Path) -> None:
    """Prouve qu'une sortie nulle en fin de groupe reste une absorption de l'échec."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/q.yml",
        'python3 gate.py || { echo "toléré"; exit 0; }',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_groupe_de_repli_dont_la_sortie_nulle_est_gardee(
    tmp_path: Path,
) -> None:
    """Prouve le refus par la règle des groupes seule, hors portée de la garde exit 0.

    La sortie nulle est ici conditionnelle, donc acceptée par
    ``_contient_exit_zero_non_garde`` : seule l'analyse du groupe de repli
    constate que l'étape se termine malgré tout en succès.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/ab.yml",
        "python3 gate.py || ( if true; then exit 0; fi )",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_groupe_de_repli_contenant_une_substitution_de_commande(
    tmp_path: Path,
) -> None:
    """Prouve que les parenthèses internes de $( … ) ne referment pas le groupe trop tôt."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/r.yml",
        "python3 gate.py || { echo $(date); }",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_groupe_apres_or_termine_par_exit_non_nul(tmp_path: Path) -> None:
    """Prouve qu'un groupe qui sort en non nul propage l'échec et n'est donc pas signalé."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/s.yml",
        'python3 gate.py || { echo "échec du gate" >&2; exit 1; }',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_un_groupe_apres_or_termine_par_false(tmp_path: Path) -> None:
    """Prouve que false en fin de groupe propage l'échec autant qu'un exit non nul."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/t.yml",
        'python3 gate.py || { echo "échec du gate" >&2; false; }',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_un_groupe_de_repli_ecrit_dans_une_chaine_shell(tmp_path: Path) -> None:
    """Prouve que le motif cité dans une chaîne shell reste une donnée, pas du code."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/u.yml",
        'python3 gate.py && echo "interdit : cmd || { :; }"',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_un_job_requis_dont_la_liste_detapes_est_vide(tmp_path: Path) -> None:
    """Prouve qu'un job requis à steps vide est un gate désarmé, pas un job valide."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/v.yml",
        "jobs: {gates: {runs-on: ubuntu-latest, steps: []}}\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_refuse_un_job_requis_dont_la_seule_etape_est_nulle(tmp_path: Path) -> None:
    """Prouve qu'une étape nulle n'est pas silencieusement sautée sur un job requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/w.yml",
        "jobs: {gates: {runs-on: ubuntu-latest, steps: [null]}}\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_refuse_un_job_requis_dont_aucune_etape_nexecute_run_ou_uses(
    tmp_path: Path,
) -> None:
    """Prouve qu'une étape sans run ni uses n'exécute aucun contrôle et ne compte pas."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/x.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: étape décorative\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_refuse_un_job_requis_sans_steps_ni_uses(tmp_path: Path) -> None:
    """Prouve qu'un job requis dépourvu de steps et de uses n'exécute rien du tout."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/y.yml",
        "jobs:\n  gates:\n    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_accepte_un_job_requis_appelant_un_workflow_reutilisable_sans_steps(
    tmp_path: Path,
) -> None:
    """Prouve que l'appel d'un workflow réutilisable reste une exécution légitime."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/z.yml",
        "jobs:\n  gates:\n    uses: ./.github/workflows/reutilisable.yml\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" not in _codes(_scanner(repo))


def test_accepte_un_job_non_requis_dont_la_liste_detapes_est_vide(
    tmp_path: Path,
) -> None:
    """Prouve que le refus des jobs vides reste borné aux identifiants du contrat."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/aa.yml",
        "jobs: {rapport-optionnel: {runs-on: ubuntu-latest, steps: []}}\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" not in _codes(_scanner(repo))


def _job_requis_delegue(repo: Path, reference: str = "./.github/actions/controle") -> None:
    """Écrit un job requis dont la seule étape délègue à une action locale."""
    _ecrire(
        repo,
        ".github/workflows/delegation.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: {reference}\n",
    )


def test_refuse_une_action_composite_locale_sans_aucune_etape(tmp_path: Path) -> None:
    """Prouve qu'un job requis délégant à une action composite vide n'exécute rien, comme un job requis sans étape."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo)
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n  using: composite\n  steps: []\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_refuse_une_action_composite_locale_aux_etapes_decoratives(
    tmp_path: Path,
) -> None:
    """Prouve qu'une étape d'action composite réduite à un name n'exécute aucun contrôle."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo)
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n  using: composite\n  steps:\n    - name: decor\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_refuse_une_action_composite_locale_depourvue_de_cle_steps(
    tmp_path: Path,
) -> None:
    """Prouve qu'une action composite sans steps du tout tombe sous la même exigence que la liste vide."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo)
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n  using: composite\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_accepte_une_action_composite_locale_avec_une_etape_reelle(
    tmp_path: Path,
) -> None:
    """Prouve que l'exigence d'étape effective ne signale pas l'action composite qui exécute réellement un contrôle."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo)
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n  using: composite\n  steps:\n    - run: verif\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" not in _codes(_scanner(repo))


def test_accepte_une_action_composite_qui_delegue_a_une_action_locale_reelle(
    tmp_path: Path,
) -> None:
    """Prouve qu'un uses vers une autre action locale compte comme étape effective, la profondeur restant suivie."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo, "./.github/actions/A")
    _ecrire(
        repo,
        ".github/actions/A/action.yml",
        "runs:\n  using: composite\n  steps:\n    - uses: ./.github/actions/B\n",
    )
    _ecrire(
        repo,
        ".github/actions/B/action.yml",
        "runs:\n  using: composite\n  steps:\n    - run: verif\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" not in _codes(_scanner(repo))


def test_accepte_une_action_locale_javascript_sans_steps(tmp_path: Path) -> None:
    """Prouve qu'une action node20 est valide sans steps et n'est pas confondue avec une composite vide."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo)
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n  using: node20\n  main: index.js\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" not in _codes(_scanner(repo))


def test_accepte_une_action_locale_docker_sans_steps(tmp_path: Path) -> None:
    """Prouve que l'action docker, elle aussi dépourvue de steps par nature, reste acceptée."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo)
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n  using: docker\n  image: Dockerfile\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" not in _codes(_scanner(repo))


def test_accepte_une_action_composite_vide_appelee_par_un_job_non_requis(
    tmp_path: Path,
) -> None:
    """Prouve que l'exigence d'étape effective reste bornée aux ids requis du contrat."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/delegation.yml",
        "jobs:\n"
        "  rapport-optionnel:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: ./.github/actions/controle\n",
    )
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n  using: composite\n  steps: []\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" not in _codes(_scanner(repo))


def _tokenisation_impossible(readline: object) -> object:
    """Simule un flux dont la tokenisation casse là où l'analyse AST a réussi.

    Aucune source réelle acceptée par ``ast.parse`` et refusée par ``tokenize``
    n'a pu être construite sur CPython 3.12 ; l'exception est donc injectée,
    ce qui mesure exactement la branche de repli du gate.
    """
    raise tokenize.TokenError("EOF in multi-line statement", (3, 0))


def test_refuse_un_fichier_dont_la_tokenisation_echoue(tmp_path: Path) -> None:
    """Prouve qu'un fichier intokenisable est une violation, jamais un silence."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "valeur = 1\n")

    with pytest.MonkeyPatch.context() as contexte:
        contexte.setattr(tokenize, "generate_tokens", _tokenisation_impossible)
        violations = _scanner(repo)

    assert "FICHIER_NON_ANALYSABLE" in _codes(violations)


def test_signale_la_ligne_rapportee_par_lechec_de_tokenisation(tmp_path: Path) -> None:
    """Prouve que la position rendue par tokenize est reportée dans la violation."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "valeur = 1\n")

    with pytest.MonkeyPatch.context() as contexte:
        contexte.setattr(tokenize, "generate_tokens", _tokenisation_impossible)
        violations = _scanner(repo)

    lignes = {
        violation.line
        for violation in violations
        if violation.code == "FICHIER_NON_ANALYSABLE"
    }
    assert lignes == {3}


def test_base_ref_option_est_refuse_avant_tout_appel_git(tmp_path, monkeypatch) -> None:
    """Un pseudo-ref Git ne doit jamais franchir la frontière subprocess."""
    from scripts.quality import no_stub_gate as gate

    fichier = tmp_path / "module.py"
    contenu = "def fonction():\n    return 1\n"
    fichier.write_text(contenu, encoding="utf-8")

    def subprocess_interdit(*_args, **_kwargs):
        pytest.fail("un --base-ref non fiable a atteint subprocess")

    monkeypatch.setattr(gate.subprocess, "run", subprocess_interdit)
    with pytest.raises(ValueError, match="base-ref"):
        gate._lignes_du_diff(tmp_path, fichier, "--stat", contenu)


def _sortie_git(repo: Path, *arguments: str) -> str:
    """Exécute git et retourne sa sortie, tout échec devenant une erreur explicite."""
    resultat = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return resultat.stdout.strip()


def _commiter_sans_hook(repo: Path, message: str) -> None:
    """Commite l'index par la plomberie Git, qui n'exécute aucun hook local.

    Les fixtures de ces cas contiennent volontairement des stubs : un
    ``git commit`` ordinaire serait refusé par les hooks qualité de la machine.
    ``write-tree`` puis ``commit-tree`` et ``update-ref`` produisent le même
    historique réel sans passer par eux.
    """
    _executer_git(repo, "add", "--all")
    arbre = _sortie_git(repo, "write-tree")
    parent = _sortie_git(repo, "rev-parse", "HEAD")
    commit = _sortie_git(repo, "commit-tree", arbre, "-p", parent, "-m", message)
    _executer_git(repo, "update-ref", "HEAD", commit)


def test_un_stub_preexistant_non_modifie_reste_refuse_choix_delibere(
    tmp_path: Path,
) -> None:
    """Verrouille le partage délibéré : _analyser_stubs juge l'ÉTAT, pas le diff.

    Le fichier est commité puis laissé intact : aucune de ses lignes n'appartient
    au diff, ce que prouve le silence de la règle diff-aware sur son marqueur de
    dette. Le stub, lui, doit rester refusé. Filtrer _analyser_stubs par le diff
    laisserait vivre indéfiniment toute dette déjà commitée : ce test rougit
    précisément si quelqu'un aligne cette règle sur les règles diff-aware.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "# " + "TO" + "DO traiter ce cas\ndef calculer() -> None:\n    pass\n",
    )
    _commiter_sans_hook(repo, "stub préexistant")

    codes = _codes(_scanner(repo))
    assert "FORBIDDEN_MARKER" not in codes
    assert "EXECUTABLE_PASS" in codes


def test_une_racine_omise_preexistante_non_modifiee_reste_refusee_choix_delibere(
    tmp_path: Path,
) -> None:
    """Verrouille le même partage pour _analyser_omissions_racines, jugée sur l'ÉTAT.

    Une racine contractuelle absente du lanceur sécurité est un trou de périmètre
    permanent, pas un ajout : le filtrer par le diff le rendrait invisible dès le
    commit suivant. Le silence de la règle diff-aware sur le marqueur de dette du
    même fichier prouve que rien de ce fichier n'appartient au diff mesuré.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        "# " + "TO" + "DO traiter ce cas\n"
        'argv = ["bandit", "-r", "core/src", "core/scripts", "scripts"]\n',
    )
    _commiter_sans_hook(repo, "périmètre incomplet préexistant")

    codes = _codes(_scanner(repo, ("core/scripts",)))
    assert "FORBIDDEN_MARKER" not in codes
    assert "SCOPE_ROOT_OMITTED" in codes


def test_un_marqueur_de_dette_preexistant_non_modifie_reste_accepte_choix_delibere(
    tmp_path: Path,
) -> None:
    """Verrouille l'autre moitié du partage : les marqueurs ne jugent QUE les ajouts.

    Un marqueur de dette est un ajout de dette, pas un état : ne juger que les
    lignes ajoutées évite de bloquer sur l'historique. Ce test rougit si quelqu'un
    étend cette règle à tout le dépôt.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "# " + "TO" + "DO traiter ce cas\nvaleur = 1\n",
    )
    _commiter_sans_hook(repo, "marqueur de dette préexistant")

    assert "FORBIDDEN_MARKER" not in _codes(_scanner(repo))


def _workflow_run(job: str, lignes: tuple[str, ...]) -> str:
    """Assemble un workflow dont l'unique étape exécute le bloc shell donné."""
    corps = "".join(f"          {ligne}\n" for ligne in lignes)
    return (
        "jobs:\n"
        f"  {job}:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: |\n" + corps
    )


def test_refuse_une_condition_de_negation_qui_absorbe_lechec_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve qu'une garde ``if !`` exempte le contrôle d'errexit puis avale son échec.

    La commande testée par ``if !`` n'est jamais soumise à ``set -e`` : c'est la
    branche ``then`` qui fixe le code de retour de l'étape. Réduite à ``:``, elle
    réussit, donc le job requis est vert alors que le contrôle a échoué.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if ! python3 core/scripts/run_security_scan.py; then",
                "  :",
                "fi",
            ),
        ),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_une_condition_de_negation_qui_journalise_sans_propager(
    tmp_path: Path,
) -> None:
    """Prouve que journaliser l'échec ne le propage pas : la branche réussit quand même."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if ! python3 core/scripts/run_security_scan.py; then",
                "  echo 'scan ignoré' >&2",
                "fi",
            ),
        ),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_une_condition_de_negation_qui_propage_lechec(tmp_path: Path) -> None:
    """Prouve que la borne est la propagation, jamais la forme : ``exit 1`` reste licite."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if ! test -f rapport.json; then",
                "  exit 1",
                "fi",
            ),
        ),
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_une_condition_de_negation_absorbante_dans_un_job_non_requis(
    tmp_path: Path,
) -> None:
    """Prouve que le durcissement reste borné aux identifiants du contrat."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "rapport-optionnel",
            (
                "if ! python3 rapport.py; then",
                "  :",
                "fi",
            ),
        ),
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_un_controle_du_depot_en_condition_if_sans_negation(
    tmp_path: Path,
) -> None:
    """Prouve que retirer le ``!`` ne suffit plus à contourner la garde ``if !``.

    Quand le contrôle échoue, la branche ``then`` n'est pas prise ; sans ``else``
    rien ne s'exécute et le ``fi`` rend 0. L'étape est verte alors que le contrôle
    requis a échoué : l'échec est absorbé exactement comme avec la négation, pour
    un caractère de moins dans le workflow.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if python3 core/scripts/run_security_scan.py; then",
                "  :",
                "fi",
            ),
        ),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_controle_du_depot_en_condition_if_qui_journalise_sans_propager(
    tmp_path: Path,
) -> None:
    """Prouve que la branche ``then`` prise au SUCCÈS ne rachète pas l'échec absorbé."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if python3 core/scripts/run_security_scan.py; then",
                "  echo ok",
                "fi",
            ),
        ),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "invocation",
    (
        "python3 gate.py",
        "bash verifier.sh",
        "bash scripts/quality/verifier.sh",
        "./tools/proof/verifier --strict",
        "core/scripts/verify_proof_sealed.py --min-vendors 3",
    ),
    ids=(
        "suffixe-py",
        "suffixe-sh",
        "racine-scripts",
        "racine-tools",
        "racine-core-scripts",
    ),
)
def test_refuse_tout_script_du_depot_en_condition_if_sans_negation(
    tmp_path: Path, invocation: str
) -> None:
    """Prouve que le critère porte sur le SCRIPT DU DÉPÔT, pas sur l'interpréteur.

    Chaque cas isole UNE marque du dépôt : le suffixe ``.py`` seul, le suffixe
    ``.sh`` seul, puis les racines ``scripts/``, ``tools/`` et ``core/scripts/``.
    Aucune n'est couverte par une autre — supprimer un seul de ces critères laisse
    donc un cas rouge, et non un contournement silencieux.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", (f"if {invocation}; then", "  :", "fi")),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_controle_en_condition_if_dont_le_else_propage_lechec(
    tmp_path: Path,
) -> None:
    """Prouve que la borne reste la propagation : le ``else`` rend l'échec au job.

    Sur un ``if`` sans négation, la branche exécutée quand le contrôle échoue est
    le ``else`` ; s'il sort en non nul, l'étape échoue comme sans conditionnelle.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if python3 core/scripts/run_security_scan.py; then",
                "  echo ok",
                "else",
                "  exit 1",
                "fi",
            ),
        ),
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_laiguillage_par_test_shell_du_job_proof_sealed(
    tmp_path: Path,
) -> None:
    """Verrouille la forme LÉGITIME réellement utilisée par le job requis proof-sealed.

    ``[ -z "$X" ]`` est un aiguillage sur une variable, pas un contrôle dont
    l'échec importerait : le contrôle réel s'exécute après le ``fi``, soumis à
    ``errexit``. Ce test rougit si la règle des ``if`` sans négation déborde sur
    les tests shell et casse le workflow du dépôt.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "proof-sealed",
            (
                'if [ -z "$CODE_CHANGE" ]; then',
                '  echo "Aucun changement sous le périmètre scellé"',
                "  exit 0",
                "fi",
                'python3 core/scripts/verify_proof_sealed.py "${ARGS[@]}"',
            ),
        ),
    )
    assert _codes(_scanner(repo)) == set()


@pytest.mark.parametrize(
    ("condition", "corps"),
    (
        ("command -v docker", "echo présent"),
        ("git diff --quiet", "echo rien"),
        ("grep -q motif fichier", "echo trouvé"),
        ('[[ -n "$RUNNER_OS" ]]', "echo os"),
        ("test -f rapport.json", "echo rapport"),
        ("[ -f core/scripts/verify_proof_sealed.py ]", "echo présent"),
        ("grep -q motif scripts/quality/no_stub_gate.py", "echo trouvé"),
    ),
    ids=(
        "command-v",
        "git-diff",
        "grep",
        "crochet-double",
        "test-f",
        "crochet-sur-un-script-du-depot",
        "grep-sur-un-script-du-depot",
    ),
)
def test_accepte_les_sondes_shell_en_condition_if_sans_negation(
    tmp_path: Path, condition: str, corps: str
) -> None:
    """Prouve que les sondes shell restent hors règle, même en nommant un script du dépôt.

    ``[``, ``[[``, ``test``, ``command``, ``grep`` et ``git`` interrogent un état ;
    leur code de retour EST la question posée, jamais le verdict d'un contrôle
    absorbé. Les deux derniers cas prouvent que citer un chemin du dépôt en
    ARGUMENT d'une sonde ne vaut pas l'invoquer.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", (f"if {condition}; then", f"  {corps}", "fi")),
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_un_controle_if_absorbant_dans_un_job_non_requis(
    tmp_path: Path,
) -> None:
    """Prouve que la nouvelle règle reste bornée aux identifiants du contrat."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "rapport-optionnel",
            (
                "if python3 core/scripts/run_security_scan.py; then",
                "  :",
                "fi",
            ),
        ),
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_set_plus_e_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que désarmer errexit rend vert tout ce qui échoue ensuite dans l'étape."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "set +e",
                "python3 core/scripts/run_security_scan.py",
                "echo terminé",
            ),
        ),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_set_plus_o_errexit_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que la forme longue ``+o errexit`` désarme la même garantie."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "set +o errexit",
                "python3 core/scripts/run_security_scan.py",
            ),
        ),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_set_moins_e_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que le durcissement vise le ``+`` : armer errexit reste la bonne pratique."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "set -e",
                "python3 core/scripts/run_security_scan.py",
            ),
        ),
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_set_plus_x_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que seule l'option errexit est visée : couper la trace ne masque aucun échec."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "set +x",
                "python3 core/scripts/run_security_scan.py",
            ),
        ),
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_un_skipif_ajoute(tmp_path: Path) -> None:
    """Prouve que la condition de saut est un saut : le test ajouté ne s'exécute pas."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest\n\n\n"
        "@pytest.mark.skipif(True, reason='indisponible')\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_skip_if_unittest_ajoute(tmp_path: Path) -> None:
    """Prouve que la variante unittest du saut conditionnel est refusée à égalité."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import unittest\n\n\n"
        "@unittest.skipIf(True, 'indisponible')\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_skip_unless_unittest_ajoute(tmp_path: Path) -> None:
    """Prouve que la négation de la même dette ne crée pas un échappatoire."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import unittest\n\n\n"
        "@unittest.skipUnless(False, 'indisponible')\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_xfail_appele_dans_le_corps(tmp_path: Path) -> None:
    """Prouve que l'échec attendu déclaré depuis le corps est aussi une dette ajoutée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest\n\n\n"
        "def test_calcul() -> None:\n"
        "    pytest.xfail('connu cassé')\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_importorskip_ajoute(tmp_path: Path) -> None:
    """Prouve que le saut conditionné à un import est un saut, donc une dette ajoutée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest\n\n\n"
        "def test_calcul() -> None:\n"
        "    pytest.importorskip('yaml')\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_accepte_un_saut_homonyme_sur_un_autre_objet(tmp_path: Path) -> None:
    """Prouve que la règle reste qualifiée par le module et n'attrape pas un homonyme."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "def test_calcul() -> None:\n"
        "    lecteur.skipIf(True)\n"
        "    assert lecteur.position == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


def test_refuse_une_absence_dimplementation_au_niveau_module(tmp_path: Path) -> None:
    """Prouve que l'absence d'implémentation est jugée partout, pas seulement en fonction.

    Un module qui lève cette exception à l'import échoue précisément par absence
    d'implémentation : le scanner limité aux corps de fonctions ne voyait rien.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "raise NotImplementedError('module non livré')\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_une_absence_dimplementation_dans_un_corps_de_classe(
    tmp_path: Path,
) -> None:
    """Prouve que le corps d'une classe est un lieu d'exécution comme un autre."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Depot:\n    raise NotImplementedError('classe non livrée')\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_une_absence_dimplementation_dans_un_bloc_module(tmp_path: Path) -> None:
    """Prouve que les blocs module — condition, boucle, try — sont bien parcourus."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import sys\n\nif sys.platform == 'win32':\n"
        "    raise NotImplementedError('plateforme non livrée')\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_accepte_une_levee_module_dune_autre_exception(tmp_path: Path) -> None:
    """Prouve que la règle vise l'absence d'implémentation, pas toute levée module."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import sys\n\nif sys.platform == 'win32':\n"
        "    raise RuntimeError('plateforme refusée par contrat')\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_ne_compte_quune_fois_une_absence_dimplementation_en_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que l'extension hors fonction ne double pas la violation déjà rendue."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def calculer() -> int:\n    raise NotImplementedError\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )
    violations = _scanner(repo)
    assert [v.code for v in violations] == ["NOT_IMPLEMENTED_STUB"]


def test_accepte_une_ellipse_dans_un_protocol_generique(tmp_path: Path) -> None:
    """Prouve qu'un Protocol paramétré reste une abstraction, non un stub.

    ``Protocol[T]`` est un ``ast.Subscript`` : la base n'était pas reconnue et
    toutes les méthodes d'une interface générique parfaitement légitime étaient
    refusées.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol, TypeVar\n\n"
        "T = TypeVar('T')\n\n\n"
        "class Depot(Protocol[T]):\n"
        "    def lire(self) -> T:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_une_ellipse_dans_un_protocol_qualifie_generique(
    tmp_path: Path,
) -> None:
    """Prouve que la forme qualifiée typing.Protocol[T] est reconnue à égalité."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing\n\n"
        "T = typing.TypeVar('T')\n\n\n"
        "class Depot(typing.Protocol[T]):\n"
        "    def lire(self) -> T:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_une_ellipse_dans_un_protocol_alias_generique(tmp_path: Path) -> None:
    """Prouve que l'alias d'import reste prouvé sous la forme paramétrée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol as P, TypeVar\n\n"
        "T = TypeVar('T')\n\n\n"
        "class Depot(P[T]):\n"
        "    def lire(self) -> T:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_une_ellipse_dans_un_protocol_combine_a_generic(
    tmp_path: Path,
) -> None:
    """Prouve que la combinaison Generic[T] + Protocol[T] reste une abstraction."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Generic, Protocol, TypeVar\n\n"
        "T = TypeVar('T')\n\n\n"
        "class Depot(Generic[T], Protocol[T]):\n"
        "    def lire(self) -> T:\n"
        "        ...\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_une_ellipse_dans_une_classe_generique_non_protocol(
    tmp_path: Path,
) -> None:
    """Prouve que le correctif reste borné : Generic[T] seul n'est pas une abstraction."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Generic, TypeVar\n\n"
        "T = TypeVar('T')\n\n\n"
        "class Depot(Generic[T]):\n"
        "    def lire(self) -> T:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_dans_un_protocol_generique_usurpe(tmp_path: Path) -> None:
    """Prouve que la preuve d'origine de l'alias survit à la forme paramétrée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Protocol:\n"
        "    valeur = 1\n\n"
        "class Service(Protocol[int]):\n"
        "    def executer(self) -> int:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_repli_vers_une_commande_prefixee_par_true(tmp_path: Path) -> None:
    """Prouve qu'un exécutable tiers en repli est refusé : il ne PROUVE pas sa sortie.

    ``true_story`` n'est pas la commande shell ``true`` — la borne de mot le
    distingue toujours, et c'est ce qui évite de le nommer « succès forcé ». Mais
    la règle des replis est une LISTE BLANCHE : dans un job requis, une branche
    ``||`` n'est acceptée que si elle démontre qu'elle rend l'échec. Un exécutable
    tiers peut rendre 0 comme 1, donc il ne démontre rien.

    Aucun critère structurel ne sépare ``true_story`` de ``env true`` : les deux
    sont un programme externe. Exempter la classe rouvrirait l'énumération des
    porteurs de commande, qui ne converge pas. Le repli légitime s'écrit avec sa
    propagation : ``|| { true_story; exit 1; }``.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || true_story",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_vers_une_commande_prefixee_par_deux_points(
    tmp_path: Path,
) -> None:
    """Prouve que ``:mon_label`` est refusé comme commande INCONNUE, non comme ``:``.

    La borne de mot tient toujours — ``:mon_label`` n'est pas la commande vide —
    mais un nom que le gate ne sait pas évaluer n'entre pas dans la liste blanche
    des formes propageantes. L'inconnu bloque, par construction.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || :mon_label",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_une_commande_prefixee_par_true_apres_un_point_virgule(
    tmp_path: Path,
) -> None:
    """Prouve que la même limite de mot s'applique à la forme séquentielle."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py; true_story",)),
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_toujours_un_repli_true_suivi_dun_point_virgule(tmp_path: Path) -> None:
    """Prouve que la limite de mot n'ouvre aucun angle mort sur le vrai ``|| true``."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || true; echo suite",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_toujours_un_repli_deux_points_suivi_dun_point_virgule(
    tmp_path: Path,
) -> None:
    """Prouve que la commande vide ``:`` reste refusée quand elle est bien elle-même."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || :; echo suite",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_type_ignore_ajoute_meme_justifie(tmp_path: Path) -> None:
    """Prouve qu'une justification n'ouvre plus la porte à une dette de typage.

    Masquer une erreur de typage n'est pas une dette justifiable : c'est la
    baseline que ce gate interdit. Le gate mypy du dépôt est à zéro erreur, donc
    aucun besoin légitime ne subsiste.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "valeur = convertir()  # type: ignore[return-value] — conversion validée\n",
    )
    assert "NEW_TYPE_IGNORE" in _codes(_scanner(repo))


def test_refuse_un_type_ignore_ajoute_sans_espace(tmp_path: Path) -> None:
    """Prouve que l'orthographe compacte acceptée par mypy ne contourne pas la règle."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "valeur = convertir()  # type:ignore[return-value] — conversion validée\n",
    )
    assert "NEW_TYPE_IGNORE" in _codes(_scanner(repo))


def test_accepte_un_type_ignore_preexistant_non_modifie(tmp_path: Path) -> None:
    """Prouve que le durcissement reste diff-aware : l'existant n'est pas rouvert."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "valeur = convertir()  # type: ignore[return-value] — conversion validée\n",
    )
    _commiter_sans_hook(repo, "suppression de typage préexistante")

    assert "NEW_TYPE_IGNORE" not in _codes(_scanner(repo))


def test_accepte_un_noqa_justifie_apres_le_durcissement_du_typage(
    tmp_path: Path,
) -> None:
    """Prouve que noqa conserve la règle de justification et n'est pas durci."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "valeur = 1  # noqa: E501 — gabarit hérité, découpage prévu par la story\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_un_noqa_avec_identifiant_sans_justification(tmp_path: Path) -> None:
    """Prouve que l'identifiant de règle précédé de « : » ne tient pas lieu de justification."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "valeur = 1  # noqa: E501\n")
    assert "UNJUSTIFIED_SUPPRESSION" in _codes(_scanner(repo))


def test_accepte_un_noqa_multi_identifiants_justifie(tmp_path: Path) -> None:
    """Prouve que la liste de règles supprimées reste lisible avant la justification."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "valeur = 1  # noqa: E501,W503 — gabarit hérité, découpage prévu\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_un_commentaire_discursif_mentionnant_une_directive_de_typage(
    tmp_path: Path,
) -> None:
    """Prouve qu'un commentaire qui PARLE d'une directive n'en applique aucune.

    Mesuré sur mypy 2.1.0 : la directive écrite au fil d'une phrase ne supprime
    rien, l'erreur de typage reste rapportée. La refuser était un faux positif.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "valeur = 1  # Ne pas utiliser type: ignore ici, corriger le type source\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_un_commentaire_discursif_mentionnant_nosec(tmp_path: Path) -> None:
    """Prouve la même borne pour bandit, mesurée sur bandit 1.9.4."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "valeur = 1  # Voir le nosec B101 pour les détails de la revue\n",
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_une_directive_de_suppression_apres_un_second_diese(
    tmp_path: Path,
) -> None:
    """Prouve que la borne est le « # », jamais le début du commentaire.

    Mesuré sur ruff 0.15.20 et bandit 1.9.4 : ``# texte  # noqa: F401`` supprime
    RÉELLEMENT le diagnostic. Borner la règle au début du jeton ouvrirait donc un
    angle mort exploitable en une ligne.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import os  # import hérité du gabarit  # noqa: F401\n",
    )
    assert "UNJUSTIFIED_SUPPRESSION" in _codes(_scanner(repo))


def test_refuse_un_protocol_reaffecte_dans_un_bloc_module(tmp_path: Path) -> None:
    """Prouve qu'une réaffectation cachée dans un bloc module écrase bien l'alias.

    À l'exécution, ``Protocol = object`` placé sous un ``if`` module-level lie le
    module exactement comme la même ligne écrite au premier niveau : la classe
    hérite alors de ``object`` et livre une méthode vide. Ne chercher les
    réaffectations que sous ``arbre.body`` laissait ce contournement passer.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "if True:\n"
        "    Protocol = object\n\n\n"
        "class Service(Protocol):\n"
        "    def executer(self) -> int:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_reaffecte_dans_un_bloc_try_module(tmp_path: Path) -> None:
    """Prouve que le repli ``try/except`` lie le module au même titre qu'un ``if``."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "try:\n"
        "    import inexistant\n"
        "except ImportError:\n"
        "    Protocol = object\n\n\n"
        "class Service(Protocol):\n"
        "    def executer(self) -> int:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_ecrase_par_une_boucle_module(tmp_path: Path) -> None:
    """Prouve qu'une cible de boucle imbriquée écrase l'alias comme une affectation."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "if True:\n"
        "    for Protocol in (object,):\n"
        "        print(Protocol)\n\n\n"
        "class Service(Protocol):\n"
        "    def executer(self) -> int:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_un_protocol_reaffecte_seulement_dans_une_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que la descente s'arrête aux corps de fonctions, dont la portée est locale.

    Une liaison interne à une fonction ne touche jamais le namespace du module :
    l'alias module reste prouvé, et refuser la classe serait un faux positif.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n\n"
        "def configurer() -> object:\n"
        "    Protocol = object\n"
        "    return Protocol\n\n\n"
        "class Service(Protocol):\n"
        "    def executer(self) -> int:\n"
        "        ...\n",
    )
    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_refuse_un_repli_vers_true_par_chemin_absolu(tmp_path: Path) -> None:
    """Prouve que ``/usr/bin/true`` est la commande ``true``, pas un exécutable tiers.

    Préfixer le chemin ne change ni le binaire appelé ni son code de retour nul :
    le job requis redevenait vert alors que le contrôle avait échoué.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || /usr/bin/true",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_vers_true_par_chemin_bin(tmp_path: Path) -> None:
    """Prouve que l'autre emplacement usuel du même binaire est traité à égalité."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || /bin/true",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_vers_la_commande_vide_par_chemin(tmp_path: Path) -> None:
    """Prouve que la commande vide reste elle-même une fois préfixée d'un chemin."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || /usr/bin/:",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_via_le_builtin_command(tmp_path: Path) -> None:
    """Prouve que ``command true`` exécute ``true`` et absorbe l'échec identiquement."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || command true",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_vers_un_chemin_prefixe_par_true(tmp_path: Path) -> None:
    """Prouve qu'un chemin vers un exécutable tiers est refusé comme le nom nu.

    La borne de nom survit toujours au préfixe — ``/usr/bin/true_story`` n'est pas
    ``/usr/bin/true`` — mais le préfixe ne change rien à la question posée : ce
    binaire prouve-t-il qu'il rend l'échec ? Non. Le préfixe de chemin ne peut
    donc pas être un chemin d'exemption.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || /usr/bin/true_story",)),
    )
    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_enchainement_et_vers_true_par_chemin_absolu(
    tmp_path: Path,
) -> None:
    """Prouve que ``&&`` n'est pas un repli : la commande gardée décide encore de l'échec."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py && /usr/bin/true",)),
    )
    assert _codes(_scanner(repo)) == set()


def test_refuse_un_decorateur_de_saut_sur_une_classe_de_test(tmp_path: Path) -> None:
    """Prouve qu'une marque de saut posée sur la classe saute tous ses tests.

    Pytest applique la marque à chaque méthode de la classe : n'examiner les
    décorateurs que sur les fonctions laissait déserter une suite entière d'un
    seul décorateur déplacé d'un cran.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest\n\n\n"
        "@pytest.mark.skip\n"
        "class TestGroupe:\n"
        "    def test_calcul(self) -> None:\n"
        "        assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_accepte_un_decorateur_sans_saut_sur_une_classe_de_test(
    tmp_path: Path,
) -> None:
    """Prouve que seules les marques de saut sont visées sur une classe de test."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest\n\n\n"
        "@pytest.mark.usefixtures('depot')\n"
        "class TestGroupe:\n"
        "    def test_calcul(self) -> None:\n"
        "        assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


def test_refuse_une_marque_de_saut_sous_alias_de_module_pytest(
    tmp_path: Path,
) -> None:
    """Prouve que renommer l'import ne désarme pas la règle : ``pt.mark.skip`` saute."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest as pt\n\n\n"
        "@pt.mark.skip\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_appel_de_saut_sous_alias_de_module_pytest(tmp_path: Path) -> None:
    """Prouve que la forme appelée est couverte par la même preuve d'alias."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest as p\n\n\n"
        "def test_calcul() -> None:\n"
        "    p.skip('indisponible')\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_saut_importe_directement_de_unittest(tmp_path: Path) -> None:
    """Prouve que le nom nu importé de unittest reste un saut prouvé par son import."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from unittest import skip\n\n\n"
        "@skip('indisponible')\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_appel_de_saut_importe_directement_de_pytest(
    tmp_path: Path,
) -> None:
    """Prouve que le nom nu importé saute AUSSI depuis le corps, hors décorateur.

    ``from pytest import skip`` puis ``skip('…')`` est la forme appelée du même
    saut : sans elle, la branche « nom nu » de la règle d'appel n'aurait aucun
    cas qui la traverse, et sa suppression passerait inaperçue.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from pytest import skip\n\n\n"
        "def test_calcul() -> None:\n"
        "    skip('indisponible')\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_une_marque_de_saut_importee_directement_de_pytest(
    tmp_path: Path,
) -> None:
    """Prouve que la marque elle-même importée porte le saut sans passer par pytest."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from pytest import mark\n\n\n"
        "@mark.xfail\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_accepte_une_marque_homonyme_importee_dun_module_metier(
    tmp_path: Path,
) -> None:
    """Prouve que ``mark`` n'est une marque pytest que si son import le prouve."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from mon_module import mark\n\n\n"
        "@mark.xfail\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


def test_refuse_un_decorateur_de_saut_nu_importe_directement(tmp_path: Path) -> None:
    """Prouve que la forme décorateur non appelée est jugée comme la forme appelée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from unittest import skip\n\n\n"
        "@skip\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_saut_sous_alias_de_module_unittest(tmp_path: Path) -> None:
    """Prouve que l'alias du module unittest est résolu comme celui de pytest."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import unittest as ut\n\n\n"
        "@ut.skipIf(True, 'indisponible')\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_accepte_un_saut_homonyme_sur_un_module_metier(tmp_path: Path) -> None:
    """Prouve que l'origine de l'alias doit être PROUVÉE par un import de pytest.

    Un module métier importé sous un nom quelconque ne saute rien : le signaler
    serait un faux positif que la règle par alias ne doit jamais introduire.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import mon_module as p\n\n\n"
        "def test_calcul() -> None:\n"
        "    p.skip('etape')\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


def test_accepte_une_methode_skip_portee_par_self(tmp_path: Path) -> None:
    """Prouve qu'une méthode d'instance homonyme n'est jamais confondue avec un saut."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest as p\n\n\n"
        "class TestGroupe:\n"
        "    def test_calcul(self) -> None:\n"
        "        self.skip('etape')\n"
        "        assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


def test_accepte_un_decorateur_skip_importe_dun_module_metier(tmp_path: Path) -> None:
    """Prouve que le nom nu n'est un saut que si son import vient de pytest ou unittest."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from mon_module import skip\n\n\n"
        "@skip('etape')\n"
        "def test_calcul() -> None:\n"
        "    assert calculer() == 1\n",
    )
    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "declaration",
    (
        'argv = ["bandit", "-r", "src"]\n',
        'configuration.racines = ["src"]\n',
        'cibles: list[str] = ["src"]\n',
        'lancer(scopes=["src"])\n',
        'definir_racines(["src"])\n',
    ),
)
def test_detecte_le_retrait_total_des_racines_dune_declaration_de_perimetre(
    tmp_path: Path,
    declaration: str,
) -> None:
    """Prouve que vider ENTIÈREMENT le périmètre reste une omission, pas un silence.

    Ne signaler que les périmètres partiels offrait la sortie exactement inverse
    de l'intention du contrôle : qui veut désarmer le scan retire toutes les
    racines d'un coup, jamais une seule.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(repo, "core/scripts/run_security_scan.py", declaration)

    assert "SCOPE_ROOT_OMITTED" in _codes(_scanner(repo, ("core/scripts",)))


def test_accepte_une_liste_anonyme_de_chaines_dans_un_lanceur(tmp_path: Path) -> None:
    """Prouve que fermer le retrait total ne juge pas les listes sans contexte de périmètre."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        'MESSAGES = ["analyse terminee", "aucun defaut releve"]\n',
    )

    assert "SCOPE_ROOT_OMITTED" not in _codes(_scanner(repo, ("core/scripts",)))


@pytest.mark.parametrize(
    "corps",
    (
        "    with pt.raises(ValueError):\n        calculer()\n",
        "    pt.fail('chemin jamais atteint')\n",
    ),
)
def test_accepte_un_oracle_pytest_sous_alias_dimport(
    tmp_path: Path,
    corps: str,
) -> None:
    """Prouve qu'un oracle pytest renommé à l'import reste un oracle, comme à l'exécution."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest as pt\n\n\ndef test_calcul() -> None:\n" + corps,
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_refuse_un_raises_porte_par_un_module_metier_comme_oracle(
    tmp_path: Path,
) -> None:
    """Prouve que l'ouverture aux alias n'accepte pas un homonyme dont l'origine n'est pas pytest."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import mon_module as pt\n\n\n"
        "def test_calcul() -> None:\n"
        "    with pt.raises(ValueError):\n"
        "        calculer()\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_refuse_une_action_locale_introuvable_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve qu'un job requis délégant à une action locale absente n'exécute aucun contrôle."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo)

    assert "LOCAL_ACTION_INTROUVABLE" in _codes(_scanner(repo))


def test_refuse_une_action_locale_introuvable_appelee_par_une_action_composite(
    tmp_path: Path,
) -> None:
    """Prouve que la référence absente est détectée aussi en cascade sous une action composite."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo, "./.github/actions/A")
    _ecrire(
        repo,
        ".github/actions/A/action.yml",
        "runs:\n  using: composite\n  steps:\n    - uses: ./.github/actions/B\n",
    )

    assert "LOCAL_ACTION_INTROUVABLE" in _codes(_scanner(repo))


def test_accepte_une_action_externe_referencee_par_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve qu'une action publiée hors du dépôt n'est jamais tenue pour absente."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo, "actions/checkout@v4")

    assert "LOCAL_ACTION_INTROUVABLE" not in _codes(_scanner(repo))


def test_accepte_une_action_locale_introuvable_dans_un_job_non_requis(
    tmp_path: Path,
) -> None:
    """Prouve que l'exigence d'existence reste bornée aux ids requis du contrat."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/delegation.yml",
        "jobs:\n"
        "  rapport-optionnel:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: ./.github/actions/inexistante\n",
    )

    assert "LOCAL_ACTION_INTROUVABLE" not in _codes(_scanner(repo))


def test_main_refuse_les_jobs_requis_quand_aucun_repertoire_de_workflows_nexiste(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve qu'un contrat déclarant des jobs requis SANS aucune CI est le défaut maximal.

    Ne rien dire d'un dépôt dépourvu de `.github/workflows/` produisait
    l'inverse de l'intention : le contrat exige des contrôles, et leur absence
    TOTALE est précisément ce que le code REQUIRED_JOB_ABSENT nomme.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat_deux_jobs(repo)
    _ecrire(repo, "src/service.py", "def calculer() -> int:\n    return 1\n")

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert not (repo / ".github" / "workflows").exists()
    assert code_retour == 1
    assert "REQUIRED_JOB_ABSENT" in sortie
    assert "gates" in sortie
    assert "types" in sortie


def test_main_refuse_les_jobs_requis_quand_le_repertoire_de_workflows_est_vide(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve qu'un répertoire de workflows créé mais vide ne dispense de rien."""
    repo = _depot_git_initialise(tmp_path)
    _contrat_deux_jobs(repo)
    (repo / ".github" / "workflows").mkdir(parents=True)

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert code_retour == 1
    assert "REQUIRED_JOB_ABSENT" in sortie


def test_main_refuse_les_jobs_requis_quand_aucun_fichier_yaml_nexiste(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve qu'un répertoire de workflows sans .yml ni .yaml ne définit aucun job."""
    repo = _depot_git_initialise(tmp_path)
    _contrat_deux_jobs(repo)
    _ecrire(repo, ".github/workflows/NOTES.md", "aucun workflow ici\n")

    code_retour = main(["--repo", str(repo)])

    sortie = capsys.readouterr().out
    assert code_retour == 1
    assert "REQUIRED_JOB_ABSENT" in sortie


def test_un_contrat_sans_job_requis_ne_signale_aucune_absence(tmp_path: Path) -> None:
    """Prouve que la borne conservée est le CONTRAT, jamais la présence d'une CI.

    Sans identifiant requis déclaré, il n'existe aucun contrôle promis dont
    l'absence puisse être reprochée : le gate doit alors rester muet, y compris
    dans un dépôt totalement dépourvu de workflows.
    """
    repo = _depot_git_initialise(tmp_path)

    assert _violations_jobs_requis_absents(repo, ()) == []


def test_refuse_une_classe_dont_le_corps_est_pass(tmp_path: Path) -> None:
    """Prouve qu'un corps de CLASSE réduit à pass est un stub, comme celui d'une fonction."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "class Service:\n    pass\n")

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_une_classe_dont_le_corps_est_une_ellipse(tmp_path: Path) -> None:
    """Prouve que l'ellipse ne rend pas plus licite un corps de classe vide."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", "class Service:\n    ...\n")

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_classe_reduite_a_sa_docstring(tmp_path: Path) -> None:
    """Prouve la cohérence avec les fonctions : documenter un vide ne le remplit pas."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", 'class Service:\n    """Décrit un service."""\n')

    assert "DOCSTRING_ONLY_BODY" in _codes(_scanner(repo))


def test_refuse_une_classe_vide_heritant_dune_base_ordinaire(tmp_path: Path) -> None:
    """Prouve que l'exemption vise les TYPES D'EXCEPTION, jamais le simple fait d'hériter."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Base:\n"
        "    def calculer(self) -> int:\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Service(Base):\n"
        "    pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_une_classe_dexception_vide(tmp_path: Path) -> None:
    """Prouve le sens inverse : un type d'exception vide est du code COMPLET, pas un stub.

    L'identité du type EST tout son contenu — elle se lève et se rattrape
    sélectivement. Le refuser serait un faux positif sur un idiome Python
    courant, et pousserait à désarmer le gate.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/erreurs.py", "class MonErreur(ValueError):\n    pass\n")

    codes = _codes(_scanner(repo))
    assert "EXECUTABLE_PASS" not in codes
    assert "DOCSTRING_ONLY_BODY" not in codes


def test_accepte_une_classe_dexception_reduite_a_sa_docstring(tmp_path: Path) -> None:
    """Prouve que la forme documentée du même idiome reste acceptée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/erreurs.py",
        'class MonErreur(RuntimeError):\n    """Signale une panne du transport."""\n',
    )

    assert "DOCSTRING_ONLY_BODY" not in _codes(_scanner(repo))


def test_accepte_une_exception_derivee_dune_exception_locale(tmp_path: Path) -> None:
    """Prouve que l'héritage est résolu TRANSITIVEMENT dans le module, pas au premier cran."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/erreurs.py",
        'class ErreurRacine(ValueError):\n'
        '    """Racine des erreurs du module."""\n'
        "\n"
        "\n"
        "class ErreurFille(ErreurRacine):\n"
        "    pass\n",
    )

    codes = _codes(_scanner(repo))
    assert "EXECUTABLE_PASS" not in codes
    assert "DOCSTRING_ONLY_BODY" not in codes


def test_accepte_une_classe_portant_de_vraies_methodes(tmp_path: Path) -> None:
    """Prouve qu'une classe ordinaire dont le corps déclare des méthodes reste acceptée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Service:\n"
        "    def calculer(self) -> int:\n"
        "        return 1\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_un_test_dont_le_seul_oracle_est_une_methode_metier(
    tmp_path: Path,
) -> None:
    """Prouve qu'un objet métier NOMMÉ comme une assertion ne vaut aucun oracle.

    Sans preuve d'héritage d'unittest.TestCase, il suffisait de nommer une
    méthode `assert…` pour faire passer un test qui ne vérifie rien.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_silence.py",
        "class Silencer:\n"
        "    def assert_noop(self) -> int:\n"
        "        return 1\n"
        "\n"
        "\n"
        "def test_c() -> None:\n"
        "    Silencer().assert_noop()\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_refuse_self_assert_hors_dune_classe_test_case(tmp_path: Path) -> None:
    """Prouve que le receveur `self` seul ne prouve rien sans l'héritage unittest."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_suite.py",
        "class Faux:\n"
        "    def assertEqual(self, gauche: int, droite: int) -> int:\n"
        "        return gauche + droite\n"
        "\n"
        "\n"
        "class Suite:\n"
        "    def test_ok(self) -> None:\n"
        "        self.assertEqual(1, 1)\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_accepte_self_assert_equal_dans_un_cas_de_test_unittest(tmp_path: Path) -> None:
    """Prouve que l'oracle unittest légitime reste accepté, sens inverse du durcissement."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_unittest.py",
        "import unittest\n"
        "\n"
        "\n"
        "class Suite(unittest.TestCase):\n"
        "    def test_ok(self) -> None:\n"
        "        self.assertEqual(1, 1)\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_accepte_self_assert_dans_une_sous_classe_locale_de_test_case(
    tmp_path: Path,
) -> None:
    """Prouve que l'héritage unittest est résolu transitivement, comme celui des exceptions."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_base.py",
        "import unittest\n"
        "\n"
        "\n"
        "class Base(unittest.TestCase):\n"
        "    def aider(self) -> int:\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Suite(Base):\n"
        "    def test_ok(self) -> None:\n"
        "        self.assertEqual(1, 1)\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_accepte_self_assert_avec_test_case_importe_sous_alias(tmp_path: Path) -> None:
    """Prouve que l'alias d'import est résolu comme ailleurs dans le gate."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_alias.py",
        "from unittest import TestCase as CasDeTest\n"
        "\n"
        "\n"
        "class Suite(CasDeTest):\n"
        "    def test_ok(self) -> None:\n"
        "        self.assertEqual(1, 1)\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_accepte_un_assert_nu_dans_un_test(tmp_path: Path) -> None:
    """Prouve que l'assertion nue reste l'oracle de référence du dépôt."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/test_nu.py", "def test_c() -> None:\n    assert 1 + 1 == 2\n")

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_refuse_continue_on_error_entier_un_dans_un_job_requis(tmp_path: Path) -> None:
    """Prouve que l'entier 1 tolère les erreurs exactement comme le booléen true.

    PyYAML rend l'entier 1, que ni `valeur is True` ni le test de chaîne
    n'attrapaient : le job requis restait vert avec son contrôle rouge.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    continue-on-error: 1\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 -m pytest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_refuse_continue_on_error_flottant_non_nul_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve que la règle porte sur la valeur numérique, pas sur le seul type entier."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    continue-on-error: 1.0\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 -m pytest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_accepte_continue_on_error_entier_zero_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve le sens inverse : zéro ne tolère rien et ne doit jamais être signalé."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    continue-on-error: 0\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 -m pytest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" not in _codes(_scanner(repo))


def test_refuse_continue_on_error_entier_un_dans_une_etape_requise(
    tmp_path: Path,
) -> None:
    """Prouve que la forme entière est refusée au niveau ÉTAPE comme au niveau job."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 -m pytest\n"
        "        continue-on-error: 1\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


def test_accepte_une_ellipse_comme_corps_entier_dun_protocol(tmp_path: Path) -> None:
    """Prouve qu'un protocole déclaré par une ellipse seule reste une interface licite.

    Contrôler le corps des classes avait pour effet de bord de refuser la
    déclaration d'interface la plus courante de Python, alors que la même ellipse
    est acceptée méthode par méthode juste au-dessous.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n\nclass Depot(Protocol):\n    ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_une_ellipse_de_classe_ordinaire_voisine_dun_protocol(
    tmp_path: Path,
) -> None:
    """Prouve que l'exemption du protocole ne déteint pas sur la classe d'à côté."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n\n"
        "class Depot(Protocol):\n    ...\n\n\n"
        "class Service:\n    ...\n",
    )

    violations = _scanner(repo)
    assert [(violation.code, violation.line) for violation in violations] == [
        ("EXECUTABLE_ELLIPSIS", 8)
    ]


def test_refuse_un_corps_de_protocol_reduit_a_pass(tmp_path: Path) -> None:
    """Prouve que l'exemption vise l'ellipse déclarative, jamais un pass de remplissage.

    La règle des méthodes est reprise à l'identique : ``...`` déclare une
    interface, ``pass`` ne déclare rien.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n\nclass Depot(Protocol):\n    pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_de_classe_sous_un_protocol_usurpe(tmp_path: Path) -> None:
    """Prouve que l'exemption exige le VRAI typing.Protocol, jamais un homonyme local."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "class Protocol:\n    def marquer(self) -> None:\n        self.vu = True\n\n\n"
        "class Depot(Protocol):\n    ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_classe_vide_homonyme_dune_exception_du_module(
    tmp_path: Path,
) -> None:
    """Prouve que l'exemption d'exception suit l'héritage, jamais une collision de nom.

    Une classe déclarée dans une autre portée peut porter le nom d'un type
    d'exception du module sans rien hériter : l'exempter revenait à ouvrir un
    contournement d'un seul renommage.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Panne(ValueError):\n    pass\n\n\n"
        "def configurer() -> None:\n"
        "    class Panne:\n        pass\n\n"
        "    raise Panne\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_une_exception_vide_du_module_apres_le_controle_dhomonymie(
    tmp_path: Path,
) -> None:
    """Prouve que resserrer l'exemption ne réintroduit pas le faux positif d'exception."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Panne(ValueError):\n    pass\n\n\n"
        "class PanneGrave(Panne):\n    pass\n",
    )

    assert _codes(_scanner(repo)) == set()


@pytest.mark.parametrize("shell", ("sh", "bash", "/bin/sh"))
def test_refuse_un_repli_shell_inline_forcant_le_succes(
    tmp_path: Path,
    shell: str,
) -> None:
    """Prouve qu'un shell lancé en repli avec un script à succès absorbe l'échec requis.

    La neutralisation des quotes rendait ``exit 0`` invisible à l'intérieur de
    l'argument, si bien qu'aucun motif de repli ne s'appliquait plus.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/inline.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - run: verif || {shell} -c 'exit 0'\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_repli_shell_inline_qui_propage_lechec(tmp_path: Path) -> None:
    """Prouve que le critère est le succès FORCÉ, pas l'appel d'un shell en repli."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/inline_echec.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: verif || sh -c 'exit 1'\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_un_repli_vers_un_script_de_recuperation(tmp_path: Path) -> None:
    """Prouve qu'un script de récupération ne suffit plus : il ne dit rien de l'échec.

    « Ce script PEUT échouer » n'est pas « ce script propage l'échec du contrôle ».
    Rien, dans ``|| bash script_de_recuperation.sh``, ne distingue statiquement un
    script qui sort en non nul d'un script qui journalise et rend 0 — ni de
    ``|| env true``, qui est aussi un programme externe.

    Dans un job REQUIS, un repli doit DIRE ce qu'il fait de l'échec. La réécriture
    qui passe est prouvée par
    ``test_accepte_un_repli_vers_un_script_de_recuperation_qui_propage``.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/recuperation.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: verif || bash script_de_recuperation.sh\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_repli_vers_un_script_de_recuperation_qui_propage(
    tmp_path: Path,
) -> None:
    """NOMME le coût de l'inversion et sa sortie : rendre la propagation explicite.

    Même script de récupération, même intention, une accolade de plus : le groupe
    exécute la récupération PUIS sort en non nul, si bien que le job requis reste
    rouge quand son contrôle l'est. C'est la forme que la politique recommande, et
    elle doit être prouvée VERTE — sans quoi l'inversion serait une interdiction
    du repli, et non une exigence de propagation.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/recuperation_ok.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: 'verif || { bash script_de_recuperation.sh; exit 1; }'\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_un_protocol_reaffecte_par_attribut_de_module(tmp_path: Path) -> None:
    """Prouve qu'écraser typing.Protocol détruit l'exemption comme écraser le nom nu.

    Ne surveiller que les cibles ``ast.Name`` laissait un seul point réaffecter
    l'origine prouvée du protocole.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\nt.Protocol = object\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_abstractmethod_reaffecte_par_attribut_de_module(
    tmp_path: Path,
) -> None:
    """Prouve que la règle vise la PREUVE d'origine, pas le seul nom Protocol."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/base.py",
        "import abc\n\nabc.abstractmethod = staticmethod\n\n\n"
        "class Socle:\n    @abc.abstractmethod\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_reaffecte_par_attribut_dans_un_corps_de_fonction(
    tmp_path: Path,
) -> None:
    """Prouve qu'un ATTRIBUT de module se réécrit à toute PROFONDEUR, jamais localement.

    MESURÉ à l'interpréteur : l'appel ``desarmer()`` exécute réellement
    ``t.Protocol = object`` AVANT la définition de ``Service``, qui hérite alors
    d'``object`` et n'est plus un protocole. La collecte des révocations ignorait
    pourtant les corps de fonctions — règle correcte pour un NOM, qu'une portée
    locale confine, mais FAUSSE pour un attribut de module : l'objet visé est le
    module lui-même, et la portée où l'écriture est rédigée ne le protège pas.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n\n"
        "def desarmer() -> None:\n"
        "    t.Protocol = object\n\n\n"
        "desarmer()\n\n\n"
        "class Service(t.Protocol):\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_reaffecte_par_attribut_dans_un_corps_de_classe(
    tmp_path: Path,
) -> None:
    """Prouve que le corps de CLASSE ne protège pas davantage l'attribut du module.

    MESURÉ à l'interpréteur : ``class Boite: t.Protocol = object`` exécute son
    corps à l'import et écrase l'attribut du module ``t`` — ``Boite.Protocol``
    n'est PAS créé, la cible étant un attribut, jamais un nom de classe. La
    divergence conservée pour les NOMS (``class Boite: Protocol = object`` ne
    réaffecte rien du module) ne vaut donc pas ici, et le même correctif ferme
    les deux profondeurs d'un coup.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n\n"
        "class Boite:\n"
        "    t.Protocol = object\n\n\n"
        "class Service(t.Protocol):\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_supprime_par_del_dans_un_corps_de_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que le ``del`` d'attribut est révocateur à toute profondeur, lui aussi.

    MESURÉ à l'interpréteur : après l'appel, ``t.Protocol`` n'existe plus et la
    classe qui prétend en hériter échoue à l'import sur une ``AttributeError``.
    Ne fermer que l'affectation laisserait exempter un code qui ne s'importe même
    pas, exactement comme au niveau du module avant sa correction.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n\n"
        "def desarmer() -> None:\n"
        "    del t.Protocol\n\n\n"
        "desarmer()\n\n\n"
        "class Service(t.Protocol):\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_abstractmethod_reaffecte_par_attribut_dans_un_corps_de_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que la profondeur vaut pour TOUT attribut prouvant, pas pour Protocol seul.

    Les deux attributs qui portent une exemption — ``Protocol`` et
    ``abstractmethod`` — passent par la même collecte : fermer la profondeur pour
    l'un sans l'autre laisserait le contournement disponible au voisin.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/base.py",
        "import abc\n\n\n"
        "def desarmer() -> None:\n"
        "    abc.abstractmethod = staticmethod\n\n\n"
        "desarmer()\n\n\n"
        "class Socle:\n"
        "    @abc.abstractmethod\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_reaffecte_par_une_fonction_jamais_appelee(
    tmp_path: Path,
) -> None:
    """Prouve la conséquence FAIL-CLOSED assumée : l'appel n'est pas suivi.

    La fonction n'est jamais appelée, donc l'attribut n'est pas réellement écrasé
    à l'exécution — et la preuve est révoquée quand même. Suivre les appels
    exigerait une analyse de flot que ni un décorateur, ni un appel indirect, ni
    un import tiers ne rendraient fiable ; le gate refuse donc par défaut.
    Écrire une fonction qui mutile ``typing.Protocol`` sans jamais l'appeler n'a
    aucun usage légitime : le coût de ce refus est nul, celui de l'angle mort
    inverse est une exemption entièrement contournable.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n\n"
        "def desarmer() -> None:\n"
        "    t.Protocol = object\n\n\n"
        "class Service(t.Protocol):\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_reaffecte_par_comprehension_dans_un_corps_de_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que la cible de compréhension est révocatrice jusque dans une fonction.

    MESURÉ à l'interpréteur : ``[1 for t.Protocol in (object,)]`` écrase
    l'attribut du module, la portée de la compréhension ne protégeant que son
    dictionnaire local, jamais l'objet visé. La forme était déjà fermée au niveau
    du module ; l'enfermer dans une fonction la rouvrait.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n\n"
        "def desarmer() -> None:\n"
        "    [1 for t.Protocol in (object,)]\n\n\n"
        "desarmer()\n\n\n"
        "class Service(t.Protocol):\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_reaffecte_par_attribut_dans_une_methode(
    tmp_path: Path,
) -> None:
    """Prouve que la profondeur se compte en NIVEAUX, pas en un cran de descente.

    L'écriture est ici doublement enfermée — corps de classe PUIS corps de
    méthode. Un correctif qui n'aurait ajouté qu'un niveau de descente à la
    collecte existante l'aurait manquée, alors que le parcours par nœuds la
    couvre au même titre qu'une écriture de premier niveau.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n\n"
        "class Atelier:\n"
        "    def desarmer(self) -> None:\n"
        "        t.Protocol = object\n\n\n"
        "Atelier().desarmer()\n\n\n"
        "class Service(t.Protocol):\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_conserve_une_exemption_dont_un_autre_attribut_est_reaffecte_en_fonction(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : la profondeur n'élargit pas la CIBLE du retrait.

    Seul l'attribut PROUVANT révoque. Une écriture profonde sur un attribut sans
    rapport — ici ``t.TYPE_CHECKING`` — ne détruit aucune preuve, faute de quoi
    étendre la portée du contrôle transformerait chaque fonction de
    configuration en faux positif.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n\n"
        "def configurer() -> None:\n"
        "    t.TYPE_CHECKING = True\n\n\n"
        "configurer()\n\n\n"
        "class Service(t.Protocol):\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_conserve_une_exemption_dont_un_attribut_homonyme_est_ecrit_en_fonction(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : le PORTEUR compte autant que le nom de l'attribut.

    ``configuration.Protocol`` écrit l'attribut d'un objet quelconque, pas celui
    du module ``typing`` : la preuve d'origine du protocole reste entière.
    Retirer sur le seul nom d'attribut ferait de tout code métier employant le
    mot ``Protocol`` un faux positif.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\n\n"
        "class Reglages:\n"
        "    Protocol = 1\n\n\n"
        "configuration = Reglages()\n\n\n"
        "def configurer() -> None:\n"
        "    configuration.Protocol = 2\n\n\n"
        "configurer()\n\n\n"
        "class Service(t.Protocol):\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_accepte_un_module_typing_dont_un_autre_attribut_est_reaffecte(
    tmp_path: Path,
) -> None:
    """Prouve que seule la réaffectation de l'attribut PROUVANT retire l'exemption."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\nt.TYPE_CHECKING = True\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_un_protocol_reaffecte_par_global_dans_une_fonction(
    tmp_path: Path,
) -> None:
    """Prouve qu'une affectation déclarée global lie le MODULE, non la fonction.

    L'exemption des affectations locales repose sur leur portée ; ``global`` la
    supprime explicitement, donc l'origine du nom n'est plus prouvée.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n\n"
        "def desarmer() -> None:\n    global Protocol\n\n    Protocol = object\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_un_global_declare_sans_reaffectation(tmp_path: Path) -> None:
    """Prouve que déclarer global ne suffit pas : il faut une affectation pour délier."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n\n"
        "def inspecter() -> str:\n    global Protocol\n\n    return Protocol.__name__\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_une_absence_dimplementation_aliasee_par_affectation(
    tmp_path: Path,
) -> None:
    """Prouve qu'un alias construit par affectation reste un stub explicite.

    Le gate résolvait l'alias d'import ; le même nom obtenu par affectation
    depuis l'attribut d'un module échappait entièrement à la règle.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import builtins\n\nAbsence = builtins.NotImplementedError\n\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "def calculer() -> None:\n    raise Absence\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_accepte_un_alias_daffectation_vers_une_autre_exception(
    tmp_path: Path,
) -> None:
    """Prouve que l'exigence de PREUVE d'origine tient : un alias quelconque n'est pas visé."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import mon_module\n\nAbsence = mon_module.PanneMetier\n\n\n"
        "def calculer() -> None:\n    raise Absence\n",
    )

    assert "NOT_IMPLEMENTED_STUB" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "declaration",
    (
        "    racines = charger_racines_qualite()[:1]\n",
        "    racines = list(charger_racines_contractuelles())[:1]\n",
        "    racines = python_roots[1:]\n",
    ),
)
def test_refuse_une_troncature_indecidable_des_racines_contractuelles(
    tmp_path: Path,
    declaration: str,
) -> None:
    """Prouve qu'un périmètre dérivé des racines sans valeur décidable est refusé.

    Le contrôle des omissions ne lisait que les collections littérales ; toute
    transformation opaque de la source des racines retirait donc des racines en
    silence.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        "def principal() -> int:\n" + declaration + "    return len(racines)\n",
    )

    assert "SCOPE_FILTRE_INDECIDABLE" in _codes(_scanner(repo, ("core/scripts",)))


@pytest.mark.parametrize(
    "declaration",
    (
        "    racines = charger_racines_qualite()\n",
        "    racines = contrat.get('python_roots')\n",
        "    racines = [chemin for chemin in python_roots if chemin.exists()]\n",
    ),
)
def test_accepte_une_declaration_de_racines_deleguee_au_contrat(
    tmp_path: Path,
    declaration: str,
) -> None:
    """Prouve que déléguer les racines au contrat reste la forme attendue d'un lanceur."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        "def principal(contrat: dict[str, object], python_roots: list[str]) -> int:\n"
        + declaration
        + "    return len(racines)\n",
    )

    assert "SCOPE_FILTRE_INDECIDABLE" not in _codes(_scanner(repo, ("core/scripts",)))


def test_accepte_une_ligne_de_commande_etrangere_aux_racines(tmp_path: Path) -> None:
    """Prouve que le contrôle vise les racines, pas toute liste au nom de périmètre.

    MESURÉ sur ce dépôt : juger toute déclaration non décidable signalerait 16
    expressions légitimes des lanceurs (chemins, lectures du contrat, lignes de
    commande), soit le faux positif qui pousse à désarmer un gate.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_tests.py",
        "def principal(interpreteur: str, arguments: list[str]) -> int:\n"
        "    argv = [str(interpreteur), '-m', 'pytest', *arguments]\n"
        "    return len(argv)\n",
    )

    assert _codes(_scanner(repo, ("core/scripts",))) == set()


def test_refuse_success_comme_condition_dun_job_requis_qui_depend_dun_autre(
    tmp_path: Path,
) -> None:
    """Prouve qu'un ``needs`` rend ``success()`` capable de SAUTER le job requis.

    ``success()`` seul est la condition par défaut et ne saute rien. Dès qu'un
    ``needs`` est déclaré, la même écriture change de sens : GitHub Actions
    évalue alors le statut des dépendances, si bien qu'une dépendance SAUTÉE ou
    en échec rend ``success()`` faux et le job requis sauté. La protection de
    branche est satisfaite sans qu'aucun contrôle ait tourné, et n'importe quel
    job non requis — donc libre de porter la condition qu'il veut — suffit à
    déclencher ce saut.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/condition.yml",
        "jobs:\n"
        "  precheck:\n"
        "    if: ${{ false }}\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo rien\n"
        "  gates:\n"
        "    needs: precheck\n"
        "    if: success()\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 scripts/quality/no_stub_gate.py\n",
    )

    assert "REQUIRED_JOB_CONDITIONNEL" in _codes(_scanner(repo))


def test_accepte_success_comme_condition_dun_job_requis_sans_needs(
    tmp_path: Path,
) -> None:
    """Prouve que le resserrement vise le ``needs``, jamais ``success()`` lui-même.

    Sans dépendance déclarée, aucun job dont l'échec ou le saut pourrait rendre
    la condition fausse n'existe : le job requis s'exécute. Le refuser serait un
    faux positif sur la forme la plus banale d'un workflow, et c'est précisément
    ce constat qui rendait la première réfutation de l'objection incomplète
    plutôt que fausse.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/condition.yml",
        "jobs:\n"
        "  gates:\n"
        "    if: success()\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 scripts/quality/no_stub_gate.py\n",
    )

    assert "REQUIRED_JOB_CONDITIONNEL" not in _codes(_scanner(repo))


def test_accepte_always_comme_condition_dun_job_requis_qui_depend_dun_autre(
    tmp_path: Path,
) -> None:
    """Prouve que ``always()`` survit au ``needs``, parce qu'il ne saute JAMAIS.

    ``always()`` vaut vrai quel que soit le sort des dépendances : le job requis
    tourne même quand le job dont il dépend a échoué ou a été sauté. Le danger
    corrigé — un contrôle requis rapporté vert sans avoir tourné — n'existe donc
    pas sous cette condition, et l'interdire supprimerait la seule écriture qui
    force un gate à s'exécuter en toutes circonstances.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/condition.yml",
        "jobs:\n"
        "  precheck:\n"
        "    if: ${{ false }}\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo rien\n"
        "  gates:\n"
        "    needs: precheck\n"
        "    if: always()\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 scripts/quality/no_stub_gate.py\n",
    )

    assert "REQUIRED_JOB_CONDITIONNEL" not in _codes(_scanner(repo))


def test_accepte_success_comme_condition_dune_etape_dun_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve que le resserrement ne déborde pas sur les ÉTAPES, qui n'ont pas de needs.

    Au niveau d'une étape, ``success()`` ne dépend que des étapes précédentes du
    même job : si l'une a échoué, le job échoue et le contrôle requis est rouge.
    Aucun saut silencieux n'est donc possible, contrairement au niveau job.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/condition.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - if: success()\n"
        "        run: python3 scripts/quality/no_stub_gate.py\n",
    )

    assert "REQUIRED_JOB_CONDITIONNEL" not in _codes(_scanner(repo))


def test_refuse_une_base_dexception_usurpee_par_un_attribut_homonyme(
    tmp_path: Path,
) -> None:
    """Prouve que l'exemption d'exception exige la preuve du PORTEUR de l'attribut.

    ``Faux.ValueError`` désigne ici ``object`` : la classe qui en hérite n'est
    aucun type d'exception, et son corps vide reste une dette entière. Se fier au
    seul nom de l'attribut laissait exempter n'importe quelle classe derrière un
    porteur inventé en deux lignes.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Faux:\n"
        "    ValueError = object\n"
        "\n"
        "\n"
        "class Service(Faux.ValueError):\n"
        "    pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_une_exception_builtin_qualifiee_par_le_module_prouve(
    tmp_path: Path,
) -> None:
    """Prouve le sens inverse : ``builtins`` prouvé par import qualifie une vraie exception."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/erreurs.py",
        "import builtins\n\n\nclass MonErreur(builtins.ValueError):\n    pass\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_accepte_une_exception_builtin_qualifiee_par_un_alias_du_module(
    tmp_path: Path,
) -> None:
    """Prouve que l'alias du module builtins prouve autant que son nom d'origine."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/erreurs.py",
        "import builtins as b\n\n\nclass MonErreur(b.ValueError):\n    pass\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_une_base_dexception_qualifiee_par_un_module_non_importe(
    tmp_path: Path,
) -> None:
    """Prouve qu'un porteur nommé ``builtins`` sans import ne prouve rien.

    Le nom n'étant lié par aucun import, il désigne ce que le module veut : la
    preuve exigée est l'import, jamais l'orthographe du porteur.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Service(builtins.ValueError):\n    pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_une_base_dexception_dont_le_nom_est_reaffecte_au_niveau_module(
    tmp_path: Path,
) -> None:
    """Prouve qu'un nom d'exception builtin réaffecté par le module ne prouve plus rien.

    ``ValueError = object`` au niveau module fait hériter ``Service`` d'``object``
    : c'est le même contournement que l'attribut homonyme, écrit d'une seule
    ligne au lieu de deux.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "ValueError = object\n\n\nclass Service(ValueError):\n    pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_une_base_dexception_dont_le_nom_vient_dun_autre_module(
    tmp_path: Path,
) -> None:
    """Prouve qu'un import lie un nom aussi sûrement qu'une affectation.

    ``from transport import ValueError`` fait désigner au nom ce que ``transport``
    exporte, et non l'exception de l'interpréteur : l'exemption tombe.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from transport import ValueError\n\n\nclass Service(ValueError):\n    pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_une_exception_builtin_importee_depuis_builtins(
    tmp_path: Path,
) -> None:
    """Prouve que l'import DEPUIS builtins conserve la preuve au lieu de la détruire."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/erreurs.py",
        "from builtins import ValueError\n\n\nclass MonErreur(ValueError):\n    pass\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_invalide_une_exemption_reaffectee_dans_un_except_etoile(
    tmp_path: Path,
) -> None:
    """Prouve que ``except*`` lie le module exactement comme ``except``.

    Le parcours des liaisons ignorait ``ast.TryStar`` alors que le parcours des
    instructions hors fonction le traitait déjà : une réaffectation cachée d'un
    seul cran conservait l'alias, donc exemptait une classe qui hérite en
    réalité d'``object``.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n"
        "\n"
        "try:\n"
        "    pass\n"
        "except* ValueError:\n"
        "    Protocol = object\n"
        "\n"
        "\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_invalide_une_exemption_reaffectee_dans_le_finally_dun_except_etoile(
    tmp_path: Path,
) -> None:
    """Prouve que les quatre corps d'un ``except*`` sont parcourus, pas seulement le premier."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n"
        "\n"
        "try:\n"
        "    pass\n"
        "except* ValueError:\n"
        "    pass\n"
        "finally:\n"
        "    Protocol = object\n"
        "\n"
        "\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_prouve_un_alias_importe_dans_un_except_etoile(tmp_path: Path) -> None:
    """Prouve que ``except*`` est parcouru dans les DEUX sens, comme ``except``.

    Le repli lie le module au même titre que son premier niveau : l'import qu'il
    porte PROUVE l'alias. Ne corriger que le sens destructeur aurait transformé
    un repli d'import légitime en faux positif.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "try:\n"
        "    pass\n"
        "except* ImportError:\n"
        "    from typing import Protocol\n"
        "\n"
        "\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_conserve_une_exemption_reaffectee_dans_un_corps_de_classe(
    tmp_path: Path,
) -> None:
    """Prouve que le corps de CLASSE reste HORS du parcours des liaisons du module.

    ``_instructions_hors_fonction`` descend dans les classes parce qu'elles
    s'exécutent à l'import ; le parcours des liaisons ne le fait pas, et ne doit
    pas le faire : ``Boite.Protocol`` est un attribut de classe, il ne réaffecte
    aucun nom du module. Aligner les deux parcours sur ce point précis créerait
    un faux positif au lieu de fermer un contournement, ce qui distingue cette
    divergence-là de celle du ``except*``.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n"
        "\n"
        "\n"
        "class Boite:\n"
        "    Protocol = object\n"
        "\n"
        "\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_accepte_un_oracle_raises_importe_directement_de_pytest(
    tmp_path: Path,
) -> None:
    """Prouve que ``from pytest import raises`` reste un oracle, comme à l'exécution.

    MESURÉ avant correction : le code ``TEST_WITHOUT_ORACLE`` était émis sur cet
    idiome courant, alors qu'``import pytest`` puis ``pytest.raises`` était
    accepté. Un gate qui refuse un idiome courant se fait désarmer par ceux qu'il
    gêne : le faux positif coûte aussi cher que l'angle mort.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from pytest import raises\n\n\n"
        "def test_calcul() -> None:\n"
        "    with raises(ValueError):\n"
        "        calculer()\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_accepte_un_oracle_fail_importe_directement_de_pytest(
    tmp_path: Path,
) -> None:
    """Prouve que ``from pytest import fail`` abandonne bien le test, donc l'oracle.

    MESURÉ avant correction : cette forme était elle aussi signalée sans oracle.
    Elle vient du même import direct, et le correctif la traite au même endroit.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from pytest import fail\n\n\n"
        "def test_calcul() -> None:\n"
        "    fail('chemin jamais atteint')\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_accepte_un_oracle_raises_importe_sous_un_alias_de_pytest(
    tmp_path: Path,
) -> None:
    """Prouve que renommer l'oracle à l'import ne change rien à ce qu'il vérifie."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from pytest import raises as leve\n\n\n"
        "def test_calcul() -> None:\n"
        "    with leve(ValueError):\n"
        "        calculer()\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_refuse_un_raises_importe_dun_module_metier_comme_oracle(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : seule l'origine pytest fait d'un nom nu un oracle.

    ``from mon_module import raises`` porte le même nom sans rien vérifier :
    l'ouverture aux imports directs se paierait d'un oracle de façade si elle ne
    lisait que l'orthographe du nom.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from mon_module import raises\n\n\n"
        "def test_calcul() -> None:\n"
        "    with raises(ValueError):\n"
        "        calculer()\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_refuse_un_raises_de_pytest_reaffecte_comme_oracle(tmp_path: Path) -> None:
    """Prouve qu'une réaffectation du nom importé détruit la preuve de son origine."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from pytest import raises\n\n"
        "raises = mon_module.raises\n\n\n"
        "def test_calcul() -> None:\n"
        "    with raises(ValueError):\n"
        "        calculer()\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_refuse_un_appel_nu_a_raises_importe_de_pytest_comme_oracle(
    tmp_path: Path,
) -> None:
    """Prouve que l'ouverture aux imports directs conserve l'asymétrie des POSITIONS.

    MESURÉ : ``pytest.raises(ValueError)`` appelé hors d'un ``with`` n'entre
    jamais dans le gestionnaire de contexte et ne vérifie donc rien — le gate le
    refuse déjà sous la forme qualifiée. La forme importée directement doit être
    jugée pareil, sans quoi le correctif du faux positif ouvrirait un oracle de
    façade à un caractère près.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from pytest import raises\n\n\n"
        "def test_calcul() -> None:\n"
        "    raises(ValueError)\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_refuse_un_protocol_ecrase_par_une_expression_daffectation(
    tmp_path: Path,
) -> None:
    """Prouve qu'un walrus module-level détruit l'exemption comme une affectation.

    MESURÉ avant correction : ``(Protocol := object)`` était accepté alors que
    ``Protocol = object`` était refusé. La collecte des réaffectations ne lisait
    que des INSTRUCTIONS, et le walrus est une EXPRESSION : l'écrasement lui
    échappait entièrement.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "(Protocol := object)\n\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_ecrase_par_un_walrus_de_comprehension(
    tmp_path: Path,
) -> None:
    """Prouve qu'un walrus écrit dans une compréhension lie bien la portée ENGLOBANTE.

    MESURÉ à l'interpréteur : ``[(P := 1) for _ in range(1)]`` laisse ``P``
    défini au dehors, contrairement à la cible de boucle de la compréhension.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "_charges = [(Protocol := object) for _element in range(1)]\n\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_un_protocol_ecrase_par_un_walrus_de_corps_de_classe(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : un walrus de CORPS DE CLASSE ne lie pas le module.

    MESURÉ à l'interpréteur : après ``class Boite: _valeur = (Protocol :=
    object)``, le nom ``Protocol`` du module vaut encore ce que l'import lui a
    donné, et c'est ``Boite.Protocol`` qui a été créé. Parcourir les corps de
    classes pour y chercher des liaisons du module produirait un faux positif,
    exactement comme pour l'affectation ordinaire déjà couverte.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n\n"
        "class Boite:\n"
        "    _valeur = (Protocol := object)\n\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_accepte_un_protocol_masque_par_une_cible_de_comprehension(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : la cible d'une compréhension ne lie PAS le module.

    MESURÉ à l'interpréteur : après ``[Protocol for Protocol in ('A', 'B')]``, le
    nom ``Protocol`` vaut encore ce que l'import lui a donné. Traiter cette forme
    comme un écrasement produirait un faux positif pur, exactement la pression
    qui fait désarmer un gate.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "_noms = [Protocol for Protocol in ('A', 'B')]\n\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_refuse_un_protocol_ecrase_par_une_affectation_augmentee(
    tmp_path: Path,
) -> None:
    """Prouve qu'une affectation augmentée module-level détruit aussi l'exemption."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "Protocol += ()\n\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_lie_par_un_gestionnaire_dexception(
    tmp_path: Path,
) -> None:
    """Prouve que ``except … as Protocol`` lie le nom, donc détruit son origine."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "try:\n"
        "    charger()\n"
        "except ValueError as Protocol:\n"
        "    class Depot(Protocol):\n"
        "        def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_lie_par_une_capture_de_filtrage(tmp_path: Path) -> None:
    """Prouve qu'une capture ``match``/``case`` réécrit le nom au niveau du module.

    MESURÉ à l'interpréteur : après ``match object:`` / ``case Protocol:``, le nom
    ``Protocol`` vaut ``object`` et la classe qui en hérite a bien ``object``
    dans son MRO. Le contournement est donc VALIDE à l'exécution, pas seulement
    sur le papier — contrairement aux formes qui lèvent une erreur à l'import.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "match object:\n"
        "    case Protocol:\n"
        "        pass\n\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_ecrase_par_un_walrus_dexpression_conditionnelle(
    tmp_path: Path,
) -> None:
    """Prouve que le corps d'une expression CONDITIONNELLE est bien parcouru.

    ``a if c else b`` range son résultat dans un champ nommé ``body`` sans ouvrir
    la moindre portée. Écarter ce champ sur son seul NOM, comme on écarte le
    corps d'une fonction, y perdrait une liaison bien réelle du module : la
    distinction tient à la NATURE du nœud, jamais au nom de son champ.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "_choix = (Protocol := object) if charger() else None\n\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_protocol_delie_par_une_suppression(tmp_path: Path) -> None:
    """Prouve qu'un ``del`` module-level retire au nom son origine prouvée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n"
        "del Protocol\n\n\n"
        "class Depot(Protocol):\n"
        "    def lire(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_classe_locale_heritant_dun_homonyme_de_sa_portee(
    tmp_path: Path,
) -> None:
    """Prouve que la base d'une classe se résout dans SA portée avant le module.

    MESURÉ avant correction : ``Service`` héritait du ``Panne`` LOCAL, ordinaire,
    et son corps vide était pourtant exempté — la résolution par nom sur tout
    l'arbre faisait croire qu'il héritait du type d'exception du module. Le
    correctif précédent avait attaché l'exemption à la POSITION de la définition
    exempte ; ici c'est la RÉSOLUTION de la base qui ignorait les portées.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Panne(ValueError):\n"
        "    pass\n\n\n"
        "def configurer() -> None:\n"
        "    class Panne:\n"
        "        marqueur = 1\n\n"
        "    class Service(Panne):\n"
        "        pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_une_classe_locale_heritant_du_type_dexception_du_module(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : sans homonyme local, la résolution retombe au module.

    Une classe locale qui dérive réellement du type d'exception du module reste
    exempte : le correctif restreint la résolution aux portées, il ne la coupe
    pas. Sans cette preuve, rendre le gate plus strict serait indiscernable de le
    rendre aveugle au cas légitime.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Panne(ValueError):\n"
        "    pass\n\n\n"
        "def configurer() -> None:\n"
        "    class Service(Panne):\n"
        "        pass\n",
    )

    assert "EXECUTABLE_PASS" not in _codes(_scanner(repo))


def test_refuse_une_classe_heritant_dun_nom_dexception_usurpe_localement(
    tmp_path: Path,
) -> None:
    """Prouve qu'une classe locale usurpant un nom builtin n'exempte plus rien."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def configurer() -> None:\n"
        "    class ValueError:\n"
        "        marqueur = 1\n\n"
        "    class Service(ValueError):\n"
        "        pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_une_classe_heritant_dun_nom_dexception_lie_sans_preuve(
    tmp_path: Path,
) -> None:
    """Prouve qu'une liaison locale OPAQUE arrête la résolution sans repli.

    ``ValueError = charger()`` dans une fonction ne dit rien de ce que le nom
    désigne ensuite. Retomber alors sur la preuve d'origine des imports
    exempterait sur la foi d'une orthographe : le nom est lié, donc la question
    est tranchée, et elle l'est contre l'exemption.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def configurer() -> None:\n"
        "    ValueError = charger()\n"
        "    class Service(ValueError):\n"
        "        pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_refuse_une_classe_heritant_dun_parametre_qui_masque_le_module(
    tmp_path: Path,
) -> None:
    """Prouve qu'un PARAMÈTRE masque le type d'exception du module dans le corps."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Panne(ValueError):\n"
        "    pass\n\n\n"
        "def configurer(Panne) -> None:\n"
        "    class Service(Panne):\n"
        "        pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_une_classe_dont_lhomonyme_vit_dans_une_portee_soeur(
    tmp_path: Path,
) -> None:
    """Prouve qu'une portée ne voit PAS ce que déclarent les portées imbriquées.

    Le ``Panne`` déclaré dans une fonction interne n'existe pas pour la fonction
    qui la contient : l'y compter ferait croire à un masquage inexistant et
    signalerait un type d'exception parfaitement valide.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Panne(ValueError):\n"
        "    pass\n\n\n"
        "def configurer() -> None:\n"
        "    def interne() -> None:\n"
        "        class Panne:\n"
        "            marqueur = 1\n\n"
        "    class Service(Panne):\n"
        "        pass\n",
    )

    assert "EXECUTABLE_PASS" not in _codes(_scanner(repo))


def test_refuse_une_classe_heritant_dun_homonyme_dun_corps_de_classe_lointain(
    tmp_path: Path,
) -> None:
    """Prouve qu'un corps de classe LOINTAIN ne participe pas à la résolution.

    Python ne fait pas participer les espaces de noms de classes à la résolution
    des portées imbriquées : ``class Enveloppe:`` déclarant ``Panne`` puis, dans
    une MÉTHODE, ``class Service(Panne)`` lève ``NameError`` à l'exécution. Le
    prêter au ``Panne`` de la classe englobante exempterait une classe qui
    n'hérite en réalité de rien.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Enveloppe:\n"
        "    class Panne(ValueError):\n"
        "        pass\n\n"
        "    def monter(self) -> None:\n"
        "        class Service(Panne):\n"
        "            pass\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_une_classe_heritant_dune_soeur_du_meme_corps_de_classe(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : le corps de classe DIRECT résout bien la base.

    La base d'une classe est évaluée pendant l'exécution du corps qui la
    contient : une sœur déclarée juste au-dessus est visible, et l'exclure
    signalerait un type d'exception valide.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "class Enveloppe:\n"
        "    class Panne(ValueError):\n"
        "        pass\n\n"
        "    class Service(Panne):\n"
        "        pass\n",
    )

    assert "EXECUTABLE_PASS" not in _codes(_scanner(repo))


def test_refuse_un_oracle_herite_dun_test_case_usurpe_dans_une_portee_locale(
    tmp_path: Path,
) -> None:
    """Prouve que la résolution par portée sert AUSSI la preuve des cas de test.

    ``_positions_de_classes_derivees`` répond à deux questions — quelle classe
    est un type d'exception, quelle classe est un cas de test ``unittest``. Le
    même défaut de résolution laissait un ``TestCase`` local usurpé fabriquer un
    receveur d'oracles : ``self.assertVrai(...)`` passait alors pour une
    vérification héritée de la bibliothèque standard.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from unittest import TestCase\n\n\n"
        "def monter() -> None:\n"
        "    class TestCase:\n"
        "        marqueur = 1\n\n"
        "    class Suite(TestCase):\n"
        "        def test_calcul(self) -> None:\n"
        "            self.assertVrai(calculer())\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_accepte_un_oracle_herite_dun_test_case_importe_du_module(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : un cas de test réel garde ses oracles hérités."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "from unittest import TestCase\n\n\n"
        "class Suite(TestCase):\n"
        "    def test_calcul(self) -> None:\n"
        "        self.assertEqual(calculer(), 1)\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_refuse_un_compose_conditionnel_de_repli_qui_absorbe_lechec(
    tmp_path: Path,
) -> None:
    """Prouve qu'un ``if`` placé en repli ``||`` ne peut pas rendre l'étape verte.

    MESURÉ avant correction : ``gate.py || if true; then :; fi`` était accepté
    dans un job requis. Le ``||`` exempte l'échec de gauche, le ``if`` rend 0, et
    l'étape passe au vert avec son contrôle rouge. Le critère est celui des
    groupes ``|| { … }`` : la branche exécutée propage-t-elle l'échec ?
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py || if true; then :; fi"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_compose_conditionnel_de_repli_qui_propage_lechec(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : un repli conditionnel qui sort non nul reste licite."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py || if true; then exit 1; fi"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_un_compose_conditionnel_de_repli_dont_le_sinon_absorbe(
    tmp_path: Path,
) -> None:
    """Prouve que TOUTE branche du repli doit propager, pas seulement la première."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py || if true; then exit 1; else echo repli; fi"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_compose_conditionnel_de_repli_dont_chaque_branche_propage(
    tmp_path: Path,
) -> None:
    """Prouve qu'un repli à ``elif`` n'est pas condamné pour sa CONDITION.

    La condition d'un ``elif`` n'est pas une branche exécutée en cas d'échec :
    la juger comme telle refuserait un repli pourtant propageant, donc un faux
    positif sur une forme légitime.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py || if a; then exit 1; elif b; then exit 2; '
        'else exit 3; fi"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_un_filtrage_de_repli_qui_absorbe_lechec(tmp_path: Path) -> None:
    """Prouve qu'un ``case`` en repli est jugé au même critère qu'un ``if``.

    MESURÉ : ``|| case … esac`` échappait lui aussi à tous les motifs. Fermer le
    seul ``if`` laisserait le contournement disponible au mot-clé voisin, que le
    gate tokenise pourtant déjà comme la même conditionnelle.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py || case x in *) : ;; esac"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_filtrage_de_repli_dont_chaque_motif_propage(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : un ``case`` de repli qui sort non nul reste licite."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py || case x in *) exit 1 ;; esac"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_un_compose_conditionnel_de_repli_sans_branche_lisible(
    tmp_path: Path,
) -> None:
    """Prouve qu'une conditionnelle de repli ILLISIBLE est refusée, non acceptée.

    Une conditionnelle dont aucune branche ne se laisse isoler ne prouve rien du
    sort de l'échec. La traiter comme propageante — ce que fait un ``all`` sur
    une liste vide — rendrait le contrôle muet devant la première syntaxe que le
    lecteur de jetons ne sait pas suivre, soit le contournement suivant tout
    trouvé. L'incertitude se tranche donc en faveur du contrôle.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "gate.py || if verifier; fi"\n',
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_compose_conditionnel_de_repli_cite_dans_une_chaine(
    tmp_path: Path,
) -> None:
    """Prouve que la neutralisation des quotes protège toujours un repli CITÉ.

    Un repli conditionnel écrit à l'intérieur d'un argument littéral n'est pas
    exécuté : le signaler ferait un faux positif sur une commande qui ne force
    aucun succès.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: \"gate.py --motif '|| if true; then :; fi'\"\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


@pytest.mark.parametrize("valeur", ("'2'", '"-1"', "'1.5'"))
def test_refuse_continue_on_error_numerique_non_nul_ecrit_comme_chaine_quotee(
    tmp_path: Path,
    valeur: str,
) -> None:
    """Prouve qu'une chaîne numérique est jugée sur sa VALEUR, comme un entier.

    MESURÉ avant correction : ``'2'`` était accepté alors que ``2`` non quoté et
    ``'true'`` étaient refusés. La liste des chaînes vraies est fermée
    (``true``, ``yes``, ``on``, ``y``, ``1``) et ne couvrait aucun autre
    numérique quoté — un caractère de quote suffisait à tolérer les erreurs d'un
    job requis.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/continue.yml",
        "jobs:\n"
        "  gates:\n"
        f"    continue-on-error: {valeur}\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


@pytest.mark.parametrize("valeur", ("'0'", '"0.0"'))
def test_accepte_continue_on_error_numerique_nul_ecrit_comme_chaine_quotee(
    tmp_path: Path,
    valeur: str,
) -> None:
    """Prouve la garde INVERSE : un zéro quoté ne tolère rien et reste accepté."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/continue.yml",
        "jobs:\n"
        "  gates:\n"
        f"    continue-on-error: {valeur}\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "repli",
    ("exit 00", "exit 000", "exit 256", "exit 0512"),
    ids=("deux-zeros", "trois-zeros", "multiple-256", "multiple-256-zero-tete"),
)
def test_refuse_un_repli_exit_dont_la_valeur_est_nulle_quelle_que_soit_lorthographe(
    tmp_path: Path, repli: str
) -> None:
    """Prouve que la VALEUR de la sortie décide, jamais son orthographe.

    MESURÉ dans bash, dash et sh : ``exit 00``, ``exit 000``, ``exit 256`` et
    ``exit 0512`` rendent tous 0 (le shell tronque modulo 256). Un motif exigeant
    le texte exact ``exit 0`` laissait donc passer quatre écritures du même
    succès forcé.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/valeur.yml", f"gate.py || {repli}"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "repli",
    ("exit 0x0", "exit 1x", "exit 12abc"),
    ids=("hexadecimal", "suffixe-court", "suffixe-long"),
)
def test_refuse_un_repli_exit_dont_largument_nest_pas_un_litteral_decimal(
    tmp_path: Path, repli: str
) -> None:
    """Prouve que seule une sortie PROUVÉE non nulle est admise en repli.

    MESURÉ dans bash et dash : ``exit 0x0``, ``exit 1x`` et ``exit 12abc`` rendent
    tous 2 — l'argument n'est pas numérique, le shell signale une erreur d'usage.
    Ces formes n'absorbent donc rien, mais elles ne PROUVENT pas davantage la
    propagation de l'échec du CONTRÔLE : le statut rendu est celui de l'erreur
    d'usage. Lire le seul préfixe décimal certifierait ``exit 1x`` comme
    propageant alors que le shell le refuse ; la liste blanche exige donc le
    littéral décimal ENTIER, et l'inconnu bloque.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/hexa.yml", f"gate.py || {repli}"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "sortie",
    ("exit 00", "exit 000", "exit 256", "exit 0512"),
    ids=("deux-zeros", "trois-zeros", "multiple-256", "multiple-256-zero-tete"),
)
def test_refuse_une_sortie_nue_dont_la_valeur_est_nulle_quelle_que_soit_lorthographe(
    tmp_path: Path, sortie: str
) -> None:
    """Prouve que la sortie NUE est jugée sur sa VALEUR, comme celle d'un repli.

    MESURÉ avant correction, la même question recevait deux réponses opposées :
    ``gate.py || exit 00`` était refusé — le repli lit ``N % 256`` — quand
    ``gate.py; exit 00`` passait, le chemin direct exigeant l'orthographe exacte
    ``0``. MESURÉ dans bash, dash et sh : ``exit 00``, ``exit 000``, ``exit 256``
    et ``exit 0512`` rendent tous 0 et forcent le succès de l'étape aussi
    sûrement que ``exit 0``. Les deux chemins consomment désormais le même
    prédicat de valeur, si bien qu'une orthographe inédite du zéro ne peut plus
    passer d'un côté en étant refusée de l'autre.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/valeur_directe.yml", f"gate.py; {sortie}"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "sortie",
    ("exit 1", "exit 2", "exit 255", "exit 257"),
    ids=("un", "deux", "dernier-non-nul", "au-dela-du-modulo"),
)
def test_accepte_une_sortie_nue_dont_la_valeur_nest_pas_nulle(
    tmp_path: Path, sortie: str
) -> None:
    """Prouve la garde INVERSE : une sortie non nulle propage et reste licite.

    MESURÉ dans bash, dash et sh : ``exit 1``, ``exit 2``, ``exit 255`` et
    ``exit 257`` rendent 1, 2, 255 et 1 — jamais 0. Sans cette garde, juger la
    valeur reviendrait à refuser toute sortie explicite, y compris celle qui
    fait précisément échouer le job requis.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/valeur_non_nulle.yml", f"gate.py; {sortie}"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "sortie",
    ("exit 0x0", "exit 1x", "exit 12abc"),
    ids=("hexadecimal", "suffixe-court", "suffixe-long"),
)
def test_accepte_une_sortie_nue_dont_largument_nest_pas_un_litteral_decimal(
    tmp_path: Path, sortie: str
) -> None:
    """Prouve la conséquence assumée du prédicat partagé sur les non-littéraux.

    MESURÉ dans bash, dash et sh : ``exit 0x0``, ``exit 1x`` et ``exit 12abc``
    rendent 2 — l'argument n'est pas numérique, le shell signale une erreur
    d'usage et l'étape ÉCHOUE. Ces écritures ne forcent donc aucun succès, et le
    chemin direct, qui DÉTECTE le succès forcé, ne les signale pas.

    Le chemin de repli les refuse au contraire, et ce n'est pas une divergence de
    prédicat : il pose la question inverse — il exige la PREUVE que la branche
    propage l'échec du CONTRÔLE — et un statut 2 d'erreur d'usage ne prouve rien
    de tel. Même prédicat de valeur des deux côtés, deux régimes assumés pour
    l'inconnu : liste noire à gauche, liste blanche à droite.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/non_decimal_direct.yml", f"gate.py; {sortie}"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_une_sortie_de_valeur_nulle_gardee_par_une_conditionnelle(
    tmp_path: Path,
) -> None:
    """Prouve que juger la VALEUR ne supprime pas la garde de CONDITIONNALITÉ.

    Une sortie nulle placée entre l'ouverture et la fermeture d'un ``if`` ne
    s'exécute pas toujours : elle reste licite. La garde vaut pour toutes les
    orthographes du zéro, et pas seulement pour celle que l'ancien motif
    reconnaissait — sans quoi élargir le motif transformerait un contrôle
    conditionnel légitime en faux positif.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise(
        repo, ".github/workflows/valeur_gardee.yml", "if true; then exit 00; fi"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "repli",
    (
        "env true",
        "/usr/bin/env true",
        "nice true",
        "timeout 1 true",
        "xargs true",
        "env -i true",
    ),
    ids=("env", "env-chemin", "nice", "timeout", "xargs", "env-option"),
)
def test_refuse_un_repli_vers_true_lance_par_un_porteur_de_commande(
    tmp_path: Path, repli: str
) -> None:
    """Prouve que la règle ne dépend plus d'une liste de préfixes reconnus.

    ``env``, ``nice``, ``timeout``, ``xargs`` lancent tous ``true`` et rendent 0 :
    MESURÉ à 0 pour chacun. Énumérer les porteurs ne converge pas — la liste est
    ouverte — donc c'est la branche qui doit PROUVER qu'elle propage.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/porteur.yml", f"gate.py || {repli}"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_vers_une_commande_inconnue_dans_un_job_requis(
    tmp_path: Path,
) -> None:
    """Prouve le cœur de l'inversion : l'inconnu bloque au lieu de passer.

    Une commande dont le gate ne sait rien peut rendre 0 comme 1. La supposer
    propageante, c'est parier ; et c'est ce pari qui rouvrait la classe entière à
    chaque nouvelle orthographe. Le doute se tranche désormais en faveur du
    contrôle requis.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/inconnue.yml", "gate.py || outil_maison --repli"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_vers_return_dont_la_valeur_est_nulle(tmp_path: Path) -> None:
    """Prouve que ``return`` est jugé à la valeur comme ``exit``.

    MESURÉ : ``f(){ return 00; }; f`` rend 0 dans bash. La forme est donc un
    succès forcé, malgré un mot-clé qui suggère la propagation.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/retour.yml", "gate.py || { echo ko; return 00; }"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_repli_vers_return_non_nul_dans_un_groupe(tmp_path: Path) -> None:
    """Prouve la garde INVERSE de la liste blanche : ``return 1`` propage et reste licite."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/retour_ok.yml", "gate.py || { echo ko; return 1; }"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_accepte_un_repli_dont_la_derniere_commande_est_un_compose_propageant(
    tmp_path: Path,
) -> None:
    """Prouve que la dernière commande d'un groupe est lue même composée.

    Découper le corps sur les seuls ``;`` faisait de ``fi`` la dernière commande
    d'un groupe terminé par une conditionnelle : un repli parfaitement propageant
    était alors refusé.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/compose_ok.yml",
        "gate.py || { echo ko; if verifier; then exit 1; else exit 2; fi }",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_un_repli_dont_le_compose_final_absorbe(tmp_path: Path) -> None:
    """Prouve la garde symétrique : lue en profondeur, la branche absorbante est vue."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/compose_ko.yml",
        "gate.py || { echo ko; if verifier; then exit 1; else echo absorbe; fi }",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_repli_absorbant_dans_un_job_non_requis(tmp_path: Path) -> None:
    """Prouve que l'inversion reste bornée aux identifiants du contrat.

    Un job hors ``target_required_job_ids`` n'atteste rien : y refuser ``|| true``
    transformerait le durcissement en interdiction générale du repli shell.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/optionnel.yml",
        "jobs:\n"
        "  rapport-optionnel:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: 'gate.py || env true'\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_un_controle_direct_dont_le_else_absorbe_apres_un_elif(
    tmp_path: Path,
) -> None:
    """Prouve que la branche ``else`` est mesurée même quand un ``elif`` la précède.

    MESURÉ avant correction : la seule branche relevée était la CONDITION du
    ``elif`` (« false »), tenue pour propageante, et le corps ``else`` — le seul
    exécuté quand toutes les conditions échouent — n'était jamais lu. Un ``elif``
    suffisait donc à rendre la garde muette.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if python3 core/scripts/run_security_scan.py; then",
                "  echo ok",
                "elif false; then",
                "  exit 1",
                "else",
                "  echo absorbe",
                "fi",
            ),
        ),
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_controle_direct_dont_le_corps_delif_absorbe(tmp_path: Path) -> None:
    """Prouve que le CORPS d'un ``elif`` est lui aussi une branche d'échec mesurée.

    Quand le contrôle échoue et que la condition du ``elif`` est vraie, c'est son
    corps qui fixe le statut de l'étape : le laisser hors mesure rouvrait la même
    absorption d'un cran plus loin.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if python3 core/scripts/run_security_scan.py; then",
                "  echo ok",
                "elif verifier; then",
                "  echo absorbe",
                "else",
                "  exit 1",
                "fi",
            ),
        ),
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_controle_direct_a_elif_sans_else(tmp_path: Path) -> None:
    """Prouve qu'une chaîne ``elif`` sans ``else`` laisse un chemin muet.

    Si le contrôle échoue ET que la condition du ``elif`` est fausse, rien ne
    s'exécute : le ``fi`` rend 0 et le job requis est vert avec son contrôle
    rouge. La branche vide doit donc compter comme absorbante.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if python3 core/scripts/run_security_scan.py; then",
                "  echo ok",
                "elif verifier; then",
                "  exit 1",
                "fi",
            ),
        ),
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_controle_direct_dont_chaque_branche_propage_apres_un_elif(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : toutes branches propageantes, le ``elif`` reste licite.

    Sans ce cas, corriger la lecture des branches pourrait se réduire à « refuser
    dès qu'un ``elif`` apparaît », ce qui serait un faux positif sur une garde
    parfaitement propageante.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if python3 core/scripts/run_security_scan.py; then",
                "  echo ok",
                "elif verifier; then",
                "  exit 1",
                "else",
                "  exit 2",
                "fi",
            ),
        ),
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_un_repli_vers_false_neutralise_par_un_tube(tmp_path: Path) -> None:
    """Prouve que ``false`` doit être la commande ENTIÈRE, pas le début d'un tube.

    MESURÉ : ``bash -c 'false | true'`` rend 0 — dans un tube, c'est le DERNIER
    maillon qui fixe le statut. Reconnaître ``false`` sur le seul début de la
    commande certifiait donc propageant un repli qui réussit toujours.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/tube_false.yml", "gate.py || false | true"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_groupe_neutralise_par_un_tube(tmp_path: Path) -> None:
    """Prouve qu'un groupe propageant ne rachète rien s'il alimente un tube.

    MESURÉ : ``bash -c '{ exit 1; } | true'`` rend 0. Borner la branche à la
    fermeture du groupe sans regarder ce qui SUIT laissait le tube hors mesure.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo, ".github/workflows/tube_groupe.yml", "gate.py || { exit 1; } | true"
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_une_negation_dont_la_branche_est_neutralisee_par_un_tube(
    tmp_path: Path,
) -> None:
    """Prouve que la garde ``if !`` juge elle aussi la commande entière du tube."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if ! python3 core/scripts/run_security_scan.py; then",
                "  false | true",
                "fi",
            ),
        ),
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_une_branche_ou_un_filtrage_precede_un_groupe_propageant(
    tmp_path: Path,
) -> None:
    """Prouve que le motif ``*)`` d'un ``case`` ne dérègle pas le compte des groupes.

    Un motif de ``case`` s'écrit avec une parenthèse FERMANTE sans ouvrante. Un
    compteur unique passe alors en négatif, et le ``{`` qui suit le ramène à zéro
    au lieu de un : le découpage coupe à l'intérieur du groupe et prend ``}``
    pour la dernière commande. MESURÉ dans bash, la branche rend pourtant 1.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if ! python3 core/scripts/run_security_scan.py; then",
                "  case x in *) : ;; esac",
                "  { exit 1; }",
                "fi",
            ),
        ),
    )

    assert _codes(_scanner(repo)) == set()


def test_accepte_un_repli_conditionnel_suivi_dun_enchainement_licite(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : exiger une branche TERMINALE ne condamne pas ``fi``.

    Sans ce cas, borner la conditionnelle avant son mot de fermeture ferait du
    ``fi`` lui-même une commande enchaînée, et tout ``|| if … fi`` propageant
    serait refusé à tort.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _workflow_commande_requise_citee(
        repo,
        ".github/workflows/compose_suite.yml",
        "gate.py || if verifier; then exit 1; else exit 2; fi",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_une_negation_dont_le_then_absorbe_malgre_un_elif_propageant(
    tmp_path: Path,
) -> None:
    """Prouve que la lecture des ``if !`` reste bornée à leur PREMIÈRE branche.

    Sur une négation, la branche prise quand le contrôle échoue est le ``then`` ;
    un ``elif`` propageant ne s'exécute alors jamais et ne rachète rien. Corriger
    le parcours des branches ne doit pas déplacer cette frontière.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run(
            "security",
            (
                "if ! python3 core/scripts/run_security_scan.py; then",
                "  echo absorbe",
                "elif verifier; then",
                "  exit 1",
                "fi",
            ),
        ),
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_sous_un_protocol_masque_par_une_classe_locale(
    tmp_path: Path,
) -> None:
    """Prouve qu'une classe locale homonyme désarme l'exemption du protocole importé.

    MESURÉ : ``C`` hérite de la classe ordinaire déclarée dans ``f``, jamais du
    protocole du module, si bien que son ellipse est un corps de méthode vide.
    Résoudre la base sur le seul alias du module ignorait ce masquage lexical.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n\n"
        "def f() -> None:\n"
        "    class Protocol:\n"
        "        marqueur = 1\n\n"
        "    class C(Protocol):\n"
        "        def manque(self) -> None: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_sous_un_protocol_masque_par_une_affectation_locale(
    tmp_path: Path,
) -> None:
    """Prouve que toute liaison locale, pas seulement une classe, éteint l'exemption.

    ``Protocol = object`` dans la portée où la base est écrite fait hériter
    ``C`` d'``object`` : le nom du module n'est plus celui qui est résolu.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n\n"
        "def f() -> None:\n"
        "    Protocol = object\n\n"
        "    class C(Protocol):\n"
        "        def manque(self) -> None: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_sous_un_protocol_masque_par_un_parametre(
    tmp_path: Path,
) -> None:
    """Prouve qu'un paramètre homonyme masque le protocole dans tout le corps."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "from typing import Protocol\n\n\n"
        "def f(Protocol) -> None:\n"
        "    class C(Protocol):\n"
        "        def manque(self) -> None: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_sous_un_protocol_dont_le_module_est_masque(
    tmp_path: Path,
) -> None:
    """Prouve que le PORTEUR d'une base qualifiée se résout aussi par portée.

    ``class t: Protocol = object`` dans ``f`` fait désigner ``object`` à
    ``t.Protocol`` : exempter sur la foi de l'import du module reviendrait à
    juger l'orthographe du porteur plutôt que ce qu'il désigne à cet endroit.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import typing as t\n\n\n"
        "def f() -> None:\n"
        "    class t:\n"
        "        Protocol = object\n\n"
        "    class C(t.Protocol):\n"
        "        def manque(self) -> None: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_sous_un_abstractmethod_masque_localement(
    tmp_path: Path,
) -> None:
    """Prouve qu'un décorateur local homonyme désarme l'exemption comme une base locale.

    Le décorateur est évalué dans la portée où il est écrit : ici il désigne la
    fonction identité déclarée juste au-dessus, qui n'abstrait rien du tout.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/base.py",
        "from abc import abstractmethod\n\n\n"
        "def f() -> None:\n"
        "    def abstractmethod(g):\n"
        "        return g\n\n"
        "    class C:\n"
        "        @abstractmethod\n"
        "        def manque(self) -> None: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_une_ellipse_sous_un_abstractmethod_dont_le_module_est_masque(
    tmp_path: Path,
) -> None:
    """Prouve que le porteur ``abc`` d'un décorateur qualifié se résout par portée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/base.py",
        "import abc\n\n\n"
        "def f(abc) -> None:\n"
        "    class C:\n"
        "        @abc.abstractmethod\n"
        "        def manque(self) -> None: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_une_classe_locale_heritant_du_protocol_du_module(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : sans homonyme, la classe locale reste un protocole.

    La résolution par portée ne doit pas inventer un masquage : aucune liaison
    de ``fabriquer`` ne porte le nom ``Protocol``, donc la base est bien celle
    du module et l'ellipse déclarative reste licite.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n\n"
        "def fabriquer() -> type:\n"
        "    class Depot(Protocol):\n"
        "        def lire(self) -> str: ...\n\n"
        "    return Depot\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_accepte_un_abstractmethod_du_module_dans_une_classe_locale(
    tmp_path: Path,
) -> None:
    """Prouve que le décorateur importé garde son exemption dans une portée imbriquée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/base.py",
        "from abc import abstractmethod\n\n\n"
        "def fabriquer() -> type:\n"
        "    class Socle:\n"
        "        @abstractmethod\n"
        "        def lire(self) -> str: ...\n\n"
        "    return Socle\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_un_protocol_supprime_par_del_dattribut(tmp_path: Path) -> None:
    """Prouve que ``del`` d'un attribut détruit la preuve autant que sa réécriture.

    Après ``del t.Protocol``, la classe qui prétend en hériter lève une
    ``AttributeError`` à l'import : l'exemption ne repose plus sur rien. Le gate
    surveillait la réaffectation d'attribut mais pas sa suppression.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\ndel t.Protocol\n\n\n"
        "class S(t.Protocol):\n    def f(self) -> None: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_abstractmethod_supprime_par_del_dattribut(tmp_path: Path) -> None:
    """Prouve que la suppression vise la PREUVE d'origine, pas le seul nom Protocol."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/base.py",
        "import abc\n\ndel abc.abstractmethod\n\n\n"
        "class Socle:\n    @abc.abstractmethod\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_un_module_typing_dont_un_autre_attribut_est_supprime(
    tmp_path: Path,
) -> None:
    """Prouve que seule la suppression de l'attribut PROUVANT retire l'exemption."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\ndel t.TYPE_CHECKING\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_un_protocol_reaffecte_par_affectation_augmentee_dattribut(
    tmp_path: Path,
) -> None:
    """Prouve que l'affectation AUGMENTÉE d'un attribut détruit la preuve d'origine.

    Le chemin des NOMS comptait déjà ``ast.AugAssign`` ; celui des ATTRIBUTS ne
    le lisait pas. MESURÉ à l'interpréteur, ``t.Protocol += ()`` réécrit bien
    l'attribut du module : la classe qui en hérite ensuite ne dérive plus du
    protocole de la bibliothèque standard, et l'exemption ne repose plus sur rien.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\nt.Protocol += ()\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_abstractmethod_reaffecte_par_affectation_augmentee_dattribut(
    tmp_path: Path,
) -> None:
    """Prouve que l'affectation augmentée vise la PREUVE, pas le seul nom Protocol."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/base.py",
        "import abc\n\nabc.abstractmethod += ()\n\n\n"
        "class Socle:\n    @abc.abstractmethod\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_un_module_typing_dont_un_autre_attribut_est_augmente(
    tmp_path: Path,
) -> None:
    """Prouve que seule l'augmentation de l'attribut PROUVANT retire l'exemption.

    Sans cette borne, traiter ``ast.AugAssign`` reviendrait à condamner tout
    module dont un attribut sans rapport est modifié — MESURÉ à l'interpréteur,
    ``t.Any += ()`` laisse ``t.Protocol`` intact.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\nt.Any += ()\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_un_protocol_reaffecte_par_cible_de_comprehension_dattribut(
    tmp_path: Path,
) -> None:
    """Prouve qu'une cible de compréhension ATTRIBUT écrase bien le module.

    Ici les deux chemins doivent DIVERGER, et ne pas diverger était le défaut.
    MESURÉ à l'interpréteur : ``[1 for Protocol in (object,)]`` laisse le NOM du
    module intact — la portée de la compréhension le confine — tandis que
    ``[1 for t.Protocol in (object,)]`` réécrit l'ATTRIBUT du module, qu'aucune
    portée ne protège. La compréhension est lue jusque dans les
    sous-expressions, un simple ``x = [...]`` suffisant sinon à la cacher.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\nx = [1 for t.Protocol in (object,)]\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_refuse_un_abstractmethod_reaffecte_par_cible_de_generateur(
    tmp_path: Path,
) -> None:
    """Prouve que le générateur lie sa cible attribut comme la compréhension."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/base.py",
        "import abc\n\nlist(1 for abc.abstractmethod in (staticmethod,))\n\n\n"
        "class Socle:\n    @abc.abstractmethod\n"
        "    def calculer(self) -> str: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_un_protocol_dont_le_nom_nu_est_cible_de_comprehension(
    tmp_path: Path,
) -> None:
    """Prouve que la cible de compréhension d'un NOM reste confinée à sa portée.

    MESURÉ à l'interpréteur, après ``[1 for Protocol in (object,)]`` le nom du
    module vaut toujours le protocole importé : révoquer ici serait un faux
    positif, et c'est la raison pour laquelle les deux chemins divergent.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "from typing import Protocol\n\n[1 for Protocol in (object,)]\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_accepte_une_comprehension_dattribut_enfermee_dans_un_lambda(
    tmp_path: Path,
) -> None:
    """Prouve que la compréhension d'un corps de lambda n'écrit rien à l'import.

    MESURÉ à l'interpréteur, ``f = lambda: [1 for t.Protocol in (object,)]``
    laisse l'attribut intact tant que ``f`` n'est pas appelée : la collecte doit
    donc sauter les portées PROPRES, exactement comme le fait le chemin des noms.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\nf = lambda: [1 for t.Protocol in (object,)]\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_accepte_un_module_typing_dont_un_autre_attribut_est_en_comprehension(
    tmp_path: Path,
) -> None:
    """Prouve que la compréhension ne révoque que l'attribut PROUVANT."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/interfaces.py",
        "import typing as t\n\nx = [1 for t.Any in (object,)]\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> str: ...\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_une_absence_dimplementation_aliasee_par_destructuration(
    tmp_path: Path,
) -> None:
    """Prouve qu'une destructuration lie l'absence d'implémentation position par position.

    La preuve d'alias n'était lue que sur une affectation à cible unique : le
    tuple de droite n'étant lui-même ni un nom ni un attribut, la même absence
    d'implémentation passait pour un objet quelconque.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import builtins\n\n"
        "A, B = builtins.NotImplementedError, builtins.NotImplemented\n\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "def f() -> None:\n    raise A\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_une_absence_dimplementation_destructuree_apres_une_etoile(
    tmp_path: Path,
) -> None:
    """Prouve que l'étoile n'aligne pas moins les positions qui la suivent.

    ``*debut, Absence`` lie la DERNIÈRE valeur à ``Absence`` : l'appariement se
    fait par la droite pour tout ce qui suit l'étoile.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import builtins\n\n"
        "*debut, Absence = 1, 2, builtins.NotImplementedError\n\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "def f() -> None:\n    raise Absence\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_accepte_une_destructuration_dont_la_position_levee_nest_pas_prouvee(
    tmp_path: Path,
) -> None:
    """Prouve que l'appariement ne contamine pas la position VOISINE de la preuve.

    Prouver toutes les cibles dès qu'UNE valeur convient serait l'erreur
    symétrique du défaut corrigé : ``B`` désigne une erreur métier, et la lever
    n'est pas un stub.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import builtins\nimport metier\n\n"
        "A, B = builtins.NotImplementedError, metier.Erreur\n\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "def f() -> None:\n    raise B\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_accepte_une_destructuration_de_modules_metier(tmp_path: Path) -> None:
    """Prouve qu'une destructuration sans absence d'implémentation ne déclenche rien."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import mon_module\nimport autre_module\n\n"
        "A, B = mon_module.Erreur, autre_module.Valeur\n\n\n"
        "def f() -> None:\n    raise A\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_une_absence_dimplementation_aliasee_en_chaine(tmp_path: Path) -> None:
    """Prouve que la preuve d'absence se propage le long d'un alias d'alias.

    MESURÉ : ``Alias`` vaut bien l'exception de l'interpréteur à l'exécution, si
    bien que ``raise Alias`` est le même stub que la levée directe. S'arrêter au
    premier cran laissait la chaîne entière échapper à la règle.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import builtins\n\n"
        "Absence = builtins.NotImplementedError\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "Alias = Absence\n\n\n"
        "def f() -> None:\n    raise Alias\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_une_chaine_dalias_dont_le_maillon_source_est_collecte_en_dernier(
    tmp_path: Path,
) -> None:
    """Prouve que la propagation atteint son POINT FIXE, et pas seulement un tour.

    MESURÉ : la collecte des liaisons visite le ``finally`` AVANT les
    gestionnaires, si bien que ``Alias = Absence`` est lu avant l'affectation qui
    prouve ``Absence``. Un seul tour de propagation laisserait donc ``Alias``
    inconnu, alors que le repli d'import le lie bien à l'exception de
    l'interpréteur. Sans ce cas, réduire la boucle à un tour passait inaperçu.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import builtins\n\n"
        "try:\n    import module_optionnel\n"
        "except ImportError:\n"
        "    Absence = builtins.NotImplementedError\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "finally:\n    Alias = Absence\n\n\n"
        "def f() -> None:\n    raise Alias\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_accepte_une_chaine_dalias_dont_lorigine_nest_pas_prouvee(
    tmp_path: Path,
) -> None:
    """Prouve que la propagation s'arrête au maillon dont l'origine est inconnue."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import metier\n\nRacine = metier.Erreur\nAlias = Racine\n\n\n"
        "def f() -> None:\n    raise Alias\n",
    )

    assert _codes(_scanner(repo)) == set()


@pytest.mark.parametrize(
    "source",
    (
        "from typing_extensions import Protocol\n\n\nclass Service(Protocol):\n",
        "from typing_extensions import Protocol as Interface\n\n\n"
        "class Service(Interface):\n",
        "import typing_extensions\n\n\nclass Service(typing_extensions.Protocol):\n",
        "import typing_extensions as te\n\n\nclass Service(te.Protocol):\n",
    ),
    ids=("import-direct", "import-alias", "module", "module-alias"),
)
def test_accepte_une_ellipse_de_protocole_retroporte_par_typing_extensions(
    tmp_path: Path, source: str
) -> None:
    """Prouve que le rétroportage ``typing_extensions`` vaut la bibliothèque standard.

    MESURÉ avant correction : seul le module ``typing`` était reconnu, si bien
    que les quatre formes ci-dessus étaient signalées ``EXECUTABLE_ELLIPSIS``
    alors que ``from typing import Protocol`` passait. ``typing_extensions`` est
    l'écriture normale d'un protocole sur les versions de Python où ``typing``
    ne l'expose pas encore : un gate qui refuse cet idiome se fait désarmer par
    ceux qu'il gêne.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/ports.py", source + "    def calculer(self) -> int: ...\n")

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_accepte_un_protocole_runtime_checkable_de_typing_extensions(
    tmp_path: Path,
) -> None:
    """Prouve que le décorateur rétroporté accompagne le protocole sans le refuser."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/ports.py",
        "from typing_extensions import Protocol, runtime_checkable\n\n\n"
        "@runtime_checkable\n"
        "class Service(Protocol):\n"
        "    def calculer(self) -> int: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_accepte_un_protocole_importe_des_deux_modules_selon_la_version(
    tmp_path: Path,
) -> None:
    """Prouve que le repli d'import entre les deux modules garde l'exemption."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/ports.py",
        "try:\n"
        "    from typing import Protocol\n"
        "except ImportError:\n"
        "    from typing_extensions import Protocol\n\n\n"
        "class Service(Protocol):\n"
        "    def calculer(self) -> int: ...\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "source",
    (
        "from typing_extensions import Protocol\nProtocol = object\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> int: ...\n",
        "from typing_extensions import Protocol\ndel Protocol\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> int: ...\n",
        "import typing_extensions as te\nte.Protocol = object\n\n\n"
        "class Service(te.Protocol):\n    def calculer(self) -> int: ...\n",
        "import typing_extensions as te\ndel te.Protocol\n\n\n"
        "class Service(te.Protocol):\n    def calculer(self) -> int: ...\n",
        "from typing_extensions import Protocol\n\n\n"
        "def monter() -> None:\n"
        "    class Protocol:\n        marqueur = 1\n\n"
        "    class Service(Protocol):\n        def calculer(self) -> int: ...\n",
    ),
    ids=(
        "nom-reaffecte",
        "nom-supprime",
        "attribut-reaffecte",
        "attribut-supprime",
        "masquage-local",
    ),
)
def test_refuse_un_protocole_typing_extensions_dont_la_preuve_est_revoquee(
    tmp_path: Path, source: str
) -> None:
    """Prouve la garde INVERSE : le rétroportage subit les mêmes révocations que ``typing``.

    Reconnaître un second module sans lui appliquer les révocations déjà en
    place ouvrirait le contournement exact que celles-ci ferment : réaffecter le
    nom, le supprimer, réécrire ou supprimer l'attribut prouvant, ou masquer le
    nom dans une portée locale.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/ports.py", source)

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_une_exception_metier_homonyme_de_labsence_dimplementation(
    tmp_path: Path,
) -> None:
    """Prouve qu'un PORTEUR non prouvé ne fait pas d'un homonyme un stub.

    MESURÉ avant correction : la levée de l'attribut HOMONYME porté par un module
    métier était refusée sur la seule orthographe de cet attribut, alors que la
    règle voisine sur les bases d'exception exige, elle, un porteur prouvé. Un
    module métier est libre de nommer ainsi son type d'erreur : l'attribut ne
    désigne alors pas l'exception de l'interpréteur.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import mon_module\n\n\n"
        "def calculer() -> int:\n"
        "    raise mon_module.NotImplementedError\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert _codes(_scanner(repo)) == set()


def test_accepte_un_alias_construit_depuis_une_exception_metier_homonyme(
    tmp_path: Path,
) -> None:
    """Prouve que le chemin des ALIAS exige le même porteur prouvé que la levée directe.

    Sans cette symétrie, l'affectation recevant l'attribut HOMONYME d'un module
    métier liait le nom à l'absence d'implémentation, et le ``raise`` qui suit
    était refusé par ricochet — le même faux positif, déplacé d'une ligne.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import mon_module\n\n"
        "Absence = mon_module.NotImplementedError\n\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "def calculer() -> int:\n    raise Absence\n",
    )

    assert _codes(_scanner(repo)) == set()


def test_refuse_une_absence_qualifiee_par_un_alias_prouve_du_module_builtins(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : le porteur prouvé reste refusé, même sous alias."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import builtins as b\n\n\n"
        "def calculer() -> int:\n"
        "    raise b.NotImplementedError\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_un_repli_masque_par_une_quote_echappee_hors_chaine(
    tmp_path: Path,
) -> None:
    """Prouve qu'un antislash devant une quote n'ouvre aucune chaîne, comme dans le shell.

    MESURÉ dans bash : ``python3 -c 'import sys; sys.exit(1)' \\" || true`` sort
    en 0 — l'antislash rend le guillemet littéral et le repli s'applique. La
    neutralisation lisait pourtant ce guillemet comme une OUVERTURE et effaçait
    tout ce qui suivait, si bien que le repli devenait invisible et que l'étape
    d'un job requis restait verte sur un contrôle rouge.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: 'python3 scripts/quality/no_stub_gate.py \\\" || true'\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_precede_dun_antislash_lui_meme_echappe(
    tmp_path: Path,
) -> None:
    """Prouve que l'échappement consomme EXACTEMENT deux caractères.

    ``gate.py \\\\ || true`` passe un antislash littéral en argument puis
    applique bien son repli : consommer un caractère de trop ferait disparaître
    l'espace, et un de moins rouvrirait la brèche précédente.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: 'python3 scripts/quality/no_stub_gate.py \\\\ || true'\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_colle_a_une_quote_echappee(tmp_path: Path) -> None:
    """Prouve que l'échappement s'arrête au caractère échappé, sans manger le suivant.

    MESURÉ dans bash : ``f gate.py \\"|| echo REPLI`` passe ``gate.py`` puis un
    guillemet littéral en arguments, et ``||`` reste un opérateur de contrôle —
    ``REPLI`` est bien écrit. Sans espace entre la quote et l'opérateur, avaler
    un caractère de trop couperait le ``||`` en deux et rendrait le repli
    invisible : c'est la borne exacte de la consommation qui est éprouvée ici.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: 'python3 scripts/quality/no_stub_gate.py \\\"|| true'\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_refuse_un_repli_apres_une_chaine_simple_terminee_par_un_antislash(
    tmp_path: Path,
) -> None:
    """Prouve la règle du shell : entre quotes SIMPLES, l'antislash n'échappe rien.

    MESURÉ à l'interpréteur : ``printf '%s' '\\"'`` écrit deux octets, ``5c 22``.
    L'antislash y est un caractère ordinaire, si bien que la quote qui suit
    ferme réellement la chaîne — traiter l'échappement partout ferait disparaître
    le repli qui suit.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: \"gate.py 'motif\\\\' || true\"\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" in _codes(_scanner(repo))


def test_accepte_un_repli_cite_dans_une_chaine_double_a_quote_echappee(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : entre guillemets DOUBLES, ``\\"`` ne ferme pas la chaîne.

    Le repli reste alors littéral, donc jamais exécuté : le signaler serait un
    faux positif sur une commande qui ne force aucun succès.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: 'gate.py --motif \"a\\\" || true\" --strict'\n",
    )

    assert "REQUIRED_JOB_FORCED_SUCCESS" not in _codes(_scanner(repo))


def test_refuse_un_test_dont_le_seul_oracle_est_dans_une_fonction_imbriquee(
    tmp_path: Path,
) -> None:
    """Prouve qu'une portée jamais appelée ne fournit aucun oracle au test.

    MESURÉ avant correction : la recherche parcourait tout l'arbre, si bien que
    l'``assert`` d'une fonction interne JAMAIS APPELÉE comptait comme oracle du
    test qui l'entoure. Le test ne vérifie pourtant rien à l'exécution.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "def test_calcul() -> None:\n"
        "    def oracle() -> None:\n"
        "        assert False\n\n"
        "    return\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


def test_refuse_un_test_dont_le_seul_oracle_est_dans_une_classe_imbriquee(
    tmp_path: Path,
) -> None:
    """Prouve que la classe interne ouvre une portée propre, comme la fonction interne."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "def test_calcul() -> None:\n"
        "    class Sonde:\n"
        "        def verifier(self) -> None:\n"
        "            assert False\n\n"
        "    return\n",
    )

    assert "TEST_WITHOUT_ORACLE" in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "corps",
    (
        "    for valeur in [1]:\n        assert valeur\n",
        "    if calculer():\n        assert calculer()\n",
        "    with ouvrir() as flux:\n        assert flux\n",
        "    try:\n        assert calculer()\n    except ValueError:\n        raise\n",
        "    while calculer():\n        assert calculer()\n",
        "    match calculer():\n        case 1:\n            assert calculer()\n",
    ),
    ids=("boucle", "condition", "contexte", "essai", "tant-que", "filtrage"),
)
def test_accepte_un_oracle_ecrit_dans_un_bloc_du_corps_du_test(
    tmp_path: Path, corps: str
) -> None:
    """Prouve la garde INVERSE : un bloc n'ouvre AUCUNE portée, son oracle compte.

    Boucle, condition, gestionnaire de contexte, essai et filtrage appartiennent
    au corps du test et s'exécutent avec lui. Les écarter avec les portées
    imbriquées ferait un faux positif sur la forme d'oracle la plus courante.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/test_service.py", "def test_calcul() -> None:\n" + corps)

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


def test_accepte_un_oracle_raises_ecrit_dans_une_boucle_du_corps_du_test(
    tmp_path: Path,
) -> None:
    """Prouve que l'oracle ``pytest.raises`` imbriqué dans un bloc compte lui aussi."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_service.py",
        "import pytest\n\n\n"
        "def test_calcul() -> None:\n"
        "    for cas in [1, 2]:\n"
        "        with pytest.raises(ValueError):\n"
        "            calculer(cas)\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


@pytest.mark.parametrize("valeur", ("'0x1'", '"0o7"', "'0b1'"))
def test_refuse_continue_on_error_ecrit_dans_une_base_non_decimale(
    tmp_path: Path, valeur: str
) -> None:
    """Prouve qu'une base non décimale ne désarme plus la règle.

    MESURÉ avant correction : ``'0x1'`` et ``'0o7'`` étaient acceptés quand
    ``'2'`` était refusé — la lecture DÉCIMALE échouait sur ces orthographes et
    retombait silencieusement sur « faux ».
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/continue.yml",
        "jobs:\n"
        "  gates:\n"
        f"    continue-on-error: {valeur}\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


@pytest.mark.parametrize("valeur", ("'0x0'", "'oui'", "'.nan'", "'enabled'", "'  '"))
def test_refuse_continue_on_error_dont_la_faussete_nest_pas_ecrite(
    tmp_path: Path, valeur: str
) -> None:
    """Prouve la règle INVERSÉE : une chaîne non vide tolère, sauf orthographe fausse.

    GitHub Actions convertit toute chaîne NON VIDE en vrai. Énumérer les
    orthographes vraies ne converge pas — ``'0x1'`` puis ``'0x0'`` puis
    ``'enabled'`` échapperaient tour à tour. La classe se ferme en exigeant
    l'inverse : la fausseté doit être ÉCRITE pour que la tolérance soit acceptée.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/continue.yml",
        "jobs:\n"
        "  gates:\n"
        f"    continue-on-error: {valeur}\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "valeur", ("'false'", "'no'", "'off'", "'n'", "'0'", '"0.0"', "''", "'-0'")
)
def test_accepte_continue_on_error_dont_lorthographe_est_explicitement_fausse(
    tmp_path: Path, valeur: str
) -> None:
    """Prouve la garde INVERSE : les acquis de fausseté restent acceptés.

    Ces orthographes disent l'intention contraire à la tolérance ; les refuser
    signalerait comme un contournement le seul moyen d'écrire explicitement
    qu'aucune erreur n'est tolérée.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/continue.yml",
        "jobs:\n"
        "  gates:\n"
        f"    continue-on-error: {valeur}\n"
        "    runs-on: ubuntu-latest\n",
    )

    assert "REQUIRED_JOB_SOFT_FAILURE" not in _codes(_scanner(repo))


def test_refuse_une_absence_levee_sous_un_alias_importe_dans_la_fonction(
    tmp_path: Path,
) -> None:
    """Prouve qu'un import ÉCRIT DANS la fonction lie l'absence aussi réellement qu'au module.

    L'import local n'était jamais collecté : la collecte s'arrêtait aux corps de
    fonctions, si bien que le même alias refusé au niveau module passait dès
    qu'il était écrit une ligne plus bas.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/livraison.py",
        "def livrer() -> None:\n"
        "    from builtins import NotImplementedError as NI\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "    raise NI\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_une_absence_qualifiee_par_un_builtins_importe_dans_la_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que la forme QUALIFIÉE suit la même portée que la forme nue."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/qualifie.py",
        "def livrer() -> None:\n"
        "    import builtins as b\n\n"
        "    raise b.NotImplementedError\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_refuse_une_absence_levee_sous_un_alias_affecte_dans_la_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que l'alias construit par AFFECTATION vaut dans la portée où il est écrit.

    Le même alias affecté au niveau module était déjà refusé : borner la preuve
    au module laissait la version locale, strictement équivalente à l'exécution,
    échapper à la règle.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/affecte.py",
        "def livrer() -> None:\n"
        "    E = NotImplementedError\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "    raise E\n",
    )

    assert "NOT_IMPLEMENTED_STUB" in _codes(_scanner(repo))


def test_accepte_le_nom_dabsence_dans_une_fonction_qui_ne_limporte_pas(
    tmp_path: Path,
) -> None:
    """Prouve le faux positif SYMÉTRIQUE : un alias local ne déborde pas de sa portée.

    ``NI`` désigne l'absence dans ``fabriquer`` et un paramètre quelconque dans
    ``livrer`` : les rendre visibles partout ferait signaler du code qui ne lève
    aucune absence d'implémentation.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/portee.py",
        "def fabriquer() -> object:\n"
        "    from builtins import NotImplementedError as NI\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "    return NI\n\n\n"
        "def livrer(NI: type) -> None:\n"
        "    raise NI\n",
    )

    assert "NOT_IMPLEMENTED_STUB" not in _codes(_scanner(repo))


def test_refuse_un_saut_appele_sous_un_module_pytest_importe_dans_le_test(
    tmp_path: Path,
) -> None:
    """Prouve qu'un module de saut importé DANS le test désarme la suite comme au module."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/test_saut.py",
        "def test_calcul() -> None:\n"
        "    import pytest as pt\n\n"
        "    pt.skip('desarme')\n"
        "    assert 1 == 1\n",
    )

    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_saut_appele_sous_un_nom_importe_dans_le_test(
    tmp_path: Path,
) -> None:
    """Prouve que le nom NU importé dans la fonction saute exactement comme au module."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/test_saut_nu.py",
        "def test_calcul() -> None:\n"
        "    from pytest import skip as sauter\n\n"
        "    sauter('desarme')\n"
        "    assert 1 == 1\n",
    )

    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_saut_unittest_appele_sous_un_module_importe_dans_la_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que l'origine unittest est établie dans la portée locale, comme pytest."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/test_saut_unittest.py",
        "def test_calcul() -> None:\n"
        "    import unittest as ut\n\n"
        "    ut.skip('desarme')\n"
        "    assert 1 == 1\n",
    )

    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_un_decorateur_de_saut_sous_un_module_importe_dans_la_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que la MARQUE, et pas seulement l'appel, est lue dans la portée locale."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/test_marque.py",
        "def fabriquer() -> object:\n"
        "    import pytest as pt\n\n"
        "    @pt.mark.skip\n"
        "    def test_interne() -> None:\n"
        "        assert 1 == 1\n\n"
        "    return test_interne\n",
    )

    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_accepte_un_homonyme_de_saut_dans_une_fonction_qui_nimporte_pas_pytest(
    tmp_path: Path,
) -> None:
    """Prouve le faux positif SYMÉTRIQUE des sauts : l'alias local reste dans sa portée.

    ``pt`` désigne pytest dans ``prepare`` et un paramètre quelconque dans le
    test : sans la limite de portée, tout objet nommé ``pt`` deviendrait un
    sauteur de test.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/test_homonyme.py",
        "def prepare() -> None:\n"
        "    import pytest as pt\n\n"
        "    pt.fixture()\n\n\n"
        "def test_calcul(pt: object) -> None:\n"
        "    pt.skip('rien')\n"
        "    assert 1 == 1\n",
    )

    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


def test_accepte_un_protocol_importe_dans_la_fonction_pour_une_classe_locale(
    tmp_path: Path,
) -> None:
    """Prouve la contrepartie EXEMPTANTE : l'import local prouve l'origine dans sa portée.

    La classe est déclarée DANS la fonction qui importe le protocole : elle
    hérite du véritable ``typing.Protocol``, et signaler son ellipse serait un
    faux positif sur une interface réelle.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/protocole_local.py",
        "def fabriquer() -> type:\n"
        "    from typing import Protocol\n\n"
        "    class Depot(Protocol):\n"
        "        def lire(self) -> str:\n"
        "            ...\n\n"
        "    return Depot\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_accepte_abstractmethod_importe_dans_la_fonction_pour_une_classe_locale(
    tmp_path: Path,
) -> None:
    """Prouve que le décorateur abstrait importé localement exempte dans sa portée."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/abstrait_local.py",
        "def fabriquer() -> type:\n"
        "    from abc import abstractmethod\n\n"
        "    class Depot:\n"
        "        @abstractmethod\n"
        "        def lire(self) -> str:\n"
        "            ...\n\n"
        "    return Depot\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


def test_accepte_un_oracle_pytest_importe_dans_la_fonction_de_test(
    tmp_path: Path,
) -> None:
    """Prouve que l'oracle importé DANS le test compte comme oracle.

    Sans cette lecture, le gate signalait comme dépourvu d'oracle un test qui
    vérifie réellement une levée.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/test_oracle_local.py",
        "def test_conversion() -> None:\n"
        "    from pytest import raises\n\n"
        "    with raises(ValueError):\n"
        "        int('x')\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


@pytest.mark.parametrize("valeur", ("''", "'   '", '"\\t"'))
def test_refuse_un_job_requis_dont_la_seule_etape_porte_un_run_vide(
    tmp_path: Path, valeur: str
) -> None:
    """Prouve qu'une commande vide ou blanche n'exécute rien, la CLÉ ne suffisant pas.

    ``run: ''`` satisfaisait l'exigence d'étape effective : la présence de la clé
    était lue sans jamais regarder sa valeur, si bien qu'un job requis pouvait
    rapporter vert sans lancer la moindre commande.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/vide.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - run: {valeur}\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_refuse_un_job_requis_dont_la_seule_etape_porte_un_uses_vide(
    tmp_path: Path,
) -> None:
    """Prouve que le critère de valeur s'applique aussi à uses, pas au seul run."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/uses-vide.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: '  '\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


@pytest.mark.parametrize("valeur", ("42", "null", "[]"))
def test_refuse_un_job_requis_dont_la_seule_etape_porte_un_run_non_chaine(
    tmp_path: Path, valeur: str
) -> None:
    """Prouve le choix FAIL-CLOSED sur une valeur non-chaîne, qu'aucune règle ne lit.

    L'analyse des commandes ignore déjà tout ``run`` non-chaîne : le compter
    comme étape effective laisserait un job requis satisfaire l'exigence avec
    une valeur qu'aucun contrôle du gate ne sait lire.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/non-chaine.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - run: {valeur}\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_accepte_un_job_requis_dont_la_seule_etape_porte_une_commande_reelle(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : une commande réelle reste une étape effective."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        ".github/workflows/reelle.yml",
        "jobs:\n"
        "  gates:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python3 -m pytest -q\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" not in _codes(_scanner(repo))


def test_refuse_une_action_composite_locale_dont_la_seule_etape_porte_un_run_vide(
    tmp_path: Path,
) -> None:
    """Prouve que l'action composite est jugée sur le MÊME critère que le job requis."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _job_requis_delegue(repo)
    _ecrire(
        repo,
        ".github/actions/controle/action.yml",
        "runs:\n  using: composite\n  steps:\n    - run: ''\n",
    )

    assert "REQUIRED_JOB_SANS_ETAPE" in _codes(_scanner(repo))


def test_refuse_un_saut_appele_dans_une_fonction_imbriquee_sous_lalias_englobant(
    tmp_path: Path,
) -> None:
    """Prouve que la chaîne ENTIÈRE des portées est lue, pas seulement la plus proche.

    L'alias est importé dans la fonction englobante et utilisé dans la fonction
    imbriquée : à l'exécution, la fermeture le rend visible. Ne consulter que la
    portée immédiate laisserait ce saut passer.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/test_imbrique.py",
        "def fabriquer() -> object:\n"
        "    import pytest as pt\n\n"
        "    def test_interne() -> None:\n"
        "        pt.skip('desarme')\n"
        "        assert 1 == 1\n\n"
        "    return test_interne\n",
    )

    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


def test_refuse_une_classe_locale_heritant_dune_exception_detournee_par_le_module(
    tmp_path: Path,
) -> None:
    """Prouve qu'une portée locale ne RESTAURE jamais un nom d'exception révoqué.

    Le module détourne le nom vers un autre module : l'exemption des types
    d'exception tombe. Une portée locale n'apporte que ce que ses imports
    prouvent — repartir de la graine complète des noms de l'interpréteur
    rendrait à la classe locale une exemption que le module vient de retirer.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/detourne.py",
        "from transport import ValueError\n\n\n"
        "def fabriquer() -> type:\n"
        "    class Panne(ValueError):\n"
        "        pass\n\n"
        "    return Panne\n",
    )

    assert "EXECUTABLE_PASS" in _codes(_scanner(repo))


def test_accepte_une_classe_locale_heritant_dune_exception_de_linterpreteur(
    tmp_path: Path,
) -> None:
    """Prouve la garde INVERSE : le type d'exception local non détourné reste exempté."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/legitime.py",
        "def fabriquer() -> type:\n"
        "    class Panne(ValueError):\n"
        "        pass\n\n"
        "    return Panne\n",
    )

    assert "EXECUTABLE_PASS" not in _codes(_scanner(repo))


def test_accepte_un_cas_de_test_unittest_importe_dans_la_fonction(
    tmp_path: Path,
) -> None:
    """Prouve que l'héritage du cas de test est prouvé dans la portée de la CLASSE.

    ``TestCase`` importé dans la fonction qui déclare la classe prouve l'origine
    des oracles hérités : sans cette lecture, une méthode qui vérifie réellement
    quelque chose était signalée dépourvue d'oracle.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "src/test_cas.py",
        "def fabriquer() -> type:\n"
        "    from unittest import TestCase\n\n"
        "    class Cas(TestCase):\n"
        "        def test_x(self) -> None:\n"
        "            self.assertTrue(bool(1))\n\n"
        "    return Cas\n",
    )

    assert "TEST_WITHOUT_ORACLE" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "source",
    (
        "from typing import Protocol\nfrom module_tiers import Protocol\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> None: ...\n",
        "import typing as t\nimport module_tiers as t\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> None: ...\n",
        "from abc import abstractmethod\nfrom module_tiers import abstractmethod\n\n\n"
        "class Service:\n    @abstractmethod\n    def calculer(self) -> None: ...\n",
    ),
)
def test_refuse_une_ellipse_dont_la_preuve_est_rebindee_par_un_import_tiers(
    tmp_path: Path,
    source: str,
) -> None:
    """Prouve qu'un import qui REBINDE un nom retire la preuve établie par le précédent.

    MESURÉ avant correction : les trois écritures passaient sans aucune
    violation. Un import ne comptait pas comme une réaffectation, si bien que le
    second import laissait intacte la preuve du premier — ``Protocol`` continuait
    de désigner ``typing`` alors qu'il désignait le module tiers, et l'ellipse
    était exemptée sur la foi d'une origine périmée.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", source)

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_une_absence_dont_le_module_builtins_est_rebinde_par_un_import_tiers(
    tmp_path: Path,
) -> None:
    """Prouve l'effet INVERSE de la même cause : un porteur rebindé ne prouve plus rien.

    MESURÉ avant correction : ``NOT_IMPLEMENTED_STUB``. Le nom ``b`` désigne le
    module tiers, dont l'attribut homonyme est un type d'erreur métier — la
    règle qualifiée exige justement un PORTEUR prouvé, et ce porteur ne l'est
    plus dès qu'un import postérieur le relie ailleurs.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "import builtins as b\nimport module_tiers as b\n\n\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "def calculer() -> None:\n    raise b.NotImplementedError\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "NOT_IMPLEMENTED_STUB" not in _codes(_scanner(repo))


def test_accepte_un_saut_dont_le_module_pytest_est_rebinde_par_un_import_tiers(
    tmp_path: Path,
) -> None:
    """Prouve la TROISIÈME manifestation de la même cause, sur les marques de saut.

    MESURÉ avant correction : ``NEW_SKIP_OR_XFAIL``, alors que ``pt`` désigne le
    module tiers et que ``pt.skip`` y est une fonction métier. Le témoin inverse
    — ``import module_tiers as pt`` SEUL — n'était déjà pas signalé : les deux
    écritures désignent pourtant le même objet, et cette incohérence est
    exactement le défaut fermé ici.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_calcul.py",
        "import pytest as pt\nimport module_tiers as pt\n\n\n"
        "def test_calcul() -> None:\n    pt.skip('indisponible')\n    assert bool(1)\n",
    )

    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "source",
    (
        "import pytest as pt\n\n\n"
        "def test_calcul() -> None:\n    pt.skip('indisponible')\n    assert bool(1)\n",
        "import pytest as pt\nimport module_tiers as autre\n\n\n"
        "def test_calcul() -> None:\n    pt.skip('indisponible')\n    assert bool(1)\n",
    ),
)
def test_refuse_un_saut_dont_le_module_pytest_reste_lie(
    tmp_path: Path,
    source: str,
) -> None:
    """Garde INVERSE : révoquer sur rebind ne doit pas rendre la détection muette.

    Seul le nom effectivement REBINDÉ perd sa preuve ; un import voisin portant
    un autre nom ne retire rien, sans quoi le correctif ouvrirait un
    contournement d'un import quelconque.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/test_calcul.py", source)

    assert "NEW_SKIP_OR_XFAIL" in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "source",
    (
        "from module_tiers import Protocol\nfrom typing import Protocol\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> None: ...\n",
        "import module_tiers as t\nimport typing as t\n\n\n"
        "class Service(t.Protocol):\n    def calculer(self) -> None: ...\n",
        "from typing import Protocol\nfrom typing_extensions import Protocol\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> None: ...\n",
        "from typing_extensions import Protocol\nfrom typing import Protocol\n\n\n"
        "class Service(Protocol):\n    def calculer(self) -> None: ...\n",
    ),
)
def test_accepte_un_protocole_dont_le_dernier_import_prouve_encore_l_origine(
    tmp_path: Path,
    source: str,
) -> None:
    """Prouve que la LIAISON LA PLUS PROCHE décide, jamais le simple fait d'un rebind.

    Deux distinctions sont verrouillées ici. L'ORDRE : le dernier import lie le
    nom, si bien qu'un retour vers ``typing`` rétablit la preuve qu'un import
    tiers antérieur avait retirée. L'ORIGINE : ``typing`` et
    ``typing_extensions`` prouvent à égalité, si bien que rebinder de l'un vers
    l'autre — l'idiome de rétroportage — ne retire rien, dans les deux sens.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(repo, "src/service.py", source)

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))


@pytest.mark.parametrize(
    "declaration",
    (
        '    racines = contrat.get("python_roots")[:1]\n',
        '    racines = contrat["python_roots"][:1]\n',
        '    racines = contrat.get("python_roots", [])[:1]\n',
        '    racines = [*contrat.get("python_roots")][:1]\n',
    ),
)
def test_refuse_une_troncature_des_racines_lues_dans_le_contrat(
    tmp_path: Path,
    declaration: str,
) -> None:
    """Prouve que la CLÉ contractuelle demandée prouve la source, pas le nom de l'appelé.

    MESURÉ avant correction : la troncature n'était pas signalée, alors que le
    témoin ``charger_racines_qualite()[:1]`` l'était. La reconnaissance
    s'appuyait sur le nom de l'appelé — ``get`` pour un accès au contrat, qui ne
    contient ni « racine » ni « root » — au lieu du champ effectivement lu dans
    ``core/quality-scopes.toml``.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        "def principal(contrat: dict[str, object]) -> int:\n"
        + declaration
        + "    return len(racines)\n",
    )

    assert "SCOPE_FILTRE_INDECIDABLE" in _codes(_scanner(repo, ("core/scripts",)))


@pytest.mark.parametrize(
    "declaration",
    (
        '    racines = contrat["python_roots"]\n',
        '    racines = contrat.get("python_roots", [])\n',
        '    racines = [chemin for chemin in contrat.get("python_roots") if chemin.exists()]\n',
    ),
)
def test_accepte_une_lecture_integrale_de_la_cle_contractuelle(
    tmp_path: Path,
    declaration: str,
) -> None:
    """Garde INVERSE : lire la clé SANS la réduire reste la forme attendue d'un lanceur.

    Les trois lanceurs réels du dépôt lisent le contrat ainsi ; juger la lecture
    elle-même produirait le faux positif qui fait désarmer un gate.
    """
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)
    _ecrire(
        repo,
        "core/scripts/run_security_scan.py",
        "def principal(contrat: dict[str, object]) -> int:\n"
        + declaration
        + "    return len(racines)\n",
    )

    assert "SCOPE_FILTRE_INDECIDABLE" not in _codes(_scanner(repo, ("core/scripts",)))


def test_refuse_une_ellipse_dont_le_protocole_local_est_rebinde(tmp_path: Path) -> None:
    """Prouve que la liaison la plus proche décide AUSSI dans une portée locale.

    La collecte d'une portée énumère ses nœuds à rebours de l'ordre du source :
    la révocation par rebind y était donc appliquée à l'envers, et le premier
    import écrit l'emportait sur le dernier. Les deux imports sont ici LOCAUX,
    si bien qu'aucune preuve du module ne vient masquer le résultat.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/fabrique.py",
        "def fabriquer() -> type:\n"
        "    from typing import Protocol\n"
        "    from module_tiers import Protocol\n\n"
        "    class Depot(Protocol):\n"
        "        def lire(self) -> str: ...\n\n"
        "    return Depot\n",
    )

    assert "EXECUTABLE_ELLIPSIS" in _codes(_scanner(repo))


def test_accepte_un_saut_dont_le_pytest_local_est_rebinde(tmp_path: Path) -> None:
    """Prouve l'effet inverse du même ordre local : la marque de saut n'est plus prouvée."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/test_calcul.py",
        "def test_calcul() -> None:\n"
        "    import pytest as pt\n"
        "    import module_tiers as pt\n"
        "    pt.skip('indisponible')\n"
        "    assert bool(1)\n",
    )

    assert "NEW_SKIP_OR_XFAIL" not in _codes(_scanner(repo))


def test_accepte_une_absence_dont_le_builtins_local_est_rebinde(tmp_path: Path) -> None:
    """Prouve que le porteur rebindé localement ne qualifie plus l'absence de l'interpréteur."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/service.py",
        "def calculer() -> None:\n"
        "    import builtins as b\n"  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
        "    import module_tiers as b\n"
        "    raise b.NotImplementedError\n",  # proof:allow — fixture du gate NO-STUB : ce motif EST le sujet du test
    )

    assert "NOT_IMPLEMENTED_STUB" not in _codes(_scanner(repo))


def test_accepte_un_protocole_local_dont_le_dernier_import_prouve_l_origine(
    tmp_path: Path,
) -> None:
    """Garde d'ORDRE en portée locale : le dernier import écrit rétablit la preuve."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        "src/fabrique.py",
        "def fabriquer() -> type:\n"
        "    from module_tiers import Protocol\n"
        "    from typing import Protocol\n\n"
        "    class Depot(Protocol):\n"
        "        def lire(self) -> str: ...\n\n"
        "    return Depot\n",
    )

    assert "EXECUTABLE_ELLIPSIS" not in _codes(_scanner(repo))
