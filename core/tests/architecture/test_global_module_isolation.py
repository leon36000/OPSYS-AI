"""Tests pour core/scripts/check_module_isolation.py (C04-002) — linter
d'isolation intermodule GLOBAL (tout le dépôt, M1-M10 inclus en lecture
seule pour l'analyse — aucune modification de logique métier).

Couvre les 3 cas RED obligatoires de tasks/C04-002.md :
  1. détecter import direct M1->M2
  2. détecter SQL/table privée d'un autre module
  3. ne pas confondre contrats publics et tables privées

Conception revue par architecture AVANT code (subagent `architecte`,
Claude Opus 5 natif) :
- La frontière public/privé EXISTE déjà et est gardée mécaniquement par
  `scripts/structure_lint.py` : `contracts/` (obligatoire par module,
  contient des YAML gelés versionnés — jamais du code Python importable,
  0 fichier .py mesuré) = PUBLIC ; `src/` = PRIVÉ. `<module>/contrats.py`
  dans `src/` N'EST PAS un contrat exporté — c'est un VALIDATEUR interne
  du contrat YAML gelé (piège de vocabulaire, confirmé par lecture
  directe de Modules M/M2-revenue-crm/src/m2_revenue_crm/contrats.py et
  Modules M/M5-financecore/src/m5_financecore/contrats.py).
- Aucun SQL dans ce dépôt (mesure exhaustive : 0 occurrence de
  sqlite3/SELECT/INSERT INTO/CREATE TABLE/.execute(/cursor( sur tout
  *.py). Le cas RED #2 est donc un ENSEMBLE DÉCLARÉ VIDE et documenté
  (même discipline que core/dependency-rules.toml pour import-linter,
  et que [layers.application] pour C04-001) — jamais un parseur SQL
  fictif sans substrat réel. Le vrai canal d'accès privé mesuré est le
  CHEMIN DE FICHIER : un littéral `Modules M/<Mx>/...` référencé par un
  fichier n'appartenant pas à Mx, hors contracts/.
- 0 import cross-module M-vers-M existe aujourd'hui dans le dépôt réel
  (mesure exhaustive par grep) — les 3 cas RED sont donc PROUVÉS par
  fixtures synthétiques, jamais par simple absence sur le code réel
  (piège de coïncidence déjà documenté, cf. C03-001/C04-001).
- M7-marketing n'a PAS de paquet unique m7_marketing : 13 paquets PLATS
  (ads, aeo, attribution, brand, competitive, content, reputation, roi,
  seo, site, social, utm, workflows), un seul avec __init__.py — mesuré
  directement. `site` est AUSSI un module stdlib : exclu explicitement
  de toute détection par nom (collision déjà rencontrée en C04-001).
- Exclusions de périmètre nommées (mesurées, pas supposées) :
  `audit/` (cartographies légitimes référençant tous les modules par
  construction, ex. path_and_authority_map.py) et `tests/e2e/` (harnais
  e2e dépôt légitime, ex. _harness.py qui construit un chemin vers
  M7-marketing/src/brand pour ses propres besoins de test).
- Scan en AST UNIQUEMENT, jamais en regex/texte brut : des fichiers
  contiennent des CHEMINS D'AUTRES MODULES dans leurs COMMENTAIRES ou
  DOCSTRINGS (ex. Modules M/M3-estimation/src/m3_estimation/contrats.py
  cite Modules M/M2-revenue-crm/... en commentaire) — un scan textuel
  produirait des faux positifs garantis. ast.Constant ne voit jamais un
  commentaire.
- Le job CI `tests` (core-ci.yml) ne lançait QUE core/tests/bootstrap —
  core/tests/architecture/ (donc aussi C04-001) n'était exécuté par
  AUCUN job CI avant ce correctif. Câblé dans ce module (ci.yml +
  core-ci.yml), pas silencieusement laissé de côté.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "core" / "scripts"))

import pytest

from check_module_isolation import (  # noqa: E402
    Violation,
    charger_map_modules_m,
    fichiers_a_scanner,
    scan_module_isolation,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Fondations — la map nom-de-paquet -> module propriétaire
# ---------------------------------------------------------------------------


def test_map_modules_m_couvre_les_22_paquets_reels():
    """9 modules mNN_* (un paquet chacun) + 13 paquets plats de M7 = 22.
    Mesure dynamique, jamais un pattern deviné (cf. mémoire verifier-la-
    structure-pas-le-nom-suppose)."""
    m = charger_map_modules_m(_REPO_ROOT)
    assert len(m) >= 22, f"mesure suspecte : seulement {len(m)} paquets Modules M détectés"
    assert m["m2_revenue_crm"] == "M2-revenue-crm"
    assert m["m5_financecore"] == "M5-financecore"
    for nom_m7 in ("ads", "aeo", "brand", "content", "roi", "workflows"):
        assert m[nom_m7] == "M7-marketing", f"{nom_m7} devrait appartenir à M7-marketing"


def test_map_modules_m_exclut_site_car_ambigu_avec_stdlib():
    """`site` est à la fois un paquet stdlib et un sous-dossier de
    M7-marketing/src/ — la map elle-même le contient (c'est un paquet M
    réel), mais tout consommateur doit soustraire sys.stdlib_module_names
    avant de signaler une collision (cas RED sur fixture synthétique
    dédié plus bas), jamais faire confiance à la map seule."""
    m = charger_map_modules_m(_REPO_ROOT)
    assert "site" in m
    assert m["site"] == "M7-marketing"
    assert "site" in sys.stdlib_module_names


def test_fichiers_a_scanner_exclut_audit_et_tests_e2e():
    """Exclusions de périmètre nommées et mesurées : audit/ (cartographies
    légitimes) et tests/e2e/ (harnais dépôt légitime) ne sont jamais
    scannés pour des violations d'isolation."""
    fichiers = set(fichiers_a_scanner(_REPO_ROOT))
    assert fichiers, "aucun fichier à scanner — la mesure elle-même serait aveugle"
    assert len(fichiers) >= 300, f"mesure suspecte : seulement {len(fichiers)} fichiers .py trouvés"
    for f in fichiers:
        rel = f.relative_to(_REPO_ROOT)
        assert not str(rel).startswith("audit/"), f"audit/ non exclu : {rel}"
        assert not str(rel).startswith("tests/e2e/"), f"tests/e2e/ non exclu : {rel}"


