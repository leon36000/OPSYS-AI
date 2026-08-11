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


# Chantier CI-hardening (post-C02-005, directive Nathan « aucun gate ne
# reste un placeholder ») : `security`, `pack-validation` ET `proof-sealed`
# ont désormais un MÉCANISME RÉEL câblé (run_security_scan.py,
# run_pack_validation.py, verify_proof_sealed.py) — le cas RED #3
# originel de C02-005 exigeait un « exit 1 » littéral pour les 3 jobs
# PARCE QU'aucun mécanisme réel n'existait encore ; l'exiger MAINTENANT
# serait incohérent (un vrai script a son propre code retour). Ensemble
# VOLONTAIREMENT VIDE aujourd'hui (pas supprimé) : si une FUTURE catégorie
# exigée était ajoutée sans mécanisme réel immédiat, elle rejoindrait cet
# ensemble — le mécanisme de repli (exit 1 littéral) reste testé
# (cf. test_categorie_sans_mecanisme_reel_exige_exit_1_litteral_sur_fixture_synthetique)
# même si aucune catégorie réelle ne l'utilise plus à ce jour.
_CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR: set[str] = set()

# Un `run:` invoquant réellement un outil/script d'analyse — jamais un
# simple `echo`/`exit` nu. Volontairement une liste FERMÉE des outils
# réellement câblés à ce jour (pas un motif générique `\S+\.py` qui
# accepterait N'IMPORTE QUEL script, y compris un futur placeholder
# déguisé en `python3 fake.py; exit 0`) — étendre cette liste EXIGE de
# nommer le nouvel outil ici, jamais un motif qui accepterait tout par défaut.
_OUTILS_REELS_RE = re.compile(
    r"\b(run_security_scan\.py|run_pack_validation\.py|verify_proof_sealed\.py|"
    r"bandit|pip-audit|run_static_checks|evaluer_matrice|pytest)\b"
)

# Une commande PUREMENT d'installation (`pip install bandit==...`) ne
# compte PAS comme invocation réelle même si le nom de l'outil apparaît
# en substring — trouvé par revue scellée indépendante (architecte) :
# supprimer le step qui EXÉCUTE le scan en ne gardant que le step
# d'installation laissait ce test VERT, puisque `bandit`/`pip-audit`
# apparaissent déjà littéralement dans la commande `pip install`. Une
# ligne matchée par CE motif est exclue de la recherche de
# `_OUTILS_REELS_RE`, quel que soit son contenu par ailleurs.
_LIGNE_INSTALLATION_SEULE_RE = re.compile(r"^\s*python3?\s+-m\s+pip\s+install\b|^\s*pip3?\s+install\b")

# Défense en profondeur (round 2, architecte) : la ligne ci-dessus exige
# que la commande d'installation COMMENCE la ligne — une continuation
# multi-ligne (`pip install \` puis la liste des paquets sur la ligne
# SUIVANTE) ou un gestionnaire alternatif (`uv pip install bandit`)
# échapperait à `_LIGNE_INSTALLATION_SEULE_RE` tout en laissant
# `bandit`/`pip-audit` matcher `_OUTILS_REELS_RE` comme si c'était une
# invocation réelle. Filtre COMPLÉMENTAIRE, au niveau du MATCH plutôt que
# de la ligne : un nom d'outil immédiatement suivi de `==<version>` est
# un spécificateur de paquet pip (jamais une invocation de commande, qui
# serait suivie d'un espace/flag/fin de ligne) — exclu quelle que soit la
# ligne où il apparaît.
_SPECIFICATEUR_PAQUET_RE = re.compile(r"==\d")


