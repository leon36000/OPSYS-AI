from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from agents_base_qa import provisionner_base_qa

from opsys import agents, identite, openclaw
from opsys.departements import charger_departements


@pytest.fixture
def configuration_politique_sandbox(session, tmp_path):
    """Real generated fragments, including two durable configurable profiles."""
    deps = charger_departements()
    provisionner_base_qa(session, deps)
    outils_m3 = [outil.nom for outil in deps["m03-estimation"].charger_outils()]
    assert len(outils_m3) >= 2
    with session() as cnx:
        identite.creer_personne(cnx, "sandbox-admin", "Admin fictif", "fictif-password-1234", ["admin"])
        for ident, outils in [("m03-limite", outils_m3[:1]), ("m03-sans-outils", [])]:
            profil = agents.creer(
                cnx, deps, {
                    "id": ident, "departement": "m03-estimation",
                    "responsabilite": "Préparer une estimation fictive dans la portée déclarée.",
                    "palier_modele": "standard", "outils": outils,
                    "budget_jour": 10000, "budget_mois": 100000,
                    "limite_tours": 12, "limite_reessais": 2, "limite_concurrence": 1,
                    "declencheurs": [{"type": "manuel"}],
                }, par="sandbox-admin", mutation_id=f"create-{ident}",
            )
            agents.definir_actif(
                cnx, ident, deps, True, par="sandbox-admin",
                mutation_id=f"activate-{ident}", revision_attendue=profil["revision"],
            )
    paliers = {
        nom: {"provider": "custom", "model": "modele-fictif", "base_url": "http://127.0.0.1:1/v1"}
        for nom in ("rapide", "standard", "fort", "local")
    }
    fichiers = openclaw.generer(
        deps, tmp_path, paliers, cnx_factory=session,
        environ={"OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:2/v1", "OPSYS_EMBEDDINGS_MODELE": "fictif"},
    )
    return {
        "config": {
            cle: json.loads(fichiers[cle].read_text(encoding="utf-8"))
            for cle in ("agents", "tools", "mcp")
        },
        "names": {
            "public": "opsys_m1__m1_ouvrir_conversation",
            "internal": f"opsys_m2__{deps['m02-revenue-crm'].charger_outils()[0].nom}",
            "custom": f"opsys_m3__{outils_m3[0]}",
            "other_custom": f"opsys_m3__{outils_m3[1]}",
        },
    }


def test_agent_public_autorise_son_catalogue_dans_le_sandbox(configuration_politique_sandbox):
    tools = configuration_politique_sandbox["config"]["agents"]["entries"]["m01-front-office"]["tools"]
    assert tools["allow"] == ["opsys_m1__*"]
    assert tools.get("sandbox", {}).get("tools", {}).get("allow") == ["opsys_m1__*"]
    assert {
        "message", "group:messaging", "opsys_m2__*", "opsys_context_*__*", "opsys_runtime_*__*",
    } <= set(tools["deny"])


def test_agent_interne_ajoute_son_catalogue_sans_remplacer_les_outils_core(configuration_politique_sandbox):
    tools = configuration_politique_sandbox["config"]["agents"]["entries"]["m02-revenue-crm"]["tools"]
    assert "allow" not in tools
    assert tools.get("sandbox", {}).get("tools", {}).get("alsoAllow") == ["opsys_m2__*"]
    assert "allow" not in tools["sandbox"]["tools"]
    assert "opsys_m1__*" in tools["deny"]


def test_profil_vide_refuse_tout_meme_si_allow_vide_est_ouvert(configuration_politique_sandbox):
    tools = configuration_politique_sandbox["config"]["agents"]["entries"]["opsys-agent-m03-sans-outils"]["tools"]
    assert tools["allow"] == []
    assert "*" in tools["deny"]


def test_profil_conserve_ses_droits_exacts_et_le_sandbox_obligatoire(configuration_politique_sandbox):
    config = configuration_politique_sandbox["config"]["agents"]
    agent = config["entries"]["opsys-agent-m03-limite"]
    assert agent["tools"]["allow"] == [configuration_politique_sandbox["names"]["custom"]]
    assert "opsys_m1__*" in agent["tools"]["deny"]
    assert agent["opsysIsolation"] == {"exec": "sandbox-required"}
    sandbox = config["defaults"]["sandbox"]
    assert sandbox["mode"] == "all" and sandbox["backend"] == "docker"
    assert sandbox["docker"] == {"network": "none", "readOnlyRoot": True, "capDrop": ["ALL"], "binds": []}


def test_configuration_generee_traverse_le_vrai_filtre_core(configuration_politique_sandbox, tmp_path):
    root = Path(__file__).resolve().parents[1]
    tsx = root / "core/node_modules/.bin/tsx"
    if not tsx.is_file():
        pytest.skip("validation croisée non exécutée : dépendances TypeScript du core absentes")
    payload = tmp_path / "politique-sandbox.json"
    payload.write_text(json.dumps(configuration_politique_sandbox), encoding="utf-8")
    result = subprocess.run(
        [str(tsx), str(root / "tests/fixtures/check_core_department_tool_policy.ts"), str(payload)],
        cwd=root / "core", capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
