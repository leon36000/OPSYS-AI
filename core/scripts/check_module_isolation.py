#!/usr/bin/env python3
"""Linter d'isolation intermodule GLOBAL — Core OPSYS-AI (C04-002).

Impose le modular monolith au niveau du dépôt ENTIER (M1-M10 inclus, en
lecture seule pour l'analyse — aucune modification de logique métier).
Généralise le mécanisme déjà scellé de core/tests/architecture/
test_dependency_rules.py (C04-001, scopé à core/src/ uniquement) à tout
le dépôt, et le mécanisme partiel déjà présent dans 4 modules
(verifier_aucun_import_domaine, M5/M8/M9/M10) qui ignorait M7-marketing
(13 paquets plats sans préfixe mNN_, non couverts par le patron ^m\\d+_).

3 classes de violation détectées, toutes en AST pur (jamais un scan
texte/regex sur le fichier — un chemin d'un autre module cité dans un
COMMENTAIRE ou une docstring n'est jamais une violation, ast.Constant ne
voit jamais un commentaire) :

  IMPORT_CROSS_MODULE — un import ABSOLU (jamais relatif : niveau > 0
    est interne par construction) d'un nom de paquet appartenant à un
    AUTRE module M que celui du fichier source (ou n'importe quel
    module M si le fichier source est hors de Modules M/, ex. core/).

  CHEMIN_PRIVE_CROSS_MODULE — un littéral de chaîne référençant
    `Modules M/<Mx>/...` où Mx diffère du module propriétaire du
    fichier, ET où le chemin NE pointe PAS vers `contracts/` (public,
    YAML gelé versionné, 0 fichier .py mesuré — cf. docstring du
    fichier de test). `<module>/contrats.py` dans src/ N'EST PAS un
    contrat exporté, c'est un VALIDATEUR interne du contrat YAML gelé
    (piège de vocabulaire, revue d'architecture AVANT code).

  SQL_TABLE_PRIVEE — un littéral de requête SQL référençant une table
    qualifiée par le nom d'un paquet d'un AUTRE module (`FROM
    m2_revenue_crm.leads`). ÉCART SOURCÉ DOCUMENTÉ EN CLAIR (mesure
    exhaustive, subagent architecte) : ce dépôt ne contient AUJOURD'HUI
    aucun SQL (0 occurrence de sqlite3/SELECT/INSERT INTO/CREATE
    TABLE/.execute(/cursor( sur tout *.py) — ce détecteur existe et est
    prouvé mordant sur fixture synthétique
    (test_detecte_un_acces_sql_table_privee_sur_fixture_synthetique),
    mais son résultat sur le dépôt réel est un ENSEMBLE VIDE, déclaré
    et testé comme tel (test_cr_er_le_linter_d_isolation_intermodule_
    global_2) — jamais confondu avec « non implémenté » (même
    discipline que core/dependency-rules.toml pour import-linter, et
    [layers.application] pour C04-001, cf. piège déjà audité
    CAND-CA05-0004 : ne jamais laisser un ensemble vide non déclaré).

Exclusions de périmètre nommées et mesurées (jamais devinées) :
  - audit/ : cartographies légitimes référençant tous les modules par
    construction (ex. path_and_authority_map.py) — EXCLU DE TOUT SCAN.
  - reviews/ : archives de preuve de revues passées (verdicts scellés +
    scripts de mutation-proof historiques, ex. reviews/M3-S002-r11/
    mut.py) — artefacts de PREUVE, jamais du code exécuté en production
    ni en CI — EXCLU DE TOUT SCAN.
  - tests/e2e/ : harnais e2e dépôt légitime (ex. _harness.py construit
    un chemin vers Modules M/M7-marketing/src/brand pour ses propres
    besoins de test) — EXCLU DE TOUT SCAN.
  - core/tests/**, Modules M/**/tests/** : exclus UNIQUEMENT des
    détecteurs CHEMIN_PRIVE_CROSS_MODULE et SQL_TABLE_PRIVEE (PAS de
    IMPORT_CROSS_MODULE, qui reste actif). Mesuré en tour 1 d'écriture
    de ce module : les fichiers de test contiennent SYSTÉMATIQUEMENT des
    chaînes littérales synthétiques ressemblant à des chemins de module
    (données de fixture, ex. core/tests/authority/test_authority_
    registry.py passe read_port="Modules M/X-module/src" comme DONNÉE
    DE TEST, jamais un accès filesystem réel ; core/tests/bootstrap/
    test_ci_contract.py simule le CONTENU d'un fichier CI en chaîne).
    Un cas RÉEL et LÉGITIME existe aussi (Modules M/M3-estimation/tests/
    test_validation_entrees.py lit le SOURCE de M2 par AST pour prouver
    l'absence de dérive d'une constante copiée — mécanisme de test
    scellé et documenté, hors périmètre de correction de C04-002 qui
    n'autorise aucune modification de logique métier M1-M10). Le risque
    d'isolation qu'un linter doit surveiller est le COUPLAGE EN
    PRODUCTION (src/), jamais un test qui LIT en lecture seule pour se
    prouver correct.

Interfaces exactes du spec (tasks/C04-002.md) :
  scan_module_isolation(repo: Path) -> list[Violation]
"""
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_MODULES_M_DIR = "Modules M"
_EXCLUSIONS_PREFIXES = ("audit/", "reviews/", "tests/e2e/")


