"""Tests pour core/src/opsys_core/ports + core/dependency-rules.toml (C04-001)
— ports provider-neutral et interdiction des accès privés intermodules.

Couvre les 3 cas RED obligatoires de tasks/C04-001.md :
  1. opsys_core ne dépend pas de Modules M
  2. adapters peuvent dépendre des ports mais pas inversement
  3. aucun SDK fournisseur dans domain/kernel

Conception revue par architecture AVANT code (subagent `architecte`,
Claude Opus 5 natif) :
- « import-linter » (implémentation strictement bornée) est un raccourci
  de langage du spec — zéro occurrence dans les 4 sources citées, zéro
  mécanisme décrit. Réimplémenté en stdlib (ast + tomllib), cohérent avec
  la discipline « stdlib d'abord » déjà appliquée (core/pyproject.toml
  n'a qu'une dépendance : PyYAML). Ajouter le paquet PyPI réel violerait
  RF01-W7-ANTI-FRANKENSTACK-RULES.csv AF-22 (« engineering tools are not
  product runtime ») et tirerait des transitives (grimp, networkx) sans
  justification sourcée.
- Couches kernel/domain/application/adapters : mapping CONCEPTUEL sur les
  chemins EXISTANTS de core/src/ (déclaré dans dependency-rules.toml),
  AUCUNE restructuration physique de fichiers — les sources ne tranchent
  pas la structure de dossiers, et déplacer casserait C03-001..004 déjà
  intégrés. Seul dossier neuf : core/src/opsys_core/ports/ (imposé par
  les « Sorties exactes » du spec).
- application est déclarée VIDE aujourd'hui (peuplée par C04-004) —
  déclarée EXPLICITEMENT vide avec raison, pour éviter le piège déjà
  audité CAND-CA05-0004 (bijection silencieuse sur deux ensembles vides).
- auth/authz/config (pré-existants, HORS opsys_core/) sont classés
  `adapters` avec une exception nommée `legacy_pre_core` (résorption :
  C04-003 « Encapsuler authz et config existants par compatibilité ») —
  confirmé par tasks/C04-001.md (« documenter exceptions existantes
  authz/config ») et tasks/C04-003.md (sorties = compat/authz.py,
  compat/config.py).
- Enforcement : scan AST des fichiers RÉELS de core/src/ (jamais une
  matrice sur données synthétiques seules — cf. mémoire garde-prouvee-
  si-un-test-nomme-son-absence). Périmètre limité à core/src/ (le scan
  GLOBAL du dépôt, avec détection d'accès SQL/table privée, est C04-002).
  Corrige 2 pièges mesurés dans le patron réutilisé de
  core/tests/kernel/test_kernel_boot.py (C03-001, déjà mergé, jamais
  modifié ici) :
    (a) `_OPSYS_CORE_SRC.glob("*.py")` n'est PAS récursif — authority/ et
        status/ (ajoutés après C03-001) ne seraient pas scannés. Ce
        module utilise rglob().
    (b) `_imports_dans` de C03-001 ne lit jamais `noeud.level` — un
        import relatif (`from .planes import X`) serait enregistré comme
        top-level absolu ("planes"). Ce module exclut explicitement
        level>0 des imports « absolus » (interne par construction, ne
        peut jamais être un SDK fournisseur ni un accès adapters->ports
        illégitime au sens de ce module).
"""
from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from opsys_core.ports.contracts import DomainPort, ModulePort, ProviderPort  # noqa: E402,F401

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULES_M_ROOT = _REPO_ROOT / "Modules M"
_CORE_SRC = _REPO_ROOT / "core" / "src"
_OPSYS_CORE_SRC = _CORE_SRC / "opsys_core"
_REGLES_PATH = _REPO_ROOT / "core" / "dependency-rules.toml"


def _charger_regles() -> dict:
    with _REGLES_PATH.open("rb") as f:
        return tomllib.load(f)


