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
                for module in _CORRESPONDANCE_IMPORT_PAQUET:
                    pattern = rf"^\s*(?:import\s+{re.escape(module)}|from\s+{re.escape(module)})\b"
                    if re.search(pattern, line):
                        known_imported.add(_CORRESPONDANCE_IMPORT_PAQUET[module])
                        break

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
