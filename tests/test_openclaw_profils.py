from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agents_base_qa import provisionner_base_qa

from opsys import agents, identite, openclaw
from opsys.departements import charger_departements


def _spec(deps, ident: str) -> dict:
    dep = deps["m03-estimation"]
    return {
        "id": ident,
        "departement": dep.id,
        "responsabilite": "Préparer des estimations vérifiables.",
        "palier_modele": "standard",
        "outils": [dep.charger_outils()[0].nom],
        "budget_jour": 10000,
        "budget_mois": 100000,
        "limite_tours": 12,
        "limite_reessais": 2,
        "limite_concurrence": 3,
        "declencheurs": [{"type": "manuel"}],
    }


def test_genere_les_profils_actifs_avec_admission_durable(session, tmp_path):
    deps = charger_departements()
    provisionner_base_qa(session, deps)
    # Le registre valide chaque profil contre le manifeste réel du département.
    with session() as cnx:
        identite.creer_personne(cnx, "profil-admin", "Admin", "test-password-admin-1234", ["admin"])
        inactive = agents.creer(cnx, deps, _spec(deps, "m03-inactive"), par="profil-admin",
                                mutation_id="create-inactive-001")
        active = agents.creer(cnx, deps, _spec(deps, "m03-estimateur"), par="profil-admin",
                              mutation_id="create-active-001")
        second_spec = _spec(deps, "m03-photos")
        second_spec["responsabilite"] = "Évaluer les preuves photographiques et signaler les inconnues."
        second = agents.creer(cnx, deps, second_spec, par="profil-admin",
                              mutation_id="create-active-002")
        active = agents.definir_actif(cnx, active["id"], deps, True, par="profil-admin",
                             mutation_id="activate-active-001", revision_attendue=1)
        second = agents.definir_actif(cnx, second["id"], deps, True, par="profil-admin",
                             mutation_id="activate-active-002", revision_attendue=1)

    paliers = {
        "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        "standard": {"provider": "anthropic", "model": "claude-sonnet-5", "fallbacks": ["rapide"]},
        "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
        "fort": {"provider": "anthropic", "model": "claude-opus-5"},
    }
    files = openclaw.generer(
        deps, tmp_path, paliers,
        environ={"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1",
                 "OPSYS_EMBEDDINGS_MODELE": "bge-m3"},
        contexte_entreprise={"m03-estimation": []},
        cnx_factory=session,
    )
    config = json.loads(files["agents"].read_text(encoding="utf-8"))["entries"]
    assert inactive["id"] not in config
    profile_agent_id = f"opsys-agent-{active['id']}"
    second_agent_id = f"opsys-agent-{second['id']}"
    assert profile_agent_id in config
    assert second_agent_id in config
    assert config[profile_agent_id]["opsysIsolation"] == {"exec": "sandbox-required"}
    assert config[second_agent_id]["opsysIsolation"] == {"exec": "sandbox-required"}
    assert config[profile_agent_id]["opsysRuntimeAdmission"] == {
        "profileId": active["id"], "profileRevision": active["revision"],
    }
    assert config[profile_agent_id]["runtime"] == {"type": "embedded"}
    assert "sessions_spawn" not in config[profile_agent_id]["tools"]["allow"]
    assert config[profile_agent_id]["model"] == {
        "primary": "anthropic/claude-sonnet-5",
        "fallbacks": ["anthropic/claude-haiku-4-5-20251001"],
    }
    assert config[profile_agent_id]["tools"]["allow"] == [
        f"{openclaw.serveur_mcp(deps[active['departement']])}__{active['outils'][0]}"
    ]
    assert all("opsys_runtime_" not in item for item in config[profile_agent_id]["tools"]["allow"])
    assert config[profile_agent_id]["workspace"] != config[second_agent_id]["workspace"]
    assert Path(config[profile_agent_id]["workspace"]).is_absolute()
    assert Path(config[second_agent_id]["workspace"]).is_absolute()
    workspace = tmp_path / config[profile_agent_id]["workspace"].removeprefix("./")
    second_workspace = tmp_path / config[second_agent_id]["workspace"].removeprefix("./")
    assert "Préparer des estimations vérifiables." in (workspace / "SOUL.md").read_text(encoding="utf-8")
    assert "Évaluer les preuves photographiques" in (second_workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert (workspace / "skills").is_dir() and (second_workspace / "skills").is_dir()
    context = json.loads(files["contexte"].read_text(encoding="utf-8"))
    assert profile_agent_id in context["agents"] and second_agent_id in context["agents"]
    assert context["agents"][profile_agent_id]["serveur_contexte"] == "opsys_context_m03-estimation"
    mcp = json.loads(files["mcp"].read_text(encoding="utf-8"))["servers"]
    assert f"opsys_context_{active['id']}" not in mcp
    runtime = mcp[f"opsys_runtime_{active['id']}"]
    assert runtime["url"].endswith(f"/mcp/runtime/{active['id']}")
    assert runtime["headers"] == {"Authorization": "Bearer ${OPSYS_CONTEXT_MCP_JETON}"}
    assert f"opsys_runtime_{second['id']}" in mcp
    denies = json.loads(files["tools"].read_text(encoding="utf-8"))["deny"]
    assert "opsys_context_*__*" in denies
    assert "opsys_runtime_*__*" in denies

    root = Path(__file__).resolve().parents[1]
    tsx = root / "core" / "node_modules" / ".bin" / "tsx"
    if tsx.is_file():
        validator = tmp_path / "validate-agents.ts"
        schema = (root / "core" / "src" / "config" / "zod-schema.agents.ts").as_posix()
        validator.write_text(
            "import { readFileSync } from 'node:fs';\n"
            f"import {{ AgentsSchema }} from {json.dumps(schema)};\n"
            "const raw = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
            "const parsed = AgentsSchema.safeParse(raw);\n"
            "if (!parsed.success) { process.stderr.write(JSON.stringify(parsed.error.issues)); process.exit(1); }\n",
            encoding="utf-8",
        )
        validation = subprocess.run(
            [str(tsx), str(validator), str(files["agents"])],
            cwd=root / "core", check=False, capture_output=True, text=True,
        )
        assert validation.returncode == 0, validation.stderr
