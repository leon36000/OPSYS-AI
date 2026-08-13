"""Cas RED du gate anti-stub et de protection qualité diff-aware."""

from __future__ import annotations

import subprocess
import tokenize
from pathlib import Path
from typing import Final

import pytest

from scripts.quality.no_stub_gate import Violation, main, scan_repository


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


def test_main_sans_scope_utilise_toutes_les_racines_du_contrat(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prouve que l'absence de --scope sélectionne exactement le périmètre contractuel complet."""
    repo = _depot_git_initialise(tmp_path)
    _contrat(repo)

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


def test_accepte_un_repli_vers_une_commande_prefixee_par_true(tmp_path: Path) -> None:
    """Prouve que le motif de repli borne ses mots : ``true_story`` est un exécutable.

    Sans limite de mot, tout programme dont le nom commence par ``true`` était lu
    comme la commande shell ``true``, et un job requis parfaitement licite était
    refusé.
    """
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || true_story",)),
    )
    assert _codes(_scanner(repo)) == set()


def test_accepte_un_repli_vers_une_commande_prefixee_par_deux_points(
    tmp_path: Path,
) -> None:
    """Prouve que ``:mon_label`` est un nom de commande, non la commande vide ``:``."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || :mon_label",)),
    )
    assert _codes(_scanner(repo)) == set()


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


def test_accepte_un_repli_vers_un_chemin_prefixe_par_true(tmp_path: Path) -> None:
    """Prouve que la borne de nom survit au préfixe de chemin : ``true_story`` reste licite."""
    repo = _depot_git_initialise(tmp_path)
    _ecrire(
        repo,
        ".github/workflows/ci.yml",
        _workflow_run("security", ("python3 gate.py || /usr/bin/true_story",)),
    )
    assert _codes(_scanner(repo)) == set()


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
