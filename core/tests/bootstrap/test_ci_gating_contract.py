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
tenu ici est plus étroit et plus stable : ces trois scopes doivent tourner,
à CHAQUE occurrence où ils apparaissent dans le workflow, dans un contexte
qui n'est PAS `continue-on-error` — ni le job qui les héberge, ni le step
qui les invoque.

Deux trous d'oracle mesurés en revue (issue #565, PR #567) et corrigés ici :
- TROU A — un `continue-on-error: true` posé sur un STEP (et non sur le
  job) passait inaperçu, car l'ancien détecteur ne lisait que le niveau
  job. Poser ce drapeau sur un step est la façon la plus naturelle de faire
  taire un test qui rougit sans toucher au job — précisément la classe de
  défaut que ce module existe pour interdire. Fermé par
  `test_detecteur_continue_on_error_signale_un_step_factice_dans_job_sain`.
- TROU B — un scope critique invoqué dans un job sain PUIS À NOUVEAU dans
  un job non bloquant listé plus loin dans le YAML : l'ancien détecteur
  (`_job_executant_scope`) rendait `return` dès la première correspondance
  et ne voyait jamais la seconde occurrence, la seule dangereuse. Fermé par
  `test_detecteur_scope_trouve_toutes_les_occurrences_pas_seulement_la_premiere`.