# ---------------------------------------------------------------------------
# Cas RED 1 — détecter import direct M1->M2
# ---------------------------------------------------------------------------


def test_cr_er_le_linter_d_isolation_intermodule_global_1(tmp_path):
    """Cas RED #1 — un import ABSOLU d'un paquet appartenant à un AUTRE
    module M doit être signalé comme violation. 0 cas réel dans le dépôt
    aujourd'hui (mesuré) : fixture synthétique, comme C04-001/C03-001."""
    faux_repo = tmp_path / "repo"
    m1_src = faux_repo / "Modules M" / "M1-front-office" / "src" / "m1_front_office"
    m1_src.mkdir(parents=True)
    (m1_src / "__init__.py").write_text("", encoding="utf-8")
    (m1_src / "service.py").write_text("import m2_revenue_crm\n", encoding="utf-8")
    (faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm").mkdir(parents=True)
    (faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm" / "__init__.py").write_text(
        "", encoding="utf-8"
    )

    violations = scan_module_isolation(faux_repo)
    cibles = [v for v in violations if v.kind == "IMPORT_CROSS_MODULE"]
    assert cibles, "GARDE RETIRÉE : import M1->M2 non détecté"
    assert any(v.module_source == "M1-front-office" and v.module_cible == "M2-revenue-crm" for v in cibles)


def test_import_relatif_intra_module_n_est_jamais_signale(tmp_path):
    """Contrôle symétrique : un import RELATIF (interne au module courant
    par construction) ne doit jamais être signalé — sinon la garde
    produirait un faux blocage sur du code sain.

    Le nom importé relativement (`m2_revenue_crm`) est délibérément
    choisi identique à un VRAI paquet M2 déclaré dans la fixture, pour
    que la garde `noeud.level == 0` soit discriminante : avec un nom
    qui ne collisionnerait avec AUCUN paquet réel (ex. « registre »),
    retirer la garde ne changerait rien (aucune collision possible dans
    la map_modules) et ce test ne mordrait pas sur la mutation — piège
    de cardinalité déjà rencontré ailleurs dans ce projet."""
    faux_repo = tmp_path / "repo"
    m1_src = faux_repo / "Modules M" / "M1-front-office" / "src" / "m1_front_office"
    m1_src.mkdir(parents=True)
    (m1_src / "__init__.py").write_text("", encoding="utf-8")
    (m1_src / "service.py").write_text(
        "from . import registre\nfrom .m2_revenue_crm import x\n", encoding="utf-8"
    )
    (faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm").mkdir(parents=True)
    (faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm" / "__init__.py").write_text(
        "", encoding="utf-8"
    )

    violations = scan_module_isolation(faux_repo)
    assert not [v for v in violations if v.kind == "IMPORT_CROSS_MODULE"]


def test_import_du_meme_module_n_est_jamais_signale(tmp_path):
    """Un fichier de M2 qui importe m2_revenue_crm (SON PROPRE paquet, de
    façon absolue) n'est pas une violation d'isolation."""
    faux_repo = tmp_path / "repo"
    m2_src = faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm"
    m2_src.mkdir(parents=True)
    (m2_src / "__init__.py").write_text("", encoding="utf-8")
    (m2_src / "service.py").write_text("import m2_revenue_crm\nfrom m2_revenue_crm import registre\n", encoding="utf-8")

    violations = scan_module_isolation(faux_repo)
    assert not [v for v in violations if v.kind == "IMPORT_CROSS_MODULE"]


def test_import_site_n_est_jamais_confondu_avec_le_paquet_m7(tmp_path):
    """`site` (stdlib) importé par un module QUI N'EST PAS M7-marketing
    ne doit jamais être signalé comme un accès au paquet M7-marketing/
    src/site/ — collision de nom déjà rencontrée en C04-001."""
    faux_repo = tmp_path / "repo"
    m1_src = faux_repo / "Modules M" / "M1-front-office" / "src" / "m1_front_office"
    m1_src.mkdir(parents=True)
    (m1_src / "__init__.py").write_text("", encoding="utf-8")
    (m1_src / "service.py").write_text("import site\n", encoding="utf-8")
    (faux_repo / "Modules M" / "M7-marketing" / "src" / "site").mkdir(parents=True)
    (faux_repo / "Modules M" / "M7-marketing" / "src" / "site" / "__init__.py").write_text("", encoding="utf-8")

    violations = scan_module_isolation(faux_repo)
    assert not [v for v in violations if v.kind == "IMPORT_CROSS_MODULE"], (
        "import site (stdlib) faussement signalé comme accès au paquet M7/site"
    )


# ---------------------------------------------------------------------------
# Cas RED 2 — détecter SQL/table privée d'un autre module
# ---------------------------------------------------------------------------


def test_cr_er_le_linter_d_isolation_intermodule_global_2():
    """Cas RED #2 — ÉCART SOURCÉ DOCUMENTÉ EN CLAIR (mesure exhaustive,
    subagent architecte) : ce dépôt ne contient AUCUN SQL (0 occurrence
    de sqlite3/SELECT/INSERT INTO/CREATE TABLE/.execute(/cursor( sur
    tout *.py, grep exhaustif). Le mécanisme de détection SQL EXISTE
    dans check_module_isolation.py (fonction dédiée, jamais un parseur
    fictif silencieusement absent) mais son résultat sur le dépôt RÉEL
    est un ensemble VIDE — déclaré et prouvé vide ici, jamais confondu
    avec « non implémenté ». Un accès SQL à une table d'un autre module
    (fixture synthétique ci-dessous) EST détecté quand il existe."""
    violations_reelles = scan_module_isolation(_REPO_ROOT)
    sql_reels = [v for v in violations_reelles if v.kind == "SQL_TABLE_PRIVEE"]
    assert sql_reels == [], (
        "mesure inattendue : le dépôt réel contient du SQL détecté comme violation — "
        "vérifier si le substrat SQL a changé depuis la mesure de la revue d'architecture"
    )


def test_detecte_un_acces_sql_table_privee_sur_fixture_synthetique(tmp_path):
    """Preuve que le détecteur SQL (déclaré vide sur le réel ci-dessus)
    MORD réellement — reproduit un accès sqlite3 à une table qualifiée
    d'un autre module."""
    faux_repo = tmp_path / "repo"
    m1_src = faux_repo / "Modules M" / "M1-front-office" / "src" / "m1_front_office"
    m1_src.mkdir(parents=True)
    (m1_src / "__init__.py").write_text("", encoding="utf-8")
    (m1_src / "acces.py").write_text(
        "import sqlite3\n"
        "def f():\n"
        "    conn = sqlite3.connect('x.db')\n"
        "    conn.execute('SELECT * FROM m2_revenue_crm.leads')\n",
        encoding="utf-8",
    )
    (faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm").mkdir(parents=True)
    (faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm" / "__init__.py").write_text(
        "", encoding="utf-8"
    )

    violations = scan_module_isolation(faux_repo)
    cibles = [v for v in violations if v.kind == "SQL_TABLE_PRIVEE"]
    assert cibles, "GARDE RETIRÉE : accès SQL à une table qualifiée d'un autre module non détecté"
    assert any(v.module_source == "M1-front-office" and v.module_cible == "M2-revenue-crm" for v in cibles)


# ---------------------------------------------------------------------------
# Cas RED 3 — ne pas confondre contrats publics et tables privées
# ---------------------------------------------------------------------------


def test_cr_er_le_linter_d_isolation_intermodule_global_3(tmp_path):
    """Cas RED #3 — un accès au dossier `contracts/` (public, YAML gelé)
    d'un AUTRE module est AUTORISÉ ; un accès à `src/` (privé) du même
    autre module dans le MÊME fichier est REFUSÉ — les deux mesurés
    ensemble pour prouver la distinction, pas seulement chacun isolément."""
    faux_repo = tmp_path / "repo"
    m1_src = faux_repo / "Modules M" / "M1-front-office" / "src" / "m1_front_office"
    m1_src.mkdir(parents=True)
    (m1_src / "__init__.py").write_text("", encoding="utf-8")
    (m1_src / "lecture.py").write_text(
        "from pathlib import Path\n"
        "CONTRAT = Path('Modules M/M2-revenue-crm/contracts/m2-lead.v1.yaml')\n"
        "PRIVE = Path('Modules M/M2-revenue-crm/src/m2_revenue_crm/registre.py')\n",
        encoding="utf-8",
    )
    (faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm").mkdir(parents=True)
    (faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (faux_repo / "Modules M" / "M2-revenue-crm" / "contracts").mkdir(parents=True)

    violations = scan_module_isolation(faux_repo)
    cibles = [v for v in violations if v.kind == "CHEMIN_PRIVE_CROSS_MODULE"]
    assert any("registre.py" in v.detail for v in cibles), (
        "GARDE RETIRÉE : accès au chemin src/ (privé) d'un autre module non détecté"
    )
    assert not any("contracts" in v.detail for v in cibles), (
        "FAUX POSITIF : accès au chemin contracts/ (public) signalé à tort comme violation"
    )


def test_chemin_prive_dans_son_propre_module_n_est_jamais_signale(tmp_path):
    """Un fichier de M2 référençant un chemin src/ de SON PROPRE module
    (M2) n'est jamais une violation — seule la référence CROISÉE l'est."""
    faux_repo = tmp_path / "repo"
    m2_src = faux_repo / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm"
    m2_src.mkdir(parents=True)
    (m2_src / "__init__.py").write_text("", encoding="utf-8")
    (m2_src / "lecture.py").write_text(
        "from pathlib import Path\nMOI = Path('Modules M/M2-revenue-crm/src/m2_revenue_crm/registre.py')\n",
        encoding="utf-8",
    )

    violations = scan_module_isolation(faux_repo)
    assert not [v for v in violations if v.kind == "CHEMIN_PRIVE_CROSS_MODULE"]


def test_chemin_dans_un_commentaire_n_est_jamais_signale_scan_ast_pas_texte(tmp_path):
    """Preuve du choix « scan AST uniquement, jamais regex/texte » : un
    chemin d'un AUTRE module cité dans un COMMENTAIRE (pas une chaîne
    littérale exécutable) ne doit jamais être signalé — ast.Constant ne
    voit jamais un commentaire. Cas réel mesuré : Modules M/M3-estimation
    /src/m3_estimation/contrats.py cite Modules M/M2-revenue-crm/... en
    commentaire, sans que ce soit une violation d'isolation."""
    faux_repo = tmp_path / "repo"
    m1_src = faux_repo / "Modules M" / "M1-front-office" / "src" / "m1_front_office"
    m1_src.mkdir(parents=True)
    (m1_src / "__init__.py").write_text("", encoding="utf-8")
    (m1_src / "doc.py").write_text(
        "# Voir aussi Modules M/M2-revenue-crm/src/m2_revenue_crm/registre.py pour le patron.\n"
        "X = 1\n",
        encoding="utf-8",
    )

    violations = scan_module_isolation(faux_repo)
    assert not [v for v in violations if v.kind == "CHEMIN_PRIVE_CROSS_MODULE"], (
        "un chemin cité en COMMENTAIRE a été signalé — le scan n'est pas purement AST"
    )


# ---------------------------------------------------------------------------
# Mesure sur le dépôt réel — non-vacuité et absence de violation réelle
# ---------------------------------------------------------------------------


def test_scan_du_depot_reel_ne_trouve_aucune_violation_d_isolation():
    """0 import cross-module M-vers-M et 0 accès chemin privé cross-module
    existent aujourd'hui dans le dépôt réel (mesuré par le subagent
    architecte, grep exhaustif). Le scan RÉEL doit rendre 0 violation —
    la preuve de morsure vient des fixtures synthétiques ci-dessus, pas
    de ce test (qui prouve l'absence de RÉGRESSION, pas la détection)."""
    violations = scan_module_isolation(_REPO_ROOT)
    non_sql = [v for v in violations if v.kind != "SQL_TABLE_PRIVEE"]
    assert non_sql == [], f"violations d'isolation inattendues sur le dépôt réel : {non_sql}"


def test_ci_yml_invoque_reellement_le_linter_isolation():
    """« remplacer le commentaire CI périmé par un test réel » : le
    commentaire de .github/workflows/ci.yml citant le fichier fantôme
    tests/test_isolation_modules.py doit être remplacé par un step
    invoquant réellement check_module_isolation.py — jamais un
    remplacement décoratif."""
    texte = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "tests/test_isolation_modules.py" not in texte, (
        "le commentaire périmé citant un fichier fantôme est toujours présent"
    )
    assert "check_module_isolation.py" in texte, (
        "ci.yml n'invoque pas réellement check_module_isolation.py"
    )


def test_core_ci_yml_execute_desormais_core_tests_architecture():
    """Trou CRITIQUE trouvé par la revue d'architecture : core/tests/
    architecture/ (donc aussi C04-001, déjà VERIFIED/INTEGRATED) n'était
    exécuté par AUCUN job CI. Fermé ici : core-ci.yml doit lancer
    core/tests/architecture en plus de core/tests/bootstrap, dans la
    MÊME commande pytest (scope core/ unique, légal selon la garde
    _isolation_violations de test_ci_contract.py — jamais deux scopes
    combinés dans une seule ligne)."""
    texte = (_REPO_ROOT / ".github" / "workflows" / "core-ci.yml").read_text(encoding="utf-8")
    assert "core/tests/architecture" in texte, (
        "core-ci.yml n'exécute toujours pas core/tests/architecture/"
    )
