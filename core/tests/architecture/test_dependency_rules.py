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
    """Preuve que le détecteur détecte VRAIMENT un import Modules M — pas
    seulement que le code réel est propre par construction (le code réel
    passerait même avec un détecteur cassé, cf. docstring de module)."""
    faux_fichier = tmp_path / "faux.py"
    faux_fichier.write_text("import m2_revenue_crm\nfrom m4_field_ops import x\n", encoding="utf-8")
    imports = _imports_absolus_top_level(faux_fichier)
    assert "m2_revenue_crm" in imports
    assert "m4_field_ops" in imports


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
    """Preuve que le détecteur détecte VRAIMENT un accès ports->adapters
    illégitime — pas seulement que le code réel (contracts.py, Protocols
    purs) est propre par construction."""
    faux_fichier = tmp_path / "faux_port.py"
    faux_fichier.write_text("from authz.engine import AuthzEngine\nimport config\n", encoding="utf-8")
    imports = _imports_absolus_top_level(faux_fichier)
    assert {"authz", "config"} <= imports


def test_adapters_peuvent_reellement_importer_les_ports_sans_etre_bloques():
    """Contrôle symétrique explicite du cas RED #2 : la règle ne bloque
    QUE ports->adapters, jamais adapters->ports. auth/authz/config
    n'important pas encore opsys_core.ports aujourd'hui (C04-001 vient
    juste de le créer), on prouve la NON-interdiction en import réel
    plutôt que par une assertion sur du code qui n'existe pas encore."""
    import importlib

    module = importlib.import_module("opsys_core.ports.contracts")
    assert hasattr(module, "DomainPort")
    assert hasattr(module, "ProviderPort")
    assert hasattr(module, "ModulePort")


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
    pour rester exempté du gate no-stub."""
    import inspect

    from opsys_core.ports import contracts

    for nom_classe in ("DomainPort", "ProviderPort", "ModulePort"):
        classe = getattr(contracts, nom_classe)
        source = inspect.getsource(classe)
        ligne_classe = next(l for l in source.splitlines() if l.strip().startswith("class "))
        assert "Protocol" in ligne_classe, (
            f"{nom_classe} n'hérite pas explicitement de Protocol dans sa ligne de "
            f"définition ({ligne_classe!r}) — l'exemption no-stub est syntaxique, pas sémantique"
        )
