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
comparée. Troisième trou, du même registre que celui que ce module vient
de fermer : un step dont le `run:` avale son propre code de retour au
niveau shell (`... || true`, `set +e`, `; exit 0`) est classé bloquant,
alors qu'il ne bloque rien. Mesuré sur fixture : un step
`pytest "core/src/authz/tests" -q || true` dans un job sain rend une liste
vide. Aucune occurrence de cette forme n'existe aujourd'hui dans `ci.yml`
(recherche des trois formes dans le fichier : zéro), l'exposition est donc
nulle — mais le trou est réel et nommé plutôt que tu.

Cause racine commune, nommée plutôt qu'énumérée par symptômes :
`_occurrences_de_scope` fait une correspondance de SOUS-CHAÎNE sur le texte brut
du `run:`. Toute forme où le chemin apparaît sans être réellement exécuté et gardé
est donc classée bloquante — invocation commentée dans un bloc `run: |`,
`--ignore=<scope>`, `--collect-only`, autant que les formes d'avalement du code de
retour citées plus haut. Trois de ces variantes ont été mesurées vertes en revue.

Ce sont des trous d'oracle CONNUS et non fermés par ce module. La liste des
symptômes ci-dessus n'est pas exhaustive — c'est la cause racine qui l'est.

---------------------------------------------------------------------------
AUD-CI-002 (issue #576) — épinglage des actions par SHA complet
---------------------------------------------------------------------------

Second sujet couvert par ce module. Il porte sur le MÊME fichier et reste
donc dans le contrat déclaré plus haut (`.github/workflows/ci.yml`, LECTURE
STATIQUE seule) : le périmètre de fichier du module est inchangé, seul son
objet s'élargit du gating vers la chaîne d'approvisionnement.

Défaut : une action référencée par un tag (`@v5`, `@main`) peut être
redirigée en amont vers un autre commit sans aucun commit ici. Le code
exécuté par la CI change alors sans trace dans ce dépôt. C'est la raison
d'être de D-035, appliquée aux `actions/checkout` de ce fichier.

Trou d'oracle qui justifie ce détecteur ICI : le dépôt possédait déjà le bon
contrôle — `test_ci_contract._unpinned_actions` — mais braqué sur
`.github/workflows/core-ci.yml`, conformément au contrat déclaré de CE
module-là (sa docstring l.3). `ci.yml`, qui porte le job `gates`, n'avait
aucun oracle de pin. Même classe de défaut qu'AUD-CI-003/004 : un contrôle
réel dont la PORTÉE rate la cible.

DUPLICATION DÉCLARÉE, pas laissée à découvrir
  `_actions_non_epinglees` ci-dessous duplique `test_ci_contract._unpinned_actions`.

  Ce qui est dupliqué : la RÈGLE MÉTIER (« un `uses:` doit porter un SHA
  complet »), pas le code. La version d'ici parcourt l'arbre YAML analysé ;
  celle de `test_ci_contract.py` applique un motif au TEXTE BRUT. Les deux
  ne classent déjà pas identiquement plusieurs formes mesurées ci-dessous
  (bloc `run: |` contenant la sous-chaîne `uses:`, scalaire replié `uses: >`,
  scalaire entre guillemets, style flow `- {uses: …}`).

  Pourquoi ne pas factoriser maintenant : les deux modules ont des
  périmètres de workflow DISJOINTS ET DÉCLARÉS (`core-ci.yml` là-bas,
  `ci.yml` ici) ; chacun doit pouvoir rougir seul et se lire seul. Un
  facteur circonstanciel a pesé au moment de la rédaction —
  `test_ci_contract.py` faisait alors l'objet d'une modification concurrente
  (PR #515) — mais ce facteur est par nature périmable et n'est PAS la
  raison de fond.

  Risque assumé : DÉRIVE. Si les deux implémentations divergent sur ce
  qu'elles acceptent, le remède n'est pas d'aligner l'une sur l'autre en
  silence : il faut extraire la règle dans un module partagé importé des
  deux côtés, et ne laisser de chaque côté que le choix du fichier de
  workflow. Ce déplacement touche `test_ci_contract.py` et sortait du
  périmètre de la tâche qui a écrit ces lignes.

CE QUE CET ORACLE NE MESURE PAS — cause racine, pas énumération
  Il lit la FORME de la référence, à l'unique endroit où GitHub l'écrit
  `uses:`, dans CE fichier. Trois conséquences qui ne se ferment pas en
  ajoutant des cas :
  - il ne RÉSOUT rien. Une chaîne de 40 hexadécimaux est acceptée sur sa
    seule forme : ni son existence, ni le dépôt qu'elle vise, ni son
    atteignabilité ne sont vérifiés. Résoudre exigerait le réseau, que le
    contrat de ce module exclut.
  - il ne voit pas la chaîne TRANSITIVE. Une action épinglée qui appelle
    elle-même des actions non épinglées dans son propre `action.yml`, ou un
    workflow réutilisable épinglé dont le contenu ne l'est pas, sont hors
    d'atteinte : ces fichiers ne vivent pas dans ce dépôt.
  - il ne voit pas ce qui n'est PAS un `uses:`. Un step `run:` qui
    télécharge et exécute du code (`curl … | bash`, `docker run`, une
    archive de release) est une dépendance externe que ce détecteur ne
    regarde pas.

  Deux exemptions explicites, qui sont des trous NOMMÉS et non des oublis :
  `./…` / `../…` (action locale, versionnée par le commit du dépôt lui-même
  — il n'existe aucun SHA amont à épingler) et `docker://…` (image de
  conteneur : un tag d'image y est tout aussi mutable qu'un tag Git, et cet
  oracle n'exige PAS son digest).

  Un SHA de 40 hexadécimaux MAJUSCULES est signalé non conforme. Faux
  positif délibéré : la minuscule est la forme canonique d'un SHA Git et
  c'est celle qu'exige déjà `test_ci_contract._FULL_SHA_RE` — diverger ici
  recréerait exactement la dérive décrite plus haut.

  Hors de ces exemptions, le détecteur REFUSE PAR DÉFAUT toute référence
  dont la forme n'est pas reconnue au lieu de l'accepter. Ce refus par
  défaut vaut pour toute référence QUI ATTEINT le classifieur — c'est la
  raison pour laquelle la liste de contournements testée plus bas n'a pas
  besoin d'être exhaustive, et elle ne l'est pas.

  La portée de cette garantie a une frontière, et c'est la cause racine de
  ce que la lecture de l'arbre analysé ne peut pas voir : une référence
  TEXTUELLEMENT PRÉSENTE mais ABSENTE de l'arbre que rend `yaml.safe_load`.
  Trois formes connues, la troisième trouvée en revue :
  commentaire YAML ; scalaire de `run:` ; et clé de mapping `uses`
  DUPLIQUÉE dans le même step, dont PyYAML ne garde que la dernière
  (dernier-gagnant). Si la référence écrasée est celle qui n'est pas
  épinglée, elle disparaît avant le classifieur et l'oracle rend une liste
  vide — un échec du côté silencieux, pas bruyant.
  Le détecteur jumeau par texte brut (`test_ci_contract._unpinned_actions`)
  voit ce cas : c'est une instanciation concrète du risque de dérive décrit
  plus haut. Exposition pratique quasi nulle — le YAML est volontairement
  malformé, et sous la sémantique dernier-gagnant l'action réellement
  exécutée serait de toute façon l'action épinglée.
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


# ---------------------------------------------------------------------------
# AUD-CI-002 (issue #576) — épinglage par SHA complet des actions de `ci.yml`.
# Section autonome : constantes, détecteur, cas RED sur le fichier réel, puis
# fixtures synthétiques de non-vacuité et de contournement. La duplication
# assumée avec `test_ci_contract._unpinned_actions`, ses raisons et le remède
# en cas de dérive sont déclarés dans l'en-tête de ce module.
# ---------------------------------------------------------------------------

# Une référence CONFORME : `owner/repo[/sous-chemin]@<40 hexadécimaux
# minuscules>`. Liste blanche stricte, appliquée en `fullmatch` — jamais un
# `match` avec `$`, qui accepterait un SHA suivi d'un saut de ligne (forme
# réellement produite par un scalaire YAML replié `uses: >`).
_USES_EPINGLE_RE = re.compile(r"[^\s@]+/[^\s@]+@[0-9a-f]{40}")

# Formes qui n'ont PAS de SHA amont à épingler — exemptées volontairement.
# `docker://` sans digest reste mutable : trou nommé, pas oubli (cf. en-tête).
_PREFIXES_SANS_SHA_AMONT = ("./", "../", "docker://")


def _refs_uses(noeud, chemin: str = "") -> list[tuple[str, object]]:
    """TOUTE valeur portée par une clé de mapping `uses`, à N'IMPORTE QUELLE
    profondeur du document analysé, avec son chemin YAML
    (`jobs.e2e.steps[1].uses`).

    Volontairement AGNOSTIQUE DU SCHÉMA : la fonction ne sait pas où GitHub
    autorise `uses:`. Elle couvre donc du même geste le `uses:` d'un step, le
    `uses:` de job d'un workflow réutilisable, le style flow `- {uses: …}` et
    toute position future — au lieu de dépendre d'une liste d'emplacements
    qu'il faudrait tenir à jour.

    La casse de la CLÉ est normalisée pour que l'oracle ne dépende jamais
    d'avoir raison sur la façon dont GitHub traite `Uses:` : une clé
    autrement cassée est vue ici, quitte à produire un faux positif — c'est
    la direction sûre.

    Ce qui n'est PAS collecté, et ne doit pas l'être : une occurrence de
    `uses:` qui n'est pas une clé de mapping mais du texte à l'intérieur d'un
    scalaire (bloc `run: |`, chaîne entre guillemets) ou un commentaire YAML.
    Ces formes n'exécutent aucune action ; les signaler serait un faux
    positif — et c'est précisément là que le détecteur par texte brut de
    `test_ci_contract.py` diverge de celui-ci.

    Liste vide == ce document ne référence AUCUNE action. Le cas RED
    ci-dessous refuse explicitement de conclure sur une liste vide, pour ne
    jamais passer VERT par absence de matière à examiner.
    """
    trouves: list[tuple[str, object]] = []
    if isinstance(noeud, dict):
        for cle, valeur in noeud.items():
            sous = f"{chemin}.{cle}" if chemin else str(cle)
            if isinstance(cle, str) and cle.lower() == "uses":
                trouves.append((sous, valeur))
            if not isinstance(valeur, str):
                trouves.extend(_refs_uses(valeur, sous))
    elif isinstance(noeud, list):
        for index, element in enumerate(noeud):
            trouves.extend(_refs_uses(element, f"{chemin}[{index}]"))
    return trouves


def _actions_non_epinglees(data) -> list[str]:
    """`<chemin YAML>: <référence>` pour chaque `uses:` qui n'est pas épinglé
    par un SHA complet, exemptions `./` et `docker://` mises à part.

    REFUS PAR DÉFAUT : tout ce qui ne correspond pas exactement à la liste
    blanche est signalé — tag (`@v5`, `@main`), SHA court, chaîne de 40
    caractères non hexadécimaux, SHA en majuscules, espace autour du `@`,
    référence sans `owner/repo`, valeur non textuelle. Une forme non
    anticipée est donc signalée, pas acceptée.

    Liste vide == aucune référence d'action de ce document ne peut changer de
    contenu sans commit ici — au sens de la FORME de la référence seulement,
    jamais de ce vers quoi elle pointe réellement (cf. en-tête du module).
    """
    non_epingles: list[str] = []
    for chemin, ref in _refs_uses(data):
        if not isinstance(ref, str):
            non_epingles.append(f"{chemin}: (valeur non textuelle) {ref!r}")
            continue
        candidat = ref.strip()
        if candidat.startswith(_PREFIXES_SANS_SHA_AMONT):
            continue
        if not _USES_EPINGLE_RE.fullmatch(candidat):
            non_epingles.append(f"{chemin}: {candidat}")
    return non_epingles


def test_ci_yml_toutes_les_actions_sont_epinglees_par_sha_complet():
    """RED #4 (AUD-CI-002) — défaut mesuré sur le merge-base `b9ced94` :
    `ci.yml` portait `actions/setup-python@v5`, tag MUTABLE, dans les jobs
    `e2e` et `e2e-load`, alors que ses trois `actions/checkout` étaient déjà
    épinglés par SHA complet. L'assertion nomme les sites fautifs par leur
    chemin YAML — deux sur cette base, liste vide une fois corrigés.
    Même convention d'ancrage que RED #1 : une mesure datée sur un commit
    atteignable, jamais une affirmation sur l'état courant du fichier.
    """
    data = _charger(_WORKFLOW_PATH)
    refs = _refs_uses(data)
    # Garde de non-vacuité sur le fichier RÉEL : sans elle, un `ci.yml` vidé,
    # renommé ou restructuré rendrait ce test VERT en n'ayant plus rien à
    # examiner — exactement le pass silencieux que cet oracle doit interdire.
    assert refs, (
        "Aucune référence `uses:` trouvée dans ci.yml : l'oracle d'épinglage "
        "n'aurait rien examiné et serait passé VERT à vide."
    )
    non_epingles = _actions_non_epinglees(data)
    assert not non_epingles, (
        "Action(s) de ci.yml non épinglée(s) par SHA complet — un tag est "
        "mutable en amont, le code exécuté par la CI peut donc changer sans "
        f"aucun commit dans ce dépôt (D-035) : {non_epingles}"
    )


# --- Non-vacuité du détecteur : fixtures synthétiques, indépendantes de ci.yml

_SHA_VALIDE = "08c6903cd8c0fde910a37f88322edcfb5dd907a8"


def _fixture(corps: str):
    return yaml.safe_load(corps) or {}


def test_detecteur_pin_signale_tag_sha_court_et_chaine_de_40_non_hex():
    """Preuve que le détecteur n'est pas vide, sur les quatre formes exigées
    par l'issue #576 : tag `@v5`, branche `@main`, SHA court (7 hex), et
    chaîne de 40 caractères NON hexadécimaux — la forme qui piégerait un
    détecteur se contentant de compter la longueur."""
    data = _fixture(
        "jobs:\n"
        "  suspect:\n"
        "    steps:\n"
        "      - uses: actions/setup-python@v5\n"
        "      - uses: actions/checkout@main\n"
        "      - uses: actions/checkout@08c6903\n"
        f"      - uses: actions/checkout@{'z' * 40}\n"
    )
    signales = _actions_non_epinglees(data)
    assert signales == [
        "jobs.suspect.steps[0].uses: actions/setup-python@v5",
        "jobs.suspect.steps[1].uses: actions/checkout@main",
        "jobs.suspect.steps[2].uses: actions/checkout@08c6903",
        f"jobs.suspect.steps[3].uses: actions/checkout@{'z' * 40}",
    ]


def test_detecteur_pin_ne_signale_pas_un_sha_complet_valide():
    """Le cas VERT doit exister, sinon l'oracle n'est pas satisfiable : un
    SHA complet de 40 hexadécimaux minuscules ne doit RIEN déclencher, y
    compris sur un `uses:` de workflow réutilisable au niveau job."""
    data = _fixture(
        "jobs:\n"
        "  sain:\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{_SHA_VALIDE}\n"
        f"      - uses: actions/setup-python@{_SHA_VALIDE}\n"
        "  appel:\n"
        f"    uses: org/repo/.github/workflows/reutilisable.yml@{_SHA_VALIDE}\n"
    )
    assert len(_refs_uses(data)) == 3, "fixture : trois références à examiner"
    assert _actions_non_epinglees(data) == []


# --- Contournements interrogés. Fermés ici, ou nommés comme trous en en-tête.


def test_contournement_uses_en_commentaire_yaml_n_est_pas_un_faux_positif():
    """CONTOURNEMENT FERMÉ (par construction) — un `uses:` en COMMENTAIRE
    n'exécute aucune action : le signaler serait un faux positif. Lire
    l'arbre analysé plutôt que le texte brut règle le cas sans liste
    d'exceptions. Le `uses:` réel de la même fixture, lui, doit être vu."""
    data = _fixture(
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      # - uses: actions/setup-python@v5   (désactivé)\n"
        f"      - uses: actions/checkout@{_SHA_VALIDE}\n"
    )
    assert [chemin for chemin, _ref in _refs_uses(data)] == ["jobs.a.steps[0].uses"]
    assert _actions_non_epinglees(data) == []


def test_contournement_uses_dans_une_chaine_run_n_est_pas_un_faux_positif():
    """CONTOURNEMENT FERMÉ — `uses:` apparaissant DANS un scalaire (bloc
    `run: |` ou chaîne entre guillemets) est du texte de shell, pas une
    action. C'est le point où ce détecteur diverge de
    `test_ci_contract._unpinned_actions`, qui applique son motif au texte
    brut et signalerait ici une action inexistante."""
    data = _fixture(
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - run: |\n"
        "          echo demarrage\n"
        "          uses: actions/evil@v1\n"
        "      - run: 'echo \"uses: actions/evil@main\"'\n"
    )
    assert _refs_uses(data) == []
    assert _actions_non_epinglees(data) == []


def test_contournement_docker_et_action_locale_ne_sont_pas_des_faux_positifs():
    """EXEMPTION ASSUMÉE — `docker://…`, `./…` et `../…` n'ont pas de SHA
    amont à épingler et ne doivent pas rougir. Que `docker://` sans digest
    reste mutable est un trou NOMMÉ dans l'en-tête, pas un oubli."""
    data = _fixture(
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - uses: docker://alpine:3.19\n"
        "      - uses: ./.github/actions/locale\n"
        "      - uses: ../action-voisine\n"
    )
    assert len(_refs_uses(data)) == 3, "fixture : les trois formes sont bien vues"
    assert _actions_non_epinglees(data) == []


def test_contournement_uses_de_job_reutilisable_non_epingle_est_signale():
    """CONTOURNEMENT FERMÉ — un `uses:` porté par le JOB (appel de workflow
    réutilisable) et non par un step échappe à tout détecteur qui n'inspecte
    que `jobs.*.steps[*]`. Le parcours agnostique du schéma le voit."""
    data = _fixture(
        "jobs:\n"
        "  appel:\n"
        "    uses: org/repo/.github/workflows/reutilisable.yml@v1\n"
        "    secrets: inherit\n"
    )
    assert _actions_non_epinglees(data) == [
        "jobs.appel.uses: org/repo/.github/workflows/reutilisable.yml@v1"
    ]


def test_contournement_style_flow_et_guillemets_est_signale():
    """CONTOURNEMENT FERMÉ — `- {uses: "actions/…@v5"}` (mapping en style
    flow, scalaire entre guillemets) est du YAML parfaitement valide. Un
    détecteur ancré sur `^\\s*-?\\s*uses:` en texte brut ne le voit pas, et
    inclurait le guillemet fermant dans la référence s'il le voyait."""
    data = _fixture(
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        '      - {uses: "actions/setup-python@v5"}\n'
        f"      - {{uses: 'actions/checkout@{_SHA_VALIDE}'}}\n"
    )
    assert _actions_non_epinglees(data) == [
        "jobs.a.steps[0].uses: actions/setup-python@v5"
    ]


def test_contournement_scalaire_replie_est_signale_malgre_le_saut_de_ligne():
    """CONTOURNEMENT FERMÉ — un scalaire replié (`uses: >`) produit une
    référence terminée par `\\n`. Avec `re.match(r"^[0-9a-f]{40}$", …)`, `$`
    accepte ce saut de ligne final : un `uses: >` suivi d'un SHA tronqué puis
    d'un retour ligne pourrait passer. D'où `fullmatch` sur la référence
    nettoyée. Un tag replié doit rougir, un SHA replié doit rester vert."""
    replie_tag = _fixture(
        "jobs:\n  a:\n    steps:\n      - uses: >\n          actions/setup-python@v5\n"
    )
    assert _refs_uses(replie_tag)[0][1].endswith("\n"), "fixture : saut de ligne présent"
    assert _actions_non_epinglees(replie_tag) == [
        "jobs.a.steps[0].uses: actions/setup-python@v5"
    ]
    replie_sha = _fixture(
        "jobs:\n  a:\n    steps:\n      - uses: >\n"
        f"          actions/checkout@{_SHA_VALIDE}\n"
    )
    assert _actions_non_epinglees(replie_sha) == []


def test_contournement_casse_et_espaces_autour_de_l_arobase_est_signale():
    """CONTOURNEMENT FERMÉ, dans la direction bruyante — un SHA de 40
    hexadécimaux MAJUSCULES et un espace de part et d'autre du `@` sont
    refusés. Refus par défaut : ces formes ne sont pas reconnues, donc elles
    sont signalées plutôt qu'acceptées."""
    data = _fixture(
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{_SHA_VALIDE.upper()}\n"
        f"      - uses: 'actions/checkout @{_SHA_VALIDE}'\n"
        f"      - uses: 'actions/checkout@ {_SHA_VALIDE}'\n"
        f"      - uses: checkout@{_SHA_VALIDE}\n"
    )
    assert [chemin for chemin, _ref in _refs_uses(data)] == [
        "jobs.a.steps[0].uses",
        "jobs.a.steps[1].uses",
        "jobs.a.steps[2].uses",
        "jobs.a.steps[3].uses",
    ]
    assert len(_actions_non_epinglees(data)) == 4


def test_contournement_ancre_yaml_est_signale_a_chaque_expansion():
    """CONTOURNEMENT FERMÉ — un step défini une fois via une ancre YAML puis
    réutilisé par alias. `yaml.safe_load` résout l'alias, le parcours voit
    donc la définition ET chaque expansion : aucune ne passe inaperçue."""
    data = _fixture(
        "modeles:\n"
        "  python: &python\n"
        "    uses: actions/setup-python@v5\n"
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - *python\n"
        "  b:\n"
        "    steps:\n"
        "      - *python\n"
    )
    assert _actions_non_epinglees(data) == [
        "modeles.python.uses: actions/setup-python@v5",
        "jobs.a.steps[0].uses: actions/setup-python@v5",
        "jobs.b.steps[0].uses: actions/setup-python@v5",
    ]


def test_detecteur_pin_signale_une_valeur_uses_non_textuelle():
    """Refus par défaut — un `uses:` dont la valeur n'est pas une chaîne
    n'est pas une référence d'action épinglable. Il est signalé, jamais
    ignoré au prétexte qu'il n'entre dans aucun cas prévu."""
    data = {"jobs": {"a": {"steps": [{"uses": ["actions/checkout@v5"]}]}}}
    signales = _actions_non_epinglees(data)
    assert len(signales) == 1
    assert signales[0].startswith("jobs.a.steps[0].uses: (valeur non textuelle)")
