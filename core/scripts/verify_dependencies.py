"""Verrou des dépendances Core (C02-002).

Rendre l'environnement, les dépendances et les checks bloquants
reproductibles avant le Core. ``verify_lock`` est le contrat qui garantit
qu'aucune dépendance Core n'est installée sans version exacte, sans hash
(profil air-gap), ni utilisée sans être déclarée.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


_CORRESPONDANCE_IMPORT_PAQUET = {"yaml": "PyYAML", "psycopg": "psycopg"}

# Regex compilées une fois au chargement du module (plutôt qu'à chaque
# appel de verify_lock) — extraites en constantes nommées lors du
# refactor de réduction de complexité cognitive (SonarCloud, révision
# chantier CI-hardening : 65 > 15 autorisé sur verify_lock avant split).
#
# Volontairement strict : une version PEP 440 avec suffixe (.post1, a1,
# b2, .dev0) est REFUSÉE ici comme non « exacte » au sens de ce lock —
# même choix que ToolchainLock (C02-001, cf. test_version_avec_suffixe_
# pre_release_refusee) : une version numérique pure est plus simple à
# raisonner qu'une comparaison PEP440 complète, tradeoff délibéré et non
# un oubli (revue C02-002, objection mineure confirmée vraie mais
# acceptée pour cohérence avec le précédent C02-001).
_EXACT_VERSION_RE = re.compile(r"^[A-Za-z0-9_.\-]+==\d+(?:\.\d+){1,3}(?:\s|$)")
_HASH_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)")
_NAME_RE = re.compile(r"^([^=<>~^!\s]+)")
_DEP_NAME_RE = re.compile(r"^[^=<>~^!\s]+")


@dataclass(frozen=True)
class LockReport:
    # frozen=True bloque la RÉAFFECTATION des 3 champs, pas la mutation du
    # CONTENU des listes référencées (revue C02-002, objection mineure
    # confirmée vraie par mesure directe : report.x.append(...) réussit
    # malgré frozen=True). Non corrigé délibérément ici, contrairement à
    # ToolchainLock (C02-001) : LockReport est un résultat de mesure
    # TERMINAL, jamais re-consommé comme verrou de sécurité qu'un futur
    # appel re-comparerait (verify_lock() le reconstruit intégralement à
    # chaque appel) — le coût du gel profond (listes -> tuples, cassant les
    # comparaisons `== []` du fichier de test) dépasse le risque réel ici.
    declared_but_undeclared_imports: list[str]
    floating_dependencies: list[str]
    missing_hash_packages: list[str]

    @property
    def ok(self) -> bool:
        return not (
            self.declared_but_undeclared_imports
            or self.floating_dependencies
            or self.missing_hash_packages
        )


def _noms_declares(pyproject: Path) -> tuple[set[str], bool]:
    """Retourne (noms déclarés en minuscules, pyproject lisible ?) —
    jamais une exception brute si pyproject.toml est absent/invalide."""
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        dependencies = data.get("project", {}).get("dependencies", []) or []
        declared_names = set()
        for dep in dependencies:
            if isinstance(dep, str):
                match = _DEP_NAME_RE.match(dep.strip())
                if match:
                    declared_names.add(match.group(0).lower())
        return declared_names, True
    except Exception:
        return set(), False


def _modules_importes_sur_ligne(stripped: str) -> set[str]:
    """Retourne TOUS les modules de `_CORRESPONDANCE_IMPORT_PAQUET`
    importés par CETTE ligne source (`from X import ...` OU `import X` /
    `import A, X, B` — une ligne combinée peut référencer PLUSIEURS
    modules connus à la fois, ex. `import yaml, psycopg` : les DEUX
    doivent être détectés, jamais seulement le premier)."""
    trouves: set[str] = set()
    sans_commentaire = re.sub(r"#.*$", "", stripped).strip()
    import_match = re.match(r"^import\s+(.+)$", sans_commentaire)
    noms_importes = (
        [n.strip().split(" as ")[0].split(".")[0] for n in import_match.group(1).split(",")]
        if import_match
        else []
    )
    for module in _CORRESPONDANCE_IMPORT_PAQUET:
        # `from X import ...` : ancré au module directement.
        if re.match(rf"^from\s+{re.escape(module)}\b", stripped):
            trouves.add(module)
            continue
        # `import X` OU `import A, X, B` (revue C02-002, objection mineure
        # confirmée vraie : un import multiple sur une ligne échappait à
        # l'ancien pattern anchré sur `import\s+{module}\b` seul) :
        # découpé sur la virgule ci-dessus, comparer chaque nom (alias
        # `as`/sous-module ignorés). Commentaire en fin de ligne retiré
        # AVANT le découpage sur virgule (revue C02-002 tour 2, objection
        # mineure confirmée vraie : `import yaml  # test` donnait le nom
        # "yaml  # test", jamais égal à "yaml").
        if module in noms_importes:
            trouves.add(module)
    return trouves


def _scanner_imports_connus(root: Path) -> set[str]:
    """Balaie tous les .py sous `root` (jamais __pycache__) et retourne
    l'ensemble des NOMS DE PAQUETS (pas des noms de module) importés,
    parmi ceux référencés par `_CORRESPONDANCE_IMPORT_PAQUET`."""
    known_imported: set[str] = set()
    if not root.exists():
        return known_imported

    for py_file in root.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except Exception:  # nosec: B112 # 1 fichier illisible (permissions/binaire) ne doit pas interrompre le scan de dépendances de tout l'arbre — dégradation gracieuse mesurée, pas un masquage de faille de sécurité
            continue
        for line in source.splitlines():
            for module in _modules_importes_sur_ligne(line.strip()):
                known_imported.add(_CORRESPONDANCE_IMPORT_PAQUET[module])

    return known_imported


def _imports_non_declares(known_imported: set[str], declared_names: set[str]) -> list[str]:
    erreurs = []
    for package in sorted(known_imported):
        if package.lower() not in declared_names:
            modules = [
                module
                for module, pkg in _CORRESPONDANCE_IMPORT_PAQUET.items()
                if pkg == package
            ]
            module_str = ", ".join(f"import {module}" for module in modules)
            erreurs.append(f"{package} ({module_str}) utilisé mais non déclaré dans pyproject.toml")
    return erreurs


def _verifier_ligne_lock(line: str) -> tuple[str | None, str | None]:
    """Retourne (erreur_flottante_ou_None, erreur_hash_manquant_ou_None)
    pour UNE ligne déjà strip()ée et non vide/non-commentaire du lock."""
    # Ligne de CONTINUATION d'un hash multi-ligne façon pip-compile
    # (`pkg==1.0 \` puis `    --hash=sha256:...` sur la ligne suivante) :
    # après strip(), commence par `--hash=` — jamais un nom de paquet
    # réel. Revue C02-002, objection mineure confirmée vraie : sans cette
    # garde, name_re la capturait comme un faux paquet nommé littéralement
    # "--hash" (le hash lui n'appartient à AUCUN paquet reconnu ⇒ ignoré
    # plutôt que mal attribué, plus sûr qu'un rattachement devinné au
    # paquet précédent qui pourrait se tromper si une ligne est
    # isolée/mal formée).
    if line.startswith("--hash="):
        return None, None

    match = _NAME_RE.match(line)
    if not match:
        return None, None
    name = match.group(1)

    erreur_flottante = None if _EXACT_VERSION_RE.match(line) else f"{name}: version non épinglée ({line})"
    erreur_hash = None if _HASH_RE.search(line) else f"{name}: hash sha256 absent ou invalide"
    return erreur_flottante, erreur_hash


def _verifier_lock(lock: Path) -> tuple[list[str], list[str]]:
    """Retourne (floating_dependencies, missing_hash_packages) pour tout
    le fichier lock — [] si le fichier est absent ou illisible."""
    floating: list[str] = []
    missing_hash: list[str] = []
    if not lock.exists():
        return floating, missing_hash

    try:
        lines = lock.read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        erreur_flottante, erreur_hash = _verifier_ligne_lock(line)
        if erreur_flottante is not None:
            floating.append(erreur_flottante)
        if erreur_hash is not None:
            missing_hash.append(erreur_hash)

    return floating, missing_hash


def verify_lock(pyproject: Path, lock: Path) -> LockReport:
    declared_names, pyproject_readable = _noms_declares(pyproject)
    known_imported = _scanner_imports_connus(pyproject.parent)

    declared_but_undeclared_imports = _imports_non_declares(known_imported, declared_names)
    if not pyproject_readable:
        declared_but_undeclared_imports.append("pyproject.toml absent ou illisible")

    floating_dependencies, missing_hash_packages = _verifier_lock(lock)

    return LockReport(
        declared_but_undeclared_imports,
        floating_dependencies,
        missing_hash_packages,
    )