def _fichiers_de_la_couche(nom_couche: str, regles: dict) -> list[Path]:
    """Énumère les fichiers .py RÉELS d'une couche déclarée, depuis les
    préfixes `paths` de dependency-rules.toml — jamais une liste devinée.
    Un préfixe pointant un fichier unique est inclus tel quel ; un préfixe
    pointant un dossier est parcouru récursivement (rglob)."""
    fichiers: list[Path] = []
    for prefixe in regles["layers"][nom_couche].get("paths", []):
        cible = _CORE_SRC / prefixe
        if cible.is_file():
            fichiers.append(cible)
        elif cible.is_dir():
            fichiers.extend(sorted(cible.rglob("*.py")))
    return fichiers


def _imports_absolus_top_level(chemin: Path) -> set[str]:
    """Ensemble des noms de premier niveau importés de façon ABSOLUE
    (import X / from X import ...) dans un fichier Python, via AST.
    Exclut EXPLICITEMENT les imports relatifs (`noeud.level > 0`) : un
    import relatif est interne au package courant par construction —
    jamais un SDK fournisseur, jamais un accès inter-couches au sens de
    ce module (piège (b) du docstring de module)."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
    noms: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                noms.add(alias.name.split(".")[0])
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0:
            if noeud.module:
                noms.add(noeud.module.split(".")[0])
    return noms


def _noms_modules_m_reels() -> set[str]:
    """Identique au mécanisme déjà scellé de core/tests/kernel/
    test_kernel_boot.py (C03-001) — énumération dynamique, jamais un
    pattern deviné. Dupliqué plutôt qu'importé : ce fichier de test ne
    doit dépendre que des SORTIES de C04-001 (opsys_core.ports), jamais
    d'un autre fichier de test."""
    noms: set[str] = set()
    for src_dir in _MODULES_M_ROOT.glob("*/src"):
        for entree in src_dir.iterdir():
            if entree.is_dir() and not entree.name.startswith((".", "__")):
                noms.add(entree.name)
            elif entree.is_file() and entree.suffix == ".py" and entree.stem != "__init__":
                noms.add(entree.stem)
    return noms


# ---------------------------------------------------------------------------
# Cas RED 1 — opsys_core ne dépend pas de Modules M
# ---------------------------------------------------------------------------


def test_d_finir_les_ports_et_d_pendances_autoris_es_1():
    """Cas RED #1 — AUCUN fichier de opsys_core/ (rglob récursif, couvre
    authority/ et status/ ajoutés après C03-001) n'importe un paquet réel
    de Modules M/."""
    noms_m = _noms_modules_m_reels()
    assert noms_m, "aucun paquet Modules M détecté — la mesure elle-même serait aveugle"
    assert len(noms_m) >= 10, f"mesure suspecte : seulement {len(noms_m)} paquets Modules M détectés"
    fichiers = sorted(_OPSYS_CORE_SRC.rglob("*.py"))
    assert len(fichiers) >= 12, f"mesure suspecte : seulement {len(fichiers)} fichiers sous opsys_core/"
    for fichier in fichiers:
        imports = _imports_absolus_top_level(fichier)
        collision = imports & noms_m
        assert not collision, f"GARDE RETIRÉE : {fichier} importe un paquet Modules M : {collision}"


def test_detecte_un_import_modules_m_sur_fixture_synthetique(tmp_path):
    """Preuve que le MÉCANISME COMPLET du cas RED #1 (extraction +
    _noms_modules_m_reels() + intersection) détecte VRAIMENT un import
    Modules M — pas seulement que le code réel est propre par
    construction (le code réel passerait même avec un détecteur cassé,
    cf. docstring de module).

    Objection Kimi-K3 tour 2 (mineure, confirmée) : la version précédente
    ne vérifiait que l'EXTRACTION des noms, jamais l'intersection avec
    _noms_modules_m_reels() ni l'assertion `assert not collision` du cas
    RED #1 réel — même classe de trou que celle déjà corrigée pour RED #2
    au tour 2, laissée ouverte ici par asymétrie. Corrigé pour cohérence :
    ce test reproduit maintenant le calcul EXACT du cas RED #1."""
    faux_fichier = tmp_path / "faux.py"
    faux_fichier.write_text("import m2_revenue_crm\nfrom m4_field_ops import x\n", encoding="utf-8")
    noms_m = _noms_modules_m_reels()
    imports = _imports_absolus_top_level(faux_fichier)
    collision = imports & noms_m
    assert collision == {"m2_revenue_crm", "m4_field_ops"}, (
        f"le détecteur ne repère pas la collision Modules M attendue : {collision}"
    )


