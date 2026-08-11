"""Shims de compatibilité (C04-003) — encapsulent authz/ et config/
existants SANS déplacer l'ancien code, en résorption PARTIELLE de
l'exception `legacy_pre_core` de core/dependency-rules.toml (authz/ et
config/ seulement ; auth/ — admin_gate.py, totp.py — reste hors
périmètre, cf. docs/core/COMPATIBILITY-SHIMS.md).

Volontairement réduit à cette docstring : AUCUN import, AUCUN
ré-export. `config/settings.py` importe PyYAML — si ce module
ré-exportait `compat.config`, `import opsys_core` (le noyau
constitutionnel, aujourd'hui stdlib pur) hériterait transitivement
d'une dépendance PyPI à l'import. Chaque appelant importe explicitement
`opsys_core.compat.authz` ou `opsys_core.compat.config`, jamais
`opsys_core.compat` seul pour ses effets de bord.

Ce fichier existe pour la cohérence avec les autres paquets de
opsys_core/ (ports/, authority/, status/ ont tous un __init__.py) —
PAS pour éviter une collision de nom de module mypy : mesuré
(mypy --ignore-missing-imports core/, argv exact du gate C02-004,
mypy 2.1.0, aucune config namespace_packages dans ce dépôt), un
répertoire sans __init__.py est traité comme un namespace package PEP
420 implicite et ne collisionne PAS avec le paquet top-level authz/ ou
config/ — l'hypothèse inverse, un temps envisagée en revue
d'architecture, a été réfutée avant ce commit.
"""
from __future__ import annotations
