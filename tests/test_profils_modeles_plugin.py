from __future__ import annotations

import json

import pytest
import yaml

from opsys import jetons, modeles
from opsys.hermes_plugin import PluginOpsys, departement_courant, register
from opsys.profils import generer_distribution

PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}


def test_paliers_valides_et_persistes(opsys_home):
    fichier = modeles.enregistrer_paliers(PALIERS)
    assert fichier == opsys_home / "paliers.yaml"
    assert modeles.charger_paliers() == PALIERS
    assert modeles.section_modele_hermes("local", PALIERS) == {
        "provider": "custom", "default": "qwen3:8b", "base_url": "http://ollama:11434/v1"}


@pytest.mark.parametrize(
    ("nom", "conf", "message"),
    [
        ("geant", {"provider": "x", "model": "y"}, "palier inconnu"),
        ("local", {"provider": "custom", "model": "y"}, "exige base_url"),
        ("rapide", {"provider": "x"}, "requis"),
        ("rapide", {"provider": "x", "model": "y", "base_url": "ftp://x"}, "URL http"),
    ],
)
def test_paliers_invalides(nom, conf, message):
    with pytest.raises(ValueError, match=message):
        modeles.valider_palier(nom, conf)


def test_palier_non_configure_explique_quoi_faire():
    with pytest.raises(ValueError, match="dashboard"):
        modeles.section_modele_hermes("fort", PALIERS)


def test_distribution_generee(departements_demo, tmp_path):
    dossier = generer_distribution(departements_demo["m09-demo"], tmp_path, PALIERS, "opsys-mcp")
    assert dossier == tmp_path / "m09-demo"
    manifeste = yaml.safe_load((dossier / "distribution.yaml").read_text(encoding="utf-8"))
    assert manifeste["name"] == "m09-demo"
    config = yaml.safe_load((dossier / "config.yaml").read_text(encoding="utf-8"))
    assert config["model"] == {"provider": "anthropic", "default": "claude-sonnet-5"}
    assert config["mcp_servers"]["opsys"] == {"command": "opsys-mcp", "args": ["--departement", "m09-demo"]}
    assert config["plugins"]["enabled"] == ["opsys"]
    soul = (dossier / "SOUL.md").read_text(encoding="utf-8")
    assert "`m9_payer` (T3)" in soul and "Règles OPSYS" in soul
    jobs = json.loads((dossier / "cron" / "jobs.json").read_text(encoding="utf-8"))["jobs"]
    assert jobs == [{"id": "m09-demo-digest", "name": "M9 · digest", "prompt": "Résume la journée.",
                     "schedule": {"kind": "cron", "expr": "0 7 * * 1-5", "display": "0 7 * * 1-5"},
                     "enabled": False}]
    assert (dossier / "skills" / "procedure-demo" / "SKILL.md").is_file()


def test_departement_courant():
    assert departement_courant({"OPSYS_DEPARTEMENT": "m03-estimation"}) == "m03-estimation"
    assert departement_courant({"HERMES_HOME": "/opt/data/profiles/m01-front-office"}) == "m01-front-office"
    assert departement_courant({"HERMES_HOME": "/opt/data"}) == "direction"


class _Ctx:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, nom, rappel):
        self.hooks[nom] = rappel


def test_register_branche_les_hooks(monkeypatch, opsys_home, racine_demo):
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine_demo))
    monkeypatch.setenv("OPSYS_DEPARTEMENT", "m09-demo")
    ctx = _Ctx()
    register(ctx)
    assert set(ctx.hooks) == {"post_api_request", "post_auxiliary_call", "pre_llm_call", "transform_tool_result"}


def test_hooks_comptent_alertent_et_tronquent(departements_demo, session):
    plugin = PluginOpsys("m09-demo", departements_demo, session, limite_sortie=500)
    assert plugin.pre_llm_call(session_id="s") is None
    plugin.post_api_request(model="claude-sonnet-5", usage={"input_tokens": 700, "output_tokens": 150})
    plugin.post_auxiliary_call(model="aux", usage=None)  # sans usage : ignoré
    notice = plugin.pre_llm_call(session_id="s")
    assert "85.0 %" in notice["context"]
    plugin.post_api_request(model="claude-sonnet-5", usage={"input_tokens": 200})
    assert "ÉPUISÉ" in plugin.pre_llm_call(session_id="s")["context"]
    with session() as cnx:
        assert jetons.consommation(cnx, "m09-demo", *[__import__("datetime").date.today()] * 2) == 1050

    long = "x" * 2000
    tronque = plugin.transform_tool_result(tool_name="web_extract", result=long)
    assert tronque is not None and len(tronque) < 800
    assert plugin.transform_tool_result(tool_name="web_extract", result="court") is None
    assert plugin.transform_tool_result(tool_name="mcp_opsys_m9_gros_rapport", result=long) is None