def test_rglob_couvre_bien_authority_et_status_pas_seulement_la_racine():
    """Preuve nommée du correctif (a) : authority/ et status/ (ajoutés
    après C03-001) sont bien scannés — un glob() non récursif les
    manquerait silencieusement."""
    fichiers = {f.relative_to(_OPSYS_CORE_SRC) for f in _OPSYS_CORE_SRC.rglob("*.py")}
    sous_dossiers_couverts = {f.parts[0] for f in fichiers if len(f.parts) > 1}
    assert "authority" in sous_dossiers_couverts, "rglob ne couvre pas authority/ — régression du correctif (a)"
    assert "status" in sous_dossiers_couverts, "rglob ne couvre pas status/ — régression du correctif (a)"


# ---------------------------------------------------------------------------
# Cas RED 2 — adapters peuvent dépendre des ports mais pas inversement
# ---------------------------------------------------------------------------


def test_d_finir_les_ports_et_d_pendances_autoris_es_2():
    """Cas RED #2 — AUCUN fichier de la couche `ports` n'importe (de façon
    absolue) un nom de package top-level appartenant à la couche
    `adapters` (auth, authz, config). L'inverse (adapters -> ports) est
    autorisé et n'est PAS testé ici comme interdiction."""
    regles = _charger_regles()
    fichiers_ports = _fichiers_de_la_couche("ports", regles)
    assert fichiers_ports, "aucun fichier dans la couche ports — la mesure elle-même serait aveugle"
    noms_adapters_top_level = {
        prefixe.split("/")[0]
        for prefixe in regles["layers"]["adapters"]["paths"]
    }
    assert noms_adapters_top_level, "aucun package top-level déclaré pour adapters — mesure aveugle"
    for fichier in fichiers_ports:
        imports = _imports_absolus_top_level(fichier)
        collision = imports & noms_adapters_top_level
        assert not collision, (
            f"GARDE RETIRÉE : {fichier} (couche ports) importe la couche adapters : {collision}"
        )


def test_detecte_un_import_adapters_depuis_ports_sur_fixture_synthetique(tmp_path):
    """Preuve que le MÉCANISME COMPLET du cas RED #2 (extraction + calcul
    de noms_adapters_top_level depuis le TOML + intersection) détecte
    VRAIMENT un accès ports->adapters illégitime — pas seulement que le
    code réel (contracts.py, Protocols purs) est propre par construction.

    Objection Kimi-K3 tour 1 (mineure, confirmée) : la version précédente
    de ce test vérifiait seulement que _imports_absolus_top_level EXTRAIT
    bien les noms "authz"/"config" d'une fixture — jamais l'intersection
    avec noms_adapters_top_level ni l'assertion `assert not collision` du
    cas RED #2. Une mutation qui casserait CETTE assertion précise
    n'était donc PAS détectée par ce test compagnon, contrairement à ce
    que le pack de revue affirmait. Corrigé : ce test reproduit
    maintenant le calcul EXACT du cas RED #2 sur la fixture."""
    faux_fichier = tmp_path / "faux_port.py"
    faux_fichier.write_text("from authz.engine import AuthzEngine\nimport config\n", encoding="utf-8")
    regles = _charger_regles()
    noms_adapters_top_level = {
        prefixe.split("/")[0]
        for prefixe in regles["layers"]["adapters"]["paths"]
    }
    imports = _imports_absolus_top_level(faux_fichier)
    collision = imports & noms_adapters_top_level
    assert collision == {"authz", "config"}, (
        f"le détecteur ne repère pas la collision ports->adapters attendue : {collision}"
    )


def test_regle_adapters_vers_ports_est_bien_declaree_allowed():
    """Contrôle de cohérence documentaire explicite du cas RED #2 : la
    règle "adapters -> ports" (autorisée) doit être déclarée dans
    [[rules.allowed]] de dependency-rules.toml.

    Objection Kimi-K3 tour 1 (mineure, confirmée) : la version précédente
    de ce test faisait un import réel de opsys_core.ports.contracts DEPUIS
    LE FICHIER DE TEST lui-même (pas depuis un adapter réel) — vacuous,
    ne prouvait rien que la simple collecte pytest ne prouvait déjà.
    auth/authz/config n'important pas encore opsys_core.ports aujourd'hui
    (C04-001 vient juste de créer ports/), il n'existe aucun import réel
    adapters->ports à vérifier en exécution — ce test vérifie donc la
    déclaration TOML elle-même, honnêtement, plutôt qu'un import qui ne
    prouve rien."""
    regles = _charger_regles()
    paires_allowed = {(r["from"], r["to"]) for r in regles["rules"]["allowed"]}
    assert ("adapters", "ports") in paires_allowed, (
        "la règle adapters->ports (autorisée) n'est pas déclarée dans [[rules.allowed]]"
    )


