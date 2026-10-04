from __future__ import annotations

import json
from pathlib import Path

from opsys import openclaw
from opsys.departements import charger_departements


def test_config_opsys_marque_tous_les_agents_et_sandbox_exec_obligatoire(tmp_path):
    paliers = {
        "rapide": {"provider": "anthropic", "model": "model-fast"},
        "standard": {"provider": "anthropic", "model": "model-standard"},
        "fort": {"provider": "anthropic", "model": "model-strong"},
        "local": {"provider": "custom", "model": "model-local", "base_url": "http://localhost/v1"},
    }
    environ = {
        "OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1",
        "OPSYS_EMBEDDINGS_MODELE": "embedding-test",
    }
    fichiers = openclaw.generer(
        charger_departements(),
        tmp_path,
        paliers,
        environ=environ,
    )
    agents = json.loads(fichiers["agents"].read_text(encoding="utf-8"))
    outils = json.loads(fichiers["tools"].read_text(encoding="utf-8"))

    assert agents["defaults"]["opsysIsolation"] == {"exec": "sandbox-required"}
    assert agents["defaults"]["sandbox"] == {
        "mode": "all",
        "backend": "docker",
        "scope": "session",
        "workspaceAccess": "none",
        "docker": {
            "network": "none",
            "readOnlyRoot": True,
            "capDrop": ["ALL"],
            "binds": [],
        },
    }
    assert outils["exec"]["host"] == "sandbox"
    assert agents["entries"]
    assert all(
        entree["opsysIsolation"] == {"exec": "sandbox-required"}
        for entree in agents["entries"].values()
    )


def test_generation_refuse_workspace_qui_recouvre_sqlite_ou_secrets(tmp_path):
    paliers = {
        "rapide": {"provider": "anthropic", "model": "model-fast"},
        "standard": {"provider": "anthropic", "model": "model-standard"},
        "fort": {"provider": "anthropic", "model": "model-strong"},
        "local": {"provider": "custom", "model": "model-local", "base_url": "http://localhost/v1"},
    }
    env = {
        "OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1",
        "OPSYS_EMBEDDINGS_MODELE": "embedding-test",
        "OPSYS_HOME": str(tmp_path / "instance"),
        "OPSYS_BASE_URL": f"sqlite:///{tmp_path / 'instance' / 'opsys.db'}",
    }
    secret_root = Path(env["OPSYS_HOME"]) / "secrets"
    secret_root.mkdir(parents=True)

    try:
        openclaw.generer(
            charger_departements(),
            tmp_path / "config",
            paliers,
            racine_espaces=str(secret_root),
            environ=env,
        )
    except ValueError as erreur:
        assert "workspace OPSYS recouvre" in str(erreur)
    else:
        raise AssertionError("workspace recouvrant OPSYS_HOME/secrets accepté")


def test_generation_refuse_un_workspace_agent_symlink_vers_secrets_avant_ecriture(tmp_path):
    paliers = {
        "rapide": {"provider": "anthropic", "model": "model-fast"},
        "standard": {"provider": "anthropic", "model": "model-standard"},
        "fort": {"provider": "anthropic", "model": "model-strong"},
        "local": {"provider": "custom", "model": "model-local", "base_url": "http://localhost/v1"},
    }
    dep_id = next(iter(charger_departements()))
    config = tmp_path / "config"
    secrets = tmp_path / "instance" / "secrets"
    secrets.mkdir(parents=True)
    workspace = config / "opsys" / "espaces" / dep_id
    workspace.parent.mkdir(parents=True)
    workspace.symlink_to(secrets, target_is_directory=True)
    environ = {
        "OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1",
        "OPSYS_EMBEDDINGS_MODELE": "embedding-test",
        "OPSYS_HOME": str(tmp_path / "instance"),
    }

    try:
        openclaw.generer(charger_departements(), config, paliers, environ=environ)
    except ValueError as erreur:
        assert "workspace OPSYS recouvre" in str(erreur)
    else:
        raise AssertionError("workspace agent symlink vers secrets accepté")

    assert not (config / "opsys" / "agents.json").exists()