def _est_zone_test(rel_str: str) -> bool:
    """Vrai si le fichier est sous core/tests/ ou Modules M/<Mx>/tests/
    — exclu des détecteurs CHEMIN_PRIVE_CROSS_MODULE et SQL_TABLE_PRIVEE
    uniquement (cf. docstring de module), jamais de IMPORT_CROSS_MODULE."""
    if rel_str.startswith("core/tests/"):
        return True
    parts = rel_str.split("/")
    return len(parts) >= 3 and parts[0] == _MODULES_M_DIR and "tests" in parts

# Capture "Modules M/<Nom-Module>/<reste-du-chemin>" — le nom de module
# suit le patron réel mesuré (ex. M2-revenue-crm, M10-memoire).
_MOTIF_CHEMIN_MODULE = re.compile(r"Modules M/([A-Za-z0-9]+-[A-Za-z0-9-]+)/(\S*)")

# Capture "FROM <table>." / "JOIN <table>." / "UPDATE <table>." /
# "INTO <table>." — qualification de table par nom de schéma/paquet,
# insensible à la casse SQL.
_MOTIF_TABLE_SQL_QUALIFIEE = re.compile(
    r"(?:FROM|JOIN|UPDATE|INTO)\s+([A-Za-z_][A-Za-z0-9_]*)\.", re.IGNORECASE
)


@dataclass(frozen=True)
class Violation:
    """Une violation d'isolation intermodule détectée. Frozen : une
    violation est un FAIT mesuré, jamais mutable après coup."""

    kind: str
    fichier: str
    module_source: str
    module_cible: str
    detail: str

    def __post_init__(self) -> None:
        if self.kind not in ("IMPORT_CROSS_MODULE", "CHEMIN_PRIVE_CROSS_MODULE", "SQL_TABLE_PRIVEE"):
            raise ValueError(f"Violation.kind inconnu : {self.kind!r}")
        for champ, valeur in (("fichier", self.fichier), ("detail", self.detail)):
            if not valeur.strip():
                raise ValueError(f"Violation.{champ} ne peut pas être vide")


