"""Contrat CI Core (C02-005) — rendre les checks CI réellement bloquants.

Valide `.github/workflows/core-ci.yml` par LECTURE STATIQUE uniquement (aucun
accès réseau, aucun appel `gh api`) : les tests exécutés en CI restent sur le
disque au moment où le workflow a été écrit, les scopes pytest par module ne
sont jamais combinés (collision de noms mesurée entre `Modules M/*`, cf.
C02-004), et les catégories de gate exigées par la tâche (proof-sealed, types,
tests, security, pack-validation) existent réellement comme jobs nommés — et
échouent explicitement tant qu'aucun mécanisme réel n'est câblé derrière elles
(jamais un pass silencieux : PROOF invariant #4).

Aucune de ces fonctions n'appelle l'API GitHub — la bascule d'un check en
« required » dans branch protection reste une décision humaine séparée,
documentée dans docs/core/CI-REQUIRED-CHECKS.md, hors périmètre de ce module.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "core-ci.yml"

# Chemins de test référencés en clair dans le texte du workflow (step `run:` ou
# commentaire) — volontairement large (englobe core/ ET Modules M/<module>/) car
# le cas RED #1 porte sur N'IMPORTE QUELLE mention, y compris en commentaire.
_TEST_PATH_RE = re.compile(r"(?:core/tests|Modules M/[^/\s\"']+/tests)[\w\-./]*")

_CATEGORIES_EXIGEES = {"proof-sealed", "types", "tests", "security", "pack-validation"}

# Un `uses:` d'action GitHub épinglé par SHA complet (40 hex) — jamais un tag
# flottant (@v5, @main) : AC explicite « chaque action est épinglée par SHA complet ».
_USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)@([^\s#]+)", re.MULTILINE)
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def parse_required_checks(workflow: Path) -> set[str]:
    """Ensemble des noms de check produits par un workflow GitHub Actions.

    Un check GitHub Actions est nommé d'après `jobs.<id>.name` s'il est défini,
    sinon d'après la clé `<id>` elle-même — cohérent avec le fait mesuré sur le
    workflow existant `.github/workflows/ci.yml` : le job `gates:` (sans `name:`
    de job propre) produit exactement le context required `"gates"` observé en
    branch protection. Le cas d'un job portant un `name:` explicite distinct de
    son id n'a pas été observé directement dans ce dépôt ; la règle appliquée
    ici est la convention GitHub Actions documentée, pas une mesure locale
    supplémentaire — transparence assumée (cf. PROOF invariant #8, CLAIMS
    UNVERIFIED : ne pas relayer une extrapolation comme un fait mesuré).
    """
    data = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    jobs = data.get("jobs") or {}
    return {job.get("name", job_id) for job_id, job in jobs.items()}


def _referenced_test_paths(texte: str) -> set[str]:
    """Tout chemin de test cité dans le texte brut (run: ou commentaire)."""
    return set(_TEST_PATH_RE.findall(texte))


def _missing_referenced_tests(texte: str, repo_root: Path) -> set[str]:
    """Sous-ensemble des chemins cités qui n'existent PAS réellement sur disque.

    Vide == aucun commentaire/step ne cite un test fantôme (cas RED #1).

    Re-revue rétroactive C02-005 (2026-08-11, Kimi-K3, MAJEURE, confirmée
    par reproduction directe — cf. test_detecte_un_fantome_dans_un_dossier_
    parent_qui_existe_reellement) : la version précédente tolérait
    `cible.parent.exists()` en plus de `cible.exists()` — dans CE dépôt,
    `core/tests/bootstrap/` existe TOUJOURS, donc cette tolérance
    désactivait silencieusement la détection pour tout fichier cité sous
    ce dossier, exactement le cas RED que cette fonction doit couvrir.
    Aucune tolérance de parent n'est correcte ici : un chemin cité qui
    n'existe pas EST un test fantôme, que son dossier parent existe ou non."""
    manquants = set()
    for chemin in _referenced_test_paths(texte):
        cible = repo_root / chemin
        if not cible.exists():
            manquants.add(chemin)
    return manquants


def _pytest_run_lines(texte: str) -> list[str]:
    return [ligne for ligne in texte.splitlines() if "pytest" in ligne and (" -m pytest" in ligne or "python -m pytest" in ligne or "pytest " in ligne)]


def _scopes_in_line(ligne: str) -> list[str]:
    return re.findall(r"(?:core/|Modules M/[^/\s\"']+)", ligne)


def _isolation_violations(texte: str) -> list[str]:
    """Toute invocation pytest combinant `core/` et `Modules M/*`, ou combinant
    plusieurs `Modules M/<module>` distincts, dans UNE seule commande — viole le
    mécanisme d'isolation réel de ce dépôt (un step pytest séparé par scope,
    seul rempart mesuré contre la collision de noms de modules entre
    `Modules M/*/docs/bmad/verif_coherence.py`, cf. évidence C02-004).

    Liste vide == isolation respectée (cas RED #2).
    """
    violations = []
    for ligne in _pytest_run_lines(texte):
        scopes = set(_scopes_in_line(ligne))
        if len(scopes) > 1:
            violations.append(ligne.strip())
    return violations


def _unpinned_actions(texte: str) -> list[str]:
    """Toute action `uses:` dont la référence n'est pas un SHA complet (40 hex)."""
    non_epingles = []
    for action, ref in _USES_RE.findall(texte):
        if not _FULL_SHA_RE.match(ref):
            non_epingles.append(f"{action}@{ref}")
    return non_epingles


def _jobs_without_hard_failure(data: dict, noms: set[str]) -> list[str]:
    """Parmi les jobs dont le nom est dans `noms`, ceux qui NE contiennent PAS de
    step à échec dur explicite (exit 1 / exit non nul) ET qui n'ont pas non plus
    de mécanisme réel (aucun `continue-on-error: true` autorisé sur ces jobs — un
    tel réglage transformerait un blocage voulu en un vert silencieux).
    """
    jobs = data.get("jobs") or {}
    en_defaut = []
    for job_id, job in jobs.items():
        nom = job.get("name", job_id)
        if nom not in noms:
            continue
        if job.get("continue-on-error") is True:
            en_defaut.append(nom)
            continue
        steps = job.get("steps") or []
        a_echec_dur = any(
            "exit 1" in (step.get("run") or "")
            for step in steps
            if isinstance(step, dict)
        )
        # Un job "réel" (types/tests) a un mécanisme concret ; on ne l'exige donc
        # PAS pour ceux-là. On ne l'exige que pour les catégories sans interface
        # mesurée à ce stade (voir docstring de test_..._3).
        if nom in {"proof-sealed", "security", "pack-validation"} and not a_echec_dur:
            en_defaut.append(nom)
    return en_defaut


def _tests_job_install_steps(data: dict) -> list[str]:
    """Textes `run:` du job `tests` qui invoquent `pip install`."""
    jobs = data.get("jobs") or {}
    tests_job = jobs.get("tests") or {}
    steps = tests_job.get("steps") or []
    return [
        step.get("run") or ""
        for step in steps
        if isinstance(step, dict) and "pip install" in (step.get("run") or "")
    ]


def _hash_enforcement_violations(data: dict) -> list[str]:
    """Le job `tests` doit installer `core/requirements.lock` avec
    `--require-hashes` (fix C05-001 tour 2, Kimi-K3 ; cf. note RÉSOLU dans
    core/requirements.lock) : sans ce flag, un hash sha256 erroné dans le
    lock reste vérifié seulement STRUCTURELLEMENT par verify_lock(), jamais
    appliqué CRYPTOGRAPHIQUEMENT — mesuré directement (hash PyYAML corrompu
    volontairement : `pip install PyYAML==6.0.1`, la commande CI d'ALORS,
    l'ignore silencieusement car elle ne lit même pas requirements.lock).

    Réciproquement, aucun step qui porte `--require-hashes` ne doit nommer
    en dur un paquet hors lock (ex. `pytest==9.1.1`) dans la MÊME commande
    — pip refuse alors tout le step (« Hashes are required in
    --require-hashes mode... », mesuré directement) car ce paquet n'a pas
    de hash déclaré. Le paquet hors lock doit vivre dans un step CI séparé
    (même principe que mypy, installé séparément dans le job `types`).

    Liste vide == enforcement correct (cas RED)."""
    violations: list[str] = []
    lock_step_vu = False
    for run in _tests_job_install_steps(data):
        reference_le_lock = "requirements.lock" in run
        porte_require_hashes = "--require-hashes" in run
        if reference_le_lock:
            lock_step_vu = True
            if not porte_require_hashes:
                violations.append(
                    f"requirements.lock installé sans --require-hashes: {run.strip()}"
                )
        if porte_require_hashes:
            noms_en_dur = re.findall(r"\b[A-Za-z][\w.\-]*==[\d][\w.]*\b", run)
            if noms_en_dur:
                violations.append(
                    f"paquet(s) hors lock mélangé(s) à --require-hashes {noms_en_dur}: {run.strip()}"
                )
    if not lock_step_vu:
        violations.append("aucun step du job tests n'installe core/requirements.lock")
    return violations


# ---------------------------------------------------------------------------
# Cas RED obligatoires (3, noms minimaux imposés par la tâche)
# ---------------------------------------------------------------------------


def test_rendre_les_checks_ci_r_ellement_bloquants_1():
    """Cas RED #1 — détecter commentaire citant un test inexistant.

    Aucun chemin de test cité (step run: ou commentaire) dans le workflow Core
    réel ne doit pointer vers un fichier absent du disque.
    """
    texte = _WORKFLOW_PATH.read_text(encoding="utf-8")
    manquants = _missing_referenced_tests(texte, _REPO_ROOT)
    assert not manquants, f"Le workflow cite des tests inexistants : {sorted(manquants)}"


def test_rendre_les_checks_ci_r_ellement_bloquants_2():
    """Cas RED #2 — exiger isolation-modules global.

    Aucune invocation pytest du workflow Core réel ne combine `core/` avec
    `Modules M/*`, ni deux `Modules M/<module>` distincts, dans une seule commande.
    """
    texte = _WORKFLOW_PATH.read_text(encoding="utf-8")
    violations = _isolation_violations(texte)
    assert not violations, f"Invocation(s) pytest combinant des scopes isolés : {violations}"


def test_rendre_les_checks_ci_r_ellement_bloquants_3():
    """Cas RED #3 — exiger proof-sealed, types, tests, security et pack validation.

    Les 5 catégories doivent exister comme jobs nommés. Celles sans mécanisme
    réel mesuré à ce jour (proof-sealed, security, pack-validation) doivent
    échouer explicitement (exit non nul, jamais continue-on-error) — jamais un
    pass silencieux tant qu'aucun outil n'est câblé derrière elles.
    """
    noms = parse_required_checks(_WORKFLOW_PATH)
    manquantes = _CATEGORIES_EXIGEES - noms
    assert not manquantes, f"Catégorie(s) de gate absente(s) : {sorted(manquantes)}"

    data = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8")) or {}
    en_defaut = _jobs_without_hard_failure(data, _CATEGORIES_EXIGEES)
    assert not en_defaut, (
        f"Job(s) sans mécanisme réel ET sans échec dur explicite "
        f"(pass silencieux potentiel) : {en_defaut}"
    )


# ---------------------------------------------------------------------------
# Tests complémentaires — mutation-proof des détecteurs eux-mêmes (fixtures
# synthétiques, indépendantes du fichier réel : prouvent que le mécanisme
# détecte VRAIMENT un cas mauvais, pas seulement que le fichier réel est bon).
# ---------------------------------------------------------------------------


def test_parse_required_checks_utilise_name_sinon_id(tmp_path):
    wf = tmp_path / "synthetic.yml"
    wf.write_text(
        "name: synthetic\n"
        "on: [push]\n"
        "jobs:\n"
        "  job_sans_name:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps: []\n"
        "  job_avec_id:\n"
        "    name: Nom Personnalise\n"
        "    runs-on: ubuntu-latest\n"
        "    steps: []\n",
        encoding="utf-8",
    )
    assert parse_required_checks(wf) == {"job_sans_name", "Nom Personnalise"}


def test_detecte_reference_a_un_test_fantome_sur_fixture_synthetique(tmp_path):
    texte = (
        "jobs:\n"
        "  tests:\n"
        "    steps:\n"
        "      # cf. core/tests/bootstrap/test_ne_existe_vraiment_pas.py\n"
        "      - run: python3 -m pytest -q core/tests/bootstrap/\n"
    )
    manquants = _missing_referenced_tests(texte, tmp_path)
    assert "core/tests/bootstrap/test_ne_existe_vraiment_pas.py" in manquants


def test_ne_signale_pas_un_chemin_de_test_qui_existe_reellement(tmp_path):
    (tmp_path / "core" / "tests" / "bootstrap").mkdir(parents=True)
    cible = tmp_path / "core" / "tests" / "bootstrap" / "test_reel.py"
    cible.write_text("def test_x(): assert True\n", encoding="utf-8")
    texte = "# core/tests/bootstrap/test_reel.py\n"
    assert _missing_referenced_tests(texte, tmp_path) == set()


def test_detecte_un_fantome_dans_un_dossier_parent_qui_existe_reellement(tmp_path):
    """Re-revue rétroactive C02-005 (2026-08-11, Kimi-K3, MAJEURE, confirmée
    par reproduction directe) : la fixture ci-dessus utilise un `tmp_path`
    VIDE — le dossier parent (`core/tests/bootstrap/`) n'existe pas non
    plus, cas NON REPRÉSENTATIF de ce dépôt où ce dossier existe TOUJOURS.
    `_missing_referenced_tests` retombe alors sur `cible.parent.exists()`
    (dernier terme du `any(...)`) : si le PARENT existe (cas réel de ce
    dépôt) mais que le FICHIER cité, lui, n'existe pas (renommé/supprimé),
    la fonction ne le signalait PAS — le cas RED #1 réel ne mordait jamais
    en pratique, seulement sur la fixture synthétique non représentative.
    Ce test crée le dossier parent réel SANS créer le fichier cité —
    reproduit le cas RED effectivement pertinent pour ce dépôt."""
    (tmp_path / "core" / "tests" / "bootstrap").mkdir(parents=True)
    texte = "# cf. core/tests/bootstrap/test_renomme_ou_supprime.py\n"
    manquants = _missing_referenced_tests(texte, tmp_path)
    assert "core/tests/bootstrap/test_renomme_ou_supprime.py" in manquants


def test_detecte_combinaison_core_et_modules_m_sur_fixture_synthetique():
    texte = "      - run: python3 -m pytest -q core/tests \"Modules M/M7-marketing/tests\"\n"
    violations = _isolation_violations(texte)
    assert violations, "Une invocation combinant core/ et Modules M/ doit être détectée"


def test_detecte_combinaison_de_deux_modules_m_distincts_sur_fixture_synthetique():
    texte = (
        '      - run: python3 -m pytest -q "Modules M/M1-front-office/tests" '
        '"Modules M/M2-revenue-crm/tests"\n'
    )
    violations = _isolation_violations(texte)
    assert violations, "Une invocation combinant deux scopes Modules M/ distincts doit être détectée"


def test_n_alerte_pas_sur_des_scopes_deja_isoles_par_step():
    texte = (
        '      - run: python3 -m pytest -q "Modules M/M1-front-office/tests"\n'
        '      - run: python3 -m pytest -q "Modules M/M2-revenue-crm/tests"\n'
        "      - run: python3 -m pytest -q core/tests/bootstrap\n"
    )
    assert _isolation_violations(texte) == []


def test_detecte_action_non_epinglee_par_sha_sur_fixture_synthetique():
    texte = "      - uses: actions/setup-python@v5\n"
    non_epingles = _unpinned_actions(texte)
    assert "actions/setup-python@v5" in non_epingles


def test_toutes_les_actions_du_workflow_core_sont_epinglees_par_sha():
    texte = _WORKFLOW_PATH.read_text(encoding="utf-8")
    non_epingles = _unpinned_actions(texte)
    assert not non_epingles, f"Action(s) non épinglée(s) par SHA complet : {non_epingles}"


def test_job_sans_mecanisme_et_sans_echec_dur_est_detecte_sur_fixture_synthetique():
    data = {
        "jobs": {
            "security": {"runs-on": "ubuntu-latest", "steps": [{"run": "echo ok"}]},
        }
    }
    en_defaut = _jobs_without_hard_failure(data, {"security"})
    assert en_defaut == ["security"]


def test_job_avec_continue_on_error_est_toujours_en_defaut_sur_fixture_synthetique():
    data = {
        "jobs": {
            "security": {
                "runs-on": "ubuntu-latest",
                "continue-on-error": True,
                "steps": [{"run": "exit 1"}],
            },
        }
    }
    en_defaut = _jobs_without_hard_failure(data, {"security"})
    assert en_defaut == ["security"], "continue-on-error masque un exit 1 : doit rester en défaut"


# ---------------------------------------------------------------------------
# Enforcement cryptographique des hash de dépendances (fix C05-001 tour 2,
# Kimi-K3) — couvre PyYAML (C02-002) ET psycopg/psycopg-binary (C05-001),
# même mécanisme pour toutes les dépendances verrouillées.
# ---------------------------------------------------------------------------


def test_installation_core_verrouillee_impose_require_hashes():
    """Cas RED — le job `tests` du workflow Core réel doit installer
    core/requirements.lock avec --require-hashes, sans jamais mélanger un
    paquet hors lock (ex. pytest) dans la même commande."""
    data = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8")) or {}
    violations = _hash_enforcement_violations(data)
    assert not violations, f"Enforcement hash rompu : {violations}"


def test_detecte_lock_installe_sans_require_hashes_sur_fixture_synthetique():
    data = {
        "jobs": {
            "tests": {
                "steps": [
                    {"run": "python3 -m pip install --quiet -r core/requirements.lock"},
                ]
            }
        }
    }
    violations = _hash_enforcement_violations(data)
    assert any("sans --require-hashes" in v for v in violations)


def test_detecte_melange_paquet_hors_lock_avec_require_hashes_sur_fixture_synthetique():
    data = {
        "jobs": {
            "tests": {
                "steps": [
                    {
                        "run": (
                            "python3 -m pip install --quiet --require-hashes "
                            "-r core/requirements.lock pytest==9.1.1"
                        )
                    },
                ]
            }
        }
    }
    violations = _hash_enforcement_violations(data)
    assert any("mélangé" in v for v in violations)


def test_n_alerte_pas_quand_lock_et_pytest_sont_dans_des_steps_separes_sur_fixture_synthetique():
    data = {
        "jobs": {
            "tests": {
                "steps": [
                    {"run": "python3 -m pip install --quiet --require-hashes -r core/requirements.lock"},
                    {"run": "python3 -m pip install --quiet pytest==9.1.1"},
                ]
            }
        }
    }
    assert _hash_enforcement_violations(data) == []


def test_detecte_absence_totale_d_installation_du_lock_sur_fixture_synthetique():
    data = {"jobs": {"tests": {"steps": [{"run": "python3 -m pytest -q core/tests"}]}}}
    violations = _hash_enforcement_violations(data)
    assert any("aucun step" in v for v in violations)
