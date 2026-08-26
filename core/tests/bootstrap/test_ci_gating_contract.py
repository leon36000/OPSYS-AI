"""Contrat CI `ci.yml` (AUD-CI-003 + AUD-CI-004, issue #565) — gating bloquant.

Trou d'oracle mesuré : `test_ci_contract.py` porte déjà un détecteur
`continue-on-error` et un détecteur de test fantôme, mais son `_WORKFLOW_PATH`
est figé sur `.github/workflows/core-ci.yml`. `ci.yml` — le workflow dont le
job `gates` est le SEUL contexte `required` mesuré en branch protection
(`gh api repos/leon36000/OPSYS-AI/branches/main/protection` :
`required_status_checks.contexts == ["gates"]`, `enforce_admins: true`,
`required_approving_review_count: 0`) — n'était couvert par AUCUN test avant
ce fichier.

Défaut reproduit sur le HEAD `31fa54976443f7413f705776dbd8a8af1cdfa872` :
- le job `e2e` (l.51) et le job `e2e-load` (l.74) portent tous les deux
  `continue-on-error: true` ;
- trois steps de tests unitaires purs — dashboard (P0-5a, l.64-65), authz
  (P0-5c, l.66-67), config/vault (P0-5d, l.68-69) — vivent À L'INTÉRIEUR du
  job non bloquant `e2e`.

Conséquence mesurable : un échec des critères Core C02-005, C09-007,
C22-002, C22-007, C23-001, C23-005 (harnais e2e, charge k6, autorisation,
coffre) ne fait jamais échouer une PR.

Ce module valide `.github/workflows/ci.yml` par LECTURE STATIQUE uniquement
(aucun accès réseau, aucun `gh`, aucun `gh api`) — même convention que
`test_ci_contract.py`. Bascule d'un contexte en `required` dans branch
protection : décision humaine séparée (AUD-CI-005, hors périmètre). Le fait
mesuré ci-dessus (`gates` seul contexte required) justifie la DESTINATION du
déplacement des trois steps critiques dans le correctif GREEN, mais n'est
délibérément PAS encodé comme oracle ici (aucun test n'exige qu'un job
s'appelle littéralement `gates`) : un oracle statique qui durcirait ce nom
romprait dès que la configuration mutable de branch protection évoluerait —
classe de changement hors du contrôle de ce module. L'oracle réellement
tenu ici est plus étroit et plus stable : ces trois scopes doivent tourner
dans un job qui n'est PAS `continue-on-error`.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Familles de chemins de test réellement citées par ci.yml aujourd'hui
# (scripts/tests, Modules M/<module>/tests, core/src/<module>/tests,
# surfaces/<surface>/tests) — liste FERMÉE de préfixes, jamais un motif
# générique `\S+/tests` qui matcherait aussi un mot "tests" isolé dans une
# phrase de commentaire sans rapport avec un chemin réel.
_TEST_PATH_RE = re.compile(
    r"(?:core/tests"
    r"|core/src/[^/\s\"']+/tests"
    r"|Modules M/[^/\s\"']+/tests"
    r"|surfaces/[^/\s\"']+/tests"
    r"|scripts/tests)[\w\-./]*"
)

# Les trois scopes critiques nommés par l'issue #565 — tests unitaires purs
# (imports vérifiés : stdlib + pytest + PyYAML uniquement, aucune dépendance
# du harnais e2e) déplacés hors du job non bloquant par le correctif GREEN.
_SCOPES_CRITIQUES = {
    "dashboard (P0-5a)": "surfaces/dashboard/tests",
    "authz (P0-5c)": "core/src/authz/tests",
    "config/vault (P0-5d)": "core/src/config/tests",
}


def _charger(workflow: Path) -> dict:
    return yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}


def _nom_job(job_id: str, job: dict) -> str:
    return job.get("name", job_id)


def _jobs_avec_continue_on_error(data: dict) -> list[str]:
    """Noms de TOUS les jobs portant `continue-on-error: true`, sans exception
    ni liste blanche par nom de job.

    Liste vide == aucun job de ce workflow ne peut échouer en silence.
    """
    jobs = data.get("jobs") or {}
    return [
        _nom_job(job_id, job)
        for job_id, job in jobs.items()
        if isinstance(job, dict) and job.get("continue-on-error") is True
    ]


def _job_executant_scope(data: dict, scope: str) -> tuple[str, dict] | None:
    """(nom, job) du premier job dont un step `run:` invoque `scope`.

    None si `scope` n'est invoqué par aucun step `run:` de ce workflow —
    distinct du cas « trouvé mais non bloquant », jamais confondu avec lui.
    """
    jobs = data.get("jobs") or {}
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and scope in (step.get("run") or ""):
                return _nom_job(job_id, job), job
    return None


def _chemins_de_test_cites(texte: str) -> set[str]:
    """Tout chemin de test cité dans le texte brut (step `run:` ou commentaire)."""
    return set(_TEST_PATH_RE.findall(texte))


def _tests_fantomes(texte: str, repo_root: Path) -> set[str]:
    """Sous-ensemble des chemins cités qui n'existent PAS réellement sur disque.

    Vide == aucun step/commentaire de ce workflow ne cite un test fantôme.
    """
    return {
        chemin
        for chemin in _chemins_de_test_cites(texte)
        if not (repo_root / chemin).exists()
    }


# ---------------------------------------------------------------------------
# Cas RED — noms explicites, doivent rougir sur le HEAD live avant correction
# (jamais planter : un `assert` lisible, jamais une exception de parsing).
# ---------------------------------------------------------------------------


def test_ci_yml_aucun_job_ne_porte_continue_on_error():
    """RED #1 — mesuré sur le HEAD `31fa5497` : `e2e` (l.51) et `e2e-load`
    (l.74) portent tous les deux `continue-on-error: true`. Doit rougir avec
    exactement ces deux noms de job avant correction, liste vide après.
    """
    data = _charger(_WORKFLOW_PATH)
    en_defaut = _jobs_avec_continue_on_error(data)
    assert not en_defaut, (
        f"Job(s) de ci.yml avec continue-on-error: true "
        f"(échec Core silencieux possible) : {sorted(en_defaut)}"
    )


def test_ci_yml_tests_critiques_bloquants():
    """RED #2 — dashboard/authz/config-vault doivent tourner dans un job qui
    n'est PAS `continue-on-error`. Mesuré sur le HEAD `31fa5497` : les trois
    steps (l.64-69) vivent dans le job `e2e`, qui porte `continue-on-error:
    true` (l.51) — leur échec ne bloque donc jamais une PR aujourd'hui.
    """
    data = _charger(_WORKFLOW_PATH)
    manquants = []
    non_bloquants = []
    for label, scope in _SCOPES_CRITIQUES.items():
        trouve = _job_executant_scope(data, scope)
        if trouve is None:
            manquants.append(f"{label} ({scope})")
            continue
        nom, job = trouve
        if job.get("continue-on-error") is True:
            non_bloquants.append(f"{label} -> job '{nom}' (continue-on-error: true)")
    assert not manquants, (
        f"Scope(s) critique(s) plus exécuté(s) du tout dans ci.yml : {manquants}"
    )
    assert not non_bloquants, (
        f"Scope(s) critique(s) exécuté(s) dans un job non bloquant : {non_bloquants}"
    )


def test_ci_yml_aucun_chemin_de_test_fantome():
    """RED #3 — tout chemin de test cité (step `run:` ou commentaire) dans
    `ci.yml` doit exister réellement sur disque (même trou de fiabilité que
    C02-005 sur `core-ci.yml`, jamais corrigé sur `ci.yml` faute de
    couverture — cf. en-tête de ce module)."""
    texte = _WORKFLOW_PATH.read_text(encoding="utf-8")
    manquants = _tests_fantomes(texte, _REPO_ROOT)
    assert not manquants, f"ci.yml cite des tests inexistants : {sorted(manquants)}"


# ---------------------------------------------------------------------------
# Fixtures synthétiques — mutation-proof des détecteurs eux-mêmes (prouvent
# que le mécanisme détecte VRAIMENT un cas mauvais, pas seulement que le
# fichier réel est bon aujourd'hui). Indépendantes de ci.yml.
# ---------------------------------------------------------------------------


def test_detecteur_continue_on_error_signale_un_job_factice(tmp_path):
    """Preuve que le détecteur n'est pas vide : un `continue-on-error: true`
    injecté dans un workflow synthétique DOIT être signalé."""
    wf = tmp_path / "synthetic.yml"
    wf.write_text(
        "name: synthetic\n"
        "on: [push]\n"
        "jobs:\n"
        "  suspect:\n"
        "    runs-on: ubuntu-latest\n"
        "    continue-on-error: true\n"
        "    steps:\n"
        "      - run: exit 1\n"
        "  sain:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: exit 0\n",
        encoding="utf-8",
    )
    assert _jobs_avec_continue_on_error(_charger(wf)) == ["suspect"]


def test_detecteur_continue_on_error_ne_signale_rien_sur_workflow_sain(tmp_path):
    wf = tmp_path / "synthetic_sain.yml"
    wf.write_text(
        "name: synthetic\n"
        "jobs:\n"
        "  sain:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: exit 0\n",
        encoding="utf-8",
    )
    assert _jobs_avec_continue_on_error(_charger(wf)) == []


def test_detecteur_scope_critique_signale_job_non_bloquant_sur_fixture_synthetique():
    """Preuve indépendante du fichier réel : un scope critique invoqué dans
    un job `continue-on-error: true` DOIT être retrouvé, avec son statut
    non bloquant visible sur le job renvoyé."""
    data = {
        "jobs": {
            "e2e": {
                "continue-on-error": True,
                "steps": [{"run": 'python3 -m pytest "core/src/authz/tests" -q'}],
            }
        }
    }
    trouve = _job_executant_scope(data, "core/src/authz/tests")
    assert trouve is not None
    nom, job = trouve
    assert nom == "e2e"
    assert job.get("continue-on-error") is True


def test_detecteur_scope_critique_absent_est_signale_distinctement():
    """Un scope critique qui ne serait invoqué par AUCUN job doit renvoyer
    None — jamais confondu avec « trouvé et bloquant »."""
    data = {"jobs": {"gates": {"steps": [{"run": "python3 -m pytest scripts/tests -q"}]}}}
    assert _job_executant_scope(data, "core/src/authz/tests") is None


def test_detecteur_scope_critique_bloquant_ne_signale_rien():
    """Un scope critique exécuté dans un job SANS continue-on-error ne doit
    déclencher aucun signal — nécessaire pour que le cas GREEN existe."""
    data = {
        "jobs": {
            "gates": {
                "steps": [{"run": 'python3 -m pytest "core/src/authz/tests" -q'}],
            }
        }
    }
    trouve = _job_executant_scope(data, "core/src/authz/tests")
    assert trouve is not None
    nom, job = trouve
    assert job.get("continue-on-error") is not True


def test_detecte_reference_a_un_test_fantome_sur_fixture_synthetique(tmp_path):
    texte = (
        "jobs:\n"
        "  gates:\n"
        "    steps:\n"
        "      # cf. core/src/authz/tests/test_ne_existe_vraiment_pas.py\n"
        "      - run: python3 -m pytest -q core/src/authz/tests\n"
    )
    manquants = _tests_fantomes(texte, tmp_path)
    assert "core/src/authz/tests/test_ne_existe_vraiment_pas.py" in manquants


def test_ne_signale_pas_un_chemin_de_test_qui_existe_reellement(tmp_path):
    (tmp_path / "surfaces" / "dashboard" / "tests").mkdir(parents=True)
    cible = tmp_path / "surfaces" / "dashboard" / "tests" / "test_reel.py"
    cible.write_text("def test_x(): assert True\n", encoding="utf-8")
    texte = '      - run: python3 -m pytest "surfaces/dashboard/tests" -q\n'
    assert _tests_fantomes(texte, tmp_path) == set()


def test_regex_chemin_de_test_ne_capture_pas_un_faux_positif_dans_un_nom_de_module():
    """Défense mesurée : `Modules M/M5-financecore/tests` contient la
    sous-chaîne littérale `core/tests` (…financeCORE/TESTS). Le motif ne
    doit produire QU'UNE seule citation pour cette ligne — le chemin complet
    du module, jamais un fragment `core/tests` orphelin en plus."""
    texte = '      - run: python3 -m pytest "Modules M/M5-financecore/tests" -q\n'
    assert _chemins_de_test_cites(texte) == {"Modules M/M5-financecore/tests"}