def charger_map_modules_m(repo: Path) -> dict[str, str]:
    """Map nom-de-paquet-importable -> nom-de-module-propriétaire.
    Énumération dynamique DEPUIS LE DISQUE, jamais un pattern deviné —
    9 modules mNN_* (un paquet chacun) + M7-marketing (13 paquets PLATS,
    ads/aeo/attribution/brand/competitive/content/reputation/roi/seo/
    site/social/utm/workflows, un seul avec __init__.py) = 22 entrées."""
    m: dict[str, str] = {}
    modules_dir = repo / _MODULES_M_DIR
    for src_dir in sorted(modules_dir.glob("*/src")):
        module_name = src_dir.parent.name
        for entree in src_dir.iterdir():
            if entree.is_dir() and not entree.name.startswith((".", "__")):
                m[entree.name] = module_name
            elif entree.is_file() and entree.suffix == ".py" and entree.stem != "__init__":
                m[entree.stem] = module_name
    return m


def fichiers_a_scanner(repo: Path) -> list[Path]:
    """Tous les .py du dépôt, hors exclusions de périmètre nommées."""
    fichiers: list[Path] = []
    for p in sorted(repo.rglob("*.py")):
        rel_str = str(p.relative_to(repo))
        if rel_str.startswith(".git/"):
            continue
        if any(rel_str.startswith(prefixe) for prefixe in _EXCLUSIONS_PREFIXES):
            continue
        fichiers.append(p)
    return fichiers


def _module_proprietaire_du_fichier(fichier: Path, repo: Path) -> str | None:
    """Nom du module M si le fichier est sous Modules M/<Mx>/, sinon
    None (fichier hors de tout module M — core/, scripts/, etc.)."""
    parts = fichier.relative_to(repo).parts
    if len(parts) >= 2 and parts[0] == _MODULES_M_DIR:
        return parts[1]
    return None


def _imports_absolus_top_level(arbre: ast.AST) -> set[str]:
    """Noms de premier niveau importés de façon ABSOLUE (level == 0) —
    un import relatif est interne au module courant par construction,
    jamais un accès cross-module au sens de ce linter."""
    noms: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                noms.add(alias.name.split(".")[0])
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0:
            if noeud.module:
                noms.add(noeud.module.split(".")[0])
    return noms


def _detecter_imports_cross_module(
    arbre: ast.AST, fichier: Path, module_source: str | None, map_modules: dict[str, str]
) -> list[Violation]:
    violations: list[Violation] = []
    # Soustraire stdlib AVANT de comparer à map_modules : élimine par
    # construction la collision "site" (module M7-marketing ET paquet
    # stdlib) sans avoir besoin d'une exception nommée séparée.
    imports_hors_stdlib = _imports_absolus_top_level(arbre) - sys.stdlib_module_names
    for nom in sorted(imports_hors_stdlib):
        module_cible = map_modules.get(nom)
        if module_cible and module_cible != module_source:
            violations.append(
                Violation(
                    kind="IMPORT_CROSS_MODULE",
                    fichier=str(fichier),
                    module_source=module_source or "(hors Modules M/)",
                    module_cible=module_cible,
                    detail=f"import absolu {nom!r} appartient à {module_cible}, pas à {module_source or 'ce fichier'}",
                )
            )
    return violations