def test_application_est_declaree_vide_explicitement():
    """Garde nommée contre le piège déjà audité CAND-CA05-0004 (bijection
    silencieuse sur deux ensembles vides) : la couche `application` doit
    être déclarée VIDE avec une raison explicite, jamais silencieusement
    absente du TOML."""
    regles = _charger_regles()
    assert "application" in regles["layers"], "couche application absente du TOML — doit être déclarée, même vide"
    assert regles["layers"]["application"]["paths"] == []
    assert regles["layers"]["application"].get("note", "").strip(), (
        "couche application vide sans raison explicite — cf. CAND-CA05-0004"
    )


# ---------------------------------------------------------------------------
# Cas RED 3 — aucun SDK fournisseur dans domain/kernel
# ---------------------------------------------------------------------------


def test_d_finir_les_ports_et_d_pendances_autoris_es_3():
    """Cas RED #3 — AUCUN fichier des couches `domain` et `kernel` n'a
    d'import absolu hors stdlib (et hors auto-référence opsys_core) —
    aucun SDK fournisseur tiers dans le coeur constitutionnel."""
    regles = _charger_regles()
    fichiers = _fichiers_de_la_couche("kernel", regles) + _fichiers_de_la_couche("domain", regles)
    assert fichiers, "aucun fichier dans kernel/domain — la mesure elle-même serait aveugle"
    stdlib = sys.stdlib_module_names
    for fichier in fichiers:
        imports = _imports_absolus_top_level(fichier)
        tiers = imports - stdlib - {"opsys_core"}
        assert not tiers, f"GARDE RETIRÉE : {fichier} (kernel/domain) importe un SDK tiers : {tiers}"


def test_detecte_un_sdk_tiers_sur_fixture_synthetique(tmp_path):
    """Preuve que le détecteur détecte VRAIMENT un SDK tiers — le code
    réel de kernel/domain n'a aujourd'hui que des imports relatifs et
    stdlib (hashlib, hmac, secrets, csv, pathlib, dataclasses, enum) :
    un test sur le code réel seul passerait même avec un détecteur
    cassé (piège de coïncidence déjà rencontré, cf. docstring)."""
    faux_fichier = tmp_path / "faux_domain.py"
    faux_fichier.write_text("import requests\nfrom boto3 import client\n", encoding="utf-8")
    imports = _imports_absolus_top_level(faux_fichier)
    tiers = imports - sys.stdlib_module_names - {"opsys_core"}
    assert tiers == {"requests", "boto3"}


def test_ne_signale_pas_un_import_relatif_ou_stdlib_comme_sdk_tiers(tmp_path):
    """Contrôle symétrique : un import relatif (interne par construction)
    et un import stdlib ne doivent JAMAIS être signalés comme SDK tiers —
    sinon la garde produirait un faux blocage sur du code sain (piège (b)
    du docstring : un détecteur naïf classerait `.planes` comme le nom
    top-level "planes", absent de stdlib -> faux positif)."""
    fichier = tmp_path / "propre.py"
    fichier.write_text(
        "from __future__ import annotations\nimport hashlib\nfrom enum import Enum\nfrom .planes import CorePlane\n",
        encoding="utf-8",
    )
    imports = _imports_absolus_top_level(fichier)
    assert "planes" not in imports, "import relatif faussement enregistré comme absolu — régression du correctif (b)"
    tiers = imports - sys.stdlib_module_names - {"opsys_core"}
    assert not tiers


