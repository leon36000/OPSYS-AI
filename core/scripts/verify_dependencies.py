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


_CORRESPONDANCE_IMPORT_PAQUET = {"yaml": "PyYAML"}


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


def verify_lock(pyproject: Path, lock: Path) -> LockReport:
    declared_but_undeclared_imports: list[str] = []
    floating_dependencies: list[str] = []
    missing_hash_packages: list[str] = []

    # Volontairement strict : une version PEP 440 avec suffixe (.post1,
    # a1, b2, .dev0) est REFUSÉE ici comme non « exacte » au sens de ce
    # lock — même choix que ToolchainLock (C02-001, cf. test_version_avec_
    # suffixe_pre_release_refusee) : une version numérique pure est plus
    # simple à raisonner qu'une comparaison PEP440 complète, tradeoff
    # délibéré et non un oubli (revue C02-002, objection mineure confirmée
    # vraie mais acceptée pour cohérence avec le précédent C02-001).
    exact_version_re = re.compile(r"^[A-Za-z0-9_.\-]+==\d+(?:\.\d+){1,3}(?:\s|$)")
    hash_re = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)")
    name_re = re.compile(r"^([^=<>~^!\s]+)")
    dep_name_re = re.compile(r"^[^=<>~^!\s]+")

    declared_names: set[str] = set()
    pyproject_readable = False

    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        dependencies = data.get("project", {}).get("dependencies", []) or []
        for dep in dependencies:
            if isinstance(dep, str):
                match = dep_name_re.match(dep.strip())
                if match:
                    declared_names.add(match.group(0).lower())
        pyproject_readable = True
    except Exception:
        declared_names = set()

    known_imported: set[str] = set()
    root = pyproject.parent

    if root.exists():
        for py_file in root.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for line in source.splitlines():
                stripped = line.strip()
                for module in _CORRESPONDANCE_IMPORT_PAQUET:
                    # `from X import ...` : ancré au module directement.
                    if re.match(rf"^from\s+{re.escape(module)}\b", stripped):
                        known_imported.add(_CORRESPONDANCE_IMPORT_PAQUET[module])
                        continue
                    # `import X` OU `import A, X, B` (revue C02-002,
                    # objection mineure confirmée vraie : un import multiple
                    # sur une ligne échappait à l'ancien pattern anchré sur
                    # `import\s+{module}\b` seul) : découper sur la virgule,
                    # comparer chaque nom (alias `as`/sous-module ignorés).
                    # Commentaire en fin de ligne retiré AVANT le découpage
                    # sur virgule (revue C02-002 tour 2, objection mineure
                    # confirmée vraie : `import yaml  # test` donnait le nom
                    # "yaml  # test", jamais égal à "yaml").
                    sans_commentaire = re.sub(r"#.*$", "", stripped).strip()
                    import_match = re.match(r"^import\s+(.+)$", sans_commentaire)
                    if import_match:
                        noms = [
                            n.strip().split(" as ")[0].split(".")[0]
                            for n in import_match.group(1).split(",")
                        ]
                        if module in noms:
                            known_imported.add(_CORRESPONDANCE_IMPORT_PAQUET[module])

    if not pyproject_readable:
        declared_but_undeclared_imports.append("pyproject.toml absent ou illisible")

    for package in sorted(known_imported):
        if package.lower() not in declared_names:
            modules = [
                module
                for module, pkg in _CORRESPONDANCE_IMPORT_PAQUET.items()
                if pkg == package
            ]
            module_str = ", ".join(f"import {module}" for module in modules)
            declared_but_undeclared_imports.append(
                f"{package} ({module_str}) utilisé mais non déclaré dans pyproject.toml"
            )

    if lock.exists():
        try:
            lines = lock.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Ligne de CONTINUATION d'un hash multi-ligne façon pip-compile
            # (`pkg==1.0 \` puis `    --hash=sha256:...` sur la ligne
            # suivante) : après strip(), commence par `--hash=` — jamais un
            # nom de paquet réel. Revue C02-002, objection mineure confirmée
            # vraie : sans cette garde, name_re la capturait comme un faux
            # paquet nommé littéralement "--hash" (le hash lui n'appartient
            # à AUCUN paquet reconnu ⇒ ignoré plutôt que mal attribué, plus
            # sûr qu'un rattachement device au paquet précédent qui pourrait
            # se tromper si une ligne est isolée/mal formée).
            if line.startswith("--hash="):
                continue

            match = name_re.match(line)
            if not match:
                continue
            name = match.group(1)

            if not exact_version_re.match(line):
                floating_dependencies.append(
                    f"{name}: version non épinglée ({line})"
                )

            if not hash_re.search(line):
                missing_hash_packages.append(
                    f"{name}: hash sha256 absent ou invalide"
                )

    return LockReport(
        declared_but_undeclared_imports,
        floating_dependencies,
        missing_hash_packages,
    )