def _noeuds_docstring(arbre: ast.AST) -> set[int]:
    """id() des ast.Constant qui sont des DOCSTRINGS (premier statement
    du corps d'un Module/ClassDef/FunctionDef/AsyncFunctionDef) — jamais
    une valeur de programme réelle. Une docstring peut légitimement
    documenter/citer un exemple de chemin d'un autre module sans que ce
    soit un accès réel : piège AUTO-RÉFÉRENTIEL découvert sur ce fichier
    lui-même (check_module_isolation.py cite « Modules M/M7-marketing/
    src/brand » dans sa propre docstring pour documenter l'exclusion
    tests/e2e/ — sans cette garde, le linter se signalerait lui-même
    comme violateur)."""
    ids: set[int] = set()
    porteurs_de_corps = [arbre] + [
        n for n in ast.walk(arbre)
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for noeud in porteurs_de_corps:
        corps = getattr(noeud, "body", None)
        if (
            corps
            and isinstance(corps[0], ast.Expr)
            and isinstance(corps[0].value, ast.Constant)
            and isinstance(corps[0].value.value, str)
        ):
            ids.add(id(corps[0].value))
    return ids


def _detecter_chemins_prives_cross_module(
    arbre: ast.AST, fichier: Path, module_source: str | None, docstrings: set[int]
) -> list[Violation]:
    violations: list[Violation] = []
    for noeud in ast.walk(arbre):
        if not (isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)):
            continue
        if id(noeud) in docstrings:
            continue
        match = _MOTIF_CHEMIN_MODULE.search(noeud.value)
        if not match:
            continue
        module_cible, reste = match.group(1), match.group(2)
        if module_cible == module_source:
            continue
        if reste.startswith("contracts/") or reste == "contracts":
            continue
        violations.append(
            Violation(
                kind="CHEMIN_PRIVE_CROSS_MODULE",
                fichier=str(fichier),
                module_source=module_source or "(hors Modules M/)",
                module_cible=module_cible,
                detail=f"référence au chemin privé {noeud.value!r}",
            )
        )
    return violations


def _detecter_sql_table_privee(
    arbre: ast.AST, fichier: Path, module_source: str | None, map_modules: dict[str, str], docstrings: set[int]
) -> list[Violation]:
    violations: list[Violation] = []
    for noeud in ast.walk(arbre):
        if not (isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)):
            continue
        if id(noeud) in docstrings:
            continue
        for match in _MOTIF_TABLE_SQL_QUALIFIEE.finditer(noeud.value):
            prefixe = match.group(1)
            module_cible = map_modules.get(prefixe)
            if module_cible and module_cible != module_source:
                violations.append(
                    Violation(
                        kind="SQL_TABLE_PRIVEE",
                        fichier=str(fichier),
                        module_source=module_source or "(hors Modules M/)",
                        module_cible=module_cible,
                        detail=(
                            f"requête SQL référence {match.group(0)!r} — table qualifiée par "
                            f"{prefixe!r}, appartenant à {module_cible}"
                        ),
                    )
                )
    return violations


def scan_module_isolation(repo: Path) -> list[Violation]:
    """Interface exacte du spec (tasks/C04-002.md, section Interfaces).
    Scanne TOUT le dépôt (hors exclusions nommées) et retourne la liste
    complète des violations d'isolation intermodule détectées."""
    repo = Path(repo).resolve()
    map_modules = charger_map_modules_m(repo)
    violations: list[Violation] = []
    for fichier in fichiers_a_scanner(repo):
        module_source = _module_proprietaire_du_fichier(fichier, repo)
        rel_str = str(fichier.relative_to(repo))
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))
        except (SyntaxError, UnicodeDecodeError):
            # Un fichier illisible/mal formé n'est pas un cas d'isolation
            # — hors périmètre de ce linter (un autre gate le couvrirait).
            continue
        # IMPORT_CROSS_MODULE reste actif PARTOUT (un import est toujours
        # un accès réel, test ou pas). CHEMIN_PRIVE/SQL sont exclus en
        # zone test (cf. docstring de module : fixtures synthétiques).
        violations.extend(_detecter_imports_cross_module(arbre, fichier, module_source, map_modules))
        if not _est_zone_test(rel_str):
            docstrings = _noeuds_docstring(arbre)
            violations.extend(_detecter_chemins_prives_cross_module(arbre, fichier, module_source, docstrings))
            violations.extend(_detecter_sql_table_privee(arbre, fichier, module_source, map_modules, docstrings))
    return violations


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    violations = scan_module_isolation(repo)
    if not violations:
        print("OK — 0 violation d'isolation intermodule détectée.")
        return 0
    for v in violations:
        print(f"VIOLATION {v.kind}: {v.fichier} ({v.module_source} -> {v.module_cible}) — {v.detail}", file=sys.stderr)
    print(f"{len(violations)} violation(s) d'isolation intermodule détectée(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
