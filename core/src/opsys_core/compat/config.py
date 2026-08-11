"""Shim de compatibilité pour config/ existant (C04-003).

Encapsule `config.settings.load_settings` SANS déplacer ni copier son
code. Le `SecretProvider` est lié au CONSTRUCTEUR de l'adapter, jamais
passé par appel à `load()` — pas une préférence de style : le provider
est STATEFUL (`EnvSecretProvider._cache` accumule les secrets déjà
résolus, cf. `config/vault.py`), et c'est ce cache que
`load_settings`/`safe_traceback` consomment pour rédiger les secrets
des ERREURS FUTURES. Un provider neuf à chaque appel repartirait avec
un cache vide : les secrets résolus lors d'un chargement précédent ne
seraient plus caviardés dans les erreurs du chargement suivant — une
régression de sécurité mesurable, pas une préférence.

Limitations du code encapsulé, assumées et documentées (jamais
corrigées en silence par ce shim — cf. docs/core/COMPATIBILITY-SHIMS.md
pour le détail complet) :
  - `FileNotFoundError` est levée par `load_settings` HORS de son bloc
    try/except qui rédige les autres exceptions : elle traverse ce
    shim TELLE QUELLE, jamais reclassée en `SettingsError`. La
    reclasser masquerait une asymétrie déjà présente dans le code
    hérité — hors périmètre de cette tâche (« ajouter adapters sans
    déplacer l'ancien code »).
  - Schéma figé à 4 champs (mode/endpoint/timeout/litellm_key) : toute
    autre clé YAML est silencieusement ignorée par le code hérité.
  - Un seul secret résolu, nom `litellm_key` codé en dur.
"""
from __future__ import annotations

from pathlib import Path

from config.settings import Settings, load_settings
from config.vault import SecretProvider


class LegacyConfigAdapter:
    """Encapsule un `SecretProvider` + `load_settings` existants
    derrière une surface unique `load(yaml_path)`."""

    def __init__(self, provider: SecretProvider) -> None:
        self._provider = provider

    def load(self, yaml_path: Path) -> Settings:
        return load_settings(yaml_path, self._provider)