def test_kernel_et_domain_n_importent_pas_la_couche_adapters():
    """Règles [[rules.forbidden]] kernel->adapters et domain->adapters de
    dependency-rules.toml : AUCUN fichier de kernel/domain n'importe (de
    façon absolue) un nom de package top-level appartenant à adapters.

    Objection MiMo-V2.5-Pro tour 1 (mineure, confirmée) : le cas RED #3
    (test_d_finir_les_ports_et_d_pendances_autoris_es_3, ci-dessus) ne
    vérifie QUE l'absence de SDK tiers (hors stdlib) — un futur
    `from auth.engine import AuthzEngine` dans kernel.py ne serait PAS
    détecté par ce cas RED (auth n'est ni stdlib ni "opsys_core", donc il
    SERAIT en fait détecté comme "SDK tiers" par accident — mais ce test
    dédié vérifie la règle inter-couches EXACTE déclarée dans le TOML,
    pas une coïncidence de calcul)."""
    regles = _charger_regles()
    fichiers = _fichiers_de_la_couche("kernel", regles) + _fichiers_de_la_couche("domain", regles)
    assert fichiers, "aucun fichier dans kernel/domain — la mesure elle-même serait aveugle"
    noms_adapters_top_level = {
        prefixe.split("/")[0]
        for prefixe in regles["layers"]["adapters"]["paths"]
    }
    assert noms_adapters_top_level, "aucun package top-level déclaré pour adapters — mesure aveugle"
    for fichier in fichiers:
        imports = _imports_absolus_top_level(fichier)
        collision = imports & noms_adapters_top_level
        assert not collision, (
            f"GARDE RETIRÉE : {fichier} (kernel/domain) importe la couche adapters : {collision}"
        )


def test_detecte_un_import_adapters_depuis_kernel_domain_sur_fixture_synthetique(tmp_path):
    """Preuve que le détecteur kernel/domain->adapters mord réellement —
    le code réel de kernel/domain est déjà propre par construction."""
    faux_fichier = tmp_path / "faux_kernel.py"
    faux_fichier.write_text("from auth.admin_gate import verify\nimport authz\n", encoding="utf-8")
    regles = _charger_regles()
    noms_adapters_top_level = {
        prefixe.split("/")[0]
        for prefixe in regles["layers"]["adapters"]["paths"]
    }
    imports = _imports_absolus_top_level(faux_fichier)
    collision = imports & noms_adapters_top_level
    assert collision == {"auth", "authz"}


# ---------------------------------------------------------------------------
# Complétude — l'union des couches déclarées couvre EXACTEMENT core/src/
# ---------------------------------------------------------------------------


def test_union_des_couches_couvre_exactement_tous_les_py_de_core_src():
    """Objection Kimi-K3 tour 1 (MAJEURE, confirmée) : dependency-
    rules.toml déclarait kernel = 4 fichiers nommés + domain =
    authority/+status/ + ports = ports/ — SANS opsys_core/__init__.py,
    qui n'appartenait donc à AUCUNE couche. Un import tiers dans
    __init__.py n'aurait été détecté par AUCUN des 3 cas RED. Corrigé :
    __init__.py ajouté à kernel (dependency-rules.toml). Cette garde
    NOMME l'absence : l'union de TOUTES les couches déclarées (kernel +
    domain + ports + application + adapters) doit couvrir EXACTEMENT
    l'ensemble des fichiers .py réels de core/src/ — aucun fichier
    "orphelin" échappant à toute couche, aucune dérive silencieuse.

    LIMITATION CONNUE (objection Kimi-K3 tour 2, mineure, confirmée et
    ASSUMÉE — pas corrigée) : cette garde vérifie l'ABSENCE d'orphelins
    (chaque fichier appartient à AU MOINS une couche), pas la CORRECTE
    assignation de chaque fichier à SA couche exacte. Déplacer
    "opsys_core/kernel.py" de kernel vers adapters dans le TOML resterait
    indétecté par cette garde seule (toujours 0 orphelin). Un test qui
    épinglerait explicitement l'appartenance de CHAQUE fichier à sa
    couche serait plus complet mais fragile (obligerait à mettre à jour
    ce test à chaque nouveau fichier de core/src/, hors du périmètre
    "définir les ports" de C04-001) — trade-off assumé, pas une
    sur-spécification non sourcée. La revue humaine du TOML reste la
    garde de correction d'assignation aujourd'hui."""
    regles = _charger_regles()
    tous_les_py_reels = {p.relative_to(_CORE_SRC) for p in _CORE_SRC.rglob("*.py")}
    assert tous_les_py_reels, "aucun fichier .py sous core/src/ — la mesure elle-même serait aveugle"

    couverts: set[Path] = set()
    for nom_couche in regles["layers"]:
        for fichier in _fichiers_de_la_couche(nom_couche, regles):
            couverts.add(fichier.relative_to(_CORE_SRC))

    orphelins = tous_les_py_reels - couverts
    assert not orphelins, (
        f"GARDE RETIRÉE : fichiers .py de core/src/ n'appartenant à AUCUNE couche déclarée "
        f"(échappent à tout enforcement kernel/domain/ports/application/adapters) : {orphelins}"
    )