def _jobs_without_hard_failure(data: dict, noms: set[str]) -> list[str]:
    """Parmi les jobs dont le nom est dans `noms` :
    - `continue-on-error: true` est TOUJOURS en défaut, quel que soit le job
      (transformerait un blocage voulu en un vert silencieux).
    - Ceux de `_CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR` (aucun mécanisme réel
      câblé à ce jour) doivent avoir un échec dur explicite (`exit 1` en dur) —
      jamais un pass silencieux tant qu'aucun outil n'est câblé derrière eux.
    - Les autres catégories exigées (`security`, `pack-validation`, `types`,
      `tests`) doivent invoquer RÉELLEMENT un outil/script nommé dans
      `_OUTILS_REELS_RE` — un mécanisme réel qui n'invoquerait RIEN de
      reconnaissable serait indiscernable d'un placeholder déguisé.
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
        commandes_run = [
            step.get("run") or "" for step in steps if isinstance(step, dict)
        ]
        if nom in _CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR:
            a_echec_dur = any("exit 1" in c for c in commandes_run)
            if not a_echec_dur:
                en_defaut.append(nom)
        else:
            # Recherche LIGNE PAR LIGNE (jamais le bloc `run:` entier) —
            # une ligne d'installation pure (`pip install bandit==...`)
            # est exclue même si elle contient le nom d'un outil réel en
            # substring, sinon supprimer le step qui EXÉCUTE le scan tout
            # en gardant celui qui l'installe resterait indétectable
            # (trouvé par revue scellée indépendante, cf. commentaire
            # _LIGNE_INSTALLATION_SEULE_RE). PUIS filtre au niveau du
            # MATCH (_SPECIFICATEUR_PAQUET_RE) — défense en profondeur
            # contre une installation multi-ligne ou un gestionnaire
            # alternatif (uv, ...) qui échapperait au filtre par ligne.
            lignes_pertinentes = [
                ligne
                for c in commandes_run
                for ligne in c.splitlines()
                if not _LIGNE_INSTALLATION_SEULE_RE.search(ligne)
            ]
            invoque_outil_reel = any(
                match
                for ligne in lignes_pertinentes
                for match in _OUTILS_REELS_RE.finditer(ligne)
                if not _SPECIFICATEUR_PAQUET_RE.match(ligne, match.end())
            )
            if not invoque_outil_reel:
                en_defaut.append(nom)
    return en_defaut


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

    Les 5 catégories doivent exister comme jobs nommés. `security`,
    `pack-validation` ET `proof-sealed` ont désormais un mécanisme réel
    câblé (chantier CI-hardening post-C02-005, `_CATEGORIES_SANS_
    MECANISME_REEL_A_CE_JOUR` vide) — les 3 doivent invoquer réellement
    un outil reconnu (_OUTILS_REELS_RE), jamais un pass silencieux ni un
    `pip install` sans invocation (cf.
    test_job_avec_seulement_l_installation_sans_invocation_reelle_est_detecte).
    Le mécanisme de repli (`exit 1` littéral exigé pour toute catégorie
    encore dans `_CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR`) reste testé
    séparément sur une fixture synthétique — voir
    test_categorie_sans_mecanisme_reel_exige_exit_1_litteral_sur_fixture_synthetique
    — même si, à ce jour, aucune des 5 catégories réelles ne l'emprunte
    plus.
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


def test_job_avec_mecanisme_reel_invoquant_un_outil_nomme_n_est_pas_en_defaut():
    """Chantier CI-hardening : `security`/`pack-validation` invoquant
    réellement un script/outil reconnu (_OUTILS_REELS_RE) ne doivent PLUS
    être exigés d'avoir un `exit 1` littéral — le mécanisme réel EST leur
    échec dur (le script a son propre code retour)."""
    data = {
        "jobs": {
            "security": {
                "runs-on": "ubuntu-latest",
                "steps": [{"run": "python3 core/scripts/run_security_scan.py"}],
            },
            "pack-validation": {
                "runs-on": "ubuntu-latest",
                "steps": [{"run": "python3 core/scripts/run_pack_validation.py"}],
            },
        }
    }
    en_defaut = _jobs_without_hard_failure(data, {"security", "pack-validation"})
    assert en_defaut == []


def test_job_avec_seulement_l_installation_sans_invocation_reelle_est_detecte():
    """Trouvé par revue scellée indépendante (subagent architecte,
    Claude Opus 5, chantier CI-hardening tour 2) : un job qui installe
    bandit/pip-audit mais dont le step d'EXÉCUTION du scan a été
    supprimé passait ce test AVANT correctif — `bandit`/`pip-audit`
    apparaissent déjà en substring dans la commande `pip install`, donc
    _OUTILS_REELS_RE matchait sans qu'aucun scan ne tourne réellement."""
    data = {
        "jobs": {
            "security": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"run": "python3 -m pip install --quiet bandit==1.9.4 pip-audit==2.10.1"},
                    # step d'exécution du scan absent — régression simulée
                ],
            },
        }
    }
    en_defaut = _jobs_without_hard_failure(data, {"security"})
    assert en_defaut == ["security"]