Ce que cet oracle NE mesure délibérément PAS, pour qu'il n'affirme rien
au-delà de ce qu'il vérifie réellement : un job ou un step neutralisé par
une condition `if:` (ex. `if: false`, ou une expression qui évalue à faux
à l'exécution) n'est pas détecté ici — il resterait invisible alors même
qu'il ne bloquerait rien non plus. De même, un `continue-on-error` exprimé
comme une expression GitHub Actions (`${{ ... }}`) plutôt que le littéral
booléen `true` n'est pas reconnu : seule la valeur booléenne stricte est
comparée. Ce sont des trous d'oracle CONNUS et non fermés par ce module,
pas des cas couverts par omission silencieuse.
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
    """Noms de TOUS les jobs portant `continue-on-error: true`, au niveau du
    JOB lui-même OU d'au moins un de ses STEPS, sans exception ni liste
    blanche par nom de job ou de step.

    TROU A (mesuré en revue #565/#567) : la version précédente ne lisait que
    `job.get("continue-on-error")` — un `continue-on-error: true` posé sur
    un step individuel, dans un job par ailleurs sain, n'était jamais vu.
    Voir `test_detecteur_continue_on_error_signale_un_step_factice_dans_job_sain`.

    Liste vide == aucun job ni aucun step de ce workflow, tel que mesuré ici,
    ne peut échouer en silence. Ce que ceci NE couvre PAS : un job/step
    neutralisé par `if:`, ou un `continue-on-error` écrit comme expression
    GitHub Actions plutôt que littéral booléen — cf. en-tête du module.
    """
    jobs = data.get("jobs") or {}
    en_defaut: list[str] = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        nom = _nom_job(job_id, job)
        if job.get("continue-on-error") is True:
            en_defaut.append(nom)
            continue
        steps = job.get("steps") or []
        if any(
            isinstance(step, dict) and step.get("continue-on-error") is True
            for step in steps
        ):
            en_defaut.append(nom)
    return en_defaut


def _occurrences_de_scope(data: dict, scope: str) -> list[tuple[str, dict, dict]]:
    """TOUTES les occurrences `(nom_job, job, step)` où un step `run:` invoque
    `scope`, dans TOUS les jobs du workflow — jamais seulement la première
    rencontrée à l'itération des jobs.

    TROU B (mesuré en revue #565/#567) : la version précédente de cette
    fonction (`_job_executant_scope`) rendait `return` dès la première
    correspondance. Un scope présent dans un job sain PUIS À NOUVEAU dans un
    job non bloquant listé plus loin dans le YAML voyait sa seconde
    occurrence — la seule dangereuse — jamais examinée. Voir
    `test_detecteur_scope_trouve_toutes_les_occurrences_pas_seulement_la_premiere`.

    Liste vide == `scope` n'est invoqué par aucun step `run:` de ce workflow
    — distinct du cas « trouvé mais non bloquant », jamais confondu avec lui.
    """
    jobs = data.get("jobs") or {}
    occurrences: list[tuple[str, dict, dict]] = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        nom = _nom_job(job_id, job)
        for step in job.get("steps") or []:
            if isinstance(step, dict) and scope in (step.get("run") or ""):
                occurrences.append((nom, job, step))
    return occurrences


def _occurrence_non_bloquante(job: dict, step: dict) -> bool:
    """Une occurrence est non bloquante si le JOB entier porte
    `continue-on-error: true`, OU si le STEP qui invoque le scope le porte
    lui-même. La seconde voie (TROU A) est celle que l'ancien oracle ne
    voyait pas quand elle s'appliquait à un job par ailleurs sain."""
    return job.get("continue-on-error") is True or step.get("continue-on-error") is True


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
    """RED #2 — dashboard/authz/config-vault doivent tourner dans un contexte
    qui n'est PAS `continue-on-error`, sur TOUTES leurs occurrences dans le
    workflow (pas seulement la première rencontrée, TROU B) et que ce soit
    le job ou le step lui-même qui porte le drapeau (TROU A). Mesuré sur le
    HEAD `31fa5497` : les trois steps (l.64-69) vivent dans le job `e2e`, qui
    porte `continue-on-error: true` (l.51) — leur échec ne bloque donc
    jamais une PR aujourd'hui.
    """
    data = _charger(_WORKFLOW_PATH)
    manquants = []
    non_bloquants = []
    for label, scope in _SCOPES_CRITIQUES.items():
        occurrences = _occurrences_de_scope(data, scope)
        if not occurrences:
            manquants.append(f"{label} ({scope})")
            continue
        for nom, job, step in occurrences:
            if _occurrence_non_bloquante(job, step):
                non_bloquants.append(
                    f"{label} -> job '{nom}' (continue-on-error: true sur le job ou le step)"
                )
    assert not manquants, (
        f"Scope(s) critique(s) plus exécuté(s) du tout dans ci.yml : {manquants}"
    )
    assert not non_bloquants, (
        f"Scope(s) critique(s) exécuté(s) dans un contexte non bloquant : {non_bloquants}"
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
    occurrences = _occurrences_de_scope(data, "core/src/authz/tests")
    assert len(occurrences) == 1
    nom, job, step = occurrences[0]
    assert nom == "e2e"
    assert _occurrence_non_bloquante(job, step) is True


def test_detecteur_scope_critique_absent_est_signale_distinctement():
    """Un scope critique qui ne serait invoqué par AUCUN job doit renvoyer
    une liste vide — jamais confondu avec « trouvé et bloquant »."""
    data = {"jobs": {"gates": {"steps": [{"run": "python3 -m pytest scripts/tests -q"}]}}}
    assert _occurrences_de_scope(data, "core/src/authz/tests") == []


def test_detecteur_scope_critique_bloquant_ne_signale_rien():
    """Un scope critique exécuté dans un job SANS continue-on-error, par un
    step qui n'en porte pas non plus, ne doit déclencher aucun signal —
    nécessaire pour que le cas GREEN existe."""
    data = {
        "jobs": {
            "gates": {
                "steps": [{"run": 'python3 -m pytest "core/src/authz/tests" -q'}],
            }
        }
    }
    occurrences = _occurrences_de_scope(data, "core/src/authz/tests")
    assert len(occurrences) == 1
    nom, job, step = occurrences[0]
    assert _occurrence_non_bloquante(job, step) is False


def test_detecteur_continue_on_error_signale_un_step_factice_dans_job_sain():
    """TROU A fermé — mesuré en revue #565/#567 : trois steps critiques
    portant CHACUN `continue-on-error: true`, dans un job qui n'en porte pas
    au niveau job. Avant correction, `_jobs_avec_continue_on_error` rendait
    `[]` ici et les tests RED de ce module passaient VERT malgré le défaut.
    Poser `continue-on-error: true` sur un step est la façon la plus
    naturelle de faire taire un test qui rougit sans toucher au job."""
    data = {
        "jobs": {
            "gates": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {
                        "name": "Tests dashboard (P0-5a)",
                        "continue-on-error": True,
                        "run": 'python3 -m pytest "surfaces/dashboard/tests" -q',
                    },
                    {
                        "name": "Tests authz (P0-5c)",
                        "continue-on-error": True,
                        "run": 'python3 -m pytest "core/src/authz/tests" -q',
                    },
                    {
                        "name": "Tests config/vault (P0-5d)",
                        "continue-on-error": True,
                        "run": 'python3 -m pytest "core/src/config/tests" -q',
                    },
                ],
            }
        }
    }
    assert data["jobs"]["gates"].get("continue-on-error") is not True, "fixture: job sain"
    assert _jobs_avec_continue_on_error(data) == ["gates"]
    # Le check par occurrence (celui qu'utilise test_ci_yml_tests_critiques_bloquants)
    # doit lui aussi voir les trois steps comme non bloquants malgré un job sain.
    for scope in _SCOPES_CRITIQUES.values():
        occurrences = _occurrences_de_scope(data, scope)
        assert len(occurrences) == 1
        _, job, step = occurrences[0]
        assert _occurrence_non_bloquante(job, step) is True, (
            f"le step de {scope} porte continue-on-error: true et doit être vu"
        )


def test_detecteur_scope_trouve_toutes_les_occurrences_pas_seulement_la_premiere():
    """TROU B fermé — mesuré en revue #565/#567 : un scope invoqué dans un
    job SAIN listé en premier dans le YAML, puis À NOUVEAU dans un job non
    bloquant listé ensuite. Avant correction, `_job_executant_scope`
    rendait `('gates', ...)` et l'occurrence non bloquante dans `e2e`
    n'était jamais examinée."""
    data = {
        "jobs": {
            "gates": {
                "steps": [{"run": 'python3 -m pytest "core/src/authz/tests" -q'}],
            },
            "e2e": {
                "continue-on-error": True,
                "steps": [{"run": 'python3 -m pytest "core/src/authz/tests" -q'}],
            },
        }
    }
    occurrences = _occurrences_de_scope(data, "core/src/authz/tests")
    assert [nom for nom, _job, _step in occurrences] == ["gates", "e2e"]
    non_bloquantes = [
        nom for nom, job, step in occurrences if _occurrence_non_bloquante(job, step)
    ]
    assert non_bloquantes == ["e2e"]


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