def test_detecte_un_fichier_orphelin_sur_fixture_synthetique(tmp_path):
    """Preuve que la garde de complétude mord réellement — reproduit le
    trou de couverture RÉEL trouvé par Kimi-K3 (un fichier .py sous
    core/src/ absent de toute couche déclarée) sur une arborescence et un
    TOML synthétiques minimaux, plutôt que de re-corrompre
    dependency-rules.toml lui-même. Réimplémente localement le calcul de
    complétude (pas d'import du reste du module, pas de monkeypatch d'une
    constante globale) — EXERCE LES DEUX BRANCHES de _fichiers_de_la_couche
    (fichier unique ET dossier récursif via rglob), pas seulement la
    première.

    Objection Kimi-K3 tour 2 (mineure, confirmée) : la version précédente
    de cette fixture ne déclarait qu'un préfixe FICHIER dans le TOML
    synthétique (opsys_core/kernel.py), n'exerçant jamais la branche
    `elif cible.is_dir(): rglob(...)` — le docstring affirmait à tort
    « la logique testée est la même » que le code réel (qui a des
    couches déclarées par DOSSIER : authority/, status/, ports/,
    auth/, authz/, config/). Corrigé : le TOML synthétique déclare
    maintenant une couche par fichier (kernel) ET une couche par dossier
    (domain, avec un sous-fichier), exerçant les deux branches réelles."""
    faux_core_src = tmp_path / "core_src"
    (faux_core_src / "opsys_core" / "domaine_dir").mkdir(parents=True)
    (faux_core_src / "opsys_core" / "kernel.py").write_text("", encoding="utf-8")
    (faux_core_src / "opsys_core" / "domaine_dir" / "regle.py").write_text("", encoding="utf-8")
    (faux_core_src / "opsys_core" / "orphelin.py").write_text("", encoding="utf-8")
    faux_toml = tmp_path / "regles.toml"
    faux_toml.write_text(
        '[layers.kernel]\npaths = ["opsys_core/kernel.py"]\n'
        '[layers.domain]\npaths = ["opsys_core/domaine_dir/"]\n',
        encoding="utf-8",
    )

    with faux_toml.open("rb") as f:
        regles = tomllib.load(f)
    tous_les_py = {p.relative_to(faux_core_src) for p in faux_core_src.rglob("*.py")}
    couverts: set[Path] = set()
    for nom_couche in regles["layers"]:
        for prefixe in regles["layers"][nom_couche].get("paths", []):
            cible = faux_core_src / prefixe
            if cible.is_file():
                couverts.add(cible.relative_to(faux_core_src))
            elif cible.is_dir():
                couverts.update(p.relative_to(faux_core_src) for p in cible.rglob("*.py"))
    orphelins = tous_les_py - couverts
    assert orphelins == {Path("opsys_core/orphelin.py")}
    assert Path("opsys_core/domaine_dir/regle.py") in couverts, (
        "la branche dossier (rglob) de la fixture n'a pas couvert le fichier attendu"
    )


# ---------------------------------------------------------------------------
# Robustesse structurelle du fichier de règles
# ---------------------------------------------------------------------------


def test_dependency_rules_toml_documente_l_ecart_import_linter():
    """La spec de tâche (implémentation strictement bornée) nomme le
    paquet PyPI `import-linter`, absent de toute source citée et non
    ajouté (revue d'architecture AVANT code) — l'écart doit être
    documenté EN CLAIR dans le fichier de règles, jamais résolu en
    silence (même discipline que core/quality-gates.toml, C02-004)."""
    texte = _REGLES_PATH.read_text(encoding="utf-8")
    assert "import-linter" in texte.lower() or "import_linter" in texte.lower()