def test_job_installation_multiligne_sans_invocation_reelle_est_detecte():
    """Défense en profondeur (round 2, architecte) : une installation
    continuée sur PLUSIEURS lignes (paquets listés sur la ligne suivant
    `pip install \\`, jamais sur la ligne qui commence par `pip install`
    elle-même) échapperait à `_LIGNE_INSTALLATION_SEULE_RE` seule — le
    filtre complémentaire par MATCH (`_SPECIFICATEUR_PAQUET_RE`, sur
    `==<version>`) doit fermer ce cas aussi."""
    data = {
        "jobs": {
            "security": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"run": "python3 -m pip install \\\n  --quiet \\\n  bandit==1.9.4 pip-audit==2.10.1"},
                    # step d'exécution du scan absent — régression simulée
                ],
            },
        }
    }
    en_defaut = _jobs_without_hard_failure(data, {"security"})
    assert en_defaut == ["security"]


def test_job_reel_deguise_en_placeholder_echo_exit_est_detecte():
    """Un job `security`/`pack-validation` qui régresserait vers un
    `echo ...; exit 0` (faux vert silencieux, jamais un vrai outil) DOIT
    être détecté — la présence d'un `exit` seul ne suffit plus, il faut un
    outil NOMMÉ dans _OUTILS_REELS_RE."""
    data = {
        "jobs": {
            "security": {
                "runs-on": "ubuntu-latest",
                "steps": [{"run": "echo tout va bien\nexit 0"}],
            },
        }
    }
    en_defaut = _jobs_without_hard_failure(data, {"security"})
    assert en_defaut == ["security"]


def test_proof_sealed_invoquant_verify_proof_sealed_n_est_pas_en_defaut():
    """proof-sealed a désormais un mécanisme réel câblé (chantier
    CI-hardening) : un job invoquant verify_proof_sealed.py, sans
    continue-on-error, n'est PLUS exigé d'avoir un exit 1 littéral."""
    data = {
        "jobs": {
            "proof-sealed": {
                "runs-on": "ubuntu-latest",
                "steps": [{"run": "python3 core/scripts/verify_proof_sealed.py --task C05-003"}],
            },
        }
    }
    en_defaut = _jobs_without_hard_failure(data, {"proof-sealed"})
    assert en_defaut == []


def test_categorie_sans_mecanisme_reel_exige_exit_1_litteral_sur_fixture_synthetique():
    """Le mécanisme de repli (catégorie SANS interface réelle -> exit 1
    littéral exigé) reste testé même si _CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR
    est vide aujourd'hui — fixture synthétique qui simule une FUTURE
    catégorie ajoutée à cet ensemble, jamais un test qui dépendrait de
    l'état actuel (vide) de la constante réelle."""
    global _CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR
    original = _CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR
    try:
        _CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR = {"future-gate"}
        data = {
            "jobs": {
                "future-gate": {
                    "runs-on": "ubuntu-latest",
                    "steps": [{"run": "echo pas encore de mecanisme reel"}],
                },
            }
        }
        en_defaut = _jobs_without_hard_failure(data, {"future-gate"})
        assert en_defaut == ["future-gate"]
    finally:
        _CATEGORIES_SANS_MECANISME_REEL_A_CE_JOUR = original


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