def test_toutes_les_couches_du_vocabulaire_du_spec_sont_declarees():
    """kernel/domain/application/adapters + ports (imposé par les Sorties
    exactes) doivent toutes être déclarées dans le TOML — même
    `application`, vide (cf. test dédié ci-dessus)."""
    regles = _charger_regles()
    assert set(regles["layers"]) == {"kernel", "domain", "ports", "application", "adapters"}


def test_adapters_documente_l_exception_legacy_pre_core():
    """auth/authz/config sont classés adapters avec une exception nommée
    et sa résorption (C04-003) — jamais une inclusion silencieuse d'un
    code pré-existant hors du périmètre littéral du spec (qui ne nomme
    que authz/config ; auth est une extension assumée, documentée comme
    telle — revue d'architecture AVANT code)."""
    regles = _charger_regles()
    adapters = regles["layers"]["adapters"]
    assert adapters.get("exception", "").strip()
    assert "C04-003" in adapters.get("exception_resorption", "")
    for nom in ("auth/", "authz/", "config/"):
        assert nom in adapters["paths"], f"{nom} absent des adapters déclarés"


def test_protocols_sont_bien_des_protocols_explicites():
    """R1 de la revue d'architecture : l'exemption no-stub des corps `...`
    est syntaxique sur node.bases — chaque Protocol doit hériter
    EXPLICITEMENT de `Protocol` (pas d'un autre Protocol par transitivité)
    pour rester exempté du gate no-stub.

    Objection Kimi-K3 tour 1 (mineure, confirmée) : la version précédente
    de ce test faisait `"Protocol" in ligne_classe` — un test de
    SOUS-CHAÎNE qui passerait pour `class DomainPort(BaseProtocol):`,
    exactement l'héritage transitif que ce test prétend exclure. Corrigé
    en parsant réellement l'AST et en comparant chaque `ast.Name` de
    `node.bases` à l'identifiant EXACT "Protocol" — la même méthode que
    le hook réel `no_stub_ast.py::_is_protocol_base`."""
    contracts_path = (
        Path(__file__).resolve().parents[2] / "src" / "opsys_core" / "ports" / "contracts.py"
    )
    arbre = ast.parse(contracts_path.read_text(encoding="utf-8"), filename=str(contracts_path))
    classes = {
        noeud.name: noeud
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.ClassDef)
    }
    for nom_classe in ("DomainPort", "ProviderPort", "ModulePort"):
        assert nom_classe in classes, f"{nom_classe} introuvable dans contracts.py"
        noms_bases = {
            base.id for base in classes[nom_classe].bases if isinstance(base, ast.Name)
        }
        assert "Protocol" in noms_bases, (
            f"{nom_classe} n'hérite pas EXPLICITEMENT de Protocol (bases réelles : "
            f"{noms_bases!r}) — l'exemption no-stub est syntaxique sur node.bases, "
            f"pas sémantique (héritage transitif non exempté)"
        )


def test_le_check_protocols_explicites_rejette_l_heritage_transitif_sur_fixture():
    """Preuve que le check ci-dessus mord réellement sur le cas que
    l'objection Kimi-K3 a nommé : une classe héritant d'un Protocol
    INTERMÉDIAIRE (pas directement de typing.Protocol) doit être rejetée
    par une vérification stricte de node.bases, alors qu'un simple test
    de sous-chaîne textuelle la laisserait passer à tort."""
    source = "class FauxPort(BaseProtocol):\n    ...\n"
    arbre = ast.parse(source)
    classe = next(n for n in ast.walk(arbre) if isinstance(n, ast.ClassDef))
    noms_bases = {base.id for base in classe.bases if isinstance(base, ast.Name)}
    assert "Protocol" not in noms_bases, "héritage transitif via BaseProtocol non détecté comme tel"
    assert "BaseProtocol" in noms_bases
    # Le test de sous-chaîne retiré (piège) aurait pourtant trouvé "Protocol" ici :
    assert "Protocol" in "class FauxPort(BaseProtocol):", (
        "démontre pourquoi un test de sous-chaîne textuelle est insuffisant"
    )
